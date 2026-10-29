"""Trim: ranks the approved-clip queue by freshness and the creator's results, and flags dead clips for a one-tap drop.

Rules in code, no Claude, no cost. The score is stored on each queued clip (clips.trim_score) and publish posts the
highest score first; clips Trim has not scored keep the old newest-first order. Steven's OK is asked for the very first
reorder; after that Trim reorders by itself and every reorder can be undone. Trim never posts, sends or spends: its
only other action is a "Drop all / Keep all" card for clips waiting more than a week.
"""

import json
from datetime import datetime, timedelta, timezone

from . import approvals, db
from .config import DATA_DIR
from .stalecheck import _age_days

DROP_DAYS = 7                  # queued longer than this: offered for a one-tap drop
FRESH_HALF_LIFE_DAYS = 3.0     # a clip loses half its freshness every 3 days in the queue
RESULTS_WINDOW_DAYS = 14       # how far back creators' view results count
TRUST_POSTS = 3                # posts needed before a creator's views count in full; fewer blends toward "unknown"
DEAD_AVG_VIEWS = 5             # a creator averaging fewer views than this (with enough posts) is "dead"
FRESH_WEIGHT, RESULTS_WEIGHT = 0.6, 0.4
KIND_FIRST, KIND_DROP = "trim_first", "trim_drop"
STATE_PATH = DATA_DIR / "trim" / "state.json"


def _state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state), encoding="utf-8")


def creator_results() -> dict[str, dict]:
    """Tally's numbers per creator: {creator: {posts, avg_views}} from recent posted clips."""
    since = (datetime.now(timezone.utc) - timedelta(days=RESULTS_WINDOW_DAYS)).isoformat(timespec="seconds")
    rows = db.rows("SELECT c.creator, COUNT(*) posts, AVG(p.views) avg_views FROM posts p JOIN clips c ON c.id = p.clip_id "
                   "WHERE p.status = 'posted' AND p.views IS NOT NULL AND p.created_at >= ? GROUP BY c.creator", since)
    return {r["creator"]: {"posts": r["posts"], "avg_views": r["avg_views"] or 0} for r in rows}


def results_score(creator: str | None, results: dict) -> float:
    """0..1: how well this creator's clips did compared with the best creator. Few posts blend toward 0.5 (unknown),
    because a score from 2 views is a guess."""
    r = results.get(creator)
    if not r:
        return 0.5
    best = max(x["avg_views"] for x in results.values()) or 0
    raw = r["avg_views"] / best if best > 0 else 0.5
    trust = min(1.0, r["posts"] / TRUST_POSTS)
    return trust * raw + (1 - trust) * 0.5


def freshness(age_days: float) -> float:
    return 0.5 ** (max(age_days, 0) / FRESH_HALF_LIFE_DAYS)


def score(clip: dict, results: dict) -> float:
    return round(FRESH_WEIGHT * freshness(_age_days(clip)) + RESULTS_WEIGHT * results_score(clip.get("creator"), results), 4)


def is_dead(clip: dict, results: dict) -> bool:
    r = results.get(clip.get("creator"))
    return bool(r) and r["posts"] >= TRUST_POSTS and r["avg_views"] < DEAD_AVG_VIEWS


def queue() -> list[dict]:
    return db.rows("SELECT * FROM clips WHERE status = 'approved' AND COALESCE(stale_state, '') != 'flagged' ORDER BY id")


def ranking() -> list[dict]:
    """The queue in the order Trim would post it, each with its score. Nothing is changed."""
    results = creator_results()
    out = [{"id": c["id"], "title": c.get("title"), "creator": c.get("creator"), "age_days": round(_age_days(c), 1),
            "score": score(c, results), "dead": is_dead(c, results), "old_score": c.get("trim_score")}
           for c in queue()]
    return sorted(out, key=lambda x: (-x["score"], -x["id"]))


def apply(order: list[dict]) -> int:
    """Store the scores (publish posts the highest first) and remember the old ones so Undo can put them back."""
    previous = {str(o["id"]): o["old_score"] for o in order}
    for o in order:
        db.execute("UPDATE clips SET trim_score = ? WHERE id = ?", o["score"], o["id"])
    state = _state()
    state["undo"] = previous
    _save(state)
    db.log("Trim", f"Reordered {len(order)} queued clips by freshness and results.")
    return len(order)


