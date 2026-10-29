"""Closer: a replied lead gets a templated quote with a payment link, sent only after Steven approves."""

import json

import pytest

from hq import approvals, db, llm, money, relay
from hq.agents import AGENTS
from hq.agents.closer import agent as closer
from hq.agents.pitch import agent as pitch_agent, mailer

CFG = {"default_tier": "starter", "tiers": {
    "starter": {"label": "First-week trial", "price_usd": 25, "period": "one week", "includes": "5 clips",
                "payment_link": "https://buy.stripe.com/trial"},
    "weekly": {"label": "Weekly clips", "price_usd": 60, "period": "per week", "includes": "10 clips",
               "payment_link": "https://buy.stripe.com/week"},
    "monthly": {"label": "Monthly clips", "price_usd": 199.5, "period": "per month", "includes": "40 clips",
                "payment_link": ""}}}


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    db.init()
    db.execute("DELETE FROM quotes")
    db.execute("DELETE FROM leads WHERE contact LIKE '%@example.com'")
    db.execute("UPDATE leads SET status = 'dead' WHERE status IN ('replied', 'won')")
    db.execute("UPDATE approvals SET status = 'rejected' WHERE status = 'pending'")
    monkeypatch.setattr(closer, "settings", lambda: json.loads(json.dumps(CFG)))
    monkeypatch.setattr(pitch_agent, "settings", lambda: {"sender_name": "Steven"})
    monkeypatch.setattr(llm, "HAS_LLM", False)
    monkeypatch.setattr(mailer, "configured", lambda: False)
    monkeypatch.setattr(relay, "ask", lambda *a, **k: None)


def lead(handle="kai", status="replied", contact="kai@example.com"):
    ts = db.now()
    return db.execute("INSERT INTO leads (name, platform, handle, contact, status, created_at, updated_at) "
                      "VALUES (?, 'twitch', ?, ?, ?, ?, ?)", "Kai Lee", handle, contact, status, ts, ts)


def test_closer_is_registered_and_idle_with_nothing_replied():
    c = AGENTS["closer"]
    assert c.schedule and c.nothing_to_do("", {}) is True


def test_replied_lead_gets_a_template_quote_in_approvals_with_no_claude():
    lid = lead()
    assert AGENTS["closer"].nothing_to_do("", {}) is False
    out = AGENTS["closer"].run({"params": "{}"})
    assert "starter quote is ready" in out
    (a,) = [x for x in approvals.pending() if x["kind"] == "quote"]
    assert "$25 one week" in a["preview"] and "https://buy.stripe.com/trial" in a["preview"]
    assert db.rows("SELECT status FROM quotes WHERE lead_id = ?", lid)[0]["status"] == "pending"
    assert AGENTS["closer"].nothing_to_do("", {}) is True      # already quoted: no second draft
    assert "already has a quote" in AGENTS["closer"].quote(lid)


def test_missing_payment_link_stops_before_anything_is_drafted():
    lid = lead()
    out = AGENTS["closer"].quote(lid, "monthly")
    assert "Stripe payment link" in out and not db.rows("SELECT 1 FROM quotes")
    assert "no 'gold' tier" in AGENTS["closer"].quote(lid, "gold")


def test_paid_tiers_offer_the_trial_and_prices_format_cleanly():
    assert closer.money(25) == "$25" and closer.money(199.5) == "$199.50"
    body = closer.build_quote(CFG, "weekly", {"name": "Kai Lee"})
    assert "$60 per week" in body and "$25 for one week" in body and body.rstrip().endswith("Steven")


def test_claude_only_writes_the_reply_line_and_the_quote_stays_template(monkeypatch):
    lid = lead()
    monkeypatch.setattr(llm, "HAS_LLM", True)
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: {"message": "Glad the clips caught your eye."})
    AGENTS["closer"].quote(lid, "starter", "sounds good, how much?")
    assert "Glad the clips caught your eye." in db.rows("SELECT body FROM quotes")[0]["body"]
    assert "https://buy.stripe.com/trial" in db.rows("SELECT body FROM quotes")[0]["body"]


def test_only_replied_leads_are_quoted():
    assert "pitched" in AGENTS["closer"].quote(lead("p", "pitched"))


def test_approve_without_gmail_hands_the_text_over_and_reject_drops_it(monkeypatch):
    sent = []
    monkeypatch.setattr(relay, "notify", sent.append)
    a, b = lead("a"), lead("b")
    AGENTS["closer"].quote(a)
    AGENTS["closer"].quote(b)
    qa, qb = [x for x in approvals.pending() if x["kind"] == "quote"]
    assert "send it yourself" in approvals.decide(qa["id"], "approve") and sent
    approvals.decide(qb["id"], "reject")
    assert [r["status"] for r in db.rows("SELECT status FROM quotes ORDER BY id")] == ["sent", "dropped"]


def test_approve_with_gmail_sends_once(monkeypatch):
    mails = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "credentials", lambda: ("me@gmail.com", "x"))
    monkeypatch.setattr(mailer, "blocked", lambda e: False)
    monkeypatch.setattr(mailer, "send", mails.append)
    monkeypatch.setattr(pitch_agent, "_email_blocker", lambda cfg: None)
    monkeypatch.setattr(mailer, "build", lambda cfg, to, body: (to, body))
    lid = lead()
    AGENTS["closer"].quote(lid)
    (a,) = [x for x in approvals.pending() if x["kind"] == "quote"]
    assert a["payload"]["email"] is True
    assert "Emailed the starter quote" in approvals.decide(a["id"], "approve")
    assert len(mails) == 1 and mails[0][0] == "kai@example.com"
    assert "Already" in approvals.decide(a["id"], "approve") and len(mails) == 1


def test_a_failed_send_goes_back_to_approvals(monkeypatch):
    def boom(msg):
        raise mailer.SendError("Gmail said no.")
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "credentials", lambda: ("me@gmail.com", "x"))
    monkeypatch.setattr(mailer, "blocked", lambda e: False)
    monkeypatch.setattr(mailer, "send", boom)
    monkeypatch.setattr(mailer, "build", lambda *a: None)
    monkeypatch.setattr(pitch_agent, "_email_blocker", lambda cfg: None)
    lid = lead()
    AGENTS["closer"].quote(lid)
    (a,) = [x for x in approvals.pending() if x["kind"] == "quote"]
    assert "Not sent" in approvals.decide(a["id"], "approve")
    assert db.rows("SELECT status FROM quotes")[0]["status"] == "pending"
    assert any("NOT SENT" in x["title"] for x in approvals.pending())


def test_won_clients_count_shows_in_the_money_summary():
    before = money.summary()["won_clients"]
    lid = lead()
    assert "won client" in AGENTS["closer"].won(lid)
    assert money.summary()["won_clients"] == before + 1
    assert "Won clients: " in AGENTS["closer"].report()
    assert "won" in pitch_agent.STATUSES
