"""Gate: checks each waiting clip against Steven's past approvals and rejections, with plain rules and no Claude.

A clip's score (0-100) starts from how often Steven approved that creator's clips (smoothed toward his overall rate, so
a creator with one clip doesn't swing it), then moves a little for its length, its caption and the words in its title.
Clips under HOLD_BELOW go to the Likely rejects tab; the rest are sorted best first. Gate never approves, rejects, posts
or sends anything: Steven still decides every clip. While there is little history, nothing is held and no accuracy is
counted.
"""

import re
from datetime import datetime, timedelta, timezone

from . import db

HOLD_BELOW = 35         # score under this goes to Likely rejects
MIN_HISTORY = 10        # decided clips needed overall before Gate holds anything
MIN_CREATOR = 3         # decided clips needed for that creator before Gate holds their clips
SMOOTHING = 4           # a creator's rate counts as this many clips of Steven's overall rate
SECONDS_PER_CLIP = 30   # review time saved by each correctly held clip
HOURLY_RATE = 15.0      # what Steven's time is counted at
ACCURACY_DAYS = 7
DECIDED = ("approved", "posted", "rejected")


def _ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def _approved(status: str) -> bool:
    return status in ("approved", "posted")


def _length(c: dict) -> float:
    return (c.get("end_s") or 0) - (c.get("start_s") or 0)


def _words(text: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z']+", (text or "").lower()) if len(w) > 3}


def history(exclude_id: int | None = None) -> list[dict]:
    return db.rows(f"SELECT id, creator, start_s, end_s, title, status FROM clips WHERE status IN "
                   f"({', '.join('?' for _ in DECIDED)}) AND id != ?", *DECIDED, exclude_id or 0)


def score_clip(clip: dict, hist: list[dict]) -> dict:
    """{score, why, learning, held} for one clip against past decisions (`hist` must not include the clip itself)."""
    overall = (sum(_approved(h["status"]) for h in hist) / len(hist)) if hist else 0.5
    creator = (clip.get("creator") or "").lower()
    mine = [h for h in hist if (h["creator"] or "").lower() == creator]
    liked = sum(_approved(h["status"]) for h in mine)
    p = (liked + SMOOTHING * overall) / (len(mine) + SMOOTHING)
    why = [f"{liked} of {len(mine)} past {clip.get('creator') or 'unknown'} clips approved" if mine
           else "no history for this creator yet"]

    ok, bad = [_length(h) for h in mine if _approved(h["status"])], [_length(h) for h in mine if not _approved(h["status"])]
    if len(ok) >= 2 and len(bad) >= 2:
        here = _length(clip)
        if abs(here - sum(ok) / len(ok)) < abs(here - sum(bad) / len(bad)):
            p += 0.08
            why.append("length like the ones you approve")
        else:
            p -= 0.08
            why.append("length like the ones you reject")

    caption = (clip.get("caption") or "").split("Credit:")[0].strip()
    if len(caption.split()) < 4:
        p -= 0.1
        why.append("very short caption")

    good = set().union(*[_words(h["title"]) for h in mine if _approved(h["status"])]) if mine else set()
    poor = set().union(*[_words(h["title"]) for h in mine if not _approved(h["status"])]) if mine else set()
    title = _words(clip.get("title"))
    up, down = len(title & good - poor), len(title & poor - good)
    if up != down:
        p += 0.06 if up > down else -0.06
        why.append("title words you " + ("approved before" if up > down else "rejected before"))

    score = round(100 * min(1.0, max(0.0, p)))
    learning = len(hist) < MIN_HISTORY
    held = None if learning else int(score < HOLD_BELOW and len(mine) >= MIN_CREATOR)
    return {"score": score, "why": "; ".join(why), "learning": learning, "held": held}


def score_pending() -> list[dict]:
    """Score every waiting clip, save the prediction on the clip (so accuracy can be checked once Steven decides),
    and return the clips best first, each with gate_score, gate_why and gate_held."""
    clips = db.rows("SELECT * FROM clips WHERE status = 'pending_approval' ORDER BY id")
    hist = history()
    for c in clips:
        r = score_clip(c, hist)
        if (c.get("gate_score"), c.get("gate_why"), c.get("gate_held")) != (r["score"], r["why"], r["held"]):
            db.execute("UPDATE clips SET gate_score = ?, gate_why = ?, gate_held = ? WHERE id = ?",
                       r["score"], r["why"], r["held"], c["id"])
        c["gate_score"], c["gate_why"], c["gate_held"] = r["score"], r["why"], r["held"]
    return sorted(clips, key=lambda c: (-c["gate_score"], -(c["score"] or 0), c["id"]))


def accuracy(days: float = ACCURACY_DAYS) -> dict:
    """How often a hold matched Steven's choice, over clips he decided in the last `days` that Gate called."""
    rows = db.rows("SELECT gate_held, status FROM clips WHERE gate_held IS NOT NULL AND decided_at >= ? "
                   "AND status IN ('approved', 'posted', 'rejected')", _ago(days))
    right = sum(bool(r["gate_held"]) == (not _approved(r["status"])) for r in rows)
    held_right = sum(1 for r in rows if r["gate_held"] and not _approved(r["status"]))
    return {"checked": len(rows), "right": right, "percent": round(100 * right / len(rows)) if rows else None,
            "time_saved_usd": round(held_right * SECONDS_PER_CLIP / 3600 * HOURLY_RATE, 2)}


def summary() -> dict:
    hist = history()
    clips = score_pending()
    return {"history": len(hist), "learning": len(hist) < MIN_HISTORY, "hold_below": HOLD_BELOW,
            "held": sum(1 for c in clips if c["gate_held"]), "accuracy": accuracy()}


def report_line() -> str:
    a = accuracy()
    if a["percent"] is None:
        return "Gate: not enough decided clips yet to measure accuracy."
    return (f"Gate this week: {a['percent']}% right on {a['checked']} clips you decided; "
            f"about ${a['time_saved_usd']:.2f} of your time saved.")


def run() -> str:
    clips = score_pending()
    held = sum(1 for c in clips if c["gate_held"])
    out = f"Scored {len(clips)} waiting clips; {held} held as likely rejects."
    if len(history()) < MIN_HISTORY:
        out += f" Still learning (needs {MIN_HISTORY} decided clips); nothing is held yet."
    recent = db.rows("SELECT 1 FROM activity WHERE agent = 'Gate' AND message LIKE 'Gate this week%' AND created_at >= ? "
                     "LIMIT 1", _ago(7))
    if not recent and accuracy()["percent"] is not None:
        db.log("Gate", report_line())   # the weekly accuracy number, on the activity feed
    db.log("Gate", out)
    return out
