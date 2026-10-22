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


# ---- Connect TikTok ----------------------------------------------------------------------------------

def _tt(monkeypatch, tmp_path):
    from hq import tiktok_auth
    monkeypatch.setattr(tiktok_auth, "TOKENS_PATH", tmp_path / "tt.json")
    monkeypatch.setattr(tiktok_auth, "STATE_PATH", tmp_path / "state.txt")
    for k, v in (("TIKTOK_CLIENT_KEY", "ck"), ("TIKTOK_CLIENT_SECRET", "cs"), ("TIKTOK_REDIRECT_URI", "https://me.github.io/callback.html")):
        monkeypatch.setenv(k, v)
    return tiktok_auth


class _Resp:
    def __init__(self, body):
        self.body, self.text = body, str(body)

    def json(self):
        return self.body


def test_tiktok_login_link_and_pasted_answer(monkeypatch, tmp_path):
    from urllib.parse import parse_qs, urlparse
    tt = _tt(monkeypatch, tmp_path)
    q = parse_qs(urlparse(tt.authorize_url()).query)
    assert q["client_key"] == ["ck"] and q["scope"] == ["user.info.basic,video.upload"]
    assert q["redirect_uri"] == ["https://me.github.io/callback.html"]
    state = q["state"][0]
    assert tt.parse_answer(f"https://me.github.io/callback.html?code=abc%2Adef&scopes=x&state={state}") == "abc*def"
    assert tt.parse_answer("rawcode123") == "rawcode123"
    with pytest.raises(tt.TikTokError, match="newest link"):
        tt.parse_answer("https://me.github.io/callback.html?code=abc&state=someoneelse")
    with pytest.raises(tt.TikTokError, match="said no"):
        tt.parse_answer("https://me.github.io/callback.html?error=access_denied&error_description=You+said+no")
    with pytest.raises(tt.TikTokError):
        tt.parse_answer("https://me.github.io/callback.html?scopes=x&code2=1")


def test_tiktok_connects_and_renews_by_itself(monkeypatch, tmp_path):
    tt = _tt(monkeypatch, tmp_path)
    sent = []

    def post(url, data=None, **k):
        sent.append(data)
        if data["grant_type"] == "authorization_code":
            return _Resp({"access_token": "A1", "refresh_token": "R1", "expires_in": 86400, "refresh_expires_in": 31536000, "open_id": "o"})
        return _Resp({"access_token": "A2", "refresh_token": "R2", "expires_in": 86400, "refresh_expires_in": 31536000})
    monkeypatch.setattr(tt.requests, "post", post)
    assert tt.access_token() is None and not tt.connected()
    assert "connected" in tt.connect("thecode")
    assert sent[0]["code"] == "thecode" and sent[0]["redirect_uri"] == "https://me.github.io/callback.html"
    assert tt.access_token() == "A1" and len(sent) == 1  # still fresh: no extra call
    stored = tt._load()
    stored["expires_at"] = 0  # a day later
    tt._save(stored)
    assert tt.access_token() == "A2" and sent[1]["refresh_token"] == "R1"
    assert tt._load()["refresh_token"] == "R2" and tt.status()["connected"]
    tt.disconnect()
    assert not tt.connected()


def test_tiktok_errors_are_plain_and_posting_uses_the_connected_token(monkeypatch, tmp_path):
    tt = _tt(monkeypatch, tmp_path)
    monkeypatch.setattr(tt.requests, "post", lambda *a, **k: _Resp({"error": "invalid_grant", "error_description": "Authorization code expired"}))
    with pytest.raises(tt.TikTokError, match="code expired"):
        tt.connect("old")
    monkeypatch.delenv("TIKTOK_CLIENT_KEY")
    with pytest.raises(tt.TikTokError, match="Settings first"):
        tt.authorize_url()
    from hq.agents.chad.publish import tiktok as pub
    monkeypatch.setattr(pub.tiktok_auth, "access_token", lambda: "CONNECTED")
    seen = {}

    def boom(url, headers=None, **k):
        seen["auth"] = headers["Authorization"]
        raise RuntimeError("stop here")
    monkeypatch.setattr(pub.requests, "post", boom)
    f = tmp_path / "c.mp4"
    f.write_bytes(b"x")
    with pytest.raises(RuntimeError):
        pub.publish({"path": str(f), "post_text": "t"}, {"access_token_env": "NOPE"})
    assert seen["auth"] == "Bearer CONNECTED"


def test_tiktok_api_needs_the_hq_page_and_settings_show_it(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from hq.api import app
    _tt(monkeypatch, tmp_path)
    c = TestClient(app)
    assert c.get("/api/tiktok/login").status_code == 403
    assert c.get("/api/tiktok/login", headers={"X-HQ": "1"}).json()["url"].startswith("https://www.tiktok.com/v2/auth/authorize/")
    assert c.post("/api/tiktok/connect", json={"answer": ""}, headers={"X-HQ": "1"}).status_code == 400
    s = c.get("/api/settings").json()
    assert s["tiktok"]["configured"] and not s["tiktok"]["connected"]
    keys = {f["key"] for sec in s["sections"] for f in sec["fields"]}
    assert {"TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REDIRECT_URI"} <= keys
