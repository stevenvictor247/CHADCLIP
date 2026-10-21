import json

import pytest

from hq import db, relay


@pytest.fixture
def telegram(monkeypatch):
    """Pretend to be Telegram: record every call instead of using the network."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "42")
    calls = []
    monkeypatch.setattr(relay, "api", lambda method, files=None, **kw: calls.append((method, kw)) or {})
    db.init()
    return calls


def test_relay_is_off_without_token_and_owner(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_OWNER_ID", raising=False)
    assert not relay.enabled() and relay.start_in_background() is False
    relay.notify("hi")  # must not raise


def test_messages_from_strangers_are_ignored(telegram, monkeypatch):
    monkeypatch.setattr(relay.boss, "chat", lambda t: pytest.fail("a stranger reached the Boss"))
    relay.handle_update({"update_id": 1, "message": {"from": {"id": 7}, "chat": {"id": 7}, "text": "status"}})
    assert telegram == []


def test_owner_message_goes_to_the_boss(telegram, monkeypatch):
    monkeypatch.setattr(relay.boss, "chat", lambda t: f"boss heard: {t}")
    relay.handle_update({"update_id": 1, "message": {"from": {"id": 42}, "chat": {"id": 42}, "text": "status"}})
    assert telegram[-1][0] == "sendMessage" and telegram[-1][1]["text"] == "boss heard: status"


def test_button_tap_approves_clip_but_only_for_owner(telegram):
    cid = db.execute("INSERT INTO clips (creator, start_s, end_s, path, title, created_at) VALUES ('c', 0, 5, 'x.mp4', 't', ?)", db.now())
    cb = {"id": "1", "from": {"id": 7}, "data": f"clip:approve:{cid}", "message": {"message_id": 5, "chat": {"id": 7}}}
    relay.handle_update({"update_id": 1, "callback_query": cb})
    assert db.rows("SELECT status FROM clips WHERE id = ?", cid)[0]["status"] == "pending_approval"
    cb["from"]["id"] = 42
    relay.handle_update({"update_id": 2, "callback_query": cb})
    assert db.rows("SELECT status FROM clips WHERE id = ?", cid)[0]["status"] == "approved"


def test_pending_clips_are_sent_once(telegram, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    cid = db.execute("INSERT INTO clips (creator, start_s, end_s, path, title, score, created_at) VALUES ('Ana', 0, 5, ?, 'Big win', 8, ?)",
                     str(video), db.now())
    relay.push_pending_clips()
    first = [c for c in telegram if c[0] == "sendVideo"]
    assert len(first) == 1
    assert json.loads(first[0][1]["reply_markup"])["inline_keyboard"][0][0]["callback_data"] == f"clip:approve:{cid}"
    relay.push_pending_clips()
    assert len([c for c in telegram if c[0] == "sendVideo"]) == 1
