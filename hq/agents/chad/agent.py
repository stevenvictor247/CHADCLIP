"""Chad: clips creators' videos into Shorts, Reels and TikToks for the clipping accounts."""

import json
import re
from pathlib import Path

import yaml

from ... import db
from ...config import CLIPS_DIR, CONFIG_DIR
from ..base import Agent
from . import editor, moments, sources, twitch
from .transcribe import transcribe


def settings() -> dict:
    with open(CONFIG_DIR / "chad.yaml") as f:
        return yaml.safe_load(f) or {}


class Chad(Agent):
    def __init__(self):
        every = settings().get("run_every_hours", 0)
        super().__init__(
            name="Chad",
            role="Clipper. Finds the best moments in chosen creators' videos, cuts them into vertical clips "
                 "with captions, and queues them for posting to TikTok, YouTube Shorts and Instagram Reels.",
            params_help='{"creator": "name from creators.yaml"} to clip one creator; {"url": "video link"} for '
                        'one video; {"twitch_top": 10, "days": 1, "per_streamer": 2} for the most-viewed recent Twitch clips of the top 10 streamers (only those with permission in streamers.yaml); {"clips": 3} clips per video. No params = check every permitted creator '
                        "for new videos.",
            schedule=[(every, "Check creators for new videos and clip them.", {})] if every else [],
        )

    def run(self, task: dict) -> str:
        params = json.loads(task.get("params") or "{}")
        cfg = settings()
        count = int(params.get("clips") or cfg.get("clips_per_video", 3))

        if params.get("twitch_top"):
            return self.run_twitch(task["id"], int(params["twitch_top"]), int(params.get("days", 1)),
                                   int(params.get("per_streamer", 2)), cfg)

        if params.get("file"):
            creator = sources.find_creator(params.get("creator", "")) or {"name": params.get("creator", "Local file")}
            path = params["file"]
            made = self.clip_video(task["id"], path, Path(path).stem, path, creator, count, cfg)
            return f"Made {made} clips from {Path(path).name}."

        if params.get("url"):
            creator = sources.find_creator(params.get("creator", "")) or {}
            if not sources.is_permitted(creator):
                return ("Skipped: that link isn't from a creator with permission set in creators.yaml. "
                        "Add the creator and how you're allowed to clip them, then try again.")
            video = sources.download(params["url"])
            made = self.clip_video(task["id"], video["path"], video["title"], video["url"], creator, count, cfg)
            sources.mark_seen(video["id"])
            return f"Made {made} clips from \"{video['title']}\"."

        creators = sources.load_creators()
        if params.get("creator"):
            creators = [c for c in creators if c.get("name", "").lower() == params["creator"].lower()]
            if not creators:
                return f"No creator called {params['creator']} in creators.yaml."
        summary, total = [], 0
        for creator in creators:
            if not sources.is_permitted(creator):
                summary.append(f"{creator.get('name')}: skipped, no permission recorded")
                continue
            for src in creator.get("sources", []):
                for v in sources.new_videos(src, int(creator.get("max_videos_per_run", 1))):
                    db.log("Chad", f"Clipping \"{v['title']}\" from {creator['name']}")
                    video = sources.download(v["url"])
                    made = self.clip_video(task["id"], video["path"], video["title"], video["url"], creator, count, cfg)
                    sources.mark_seen(v["id"])
                    total += made
                    summary.append(f"{creator['name']}: {made} clips from \"{video['title']}\"")
        if not summary:
            return "No creators set up yet. Add some to config/creators.yaml."
        return f"Made {total} clips. " + "; ".join(summary)

    def run_twitch(self, task_id, top_n, days, per_streamer, cfg) -> str:
        """Most-viewed recent Twitch clips from the top streamers, for the ones you have permission to clip."""
        perms = twitch.permissions()
        made, skipped, lines = 0, [], []
        for s in twitch.top_streamers(top_n):
            if not perms.get(s["login"].lower()):
                skipped.append(s["name"])
                continue
            creator = {"name": s["name"], "credit": f"{s['name']} on Twitch",
                       "notes": "Funny moments, big reactions, chaos."}
            for c in twitch.top_clips(s["id"], days, per_streamer):
                video = sources.download(c["url"])
                made += self.clip_whole(task_id, video, c["title"], c["views"], creator, cfg)
                lines.append(f"{s['name']}: \"{c['title']}\" ({c['views']:,} views)")
        out = f"Made {made} clips from Twitch's top {top_n}. " + "; ".join(lines)
        if skipped:
            out += f" Skipped (no permission recorded in streamers.yaml): {', '.join(skipped)}."
        return out

    def clip_whole(self, task_id, video, title, views, creator, cfg) -> int:
        """Twitch clips are already short and already picked by viewers, so use the whole thing."""
        length = min(editor.duration(video["path"]), float(cfg.get("max_clip_seconds", 59)))
        transcript = transcribe(video["path"])
        words = transcript["words"] if transcript else None
        out = CLIPS_DIR / f"{task_id}-{video['id'][:30]}.mp4"
        editor.render(video["path"], 0, length, out, words, cfg.get("layout", "blur"),
                      cfg.get("captions", True), int(cfg.get("caption_font_size", 64)))
        clip_id = db.execute(
            "INSERT INTO clips (task_id, creator, source_url, source_title, start_s, end_s, path, title, caption, "
            "hashtags, score, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            task_id, creator["name"], video["url"], title, 0, length, str(out), title[:80],
            f"{title}\n\nCredit: {creator['credit']}", json.dumps(["twitch", "streamer", "funny", "fyp"]),
            float(views), f"{views:,} views on Twitch in the last day(s).", db.now())
        db.log("Chad", f"Clip #{clip_id} ready for approval: {title}")
        sources.mark_seen(video["id"])
        return 1

    def clip_video(self, task_id, path, title, url, creator, count, cfg) -> int:
        length = editor.duration(path)
        transcript = transcribe(path)
        picked = moments.pick(transcript, length, title, creator, count,
                              float(cfg.get("min_clip_seconds", 15)), float(cfg.get("max_clip_seconds", 59)))
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "clip"
        words = transcript["words"] if transcript else None
        for i, m in enumerate(picked, 1):
            out = CLIPS_DIR / f"{task_id}-{slug}-{i}.mp4"
            editor.render(path, m["start"], m["end"], out, words, cfg.get("layout", "blur"),
                          cfg.get("captions", True), int(cfg.get("caption_font_size", 64)))
            caption = m["caption"]
            if creator.get("credit"):
                caption += f"\n\nCredit: {creator['credit']}"
            clip_id = db.execute(
                "INSERT INTO clips (task_id, creator, source_url, source_title, start_s, end_s, path, title, caption, "
                "hashtags, score, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                task_id, creator.get("name"), url, title, m["start"], m["end"], str(out), m["title"], caption,
                json.dumps(m["hashtags"]), m.get("score"), m.get("reason"), db.now(),
            )
            db.log("Chad", f"Clip #{clip_id} ready for approval: {m['title']}")
        return len(picked)
