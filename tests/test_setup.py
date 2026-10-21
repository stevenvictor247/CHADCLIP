"""Test buttons, the getting-started checklist and the practice account."""

import json

import pytest
from fastapi.testclient import TestClient

from hq import boss, campaigns, connections, db, setup_check
from hq.agents.chad import publish
from hq.agents.chad.publish import practice


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    db.init()
    monkeypatch.setattr(connections, "RESULTS_PATH", tmp_path / "tests.json")
    monkeypatch.setattr(practice, "FOLDER", tmp_path / "practice-posts")
    for key in ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_OWNER_ID", "TWITCH_CLIENT_ID",
                "TWITCH_CLIENT_SECRET", "HQ_DAILY_BUDGET", "HQ_PRACTICE_POSTING", "HQ_PASSWORD"):
        monkeypatch.delenv(key, raising=False)


def test_claude_test_explains_each_problem_in_plain_words(monkeypatch):
    replies = iter([Resp(401), Resp(400, {"error": {"message": "Your credit balance is too low"}}), Resp(200)])
    monkeypatch.setattr(connections.requests, "post", lambda *a, **k: next(replies))
    assert "No key yet" in connections.run("claude")["message"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-old")
    assert "wrong or was deleted" in connections.run("claude")["message"]
    assert "no credit" in connections.run("claude")["message"]
    assert connections.run("claude") == {"ok": True, "message": "Claude key works."}
    assert connections.results()["claude"]["ok"] is True


def test_a_typed_but_unsaved_key_is_what_gets_tested(monkeypatch):
    seen = []
    monkeypatch.setattr(connections.requests, "post", lambda url, **k: seen.append(k["headers"]["x-api-key"]) or Resp(200))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-saved")
    connections.run("claude", {"ANTHROPIC_API_KEY": " sk-typed "})
    connections.run("claude", {"ANTHROPIC_API_KEY": ""})
    assert seen == ["sk-typed", "sk-saved"]


def test_telegram_test_sends_a_message_but_the_background_check_stays_quiet(monkeypatch):
    sent = []
    monkeypatch.setattr(connections.requests, "get", lambda *a, **k: Resp(200, {"ok": True, "result": {"username": "hq_bot"}}))
    monkeypatch.setattr(connections.requests, "post", lambda url, **k: sent.append(url) or Resp(200, {"ok": True}))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    assert "TELEGRAM_OWNER_ID is empty" in connections.run("telegram")["message"]
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "42")
    assert connections.run("telegram")["ok"] and len(sent) == 1
    connections.run_all()
    assert len(sent) == 1 and connections.results()["telegram"]["ok"]
    assert "_all" in connections.results()


def test_tiktok_expired_token_says_to_make_a_new_one(monkeypatch):
    monkeypatch.setattr(connections.requests, "get",
                        lambda *a, **k: Resp(401, {"error": {"code": "access_token_invalid", "message": "expired"}}))
    monkeypatch.setenv("TIKTOK_TEST_TOKEN", "act.x")
    r = connections.tiktok({"name": "tiktok_main", "access_token_env": "TIKTOK_TEST_TOKEN"})
    assert not r["ok"] and "about a day" in r["message"]


def test_checklist_on_a_fresh_install_points_at_the_claude_key_first():
    s = setup_check.summary()
    by_id = {i["id"]: i for i in s["items"]}
    assert not s["ready"] and s["next"]["id"] == "claude"
    assert by_id["claude"]["status"] == "todo" and by_id["claude"]["link"] == "/settings#k-ANTHROPIC_API_KEY"
    assert by_id["permission"]["status"] == "todo"
    assert by_id["posting"]["status"] == "todo" and "practice" in by_id["posting"]["detail"]
    assert by_id["budget"]["required"] is False


def test_checklist_shows_a_failed_test_as_a_problem(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    monkeypatch.setattr(connections.requests, "post", lambda *a, **k: Resp(401))
    assert {i["id"]: i for i in setup_check.items()}["claude"]["status"] == "todo"  # saved but never tested
    connections.run("claude")
    claude = {i["id"]: i for i in setup_check.items()}["claude"]
    assert claude["status"] == "problem" and "wrong or was deleted" in claude["detail"]


def test_practice_account_is_on_until_a_real_account_is():
    assert practice.account([{"name": "tiktok_main", "enabled": False}])["enabled"] is True
    assert practice.account([{"name": "tiktok_main", "enabled": True}])["enabled"] is False


def test_practice_posting_saves_the_clip_and_never_counts_for_campaigns(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake video")
    cid = campaigns.propose({"name": "Practice camp", "creator": "You", "platforms": [], "required_tags": [],
                             "content_sources": [], "red_flags": [], "score": 5})
    clip_id = db.execute("INSERT INTO clips (creator, start_s, end_s, path, title, caption, hashtags, status, campaign_id, "
                         "created_at) VALUES ('You', 0, 10, ?, 'My test', 'hello', '[\"hq\"]', 'approved', ?, ?)",
                         str(video), cid, db.now())
    publish.publish_approved()
    saved = practice.FOLDER / f"clip-{clip_id}.mp4"
    assert saved.read_bytes() == b"fake video"
    assert "#hq" in (practice.FOLDER / f"clip-{clip_id}.txt").read_text()
    post = db.rows("SELECT * FROM posts WHERE clip_id = ?", clip_id)[0]
    assert post["platform"] == "practice" and post["status"] == "posted"
    assert all(n["clip_id"] != clip_id for n in campaigns.sync_submissions())


def test_api_test_buttons_setup_card_and_try_chad(monkeypatch):
    from hq import api
    monkeypatch.setattr(api, "PASSWORD", "")
    c = TestClient(api.app)
    assert c.post("/api/test/claude", json={}).status_code == 403  # only HQ's own pages
    r = c.post("/api/test/claude", json={"values": {}}, headers={"X-HQ": "1"}).json()
    assert r["ok"] is False and "No key yet" in r["message"]
    assert c.get("/api/setup").json()["items"][0]["id"] == "claude"
    assert "getting started" in c.get("/setup-card.js").text.lower()
    bad = c.post("/api/try-chad", headers={"X-HQ": "1"}, files={"video": ("notes.txt", b"hi", "text/plain")})
    assert bad.status_code == 400
    ok = c.post("/api/try-chad", headers={"X-HQ": "1"}, files={"video": ("my vlog.mp4", b"fake", "video/mp4")}).json()
    task = db.rows("SELECT * FROM tasks WHERE id = ?", ok["task_id"])[0]
    assert task["agent"] == "Chad" and json.loads(task["params"])["creator"] == "You"
    fields = {f["key"]: f for s in c.get("/api/settings").json()["sections"] for f in s["fields"]}
    assert fields["ANTHROPIC_API_KEY"]["test"] == "claude" and fields["HQ_WHISPER_MODEL"]["test"] is None


def test_boss_can_say_whats_left_to_set_up():
    out, is_error = boss.run_tool("setup_status", {})
    assert not is_error and "Claude API key" in out
