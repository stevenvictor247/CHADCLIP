"""Stale-check: old, duplicate, orphaned or bad-caption queued clips are held and put on one Approvals card."""

from datetime import datetime, timedelta, timezone

import pytest

from hq import approvals, db, stalecheck


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    db.init()
    db.execute("DELETE FROM clips")
    db.execute("DELETE FROM approvals")
    monkeypatch.setattr("hq.agents.chad.sources.find_creator", lambda name: {"name": name} if name != "gone" else None)


def clip(days=0, start=0, end=30, src="http://v/1", creator="kai", caption="Great bit\n\nCredit: Kai", status="approved"):
    ts = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    return db.execute("INSERT INTO clips (creator, source_url, start_s, end_s, path, title, caption, status, approved_at, created_at) "
                      "VALUES (?, ?, ?, ?, 'x.mp4', 't', ?, ?, ?, ?)", creator, src, start, end, caption, status, ts, ts)


def state(cid):
    return db.rows("SELECT stale_state FROM clips WHERE id = ?", cid)[0]["stale_state"]


def test_healthy_queue_raises_nothing():
    clip(days=2, src="a"); clip(days=1, src="b")
    assert stalecheck.check()["flagged"] == []
    assert approvals.pending() == []


def test_flags_old_duplicate_unknown_creator_and_bad_caption_on_one_card():
    old = clip(days=9, src="a")
    first = clip(src="d", start=10, end=40)
    dup = clip(src="d", start=20, end=50)
    gone = clip(creator="gone", src="g")
    nocap = clip(src="c", caption="x")
    out = stalecheck.check()
    assert set(out["flagged"]) == {old, dup, gone, nocap}
    assert state(first) is None
    cards = approvals.pending()
    assert len(cards) == 1 and cards[0]["kind"] == "stale_clips"
    assert stalecheck.check()["approval_id"] == cards[0]["id"] and len(approvals.pending()) == 1   # no second card


def test_duplicate_of_already_posted_clip():
    clip(src="p", status="posted")
    dup = clip(src="p", start=5, end=20)
    assert stalecheck.check()["flagged"] == [dup]


def test_keep_all_never_reflags_and_drop_all_rejects():
    a, b = clip(days=10, src="a"), clip(days=12, src="b")
    stalecheck.check()
    aid = approvals.pending()[0]["id"]
    approvals.decide(aid, "approve")
    assert state(a) == state(b) == "kept"
    assert stalecheck.check()["flagged"] == []
    c = clip(days=20, src="c")
    stalecheck.check()
    approvals.decide(approvals.pending()[0]["id"], "reject")
    assert db.rows("SELECT status FROM clips WHERE id = ?", c)[0]["status"] == "rejected"


def test_flagged_clips_are_held_from_publishing(monkeypatch):
    from hq.agents.chad import publish
    held = clip(days=10)
    seen = []
    monkeypatch.setattr(publish, "accounts_for", lambda c: seen.append(c) or [])
    stalecheck.check()
    publish.publish_approved()
    assert seen == []
    assert state(held) == "flagged"
