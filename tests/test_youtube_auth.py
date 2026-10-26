"""Connect YouTube from the Settings page: paste the Google client file, approve in Google, paste back the address."""

import json
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import hq.api
from hq import youtube_auth

GOOD = json.dumps({"installed": {"client_id": "abc.apps.googleusercontent.com", "client_secret": "s3cret",
                                 "redirect_uris": ["http://localhost"],
                                 "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                                 "token_uri": "https://oauth2.googleapis.com/token"}})


@pytest.fixture
def account(monkeypatch, tmp_path):
    acct = {"name": "youtube_main", "platform": "youtube", "client_secrets_file": str(tmp_path / "client.json"),
            "token_file": str(tmp_path / "token.json")}
    monkeypatch.setattr(youtube_auth, "_accounts", lambda: [acct])
    youtube_auth._pending.clear()
    return acct


def test_client_file_is_checked_before_saving(account, tmp_path):
    with pytest.raises(youtube_auth.YouTubeError, match="isn't the file"):
        youtube_auth.save_client("youtube_main", "hello")
    with pytest.raises(youtube_auth.YouTubeError, match="Desktop app"):
        youtube_auth.save_client("youtube_main", json.dumps({"web": {"client_id": "x"}}))
    with pytest.raises(youtube_auth.YouTubeError, match="No YouTube account"):
        youtube_auth.save_client("nope", GOOD)
    assert "Open Google sign-in" in youtube_auth.save_client("youtube_main", GOOD)
    assert json.loads((tmp_path / "client.json").read_text())["installed"]["client_secret"] == "s3cret"
    assert youtube_auth.status() == [{"name": "youtube_main", "has_client": True, "connected": False,
                                      "waiting": False}]


def test_sign_in_needs_the_client_file_first(account):
    with pytest.raises(youtube_auth.YouTubeError, match="client file first"):
        youtube_auth.start_sign_in("youtube_main")


def test_sign_in_link_then_pasted_address_saves_the_token(account, monkeypatch, tmp_path):
    from hq import db
    db.init()
    youtube_auth.save_client("youtube_main", GOOD)
    q = parse_qs(urlparse(youtube_auth.start_sign_in("youtube_main")).query)
    assert q["client_id"] == ["abc.apps.googleusercontent.com"] and q["access_type"] == ["offline"]
    assert youtube_auth.status()[0]["waiting"]
    state = q["state"][0]

    from google_auth_oauthlib.flow import Flow

    def fake_fetch(self, **kw):
        assert kw["code"] == "4/abc" and self.code_verifier == youtube_auth._pending["youtube_main"]["verifier"]
    class C:
        def to_json(self): return '{"token": "t"}'
    monkeypatch.setattr(Flow, "fetch_token", fake_fetch)
    monkeypatch.setattr(Flow, "credentials", C())

    with pytest.raises(youtube_auth.YouTubeError, match="older sign-in"):
        youtube_auth.finish_sign_in("youtube_main", "http://localhost:8080/?state=old&code=4/abc")
    with pytest.raises(youtube_auth.YouTubeError, match="Google said no"):
        youtube_auth.finish_sign_in("youtube_main", "http://localhost:8080/?error=access_denied")
    assert "connected" in youtube_auth.finish_sign_in("youtube_main", f"http://localhost:8080/?state={state}&code=4/abc")
    st = youtube_auth.status()[0]
    assert st["connected"] and not st["waiting"]
    assert (tmp_path / "token.json").read_text() == '{"token": "t"}'
    youtube_auth.disconnect("youtube_main")
    assert not youtube_auth.status()[0]["connected"]


def test_connect_needs_the_sign_in_link_first(account):
    youtube_auth.save_client("youtube_main", GOOD)
    with pytest.raises(youtube_auth.YouTubeError, match="Open Google sign-in first"):
        youtube_auth.finish_sign_in("youtube_main", "4/abc")


def test_api_needs_the_settings_page(account):
    c = TestClient(hq.api.app)
    assert c.get("/api/youtube").status_code == 403
    assert c.post("/api/youtube/client", json={"account": "youtube_main", "text": GOOD}).status_code == 403
    c = TestClient(hq.api.app, headers={"X-HQ": "1"})
    assert c.post("/api/youtube/client", json={"account": "youtube_main", "text": "x"}).status_code == 400
    r = c.post("/api/youtube/client", json={"account": "youtube_main", "text": GOOD}).json()
    assert r["accounts"][0]["has_client"]
    assert c.get("/api/settings").json()["youtube"][0]["name"] == "youtube_main"


def test_expired_sign_in_tells_you_how_to_redo_it(tmp_path, monkeypatch):
    from hq import connections
    from hq.agents.chad.publish import youtube as yt
    (tmp_path / "t.json").write_text("{}")
    monkeypatch.setattr(connections, "ROOT", tmp_path)

    def expired(account):
        raise RuntimeError("invalid_grant: Token has been expired or revoked.")
    monkeypatch.setattr(yt, "_credentials", expired)
    r = connections.youtube({"name": "youtube_main", "token_file": "t.json"})
    assert not r["ok"] and "Open Google sign-in" in r["message"] and "7 days" in r["message"]
