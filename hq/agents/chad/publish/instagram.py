"""Instagram Reels via the Instagram Graph API (Business or Creator account).

Instagram downloads the video itself, so the clip must be reachable at a public URL:
set HQ_PUBLIC_BASE_URL to wherever data/clips is served (the dashboard serves it at /clips).
"""

import os
import time
from pathlib import Path

import requests

from ....config import PUBLIC_BASE_URL

GRAPH = os.getenv("HQ_GRAPH_API", "https://graph.facebook.com/v21.0")


def publish(clip: dict, account: dict) -> tuple[str, str | None]:
    if not PUBLIC_BASE_URL:
        raise RuntimeError("Set HQ_PUBLIC_BASE_URL so Instagram can fetch the clip.")
    user_id = os.environ[account["ig_user_id_env"]]
    token = os.environ[account["access_token_env"]]
    video_url = f"{PUBLIC_BASE_URL}/clips/{Path(clip['path']).name}"

    r = requests.post(f"{GRAPH}/{user_id}/media", timeout=60, data={
        "media_type": "REELS", "video_url": video_url, "caption": clip["post_text"][:2200],
        "share_to_feed": "true", "access_token": token})
    data = r.json()
    if "id" not in data:
        raise RuntimeError(f"Instagram container failed: {data}")
    container = data["id"]

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
