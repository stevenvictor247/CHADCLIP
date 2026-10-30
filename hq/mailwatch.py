"""Nudge: finds replies to Pitch emails in Gmail. Read-only: the inbox is opened read-only, messages are fetched with
BODY.PEEK (so they are never marked read), and nothing is sent, moved or deleted. A message only counts when it comes
from the address of a lead Pitch emailed, or is a bounce naming one. Plain rules, no Claude.
"""

import email
import imaplib
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime

from . import db, relay
from .agents.pitch import agent as pitch, mailer

HOST = "imap.gmail.com"
QUIET_DAYS = 5          # a pitched lead with no answer after this long is quiet
LOOKBACK_DAYS = 45      # how far back the inbox search goes at most
MAX_MESSAGES = 400      # most inbox messages looked at in one check
SNIPPET = 400
HEADERS = "FROM SUBJECT DATE MESSAGE-ID AUTO-SUBMITTED PRECEDENCE X-FAILED-RECIPIENTS"
DAEMONS = ("mailer-daemon", "postmaster")
AUTO_SUBJECT = re.compile(r"out of office|automatic reply|auto[- ]?reply|autoreply|vacation", re.I)


def quiet_days(cfg: dict | None = None) -> int:
    try:
        return max(1, min(60, int((cfg if cfg is not None else pitch.settings()).get("nudge_quiet_days", QUIET_DAYS))))
    except (TypeError, ValueError):
        return QUIET_DAYS


