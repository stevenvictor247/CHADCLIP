import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hq import approvals, db, relay
from hq.agents.pitch import agent as pitch_mod, sample
from hq.agents.pitch.agent import Pitch
from hq.agents.chad import editor, sources, twitch


@pytest.fixture(autouse=True)
def _setup(monkeypatch, tmp_path):
    db.init()
    for t in ("leads", "samples", "approvals"):
        db.execute(f"DELETE FROM {t}")
    monkeypatch.setattr(relay, "ask", lambda *a, **k: None)
    monkeypatch.setattr(relay, "notify", lambda *a, **k: None)
    monkeypatch.setattr(sample, "SAMPLES_DIR", tmp_path)
    monkeypatch.setenv("HQ_SAMPLE_BASE_URL", "https://hq.example/")
    monkeypatch.setattr(twitch, "user_id", lambda login: "1")
    monkeypatch.setattr(twitch, "top_clips", lambda *a, **k: [{"url": "https://clips.twitch.tv/x", "title": "Wow"}])
    monkeypatch.setattr(sources, "download", lambda url: {"path": "src.mp4", "id": "x"})
    monkeypatch.setattr(editor, "duration", lambda p: 45.0)
    monkeypatch.setattr(sample, "transcribe", lambda p: None)
    rendered = []

    def fake_render(src, start, end, out, words=None, **k):
        out.write_bytes(b"video")
        rendered.append((start, end))
        return out
    monkeypatch.setattr(editor, "render", fake_render)
    return rendered


def lead(status="drafted", platform="twitch"):
    ts = db.now()
    lid = db.execute("INSERT INTO leads (name, platform, handle, contact, pitch, status, created_at, updated_at) "
                     "VALUES ('Sam', ?, 'sam', 'sam@example.com', 'Subject: Hi\n\nHello\nSteven', ?, ?, ?)",
                     platform, status, ts, ts)
    approvals.request("Pitch", "pitch", "Pitch to Sam", "why", {"lead_id": lid, "email": False})
    return lid


def test_sample_is_capped_at_30_seconds_and_asks_steven(_setup):
    lid = lead()
    assert "waiting for your OK" in sample.make(lid)
    assert _setup == [(0, 30.0)]
    s = db.rows("SELECT * FROM samples")[0]
    assert s["status"] == "pending" and sample.find(s["token"]) is None  # no link works before approval
    ask = [a for a in approvals.pending() if a["kind"] == "sample"][0]
    assert s["token"] in ask["preview"] and ask["yes_label"] == "Attach to the pitch"


def test_only_for_drafted_twitch_leads_and_too_short_clips(monkeypatch):
    assert "no sample" in sample.make(lead("pitched"))
    db.execute("DELETE FROM leads")
    assert "only cut samples from Twitch" in sample.make(lead(platform="youtube"))
    db.execute("DELETE FROM leads")
    monkeypatch.setattr(editor, "duration", lambda p: 8.0)
    assert "shorter than" in sample.make(lead()) and not db.rows("SELECT * FROM samples")


def test_approve_puts_private_link_in_pitch_but_sends_nothing():
    lid = lead()
    sample.make(lid)
    a = [x for x in approvals.pending() if x["kind"] == "sample"][0]
    approvals.decide(a["id"], "approve")
    token = db.rows("SELECT token FROM samples")[0]["token"]
    url = f"https://hq.example/sample/{token}"
    assert url in db.rows("SELECT pitch FROM leads")[0]["pitch"]
    assert db.rows("SELECT status FROM leads")[0]["status"] == "drafted"
    pitch_card = [x for x in approvals.pending() if x["kind"] == "pitch"][0]
    assert url in pitch_card["preview"]
    assert sample.find(token)["lead_id"] == lid


def test_reject_deletes_the_file():
    lid = lead()
    sample.make(lid)
    a = [x for x in approvals.pending() if x["kind"] == "sample"][0]
    path = db.rows("SELECT path FROM samples")[0]["path"]
    approvals.decide(a["id"], "reject")
    import os
    assert not os.path.exists(path) and db.rows("SELECT status FROM samples")[0]["status"] == "rejected"


def test_deleted_after_14_days_and_link_dies():
    import os
    lid = lead()
    sample.make(lid)
    approvals.decide([x for x in approvals.pending() if x["kind"] == "sample"][0]["id"], "approve")
    row = db.rows("SELECT * FROM samples")[0]
    assert 13 < (datetime.fromisoformat(row["expires_at"]) - datetime.now(timezone.utc)).days + 1 <= 14
    assert sample.cleanup() == 0 and os.path.exists(row["path"])
    old = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
    db.execute("UPDATE samples SET expires_at = ?", old)
    assert sample.find(row["token"]) is None and sample.due_for_cleanup()
    assert Pitch().nothing_to_do("", {"sample_cleanup": True}) is False
    assert "Deleted 1" in Pitch().run({"params": json.dumps({"sample_cleanup": True})})
    assert not os.path.exists(row["path"]) and db.rows("SELECT status FROM samples")[0]["status"] == "deleted"
    assert Pitch().nothing_to_do("", {"sample_cleanup": True}) is True


def test_replies_are_recorded_and_reported():
    lid = lead()
    sample.make(lid)
    approvals.decide([x for x in approvals.pending() if x["kind"] == "sample"][0]["id"], "approve")
    pitch_mod.set_status(lid, "replied", "liked it")
    assert db.rows("SELECT replied FROM samples")[0]["replied"] == 1
    assert "1 of those leads replied" in Pitch().report()


def test_private_link_route_serves_only_approved_unexpired_samples():
    from hq import api
    lid = lead()
    sample.make(lid)
    token = db.rows("SELECT token FROM samples")[0]["token"]
    c = TestClient(api.app, headers={"host": "localhost"})
    assert c.get(f"/sample/{token}").status_code == 404           # not approved yet
    approvals.decide([x for x in approvals.pending() if x["kind"] == "sample"][0]["id"], "approve")
    r = c.get(f"/sample/{token}")
    assert r.status_code == 200 and r.content == b"video" and "no-store" in r.headers["cache-control"]
    assert c.get("/sample/not-a-token").status_code == 404
