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


# ---- one-click email ----

from hq.agents.pitch import mailer  # noqa: E402


@pytest.fixture
def gmail(monkeypatch):
    """Gmail set up, postal address filled in, and a fake outbox instead of a real connection."""
    monkeypatch.setenv("PITCH_EMAIL_ADDRESS", "steven@gmail.com")
    monkeypatch.setenv("PITCH_EMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setattr(pitch_mod, "settings", lambda: {**CFG, "postal_address": "PO Box 1, Austin TX 78701"})
    db.execute("DELETE FROM pitch_sent")
    db.execute("DELETE FROM followup_sent")
    db.execute("DELETE FROM do_not_contact")
    outbox = []
    monkeypatch.setattr(mailer, "send", outbox.append)
    return outbox


def _draft(handle="sam", contact="sam@example.com"):
    run({"lead": {"name": handle.title(), "platform": "youtube", "handle": handle, "contact": contact}})
    return approvals.pending()[-1]


def test_email_is_not_sent_until_approved_then_sends_once(gmail):
    a = _draft()
    assert a["yes_label"] == "Send email" and "steven@gmail.com" in a["preview"]
    assert gmail == []  # drafting never sends
    out = approvals.decide(a["id"], "approve")
    assert "Emailed Sam" in out and len(gmail) == 1
    m = gmail[0]
    assert m["To"] == "sam@example.com" and m["From"].endswith("<steven@gmail.com>")
    assert m["Subject"] == "Clips for your stream" and "unsubscribe" in m["List-Unsubscribe"]
    body = m.get_content()
    assert "Say no and I stop." in body and "PO Box 1, Austin TX 78701" in body
    assert db.rows("SELECT status FROM leads")[0]["status"] == "pitched"
    assert approvals.decide(a["id"], "approve") == "Already approved."
    assert len(gmail) == 1


def test_opt_out_line_and_address_are_added_when_the_draft_lacks_them(gmail):
    db.execute("DELETE FROM leads")
    msg = mailer.build({**CFG, "postal_address": "PO Box 1"}, "a@b.com", "Subject: Hi\n\nHello there")
    body = msg.get_content()
    assert "Say no and I stop." in body and "PO Box 1" in body


def test_reject_sends_nothing(gmail):
    approvals.decide(_draft()["id"], "reject")
    assert gmail == [] and db.rows("SELECT status FROM leads")[0]["status"] == "dropped"


def test_do_not_contact_blocks_the_email(gmail):
    run({"do_not_contact": "Sam@Example.com"})
    out = approvals.decide(_draft()["id"], "approve")
    assert "do-not-contact" in out and gmail == []
    assert db.rows("SELECT status FROM leads")[0]["status"] == "do_not_contact"


def test_marking_do_not_contact_blocks_that_address_for_good(gmail):
    a = _draft()
    lid = db.rows("SELECT id FROM leads")[0]["id"]
    run({"mark": {"lead_id": lid, "status": "do_not_contact", "note": "said no"}})
    assert mailer.blocked("sam@example.com")
    run({"lead": {"name": "Sam2", "platform": "twitch", "handle": "sam2", "contact": "SAM@example.com"}})
    assert "do-not-contact" in approvals.decide(approvals.pending()[-1]["id"], "approve")
    assert gmail == []


def test_missing_postal_address_blocks_sending_and_requeues(monkeypatch, gmail):
    monkeypatch.setattr(pitch_mod, "settings", lambda: dict(CFG))
    a = _draft()
    out = approvals.decide(a["id"], "approve")
    assert "postal address" in out and gmail == []
    assert db.rows("SELECT status FROM leads")[0]["status"] == "drafted"
    assert [p["yes_label"] for p in approvals.pending() if "NOT SENT" in p["title"]] == ["Try again"]


def test_daily_cap_stops_sending(monkeypatch, gmail):
    monkeypatch.setattr(pitch_mod, "settings", lambda: {**CFG, "postal_address": "PO Box 1", "daily_send_cap": 2})
    for i in range(3):
        approvals.decide(_draft(f"s{i}", f"s{i}@example.com")["id"], "approve")
    assert len(gmail) == 2
    assert db.rows("SELECT status FROM leads WHERE handle = 's2'")[0]["status"] == "drafted"
    assert mailer.cap({"daily_send_cap": 500}) == mailer.HARD_CAP


def test_failed_send_leaves_lead_drafted_and_can_be_retried(monkeypatch, gmail):
    def boom(msg):
        raise mailer.SendError("Gmail didn't accept the address or app password.")
    monkeypatch.setattr(mailer, "send", boom)
    out = approvals.decide(_draft()["id"], "approve")
    assert "Not sent" in out and db.rows("SELECT status FROM leads")[0]["status"] == "drafted"
    assert not db.rows("SELECT * FROM pitch_sent")
    monkeypatch.setattr(mailer, "send", gmail.append)
    retry = next(p for p in approvals.pending() if "NOT SENT" in p["title"])
    assert "Emailed" in approvals.decide(retry["id"], "approve") and len(gmail) == 1


def test_contact_without_email_falls_back_to_copy_and_send(gmail):
    a = _draft("disc", "discord: sam#1234")
    assert a["yes_label"] == "I'll send it"
    assert "Send this to" in approvals.decide(a["id"], "approve") and gmail == []


def test_without_gmail_keeps_the_manual_flow(monkeypatch, gmail):
    monkeypatch.delenv("PITCH_EMAIL_APP_PASSWORD")
    a = _draft()
    assert a["yes_label"] == "I'll send it"
    assert "Send this to" in approvals.decide(a["id"], "approve") and gmail == []


def test_gmail_connection_test_never_sends(monkeypatch):
    from hq import connections
    monkeypatch.setattr(mailer, "check_login", lambda: None)
    assert connections.run("pitch_email", {"PITCH_EMAIL_ADDRESS": "a@gmail.com", "PITCH_EMAIL_APP_PASSWORD": "x y"})["ok"]
    assert not connections.run("pitch_email", {})["ok"]


# ---- one-click follow-ups ----

def _pitched(gmail, handle="sam", contact="sam@example.com"):
    approvals.decide(_draft(handle, contact)["id"], "approve")
    db.execute("UPDATE leads SET followup_at = '2000-01-01T00:00:00+00:00' WHERE handle = ?", handle)


def _followup_card():
    return next(p for p in approvals.pending() if p["kind"] == "followup")


def test_followup_email_is_drafted_for_approval_not_sent(monkeypatch, gmail):
    monkeypatch.setattr(llm, "ask_json", lambda m, s, p, schema, **k: {"message": "Just checking in.\nSay no and I stop.\nSteven"}
                        if "message" in schema["properties"] and "subject" not in schema["properties"] else dict(DRAFT))
    _pitched(gmail)
    sent_before = len(gmail)
    assert "ready in Waiting for your OK" in run({"followups": True})
    assert len(gmail) == sent_before  # drafting a follow-up never sends
    card = _followup_card()
    assert card["yes_label"] == "Send follow-up" and "Re: Clips for your stream" in card["preview"]
    out = approvals.decide(card["id"], "approve")
    assert "Emailed follow-up 1" in out and len(gmail) == sent_before + 1
    m = gmail[-1]
    assert m["To"] == "sam@example.com" and m["Subject"] == "Re: Clips for your stream"
    assert "PO Box 1" in m.get_content()
    assert approvals.decide(card["id"], "approve") == "Already approved."
    assert len(gmail) == sent_before + 1


def test_followup_not_sent_if_they_replied_or_opted_out(monkeypatch, gmail):
    monkeypatch.setattr(llm, "ask_json", lambda m, s, p, schema, **k: {"message": "Hi again. Say no and I stop."}
                        if "subject" not in schema["properties"] else dict(DRAFT))
    _pitched(gmail)
    run({"followups": True})
    card = _followup_card()
    lid = db.rows("SELECT id FROM leads")[0]["id"]
    run({"mark": {"lead_id": lid, "status": "replied"}})
    sent_before = len(gmail)
    assert "now replied" in approvals.decide(card["id"], "approve") and len(gmail) == sent_before


def test_followup_double_send_and_cap_are_blocked(monkeypatch, gmail):
    monkeypatch.setattr(pitch_mod, "settings", lambda: {**CFG, "postal_address": "PO Box 1", "daily_send_cap": 1})
    _pitched(gmail)  # uses the one email allowed today
    payload = {"lead_id": db.rows("SELECT id FROM leads")[0]["id"], "n": 1, "pitch": "Subject: Re: x\n\nHi"}
    out = pitch_mod._handle_followup_decision(payload, "approve")
    assert "limit" in out and len(gmail) == 1
    db.execute("DELETE FROM pitch_sent")
    monkeypatch.setattr(pitch_mod, "settings", lambda: {**CFG, "postal_address": "PO Box 1", "daily_send_cap": 5})
    assert "Emailed follow-up 1" in pitch_mod._handle_followup_decision(payload, "approve")
    assert "already sent" in pitch_mod._handle_followup_decision(payload, "approve") and len(gmail) == 2


def test_followup_without_email_stays_a_reminder(gmail):
    _pitched(gmail, "disc", "discord: sam#1234")
    before = len([p for p in approvals.pending() if p["kind"] == "followup"])
    assert "Follow up with Disc" in run({"followups": True})
    assert len([p for p in approvals.pending() if p["kind"] == "followup"]) == before
