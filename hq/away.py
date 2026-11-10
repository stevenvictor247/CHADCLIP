"""Away mode: when Steven hasn't been around for a few days, HQ stops making new work that would only pile up waiting
for him, and says hello with a short catch-up when he comes back.

"Around" means he did something: opened the dashboard page, pressed a button in it, or wrote or tapped in Telegram.
A dashboard tab left open doesn't count, because its background refreshes aren't Steven.

While away, scheduled rounds of the agents that spend Claude money in the business and Etsy villages are skipped (their
drafts would go stale before he saw them). Free agents, posting of clips he already approved, football, backups and the
daily report keep going. Nothing is deleted or changed. HQ_AWAY_DAYS=0 turns this off.
"""

import os
import threading
from datetime import datetime, timedelta, timezone

from . import db
from .config import DATA_DIR

SEEN_PATH = DATA_DIR / "last_seen.txt"
DEFAULT_DAYS = 3
KEEP_WORKING = ("football",)   # villages whose scheduled work goes on while Steven is away (it's his job)
_lock = threading.Lock()


def away_days() -> float:
    """Days without Steven before away mode starts. 0 (or anything below 0) turns it off."""
    try:
        return max(0.0, float(os.getenv("HQ_AWAY_DAYS", "") or DEFAULT_DAYS))
    except ValueError:
        return float(DEFAULT_DAYS)


def last_seen() -> datetime | None:
    try:
        return datetime.fromisoformat(SEEN_PATH.read_text().strip())
    except (OSError, ValueError):
        return None


def is_away(now: datetime | None = None) -> bool:
    days = away_days()
    seen = last_seen()
    if not days or seen is None:   # never seen yet (new install or first run after this update): start the clock
        return False
    return (now or datetime.now(timezone.utc)) - seen >= timedelta(days=days)


def ensure_started() -> None:
    """Start the clock the first time HQ runs with away mode, so an old install isn't treated as away forever."""
    if last_seen() is None:
        _write(datetime.now(timezone.utc))


def _write(when: datetime) -> None:
    tmp = SEEN_PATH.with_suffix(".tmp")
    tmp.write_text(when.isoformat(timespec="seconds"))
    os.replace(tmp, SEEN_PATH)


def seen(now: datetime | None = None) -> None:
    """Steven did something. If he was away, send the welcome-back catch-up once."""
    now = now or datetime.now(timezone.utc)
    with _lock:
        was_away, since = is_away(now), last_seen()
        try:
            _write(now)
        except OSError:
            return
    if was_away and since is not None:
        try:
            text = catch_up(since, now)
            db.log("HQ", text.replace("\n", " "))
            from . import relay
            relay.notify(text)
        except Exception:   # a catch-up that can't be written must never break the click that triggered it
            import traceback
            traceback.print_exc()


def skips(agent) -> bool:
    """True when this agent's scheduled rounds wait because Steven is away."""
    return not agent.free and agent.village not in KEEP_WORKING and is_away()


def catch_up(since: datetime, now: datetime) -> str:
    """Plain-code summary of what happened while Steven was gone. No Claude call, so it costs nothing."""
    from . import money
    days = max(1, round((now - since).total_seconds() / 86400))
    ts = since.isoformat(timespec="seconds")
    approvals = db.rows("SELECT COUNT(*) n FROM approvals WHERE status = 'pending'")[0]["n"]
    clips = db.rows("SELECT COUNT(*) n FROM clips WHERE status = 'pending_approval'")[0]["n"]
    posted = db.rows("SELECT COUNT(*) n FROM posts WHERE status = 'posted' AND created_at >= ?", ts)[0]["n"]
    spent = money._claude(ts)
    made = money._campaigns(ts)
    lines = [f"👋 Welcome back. You were away about {days} day{'s' if days != 1 else ''}.",
             "While you were gone, agents that would only pile up drafts for you rested. They're working again now.",
             f"Waiting for you: {clips} clip{'s' if clips != 1 else ''} and {approvals} other approval"
             f"{'s' if approvals != 1 else ''}.",
             f"Posts that went out: {posted}. Claude spend: ${spent:.2f}. Campaign pay recorded: "
             f"${made:.2f}."]
    if clips + approvals > 10:
        lines.append("Tip: clips older than 3 days are held as stale, so start with the newest ones.")
    return "\n".join(lines)
