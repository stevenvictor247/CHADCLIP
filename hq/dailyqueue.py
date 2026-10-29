"""Queue: the daily send-list for Pitch. Counts today's drafts against the goal (10 new streamers a day), puts the best
fit first, and shows one screen to copy from and mark sent. Plain rules, no Claude, nothing is sent from here.

Order is Pitch's own lead score (best first), so quota pressure never lifts a weak lead above a strong one.
"""

import json
from datetime import datetime, timedelta, timezone

from . import approvals, db, relay
from .agents.pitch import agent as pitch

GOAL = 10
ALERT_HOUR = 17            # local hour after which Queue texts you if the list is short
NEUTRAL_SCORE = 5          # unscored (hand-added) leads sort as middling
REPLY_AFTER_DAYS = 7       # show the sent-to-reply rate once the first send is this old
REPLIED = ("replied", "client", "won")


def _int(cfg: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(cfg.get(key, default))))
    except (TypeError, ValueError):
        return default


def goal(cfg: dict | None = None) -> int:
    return _int(pitch.settings() if cfg is None else cfg, "queue_goal", GOAL, 1, 50)


def _day_start() -> str:
    """Midnight today, local time, as the UTC stamp the database uses."""
    local = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc).isoformat(timespec="seconds")


def _n(sql: str, *args) -> int:
    return db.rows(sql, *args)[0]["n"]


def _sent_ids(since: str | None = None) -> set[int]:
    where = " WHERE sent_at >= ?" if since else ""
    args = (since,) if since else ()
    return {r["lead_id"] for t in ("pitch_sent", "queue_sent") for r in db.rows(f"SELECT lead_id FROM {t}{where}", *args)}


def counters() -> dict:
    """Today's drafted, approved and sent pitches."""
    since = _day_start()
    return {
        "drafted": _n("SELECT COUNT(*) n FROM leads WHERE created_at >= ? AND pitch IS NOT NULL AND status != 'new'", since),
        "approved": _n("SELECT COUNT(*) n FROM approvals WHERE kind = 'pitch' AND status = 'approved' AND decided_at >= ?", since),
        "sent": len(_sent_ids(since)),
    }


def ready() -> list[dict]:
    """Drafts waiting for you, best fit first (Pitch's lead score, then bigger audience, then oldest)."""
    out = []
    for a in approvals.pending():
        if a["kind"] != "pitch":
            continue
        rows = db.rows("SELECT * FROM leads WHERE id = ? AND status = 'drafted'", a["payload"].get("lead_id", 0))
        if rows:
            out.append({**rows[0], "approval_id": a["id"]})
    out.sort(key=lambda r: (-(r["score"] if r["score"] is not None else NEUTRAL_SCORE), -(r["followers"] or 0), r["id"]))
    return out


def reply_rate() -> dict | None:
    """Sent-to-reply rate, only once the first send is a week old (earlier it would be noise)."""
    ids = _sent_ids()
    if not ids:
        return None
    marks = ",".join("?" * len(ids))
    first = min(r["sent_at"] for t in ("pitch_sent", "queue_sent") for r in db.rows(f"SELECT sent_at FROM {t}"))
    if first > (datetime.now(timezone.utc) - timedelta(days=REPLY_AFTER_DAYS)).isoformat(timespec="seconds"):
        return None
    replied = _n(f"SELECT COUNT(*) n FROM leads WHERE id IN ({marks}) AND status IN ({','.join('?' * len(REPLIED))})", *ids, *REPLIED)
    return {"sent": len(ids), "replied": replied, "percent": round(100 * replied / len(ids))}


def state() -> dict:
    cfg = pitch.settings()
    want, c = goal(cfg), counters()
    queue = ready()
    return {
        "paused": pitch.paused(cfg), "goal": want, **c, "left": max(0, want - c["sent"]),
        "ready": queue, "show": queue[:max(0, want - c["sent"])], "more": max(0, len(queue) - max(0, want - c["sent"])),
        "short_by": max(0, want - c["sent"] - len(queue)), "reply_rate": reply_rate(),
        "alert_hour": _int(cfg, "queue_alert_hour", ALERT_HOUR, 0, 23),
    }


def mark_sent(lead_id: int) -> str:
    """You sent this pitch yourself: record it, close its approval card and start the follow-up clock."""
    rows = db.rows("SELECT * FROM leads WHERE id = ?", lead_id)
    if not rows:
        raise ValueError("No such lead")
    lead = rows[0]
    if lead["status"] != "drafted":
        return f"{lead['name']} is already {lead['status']}, so nothing changed."
    days = float(pitch.settings().get("followup_days", 4))
    ts = db.now()
    with db.connect() as c:
        c.execute("UPDATE leads SET status = 'pitched', followup_at = ?, updated_at = ? WHERE id = ? AND status = 'drafted'",
                  ((datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds"), ts, lead_id))
        c.execute("INSERT OR IGNORE INTO queue_sent (lead_id, sent_at) VALUES (?, ?)", (lead_id, ts))
        for a in c.execute("SELECT id, payload FROM approvals WHERE kind = 'pitch' AND status = 'pending'").fetchall():
            if json.loads(a["payload"]).get("lead_id") == lead_id:
                c.execute("UPDATE approvals SET status = 'approved', decided_at = ? WHERE id = ?", (ts, a["id"]))
    db.log("Queue", f"Steven sent the pitch to {lead['name']}")
    return f"Marked as sent. I'll remind you to follow up in {days:g} days."


def alert_due() -> bool:
    """Time to text you, and we haven't today. Never while Pitch is paused."""
    cfg = pitch.settings()
    if pitch.paused(cfg) or not relay.enabled():
        return False
    if datetime.now().hour < _int(cfg, "queue_alert_hour", ALERT_HOUR, 0, 23):
        return False
    return not _n("SELECT COUNT(*) n FROM relay_sent WHERE kind = 'queue_alert' AND ref_id = ?", _today_key())


def _today_key() -> int:
    return int(datetime.now().strftime("%Y%m%d"))


def run() -> str:
    s = state()
    if s["paused"]:
        return "Pitch paused. Nothing to queue and no texts sent."
    line = f"{s['sent']} of {s['goal']} sent today, {len(s['ready'])} ready."
    if alert_due():
        db.execute("INSERT OR IGNORE INTO relay_sent (kind, ref_id, created_at) VALUES ('queue_alert', ?, ?)", _today_key(), db.now())
        if s["short_by"] > 0:
            relay.notify(f"Queue: {line} You're {s['short_by']} short of today's {s['goal']} pitches. Open HQ > Pitch > Today's {s['goal']}.")
            return line + f" Texted you: {s['short_by']} short."
    return line
