"""The Boss's check on Chad's work: plain rule-based findings the Boss reads and reports to Steven.

Nothing here approves, rejects or posts anything. It only looks and writes down what it sees.
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db

STUCK_HOURS = 2         # a task "running" longer than this is probably stuck
STALE_HOURS = 24        # a clip waiting longer than this needs Steven's eye
WEAK_SCORE = 5          # Chad's own 0-10 score below this is a weak moment
WEAK_TWITCH_VIEWS = 1000


def _ago(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")


def _hours_since(ts: str) -> float:
    return (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 3600


def _chad_settings() -> dict:
    from .agents.chad.agent import settings
    try:
        return settings()
    except Exception:
        return {}


def clip_issues(clip: dict, cfg: dict) -> list[str]:
    """Quality problems with one clip, in plain words. Empty list means it looks fine."""
    issues = []
    if clip.get("path") and not Path(clip["path"]).exists():
        issues.append("video file is missing from disk")
    if cfg.get("captions", True) and clip.get("captioned") == 0:
        issues.append("no captions (no speech was found to caption)")
    caption = (clip.get("caption") or "").strip()
    if len(caption.split("Credit:")[0].strip()) < 5:
        issues.append("post caption is empty or too short")
    if "Credit:" not in caption:
        issues.append("caption has no credit to the creator")
    if not (clip.get("title") or "").strip():
        issues.append("no title")
    length = (clip.get("end_s") or 0) - (clip.get("start_s") or 0)
    if length > float(cfg.get("max_clip_seconds", 59)) + 0.5:
        issues.append(f"too long for a Short ({length:.0f}s)")
    elif length < min(float(cfg.get("min_clip_seconds", 15)), 10) - 0.5:
        issues.append(f"very short ({length:.0f}s)")
    score = clip.get("score")
    if "twitch.tv" in (clip.get("source_url") or ""):
        if score is not None and score < WEAK_TWITCH_VIEWS:
            issues.append(f"weak moment: only {score:,.0f} Twitch views")
    elif score is not None and score < WEAK_SCORE:
        issues.append(f"weak moment: Chad scored it {score:g}/10")
    if not (clip.get("reason") or "").strip():
        issues.append("Chad gave no reason for picking it")
    return issues


def _overlaps(a: dict, b: dict) -> bool:
    return a["source_url"] and a["source_url"] == b["source_url"] and a["start_s"] < b["end_s"] and b["start_s"] < a["end_s"]


def review_chad(hours: float = 24) -> dict:
    """What Chad did in the last `hours`, what went wrong, and which waiting clips need a closer look."""
    since = _ago(hours)
    cfg = _chad_settings()

    tasks = db.rows("SELECT id, instructions, status, result, created_at, updated_at FROM tasks "
                    "WHERE agent = 'Chad' AND updated_at >= ? ORDER BY id DESC", since)
    failed_tasks = [{"task": t["id"], "error": (t["result"] or "")[:300]} for t in tasks if t["status"] == "failed"]
    stuck = [{"task": t["id"], "running_for_hours": round(_hours_since(t["updated_at"]), 1)}
             for t in db.rows("SELECT id, updated_at FROM tasks WHERE agent = 'Chad' AND status = 'running'")
             if _hours_since(t["updated_at"]) > STUCK_HOURS]
    empty_runs = [{"task": t["id"], "result": (t["result"] or "")[:300]} for t in tasks
                  if t["status"] == "done" and (re.match(r"Made 0 clips", t["result"] or "") or
                                                (t["result"] or "").startswith(("Skipped", "No ")))]

    new_clips = db.rows("SELECT id, creator, status FROM clips WHERE created_at >= ?", since)
    by_creator: dict[str, int] = {}
    for c in new_clips:
        by_creator[c["creator"] or "unknown"] = by_creator.get(c["creator"] or "unknown", 0) + 1

    pending = db.rows("SELECT * FROM clips WHERE status = 'pending_approval' ORDER BY id")
    others = db.rows("SELECT id, source_url, start_s, end_s FROM clips WHERE status IN "
                     "('pending_approval', 'approved', 'posted')")
    flagged, looks_good = [], []
    for c in pending:
        issues = clip_issues(c, cfg)
        dupes = [o["id"] for o in others if o["id"] != c["id"] and _overlaps(c, o)]
        if dupes:
            issues.append("overlaps clip " + ", ".join(f"#{d}" for d in dupes) + " from the same video")
        waited = _hours_since(c["created_at"])
        if waited > STALE_HOURS:
            issues.append(f"waiting for approval {waited:.0f} hours")
        entry = {"clip": c["id"], "creator": c["creator"], "title": c["title"], "score": c["score"]}
        if c.get("boss_note"):
            entry["your_earlier_note"] = c["boss_note"]
        if issues:
            flagged.append({**entry, "issues": issues})
        else:
            looks_good.append(entry)

    failed_posts = db.rows("SELECT clip_id, platform, account, error, created_at FROM posts "
                           "WHERE status = 'failed' AND created_at >= ? ORDER BY id DESC LIMIT 20", since)

    return {
        "window_hours": hours,
        "tasks": {"done": sum(t["status"] == "done" for t in tasks), "failed": failed_tasks,
                  "stuck": stuck, "ran_but_made_nothing": empty_runs},
        "new_clips": {"total": len(new_clips), "by_creator": by_creator},
        "waiting_for_steven": {"total": len(pending), "flagged": flagged, "looks_good": looks_good},
        "failed_posts": failed_posts,
    }


def summary(r: dict) -> str:
    """A short plain-text version, used when the Boss has no API key."""
    t, w = r["tasks"], r["waiting_for_steven"]
    lines = [f"Chad in the last {r['window_hours']:g} hours: {t['done']} tasks done, {len(t['failed'])} failed, "
             f"{r['new_clips']['total']} new clips. {w['total']} waiting for you, {len(w['flagged'])} flagged."]
    lines += [f"Task #{f['task']} failed: {f['error'][:120]}" for f in t["failed"]]
    lines += [f"Task #{s['task']} looks stuck ({s['running_for_hours']}h)." for s in t["stuck"]]
    lines += [f"Clip #{f['clip']}: {'; '.join(f['issues'])}" for f in w["flagged"]]
    lines += [f"Post of clip #{p['clip_id']} to {p['platform']} failed: {(p['error'] or '')[:120]}"
              for p in r["failed_posts"]]
    return "\n".join(lines)
