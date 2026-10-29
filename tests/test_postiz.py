"""Posting through a self-hosted Postiz: only its public HTTP API is used."""

from types import SimpleNamespace

import pytest

from hq import connections
from hq.agents.chad.publish import postiz

ACCOUNT = {"name": "postiz_tiktok", "platform": "postiz", "provider": "tiktok", "integration_id": "chan1"}


class Resp(SimpleNamespace):
    def json(self):
        return self.data


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("POSTIZ_URL", "http://localhost:5000/")
    monkeypatch.setenv("POSTIZ_API_KEY", "k123")


def test_tiktok_posts_directly_not_to_the_inbox(tmp_path, monkeypatch):
    video = tmp_path / "c.mp4"
    video.write_bytes(b"x")
    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw))
        if url.endswith("/upload"):
            return Resp(status_code=201, data={"id": "m1", "path": "http://localhost:5000/uploads/c.mp4"})
        return Resp(status_code=201, data=[{"postId": "p9", "integration": "chan1"}])

    monkeypatch.setattr(postiz.requests, "post", fake_post)
    ext, url = postiz.publish({"path": str(video), "post_text": "hi #fyp", "title": "t"}, ACCOUNT)
    assert ext == "p9"
    assert calls[0][0] == "http://localhost:5000/api/public/v1/upload" and calls[0][1]["headers"] == {"Authorization": "k123"}
    body = calls[1][1]["json"]["posts"][0]
    assert body["integration"] == {"id": "chan1"} and body["settings"]["content_posting_method"] == "DIRECT_POST"
    assert body["value"][0]["image"][0]["path"].endswith("c.mp4")


def test_failure_raises_so_the_clip_is_marked_failed(tmp_path, monkeypatch):
    video = tmp_path / "c.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(postiz.requests, "post", lambda url, **kw: Resp(status_code=500, text="boom", data={}))
    with pytest.raises(RuntimeError, match="Postiz upload failed"):
        postiz.publish({"path": str(video), "post_text": "x"}, ACCOUNT)


def test_missing_settings_say_what_to_do(monkeypatch):
    monkeypatch.delenv("POSTIZ_URL")
    with pytest.raises(RuntimeError, match="POSTIZ_URL"):
        postiz.base()


def test_settings_test_lists_channel_ids(monkeypatch):
    monkeypatch.setattr(connections.requests, "get", lambda url, **kw: Resp(
        status_code=200, data=[{"id": "chan1", "name": "Chad TikTok", "identifier": "tiktok"}]))
    r = connections.postiz({"POSTIZ_URL": "http://x:5000", "POSTIZ_API_KEY": "k"})
    assert r["ok"] and "chan1" in r["message"]
    assert connections.postiz({"POSTIZ_URL": "http://x", "POSTIZ_API_KEY": "k"}, ACCOUNT)["ok"]
    assert not connections.postiz({"POSTIZ_URL": "http://x", "POSTIZ_API_KEY": "k"}, {**ACCOUNT, "integration_id": "nope"})["ok"]
