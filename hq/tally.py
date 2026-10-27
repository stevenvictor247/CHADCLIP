"""Tally: counts the views on every posted clip, so HQ learns what works and campaign earnings fill themselves in.

Once or twice a day Tally reads each posted clip's view count from the platform, saves it on the post, copies it into
that clip's campaign submission (views only go up, and the pay you typed is never touched), and writes a short note of
the clips that did best. Chad reads that note when he picks moments. Tally never calls Claude, so it costs nothing.

Platforms so far: YouTube (the sign-in from Settings can read your own videos' views). TikTok inbox uploads have no
video id until you post them in the app, so they're counted once TikTok's video list is connected (later).
"""

import json
from datetime import datetime, timedelta, timezone

from . import db, hooks
from .config import DATA_DIR

TALLY_DIR = DATA_DIR / "tally"
INSIGHTS_PATH = TALLY_DIR / "insights.json"
REPORT_PATH = TALLY_DIR / "report.json"   # the latest daily report; also says which day it was last sent
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


def your_taste(creator: str | None = None, days: float = BEST_WINDOW_DAYS) -> str:
    """One line for Chad: titles Steven approved and rejected lately, so picks drift toward his taste."""
    since = _ago(days)
    def titles(statuses: tuple) -> list[str]:
        marks = ", ".join("?" for _ in statuses)
        rows = db.rows(f"SELECT title FROM clips WHERE status IN ({marks}) AND created_at >= ? AND title IS NOT NULL "
                       "AND (? IS NULL OR LOWER(creator) = LOWER(?)) ORDER BY id DESC LIMIT 3",
                       *statuses, since, creator, creator)
        return [f"\"{r['title'][:70]}\"" for r in rows]
    liked, passed = titles(("approved", "posted")), titles(("rejected",))
    if not liked and not passed and creator:
        return your_taste(None, days)   # nothing for this creator yet: use all of them
    parts = []
    if liked:
        parts.append("Steven approved clips like " + ", ".join(liked))
    if passed:
        parts.append("he rejected clips like " + ", ".join(passed))
    return ("Steven's taste: " + "; ".join(parts) + ".") if parts else ""


def summary() -> dict:
    week = db.rows("SELECT COUNT(*) n, COALESCE(SUM(views), 0) v FROM posts WHERE status = 'posted' AND views IS NOT NULL "
                   "AND created_at >= ?", _ago(7))[0]
    return {"posts_counted_7d": week["n"], "views_7d": week["v"], "best": best_clips(limit=3),
            "estimated_campaign_pay_usd": estimated_pay(), "report": _saved_report().get("text", ""),
            "hooks": hooks.stats()}


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def snapshot() -> int:
    """Save today's view count for every counted post, so tomorrow's report can say what changed."""
    with db.connect() as c:
        return c.execute("INSERT OR REPLACE INTO view_snapshots (post_id, day, views) SELECT id, ?, views FROM posts "
                         "WHERE status = 'posted' AND views IS NOT NULL", (_today(),)).rowcount


def build_report() -> dict:
    """Views per platform and per clip, and the change since the last day we counted. No Claude, just arithmetic."""
    today = _today()
    posts = db.rows("SELECT p.id, p.platform, p.views, c.id clip_id, c.title, c.creator, "
                    "(SELECT views FROM view_snapshots s WHERE s.post_id = p.id AND s.day < ? "
                    "ORDER BY s.day DESC LIMIT 1) before FROM posts p JOIN clips c ON c.id = p.clip_id "
                    "WHERE p.status = 'posted' AND p.views IS NOT NULL AND p.created_at >= ?", today, _ago(LOOK_BACK_DAYS))
    platforms: dict[str, dict] = {}
    clips: dict[int, dict] = {}
    for p in posts:
        change = None if p["before"] is None else p["views"] - p["before"]
        for bucket, key, label in ((platforms, p["platform"], p["platform"]), (clips, p["clip_id"], p["title"])):
            b = bucket.setdefault(key, {"name": label, "views": 0, "change": 0, "has_change": False})
            b["views"] += p["views"]
            if change is not None:
                b["change"] += change
                b["has_change"] = True
    plat = sorted(platforms.values(), key=lambda b: -b["views"])
    clip_list = sorted(clips.values(), key=lambda b: -b["views"])
    gaining = [c for c in clip_list if c["has_change"] and c["change"] > 0]
    top = max(gaining, key=lambda c: c["change"]) if gaining else (clip_list[0] if clip_list else None)
    return {"day": today, "total": sum(b["views"] for b in plat),
            "change": sum(b["change"] for b in plat) if any(b["has_change"] for b in plat) else None,
            "platforms": plat, "clips": clip_list[:10], "top": top, "top_is_gain": bool(gaining)}


def _delta(b: dict) -> str:
    return f" ({b['change']:+,} since yesterday)" if b["has_change"] else " (first count)"


def format_report(r: dict) -> str:
    if not r["clips"]:
        return "Tally: no counted views yet. Counting starts once a real account (YouTube first) is posting."
    head = f"📊 Tally daily views: {r['total']:,} total"
    if r["change"] is not None:
        head += f", {r['change']:+,} since yesterday"
    lines = [head, ""]
    lines += [f"{b['name'].title()}: {b['views']:,}{_delta(b)}" for b in r["platforms"]]
    if r["top"]:
        t = r["top"]
        lines += ["", ("Top climber: " if r["top_is_gain"] else "Top clip: ") + f"\"{t['name']}\" {t['views']:,}{_delta(t)}"]
    lines += ["", "Per clip:"] + [f"• \"{c['name'][:50]}\" {c['views']:,}{_delta(c)}" for c in r["clips"]]
    return "\n".join(lines)


def _saved_report() -> dict:
    try:
        return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def send_report(force: bool = False) -> str:
    """Send the daily view report to the dashboard and Telegram. On a schedule it goes out once a day; force sends now."""
    saved = _saved_report()
    if not force and saved.get("sent_day") == _today():
        return ""
    text = format_report(build_report())
    from . import relay
    relay.notify(text)
    db.log("Tally", text)
    TALLY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = REPORT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps({"sent_day": _today(), "sent_at": db.now(), "text": text}, indent=2), encoding="utf-8")
    tmp.replace(REPORT_PATH)
    return text


def run(send_now: bool = False) -> str:
    counted, problems = 0, []
    for platform, fetch in FETCHERS.items():
        if not _posts(platform):
            continue
        n, errs = fetch()
        counted += n
        problems += errs
    synced = sync_submissions()
    data = write_insights()
    snapshot()
    if not counted and not problems:
        send_report(force=send_now)
        return "No posted clips to count yet. Tally starts once a real account (YouTube first) is posting."
    out = f"Counted views on {counted} posts; updated {synced} campaign submissions."
    if line := hooks.report_line():
        out += " " + line
    if data["best"]:
        top = data["best"][0]
        out += f" Best lately: \"{top['title']}\" with {int(top['views'] or 0):,} views."
    if problems:
        out += " Problems: " + "; ".join(problems)
    db.log("Tally", out)
    send_report(force=send_now)
    return out
