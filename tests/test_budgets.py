"""Per-agent daily budgets: alert at 80%, pause at 100%, a receipt for every run."""

import pytest

from hq import budgets, db, ledger, llm


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    db.init()
    for t in ("llm_usage", "run_receipts", "relay_sent", "tasks", "activity"):
        db.execute(f"DELETE FROM {t}")
    monkeypatch.setenv("HQ_AGENT_BUDGETS", "Chad=2, scout = $0.5, junk, Muse=oops, Zero=0")
    monkeypatch.setattr(budgets.relay, "notify", lambda text: sent.append(text))
    sent.clear()


sent = []


def spend(agent, usd):
    ledger.record_cost(agent, "test", usd)


def test_limits_parse_and_skip_bad_pieces():
    assert budgets.limits() == {"chad": 2.0, "scout": 0.5}


def test_states_walk_from_ok_to_alert_to_paused():
    assert budgets.state("Chad")["state"] == "ok"
    spend("Chad", 1.7)
    assert budgets.state("Chad")["state"] == "alert"
    spend("Chad", 0.3)
    assert budgets.state("chad")["state"] == "paused" and budgets.is_paused("Chad")
    assert budgets.state("Pitch")["state"] == "none" and not budgets.is_paused("Pitch")


def test_check_refuses_only_the_paused_agent():
    spend("Chad", 2.5)
    with pytest.raises(budgets.BudgetPaused):
        budgets.check("Chad")
    budgets.check("Scout")
    with pytest.raises(budgets.BudgetPaused):
        llm.create("claude-sonnet-5-5", "s", [], agent="Chad")   # refused before any call is made


def test_alert_goes_out_once_a_day_per_level():
    spend("Scout", 0.45)
    assert budgets.alert("Scout") and "90%" in sent[0]
    assert budgets.alert("Scout") is None
    spend("Scout", 0.1)
    assert budgets.alert("Scout") and "paused" in sent[1]
    assert budgets.alert("Scout") is None and len(sent) == 2


def test_no_alert_below_80_percent():
    spend("Chad", 1.0)
    assert budgets.alert("Chad") is None and not sent


def test_receipt_records_cost_and_reason():
    tid = db.create_task("Chad", "x", {}, created_by="Steven")
    started = db.now()
    spend("Chad", 0.25)
    budgets.receipt({"id": tid, "agent": "Chad"}, "failed", started, "boom", paused=True)
    r = budgets.snapshot()["receipts"][0]
    assert (r["agent"], r["status"], r["stop_reason"], r["cost_usd"]) == ("Chad", "failed", "budget", 0.25)


def test_paused_agent_gets_no_scheduled_round(monkeypatch):
    from hq import agents, worker
    from hq.agents.base import Agent
    monkeypatch.setitem(agents.AGENTS, "Chad", Agent("Chad", "test", schedule=[(1, "round", {})]))
    spend("Chad", 3)
    worker.queue_scheduled({})
    assert not db.rows("SELECT 1 FROM tasks WHERE LOWER(agent) = 'chad'")
    db.execute("DELETE FROM llm_usage")
    worker.queue_scheduled({})
    assert db.rows("SELECT 1 FROM tasks WHERE LOWER(agent) = 'chad'")
