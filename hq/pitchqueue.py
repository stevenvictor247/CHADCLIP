"""Queue's rules: how many pitches went out today, which drafts come next, and whether to nudge Steven.

Plain code, no Claude. Drafts are ordered by Pitch's lead score, so chasing the daily goal never promotes a weak lead:
a low score always sorts last. Nothing here sends anything; "mark sent" only records that Steven sent a draft himself.
"""

import os
from datetime import datetime, timedelta, timezone

from . import db, relay
from .config import DATA_DIR

ALERT_PATH = DATA_DIR / "queue" / "alerted.txt"   # the local date of the last "too few ready" text
RATE_AFTER_DAYS = 7                                # the sent-to-reply rate shows once the first send is this old
REPLIED = ("replied", "client")


def goal() -> int:
    return int(os.getenv("HQ_QUEUE_GOAL", "") or 10)


def alert_hour() -> int:
    return int(os.getenv("HQ_QUEUE_ALERT_HOUR", "") or 17)   # local hour of the "fewer than the goal" text


def _local_day(iso: str | None) -> str | None:
    if not iso:
        return None
    return datetime.fromisoformat(iso).astimezone().date().isoformat()


def _today() -> str:
    return datetime.now().astimezone().date().isoformat()


def _sent_times() -> dict[int, str]:
    """lead id -> when it was sent, from emails HQ sent and pitches marked sent by hand."""
    out = {}
    for table in ("pitch_sent", "queue_sent"):
        for r in db.rows(f"SELECT lead_id, sent_at FROM {table}"):
            out[r["lead_id"]] = min(r["sent_at"], out.get(r["lead_id"], r["sent_at"]))
    return out


def counts() -> dict:
    today = _today()
    drafted = sum(1 for r in db.rows("SELECT created_at FROM leads WHERE pitch IS NOT NULL")
                  if _local_day(r["created_at"]) == today)
    approved = sum(1 for r in db.rows("SELECT decided_at FROM approvals WHERE kind = 'pitch' AND status = 'approved'")
                   if _local_day(r["decided_at"]) == today)
    sent = sum(1 for t in _sent_times().values() if _local_day(t) == today)
    ready = db.rows("SELECT COUNT(*) n FROM leads WHERE status = 'drafted'")[0]["n"]
    return {"goal": goal(), "drafted": drafted, "approved": approved, "sent": sent, "ready": ready}


def ranked(limit: int | None = None) -> list[dict]:
    """Unsent drafts, best fit first. Unscored leads sort after every scored one; ties go to the oldest draft."""
    rows = db.rows("SELECT id, name, platform, handle, contact, score, score_why, pitch, created_at FROM leads "
                   "WHERE status = 'drafted' AND pitch IS NOT NULL "
                   "ORDER BY score IS NULL, score DESC, created_at, id")
    return rows[:limit] if limit else rows


def reply_rate() -> dict | None:
    """Sent-to-reply rate, only once the first pitch is a week old (before that it's noise)."""
    sent = _sent_times()
    if not sent:
        return None
    first = datetime.fromisoformat(min(sent.values()))
    if datetime.now(timezone.utc) - first < timedelta(days=RATE_AFTER_DAYS):
        return None
    ids = list(sent)
    marks = ",".join("?" * len(ids))
    replied = db.rows(f"SELECT COUNT(*) n FROM leads WHERE id IN ({marks}) AND status IN ('replied', 'client')", *ids)[0]["n"]
    return {"sent": len(ids), "replied": replied, "rate": round(100 * replied / len(ids), 1)}


def state() -> dict:
    c = counts()
    todays = ranked(max(c["goal"] - c["sent"], 0))
    return {**c, "short_by": max(c["goal"] - c["sent"] - c["ready"], 0), "drafts": todays, "reply_rate": reply_rate()}


def mark_sent(lead_id: int) -> str:
    """Steven sent this draft himself. Same effect as tapping 'I'll send it', and it closes the waiting approval card."""
    from .agents.pitch.agent import settings, _iso
    rows = db.rows("SELECT * FROM leads WHERE id = ?", lead_id)
    if not rows:
        raise KeyError(lead_id)
    lead = rows[0]
    if lead["status"] != "drafted":
        return f"{lead['name']} is already {lead['status']}."
    days = float(settings().get("followup_days", 4))
    with db.connect() as c:
        if c.execute("UPDATE leads SET status = 'pitched', followup_at = ?, updated_at = ? WHERE id = ? AND status = 'drafted'",
                     (_iso(days), db.now(), lead_id)).rowcount != 1:
            return f"{lead['name']} is already being handled."
        c.execute("INSERT OR IGNORE INTO queue_sent (lead_id, sent_at) VALUES (?, ?)", (lead_id, db.now()))
    for a in db.rows("SELECT id, payload FROM approvals WHERE kind = 'pitch' AND status = 'pending'"):
        if f'"lead_id": {lead_id},' in a["payload"] + "," or f'"lead_id": {lead_id}}}' in a["payload"]:
            db.execute("UPDATE approvals SET status = 'approved', decided_at = ? WHERE id = ?", db.now(), a["id"])
    db.log("Queue", f"{lead['name']} marked sent")
    return f"Marked {lead['name']} as sent. I'll remind you to follow up in {days:g} days."


def alert_due() -> bool:
    if datetime.now().hour < alert_hour():
        return False
    if ALERT_PATH.exists() and ALERT_PATH.read_text().strip() == _today():
        return False
    c = counts()
    return c["sent"] + c["ready"] < c["goal"]


def check_and_alert() -> str:
    if not alert_due():
        return "Quota fine or already texted today."
    c = counts()
    short = c["goal"] - c["sent"] - c["ready"]
    text = (f"Queue: {c['sent']} sent and {c['ready']} ready today, {short} short of your {c['goal']} a day. "
            "Pitch needs to find more leads.")
    relay.notify(text)
    ALERT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALERT_PATH.write_text(_today())
    return text
