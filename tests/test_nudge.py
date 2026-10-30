"""Nudge: matches replies to pitched leads by address, spots bounces, ignores auto-replies and strangers, goes quiet after
5 days, never reads anything but the inbox read-only, and Draft quote only hands the lead to Closer."""

from datetime import datetime, timedelta, timezone

import pytest

from hq import db, mailwatch, relay
from hq.agents import get
from hq.agents.pitch import mailer


def ts(days=0):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    db.init()
    for t in ("leads", "approvals", "pitch_sent", "queue_sent", "relay_sent", "nudge_seen", "nudge_state", "quotes"):
        db.execute(f"DELETE FROM {t}")
    monkeypatch.setenv("PITCH_EMAIL_ADDRESS", "me@gmail.com")
    monkeypatch.setenv("PITCH_EMAIL_APP_PASSWORD", "abcdabcdabcdabcd")
    cards = []
    monkeypatch.setattr(relay, "ask", lambda text, kind, ref, **k: cards.append((kind, ref, text, k)))
    return cards


def lead(name, sent_days=1, status="pitched"):
    lid = db.execute("INSERT INTO leads (name, platform, handle, contact, pitch, status, created_at, updated_at) "
                     "VALUES (?, 'twitch', ?, ?, 'Hi', ?, ?, ?)", name, name, f"{name}@x.com", status, ts(sent_days), ts(sent_days))
    db.execute("INSERT INTO pitch_sent (lead_id, email, subject, sent_at) VALUES (?, ?, 's', ?)", lid, f"{name}@x.com", ts(sent_days))
    return lid


def msg(sender, mid, days=0, **kw):
    return {"from": sender, "subject": "Re: clips", "id": mid, "date": ts(days), "auto": False, "bounce": False,
            "failed": "", "snippet": "Sounds good, how much?", **kw}


def test_reply_matched_by_address_and_card_sent(_setup):
    a = lead("ann")
    found = mailwatch.classify([msg("ann@x.com", "<1>"), msg("stranger@x.com", "<2>")], mailwatch.watched())
    assert [(f["lead"]["id"], f["kind"]) for f in found] == [(a, "replied")]
    mailwatch.record(found)
    mailwatch.card(found[0]["lead"], found[0]["snippet"])
    mailwatch.card(found[0]["lead"], found[0]["snippet"])   # once only
    assert len(_setup) == 1 and _setup[0][:2] == ("nudge", a) and _setup[0][3]["yes"] == "📝 Draft quote"
    assert mailwatch.classify([msg("ann@x.com", "<1>")], mailwatch.watched()) == []   # already seen


def test_auto_reply_and_old_mail_ignored():
    lead("ann", sent_days=1)
    found = mailwatch.classify([msg("ann@x.com", "<1>", auto=True), msg("ann@x.com", "<2>", days=3)], mailwatch.watched())
    assert found == []


def test_bounce_marks_lead_dead():
    a = lead("bob")
    found = mailwatch.classify([msg("mailer-daemon@googlemail.com", "<b>", bounce=True, snippet="Address not found: bob@x.com")],
                               mailwatch.watched())
    assert found[0]["kind"] == "bounced"
    mailwatch.record(found)
    assert db.rows("SELECT status FROM leads WHERE id = ?", a)[0]["status"] == "dead"
    assert mailwatch.summary()["bounced"] == 1


def test_quiet_after_five_days_only():
    old, new = lead("old", sent_days=6), lead("new", sent_days=2)
    assert mailwatch.mark_quiet(mailwatch.watched()) == 1
    assert mailwatch.mark_quiet(mailwatch.watched()) == 0
    assert db.rows("SELECT lead_id FROM nudge_state WHERE state = 'quiet'") == [{"lead_id": old}]
    assert db.rows("SELECT status FROM leads WHERE id = ?", new)[0]["status"] == "pitched"


def test_run_end_to_end_with_fake_inbox(monkeypatch, _setup):
    lead("ann"), lead("old", sent_days=7)
    monkeypatch.setattr(mailwatch, "scan", lambda days: [msg("ann@x.com", "<1>")])
    out = mailwatch.run()
    assert "1 new reply" in out and "1 newly quiet" in out and len(_setup) == 1
    s = mailwatch.summary()
    assert s["replied"] == 1 and s["quiet"] == 1 and s["percent"] == 50


def test_draft_quote_button_asks_closer_and_sends_nothing(monkeypatch):
    a = lead("ann")
    drafted = []
    from hq.agents.closer import agent as closer
    monkeypatch.setattr(closer.Closer, "quote", lambda self, lid, tier=None, reply="": drafted.append((lid, reply)) or "ready")
    monkeypatch.setattr(mailer, "send", lambda m: pytest.fail("Nudge must never send"))
    assert mailwatch.decide(a, "approve") == "ready"
    assert drafted == [(a, "")] and db.rows("SELECT status FROM leads WHERE id = ?", a)[0]["status"] == "replied"


def test_not_interested_closes_lead():
    a = lead("ann")
    assert "not interested" in mailwatch.decide(a, "reject")
    assert db.rows("SELECT status FROM leads WHERE id = ?", a)[0]["status"] == "dead"


def test_nothing_to_do_without_gmail_or_pitched_leads(monkeypatch):
    nudge = get("nudge")
    assert nudge.nothing_to_do("", {}) is True        # no pitched leads
    lead("ann")
    assert nudge.nothing_to_do("", {}) is False
    monkeypatch.delenv("PITCH_EMAIL_APP_PASSWORD")
    assert nudge.nothing_to_do("", {}) is True


def test_scan_opens_inbox_read_only_and_only_peeks(monkeypatch):
    lead("ann")
    calls = []

    class FakeIMAP:
        def __init__(self, *a, **k): pass
        def login(self, *a): calls.append("login")
        def select(self, box, readonly=False): calls.append(("select", box, readonly)); return "OK", [b"1"]
        def logout(self): pass
        def uid(self, cmd, *args):
            calls.append((cmd, args))
            if cmd == "SEARCH":
                return "OK", [b"1 2"]
            uid = args[0]
            frm = b"From: ann@x.com\r\nSubject: Re: clips\r\nMessage-ID: <9>\r\nDate: " + \
                  datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000").encode() + b"\r\n\r\n"
            if uid == b"2":
                frm = frm.replace(b"ann@", b"other@")
            if "HEADER" in args[1]:
                return "OK", [(b"x", frm)]
            return "OK", [(b"x", frm + b"Yes please!\r\n")]

    monkeypatch.setattr(mailwatch.imaplib, "IMAP4_SSL", FakeIMAP)
    out = mailwatch.scan(3)
    assert [m["from"] for m in out] == ["ann@x.com"] and out[0]["snippet"] == "Yes please!"
    assert ("select", "INBOX", True) in calls
    assert all(c[0] == "SEARCH" or "PEEK" in c[1][1] for c in calls if isinstance(c, tuple) and c[0] in ("SEARCH", "FETCH"))
