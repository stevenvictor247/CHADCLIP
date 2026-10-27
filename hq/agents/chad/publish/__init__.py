"""Posts approved clips to every enabled clipping account."""

import json
import os
from datetime import datetime, timedelta, timezone

import yaml

from .... import db
from ....config import CONFIG_DIR
from ..sources import find_creator
from . import instagram, practice, tiktok, youtube

PLATFORMS = {"tiktok": tiktok, "youtube": youtube, "instagram": instagram, "practice": practice}
# TikTok first: it's the top priority.
ORDER = ["tiktok", "youtube", "instagram"]


def load_accounts() -> list[dict]:
    """accounts.yaml plus the built-in practice account."""
    with open(CONFIG_DIR / "accounts.yaml") as f:
        accounts = (yaml.safe_load(f) or {}).get("accounts") or []
    accounts = accounts + [practice.account(accounts)]
    return sorted(accounts, key=lambda a: ORDER.index(a["platform"]) if a["platform"] in ORDER else 99)


def accounts_for(creator_name: str | None) -> list[dict]:
    allowed = (find_creator(creator_name or "") or {}).get("accounts") or []
    return [a for a in load_accounts()
            if a.get("enabled") and (not allowed or a["name"] in allowed or a["platform"] == "practice")]


def post_text(clip: dict) -> str:
    tags = " ".join(f"#{t}" for t in json.loads(clip.get("hashtags") or "[]"))
    return f"{clip.get('caption') or clip.get('title') or ''}\n\n{tags}".strip()


def paused() -> bool:
    """The Pause All switch (dashboard button, "pause" on your phone, or HQ_PAUSED in Settings)."""
    return os.getenv("HQ_PAUSED", "").strip().lower() in ("true", "1", "yes")


def _number(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def wait_reason(account: dict) -> str | None:
    """Posting seatbelts: why this account shouldn't post right now, or None if it can.
    Bursts of posts look like spam to TikTok, YouTube and Instagram and get new accounts limited or banned."""
    if account["platform"] == "practice":
        return None
    cap = int(_number("HQ_MAX_POSTS_PER_DAY", 4))
    gap = _number("HQ_POST_GAP_MINUTES", 60)
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    recent = db.rows("SELECT created_at FROM posts WHERE platform = ? AND account = ? AND status = 'posted' "
                     "AND created_at >= ? ORDER BY created_at DESC", account["platform"], account["name"], since)
    if cap > 0 and len(recent) >= cap:
        return f"already posted {len(recent)} today (limit {cap})"
    if recent and gap > 0:
        last = datetime.fromisoformat(recent[0]["created_at"])
        free_at = last + timedelta(minutes=gap)
        if datetime.now(timezone.utc) < free_at:
            return f"waiting {gap:g} minutes between posts"
    return None


def publish_approved() -> list[str]:
    """Post every approved clip that hasn't gone out yet, within the seatbelts. Returns a line per attempt."""
    if paused():
        return ["HQ is paused: nothing posts until you press Resume."]
    report = []
    for clip in db.rows("SELECT * FROM clips WHERE status = 'approved' "
                          "AND COALESCE(stale_state, '') != 'flagged' ORDER BY id"):   # flagged = held for Steven's keep/drop
        accounts = accounts_for(clip["creator"])
        if not accounts:
            report.append(f"Clip #{clip['id']}: approved, but no clipping accounts are enabled in accounts.yaml yet.")
            continue
        # Every account this clip already went to (or failed on) is finished for this clip: a failure is never
        # retried on its own, because a half-finished upload could post twice.
        tried = {(p["platform"], p["account"]): p["status"] for p in
                 db.rows("SELECT platform, account, status FROM posts WHERE clip_id = ? AND status != 'retried' "
                         "ORDER BY id", clip["id"])}
        payload = {**clip, "post_text": post_text(clip), "hashtags": json.loads(clip.get("hashtags") or "[]")}
        waiting = 0
        for account in accounts:
            key = (account["platform"], account["name"])
            if key in tried:
                continue
            why = wait_reason(account)
            if why:
                waiting += 1
                report.append(f"Clip #{clip['id']} waits for {account['platform']} ({account['name']}): {why}")
                continue
            try:
                ext_id, url = PLATFORMS[account["platform"]].publish(payload, account)
                db.execute("INSERT INTO posts (clip_id, platform, account, status, external_id, url, created_at) "
                           "VALUES (?, ?, ?, 'posted', ?, ?, ?)", clip["id"], account["platform"], account["name"],
                           ext_id, url, db.now())
                tried[key] = "posted"
                msg = f"Clip #{clip['id']} posted to {account['platform']} ({account['name']})"
            except Exception as e:
                db.execute("INSERT INTO posts (clip_id, platform, account, status, error, created_at) "
                           "VALUES (?, ?, ?, 'failed', ?, ?)", clip["id"], account["platform"], account["name"],
                           str(e)[:1000], db.now())
                tried[key] = "failed"
                msg = f"Clip #{clip['id']} failed on {account['platform']} ({account['name']}): {e}"
            db.log("Chad", msg)
            report.append(msg)
        if waiting:
            continue  # stays approved; the next round posts it to the accounts that were waiting
        results = [tried.get((a["platform"], a["name"])) for a in accounts]
        db.set_clip_status(clip["id"], "posted" if "posted" in results else "failed")
    return report


def retry(clip_id: int) -> str:
    """You pressed "Try posting again" on a clip that failed somewhere: the failed accounts get one more go."""
    rows = db.rows("SELECT status FROM clips WHERE id = ?", clip_id)
    if not rows:
        raise ValueError(f"No clip #{clip_id}")
    failed = db.rows("SELECT platform, account FROM posts WHERE clip_id = ? AND status = 'failed'", clip_id)
    if not failed:
        raise ValueError(f"Clip #{clip_id} has no failed posts to try again")
    db.execute("UPDATE posts SET status = 'retried' WHERE clip_id = ? AND status = 'failed'", clip_id)
    db.set_clip_status(clip_id, "approved")
    where = ", ".join(f"{p['platform']} ({p['account']})" for p in failed)
    db.log("Steven", f"Clip #{clip_id}: try posting again to {where}")
    return f"Clip #{clip_id} will be posted again to {where}."
