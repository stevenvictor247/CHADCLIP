"""Other websites open in the same browser must not be able to press HQ's buttons or read it."""

from fastapi.testclient import TestClient

import hq.api
from hq import approvals, db


def _client(**kw):
    db.init()
    return TestClient(hq.api.app, **kw)


def test_changes_need_hq_header():
    c = _client()
    aid = approvals.request("Pitch", "test-kind", "Email someone", "preview", {})
    # a page on another website can POST, but it can't add the X-HQ header
    for path in (f"/api/approvals/{aid}/approve", "/api/clips/1/approve", "/api/chat", "/api/tasks",
                 "/api/conversation/new", "/api/leads/1", "/api/campaigns/1/join"):
        assert c.post(path, json={}).status_code == 403, path
    assert c.patch("/api/clips/1", json={"title": "x"}).status_code == 403
    assert approvals.pending()[-1]["id"] == aid  # still waiting: nothing was approved
    ok = c.post(f"/api/approvals/{aid}/approve", headers={"X-HQ": "1"})
    assert ok.status_code == 200


def test_reading_still_works_without_header():
    assert _client().get("/api/state").status_code == 200


def test_only_this_computer_without_password(monkeypatch):
    monkeypatch.setattr(hq.api, "PASSWORD", "")
    evil = _client(base_url="http://evil.example.com")
    assert evil.get("/api/state").status_code == 403   # DNS rebinding: a site pointed at 127.0.0.1
    assert evil.get("/").status_code == 403
    for host in ("http://127.0.0.1:8000", "http://localhost:8000", "http://[::1]:8000"):
        assert _client(base_url=host).get("/api/state").status_code == 200, host


def test_other_names_allowed_with_password(monkeypatch):
    monkeypatch.setattr(hq.api, "PASSWORD", "s3cret")
    c = _client(base_url="http://my-pc.tailnet.ts.net")
    assert c.get("/login").status_code == 200         # Tailscale address reaches the login page
    assert c.get("/api/state").status_code == 401     # and still needs the password
