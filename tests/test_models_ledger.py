from types import SimpleNamespace

import pytest

from hq import config, db, ledger, llm


def test_default_models_pick_cheapest_that_fits(monkeypatch):
    for k in ("HQ_MODEL_BOSS", "HQ_MODEL_CHAD", "HQ_MODEL_SCOUT", "HQ_BOSS_MODEL", "HQ_AGENT_MODEL"):
        monkeypatch.delenv(k, raising=False)
    assert config.model_for("Boss") == "claude-opus-5-5"
    assert config.model_for("Chad") == "claude-sonnet-5-5"
    assert config.model_for("Scout") == "claude-haiku-5-5"


def test_model_can_be_overridden_per_agent(monkeypatch):
    monkeypatch.setenv("HQ_MODEL_CHAD", "claude-opus-5-5")
    monkeypatch.setenv("HQ_MODEL_SCOUT", "claude-sonnet-5-5")
    assert config.model_for("chad") == "claude-opus-5-5"
    assert config.model_for("scout") == "claude-sonnet-5-5"


def test_old_env_names_still_work(monkeypatch):
    monkeypatch.delenv("HQ_MODEL_BOSS", raising=False)
    monkeypatch.setenv("HQ_BOSS_MODEL", "claude-sonnet-5-5")
    assert config.model_for("boss") == "claude-sonnet-5-5"


def test_cost_math():
    # 1M in + 1M out on Opus 5.5 is $4 + $20
    assert ledger.cost_of("claude-opus-5-5", 1_000_000, 1_000_000) == pytest.approx(24.0)
    # cached reads cost a tenth of input, writes 1.25x
    assert ledger.cost_of("claude-haiku-5-5", 0, 0, cache_read=1_000_000, cache_write=1_000_000) == pytest.approx(0.01 + 0.125)
    # unknown models are priced high so the meter never under-reports
    assert ledger.cost_of("mystery", 1_000_000, 0) == pytest.approx(5.0)


def test_only_models_that_support_fallback_get_it():
    assert llm.supports_fallback("claude-opus-5-5")
    assert llm.supports_fallback("claude-sonnet-5-5")
    assert not llm.supports_fallback("claude-haiku-5-5")


def test_ledger_records_and_budget_stops_scheduled_work(monkeypatch):
    db.init()
    before = ledger.spent_today()
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    cost = ledger.record("TestAgent", "claude-opus-5-5", usage)
    assert cost == pytest.approx(4.0)
    assert ledger.spent_today() == pytest.approx(before + 4.0)
    assert any(a["agent"] == "TestAgent" for a in ledger.summary()["month_by_agent"])

    monkeypatch.setattr(ledger, "DAILY_BUDGET", before + 1.0)
    assert ledger.over_budget()
    from hq import worker
    state = {}
    from hq.config import ETSY_AGENTS
    free = "('Sweep', 'Tally', 'Trim', " + ", ".join(f"'{a}'" for a in ETSY_AGENTS) + ")"
    queued = db.rows(f"SELECT COUNT(*) n FROM tasks WHERE agent NOT IN {free}")[0]["n"]
    worker.queue_scheduled(state)
    # Sweep, Tally and Trim cost no Claude money, so they keep working; everyone else waits.
    # The Etsy village has its own budget, so the business one running out doesn't stop it.
    assert db.rows(f"SELECT COUNT(*) n FROM tasks WHERE agent NOT IN {free}")[0]["n"] == queued
    business = {k for k in state if k.split(":")[1] not in ETSY_AGENTS}
    assert business == {"sched:Sweep:Tidy up and check what Claude is costing.", "sched:Tally:Count views on posted clips.", "sched:Trim:Rank the clip queue."}


def test_create_records_usage_and_skips_fallback_for_haiku(monkeypatch):
    db.init()
    seen = {}

    class FakeMessages:
        def create(self, **kw):
            seen.update(kw)
            return SimpleNamespace(stop_reason="end_turn", model="claude-haiku-5-5", content=[],
                                   usage=SimpleNamespace(input_tokens=1000, output_tokens=100,
                                                         cache_read_input_tokens=0, cache_creation_input_tokens=0))

    monkeypatch.setattr(llm, "client", lambda: SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages())))
    llm.create("claude-haiku-5-5", "s", [{"role": "user", "content": "hi"}], agent="Scout")
    assert "fallbacks" not in seen and "betas" not in seen
    assert any(r["agent"] == "Scout" for r in db.rows("SELECT agent FROM llm_usage"))
    llm.create("claude-sonnet-5-5", "s", [{"role": "user", "content": "hi"}], agent="Chad")
    assert seen["fallbacks"] == "default"


def test_api_state_shows_spend():
    from fastapi.testclient import TestClient

    from hq.api import app
    db.init()
    s = TestClient(app).get("/api/state").json()
    assert "today_usd" in s["spend"] and "month_by_agent" in s["spend"]
