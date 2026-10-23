"""Tally: counts the views on every posted clip, so HQ learns what works and campaign earnings fill themselves in.

Once or twice a day Tally reads each posted clip's view count from the platform, saves it on the post, copies it into
that clip's campaign submission (views only go up, and the pay you typed is never touched), and writes a short note of
the clips that did best. Chad reads that note when he picks moments. Tally never calls Claude, so it costs nothing.

Platforms so far: YouTube (the sign-in from Settings can read your own videos' views). TikTok inbox uploads have no
video id until you post them in the app, so they're counted once TikTok's video list is connected (later).
"""

import json
from datetime import datetime, timedelta, timezone

from . import db
from .config import DATA_DIR

TALLY_DIR = DATA_DIR / "tally"
INSIGHTS_PATH = TALLY_DIR / "insights.json"
LOOK_BACK_DAYS = 60     # posts older than this stop being re-counted
BEST_WINDOW_DAYS = 14   # "what worked lately"


def _ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def _posts(platform: str) -> list[dict]:
    return db.rows("SELECT id, clip_id, account, external_id FROM posts WHERE platform = ? AND status = 'posted' "
                   "AND external_id IS NOT NULL AND created_at >= ? ORDER BY id", platform, _ago(LOOK_BACK_DAYS))


def _save_views(post_id: int, views: int):
    db.execute("UPDATE posts SET views = MAX(COALESCE(views, 0), ?), views_at = ? WHERE id = ?", views, db.now(), post_id)


def fetch_youtube() -> tuple[int, list[str]]:
    """View counts for the YouTube Shorts HQ posted. Returns (posts counted, problems)."""
    from .agents.chad.publish import load_accounts, youtube
    accounts = {a["name"]: a for a in load_accounts() if a["platform"] == "youtube"}
    by_account: dict[str, list[dict]] = {}
    for p in _posts("youtube"):
        by_account.setdefault(p["account"], []).append(p)
    counted, problems = 0, []
    for name, posts in by_account.items():
        account = accounts.get(name)
        if not account:
            continue
        try:
            from googleapiclient.discovery import build
            client = build("youtube", "v3", credentials=youtube._credentials(account), cache_discovery=False)
            for i in range(0, len(posts), 50):   # the API takes up to 50 ids per call
                batch = posts[i:i + 50]
                ids = ",".join(p["external_id"] for p in batch)
                items = client.videos().list(part="statistics", id=ids).execute().get("items", [])
                views = {it["id"]: int(it.get("statistics", {}).get("viewCount", 0)) for it in items}
                for p in batch:
                    if p["external_id"] in views:
                        _save_views(p["id"], views[p["external_id"]])
                        counted += 1
        except Exception as e:
            problems.append(f"YouTube ({name}): {str(e)[:160]}")
    return counted, problems


FETCHERS = {"youtube": fetch_youtube}


def sync_submissions() -> int:
    """Copy fresh view counts into campaign submissions. Views only go up; earnings you typed are left alone."""
    with db.connect() as c:
        return c.execute("UPDATE submissions SET views = (SELECT p.views FROM posts p WHERE p.id = submissions.post_id), "
                         "updated_at = ? WHERE status IN ('to_submit', 'submitted') AND EXISTS (SELECT 1 FROM posts p "
                         "WHERE p.id = submissions.post_id AND COALESCE(p.views, 0) > submissions.views)",
                         (db.now(),)).rowcount


def estimated_pay() -> float:
    """What the campaigns should pay for the views so far, from each campaign's rate, minimum and cap."""
    total = 0.0
    for s in db.rows("SELECT s.views, c.rate_per_1k, c.min_views, c.max_payout FROM submissions s "
                     "JOIN campaigns c ON c.id = s.campaign_id WHERE s.status != 'unpaid'"):
        if not s["rate_per_1k"] or s["views"] < (s["min_views"] or 0):
            continue
        pay = s["views"] / 1000 * s["rate_per_1k"]
        total += min(pay, s["max_payout"]) if s["max_payout"] else pay
    return round(total, 2)


def best_clips(days: float = BEST_WINDOW_DAYS, limit: int = 5) -> list[dict]:
    return db.rows("SELECT c.id, c.creator, c.title, ROUND(c.end_s - c.start_s) seconds, SUM(p.views) views "
                   "FROM posts p JOIN clips c ON c.id = p.clip_id WHERE p.status = 'posted' AND p.views IS NOT NULL "
                   "AND p.created_at >= ? GROUP BY c.id ORDER BY views DESC LIMIT ?", _ago(days), limit)


def write_insights() -> dict:
    best = best_clips()
    by_creator = db.rows("SELECT c.creator, COUNT(DISTINCT c.id) clips, ROUND(AVG(p.views)) avg_views FROM posts p "
                         "JOIN clips c ON c.id = p.clip_id WHERE p.status = 'posted' AND p.views IS NOT NULL "
                         "AND p.created_at >= ? GROUP BY c.creator ORDER BY avg_views DESC", _ago(BEST_WINDOW_DAYS))
    data = {"updated": db.now(), "best": best, "by_creator": by_creator}
    TALLY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = INSIGHTS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(INSIGHTS_PATH)
    return data


def for_chad(creator: str | None) -> str:
    """One or two lines for Chad's prompt: which recent clips got the most views (same creator first)."""
    try:
        data = json.loads(INSIGHTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    best = data.get("best") or []
    if not best:
        return ""
    same = [b for b in best if creator and (b.get("creator") or "").lower() == creator.lower()]
    picks = (same or best)[:3]
    who = f"{creator}'s" if same else "your"
    listed = "; ".join(f"\"{b['title']}\" ({int(b['views'] or 0):,} views, {int(b['seconds'] or 0)} s)" for b in picks)
    return f"Recent results: {who} clips that got the most views lately were {listed}. Lean toward what worked."


def summary() -> dict:
    week = db.rows("SELECT COUNT(*) n, COALESCE(SUM(views), 0) v FROM posts WHERE status = 'posted' AND views IS NOT NULL "
                   "AND created_at >= ?", _ago(7))[0]
    return {"posts_counted_7d": week["n"], "views_7d": week["v"], "best": best_clips(limit=3),
            "estimated_campaign_pay_usd": estimated_pay()}


def run() -> str:
    counted, problems = 0, []
    for platform, fetch in FETCHERS.items():
        if not _posts(platform):
            continue
        n, errs = fetch()
        counted += n
        problems += errs
    synced = sync_submissions()
    data = write_insights()
    if not counted and not problems:
        return "No posted clips to count yet. Tally starts once a real account (YouTube first) is posting."
    out = f"Counted views on {counted} posts; updated {synced} campaign submissions."
    if data["best"]:
        top = data["best"][0]
        out += f" Best lately: \"{top['title']}\" with {int(top['views'] or 0):,} views."
    if problems:
        out += " Problems: " + "; ".join(problems)
    db.log("Tally", out)
    return out
