"""Away mode: drafting agents rest after days without Steven, football keeps going, and he gets one catch-up back."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hq import away, db, relay, worker
from hq.agents.base import Agent


class Drafter(Agent):
    def run(self, task):
        return "ok"


@pytest.fixture
def clean(monkeypatch):
    db.init()
    away.SEEN_PATH.unlink(missing_ok=True)
    monkeypatch.delenv("HQ_AWAY_DAYS", raising=False)
    sent = []
    monkeypatch.setattr(relay, "notify", lambda text: sent.append(text))
    yield sent
    away.SEEN_PATH.unlink(missing_ok=True)


def _seen_days_ago(days):
    away._write(datetime.now(timezone.utc) - timedelta(days=days))


def test_never_seen_is_not_away_and_starts_the_clock(clean):
    assert not away.is_away()
    away.ensure_started()
    assert away.last_seen() is not None and not away.is_away()


def test_away_after_the_set_days_and_zero_turns_it_off(clean, monkeypatch):
    _seen_days_ago(2)
    assert not away.is_away()
    _seen_days_ago(4)
    assert away.is_away()
    monkeypatch.setenv("HQ_AWAY_DAYS", "0")
    assert not away.is_away()


def test_only_paid_non_football_agents_rest(clean):
    _seen_days_ago(5)
    assert away.skips(Drafter(name="Chad", role="t"))
    assert away.skips(Drafter(name="Quill", role="t", village="etsy"))
    assert not away.skips(Drafter(name="Captain", role="t", village="football"))
    assert not away.skips(Drafter(name="Tally", role="t", free=True))


def test_scheduled_rounds_skip_while_away(clean, monkeypatch):
    from hq import agents
    a = Drafter(name="AwayTest", role="t", schedule=[(1, "Make drafts", {})])
    monkeypatch.setattr(agents, "AGENTS", {"awaytest": a})
    count = lambda: db.rows("SELECT COUNT(*) n FROM tasks WHERE agent = 'AwayTest'")[0]["n"]  # noqa: E731
    _seen_days_ago(5)
    worker.queue_scheduled({})
    assert count() == 0
    away.seen()
    worker.queue_scheduled({})
    assert count() == 1


def test_coming_back_sends_one_free_catch_up(clean):
    _seen_days_ago(6)
    away.seen()
    assert len(clean) == 1 and "Welcome back" in clean[0] and "6 days" in clean[0]
    away.seen()
    assert len(clean) == 1   # only the first return after an absence


def test_dashboard_visit_counts_but_background_refresh_does_not(clean):
    from hq.api import app
    client = TestClient(app)
    _seen_days_ago(5)
    client.get("/api/approvals")
    assert away.is_away()
    client.get("/")
    assert not away.is_away() and len(clean) == 1