def _iso(days: float = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


# ---- who we are watching for -----------------------------------------------------------------------------

def watched() -> dict[str, dict]:
    """Email address -> lead, for every lead Pitch emailed and nobody has answered yet. Each carries `sent_at`."""
    out = {}
    for lead in db.rows("SELECT * FROM leads WHERE status = 'pitched' ORDER BY id"):
        addr = mailer.address_in(lead["contact"])
        if not addr:
            continue
        sent = db.rows("SELECT sent_at FROM pitch_sent WHERE lead_id = ? UNION SELECT sent_at FROM queue_sent WHERE lead_id = ?",
                       lead["id"], lead["id"])
        lead["sent_at"] = min((r["sent_at"] for r in sent), default=lead["updated_at"])
        out[addr] = lead
    return out


def worth_checking() -> bool:
    return mailer.configured() and bool(watched())


# ---- reading the inbox (read-only) -----------------------------------------------------------------------

def _fetch(m: imaplib.IMAP4_SSL, uid: bytes, what: str) -> bytes:
    typ, data = m.uid("FETCH", uid, what)
    if typ != "OK":
        return b""
    return b"".join(p[1] for p in data if isinstance(p, tuple))


def _text(raw: bytes) -> str:
    msg = email.message_from_bytes(raw)
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_type() == "text/plain":
            try:
                body = part.get_payload(decode=True) or b""
            except Exception:
                continue
            return body.decode(part.get_content_charset() or "utf-8", "replace")
    return ""


def _clean(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.startswith(">") or re.match(r"on .+wrote:\s*$", line.strip(), re.I):
            break   # the quoted copy of our own pitch starts here
        lines.append(line.strip())
    return " ".join(" ".join(lines).split())[:SNIPPET]


def scan(since_days: float) -> list[dict]:
    """Inbox messages since `since_days` ago as dicts: from, subject, id, date, auto, failed, snippet (bounces keep the
    text the bounce quotes). Only headers are fetched, plus a short peek at the body of senders we watch for."""
    address, password = mailer.credentials()
    watch = watched()
    since = (datetime.now(timezone.utc) - timedelta(days=min(since_days, LOOKBACK_DAYS))).strftime("%d-%b-%Y")
    found = []
    m = imaplib.IMAP4_SSL(HOST, timeout=30)
    try:
        m.login(address, password)
        m.select("INBOX", readonly=True)
        typ, data = m.uid("SEARCH", None, "SINCE", since)
        uids = (data[0] or b"").split()[-MAX_MESSAGES:] if typ == "OK" else []
        for uid in uids:
            head = email.message_from_bytes(_fetch(m, uid, f"(BODY.PEEK[HEADER.FIELDS ({HEADERS})])"))
            sender = parseaddr(head.get("From", ""))[1].lower()
            subject = " ".join(str(head.get("Subject", "")).split())
            daemon = sender.split("@")[0] in DAEMONS
            if sender not in watch and not daemon:
                continue   # not from a pitched lead: never opened beyond its headers
            body = _text(_fetch(m, uid, f"(BODY.PEEK[]<0.{12000 if daemon else 6000}>)"))
            try:
                date = parsedate_to_datetime(head.get("Date", "")).astimezone(timezone.utc).isoformat(timespec="seconds")
            except (TypeError, ValueError):
                date = db.now()
            auto = (str(head.get("Auto-Submitted", "no")).lower() != "no" or str(head.get("Precedence", "")).lower() in ("bulk", "auto_reply", "junk")
                    or bool(AUTO_SUBJECT.search(subject)))
            found.append({"from": sender, "subject": subject, "id": str(head.get("Message-ID", "")).strip() or f"uid-{uid.decode()}",
                          "date": date, "auto": auto, "bounce": daemon,
                          "failed": str(head.get("X-Failed-Recipients", "")), "snippet": body if daemon else _clean(body)})
    finally:
        try:
            m.logout()
        except Exception:
            pass
    return found


# ---- turning messages into lead states -------------------------------------------------------------------

def classify(messages: list[dict], watch: dict[str, dict]) -> list[dict]:
    """[{lead, kind: replied|bounced, snippet, message_id}], dropping anything seen before, sent before the pitch,
    or an automatic out-of-office. Replies from the lead's own address; bounces that name the lead's address."""
    out, done = [], set()
    for msg in messages:
        if db.rows("SELECT 1 FROM nudge_seen WHERE message_id = ?", msg["id"]):
            continue
        if msg["bounce"]:
            text = f"{msg['failed']} {msg['snippet']}".lower()
            lead = next((l for a, l in watch.items() if a in text), None)
            kind = "bounced"
        else:
            lead, kind = watch.get(msg["from"]), "replied"
            if msg["auto"]:
                lead = None
        if not lead or msg["date"] < lead["sent_at"] or (lead["id"], kind) in done:
            continue
        done.add((lead["id"], kind))
        out.append({"lead": lead, "kind": kind, "snippet": msg["snippet"] if kind == "replied" else "", "message_id": msg["id"]})
    return out


def record(found: list[dict]) -> None:
    for f in found:
        lead = f["lead"]
        with db.connect() as c:
            c.execute("INSERT OR IGNORE INTO nudge_seen (message_id, lead_id, kind, seen_at) VALUES (?, ?, ?, ?)",
                      (f["message_id"], lead["id"], f["kind"], db.now()))
            c.execute("INSERT INTO nudge_state (lead_id, state, snippet, at) VALUES (?, ?, ?, ?) "
                      "ON CONFLICT(lead_id) DO UPDATE SET state = excluded.state, snippet = excluded.snippet, at = excluded.at",
                      (lead["id"], f["kind"], f["snippet"], db.now()))
        if f["kind"] == "bounced":
            pitch.set_status(lead["id"], "dead", "Email bounced")
            db.log("Nudge", f"Email to {lead['name']} bounced")
        else:
            db.log("Nudge", f"{lead['name']} replied")


def mark_quiet(watch: dict[str, dict]) -> int:
    """Pitched, no answer, and older than the quiet window. Counted once; status stays pitched so Pitch's follow-ups go on."""
    cutoff, n = _iso(quiet_days()), 0
    for lead in watch.values():
        if lead["sent_at"] <= cutoff and not db.rows("SELECT 1 FROM nudge_state WHERE lead_id = ?", lead["id"]):
            db.execute("INSERT OR IGNORE INTO nudge_state (lead_id, state, snippet, at) VALUES (?, 'quiet', '', ?)", lead["id"], db.now())
            n += 1
    return n


def card(lead: dict, snippet: str) -> None:
    """One Telegram card per reply: Draft quote or Not interested. Nothing is sent until you approve the quote."""
    if db.rows("SELECT 1 FROM relay_sent WHERE kind = 'nudge' AND ref_id = ?", lead["id"]):
        return
    db.execute("INSERT OR IGNORE INTO relay_sent (kind, ref_id, created_at) VALUES ('nudge', ?, ?)", lead["id"], db.now())
    relay.ask(f"📬 {lead['name']} replied to your pitch\n\n{snippet or '(no text)'}", "nudge", lead["id"],
              yes="📝 Draft quote", no="🚫 Not interested")


def decide(lead_id: int, decision: str) -> str:
    """Tap on a reply card. Draft quote hands the lead to Closer (which asks for your OK before anything is sent)."""
    rows = db.rows("SELECT * FROM leads WHERE id = ?", lead_id)
    if not rows:
        return "No such lead."
    lead = rows[0]
    if lead["status"] not in ("pitched", "replied"):
        return f"{lead['name']} is already {lead['status']}, so nothing changed."
    if decision == "reject":
        pitch.set_status(lead_id, "dead", "Not interested (from Nudge)")
        db.log("Steven", f"{lead['name']} marked not interested (from Nudge)")
        return f"{lead['name']} closed as not interested."
    from .agents.closer import agent as closer
    state = db.rows("SELECT snippet FROM nudge_state WHERE lead_id = ?", lead_id)
    pitch.set_status(lead_id, "replied", "Replied (Nudge)")
    return closer.Closer().quote(lead_id, reply=state[0]["snippet"] if state else "")


relay.DECIDERS["nudge"] = decide


# ---- the round --------------------------------------------------------------------------------------------

def run() -> str:
    if not mailer.configured():
        return "Gmail isn't set up (Settings > Pitch), so there is nothing to read."
    watch = watched()
    if not watch:
        return "No pitched leads with an email address to watch."
    oldest = min(l["sent_at"] for l in watch.values())
    days = (datetime.now(timezone.utc) - datetime.fromisoformat(oldest)).total_seconds() / 86400 + 1
    try:
        found = classify(scan(days), watch)
    except imaplib.IMAP4.error as e:
        return f"Gmail refused the login or IMAP is off ({e}). Turn on IMAP in Gmail settings and check the app password."
    except OSError as e:
        return f"Couldn't reach Gmail ({e.__class__.__name__}). Will try again next round."
    record(found)
    for f in found:
        if f["kind"] == "replied":
            card(f["lead"], f["snippet"])
    quiet = mark_quiet(watch)
    replied = sum(f["kind"] == "replied" for f in found)
    return f"{replied} new repl{'y' if replied == 1 else 'ies'}, {len(found) - replied} bounced, {quiet} newly quiet."


def summary() -> dict:
    """Counts for the dashboard. Reply rate = replied-or-better leads out of everything pitched."""
    by = {r["state"]: r["n"] for r in db.rows("SELECT state, COUNT(*) n FROM nudge_state GROUP BY state")}
    pitched = db.rows("SELECT COUNT(*) n FROM leads WHERE status IN ('pitched','replied','client','won') "
                      "OR id IN (SELECT lead_id FROM nudge_state)")[0]["n"]
    replied = db.rows("SELECT COUNT(*) n FROM leads WHERE status IN ('replied','client','won') "
                      "OR id IN (SELECT lead_id FROM nudge_state WHERE state = 'replied')")[0]["n"]
    return {"configured": mailer.configured(), "pitched": pitched, "replied": replied, "bounced": by.get("bounced", 0),
            "quiet": by.get("quiet", 0), "percent": round(100 * replied / pitched) if pitched else None,
            "quiet_days": quiet_days()}
