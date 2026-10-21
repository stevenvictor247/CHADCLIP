import json

import pytest

from hq import approvals, db, llm, relay
from hq.agents.pitch import agent as pitch_mod
from hq.agents.pitch.agent import Pitch

CFG = {"sender_name": "Steven", "what_you_offer": "Clips.", "price": "$250 a month", "opt_out_line": "Say no and I stop.",
       "free_sample": True, "followup_days": 4, "max_followups": 2, "min_viewers": 50, "max_viewers": 2000}
DRAFT = {"subject": "Clips for your stream", "message": "Hi Sam, great run on that boss fight.\nSay no and I stop.\nSteven",
         "why_this_lead": "Active, mid-size, no clip channel."}


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    db.init()
    db.execute("DELETE FROM leads")
    monkeypatch.setattr(pitch_mod, "settings", lambda: dict(CFG))
    monkeypatch.setattr(llm, "HAS_LLM", True)
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: dict(DRAFT))
    sent, asked = [], []
    monkeypatch.setattr(relay, "notify", sent.append)
    monkeypatch.setattr(relay, "ask", lambda *a, **k: asked.append(a))
    return {"sent": sent, "asked": asked}


def run(params):
    return Pitch().run({"params": json.dumps(params)})


def test_nothing_is_drafted_until_sender_name_is_filled_in(monkeypatch):
    monkeypatch.setattr(pitch_mod, "settings", lambda: {**CFG, "sender_name": ""})
    assert "sender_name" in run({"lead": {"name": "Sam", "platform": "youtube", "handle": "sam"}})
    assert db.rows("SELECT COUNT(*) n FROM leads")[0]["n"] == 0


def test_manual_lead_gets_a_draft_waiting_for_approval(_setup):
    run({"lead": {"name": "Sam", "platform": "youtube", "handle": "sam", "contact": "sam@example.com", "notes": "Podcast"}})
    lead = db.rows("SELECT * FROM leads")[0]
    assert lead["status"] == "drafted" and "Subject: Clips for your stream" in lead["pitch"]
    pending = approvals.pending()
    assert len(pending) == 1 and pending[0]["payload"] == {"lead_id": lead["id"]} and pending[0]["yes_label"] == "I'll send it"
    assert _setup["asked"], "the phone was asked too"
    assert "already a lead" in run({"lead": {"name": "Sam", "platform": "youtube", "handle": "sam"}})


def test_approving_marks_pitched_and_sends_text_to_copy(_setup):
    run({"lead": {"name": "Sam", "platform": "youtube", "handle": "sam", "contact": "sam@example.com"}})
    aid = approvals.pending()[0]["id"]
    out = approvals.decide(aid, "approve")
    lead = db.rows("SELECT * FROM leads")[0]
    assert lead["status"] == "pitched" and lead["followup_at"] and "sam@example.com" in out
    assert _setup["sent"] and "Subject:" in _setup["sent"][0]
    assert approvals.decide(aid, "approve") == "Already approved."  # a double tap does nothing


def test_rejecting_drops_the_lead():
    run({"lead": {"name": "Sam", "platform": "youtube", "handle": "sam"}})
    approvals.decide(approvals.pending()[0]["id"], "reject")
    assert db.rows("SELECT status FROM leads")[0]["status"] == "dropped"


def test_followups_remind_then_give_up(_setup):
    run({"lead": {"name": "Sam", "platform": "youtube", "handle": "sam", "contact": "c"}})
    approvals.decide(approvals.pending()[0]["id"], "approve")
    assert run({"followups": True}) == "No follow-ups due."  # not due yet
    for expected_followups in (1, 2):
        db.execute("UPDATE leads SET followup_at = '2000-01-01T00:00:00+00:00'")
        assert "Follow up with Sam" in run({"followups": True})
        assert db.rows("SELECT followups FROM leads")[0]["followups"] == expected_followups
    db.execute("UPDATE leads SET followup_at = '2000-01-01T00:00:00+00:00'")
    assert "marked dead" in run({"followups": True})
    assert db.rows("SELECT status FROM leads")[0]["status"] == "dead"


