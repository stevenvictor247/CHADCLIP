"""Stale-check for the approved-clip queue: free checks in code, one Approvals card, bulk keep or drop.

Before a queued clip posts, it must still be worth posting: not a duplicate of a clip already posted or ahead of it in
the queue, its creator still on the list, its caption still valid, and not sitting in the queue for over 3 days.
Clips that fail are held (publish skips them) and listed on ONE card for Steven to keep or drop. Kept clips are never
flagged again, so the card can't become extra approval work.
"""

from datetime import datetime, timezone

from . import approvals, db

STALE_DAYS = 3
KIND = "stale_clips"


def _age_days(clip: dict) -> float:
    ts = clip.get("approved_at") or clip.get("created_at")
    try:
        t = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return 0.0
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 86400


def _overlaps(a: dict, b: dict) -> bool:
    return bool(a["source_url"]) and a["source_url"] == b["source_url"] \
        and a["start_s"] < b["end_s"] and b["start_s"] < a["end_s"]


def reasons(clip: dict, ahead: list[dict]) -> list[str]:
    """Why this approved clip should be held, in plain words. `ahead` = clips that already posted or are earlier in the queue."""
    out = []
    age = _age_days(clip)
    if age > STALE_DAYS:
        out.append(f"waiting {age:.0f} days in the queue")
    dup = next((o for o in ahead if _overlaps(clip, o)), None)
    if dup:
        out.append(f"same moment as clip #{dup['id']} (same source video and timestamp)")
    if clip.get("creator"):
        from .agents.chad.sources import find_creator
        if not find_creator(clip["creator"]):
            out.append(f"{clip['creator']} is no longer on the creator list")
    caption = (clip.get("caption") or "").strip()
    if len(caption.split("Credit:")[0].strip()) < 5 or "Credit:" not in caption:
        out.append("caption is empty or has no credit")
    return out


def check() -> dict:
    """Flag stale approved clips and raise one Approvals card for them. Returns {flagged: ids, approval_id}."""
    posted = db.rows("SELECT id, source_url, start_s, end_s FROM clips WHERE status = 'posted'")
    queue = db.rows("SELECT * FROM clips WHERE status = 'approved' ORDER BY id")
    ahead, found = list(posted), []
    for clip in queue:
        if clip.get("stale_state") == "kept":
            ahead.append(clip)
            continue
        why = reasons(clip, ahead)
        if why:
            found.append((clip, why))
            if clip.get("stale_state") != "flagged":
                db.execute("UPDATE clips SET stale_state = 'flagged' WHERE id = ?", clip["id"])
        else:
            if clip.get("stale_state") == "flagged":   # fixed since (e.g. caption edited): back in the queue
                db.execute("UPDATE clips SET stale_state = NULL WHERE id = ?", clip["id"])
            ahead.append(clip)
    # held clips are not "ahead": a flagged duplicate must not make its twin look like the duplicate
    ids = [c["id"] for c, _ in found]
    open_card = db.rows("SELECT id, payload FROM approvals WHERE kind = ? AND status = 'pending'", KIND)
    if not ids:
        return {"flagged": [], "approval_id": None}
    if open_card:
        import json
        old = set(json.loads(open_card[0]["payload"]).get("clip_ids", []))
        if set(ids) <= old:
            return {"flagged": ids, "approval_id": open_card[0]["id"]}
        db.execute("UPDATE approvals SET status = 'rejected', decided_at = ? WHERE id = ?", db.now(), open_card[0]["id"])
    lines = [f"#{c['id']} {c.get('title') or 'untitled'}: " + "; ".join(w) for c, w in found[:15]]
    if len(found) > 15:
        lines.append(f"…and {len(found) - 15} more")
    aid = approvals.request(
        "Chad", KIND, f"{len(ids)} queued clip{'s' if len(ids) != 1 else ''} to keep or drop",
        "These approved clips look stale. They are on hold and won't post until you decide.\n\n" + "\n".join(lines),
        {"clip_ids": ids}, yes="Keep all", no="Drop all")
    return {"flagged": ids, "approval_id": aid}


def _decided(payload: dict, decision: str) -> str:
    ids = payload.get("clip_ids", [])
    marks = ",".join("?" * len(ids))
    if not ids:
        return "Nothing to do."
    if decision == "approve":
        db.execute(f"UPDATE clips SET stale_state = 'kept' WHERE status = 'approved' AND id IN ({marks})", *ids)
        return f"Kept {len(ids)} clips; they post as normal."
    db.execute(f"UPDATE clips SET status = 'rejected', stale_state = NULL WHERE status = 'approved' AND id IN ({marks})", *ids)
    return f"Dropped {len(ids)} clips."


approvals.HANDLERS[KIND] = _decided
