"""Posts approved clips to every enabled clipping account."""

import json

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


def publish_approved() -> list[str]:
    """Post every approved clip that hasn't gone out yet. Returns a line per attempt."""
    report = []
    for clip in db.rows("SELECT * FROM clips WHERE status = 'approved' ORDER BY id"):
        accounts = accounts_for(clip["creator"])
        if not accounts:
            report.append(f"Clip #{clip['id']}: approved, but no clipping accounts are enabled in accounts.yaml yet.")
            continue
        done = {(p["platform"], p["account"]) for p in
                db.rows("SELECT platform, account FROM posts WHERE clip_id = ? AND status = 'posted'", clip["id"])}
        payload = {**clip, "post_text": post_text(clip), "hashtags": json.loads(clip.get("hashtags") or "[]")}
        failures = 0
        for account in accounts:
            if (account["platform"], account["name"]) in done:
                continue
            try:
                ext_id, url = PLATFORMS[account["platform"]].publish(payload, account)
                db.execute("INSERT INTO posts (clip_id, platform, account, status, external_id, url, created_at) "
                           "VALUES (?, ?, ?, 'posted', ?, ?, ?)", clip["id"], account["platform"], account["name"],
                           ext_id, url, db.now())
                msg = f"Clip #{clip['id']} posted to {account['platform']} ({account['name']})"
            except Exception as e:
                failures += 1
                db.execute("INSERT INTO posts (clip_id, platform, account, status, error, created_at) "
                           "VALUES (?, ?, ?, 'failed', ?, ?)", clip["id"], account["platform"], account["name"],
                           str(e)[:1000], db.now())
                msg = f"Clip #{clip['id']} failed on {account['platform']} ({account['name']}): {e}"
            db.log("Chad", msg)
            report.append(msg)
        db.set_clip_status(clip["id"], "failed" if failures == len(accounts) else "posted")
    return report