def test_find_skips_known_streamers_and_includes_facts(monkeypatch):
    seen = {}
    monkeypatch.setattr(pitch_mod.twitch, "small_streamers", lambda *a, **k: [
        {"login": "sam", "name": "Sam", "id": "1", "viewers": 300, "game": "Elden Ring"},
        {"login": "old", "name": "Old", "id": "2", "viewers": 200, "game": "Chess"}])
    monkeypatch.setattr(pitch_mod.twitch, "profile", lambda uid: {"bio": "Business: sam@example.com", "type": "affiliate"})
    monkeypatch.setattr(pitch_mod.twitch, "top_clips", lambda *a, **k: [{"title": "Parry god", "views": 5000}])
    monkeypatch.setattr(llm, "ask_json", lambda m, s, prompt, *a, **k: seen.setdefault("prompt", prompt) and dict(DRAFT))
    ts = db.now()
    db.execute("INSERT INTO leads (name, platform, handle, status, created_at, updated_at) VALUES ('Old', 'twitch', 'old', 'dead', ?, ?)", ts, ts)
    out = run({"find": 5})
    assert "Drafted 1" in out
    lead = db.rows("SELECT * FROM leads WHERE handle = 'sam'")[0]
    assert lead["contact"] == "sam@example.com" and lead["followers"] == 300
    assert "Parry god" in seen["prompt"] and "Elden Ring" in seen["prompt"] and "$250 a month" in seen["prompt"]


def test_mark_and_report():
    run({"lead": {"name": "Sam", "platform": "youtube", "handle": "sam"}})
    lid = db.rows("SELECT id FROM leads")[0]["id"]
    assert "client" in run({"mark": {"lead_id": lid, "status": "client", "note": "paying $250"}})
    assert run({"mark": {"lead_id": lid, "status": "bogus"}}).startswith("status must be")
    assert "1 client" in run({"report": True})


def test_small_streamers_pages_past_big_channels(monkeypatch):
    from hq.agents.chad import twitch
    pages = iter([
        {"data": [{"user_login": "big", "user_name": "Big", "user_id": "1", "viewer_count": 9000}], "pagination": {"cursor": "a"}},
        {"data": [{"user_login": "mid", "user_name": "Mid", "user_id": "2", "viewer_count": 500, "game_name": "X"}], "pagination": {"cursor": "b"}},
        {"data": [{"user_login": "tiny", "user_name": "Tiny", "user_id": "3", "viewer_count": 5}], "pagination": {"cursor": "c"}},
    ])

    class R:
        def __init__(self, body): self.body = body
        def raise_for_status(self): pass
        def json(self): return self.body

    monkeypatch.setattr(twitch, "_headers", lambda: {})
    monkeypatch.setattr(twitch.requests, "get", lambda *a, **k: R(next(pages)))
    assert [s["login"] for s in twitch.small_streamers(50, 2000)] == ["mid"]


def test_dashboard_api_for_approvals_and_leads():
    from fastapi.testclient import TestClient

    from hq.api import app
    run({"lead": {"name": "Sam", "platform": "youtube", "handle": "sam2"}})
    c = TestClient(app)
    s = c.get("/api/state").json()
    assert s["approvals"] and any(l["handle"] == "sam2" for l in s["leads"])
    aid = s["approvals"][0]["id"]
    assert c.post(f"/api/approvals/{aid}/approve").status_code == 200
    assert c.post("/api/approvals/99999/approve").status_code == 404
    lid = next(l["id"] for l in s["leads"] if l["handle"] == "sam2")
    assert c.post(f"/api/leads/{lid}", json={"status": "replied"}).status_code == 200
    assert c.post(f"/api/leads/{lid}", json={"status": "bogus"}).status_code == 400
