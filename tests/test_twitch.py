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