def undo() -> str:
    state = _state()
    previous = state.pop("undo", None)
    if previous is None:
        return "Nothing to undo."
    for cid, old in previous.items():
        db.execute("UPDATE clips SET trim_score = ? WHERE id = ?", old, int(cid))
    _save(state)
    db.log("Trim", f"Undid the last reorder ({len(previous)} clips back where they were).")
    return f"Put {len(previous)} clips back in their old order."


def _first_decided(payload: dict, decision: str) -> str:
    state = _state()
    if decision != "approve":
        state["declined_at"] = db.now()
        _save(state)
        return "OK, Trim leaves the queue order alone. It will ask again only if you press Reorder."
    state["approved"] = True
    _save(state)
    return f"Trim will reorder the queue ({apply(ranking())} clips now) and keep it ordered. You can undo any reorder."


def _drop_decided(payload: dict, decision: str) -> str:
    ids = payload.get("clip_ids", [])
    if not ids:
        return "Nothing to do."
    marks = ",".join("?" * len(ids))
    if decision == "approve":
        db.execute(f"UPDATE clips SET stale_state = 'kept' WHERE status = 'approved' AND id IN ({marks})", *ids)
        return f"Kept {len(ids)} clips."
    db.execute(f"UPDATE clips SET status = 'rejected', stale_state = NULL WHERE status = 'approved' AND id IN ({marks})", *ids)
    return f"Dropped {len(ids)} clips."


approvals.HANDLERS[KIND_FIRST] = _first_decided
approvals.HANDLERS[KIND_DROP] = _drop_decided


def _open_card(kind: str) -> dict | None:
    rows = db.rows("SELECT id, payload FROM approvals WHERE kind = ? AND status = 'pending'", kind)
    return rows[0] if rows else None


def flag_old(order: list[dict]) -> int | None:
    """One card for clips queued over DROP_DAYS (kept ones are never flagged again). Returns the approval id."""
    kept = {r["id"] for r in db.rows("SELECT id FROM clips WHERE stale_state = 'kept'")}
    old = [o for o in order if o["age_days"] > DROP_DAYS and o["id"] not in kept]
    if not old:
        return None
    ids = [o["id"] for o in old]
    card = _open_card(KIND_DROP)
    if card:
        if set(ids) <= set(json.loads(card["payload"]).get("clip_ids", [])):
            return card["id"]
        db.execute("UPDATE approvals SET status = 'rejected', decided_at = ? WHERE id = ?", db.now(), card["id"])
    lines = [f"#{o['id']} {o['title'] or 'untitled'} ({o['creator'] or '?'}): {o['age_days']:.0f} days"
             + (", creator's recent posts got almost no views" if o["dead"] else "") for o in old[:15]]
    if len(old) > 15:
        lines.append(f"…and {len(old) - 15} more")
    return approvals.request("Trim", KIND_DROP, f"{len(ids)} queued clip{'s' if len(ids) != 1 else ''} over {DROP_DAYS} days old",
                             "Still waiting to post. Keep them, or drop them.\n\n" + "\n".join(lines),
                             {"clip_ids": ids}, yes="Keep all", no="Drop all")


def run() -> str:
    order = ranking()
    if not order:
        return "The queue is empty; nothing to trim."
    flag_old(order)
    state = _state()
    moved = sum(1 for i, o in enumerate(order) if o["old_score"] is None or o["old_score"] != o["score"])
    if state.get("approved"):
        apply(order)
        return f"Reordered {len(order)} queued clips (best and freshest first); {sum(o['dead'] for o in order)} look dead."
    if not _open_card(KIND_FIRST) and not state.get("declined_at"):
        top = "\n".join(f"{i + 1}. #{o['id']} {o['title'] or 'untitled'} ({o['creator'] or '?'}, {o['age_days']:.0f}d)"
                        for i, o in enumerate(order[:8]))
        approvals.request("Trim", KIND_FIRST, f"Reorder {len(order)} queued clips, freshest and best first?",
                          "Nothing is posted or changed except the order. Next to post would be:\n\n" + top
                          + "\n\nAfter your OK Trim keeps the queue ordered itself, and every reorder can be undone.",
                          {}, yes="Reorder", no="Not now")
        return "Asked for your OK to reorder the queue the first time."
    return f"Waiting for your OK to reorder ({moved} clips would move)." if not state.get("declined_at") \
        else "You said not now; the queue order is unchanged."
