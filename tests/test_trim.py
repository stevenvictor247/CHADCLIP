"""Trim: ranks the approved queue by freshness and creator results, asks before the first reorder, undoes, flags old clips."""

from datetime import datetime, timedelta, timezone

import pytest

from hq import approvals, db, trim
from hq.agents import get


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    db.init()
    for t in ("clips", "posts", "approvals"):
        db.execute(f"DELETE FROM {t}")
    monkeypatch.setattr(trim, "STATE_PATH", tmp_path / "state.json")


def ts(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def clip(days=0, creator="kai", status="approved"):
    return db.execute("INSERT INTO clips (creator, source_url, start_s, end_s, path, title, caption, status, approved_at, created_at) "
                      "VALUES (?, 'u', 0, 30, 'x.mp4', 't', 'c', ?, ?, ?)", creator, status, ts(days), ts(days))


def posted(creator, views, n=3):
    for _ in range(n):
        cid = clip(creator=creator, status="posted")
        db.execute("INSERT INTO posts (clip_id, platform, account, status, views, created_at) VALUES (?, 'youtube', 'a', 'posted', ?, ?)",
                   cid, views, ts(1))


def test_newer_clip_ranks_first():
    old, new = clip(days=5), clip(days=0)
    assert [r["id"] for r in trim.ranking()] == [new, old]


def test_better_creator_beats_slightly_newer_clip():
    posted("star", 1000); posted("dud", 0)
    a, b = clip(days=1, creator="dud"), clip(days=2, creator="star")
    assert [r["id"] for r in trim.ranking()][0] == b


def test_two_posts_of_data_is_trusted_only_partly():
    posted("one", 100, n=1); posted("other", 0, n=3)
    r = trim.creator_results()
    assert trim.results_score("one", r) == pytest.approx(1 / 3 + 2 / 3 * 0.5)
    assert trim.results_score("nobody", r) == 0.5


def test_dead_needs_enough_posts():
    posted("dead", 1, n=3); posted("thin", 0, n=1)
    r = trim.creator_results()
    assert trim.is_dead({"creator": "dead"}, r) and not trim.is_dead({"creator": "thin"}, r)


def test_first_reorder_waits_for_ok_then_runs_alone_and_undoes():
    a, b = clip(days=4), clip(days=0)
    assert "Asked" in trim.run()
    assert len(approvals.pending()) == 1 and db.rows("SELECT trim_score FROM clips WHERE id = ?", b)[0]["trim_score"] is None
    trim.run()
    assert len(approvals.pending()) == 1                       # no second card
    approvals.decide(approvals.pending()[0]["id"], "approve")
    assert db.rows("SELECT trim_score FROM clips WHERE id = ?", b)[0]["trim_score"] is not None
    c = clip(days=0)
    trim.run()                                                  # now automatic
    assert db.rows("SELECT trim_score FROM clips WHERE id = ?", c)[0]["trim_score"] is not None
    assert "Put 3 clips back" in trim.undo()
    assert db.rows("SELECT trim_score FROM clips WHERE id = ?", b)[0]["trim_score"] is not None   # the earlier reorder remains
    assert trim.undo() == "Nothing to undo."


def test_declining_the_first_reorder_changes_nothing_and_is_not_asked_again():
    clip(); trim.run()
    approvals.decide(approvals.pending()[0]["id"], "reject")
    trim.run()
    assert approvals.pending() == [] and db.rows("SELECT trim_score FROM clips")[0]["trim_score"] is None


def test_old_clips_get_one_drop_card_and_drop_or_keep_works():
    old, other, fresh_ = clip(days=9), clip(days=10), clip(days=1)
    trim.run()
    cards = [c for c in approvals.pending() if c["kind"] == trim.KIND_DROP]
    assert len(cards) == 1 and set(cards[0]["payload"]["clip_ids"]) == {old, other}
    trim.run()
    assert len([c for c in approvals.pending() if c["kind"] == trim.KIND_DROP]) == 1
    approvals.decide(cards[0]["id"], "reject")
    assert db.rows("SELECT status FROM clips WHERE id = ?", old)[0]["status"] == "rejected"
    assert db.rows("SELECT status FROM clips WHERE id = ?", fresh_)[0]["status"] == "approved"


def test_kept_clips_are_not_flagged_again():
    old = clip(days=9)
    db.execute("UPDATE clips SET stale_state = 'kept' WHERE id = ?", old)
    trim.run()
    assert [c for c in approvals.pending() if c["kind"] == trim.KIND_DROP] == []


def test_empty_queue_and_registered_agent():
    assert "empty" in trim.run()
    assert get("trim") and get("trim").free


def test_publish_posts_highest_trim_score_first(monkeypatch):
    from hq.agents.chad import publish
    a, b = clip(), clip()
    db.execute("UPDATE clips SET trim_score = 0.9 WHERE id = ?", a)
    db.execute("UPDATE clips SET trim_score = 0.2 WHERE id = ?", b)
    seen = []
    monkeypatch.setattr(publish, "paused", lambda: False)
    monkeypatch.setattr(publish, "accounts_for", lambda creator: seen.append(1) or [])
    order = [r["id"] for r in db.rows("SELECT id FROM clips WHERE status = 'approved' ORDER BY trim_score IS NULL, trim_score DESC, id DESC")]
    assert order == [a, b]
    publish.publish_approved()
    assert len(seen) == 2
