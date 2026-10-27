"""Instagram Reels via the Instagram Graph API (Business or Creator account).

By default the clip is uploaded straight to Instagram (resumable upload), so no public address is needed.
If HQ_PUBLIC_BASE_URL is set, Instagram downloads the clip from there instead (the dashboard serves it at /clips).
"""

import os
import time
from pathlib import Path

import requests

from ....config import PUBLIC_BASE_URL

GRAPH = os.getenv("HQ_GRAPH_API", "https://graph.facebook.com/v25.0")
RUPLOAD = os.getenv("HQ_IG_UPLOAD_API", "https://rupload.facebook.com/ig-api-upload/v25.0")


def publish(clip: dict, account: dict) -> tuple[str, str | None]:
    user_id = os.environ[account["ig_user_id_env"]]
    token = os.environ[account["access_token_env"]]
    base = os.getenv("HQ_PUBLIC_BASE_URL", PUBLIC_BASE_URL).rstrip("/")
    fields = {"media_type": "REELS", "caption": clip["post_text"][:2200], "share_to_feed": "true",
              "access_token": token}
    if base:
        fields["video_url"] = f"{base}/clips/{Path(clip['path']).name}"
    else:
        fields["upload_type"] = "resumable"

    r = requests.post(f"{GRAPH}/{user_id}/media", timeout=60, data=fields)
    data = r.json()
    if "id" not in data:
        raise RuntimeError(f"Instagram container failed: {data}")
    container = data["id"]

    if not base:
        size = os.path.getsize(clip["path"])
        with open(clip["path"], "rb") as f:
            up = requests.post(f"{RUPLOAD}/{container}", data=f, timeout=600, headers={
                "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)})
        if up.status_code != 200 or not up.json().get("success"):
            raise RuntimeError(f"Instagram upload failed: {up.status_code} {up.text[:300]}")

    for _ in range(40):  # up to ~4 minutes for Instagram to process the video
        status = requests.get(f"{GRAPH}/{container}", timeout=30,
                              params={"fields": "status_code,status", "access_token": token}).json()
        if status.get("status_code") == "FINISHED":
            break
        if status.get("status_code") == "ERROR":
            raise RuntimeError(f"Instagram couldn't process the clip: {status.get('status')}")
        time.sleep(6)
    else:
        raise RuntimeError("Instagram took too long to process the clip.")

    pub = requests.post(f"{GRAPH}/{user_id}/media_publish", timeout=60,
                        data={"creation_id": container, "access_token": token}).json()
    if "id" not in pub:
        raise RuntimeError(f"Instagram publish failed: {pub}")
    return pub["id"], None
