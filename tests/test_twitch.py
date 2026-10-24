from unittest import mock

from hq import db
from hq.agents.chad import agent as chad_agent, twitch


def test_twitch_skips_streamers_without_permission(tmp_path, monkeypatch):
    db.init()
    streamers = [{"login": "a", "name": "A", "id": "1", "viewers": 9}, {"login": "b", "name": "B", "id": "2", "viewers": 8}]
    monkeypatch.setattr(twitch, "top_streamers", lambda n: streamers)
    monkeypatch.setattr(twitch, "permissions", lambda: {"a": "clipping program"})
    got = []
    monkeypatch.setattr(twitch, "top_clips", lambda i, d, n: got.append(i) or [])
    out = chad_agent.Chad().run_twitch(1, 2, 1, 2, {})
    assert got == ["1"]
    assert "Skipped" in out and "B" in out and "A" not in out.split("Skipped")[1]


def test_vods_need_permission(monkeypatch):
    db.init()
    monkeypatch.setattr(twitch, "permissions", lambda: {})
    assert "Skipped" in chad_agent.Chad().run_vods(1, "jynxzi", 2, 3, {})


def test_vods_clip_viewer_clipped_moments(monkeypatch):
    from hq.agents.chad import sources
    db.init()
    monkeypatch.setattr(twitch, "permissions", lambda: {"jynxzi": "clipping policy"})
    monkeypatch.setattr(twitch, "user_id", lambda login: "7")
    monkeypatch.setattr(twitch, "recent_vods", lambda uid, n: [{"id": "99", "url": "https://twitch.tv/videos/99", "title": "Stream"}])
    monkeypatch.setattr(twitch, "vod_hot_moments", lambda uid, vod, n: [{"offset": 100.0, "duration": 20.0, "title": "Funny", "views": 5}])
    seen = set()
    monkeypatch.setattr(sources, "_seen", lambda: seen)
    monkeypatch.setattr(sources, "mark_seen", lambda k: seen.add(k))
    got = {}
    monkeypatch.setattr(sources, "download_section", lambda url, s, e: got.update(s=s, e=e) or {"path": "x.mp4", "url": url})
    monkeypatch.setattr(chad_agent.Chad, "clip_video", lambda self, *a, **k: 1)
    bot = chad_agent.Chad()
    out = bot.run_vods(1, "jynxzi", 1, 3, {})
    assert got == {"s": 80.0, "e": 145.0}
    assert "Made 1 clips" in out and "expire" in out
    assert "Made 0 clips" in bot.run_vods(1, "jynxzi", 1, 3, {})  # same moment isn't clipped twice
