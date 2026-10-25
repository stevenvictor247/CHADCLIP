"""Posting seatbelts (a daily cap and a gap per account) and the Pause All switch."""

from types import SimpleNamespace

import pytest

from hq import db, worker
from hq.agents.chad import publish


@pytest.fixture
def board(monkeypatch, tmp_path):
    db.init()
    db.execute("UPDATE clips SET status = 'rejected' WHERE status = 'approved'")  # leftovers from other tests
    db.execute("DELETE FROM posts WHERE account IN ('main', 'other')")
    sent = []

    def fake_publish(clip, account):
        if account.get("broken"):
            raise RuntimeError("token expired")
        sent.append((clip["id"], account["name"]))
        return f"ext-{clip['id']}", None

    monkeypatch.setitem(publish.PLATFORMS, "tiktok", SimpleNamespace(publish=fake_publish))
    accounts = [{"name": "main", "platform": "tiktok", "enabled": True}]
    monkeypatch.setattr(publish, "accounts_for", lambda creator: accounts)
    monkeypatch.setenv("HQ_MAX_POSTS_PER_DAY", "2")
    monkeypatch.setenv("HQ_POST_GAP_MINUTES", "0")
    monkeypatch.delenv("HQ_PAUSED", raising=False)
    video = tmp_path / "c.mp4"
    video.write_bytes(b"x")

    def clip():
        return db.execute("INSERT INTO clips (creator, start_s, end_s, path, title, caption, hashtags, status, created_at) "
                          "VALUES ('You', 0, 10, ?, 't', 'c', '[]', 'approved', ?)", str(video), db.now())
    return SimpleNamespace(sent=sent, clip=clip, accounts=accounts)


def _status(cid):
    return db.rows("SELECT status FROM clips WHERE id = ?", cid)[0]["status"]


def test_daily_cap_holds_extra_clips_back(board):
    a, b, c = board.clip(), board.clip(), board.clip()
    publish.publish_approved()
    assert [s[0] for s in board.sent] == [a, b]
    assert _status(a) == _status(b) == "posted"
    assert _status(c) == "approved"                    # waits for tomorrow instead of a spammy burst


def test_gap_between_posts(board, monkeypatch):
    monkeypatch.setenv("HQ_POST_GAP_MINUTES", "60")
    a, b = board.clip(), board.clip()
    out = publish.publish_approved()
    assert [s[0] for s in board.sent] == [a]
    assert _status(b) == "approved" and any("waiting 60 minutes" in line for line in out)


def test_a_failed_post_is_not_retried_by_itself(board):
    board.accounts[0]["broken"] = True
    a = board.clip()
    publish.publish_approved()
    publish.publish_approved()
    assert _status(a) == "failed"
    assert len(db.rows("SELECT 1 FROM posts WHERE clip_id = ?", a)) == 1   # one attempt, never a double post


def test_practice_account_has_no_limits(board):
    board.accounts[:] = [{"name": "practice", "platform": "practice", "enabled": True}]
    assert publish.wait_reason(board.accounts[0]) is None


def test_pause_all_stops_posting_and_agents(board, monkeypatch):
    a = board.clip()
    monkeypatch.setenv("HQ_PAUSED", "true")
    assert "paused" in publish.publish_approved()[0]
    tid = db.create_task("Sweep", "should wait", created_by="test")
    worker.tick()
    assert db.rows("SELECT status FROM tasks WHERE id = ?", tid)[0]["status"] == "queued"
    assert _status(a) == "approved" and not board.sent
    monkeypatch.setenv("HQ_PAUSED", "false")
    publish.publish_approved()
    assert board.sent == [(a, "main")]
    db.update_task(tid, "done")


def test_pause_button_api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import hq.api
    monkeypatch.setattr(hq.settings, "SETTINGS_PATH", tmp_path / "settings.json")
    c = TestClient(hq.api.app, headers={"X-HQ": "1"})
    assert c.post("/api/pause", json={"paused": True}).json() == {"paused": True}
    assert c.get("/api/pause").json()["paused"] is True
    assert c.get("/api/state").json()["paused"] is True
    assert c.post("/api/pause", json={"paused": False}).json() == {"paused": False}


