"""Why an idle agent is idle: every agent answers, and the answers match what the agents themselves check."""

import pytest
from fastapi.testclient import TestClient

import hq.api
from hq import activity, boss, db, llm
from hq.agents import AGENTS


@pytest.fixture(autouse=True)
def _fresh():
    db.init()
    activity._cache["at"] = 0.0


def test_every_agent_gets_a_row_and_nothing_breaks_on_a_fresh_install():
    rows = {r["name"]: r for r in activity.build()}
    assert set(rows) == {a.name for a in AGENTS.values()}
    assert all(r["state"] in ("working", "queued", "waiting", "ready") for r in rows.values())
    assert all(r["why"] for r in rows.values() if r["state"] == "waiting")


def test_chad_says_who_it_needs_before_it_can_work(monkeypatch):
    monkeypatch.setattr(llm, "HAS_LLM", True)
    monkeypatch.setattr(activity, "HAS_LLM", True)
    from hq.agents.chad import sources, twitch
    monkeypatch.setattr(sources, "load_creators", lambda: [])
    monkeypatch.setattr(twitch, "permissions", lambda: {})
    why, unlock, link = activity._chad()
    assert "Nobody" in why and "Clips tab" in unlock and link == "/#clips"
    monkeypatch.setattr(sources, "load_creators", lambda: [{"name": "x", "sources": ["u"], "permission": "campaign"}])
    assert activity._chad() is None   # someone to clip: nothing is holding Chad


def test_chad_points_at_approvals_when_the_posting_backlog_is_what_holds_it(monkeypatch):
    from hq import clipbudget
    monkeypatch.setattr(activity, "HAS_LLM", True)
    monkeypatch.setattr(clipbudget, "room", lambda: (0, "9 clips are still waiting to post."))
    monkeypatch.setattr(clipbudget, "backlog", lambda: 9)
    monkeypatch.setattr(clipbudget, "posting_capacity", lambda: 4)
    why, unlock, link = activity._chad()
    assert why.startswith("9 clips") and link == "/#approvals"


def test_paused_hq_and_a_spent_budget_explain_every_idle_agent(monkeypatch):
    from hq import ledger
    from hq.agents.chad import publish
    monkeypatch.setattr(publish, "paused", lambda: True)
    assert "paused" in activity._why(AGENTS["chad"])["why"]
    monkeypatch.setattr(publish, "paused", lambda: False)
    monkeypatch.setattr(ledger, "over_budget", lambda village="business": True)
    assert "budget" in activity._why(AGENTS["chad"])["why"]
    assert activity._why(AGENTS["tally"]) is None or "budget" not in activity._why(AGENTS["tally"])["why"]   # free agents still run


def test_a_broken_look_never_breaks_the_report(monkeypatch):
    monkeypatch.setitem(activity.REASONS, "scout", lambda: 1 / 0)
    assert activity._why(AGENTS["scout"]) is None


def test_dashboard_boss_and_muse_get_the_reasons(monkeypatch):
    monkeypatch.setitem(activity.REASONS, "tally", lambda: ("No posted clips yet.", "", ""))
    activity._cache["at"] = 0.0
    c = TestClient(hq.api.app)
    state = c.get("/api/state").json()
    tally = next(a for a in state["agents"] if a["name"] == "Tally")
    assert tally["state"] == "waiting" and tally["why"] == "No posted clips yet."
    assert next(a for a in c.get("/api/activity").json() if a["name"] == "Tally")["runs_7d"] == 0
    assert any(line.startswith("Tally: idle. No posted clips yet.") for line in boss.get_status()["agents"])
    from hq import muse
    assert any(a["name"] == "Tally" for a in muse.facts()["agents_idle"])


def test_a_running_task_shows_as_working():
    tid = db.create_task("Sweep", "Tidy up", {}, created_by="Schedule")
    db.execute("UPDATE tasks SET status = 'running' WHERE id = ?", tid)
    try:
        row = next(r for r in activity.build() if r["name"] == "Sweep")
        assert row["state"] == "working" and row["doing"] == "Tidy up" and row["why"] is None
    finally:
        db.execute("UPDATE tasks SET status = 'done' WHERE id = ?", tid)
