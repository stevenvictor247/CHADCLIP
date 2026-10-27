"""Rally: free checks first, invented stats rejected, every post waits in Approvals, nothing is ever posted."""

import pytest

from hq import approvals, db, llm, rally, relay
from hq.agents import AGENTS

FACTS = ["AP Top 25: Alpha is ranked 3 with a 7-0 record", "AP Top 25: Beta is ranked 12 with a 6-1 record",
         "Alpha plays Beta on Saturday"]


def post(**kw):
    return {"topic": "upset_watch", "headline": "Upset watch: Beta at Alpha", "caption": "Saturday #cfb",
            "body": "No. 12 Beta (6-1) visits No. 3 Alpha (7-0).", **kw}


@pytest.fixture(autouse=True)
def _setup(monkeypatch, tmp_path):
    db.init()
    db.execute("DELETE FROM rally_posts")
    db.execute("UPDATE approvals SET status = 'rejected' WHERE status = 'pending'")
    monkeypatch.setattr(rally, "CARDS_DIR", tmp_path)
    monkeypatch.setattr(llm, "HAS_LLM", True)
    monkeypatch.setattr(relay, "notify", lambda *a, **k: None)
    monkeypatch.setattr(relay, "ask", lambda *a, **k: None)


def fake_claude(monkeypatch, posts):
    calls = []
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: calls.append(a) or {"posts": posts})
    return calls


def test_rally_is_registered_and_scheduled():
    r = AGENTS["rally"]
    assert r.schedule and not r.free


def test_draft_queues_approvals_and_cards_and_posts_nothing(monkeypatch):
    fake_claude(monkeypatch, [post(), post(topic="rankings", headline="Top 12")])
    out = AGENTS["rally"].run({"params": '{"facts": %s}' % __import__("json").dumps(FACTS)})
    assert "Drafted 2 posts" in out
    pend = [a for a in approvals.pending() if a["kind"] == "rally"]
    assert len(pend) == 2 and "NOT POSTED" in pend[0]["title"]
    rows = db.rows("SELECT * FROM rally_posts")
    assert all(r["status"] == "pending" and r["card_path"] for r in rows)
    from PIL import Image
    assert Image.open(rows[0]["card_path"]).size == (1080, 1920)


def test_invented_numbers_and_school_marks_are_dropped(monkeypatch):
    fake_claude(monkeypatch, [post(body="Alpha won 41-3 last year."), post(caption="Check the logo #cfb"),
                              post(body="Alpha (7-0) leads."), post(topic="betting")])
    rally.draft({"facts": FACTS})
    assert [r["body"] for r in db.rows("SELECT body FROM rally_posts")] == ["Alpha (7-0) leads."]


def test_all_bad_drafts_say_so(monkeypatch):
    fake_claude(monkeypatch, [post(body="Alpha won 99-0.")])
    with pytest.raises(rally.RallyError):
        rally.draft({"facts": FACTS})


def test_too_few_facts_never_calls_claude(monkeypatch):
    calls = fake_claude(monkeypatch, [post()])
    with pytest.raises(rally.RallyError, match="facts"):
        rally.draft({"facts": ["one"]})
    assert not calls


def test_free_look_skips_when_waiting_or_season_over(monkeypatch):
    assert rally.why_not_now() is None
    monkeypatch.setattr(llm, "HAS_LLM", False)
    assert rally.why_not_now() == "No Claude key."
    monkeypatch.setattr(llm, "HAS_LLM", True)
    with monkeypatch.context() as m:
        m.setattr(rally, "_today", lambda: __import__("datetime").date(2027, 3, 1))
        assert "over" in rally.why_not_now()
    fake_claude(monkeypatch, [post()])
    rally.draft({"facts": FACTS})
    assert "waiting" in rally.why_not_now()
    assert AGENTS["rally"].nothing_to_do("", {"weekly": True}) is True


def test_approve_hands_text_over_reject_closes_and_views_feed_the_topic_report(monkeypatch):
    fake_claude(monkeypatch, [post(), post(topic="rivalry", headline="Rivalry")])
    rally.draft({"facts": FACTS})
    a, b = approvals.pending()[-2:]
    assert "Post it yourself" in approvals.decide(a["id"], "approve")
    approvals.decide(b["id"], "reject")
    ids = {r["status"]: r["id"] for r in db.rows("SELECT id, status FROM rally_posts")}
    assert set(ids) == {"approved", "rejected"}
    assert "isn't approved" in rally.record_views(ids["rejected"], 50)
    assert "1,200" in rally.record_views(ids["approved"], 1200)
    assert "upset_watch: 1,200" in rally.topic_report()


def test_fetch_rankings_reads_the_public_feed_and_fails_politely(monkeypatch):
    feed = {"rankings": [{"name": "AP Top 25", "ranks": [
        {"current": 1, "recordSummary": "7-0", "team": {"location": "Alpha"}}]}]}

    class R:
        def json(self): return feed
    monkeypatch.setattr(rally.requests, "get", lambda *a, **k: R())
    assert rally.fetch_rankings("http://x") == ["AP Top 25: Alpha is ranked 1 with a 7-0 record"]
    monkeypatch.setattr(rally.requests, "get", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    with pytest.raises(rally.RallyError):
        rally.fetch_rankings("http://x")
