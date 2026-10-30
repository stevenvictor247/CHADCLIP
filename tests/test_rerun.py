"""Rerun: only quiet pitched leads, best followers first, at most 5 drafts a day, a different clip idea each try,
two tries then dead, and nothing is ever sent from the code."""

from datetime import datetime, timedelta, timezone

import pytest

from hq import db, rerun
from hq.agents import get


def ts(days=0):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    db.init()
    for t in ("leads", "approvals", "pitch_sent", "queue_sent", "nudge_state", "rerun_tries", "do_not_contact"):
        db.execute(f"DELETE FROM {t}")
    monkeypatch.setattr(rerun.llm, "HAS_LLM", False)
    monkeypatch.setattr(rerun.pitch, "settings", lambda: {"paused": False, "opt_out_line": "Reply STOP and I won't write again.", "sender_name": "Steven"})


def lead(name, followers=100, quiet=True, sent_days=7, status="pitched"):
    lid = db.execute("INSERT INTO leads (name, platform, handle, followers, contact, pitch, status, created_at, updated_at) "
                     "VALUES (?, 'twitch', ?, ?, ?, 'Subject: Clips\n\nHi', ?, ?, ?)",
                     name, name, followers, f"{name}@x.com", status, ts(sent_days), ts(sent_days))
    db.execute("INSERT INTO pitch_sent (lead_id, email, subject, sent_at) VALUES (?, ?, 's', ?)", lid, f"{name}@x.com", ts(sent_days))
    if quiet:
        db.execute("INSERT INTO nudge_state (lead_id, state, snippet, at) VALUES (?, 'quiet', '', ?)", lid, ts(1))
    return lid


def test_only_quiet_pitched_leads_ranked_by_followers_then_oldest():
    small, big = lead("small", 50), lead("big", 900)
    old, new = lead("old", 300, sent_days=20), lead("new", 300, sent_days=6)
    lead("loud", 5000, quiet=False)
    lead("replied", 5000, status="replied")
    assert [c["id"] for c in rerun.candidates()] == [big, old, new, small]


def test_daily_cap_and_template_draft_has_idea_and_opt_out():
    for i in range(8):
        lead(f"l{i}", 100 + i)
    assert "5 second tries drafted" in rerun.run()
    assert db.rows("SELECT COUNT(*) n FROM rerun_tries")[0]["n"] == 5
    assert rerun.slots() == 0 and "0 second tries" in rerun.run()
    t = db.rows("SELECT * FROM rerun_tries ORDER BY id")[0]
    assert t["idea"] in t["message"] and "Reply STOP" in t["message"] and t["subject"] == "Re: Clips" and t["n"] == 1


def test_claude_draft_is_used_and_opt_out_added(monkeypatch):
    lead("ann")
    monkeypatch.setattr(rerun.llm, "HAS_LLM", True)
    monkeypatch.setattr(rerun.llm, "ask_json", lambda *a, **k: {"message": "Hi Ann\nA free clip?\nInterested?"})
    rerun.run()
    msg = db.rows("SELECT message FROM rerun_tries")[0]["message"]
    assert msg.startswith("Hi Ann") and msg.endswith("Reply STOP and I won't write again.")


def test_claude_failure_falls_back_to_template(monkeypatch):
    lead("ann")
    monkeypatch.setattr(rerun.llm, "HAS_LLM", True)
    def boom(*a, **k): raise RuntimeError("down")
    monkeypatch.setattr(rerun.llm, "ask_json", boom)
    rerun.run()
    assert "free sample" in db.rows("SELECT message FROM rerun_tries")[0]["message"]


def test_two_tries_different_ideas_then_dead():
    a = lead("ann")
    rerun.run()
    first = db.rows("SELECT * FROM rerun_tries")[0]
    assert rerun.candidates() == []                       # waiting for review: no second draft yet
    rerun.decide(first["id"], "sent")
    assert rerun.candidates() == []                       # a quiet window must pass first
    db.execute("UPDATE rerun_tries SET decided_at = ?", ts(6))
    rerun.run()
    tries = db.rows("SELECT * FROM rerun_tries ORDER BY n")
    assert [t["n"] for t in tries] == [1, 2] and tries[0]["idea"] != tries[1]["idea"]
    rerun.decide(tries[1]["id"], "sent")
    assert rerun.candidates() == [] and rerun.retire() == 0   # window not passed, still pitched
    db.execute("UPDATE rerun_tries SET decided_at = ?", ts(6))
    assert rerun.retire() == 1
    assert db.rows("SELECT status FROM leads WHERE id = ?", a)[0]["status"] == "dead"
    assert db.rows("SELECT COUNT(*) n FROM rerun_tries")[0]["n"] == 2


def test_blocked_address_and_pending_followup_skipped():
    a, b = lead("ann"), lead("bob")
    db.execute("INSERT INTO do_not_contact (email, reason, created_at) VALUES ('ann@x.com', '', ?)", ts())
    import json
    db.execute("INSERT INTO approvals (agent, kind, title, preview, payload, created_at) VALUES ('Pitch', 'followup', 't', 'p', ?, ?)",
               json.dumps({"lead_id": b, "n": 1}), ts())
    assert rerun.candidates() == []


def test_decide_is_once_only_and_api_needs_hq_header():
    lead("ann")
    rerun.run()
    tid = db.rows("SELECT id FROM rerun_tries")[0]["id"]
    assert rerun.decide(tid, "skipped") == "Skipped."
    assert "already skipped" in rerun.decide(tid, "sent")
    from fastapi.testclient import TestClient
    from hq import api
    c = TestClient(api.app)
    assert c.post(f"/api/rerun/{tid}/sent").status_code == 403
    assert c.get("/api/rerun").json()["waiting"] == []


def test_agent_registered_and_idle_when_nothing_quiet():
    agent = get("rerun")
    assert agent and agent.nothing_to_do("", {}) is True
    lead("ann")
    assert agent.nothing_to_do("", {}) is False
