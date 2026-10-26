"""Scores a Twitch lead 1 to 10 from free public data, so Steven reviews the best ones first.

Pure code, no tokens. Uses only what Twitch's official API gives (follower count, how often they stream, partner level)
plus their own public bio. Whether they already have a clipping team is a bio check, so it's a rough signal.
"""

import re

MIN_SHOWN = 4   # leads scoring under this are hidden from the daily review list

# Sweet spot: big enough to pay, small enough to need a clipper.
_SIZE = ((100, 1), (500, 3), (2_000, 5), (10_000, 6), (50_000, 4), (float("inf"), 2))
_TEAM = re.compile(r"\b(clips?\s+(?:by|team|channel|editor)|clipped\s+by|clipping\s+team|editor\s*:|"
                   r"yt\s*/\s*tiktok\s+by|highlights?\s+(?:by|channel)|managed\s+by|(?:represented|signed)\s+(?:by|with))", re.I)


def has_clip_team(bio: str) -> bool:
    return bool(_TEAM.search(bio or ""))


def score(followers: int | None, streams_14d: int | None, broadcaster_type: str = "", bio: str = "") -> tuple[int, str]:
    """Returns (1 to 10, one-line reason). Unknown numbers score neutral rather than zero."""
    size = next(pts for cap, pts in _SIZE if (followers or 0) <= cap) if followers is not None else 3
    points, why = size, [f"{followers:,} followers" if followers is not None else "followers unknown"]
    if streams_14d is not None:
        gain = 3 if streams_14d >= 10 else 2 if streams_14d >= 5 else 1 if streams_14d >= 2 else 0
        points += gain
        why.append(f"{streams_14d} streams in 14 days")
    else:
        points += 1
    if broadcaster_type in ("partner", "affiliate"):
        points += 1
        why.append(broadcaster_type)
    if has_clip_team(bio):
        points -= 4
        why.append("bio mentions a clip team")
    return max(1, min(10, points)), ", ".join(why)


def lookup(login: str, user_id: str, bio: str, broadcaster_type: str, viewers: int | None = None) -> tuple[int, str]:
    """Fetch follower count and recent stream count from Twitch (3 cheap calls), then score. Any failed call
    falls back to neutral instead of raising, so scoring never blocks finding leads."""
    from ..chad import twitch
    followers = streams = None
    try:
        followers = twitch.follower_count(user_id)
    except Exception:
        followers = viewers * 20 if viewers else None   # rough: live viewers x 20; follower API needs extra access
    try:
        streams = len(twitch.recent_vods(user_id, 20))
    except Exception:
        pass
    return score(followers, streams, broadcaster_type, bio)
