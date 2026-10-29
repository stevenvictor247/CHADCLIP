"""Posts through a self-hosted Postiz (https://github.com/gitroomhq/postiz-app) using only its public HTTP API.

Postiz is AGPL-3.0, so it runs as its own separate service and CHADCLIP never contains or copies its code: this file
just makes web requests to it. One Postiz channel (TikTok, Instagram, YouTube...) is one account here:

  - name: postiz_tiktok
    platform: postiz
    enabled: true
    integration_id: <the channel's id from Settings > Postiz channels>
    provider: tiktok            # tiktok, instagram, youtube or x
    privacy: PUBLIC_TO_EVERYONE  # TikTok only

Needs POSTIZ_URL (like http://localhost:5000) and POSTIZ_API_KEY in Settings. Only approved clips ever get here.
"""

import os
from datetime import datetime, timezone

import requests


def base() -> str:
    url = (os.getenv("POSTIZ_URL") or "").strip().rstrip("/")
    if not url:
        raise RuntimeError("Set the Postiz address (POSTIZ_URL) in Settings first.")
    return url if url.endswith("/api/public/v1") else url + "/api/public/v1"


def _headers() -> dict:
    key = (os.getenv("POSTIZ_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("Set the Postiz API key (POSTIZ_API_KEY) in Settings first.")
    return {"Authorization": key}


def channels() -> list[dict]:
    """The channels connected inside Postiz: [{id, name, identifier, ...}]. Used by the Settings test."""
    r = requests.get(f"{base()}/integrations", headers=_headers(), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Postiz said {r.status_code}: {r.text[:200]}")
    return r.json()


def provider_settings(account: dict, clip: dict) -> dict:
    """The per-platform settings Postiz needs. TikTok must be DIRECT_POST or Postiz only drops it in the TikTok inbox."""
    kind = account.get("provider", "tiktok")
    if kind == "tiktok":
        return {"__type": "tiktok", "privacy_level": account.get("privacy", "PUBLIC_TO_EVERYONE"), "duet": False,
                "stitch": False, "comment": True, "autoAddMusic": "no", "brand_content_toggle": False,
                "brand_organic_toggle": False,
                "content_posting_method": "UPLOAD" if account.get("mode") == "inbox" else "DIRECT_POST"}
    if kind == "instagram":
        return {"__type": "instagram", "post_type": "post", "is_trial_reel": False, "collaborators": []}
    if kind == "youtube":
        return {"__type": "youtube", "title": (clip.get("title") or "Clip")[:100], "type": account.get("privacy", "public"),
                "tags": []}
    return {"__type": kind}


def publish(clip: dict, account: dict) -> tuple[str, str | None]:
    headers = _headers()
    with open(clip["path"], "rb") as f:
        up = requests.post(f"{base()}/upload", headers=headers, files={"file": (os.path.basename(clip["path"]), f, "video/mp4")},
                           timeout=600)
    if up.status_code not in (200, 201):
        raise RuntimeError(f"Postiz upload failed: {up.status_code} {up.text[:200]}")
    media = up.json()
    body = {"type": "now", "date": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "shortLink": False, "tags": [],
            "posts": [{"integration": {"id": account["integration_id"]},
                       "value": [{"content": clip["post_text"], "image": [{"id": media["id"], "path": media["path"]}]}],
                       "settings": provider_settings(account, clip)}]}
    r = requests.post(f"{base()}/posts", headers=headers, json=body, timeout=120)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Postiz would not post it: {r.status_code} {r.text[:300]}")
    data = r.json()
    first = data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else {}
    return str(first.get("postId") or first.get("id") or "postiz"), None
