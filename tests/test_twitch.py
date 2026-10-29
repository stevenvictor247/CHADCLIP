
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
    from hq import clipbudget
    from hq.agents.chad import sources
    db.init()
    monkeypatch.setattr(clipbudget, "room", lambda: (5, ""))   # other tests leave clips queued in the shared db
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


def test_scheduled_round_clips_added_streamers_and_says_what_happened(monkeypatch):
    from hq import clipbudget
    from hq.agents.chad import sources
    db.init()
    monkeypatch.setattr(clipbudget, "room", lambda: (5, ""))   # other tests leave clips queued in the shared db
    monkeypatch.setenv("TWITCH_CLIENT_ID", "id")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "secret")
    monkeypatch.setattr(twitch, "permissions", lambda: {"jynxzi": "clipping policy", "ghost": "ok policy"})
    monkeypatch.setattr(twitch, "user_id", lambda login: "7" if login == "jynxzi" else None)
    monkeypatch.setattr(twitch, "top_clips", lambda uid, days, n: [{"id": "c1", "url": "u", "title": "T", "views": 9, "streamer": "Jynxzi"}])
    monkeypatch.setattr(sources, "_seen", lambda: set())
    monkeypatch.setattr(sources, "download", lambda url: {"path": "x.mp4", "url": url, "id": "c1"})
    monkeypatch.setattr(chad_agent.Chad, "clip_whole", lambda self, *a: 1)
    total, summary = chad_agent.Chad().run_permitted_streamers(1, {}, 0, [])
    assert total == 1
    assert any("Jynxzi" in s for s in summary) and any("ghost" in s for s in summary)


def test_missing_twitch_keys_are_reported_not_silent(monkeypatch):
    monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
    monkeypatch.setattr(twitch, "permissions", lambda: {"jynxzi": "clipping policy"})
    total, summary = chad_agent.Chad().run_permitted_streamers(1, {}, 0, [])
    assert total == 0 and "Twitch keys missing" in summary[0]


def test_adding_a_streamer_queues_a_chad_round_once(tmp_path, monkeypatch):
    from hq import creators
    db.init()
    (tmp_path / "streamers.yaml").write_text("permissions:\n")
    monkeypatch.setattr(creators, "CONFIG_DIR", tmp_path)
    creators.add_allowed("jynxzi", "public open-clipping policy")
    creators.add_allowed("xqc", "public open-clipping policy")
    assert len(db.rows("SELECT 1 FROM tasks WHERE agent = 'Chad' AND status = 'queued'")) == 1
