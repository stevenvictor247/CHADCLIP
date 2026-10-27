"""Recruiter: free checks before spending, daily pace by cost, honest 1 to 10 rating, no repeats, Approvals, caps."""

import importlib
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ENV = ("HQ_RECRUITER", "HQ_RECRUITER_PER_DAY", "HQ_RECRUITER_MONTHLY_BUDGET", "HQ_RECRUITER_MAX_WAITING",
       "HQ_RECRUITER_MIN_RATING", "HQ_MODEL_RECRUITER", "HQ_AGENT_MODEL", "HQ_BUILD_TOKEN", "HQ_BUILD_URL")


def _fresh(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("HQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HQ_PASSWORD", "")
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import hq.config, hq.db, hq.ledger, hq.muse, hq.recruiter, hq.agents, hq.api
    for m in (hq.config, hq.db, hq.ledger, hq.muse, hq.recruiter, hq.api):
        importlib.reload(m)
    hq.db.init()
    monkeypatch.setattr(hq.recruiter, "DAILY_BUDGET", 5.0)
    return hq


def _agent(title, name, low=100, high=300, conf=0.5, start=10, monthly=2, effort="small", hours=3, gap="Nobody does X."):
    return {"title": title, "name": name, "pitch": f"{title}: a real plan.", "why_now": "A fact.", "builds_on": ["Chad"],
            "first_steps": ["One", "Two", "Three"], "steven_does": "10 minutes.", "risks": "May earn $0.",
            "start_cost_usd": start, "monthly_cost_usd": monthly, "effort": effort, "effort_hours": hours,
            "profit_low_usd_month": low, "profit_high_usd_month": high, "months_to_first_dollar": 1,
            "confidence": conf, "repeats": None, "gap": gap}


GOOD = [_agent("Invoice chaser for clip clients", "Chaser", low=200, high=500, conf=0.6),
        _agent("Thumbnail tester for shorts", "Thumbs", low=50, high=150, conf=0.5)]


def _fake_llm(monkeypatch, hq, ideas, calls=None):
    def create(model, system, messages, **kw):
        if calls is not None:
            calls.append({"model": model, "prompt": messages[0]["content"], **kw})
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps({"ideas": ideas}))],
                               stop_reason="end_turn")
    monkeypatch.setattr(hq.llm, "HAS_LLM", True)
    monkeypatch.setattr(hq.llm, "create", create)


