"""TikTok Content Posting API (https://developers.tiktok.com/doc/content-posting-api-get-started).

"inbox" mode uploads the clip to the account's TikTok inbox; you finish posting in the app.
"direct" mode posts straight away and needs TikTok to have audited your app.
"""

import math
import os
import time

import requests

from .... import tiktok_auth

API = "https://open.tiktokapis.com/v2"
MIN_CHUNK, MAX_CHUNK = 5 * 1024 * 1024, 64 * 1024 * 1024
CHUNK = 10 * 1024 * 1024


def _chunks(size: int) -> tuple[int, int]:
    if size <= MAX_CHUNK:
        return size, 1
    # Every chunk is CHUNK bytes except the last, which absorbs the remainder.
    return CHUNK, math.floor(size / CHUNK)


def publish(clip: dict, account: dict) -> tuple[str, str | None]:
    # A connected TikTok (Settings page) renews itself; a token pasted into the account's field is used as before.
    token = tiktok_auth.access_token() or os.environ[account["access_token_env"]]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    path = clip["path"]
    size = os.path.getsize(path)
    chunk_size, count = _chunks(size)
    source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk_size, "total_chunk_count": count}

    if account.get("mode", "inbox") == "direct":
        body = {"post_info": {"title": clip["post_text"][:2200], "privacy_level": account.get("privacy", "PUBLIC_TO_EVERYONE"),
                              "disable_duet": False, "disable_comment": False, "disable_stitch": False},
                "source_info": source}
        url = f"{API}/post/publish/video/init/"
    else:
        body = {"source_info": source}
        url = f"{API}/post/publish/inbox/video/init/"

    r = requests.post(url, headers=headers, json=body, timeout=60)
    data = r.json()
    if r.status_code != 200 or data.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok init failed: {data.get('error') or r.text}")
    upload_url, publish_id = data["data"]["upload_url"], data["data"]["publish_id"]

    with open(path, "rb") as f:
        for i in range(count):
            first = i * chunk_size
            last = size - 1 if i == count - 1 else first + chunk_size - 1
            f.seek(first)
            part = f.read(last - first + 1)
            put = requests.put(upload_url, data=part, timeout=300, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(part)),
                "Content-Range": f"bytes {first}-{last}/{size}"})
            if put.status_code not in (200, 201, 206):
                raise RuntimeError(f"TikTok upload failed on chunk {i + 1}: {put.status_code} {put.text}")

    # Wait briefly for TikTok to accept it.
    for _ in range(20):
        s = requests.post(f"{API}/post/publish/status/fetch/", headers=headers, json={"publish_id": publish_id}, timeout=30).json()
        status = s.get("data", {}).get("status")
        if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            break
        if status == "FAILED":
            raise RuntimeError(f"TikTok rejected the clip: {s.get('data', {}).get('fail_reason')}")
        time.sleep(6)
    return publish_id, None
