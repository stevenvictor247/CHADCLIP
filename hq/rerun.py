"""Rerun: second tries for pitched leads that went quiet. Plain rules choose who and when; Claude only writes the short
draft (a rule-based template stands in when Claude is off). Nothing is sent from here: Steven copies each draft and taps
Mark sent. Two tries per lead at most, then the lead is marked dead, so nobody is chased more than twice.
"""

from datetime import datetime, timedelta, timezone

from . import db, llm
from .agents.pitch import agent as pitch, mailer
from .config import model_for

MAX_TRIES = 2
DAILY = 5            # most second tries drafted (and so reviewed) in a day
CLIP_IDEAS = [
    "a 30-second highlight of your funniest moment from this week",
    "a short reel of your best clutch play, cut for TikTok",
    "a captioned clip of your most quotable line, made for Shorts",
    "a quick fails-and-fun montage from your last few streams",
    "a reaction moment from your chat, trimmed to a punchy vertical clip",
    "a 'best of the month' teaser that points viewers back to your stream",
]

SYSTEM = """You write a short second message from Steven, a clipper, to a streamer or podcaster he emailed before and who
has not replied. Exactly 3 short lines, friendly and plain, no guilt, no pressure, no pretending they saw the first email.
Line 1: one specific hook about them from the facts given, without inventing anything. Line 2: offer the one clip idea you
are given, as a free sample. Line 3: one easy question they can answer in a few words. Then the opt-out line you are given,
word for word, then the sender name. Never mention a price."""

SCHEMA = {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"], "additionalProperties": False}


def _int(cfg: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(cfg.get(key, default))))
    except (TypeError, ValueError):
        return default


def _iso(days: float = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def _day_start() -> str:
    local = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc).isoformat(timespec="seconds")


def daily(cfg: dict | None = None) -> int:
    return _int(pitch.settings() if cfg is None else cfg, "rerun_daily", DAILY, 1, 20)


def quiet_days(cfg: dict | None = None) -> int:
    return _int(pitch.settings() if cfg is None else cfg, "nudge_quiet_days", 5, 1, 60)


def _pitched_at(lead: dict) -> str:
    rows = db.rows("SELECT sent_at FROM pitch_sent WHERE lead_id = ? UNION SELECT sent_at FROM queue_sent WHERE lead_id = ?",
                   lead["id"], lead["id"])
    return min((r["sent_at"] for r in rows), default=lead["updated_at"])


def slots(cfg: dict | None = None) -> int:
    """How many more drafts may be made now: under the daily cap, and never more waiting for review than the cap."""
    cap = daily(cfg)
    today = db.rows("SELECT COUNT(*) n FROM rerun_tries WHERE created_at >= ?", _day_start())[0]["n"]
    waiting = db.rows("SELECT COUNT(*) n FROM rerun_tries WHERE status = 'drafted'")[0]["n"]
    return max(0, min(cap - today, cap - waiting))


def candidates(cfg: dict | None = None) -> list[dict]:
    """Quiet pitched leads worth a try, best first: most followers, then the oldest pitch. Each carries `try_n` and `idea`."""
    cfg = pitch.settings() if cfg is None else cfg
    window = _iso(quiet_days(cfg))
    out = []
    for lead in db.rows("SELECT l.* FROM leads l JOIN nudge_state n ON n.lead_id = l.id "
                        "WHERE l.status = 'pitched' AND n.state = 'quiet' ORDER BY l.id"):
        to = mailer.address_in(lead["contact"])
        if not to or mailer.blocked(to):
            continue
        tries = db.rows("SELECT * FROM rerun_tries WHERE lead_id = ? ORDER BY n", lead["id"])
        if len(tries) >= MAX_TRIES or any(t["status"] == "drafted" for t in tries):
            continue
        if tries and (tries[-1]["decided_at"] or "") > window:
            continue   # give the last try a quiet window before the next one
        if db.rows("SELECT 1 FROM approvals WHERE kind = 'followup' AND status = 'pending' AND payload LIKE ?",
                   f'%"lead_id": {lead["id"]},%'):
            continue   # Pitch's own follow-up is already waiting for you
        lead["sent_at"] = _pitched_at(lead)
        lead["try_n"] = len(tries) + 1
        lead["idea"] = pick_idea(lead["id"], [t["idea"] for t in tries])
        out.append(lead)
    out.sort(key=lambda l: (-(l["followers"] or 0), l["sent_at"], l["id"]))
    return out


def pick_idea(lead_id: int, used: list[str]) -> str:
    """A clip idea this lead has not been offered, rotating by lead so neighbours in the list get different ones."""
    for i in range(len(CLIP_IDEAS)):
        idea = CLIP_IDEAS[(lead_id + i) % len(CLIP_IDEAS)]
        if idea not in used:
            return idea
    return CLIP_IDEAS[lead_id % len(CLIP_IDEAS)]


