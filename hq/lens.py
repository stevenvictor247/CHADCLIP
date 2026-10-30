"""Lens: finds likely reasons posted clips get few views. Plain rules over what Tally already counted, no Claude.

Rules (each makes a fix with a short plain-English action):
- zero reach: an account whose posts are all older than ZERO_DAYS and still at 0 views
- odd hours: posts made in the small hours (local time) that got fewer views than the rest
- missing hashtags: clips posted with no hashtag in the caption or tags
- repeated captions: the same caption posted to one account several times
Steven taps Done or Ignore on each fix; Lens only suggests, it never changes an account or a post.
"""

import json
from datetime import datetime, timedelta, timezone

from . import db, relay

ZERO_DAYS = 3           # an account with only zero-view posts this old gets flagged and a Telegram note
ODD_HOURS = range(0, 6)  # local hours counted as "small hours"
REPEAT_MIN = 3          # same caption this many times on one account
WINDOW_DAYS = 7
MIN_POSTS = 2           # fewest posts before an account or an hour is judged


def _ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def _hour(created_at: str) -> int:
    dt = datetime.fromisoformat(created_at)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().hour


def pull(days: float = WINDOW_DAYS) -> list[dict]:
    """Each posted clip's account, time, length, caption and views (from Tally) for the last `days`."""
    return db.rows("SELECT p.id, p.platform, p.account, p.created_at, COALESCE(p.views, 0) views, "
                   "ROUND(c.end_s - c.start_s) seconds, COALESCE(NULLIF(c.caption, ''), c.title, '') caption, "
                   "c.hashtags FROM posts p JOIN clips c ON c.id = p.clip_id WHERE p.status = 'posted' "
                   "AND p.created_at >= ? ORDER BY p.id", _ago(days))


def has_hashtags(row: dict) -> bool:
    try:
        tags = json.loads(row.get("hashtags") or "[]")
    except ValueError:
        tags = []
    return bool(tags) or "#" in (row.get("caption") or "")


def group_by_account(posts: list[dict]) -> list[dict]:
    out: dict[str, dict] = {}
    for p in posts:
        g = out.setdefault(f"{p['platform']}:{p['account']}", {"account": p["account"], "platform": p["platform"], "posts": 0, "views": 0})
        g["posts"] += 1
        g["views"] += p["views"]
    return sorted(out.values(), key=lambda g: -g["views"])


def group_by_hour(posts: list[dict]) -> list[dict]:
    out: dict[int, dict] = {}
    for p in posts:
        g = out.setdefault(_hour(p["created_at"]), {"hour": _hour(p["created_at"]), "posts": 0, "views": 0})
        g["posts"] += 1
        g["views"] += p["views"]
    return sorted(out.values(), key=lambda g: g["hour"])


def zero_reach(posts: list[dict]) -> list[dict]:
    """Accounts whose posts are all older than ZERO_DAYS and all still at 0 views."""
    cutoff = _ago(ZERO_DAYS)
    by: dict[str, list[dict]] = {}
    for p in posts:
        by.setdefault(f"{p['platform']}:{p['account']}", []).append(p)
    found = []
    for key, rows in by.items():
        if len(rows) >= MIN_POSTS and all(r["views"] == 0 and r["created_at"] <= cutoff for r in rows):
            found.append({"key": f"zero:{key}", "rule": "zero_reach", "account": rows[0]["account"], "platform": rows[0]["platform"],
                          "text": f"{rows[0]['account']} ({rows[0]['platform']}) has {len(rows)} posts and 0 views after {ZERO_DAYS}+ days. "
                                  "Check the account isn't restricted or shadow-banned and that clips are really public; "
                                  "a brand-new account may just need a few days."})
    return found


