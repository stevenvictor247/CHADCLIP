"""Twitch Helix API: who the top streamers are right now, and their most-watched recent clips.

Needs a free Twitch developer app: set TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET in .env.
"""

import os
from datetime import datetime, timedelta, timezone

import requests
import yaml

from ...config import CONFIG_DIR

HELIX = "https://api.twitch.tv/helix"
_token = None


def _headers() -> dict:
    global _token
    cid, secret = os.environ["TWITCH_CLIENT_ID"], os.environ["TWITCH_CLIENT_SECRET"]
    if _token is None:
        r = requests.post("https://id.twitch.tv/oauth2/token", timeout=30,
                          data={"client_id": cid, "client_secret": secret, "grant_type": "client_credentials"})
        r.raise_for_status()
        _token = r.json()["access_token"]
    return {"Client-Id": cid, "Authorization": f"Bearer {_token}"}


def top_streamers(n: int = 10) -> list[dict]:
    """The n most-watched live channels right now (one entry per channel)."""
    r = requests.get(f"{HELIX}/streams", headers=_headers(), params={"first": min(n, 100)}, timeout=30)
    r.raise_for_status()
    return [{"login": s["user_login"], "name": s["user_name"], "id": s["user_id"], "viewers": s["viewer_count"]}
            for s in r.json()["data"]][:n]


def small_streamers(min_viewers: int, max_viewers: int, language: str = "en", max_pages: int = 8) -> list[dict]:
    """Live channels with between min and max viewers. Twitch lists streams from most-watched down, so this pages
    past the big ones (100 channels a page) and keeps the mid-size ones."""
    out, cursor = [], None
    for _ in range(max_pages):
        params = {"first": 100, "language": language, **({"after": cursor} if cursor else {})}
        r = requests.get(f"{HELIX}/streams", headers=_headers(), params=params, timeout=30)
        r.raise_for_status()
        body = r.json()
        for s in body["data"]:
            if min_viewers <= s["viewer_count"] <= max_viewers:
                out.append({"login": s["user_login"], "name": s["user_name"], "id": s["user_id"],
                            "viewers": s["viewer_count"], "game": s.get("game_name", "")})
        cursor = (body.get("pagination") or {}).get("cursor")
        if not cursor or (body["data"] and body["data"][-1]["viewer_count"] < min_viewers):
            break
    return out


def profile(user_id: str) -> dict:
    """A channel's public bio and partner level."""
    r = requests.get(f"{HELIX}/users", headers=_headers(), params={"id": user_id}, timeout=30)
    r.raise_for_status()
    u = (r.json()["data"] or [{}])[0]
    return {"bio": u.get("description", ""), "type": u.get("broadcaster_type", "")}


def top_clips(broadcaster_id: str, days: int = 1, limit: int = 5) -> list[dict]:
    """Most-viewed clips from the last `days` days (Twitch returns them sorted by views)."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = requests.get(f"{HELIX}/clips", headers=_headers(), timeout=30,
                     params={"broadcaster_id": broadcaster_id, "started_at": since, "first": limit})
    r.raise_for_status()
    return [{"id": c["id"], "url": c["url"], "title": c["title"], "views": c["view_count"],
             "duration": c["duration"], "streamer": c["broadcaster_name"]} for c in r.json()["data"]]


def permissions() -> dict:
    """login -> how you're allowed to clip them, from config/streamers.yaml."""
    path = CONFIG_DIR / "streamers.yaml"
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    return {k.lower(): str(v or "").strip() for k, v in ((data or {}).get("permissions") or {}).items()}
