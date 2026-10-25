"""Finding and downloading creators' videos with yt-dlp."""

import json
from pathlib import Path

import yaml
import yt_dlp

from ...config import CONFIG_DIR, DATA_DIR, SOURCES_DIR

SEEN_PATH = DATA_DIR / "chad_seen.json"


def load_creators() -> list[dict]:
    """creators.yaml plus every clipping campaign you've joined (the campaign is their recorded permission)."""
    from ... import campaigns
    with open(CONFIG_DIR / "creators.yaml") as f:
        listed = (yaml.safe_load(f) or {}).get("creators") or []
    listed = [c for c in listed if not _is_placeholder(c)]
    return listed + campaigns.as_creators()


def _is_placeholder(creator: dict) -> bool:
    """The "Example Creator" entry from the old sample file is not a real creator: never count or report it."""
    return str(creator.get("name", "")).strip().lower() == "example creator" and not is_permitted(creator)


def find_creator(name: str) -> dict | None:
    for c in load_creators():
        if c.get("name", "").lower() == name.lower():
            return c
    return None


def is_permitted(creator: dict) -> bool:
    return bool(str(creator.get("permission") or "").strip())


def _seen() -> set:
    if SEEN_PATH.exists():
        return set(json.loads(SEEN_PATH.read_text()))
    return set()


def mark_seen(video_id: str):
    seen = _seen()
    seen.add(video_id)
    SEEN_PATH.write_text(json.dumps(sorted(seen)))


def new_videos(source_url: str, limit: int) -> list[dict]:
    """Newest videos from a channel or playlist that Chad hasn't clipped yet."""
    opts = {"quiet": True, "extract_flat": "in_playlist", "playlistend": max(limit * 5, 10)}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(source_url, download=False)
    entries = info.get("entries") or [info]
    seen = _seen()
    fresh = []
    for e in entries:
        vid = e.get("id")
        if not vid or vid in seen:
            continue
        fresh.append({"id": vid, "url": e.get("url") or e.get("webpage_url") or source_url,
                      "title": e.get("title") or vid})
        if len(fresh) >= limit:
            break
    return fresh


def download(url: str) -> dict:
    """Download one video (up to 1080p mp4). Returns id, title, path and duration."""
    opts = {
        "quiet": True,
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(SOURCES_DIR / "%(id)s.%(ext)s"),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
    return {"id": info["id"], "title": info.get("title") or info["id"], "path": str(path),
            "url": info.get("webpage_url") or url, "duration": info.get("duration")}


def download_section(url: str, start: float, end: float) -> dict:
    """Download only start..end seconds of a long video (a Twitch VOD can be many hours)."""
    opts = {
        "quiet": True,
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "download_ranges": yt_dlp.utils.download_range_func(None, [(start, end)]),
        "force_keyframes_at_cuts": True,
        "outtmpl": str(SOURCES_DIR / f"%(id)s-{int(start)}.%(ext)s"),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
    return {"id": f"{info['id']}-{int(start)}", "title": info.get("title") or info["id"], "path": str(path),
            "url": f"{url}?t={int(start)}s"}
