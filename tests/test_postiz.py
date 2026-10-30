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


# ---- several accounts: clips take turns --------------------------------------------------------------------
from types import SimpleNamespace as NS  # noqa: E402

from hq import db, settings  # noqa: E402
from hq.agents.chad import publish  # noqa: E402


@pytest.fixture
def pool(monkeypatch, tmp_path):
    db.init()
    db.execute("UPDATE clips SET status = 'rejected' WHERE status = 'approved'")
    db.execute("DELETE FROM posts WHERE account LIKE 'pz_%'")
    sent = []

    def fake_publish(clip, account):
        sent.append((clip["id"], account["name"]))
        return f"ext-{clip['id']}", None

    monkeypatch.setitem(publish.PLATFORMS, "postiz", NS(publish=fake_publish))
    accounts = [{"name": f"pz_{n}", "platform": "postiz", "provider": "tiktok", "enabled": True, "integration_id": n}
                for n in "ab"]
    monkeypatch.setattr(publish, "accounts_for", lambda creator: accounts)
    monkeypatch.setattr(publish, "load_accounts", lambda: accounts)
    monkeypatch.setenv("HQ_MAX_POSTS_PER_DAY", "2")
    monkeypatch.setenv("HQ_POST_GAP_MINUTES", "0")
    monkeypatch.delenv("HQ_PAUSED", raising=False)
    video = tmp_path / "c.mp4"
    video.write_bytes(b"x")

    def clip():
        return db.execute("INSERT INTO clips (creator, start_s, end_s, path, title, caption, hashtags, status, created_at) "
                          "VALUES ('You', 0, 10, ?, 't', 'c', '[]', 'approved', ?)", str(video), db.now())
    return NS(sent=sent, clip=clip, accounts=accounts)


def test_each_clip_goes_to_one_account_and_they_take_turns(pool):
    ids = [pool.clip() for _ in range(4)]
    publish.publish_approved()
    assert sorted(c for c, _ in pool.sent) == sorted(ids)            # nothing posted twice
    assert len({c for c, _ in pool.sent}) == 4
    names = [a for _, a in pool.sent]
    assert names.count("pz_a") == 2 and names.count("pz_b") == 2     # shared evenly


def test_account_limits_hold_clips_back(pool):
    ids = [pool.clip() for _ in range(5)]
    publish.publish_approved()
    assert len(pool.sent) == 4                                       # 2 accounts x 2 a day
    left = [i for i in ids if i not in {c for c, _ in pool.sent}]
    assert len(left) == 1 and db.rows("SELECT status FROM clips WHERE id = ?", left[0])[0]["status"] == "approved"


def test_per_account_limit_overrides_general_limit(pool):
    pool.accounts[0]["max_posts_per_day"] = 1
    for _ in range(3):
        pool.clip()
    publish.publish_approved()
    names = [a for _, a in pool.sent]
    assert names.count("pz_a") == 1 and names.count("pz_b") == 2


def test_rotate_false_posts_every_clip_there_too(pool):
    pool.accounts[0]["rotate"] = False
    c = pool.clip()
    publish.publish_approved()
    assert sorted(a for cid, a in pool.sent if cid == c) == ["pz_a", "pz_b"]


def test_nothing_posts_when_paused(pool, monkeypatch):
    monkeypatch.setenv("HQ_PAUSED", "true")
    pool.clip()
    publish.publish_approved()
    assert pool.sent == []


def test_only_approved_clips_post(pool):
    c = pool.clip()
    db.execute("UPDATE clips SET status = 'pending_approval' WHERE id = ?", c)
    publish.publish_approved()
    assert pool.sent == []


def test_capacity_adds_up_a_pool(pool):
    assert publish.daily_capacity() == 4


def test_failed_post_goes_to_one_account_only(pool, monkeypatch):
    c = pool.clip()
    monkeypatch.setitem(publish.PLATFORMS, "postiz", NS(publish=lambda clip, account: (_ for _ in ()).throw(RuntimeError("boom"))))
    publish.publish_approved()
    publish.publish_approved()                                       # a failure is never retried on its own
    assert db.rows("SELECT status FROM clips WHERE id = ?", c)[0]["status"] == "failed"
    assert len(db.rows("SELECT 1 FROM posts WHERE clip_id = ? AND status = 'failed'", c)) == 1


def test_label_limit_and_add_account_edit_the_yaml(monkeypatch, tmp_path):
    import shutil
    cfg = tmp_path / "config"
    shutil.copytree(settings.CONFIG_DIR, cfg)
    monkeypatch.setattr(settings, "CONFIG_DIR", cfg)
    settings.set_account_field("postiz_tiktok", "label", "Funny clips")
    settings.set_account_field("postiz_tiktok", "max_posts_per_day", "2")
    settings.set_account_field("postiz_tiktok", "rotate", "false")
    a = next(x for x in settings.accounts() if x["name"] == "postiz_tiktok")
    assert a["label"] == "Funny clips" and a["max_posts_per_day"] == 2 and a["rotate"] is False
    settings.set_account_field("postiz_tiktok", "max_posts_per_day", "")
    settings.add_postiz_account("postiz_tiktok_2", "abc123", "Second", "tiktok")
    accts = {x["name"]: x for x in settings.accounts()}
    assert accts["postiz_tiktok_2"]["enabled"] is False and accts["postiz_tiktok_2"]["integration_id"] == "abc123"
    assert "max_posts_per_day" not in accts["postiz_tiktok"] and accts["youtube_main"]["enabled"] is False
    assert "# Clipping accounts" in (cfg / "accounts.yaml").read_text()
    for bad in (("postiz_tiktok_2", "xyz999"), ("Bad Name", "xyz999"), ("postiz_x", "../../etc")):
        with pytest.raises(ValueError):
            settings.add_postiz_account(*bad)
    with pytest.raises(ValueError):
        settings.set_account_field("postiz_tiktok", "max_posts_per_day", "lots")
    with pytest.raises(KeyError):
        settings.set_account_field("nope", "label", "x")


def test_settings_api_saves_account_edits(monkeypatch, tmp_path):
    import shutil

    from fastapi.testclient import TestClient

    from hq import api
    cfg = tmp_path / "config"
    shutil.copytree(settings.CONFIG_DIR, cfg)
    monkeypatch.setattr(settings, "CONFIG_DIR", cfg)
    c = TestClient(api.app)
    body = {"account_edits": {"postiz_tiktok": {"label": "Main"}}, "new_account": {"name": "postiz_tiktok_3", "integration_id": "id333"}}
    assert c.post("/api/settings", json=body).status_code == 403
    assert c.post("/api/settings", json=body, headers={"X-HQ": "1"}).status_code == 200
    got = {a["name"]: a for a in c.get("/api/settings").json()["accounts"]}
    assert got["postiz_tiktok"]["label"] == "Main" and got["postiz_tiktok_3"]["enabled"] is False
    assert c.post("/api/settings", json={"new_account": {"name": "postiz_tiktok_3", "integration_id": "id444"}},
                  headers={"X-HQ": "1"}).status_code == 400