def test_rating_is_1_to_10_and_capped_by_confidence(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    clean = lambda raw: hq.muse.clean({**raw, "kind": "agent"})
    assert hq.recruiter.rating(clean(_agent("Loser", "Loss", low=0, high=5, monthly=50))) == 1
    great = clean(_agent("Gold mine", "Gold", low=3000, high=6000, conf=0.8, start=0, monthly=5, hours=1))
    assert hq.recruiter.rating(great) == 10
    shaky = clean(_agent("Long shot", "Shot", low=3000, high=6000, conf=0.1, start=0, monthly=5, hours=1))
    assert hq.recruiter.rating(shaky) == 6
    ok = hq.recruiter.rating(clean(_agent("Middle", "Mid")))
    assert 1 < ok < 10


@pytest.mark.parametrize("model,expected", [("claude-haiku-5-5", 4), ("claude-sonnet-5-5", 2), ("claude-opus-5-5", 1)])
def test_pace_follows_cost(monkeypatch, tmp_path, model, expected):
    hq = _fresh(monkeypatch, tmp_path, HQ_MODEL_RECRUITER=model)
    assert hq.recruiter.per_day() == expected


def test_pace_can_be_set(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path, HQ_RECRUITER_PER_DAY="3")
    assert hq.recruiter.per_day() == 3


def test_round_files_proposals_to_approvals(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    calls = []
    _fake_llm(monkeypatch, hq, GOOD, calls)
    out = hq.recruiter.run()
    assert "2 proposal(s)" in out and len(calls) == 1
    assert calls[0]["agent"] == "Recruiter"
    rows = hq.db.rows("SELECT * FROM ideas ORDER BY id")
    assert len(rows) == 2 and all(r["source"] == "recruiter" and r["kind"] == "agent" and r["status"] == "proposed" for r in rows)
    assert all(1 <= r["rating"] <= 10 and r["gap"] for r in rows)
    ap = hq.approvals.pending()
    assert len(ap) == 2 and all(a["kind"] == "recruit_idea" and a["agent"] == "Recruiter" for a in ap)
    assert "Rating" in ap[0]["preview"] and "Nobody does X" in ap[0]["preview"]


def test_prompt_includes_sweep_and_muse_findings(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    hq.db.execute("INSERT INTO ideas (kind, title, name, pitch, status, created_at) VALUES "
                  "('agent', 'Muse wants a refund watcher', 'Refunder', 'Watches refunds.', 'proposed', ?)", hq.db.now())
    hq.db.execute("INSERT INTO tasks (agent, instructions, status, created_at, updated_at) VALUES "
                  "('Chad', 'x', 'failed', ?, ?)", hq.db.now(), hq.db.now())
    import hq.sweep
    monkeypatch.setattr(hq.sweep, "latest", lambda: {"report": {"improve": {"score": 71, "tips": [
        {"area": "waste", "severity": "high", "title": "Chad repeats failed downloads", "why": "Wastes money"}]},
        "problems": [{"message": "Disk is filling"}]}})
    _fake_llm(monkeypatch, hq, [], [])
    text = hq.recruiter.prompt(2)
    assert "Chad repeats failed downloads" in text and "Disk is filling" in text
    assert "Muse wants a refund watcher" in text and '"Chad":1' in text.replace(" ", "")


def test_sift_drops_repeats_rule_breakers_weak_and_nameless(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    ideas = [_agent("Sweep: janitor and quality control", "Sweeper"),             # already built
             _agent("Fake followers booster", "Booster"),                        # breaks the rules
             _agent("Dead weight agent", "Weight", low=0, high=5, monthly=40),   # rated 1
             _agent("Nameless helper", ""),
             _agent("Invoice chaser for clip clients", "Chaser", low=200, high=500)]
    kept, dropped = hq.recruiter.sift(ideas)
    assert [i["title"] for i in kept] == ["Invoice chaser for clip clients"]
    assert len(dropped) == 4


def test_recruiter_never_repeats_itself_or_muse(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    _fake_llm(monkeypatch, hq, GOOD[:1])
    hq.recruiter.run()
    kept, dropped = hq.recruiter.sift([dict(GOOD[0])])
    assert kept == [] and dropped


def test_one_look_a_day_and_daily_allowance(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    calls = []
    _fake_llm(monkeypatch, hq, GOOD, calls)
    hq.recruiter.run()
    assert hq.recruiter.why_not_now() is not None
    assert hq.recruiter.run().startswith("Skipped")
    assert len(calls) == 1


def test_manual_run_ignores_the_day_but_not_money_or_room(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path, HQ_RECRUITER_MAX_WAITING="2")
    calls = []
    _fake_llm(monkeypatch, hq, GOOD, calls)
    hq.recruiter.run()
    assert hq.recruiter.why_not_now(manual=True)   # two waiting = full
    hq.db.execute("UPDATE ideas SET status = 'rejected'")
    assert hq.recruiter.why_not_now(manual=True) is None


def test_waiting_cap_asks_for_less(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path, HQ_RECRUITER_MAX_WAITING="3")
    _fake_llm(monkeypatch, hq, GOOD)
    hq.recruiter.run()
    assert hq.recruiter.wanted(manual=True) == 1


def test_idle_day_costs_nothing(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    calls = []
    _fake_llm(monkeypatch, hq, GOOD, calls)
    monkeypatch.setattr(hq.llm, "HAS_LLM", False)
    assert "API key" in hq.recruiter.why_not_now()
    monkeypatch.setattr(hq.llm, "HAS_LLM", True)
    monkeypatch.setenv("HQ_RECRUITER", "false")
    assert "switched off" in hq.recruiter.why_not_now()
    assert hq.recruiter.run().startswith("Skipped") and calls == []


def test_monthly_and_daily_budget_stop_it(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path, HQ_RECRUITER_MONTHLY_BUDGET="0")
    _fake_llm(monkeypatch, hq, GOOD)
    assert "switched off" in hq.recruiter.why_not_now()
    monkeypatch.setenv("HQ_RECRUITER_MONTHLY_BUDGET", "3")
    hq.db.execute("INSERT INTO llm_usage (agent, model, input_tokens, output_tokens, cost_usd, created_at) "
                  "VALUES ('Recruiter', 'm', 1, 1, 2.99, ?)", hq.db.now())
    assert "used $2.99" in hq.recruiter.why_not_now()
    monkeypatch.setenv("HQ_RECRUITER_MONTHLY_BUDGET", "50")
    monkeypatch.setattr(hq.ledger, "spent_today", lambda v=None: 4.99)
    assert "Today's Claude budget" in hq.recruiter.why_not_now()


def test_bad_answer_adds_nothing(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    monkeypatch.setattr(hq.llm, "HAS_LLM", True)
    monkeypatch.setattr(hq.llm, "create", lambda *a, **k: SimpleNamespace(
        content=[SimpleNamespace(type="text", text="{not json")], stop_reason="max_tokens"))
    assert "cut off" in hq.recruiter.run()
    assert hq.db.rows("SELECT COUNT(*) n FROM ideas")[0]["n"] == 0


def test_recruiter_proposals_do_not_block_muse(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    _fake_llm(monkeypatch, hq, GOOD)
    hq.recruiter.run()
    assert hq.muse.open_ideas() == 0 and hq.recruiter.waiting() == 2


def test_approve_card_and_build_flow(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    _fake_llm(monkeypatch, hq, GOOD)
    hq.recruiter.run()
    aid = hq.approvals.pending()[0]["id"]
    msg = hq.approvals.decide(aid, "approve")
    assert "approved" in msg
    row = hq.db.rows("SELECT * FROM ideas WHERE status = 'approved'")[0]
    assert "Build this for Agent HQ" in hq.muse.brief(row)
    aid2 = hq.approvals.pending()[0]["id"]
    hq.approvals.decide(aid2, "reject")
    assert hq.db.rows("SELECT COUNT(*) n FROM ideas WHERE status = 'rejected'")[0]["n"] == 1


def test_agent_registered_and_scheduled(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    import hq.agents
    importlib.reload(hq.agents)
    a = hq.agents.get("recruiter")
    assert a and a.village == "business" and a.schedule
    monkeypatch.setattr(hq.llm, "HAS_LLM", False)
    assert a.nothing_to_do("x", {}) is True   # free look: no key, no task


def test_api_state_and_run(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    _fake_llm(monkeypatch, hq, GOOD)
    c = TestClient(hq.api.app)
    st = c.get("/api/recruiter").json()
    assert st["per_day"] == 2 and st["waiting"] == 0 and st["enabled"]
    assert c.post("/api/recruiter/run").status_code == 403
    r = c.post("/api/recruiter/run", headers={"X-HQ": "1"})
    assert r.status_code == 200 and r.json()["task_id"]
    assert "already looking" in c.post("/api/recruiter/run", headers={"X-HQ": "1"}).json()["message"]
    shown = c.get("/api/muse").json()
    assert shown["ideas"] == []
    hq.recruiter.run(manual=True)
    ideas = c.get("/api/muse").json()["ideas"]
    assert len(ideas) == 2 and ideas[0]["source"] == "recruiter" and ideas[0]["rating"]
