"""How many new clips Chad may make: a daily cap, and a pause while the posting backlog is bigger than a day of posts.

Clips go stale while they wait, so Chad makes only a few a day and none at all while earlier clips are still queued.
"""

import os
from datetime import datetime, timedelta, timezone

from . import db

MIN_PER_DAY = 4
DEFAULT_PER_DAY = 6


def _int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, "") or default))
    except ValueError:
        return default


def daily_cap() -> int:
    """HQ_MAX_CLIPS_PER_DAY, never below 4."""
    return max(MIN_PER_DAY, _int("HQ_MAX_CLIPS_PER_DAY", DEFAULT_PER_DAY))


def posting_capacity() -> int:
    """Clips the posting seatbelt lets out per day (HQ_MAX_POSTS_PER_DAY; 0 means no limit, so use the clip cap)."""
    try:
        from .agents.chad.publish import daily_capacity
        real = daily_capacity()  # several rotating accounts post more clips a day between them
    except Exception:
        real = 0
    if real > 0:
        return real
    cap = _int("HQ_MAX_POSTS_PER_DAY", 4)
    return cap if cap > 0 else daily_cap()


def backlog() -> int:
    """Clips waiting to be posted: made but not yet posted, rejected or failed (held stale ones don't count)."""
    return db.rows("SELECT COUNT(*) AS n FROM clips WHERE status IN ('pending_approval', 'approved') "
                   "AND COALESCE(stale_state, '') != 'flagged'")[0]["n"]


def made_today() -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    return db.rows("SELECT COUNT(*) AS n FROM clips WHERE created_at >= ?", since)[0]["n"]


def room() -> tuple[int, str]:
    """(clips Chad may still make right now, plain-English reason when that is 0)."""
    queued, capacity = backlog(), posting_capacity()
    if queued > capacity:
        return 0, (f"{queued} clips are still waiting to post (a day's posting is {capacity}), "
                   "so I'm not making new ones until they go out.")
    left = daily_cap() - made_today()
    if left <= 0:
        return 0, f"already made {daily_cap()} clips in the last 24 hours (the daily limit)."
    return left, ""
