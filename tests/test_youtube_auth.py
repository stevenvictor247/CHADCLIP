"""Connect YouTube from the Settings page: paste the Google client file, then Sign in with Google."""

import json
import time

import pytest
from fastapi.testclient import TestClient

import hq.api
from hq import youtube_auth

GOOD = json.dumps({"installed": {"client_id": "abc.apps.googleusercontent.com", "client_secret": "s3cret",
                                 "redirect_uris": ["http://localhost"]}})


@pytest.fixture
def account(monkeypatch, tmp_path):
    acct = {"name": "youtube_main", "platform": "youtube", "client_secrets_file": str(tmp_path / "client.json"),
            "token_file": str(tmp_path / "token.json")}
    monkeypatch.setattr(youtube_auth, "_accounts", lambda: [acct])
    youtube_auth._jobs.clear()
    return acct


def test_client_file_is_checked_before_saving(account, tmp_path):
    with pytest.raises(youtube_auth.YouTubeError, match="isn't the file"):
        youtube_auth.save_client("youtube_main", "hello")
    with pytest.raises(youtube_auth.YouTubeError, match="Desktop app"):
        youtube_auth.save_client("youtube_main", json.dumps({"web": {"client_id": "x"}}))
    with pytest.raises(youtube_auth.YouTubeError, match="No YouTube account"):
        youtube_auth.save_client("nope", GOOD)
    assert "Sign in with Google" in youtube_auth.save_client("youtube_main", GOOD)
    assert json.loads((tmp_path / "client.json").read_text())["installed"]["client_secret"] == "s3cret"
    assert youtube_auth.status() == [{"name": "youtube_main", "has_client": True, "connected": False,
                                      "signing_in": False, "error": ""}]


def test_sign_in_needs_the_client_file_first(account):
    with pytest.raises(youtube_auth.YouTubeError, match="client file first"):
        youtube_auth.start_sign_in("youtube_main")


def test_sign_in_runs_in_the_background_and_saves_the_token(account, monkeypatch, tmp_path):
    youtube_auth.save_client("youtube_main", GOOD)

    def fake_sign_in(acct):
        (tmp_path / "token.json").write_text('{"token": "t"}')
    monkeypatch.setattr(youtube_auth, "_sign_in", fake_sign_in)
    assert "opened" in youtube_auth.start_sign_in("youtube_main")
    for _ in range(50):
        if youtube_auth.status()[0]["connected"] and not youtube_auth.status()[0]["signing_in"]:
            break
        time.sleep(0.05)
    assert youtube_auth.status()[0]["connected"]
    youtube_auth.disconnect("youtube_main")
    assert not youtube_auth.status()[0]["connected"]


def test_a_timed_out_sign_in_says_so(account, monkeypatch):
    youtube_auth.save_client("youtube_main", GOOD)

    class WSGITimeoutError(Exception):
        pass

    def slow(acct):
        raise WSGITimeoutError("timed out")
    monkeypatch.setattr(youtube_auth, "_sign_in", slow)
    youtube_auth.start_sign_in("youtube_main")
    for _ in range(50):
        if youtube_auth.status()[0]["error"]:
            break
        time.sleep(0.05)
    assert "10 minutes" in youtube_auth.status()[0]["error"]


def test_api_needs_the_settings_page(account):
    c = TestClient(hq.api.app)
    assert c.get("/api/youtube").status_code == 403
    assert c.post("/api/youtube/client", json={"account": "youtube_main", "text": GOOD}).status_code == 403
    c = TestClient(hq.api.app, headers={"X-HQ": "1"})
    assert c.post("/api/youtube/client", json={"account": "youtube_main", "text": "x"}).status_code == 400
    r = c.post("/api/youtube/client", json={"account": "youtube_main", "text": GOOD}).json()
    assert r["accounts"][0]["has_client"]
    assert c.get("/api/settings").json()["youtube"][0]["name"] == "youtube_main"
