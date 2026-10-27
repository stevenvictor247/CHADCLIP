"""Chad's daily clip cap and the pause while the posting backlog drains."""

import pytest

from hq import clipbudget, db
from hq.agents.chad.agent import Chad


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    db.init()
    db.execute("DELETE FROM clips")
    monkeypatch.setenv("HQ_MAX_POSTS_PER_DAY", "4")
    monkeypatch.delenv("HQ_MAX_CLIPS_PER_DAY", raising=False)


def clip(status="approved", stale=None):
    return db.execute("INSERT INTO clips (creator, start_s, end_s, path, status, stale_state, created_at) "
                      "VALUES ('You', 0, 10, 'x.mp4', ?, ?, ?)", status, stale, db.now())


def test_cap_defaults_to_six_and_never_goes_below_four(monkeypatch):
    assert clipbudget.daily_cap() == 6
    monkeypatch.setenv("HQ_MAX_CLIPS_PER_DAY", "2")
    assert clipbudget.daily_cap() == 4
    monkeypatch.setenv("HQ_MAX_CLIPS_PER_DAY", "oops")
    assert clipbudget.daily_cap() == 6


def test_room_counts_down_through_the_day():
    for _ in range(5):
        clip("posted")
    assert clipbudget.room()[0] == 1
    clip("posted")
    left, why = clipbudget.room()
    assert left == 0 and "daily limit" in why


def test_no_new_clips_while_backlog_exceeds_a_days_posting():
    for _ in range(5):
        clip("approved")
    left, why = clipbudget.room()
    assert left == 0 and "5 clips are still waiting" in why


def test_backlog_at_capacity_still_allows_clips_and_held_ones_do_not_count():
    for _ in range(4):
        clip("approved")
    clip("approved", stale="flagged")
    assert clipbudget.backlog() == 4 and clipbudget.room()[0] > 0


def test_chad_skips_the_round_and_run_reports_pause(monkeypatch):
    for _ in range(5):
        clip("pending_approval")
    chad = Chad()
    assert chad.nothing_to_do("check", {}) is True
    out = chad.run({"id": 1, "params": "{}"})
    assert out.startswith("Paused clip-making") and "5 clips" in out
