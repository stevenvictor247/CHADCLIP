"""Clipping campaigns Scout has found, and the clips submitted to them.

A campaign you join becomes a creator Chad is allowed to clip: the campaign is the recorded permission.
"""

import json

from . import db


def _j(value) -> str:
    return json.dumps(list(value or []))


def _load(row: dict) -> dict:
    for k in ("platforms", "required_tags", "content_sources", "flags"):
        row[k] = json.loads(row.get(k) or "[]")
    return row


def get(campaign_id: int) -> dict | None:
    r = db.rows("SELECT * FROM campaigns WHERE id = ?", campaign_id)
    return _load(r[0]) if r else None


def all_campaigns() -> list[dict]:
    return [_load(r) for r in db.rows("SELECT * FROM campaigns ORDER BY id DESC")]


def flags_for(c: dict) -> list[str]:
    """Plain-rule warnings, so a campaign isn't judged by Claude's enthusiasm alone."""
    out = []
    if c.get("rate_per_1k") is not None and c["rate_per_1k"] < 0.5:
        out.append(f"low pay: ${c['rate_per_1k']:g} per 1,000 views")
    if c.get("budget_left_pct") is not None and c["budget_left_pct"] < 20:
        out.append(f"budget is {100 - c['budget_left_pct']:.0f}% spent, it may run dry before you're paid")
    if not c.get("content_sources"):
        out.append("no source videos listed, so Chad has nothing to clip until you add some")
    if c.get("min_views"):
        out.append(f"only pays once a clip reaches {c['min_views']:,} views")
    return out


def propose(data: dict, url: str | None = None, sources: list | None = None) -> int:
    c = {**data, "content_sources": list(sources or data.get("content_sources") or [])}
    flags = list(data.get("red_flags") or []) + flags_for(c)
    return db.execute(
        "INSERT INTO campaigns (name, creator, url, platforms, rate_per_1k, budget_left_pct, min_views, max_payout, "
        "required_tags, credit, rules, clip_style, content_sources, flags, score, verdict, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        c["name"], c.get("creator"), url, _j(c.get("platforms")), c.get("rate_per_1k"), c.get("budget_left_pct"),
        c.get("min_views"), c.get("max_payout"), _j(c.get("required_tags")), c.get("credit"), c.get("rules"),
        c.get("clip_style"), _j(c["content_sources"]), _j(flags), c.get("score"), c.get("verdict"), db.now())


def decide(campaign_id: int, decision: str) -> str:
    status = {"join": "joined", "approve": "joined", "skip": "skipped", "reject": "skipped"}[decision]
    c = get(campaign_id)
    if not c:
        raise ValueError(f"No campaign #{campaign_id}")
    db.execute("UPDATE campaigns SET status = ? WHERE id = ?", status, campaign_id)
    db.log("Steven", f"Campaign \"{c['name']}\" {status}")
    return f"Campaign \"{c['name']}\" {status}." + (
        " Chad can clip it now." if status == "joined" and c["content_sources"]
        else " Add source video links so Chad has something to clip." if status == "joined" else "")


def add_sources(campaign_id: int, urls: list[str]) -> None:
    c = get(campaign_id)
    merged = list(dict.fromkeys(c["content_sources"] + [u for u in urls if u]))
    db.execute("UPDATE campaigns SET content_sources = ? WHERE id = ?", json.dumps(merged), campaign_id)


def as_creators() -> list[dict]:
    """Joined campaigns in the same shape as creators.yaml entries, so Chad treats them as permitted creators."""
    out = []
    for c in all_campaigns():
        if c["status"] != "joined":
            continue
        out.append({
            "name": c["creator"] or c["name"],
            "sources": c["content_sources"],
            "permission": f"Clipping campaign: {c['name']}" + (f" ({c['url']})" if c.get("url") else ""),
            "notes": " ".join(x for x in (c.get("clip_style"), c.get("rules")) if x),
            "credit": c.get("credit") or "",
            "required_tags": c["required_tags"],
            "campaign_id": c["id"],
            "max_videos_per_run": 1,
            "accounts": [],
        })
    return out


def sync_submissions() -> list[dict]:
    """Make a to-do entry for each posted clip from a campaign that hasn't been logged yet. Returns the new ones."""
    new = []
    for p in db.rows("SELECT p.id post_id, p.url, p.platform, p.clip_id, c.campaign_id FROM posts p "
                     "JOIN clips c ON c.id = p.clip_id WHERE p.status = 'posted' AND p.platform != 'practice' "
                     "AND c.campaign_id IS NOT NULL "
                     "AND p.id NOT IN (SELECT post_id FROM submissions)"):
        ts = db.now()
        sid = db.execute("INSERT INTO submissions (campaign_id, clip_id, post_id, post_url, platform, created_at, updated_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)", p["campaign_id"], p["clip_id"], p["post_id"], p["url"], p["platform"], ts, ts)
        new.append({**p, "submission_id": sid})
    return new


def record(submission_id: int, views: int | None = None, earned_usd: float | None = None, status: str | None = None) -> None:
    if status and status not in ("to_submit", "submitted", "paid", "unpaid"):
        raise ValueError("status must be to_submit, submitted, paid or unpaid")
    db.execute("UPDATE submissions SET views = COALESCE(?, views), earned_usd = COALESCE(?, earned_usd), "
               "status = COALESCE(?, status), updated_at = ? WHERE id = ?", views, earned_usd, status, db.now(), submission_id)


def summary() -> list[dict]:
    """Every campaign with its totals, for the dashboard."""
    out = []
    for c in all_campaigns():
        subs = db.rows("SELECT status, views, earned_usd FROM submissions WHERE campaign_id = ?", c["id"])
        c["totals"] = {
            "submissions": len(subs),
            "to_submit": sum(1 for s in subs if s["status"] == "to_submit"),
            "views": sum(s["views"] for s in subs),
            "earned_usd": round(sum(s["earned_usd"] for s in subs), 2),
            "expected_usd": round(sum(s["views"] for s in subs) / 1000 * (c.get("rate_per_1k") or 0), 2),
        }
        out.append(c)
    return out