def odd_hours(posts: list[dict]) -> list[dict]:
    odd = [p for p in posts if _hour(p["created_at"]) in ODD_HOURS]
    rest = [p for p in posts if _hour(p["created_at"]) not in ODD_HOURS]
    if len(odd) < MIN_POSTS or not rest:
        return []
    odd_avg, rest_avg = sum(p["views"] for p in odd) / len(odd), sum(p["views"] for p in rest) / len(rest)
    if odd_avg >= rest_avg:
        return []
    return [{"key": "odd_hours", "rule": "odd_hours", "account": None, "platform": None,
             "text": f"{len(odd)} clips went out between midnight and 6am and averaged {odd_avg:.0f} views against "
                     f"{rest_avg:.0f} for the rest. Move those posts to the daytime or evening."}]


def missing_hashtags(posts: list[dict]) -> list[dict]:
    bare = [p for p in posts if not has_hashtags(p)]
    if not bare:
        return []
    accounts = sorted({p["account"] for p in bare})
    return [{"key": "no_hashtags", "rule": "missing_hashtags", "account": None, "platform": None,
             "text": f"{len(bare)} posted clips have no hashtags (accounts: {', '.join(accounts)}). "
                     "Add 3 to 5 relevant hashtags to the caption."}]


def repeated_captions(posts: list[dict]) -> list[dict]:
    seen: dict[tuple, int] = {}
    for p in posts:
        cap = " ".join((p["caption"] or "").lower().split())
        if cap:
            seen[(p["account"], cap)] = seen.get((p["account"], cap), 0) + 1
    return [{"key": f"repeat:{acct}:{cap[:40]}", "rule": "repeated_captions", "account": acct, "platform": None,
             "text": f"{acct} posted the same caption {n} times (\"{cap[:50]}\"). Vary the wording so the platform doesn't treat it as spam."}
            for (acct, cap), n in seen.items() if n >= REPEAT_MIN]


def find_fixes(posts: list[dict] | None = None) -> list[dict]:
    posts = pull() if posts is None else posts
    return zero_reach(posts) + odd_hours(posts) + missing_hashtags(posts) + repeated_captions(posts)


def worth_checking() -> bool:
    return bool(db.rows("SELECT 1 FROM posts WHERE status = 'posted' AND created_at >= ? LIMIT 1", _ago(WINDOW_DAYS)))


# ---- Steven's decisions and the Telegram note -----------------------------------------------------------

def decide(key: str, state: str) -> bool:
    if state not in ("done", "ignored"):
        return False
    db.execute("INSERT OR REPLACE INTO lens_fixes (fix_key, state, at) VALUES (?, ?, ?)", key, state, db.now())
    return True


def _decided() -> dict[str, str]:
    return {r["fix_key"]: r["state"] for r in db.rows("SELECT fix_key, state FROM lens_fixes")}


def open_fixes(posts: list[dict] | None = None) -> list[dict]:
    decided = _decided()
    return [f for f in find_fixes(posts) if f["key"] not in decided]


def alert_zero(fixes: list[dict]) -> int:
    """One Telegram note per account the first time it shows zero reach."""
    sent = 0
    for f in fixes:
        if f["rule"] != "zero_reach" or db.rows("SELECT 1 FROM lens_alerts WHERE fix_key = ?", f["key"]):
            continue
        relay.notify(f"🔎 Lens: {f['text']}")
        db.execute("INSERT INTO lens_alerts (fix_key, at) VALUES (?, ?)", f["key"], db.now())
        sent += 1
    return sent


def run() -> str:
    posts = pull()
    fixes = find_fixes(posts)
    alerts = alert_zero(fixes)
    open_n = len([f for f in fixes if f["key"] not in _decided()])
    out = f"Looked at {len(posts)} posts from the last {WINDOW_DAYS} days: {open_n} fixes waiting"
    out += f", {alerts} zero-view alerts sent." if alerts else "."
    db.log("Lens", out)
    return out


def summary() -> dict:
    posts = pull()
    return {"posts": len(posts), "views": sum(p["views"] for p in posts), "fixes": open_fixes(posts),
            "by_account": group_by_account(posts), "by_hour": group_by_hour(posts), "days": WINDOW_DAYS}
