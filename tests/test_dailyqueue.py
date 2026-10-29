"""Queue: counts today's pitches against the goal, orders by Pitch's score, marks sent, texts when short, respects the pause."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hq import api, approvals, dailyqueue, db, relay
from hq.agents import get
from hq.agents.pitch import agent as pitch_mod

CFG = {"paused": False, "queue_goal": 3, "queue_alert_hour": 0, "followup_days": 4}


def ts(days=0):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    db.init()
    for t in ("leads", "approvals", "pitch_sent", "queue_sent", "relay_sent"):
        db.execute(f"DELETE FROM {t}")
    cfg = dict(CFG)
    monkeypatch.setattr(pitch_mod, "settings", lambda: cfg)
    texts = []
    monkeypatch.setattr(relay, "notify", texts.append)
    monkeypatch.setattr(relay, "ask", lambda *a, **k: None)
    monkeypatch.setattr(relay, "enabled", lambda: True)
    return {"cfg": cfg, "texts": texts}


def draft(name, score, followers=100, status="drafted", created=None):
    lid = db.execute("INSERT INTO leads (name, platform, handle, followers, contact, pitch, status, created_at, updated_at, score) "
                     "VALUES (?, 'twitch', ?, ?, ?, 'Hi there', ?, ?, ?, ?)", name, name, followers, f"{name}@x.com", status,
                     created or ts(), ts(), score)
    if status == "drafted":
        approvals.request("Pitch", "pitch", f"Pitch to {name}", "p", {"lead_id": lid, "email": True})
    return lid


def test_best_score_first_then_audience():
    draft("low", 4)
    draft("top", 9, followers=50)
    draft("mid_big", 6, followers=900)
    draft("mid_small", 6, followers=10)
    assert [r["name"] for r in dailyqueue.ready()] == ["top", "mid_big", "mid_small", "low"]


def test_quota_never_pads_with_weak_leads():
    draft("only", 8)
    s = dailyqueue.state()
    assert [r["name"] for r in s["show"]] == ["only"] and s["short_by"] == 2


def test_mark_sent_counts_and_closes_the_approval():
    a, b = draft("a", 8), draft("b", 7)
    assert "follow up" in dailyqueue.mark_sent(a)
    assert db.rows("SELECT status FROM leads WHERE id = ?", a)[0]["status"] == "pitched"
    assert not any(x["payload"]["lead_id"] == a for x in approvals.pending())
    s = dailyqueue.state()
    assert s["sent"] == 1 and s["drafted"] == 2 and s["approved"] == 1 and s["left"] == 2
    assert [r["id"] for r in s["ready"]] == [b]
    assert "already" in dailyqueue.mark_sent(a)


def test_emailed_pitches_count_as_sent():
    a = draft("a", 8)
    db.execute("INSERT INTO pitch_sent (lead_id, email, subject, sent_at) VALUES (?, 'a@x.com', 's', ?)", a, ts())
    assert dailyqueue.counters()["sent"] == 1


def test_reply_rate_waits_a_week():
    a = draft("a", 8, status="replied")
    db.execute("INSERT INTO queue_sent (lead_id, sent_at) VALUES (?, ?)", a, ts())
    assert dailyqueue.reply_rate() is None
    db.execute("DELETE FROM queue_sent")
    db.execute("INSERT INTO queue_sent (lead_id, sent_at) VALUES (?, ?)", a, ts(8))
    b = draft("b", 8, status="pitched")
    db.execute("INSERT INTO queue_sent (lead_id, sent_at) VALUES (?, ?)", b, ts(8))
    assert dailyqueue.reply_rate() == {"sent": 2, "replied": 1, "percent": 50}


def test_texts_once_when_short(_setup):
    draft("only", 8)
    assert "short" in dailyqueue.run() and len(_setup["texts"]) == 1
    dailyqueue.run()
    assert len(_setup["texts"]) == 1   # once a day


def test_no_text_when_goal_is_covered(_setup):
    for i in range(3):
        draft(f"l{i}", 7)
    dailyqueue.run()
    assert _setup["texts"] == []


def test_paused_sends_no_text_and_skips_the_round(_setup):
    _setup["cfg"]["paused"] = True
    draft("only", 8)
    assert get("queue").nothing_to_do("", {}) is True
    assert dailyqueue.run().startswith("Pitch paused") and _setup["texts"] == []
    assert dailyqueue.state()["paused"] is True


def test_too_early_no_text(_setup):
    _setup["cfg"]["queue_alert_hour"] = 23
    draft("only", 8)
    assert dailyqueue.alert_due() is (datetime.now().hour >= 23)


def test_routes(_setup):
    lid = draft("a", 8)
    c = TestClient(api.app)
    body = c.get("/api/queue").json()
    assert body["goal"] == 3 and body["show"][0]["name"] == "a" and body["paused"] is False
    assert c.post(f"/api/queue/sent/{lid}").status_code == 403
    assert c.post(f"/api/queue/sent/{lid}", headers={"x-hq": "1"}).json()["message"].startswith("Marked as sent")
    assert c.post("/api/queue/sent/9999", headers={"x-hq": "1"}).status_code == 404
