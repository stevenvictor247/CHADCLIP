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
    assert c.get("/api/pause").json() == {"paused": True}
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
