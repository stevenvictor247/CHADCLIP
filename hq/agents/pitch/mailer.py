"""Sends an approved Pitch email from Steven's own Gmail. Only the approval handler calls this, never an agent on
its own, so nothing is sent until Steven taps "Send email".

Setup: PITCH_EMAIL_ADDRESS and a Gmail app password in PITCH_EMAIL_APP_PASSWORD (Settings page).
"""

import os
import re
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from ... import db

HOST, PORT = "smtp.gmail.com", 465
HARD_CAP = 20  # most emails in 24 hours, whatever pitch.yaml says: more than this gets Gmail accounts suspended
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


class SendError(Exception):
    """Plain words for Steven about why an email didn't go."""


def credentials() -> tuple[str, str]:
    return (os.getenv("PITCH_EMAIL_ADDRESS", "").strip(),
            re.sub(r"\s+", "", os.getenv("PITCH_EMAIL_APP_PASSWORD", "")))  # Google shows app passwords in 4s with spaces


def configured() -> bool:
    return all(credentials())


def address_in(text: str | None) -> str | None:
    m = EMAIL.search(text or "")
    return m.group(0).lower() if m else None


def blocked(email: str) -> bool:
    return bool(db.rows("SELECT 1 FROM do_not_contact WHERE email = ?", email.lower()))


def add_do_not_contact(email: str, reason: str = "") -> None:
    with db.connect() as c:
        c.execute("INSERT OR IGNORE INTO do_not_contact (email, reason, created_at) VALUES (?, ?, ?)",
                  (email.lower(), reason, db.now()))


def cap(cfg: dict) -> int:
    try:
        wanted = int(cfg.get("daily_send_cap", 10))
    except (TypeError, ValueError):
        wanted = 10
    return max(0, min(wanted, HARD_CAP))


def sent_last_day() -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    return sum(db.rows(f"SELECT COUNT(*) n FROM {t} WHERE sent_at >= ?", since)[0]["n"] for t in ("pitch_sent", "followup_sent"))


def split_pitch(pitch: str) -> tuple[str, str]:
    """Pitch drafts are stored as 'Subject: ...' then a blank line then the message."""
    head, _, body = (pitch or "").partition("\n\n")
    subject = head[len("Subject:"):].strip() if head.startswith("Subject:") else "Clips for your stream"
    return " ".join(subject.split()) or "Clips for your stream", body.strip()


def build(cfg: dict, to: str, pitch: str) -> EmailMessage:
    address, _ = credentials()
    subject, body = split_pitch(pitch)
    opt_out = str(cfg.get("opt_out_line") or "").strip()
    if opt_out and opt_out not in body:
        body += f"\n\n{opt_out}"
    body += f"\n\n{str(cfg.get('postal_address')).strip()}"  # spam law (CAN-SPAM): a real postal address
    msg = EmailMessage()
    msg["From"] = formataddr((str(cfg.get("sender_name") or "").strip(), address))
    msg["To"] = to
    msg["Reply-To"] = address
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=address.split("@")[-1])
    msg["List-Unsubscribe"] = f"<mailto:{address}?subject=unsubscribe>"
    msg.set_content(body)
    return msg


def _connect() -> smtplib.SMTP:
    """A logged-in Gmail connection. Tries port 465, then 587 (some networks and antivirus programs block one)."""
    address, password = credentials()
    errors = []
    for port in (465, 587):
        try:
            if port == 465:
                s = smtplib.SMTP_SSL(HOST, port, timeout=30, context=ssl.create_default_context())
            else:
                s = smtplib.SMTP(HOST, port, timeout=30)
                s.starttls(context=ssl.create_default_context())
            s.login(address, password)
            return s
        except smtplib.SMTPAuthenticationError:
            raise
        except (smtplib.SMTPException, OSError) as e:
            errors.append(f"port {port}: {e.__class__.__name__} {e}".strip())
    raise ConnectionError("; ".join(errors))


def _explain(e: Exception) -> SendError:
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return SendError("Gmail didn't accept the address or app password. Make a new app password at "
                         "myaccount.google.com/apppasswords (2-Step Verification must be on) and paste it in Settings.")
    detail = str(e)
    hint = (" Something on this computer or network is blocking the connection to Gmail: check that your antivirus or "
            "firewall allows Python, and that you're not on a work or school network.")
    return SendError(f"Couldn't reach Gmail ({detail}).{hint}")


def send(msg: EmailMessage) -> None:
    from ...standby import blocked
    why = blocked()
    if why:   # only the copy of HQ that runs the agents sends email, so nothing goes out twice
        raise SendError(f"Not sent. {why}")
    try:
        with _connect() as s:
            s.send_message(msg)
    except smtplib.SMTPRecipientsRefused:
        raise SendError("Gmail says that email address doesn't exist or refuses mail.")
    except (smtplib.SMTPException, OSError) as e:
        raise _explain(e)


def check_login() -> None:
    """Log in without sending anything (the Settings page's Test button)."""
    try:
        with _connect():
            pass
    except (smtplib.SMTPException, OSError) as e:
        raise _explain(e)