def retire() -> int:
    """Two tries made and a quiet window passed with no answer: mark the lead dead. Never chased a third time."""
    window, n = _iso(quiet_days()), 0
    for lead in db.rows("SELECT * FROM leads WHERE status = 'pitched'"):
        tries = db.rows("SELECT * FROM rerun_tries WHERE lead_id = ?", lead["id"])
        if len(tries) >= MAX_TRIES and all(t["status"] != "drafted" and (t["decided_at"] or "") <= window for t in tries):
            pitch.set_status(lead["id"], "dead", "No reply after two second tries (Rerun)")
            db.log("Rerun", f"{lead['name']} marked dead after two tries")
            n += 1
    return n


def template(lead: dict, cfg: dict) -> str:
    opt, sender = cfg.get("opt_out_line") or "", cfg.get("sender_name") or "Steven"
    lines = [f"Hi {lead['name']}, I emailed a few days ago about clipping your streams.",
             f"This time I'd love to send you a free sample: {lead['idea']}.",
             "Want me to send it over?", "", opt, sender]
    return "\n".join(l for i, l in enumerate(lines) if l or i == 3)


def write(lead: dict, cfg: dict) -> str:
    """Claude writes the 3 lines; any trouble falls back to the template, so a draft is always made."""
    if not llm.HAS_LLM:
        return template(lead, cfg)
    facts = (f"Creator: {lead['name']} ({lead['platform']}, {lead['followers'] or 'unknown'} followers)\nFirst email:\n{lead['pitch']}\n"
             f"Clip idea to offer: {lead['idea']}\nOpt-out line: {cfg.get('opt_out_line')}\nSign as: {cfg.get('sender_name')}")
    try:
        message = llm.ask_json(model_for("pitch"), SYSTEM, facts, SCHEMA, effort="low", agent="Rerun")["message"].strip()
    except Exception:
        return template(lead, cfg)
    opt = cfg.get("opt_out_line")
    if opt and opt not in message:
        message += f"\n\n{opt}"
    return message or template(lead, cfg)


def draft(lead: dict, cfg: dict) -> int:
    subject = mailer.split_pitch(lead["pitch"])[0]
    subject = subject if subject.lower().startswith("re:") else "Re: " + subject
    tid = db.execute("INSERT INTO rerun_tries (lead_id, n, idea, subject, message, status, created_at) VALUES (?, ?, ?, ?, ?, 'drafted', ?)",
                     lead["id"], lead["try_n"], lead["idea"], subject, write(lead, cfg), db.now())
    db.log("Rerun", f"Second try {lead['try_n']} for {lead['name']} is ready to send")
    return tid


def decide(try_id: int, status: str) -> str:
    """Steven sent it himself (sent) or passed on it (skipped). Either way the try is used up."""
    rows = db.rows("SELECT t.*, l.name FROM rerun_tries t JOIN leads l ON l.id = t.lead_id WHERE t.id = ?", try_id)
    if not rows:
        raise ValueError("No such second try")
    t = rows[0]
    if t["status"] != "drafted":
        return f"That one is already {t['status']}."
    db.execute("UPDATE rerun_tries SET status = ?, decided_at = ? WHERE id = ? AND status = 'drafted'", status, db.now(), try_id)
    db.log("Steven", f"{'Sent' if status == 'sent' else 'Skipped'} second try {t['n']} to {t['name']}")
    return "Marked as sent." if status == "sent" else "Skipped."


def worth_running() -> bool:
    """A free look before any round: something to draft, or a lead whose two tries are used up and can be retired."""
    if pitch.paused():
        return False
    spent = db.rows("SELECT 1 FROM rerun_tries t JOIN leads l ON l.id = t.lead_id WHERE l.status = 'pitched' "
                    "GROUP BY t.lead_id HAVING COUNT(*) >= ?", MAX_TRIES)
    return bool(spent) or bool(slots() and candidates())


def run() -> str:
    cfg = pitch.settings()
    if pitch.paused(cfg):
        return "Pitch paused. No second tries drafted."
    dead = retire()
    room, made = slots(cfg), 0
    for lead in candidates(cfg)[:room]:
        draft(lead, cfg)
        made += 1
    return f"{made} second tr{'y' if made == 1 else 'ies'} drafted, {dead} lead{'' if dead == 1 else 's'} retired as dead."


def state() -> dict:
    waiting = db.rows("SELECT t.id, t.lead_id, t.n, t.idea, t.subject, t.message, l.name, l.platform, l.contact, l.followers "
                      "FROM rerun_tries t JOIN leads l ON l.id = t.lead_id WHERE t.status = 'drafted' "
                      "ORDER BY l.followers DESC, t.id")
    counts = {r["status"]: r["n"] for r in db.rows("SELECT status, COUNT(*) n FROM rerun_tries GROUP BY status")}
    return {"paused": pitch.paused(), "daily": daily(), "waiting": waiting, "sent": counts.get("sent", 0),
            "queued_up": len(candidates()), "max_tries": MAX_TRIES}