def test_pause_from_phone(monkeypatch, tmp_path):
    import hq.settings
    from hq import relay
    monkeypatch.setattr(hq.settings, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(relay, "owner_id", lambda: 7)
    said = []
    monkeypatch.setattr(relay, "api", lambda method, **kw: said.append(kw.get("text")))
    relay.handle_message({"from": {"id": 7}, "chat": {"id": 7}, "text": "Pause"})
    assert publish.paused() and "paused" in said[-1]
    relay.handle_message({"from": {"id": 7}, "chat": {"id": 7}, "text": "resume"})
    assert not publish.paused()
    monkeypatch.delenv("HQ_PAUSED", raising=False)


def test_try_posting_again_button(board):
    board.accounts[0]["broken"] = True
    a = board.clip()
    publish.publish_approved()
    assert _status(a) == "failed"
    board.accounts[0]["broken"] = False
    from fastapi.testclient import TestClient

    import hq.api
    c = TestClient(hq.api.app, headers={"X-HQ": "1"})
    assert "posted again to tiktok (main)" in c.post(f"/api/clips/{a}/retry").json()["message"]
    publish.publish_approved()
    assert _status(a) == "posted" and board.sent == [(a, "main")]
    assert c.post(f"/api/clips/{a}/retry").status_code == 400      # nothing failed any more
    lib = next(x for x in c.get("/api/state").json()["clips"] if x["id"] == a)
    assert [p["status"] for p in lib["posts"]] == ["retried", "posted"]


def test_dashboard_can_tell_when_the_agents_stopped(monkeypatch, tmp_path):
    import os
    import time as _time

    from fastapi.testclient import TestClient

    import hq.api
    monkeypatch.setattr(worker, "ALIVE_PATH", tmp_path / "worker_alive.txt")
    c = TestClient(hq.api.app)
    assert c.get("/api/pause").json()["worker_seconds_ago"] is None      # not started yet: no false alarm
    monkeypatch.delenv("HQ_PAUSED", raising=False)
    monkeypatch.setattr(worker, "queue_scheduled", lambda state: None)
    monkeypatch.setattr(worker, "football_tick", lambda: None)
    monkeypatch.setattr(worker, "run_next_task", lambda *a: False)
    monkeypatch.setattr(worker, "publish_approved", lambda: [])
    monkeypatch.setattr(worker, "daily_report", lambda state: None)
    monkeypatch.setattr(worker, "daily_backup", lambda state: None)
    monkeypatch.setattr(worker, "STATE_PATH", tmp_path / "state.json")
    worker.tick()
    assert c.get("/api/pause").json()["worker_seconds_ago"] <= 2
    old = _time.time() - 3600
    os.utime(tmp_path / "worker_alive.txt", (old, old))
    assert c.get("/api/pause").json()["worker_seconds_ago"] >= 3599


# ---- Instagram ----

class _R:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.text = data, status, str(data)

    def json(self):
        return self._d


def test_instagram_uploads_straight_when_no_public_url(monkeypatch, tmp_path):
    from hq.agents.chad.publish import instagram as ig
    video = tmp_path / "c.mp4"
    video.write_bytes(b"12345")
    monkeypatch.delenv("HQ_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("IG_U", "42")
    monkeypatch.setenv("IG_T", "tok")
    calls = []

    def post(url, **k):
        calls.append((url, k))
        if url.endswith("/media"):
            return _R({"id": "cont1"})
        if "rupload" in url:
            return _R({"success": True})
        return _R({"id": "media9"})
    monkeypatch.setattr(ig.requests, "post", post)
    monkeypatch.setattr(ig.requests, "get", lambda *a, **k: _R({"status_code": "FINISHED"}))
    ext, url = ig.publish({"path": str(video), "post_text": "hi"}, {"ig_user_id_env": "IG_U", "access_token_env": "IG_T"})
    assert ext == "media9"
    assert calls[0][1]["data"]["upload_type"] == "resumable" and "video_url" not in calls[0][1]["data"]
    assert calls[1][1]["headers"] == {"Authorization": "OAuth tok", "offset": "0", "file_size": "5"}


def test_instagram_uses_public_url_when_set(monkeypatch, tmp_path):
    from hq.agents.chad.publish import instagram as ig
    monkeypatch.setenv("HQ_PUBLIC_BASE_URL", "https://x.example/")
    monkeypatch.setenv("IG_U", "42")
    monkeypatch.setenv("IG_T", "tok")
    seen = []
    monkeypatch.setattr(ig.requests, "post", lambda url, **k: seen.append(url) or _R({"id": "a"}))
    monkeypatch.setattr(ig.requests, "get", lambda *a, **k: _R({"status_code": "FINISHED"}))
    ig.publish({"path": "/d/c.mp4", "post_text": "hi"}, {"ig_user_id_env": "IG_U", "access_token_env": "IG_T"})
    assert not any("rupload" in u for u in seen)


def test_connect_instagram_saves_page_token_and_account(monkeypatch):
    from hq import instagram_auth as ia
    monkeypatch.setenv("IG_APP_ID", "app")
    monkeypatch.setenv("IG_APP_SECRET", "sec")
    saved = {}
    monkeypatch.setattr(ia.settings, "save", lambda v: saved.update(v) or list(v))

    def get(url, params=None, **k):
        if url.endswith("oauth/access_token"):
            return _R({"access_token": "LONGUSER"})
        if url.endswith("me/accounts"):
            assert params["access_token"] == "LONGUSER"
            return _R({"data": [{"name": "NoIG", "access_token": "x"},
                                {"name": "Pg", "access_token": "PAGETOK", "instagram_business_account": {"id": "17841"}}]})
        return _R({"username": "chadclips"})
    monkeypatch.setattr(ia.requests, "get", get)
    msg = ia.connect("s" * 30)
    assert saved == {"IG_USER_ID_MAIN": "17841", "IG_ACCESS_TOKEN_MAIN": "PAGETOK"}
    assert "@chadclips" in msg


def test_connect_instagram_explains_problems(monkeypatch):
    from hq import instagram_auth as ia
    monkeypatch.setenv("IG_APP_ID", "app")
    monkeypatch.setenv("IG_APP_SECRET", "sec")
    monkeypatch.setattr(ia.settings, "save", lambda v: [])
    monkeypatch.setattr(ia.requests, "get", lambda url, **k: _R({"access_token": "L"}) if "oauth" in url else _R({"data": []}))
    with pytest.raises(ia.InstagramError, match="Pages"):
        ia.connect("s" * 30)
    monkeypatch.setattr(ia.requests, "get", lambda url, **k: _R({"error": {"message": "bad"}}))
    with pytest.raises(ia.InstagramError, match="bad"):
        ia.connect("s" * 30)
    monkeypatch.delenv("IG_APP_ID")
    with pytest.raises(ia.InstagramError, match="IG_APP_ID"):
        ia.connect("s" * 30)
