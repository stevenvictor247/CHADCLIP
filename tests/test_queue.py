from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hq import approvals, db, pitchqueue, relay
from hq.api import app
from hq.agents import AGENTS


@pytest.fixture(autouse=True)
def _setup(monkeypatch, tmp_path):
    db.init()
    for t in ("leads", "queue_sent", "pitch_sent", "approvals"):
        db.execute(f"DELETE FROM {t}")
    monkeypatch.setattr(pitchqueue, "ALERT_PATH", tmp_path / "alerted.txt")
    monkeypatch.delenv("HQ_QUEUE_GOAL", raising=False)
    sent = []
    monkeypatch.setattr(relay, "notify", sent.append)
    return sent


def lead(handle, score, status="drafted", created=None):
    ts = created or db.now()
    return db.execute("INSERT INTO leads (name, platform, handle, contact, pitch, status, created_at, updated_at, score) "
                      "VALUES (?, 'twitch', ?, 'a@b.co', 'Subject: Hi\n\nHello', ?, ?, ?, ?)", handle, handle, status, ts, ts, score)


def test_drafts_are_ordered_by_score_with_unscored_last():
    lead("low", 3), lead("none", None), lead("high", 9), lead("mid", 6)
    assert [d["handle"] for d in pitchqueue.ranked()] == ["high", "mid", "low", "none"]


def test_quota_counts_and_screen_shows_only_what_is_still_needed():
    for i in range(12):
        lead(f"s{i}", i)
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")
    lead("old", 5, created=old)
    c = pitchqueue.counts()
    assert c["drafted"] == 12 and c["ready"] == 13 and c["sent"] == 0
    s = pitchqueue.state()
    assert len(s["drafts"]) == 10 and s["drafts"][0]["handle"] == "s11" and s["short_by"] == 0


def test_mark_sent_counts_closes_approval_and_is_idempotent():
    lid = lead("sam", 8)
    approvals.request("Pitch", "pitch", "Pitch to sam", "p", {"lead_id": lid, "email": False})
    assert "Marked sam as sent" in pitchqueue.mark_sent(lid)
    assert db.rows("SELECT status, followup_at FROM leads")[0]["status"] == "pitched"
    assert not approvals.pending()
    assert pitchqueue.counts()["sent"] == 1 and pitchqueue.counts()["approved"] == 1
    assert "already pitched" in pitchqueue.mark_sent(lid)
    assert pitchqueue.counts()["sent"] == 1


def test_reply_rate_hidden_until_a_week_old():
    a, b = lead("a", 5, "pitched"), lead("b", 5, "replied")
    now = db.now()
    for lid in (a, b):
        db.execute("INSERT INTO queue_sent (lead_id, sent_at) VALUES (?, ?)", lid, now)
    assert pitchqueue.reply_rate() is None
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(timespec="seconds")
    db.execute("UPDATE queue_sent SET sent_at = ?", old)
    assert pitchqueue.reply_rate() == {"sent": 2, "replied": 1, "rate": 50.0}


def test_text_goes_out_once_after_the_alert_hour_when_short(monkeypatch, _setup):
    lead("one", 5)
    monkeypatch.setenv("HQ_QUEUE_ALERT_HOUR", "0")
    assert "9 short of your 10" in pitchqueue.check_and_alert()
    assert len(_setup) == 1
    assert not pitchqueue.alert_due()   # not twice the same day
    monkeypatch.setenv("HQ_QUEUE_ALERT_HOUR", "24")
    pitchqueue.ALERT_PATH.unlink()
    assert not pitchqueue.alert_due()   # too early


def test_no_text_when_enough_are_ready(monkeypatch):
    monkeypatch.setenv("HQ_QUEUE_ALERT_HOUR", "0")
    for i in range(10):
        lead(f"s{i}", 5)
    assert not pitchqueue.alert_due()


def test_agent_is_free_and_routes():
    q = AGENTS["queue"]
    assert q.free
    client = TestClient(app, headers={"x-hq": "1"})
    lid = lead("sam", 7)
    assert client.get("/api/queue").json()["drafts"][0]["id"] == lid
    assert TestClient(app).post(f"/api/queue/{lid}/sent").status_code == 403
    assert client.post(f"/api/queue/{lid}/sent").status_code == 200
    assert client.post("/api/queue/9999/sent").status_code == 404
