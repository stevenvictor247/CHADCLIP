"""Chad: clips creators' videos into Shorts, Reels and TikToks for the clipping accounts."""

import json
import os
import re
from pathlib import Path

import yaml

from ... import db, ledger
from ...config import CLIPS_DIR, CONFIG_DIR
from ..base import Agent
from . import editor, moments, sources, twitch
from .transcribe import transcribe


def settings() -> dict:
    with open(CONFIG_DIR / "chad.yaml") as f:
        return yaml.safe_load(f) or {}


def _with_required_tags(tags: list, creator: dict) -> list:
    """Campaign rules often demand certain hashtags; make sure every clip carries them."""
    required = [t.lstrip("#@").strip() for t in creator.get("required_tags") or [] if t.strip()]
    have = {t.lower() for t in tags}
    return required + [t for t in tags if t.lower() not in {r.lower() for r in required}] if required else tags


class Chad(Agent):
    def __init__(self):
        every = settings().get("run_every_hours", 0)
        super().__init__(
            name="Chad",
            role="Clipper. Finds the best moments in chosen creators' videos, cuts them into vertical clips "
                 "with captions, and queues them for posting to TikTok, YouTube Shorts and Instagram Reels.",
            params_help='{"creator": "name from creators.yaml"} to clip one creator; {"url": "video link"} for '
                        'one video; {"twitch_top": 10, "days": 1, "per_streamer": 2} for the most-viewed recent Twitch clips of the top 10 streamers (only those with permission in streamers.yaml); {"vods": "jynxzi", "vod_count": 2, "per_vod": 3} for the funniest viewer-clipped moments in a permitted streamer\'s recent past streams (Twitch deletes VODs after ~14-60 days); {"clips": 3} clips per video. No params = check every permitted creator '
                        "for new videos.",
            schedule=[(every, "Check creators for new videos and clip them.", {})] if every else [],
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        """The scheduled round only has work when someone is allowed to be clipped: a creator with permission and a
        source, a joined campaign, or a Twitch streamer with permission (and the Twitch keys to look them up)."""
        if params:
            return None
        if any(sources.is_permitted(c) and c.get("sources") for c in sources.load_creators()):
            return None   # there is someone to check; if they keep having nothing new, the round backs off
        if os.getenv("TWITCH_CLIENT_ID") and os.getenv("TWITCH_CLIENT_SECRET") and any(twitch.permissions().values()):
            return None
        return True

    def run(self, task: dict) -> str:
        params = json.loads(task.get("params") or "{}")
        cfg = settings()
        count = int(params.get("clips") or cfg.get("clips_per_video", 3))

        if params.get("vods"):
            return self.run_vods(task["id"], str(params["vods"]), int(params.get("vod_count", 2)),
                                 int(params.get("per_vod", 3)), cfg)

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
                if params.get("creator"):   # asked for by name: say why; on the schedule it is just not on the list
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
        if not params.get("creator"):   # the scheduled round also covers streamers with permission in streamers.yaml
            total, summary = self.run_permitted_streamers(task["id"], cfg, total, summary)
        if not summary:
            return "No creators set up yet. Add some to config/creators.yaml."
        return f"Made {total} clips. " + "; ".join(summary)

    def run_permitted_streamers(self, task_id, cfg, total, summary):
        """Newest viewer clips from every streamer with permission recorded (the Clips tab box), skipping clips seen before."""
        if not (os.getenv("TWITCH_CLIENT_ID") and os.getenv("TWITCH_CLIENT_SECRET")):
            return total, summary
        for login, how in twitch.permissions().items():
            if not how:
                continue
            try:
                uid = twitch.user_id(login)
                clips = [c for c in twitch.top_clips(uid, 7, 3) if c["id"] not in sources._seen()] if uid else []
                for c in clips:
                    creator = {"name": c["streamer"], "credit": f"{c['streamer']} on Twitch",
                               "notes": "Funny moments, big reactions, chaos."}
                    video = sources.download(c["url"])
                    total += self.clip_whole(task_id, video, c["title"], c["views"], creator, cfg)
                    summary.append(f"{c['streamer']}: \"{c['title']}\" ({c['views']:,} views)")
            except Exception as e:   # one streamer failing shouldn't stop the rest
                db.log("Chad", f"Couldn't check {login}'s clips: {e}")
        return total, summary

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

    def run_vods(self, task_id, login, vod_count, per_vod, cfg) -> str:
        """Clip the funniest moments out of a permitted streamer's recent past broadcasts (VODs)."""
        login = login.lower().lstrip("@")
        if not twitch.permissions().get(login):
            return (f"Skipped: no permission recorded for {login} in streamers.yaml. "
                    "Add how you're allowed to clip them first.")
        if ledger.over_budget():
            return "Today's budget is spent, so I'm paused until tomorrow."
        uid = twitch.user_id(login)
        if not uid:
            return f"Couldn't find a Twitch channel called {login}."
        vods = twitch.recent_vods(uid, vod_count)
        if not vods:
            return (f"{login} has no past broadcasts saved. Twitch deletes them after about 14 days "
                    "(60 for partners), unless the streamer saved highlights.")
        creator = {"name": login, "credit": f"{login} on Twitch", "notes": "Funny moments, big reactions, chaos."}
        made, lines = 0, []
        for vod in vods:
            for m in twitch.vod_hot_moments(uid, vod["id"], per_vod):
                key = f"vod:{vod['id']}:{int(m['offset'])}"
                if key in sources._seen():
                    continue
                start = max(0.0, m["offset"] - 20)
                end = m["offset"] + m["duration"] + 25
                try:
                    video = sources.download_section(vod["url"], start, end)
                    n = self.clip_video(task_id, video["path"], m["title"] or vod["title"], video["url"],
                                        creator, 1, cfg)
                except Exception as e:  # sub-only or expired VOD, ffmpeg trouble: keep going with the rest
                    db.log("Chad", f"Skipped a moment in {vod['title']}: {e}")
                    continue
                sources.mark_seen(key)
                made += n
                lines.append(f"\"{m['title']}\" ({m['views']:,} clip views)")
        out = f"Made {made} clips from {login}'s last {len(vods)} streams. " + "; ".join(lines)
        if not lines:
            out += "No viewer-clipped moments found there yet (or all already done)."
        return out + " Note: Twitch VODs expire after ~14-60 days, so this only reaches recent streams."

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
            "hashtags, score, reason, captioned, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            task_id, creator["name"], video["url"], title, 0, length, str(out), title[:80],
            f"{title}\n\nCredit: {creator['credit']}", json.dumps(["twitch", "streamer", "funny", "fyp"]),
            float(views), f"{views:,} views on Twitch in the last day(s).",
            int(bool(cfg.get("captions", True) and words)), db.now())
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
                "hashtags, score, reason, captioned, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                task_id, creator.get("name"), url, title, m["start"], m["end"], str(out), m["title"], caption,
                json.dumps(_with_required_tags(m["hashtags"], creator)), m.get("score"), m.get("reason"),
                int(bool(cfg.get("captions", True) and words)), db.now(),
            )
            if creator.get("campaign_id"):
                db.execute("UPDATE clips SET campaign_id = ? WHERE id = ?", creator["campaign_id"], clip_id)
            db.log("Chad", f"Clip #{clip_id} ready for approval: {m['title']}")
        return len(picked)
