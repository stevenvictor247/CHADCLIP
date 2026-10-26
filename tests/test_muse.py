"""Muse, the Creative Director: free checks before spending, no repeats, honest ranking, Approvals, caps and the tab."""

import importlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient


def _fresh(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("HQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HQ_PASSWORD", "")
    for k in ("HQ_MUSE", "HQ_MUSE_EVERY_DAYS", "HQ_MUSE_MONTHLY_BUDGET", "HQ_MUSE_IDEAS", "HQ_MUSE_TO_APPROVALS",
              "HQ_MODEL_MUSE", "HQ_AGENT_MODEL", "HQ_MUSE_BATCH", "HQ_MUSE_EFFORT", "HQ_BUILD_TOKEN", "HQ_BUILD_URL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import hq.config, hq.db, hq.ledger, hq.muse, hq.api
    for m in (hq.config, hq.db, hq.ledger, hq.muse, hq.api):
        importlib.reload(m)
    hq.db.init()
    monkeypatch.setattr(hq.muse, "DAILY_BUDGET", 5.0)
    return hq


def _idea(title, kind="business", low=100, high=300, conf=0.5, start=20, monthly=0, effort="small", hours=4, **kw):
    return {"kind": kind, "title": title, "name": kw.get("name"), "pitch": kw.get("pitch", f"{title}: a real plan."),
            "why_now": "Because of a fact.", "builds_on": ["Chad"], "first_steps": ["Do one", "Do two", "Do three"],
            "steven_does": "Sign up, 10 minutes.", "risks": "Might earn $0.", "start_cost_usd": start,
            "monthly_cost_usd": monthly, "effort": effort, "effort_hours": hours, "profit_low_usd_month": low,
            "profit_high_usd_month": high, "months_to_first_dollar": 1, "confidence": conf, "repeats": kw.get("repeats")}


GOOD = [
    _idea("Stream recap carousels for Pinterest", low=50, high=150),
    _idea("Clip bundles sold to podcast editors", low=200, high=600, conf=0.4, hours=6),
    _idea("Coach wristband card builder app", kind="addon", low=20, high=80),
    _idea("Kick clipping network scout", kind="agent", name="Kicker", low=40, high=120, effort="medium"),
    _idea("Weekly win wall in HQ Town", kind="hq", low=0, high=30, conf=0.3, hours=1),
]


def _fake_llm(monkeypatch, hq, ideas, calls=None):
    def create(model, system, messages, **kw):
        if calls is not None:
            calls.append({"model": model, "prompt": messages[0]["content"], **kw})
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps({"ideas": ideas}))])
    monkeypatch.setattr(hq.llm, "HAS_LLM", True)
    monkeypatch.setattr(hq.llm, "create", create)


class FakeQueue:
    """Claude's batch queue, in memory."""
    def __init__(self, ideas, outcome="succeeded"):
        self.ideas, self.outcome, self.status, self.sent, self.cancelled = ideas, outcome, "in_progress", [], False

    def create(self, requests):
        self.sent.append(requests)
        return SimpleNamespace(id="msgbatch_1", processing_status="in_progress")

    def retrieve(self, batch_id):
        assert batch_id == "msgbatch_1"
        return SimpleNamespace(processing_status=self.status)

    def cancel(self, batch_id):
        self.cancelled = True

    def results(self, batch_id):
        msg = SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps({"ideas": self.ideas}))],
                              model="claude-sonnet-5-5", stop_reason="end_turn",
                              usage=SimpleNamespace(input_tokens=5000, output_tokens=4000, cache_read_input_tokens=0,
                                                    cache_creation_input_tokens=0))
        return [SimpleNamespace(custom_id="muse", result=SimpleNamespace(type=self.outcome, message=msg))]


def _fake_queue(monkeypatch, hq, ideas, outcome="succeeded"):
    q = FakeQueue(ideas, outcome)
    monkeypatch.setattr(hq.llm, "HAS_LLM", True)
    monkeypatch.setattr(hq.llm, "client", lambda: SimpleNamespace(messages=SimpleNamespace(batches=q)))
    monkeypatch.setattr(hq.llm, "create", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no live call")))
    return q


def _usage(db, agent, usd):
    db.execute("INSERT INTO llm_usage (agent, model, input_tokens, output_tokens, cost_usd, created_at) "
               "VALUES (?, 'claude-sonnet-5-5', 1, 1, ?, ?)", agent, usd, db.now())


def test_muse_lives_in_the_main_village_on_a_weekly_check():
    from hq import muse, sweep
    from hq.agents import AGENTS
    from hq.config import DEFAULT_MODELS
    m = AGENTS["muse"]
    assert m.village == "business" and not m.free          # it calls Claude, so the daily budget applies
    assert m.schedule == [(0.25, "Pick up the weekly ideas from Claude's queue.", {"collect": True})]
    from hq import boss
    assert [o[0] for o in boss.WEEKLY_ORDERS] == ["Muse"] and boss.WEEKLY_ORDERS[0][2] == {"weekly": True}
    assert DEFAULT_MODELS["muse"] == "claude-sonnet-5-5"
    assert "muse" in sweep.PROTECTED                         # Sweep never suggests a cheaper model for judgement work
    assert muse.approvals.HANDLERS["muse_idea"]


def test_repeats_and_rule_breakers_are_dropped(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    m = hq.muse
    kept, dropped = m.sift([
        _idea("Morning brief on Telegram"),                                   # Sunny, on the earlier ideas page
        _idea("Etsy shop of digital football coaching tools"),               # the business plan's pick
        _idea("Move HQ to a cloud server"),                                  # parked by Steven
        _idea("Sports betting picks newsletter"),                            # off limits
        _idea("Merch with NFL team logos"),                                  # trademarks
        _idea("Shirts for the school", pitch="Shirts with the school's logo for fans."),
        _idea("Auto DM bot for streamers", pitch="Mass DMs to streamers to sell clips."),
        _idea("Clip vault", repeats="Penny: views and stats for every clip"),  # Claude flagged it itself
        _idea("Stats agent", kind="agent", name="Tally"),                    # an agent HQ already has
        GOOD[0],
        _idea("Pinterest stream recap carousels"),                            # same as the one just kept
        GOOD[1],
    ])
    assert [i["title"] for i in kept] == [GOOD[0]["title"], GOOD[1]["title"]]
    assert len(dropped) == 10
    text = " ".join(dropped)
    assert "Sunny" in text and "Etta" in text and "back burner" in text and "betting" in text
    assert "trademarks" in text and "school" in text and "spam" in text and "Penny" in text and "Tally" in text


def test_ranking_is_arithmetic_on_sane_numbers(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    m = hq.muse
    i = m.clean({**_idea("Odd numbers"), "profit_low_usd_month": 900, "profit_high_usd_month": -50, "confidence": 4,
                 "effort": "huge", "kind": "nonsense", "start_cost_usd": "lots", "effort_hours": 0})
    assert (i["profit_low"], i["profit_high"]) == (0, 900)       # negative and swapped ranges are fixed
    assert i["confidence"] == 0.95 and i["effort"] == "medium" and i["kind"] == "addon" and i["start_cost"] == 0
    assert i["effort_hours"] == 0.5
    # (100+300)/2 * 0.5 = 100 a month; first year 1200 - 20 start = 1180; over 4 h + 2 h build = 196.7
    assert m.score(m.clean(_idea("Plain"))) == 196.7
    cheap_quick = m.score(m.clean(_idea("A", low=100, high=100, conf=0.5, hours=2)))
    pricey_slow = m.score(m.clean(_idea("B", low=300, high=300, conf=0.5, hours=40, effort="large", monthly=100)))
    assert cheap_quick > pricey_slow
    assert m.payback_months(m.clean(_idea("C", start=200, low=100, high=100, conf=1))) == 2.1


def test_a_round_ranks_ideas_and_brings_the_best_to_approvals(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    calls = []
    _fake_llm(monkeypatch, hq, GOOD + [_idea("Morning brief on Telegram")], calls)
    out = hq.muse.run(focus="the clipping accounts", manual=True)
    assert "5 new idea(s), 3 brought to Approvals" in out and "Dropped 1" in out
    assert calls[0]["model"] == "claude-sonnet-5-5" and calls[0]["output_schema"] and calls[0]["agent"] == "Muse"
    p = calls[0]["prompt"]
    assert "the clipping accounts" in p and "Sunny: morning brief" in p and "Run HQ on a cloud server 24/7 [parked]" in p
    rows = hq.db.rows("SELECT * FROM ideas ORDER BY score DESC")
    assert len(rows) == 5 and all(r["status"] == "proposed" and r["focus"] == "the clipping accounts" for r in rows)
    cards = hq.db.rows("SELECT * FROM approvals WHERE kind = 'muse_idea' ORDER BY id")
    assert len(cards) == 3 and cards[0]["agent"] == "Muse" and cards[0]["yes_label"] == "👍 Build it"
    assert [json.loads(c["payload"])["idea_id"] for c in cards] == [r["id"] for r in rows[:3]]   # best three, in order
    assert "💰 About" in cards[0]["preview"] and "First steps: 1)" in cards[0]["preview"]
    assert hq.db.rows("SELECT approval_id FROM ideas WHERE id = ?", rows[0]["id"])[0]["approval_id"] == cards[0]["id"]
    assert hq.muse.latest()["last_round"]["kept"] == 5
    # the same ideas again are all repeats now, so nothing is added twice
    out = hq.muse.run(manual=True)
    assert out.startswith("No new ideas this round") and hq.db.rows("SELECT COUNT(*) n FROM ideas")[0]["n"] == 5


def test_free_checks_decide_when_a_scheduled_round_is_worth_it(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path, HQ_MUSE_BATCH="false")
    agent = hq.muse and __import__("hq.agents", fromlist=["AGENTS"]).AGENTS["muse"]
    params = {"brainstorm": True}
    monkeypatch.setattr(hq.llm, "HAS_LLM", False)
    assert agent.nothing_to_do("x", params) is True                  # no key: nothing can happen
    _fake_llm(monkeypatch, hq, GOOD)
    assert agent.nothing_to_do("x", params) is False                 # first ever round
    hq.muse.run()
    assert "waiting for your answer" in hq.muse.why_not_now()        # 5 unanswered ideas: no more until he looks
    assert agent.nothing_to_do("x", params) is True
    for r in hq.db.rows("SELECT id FROM ideas"):
        hq.muse.decide(r["id"], "later")
    assert hq.muse.why_not_now().startswith("Next round in about 7 day")   # answered, but it's only been minutes
    state = hq.muse._state()
    state["last_round_at"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(timespec="seconds")
    hq.muse._save_state(state)
    assert agent.nothing_to_do("x", params) is False
    monkeypatch.setenv("HQ_MUSE", "false")
    assert agent.nothing_to_do("x", params) is True                  # weekly round switched off
    assert hq.muse.why_not_now(manual=True) is None                  # but Brainstorm now still works
    # a scheduled task that finds the door shut says so without calling Claude
    monkeypatch.setattr(hq.llm, "create", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    assert agent.run({"params": json.dumps(params), "created_by": "Schedule"}).startswith("Skipped:")


def test_money_caps_hold_even_for_the_button(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path, HQ_MUSE_MONTHLY_BUDGET="1")
    _fake_llm(monkeypatch, hq, GOOD)
    assert hq.muse.round_cost_estimate() == 0.136                    # 8k in + 12k out on Sonnet
    assert hq.muse.round_cost_estimate(weekly=True) == 0.068         # the weekly round is half price
    _usage(hq.db, "Muse", 0.9)
    assert "of its $1.00 for this month" in hq.muse.why_not_now(manual=True)
    assert "Muse has used" in hq.muse.run(manual=True)
    assert hq.db.rows("SELECT COUNT(*) n FROM ideas")[0]["n"] == 0
    hq = _fresh(monkeypatch, tmp_path / "b")
    _fake_llm(monkeypatch, hq, GOOD)
    _usage(hq.db, "Chad", 4.9)                                       # the day's HQ budget is nearly gone
    assert "Today's Claude budget" in hq.muse.why_not_now(manual=True)
    hq = _fresh(monkeypatch, tmp_path / "c", HQ_MUSE_MONTHLY_BUDGET="0")
    assert "switched off" in hq.muse.why_not_now(manual=True)


def test_answers_close_cards_teach_muse_and_give_a_brief(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    _fake_llm(monkeypatch, hq, GOOD)
    hq.muse.run(manual=True)
    cards = hq.db.rows("SELECT * FROM approvals WHERE kind = 'muse_idea' ORDER BY id")
    first = json.loads(cards[0]["payload"])["idea_id"]
    # a tap on the Approvals card (dashboard or phone) approves the idea
    msg = hq.approvals.decide(cards[0]["id"], "approve")
    assert "build brief" in msg
    shaped = [i for i in hq.muse.ideas() if i["id"] == first][0]
    assert shaped["status"] == "approved" and shaped["title"] in shaped["brief"]
    assert "github.com/stevenvictor247/CHADCLIP" in shaped["brief"] and "without my approval" in shaped["brief"]
    # an answer on the Ideas tab closes that idea's Approvals card too
    second = json.loads(cards[1]["payload"])["idea_id"]
    assert "won't pitch" in hq.muse.decide(second, "pass", "Too much work")
    assert hq.db.rows("SELECT status FROM approvals WHERE id = ?", cards[1]["id"])[0]["status"] == "rejected"
    assert hq.approvals.decide(cards[1]["id"], "approve") == "Already rejected."
    assert hq.db.rows("SELECT reason FROM ideas WHERE id = ?", second)[0]["reason"] == "Too much work"
    assert "said NO, because: Too much work" in hq.muse._decisions_text()
    assert "said BUILD IT" in hq.muse._decisions_text()
    hq.muse.decide(second, "reopen")
    assert hq.db.rows("SELECT status, reason FROM ideas WHERE id = ?", second)[0] == {"status": "proposed", "reason": None}
    assert "marked built" in hq.muse.decide(first, "built")
    try:
        hq.muse.decide(first, "maybe")
        assert False
    except ValueError:
        pass


def test_an_approved_agent_idea_is_marked_built_when_the_agent_exists(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    i = hq.muse.clean(_idea("Counting house", kind="agent", name="Tally"))
    iid = hq.muse.save(i, None)
    hq.muse.decide(iid, "build")
    assert hq.muse.mark_built_agents() == 1
    assert hq.db.rows("SELECT status FROM ideas WHERE id = ?", iid)[0]["status"] == "built"


def test_facts_and_prompt_work_on_an_empty_hq(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    f = hq.muse.facts()
    assert {a["name"] for a in f["team"]} >= {"Chad", "Scout", "Pitch", "Tally", "Sweep", "Muse", "Captain"}
    p = hq.muse.prompt(None, 5)
    assert "at least one new business, one new agent and one add-on" in p and "Give exactly 5 ideas" in p
    assert "hasn't decided" in p


def test_dashboard_routes(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    c = TestClient(hq.api.app)
    assert c.get("/muse-panel.js").status_code == 200
    d = c.get("/api/muse").json()
    assert d["ideas"] == [] and d["monthly_budget"] == 3 and d["per_round"] == 5 and "Too much work" in d["reasons"]
    assert c.post("/api/muse/run", json={}).status_code == 403                    # only from the HQ page
    monkeypatch.setattr(hq.llm, "HAS_LLM", False)
    r = c.post("/api/muse/run", json={}, headers={"X-HQ": "1"})
    assert r.status_code == 409 and "API key" in r.json()["detail"]
    monkeypatch.setattr(hq.llm, "HAS_LLM", True)
    r = c.post("/api/muse/run", json={"focus": "football fans"}, headers={"X-HQ": "1"})
    assert r.status_code == 200
    task = hq.db.rows("SELECT * FROM tasks WHERE agent = 'Muse'")[0]
    assert json.loads(task["params"]) == {"focus": "football fans"} and task["created_by"] == "Steven"
    assert "already thinking" in c.post("/api/muse/run", json={}, headers={"X-HQ": "1"}).json()["message"]
    assert c.get("/api/muse").json()["running"] is True
    iid = hq.muse.save(hq.muse.clean(_idea("Something new")), None)
    r = c.post(f"/api/muse/ideas/{iid}/later", json={"reason": "Bad timing"}, headers={"X-HQ": "1"})
    assert r.status_code == 200 and "parked" in r.json()["message"]
    assert c.post("/api/muse/ideas/999/build", json={}, headers={"X-HQ": "1"}).status_code == 404
    assert c.post(f"/api/muse/ideas/{iid}/nope", json={}, headers={"X-HQ": "1"}).status_code == 400
    s = c.get("/api/state").json()
    assert s["ideas"]["open"] == 0 and any(a["name"] == "Muse" and a["village"] == "business" for a in s["agents"])


def test_boss_and_sweep_know_about_muse(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    import hq.boss, hq.quality
    assert "Muse is the Creative Director" in hq.boss.SYSTEM
    iid = hq.muse.save(hq.muse.clean(_idea("Old idea")), None)
    assert hq.boss.get_status()["ideas"]["open"] == 1
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(timespec="seconds")
    hq.db.execute("UPDATE ideas SET created_at = ? WHERE id = ?", old, iid)
    tips = [t for t in hq.quality.check_other_agents() if t["id"] == "muse_waiting"]
    assert tips and tips[0]["link"]["href"] == "/#ideas"


def test_village_and_tab_are_wired():
    from pathlib import Path
    static = Path(__file__).parent.parent / "hq/static"
    html = (static / "index.html").read_text(encoding="utf-8")
    world = (static / "world.js").read_text(encoding="utf-8")
    tabs = (static / "hq-tabs.js").read_text(encoding="utf-8")
    assert html.index('src="/muse-panel.js"') < html.index('src="/hq-tabs.js"') and 'id="muse"' in html
    assert 'Muse: {color:' in html and "beret:" in html
    assert 'label: "Writers\' Room"' in world and 'style: "writers"' in world and 'key === "muse" ? S.ideas' in world and "ideasCard()" in world
    assert '{id: "ideas", icon: "💡", label: "Ideas", has: ["muse"]}' in tabs


def test_the_boss_sends_muse_weekly_through_the_half_price_queue(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    import hq.boss
    from hq.agents import AGENTS
    agent = AGENTS["muse"]
    q = _fake_queue(monkeypatch, hq, GOOD)
    assert agent.nothing_to_do("x", {"collect": True}) is True       # nothing in the queue: no task, no network
    state = {}
    [task_id] = hq.boss.send_weekly_orders(state)
    assert hq.boss.send_weekly_orders(state) == []                   # looks at most once an hour
    task = hq.db.rows("SELECT * FROM tasks WHERE id = ?", task_id)[0]
    assert task["agent"] == "Muse" and task["created_by"] == "Boss"
    assert "Sent Muse on its weekly round." in [r["message"] for r in hq.db.rows("SELECT message FROM activity")]
    out = agent.run(task)
    assert out.startswith("Asked Claude for 5 ideas through the half-price queue")
    params = q.sent[0][0]["params"]
    assert q.sent[0][0]["custom_id"] == "muse" and "fallbacks" not in params      # the queue rejects fallbacks
    assert params["output_config"]["effort"] == "medium" and params["thinking"] == {"type": "adaptive"}
    assert params["output_config"]["format"]["schema"] == hq.muse.SCHEMA and params["max_tokens"] == 12000
    assert "Give exactly 5 ideas" in params["messages"][0]["content"]
    # while it's out, nothing else starts: no second weekly round and no full-price Brainstorm now
    assert "half-price queue" in hq.muse.why_not_now(manual=True)
    state["boss_orders_at"] = 0
    assert hq.boss.send_weekly_orders(state) == []
    assert hq.muse.summary()["thinking"] and hq.muse.latest()["queued"]
    assert agent.nothing_to_do("x", {"collect": True}) is True       # still being worked on
    q.status = "ended"
    assert agent.nothing_to_do("x", {"collect": True}) is False
    out = agent.run({"params": json.dumps({"collect": True}), "created_by": "Schedule"})
    assert out.startswith("5 new idea(s), 3 brought to Approvals")
    cost = hq.db.rows("SELECT agent, cost_usd FROM llm_usage")
    assert cost == [{"agent": "Muse", "cost_usd": hq.ledger.cost_of("claude-sonnet-5-5", 5000, 4000) * 0.5}]
    assert hq.muse.pending() is None and not hq.muse.summary()["thinking"]
    assert "waits until there's room for at least 3" in hq.muse.why_not_now()


def test_weekly_round_only_asks_for_the_free_places(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path, HQ_MUSE_BATCH="false")
    calls = []
    _fake_llm(monkeypatch, hq, GOOD[:2], calls)
    hq.muse.run(manual=True)                                          # two ideas still open
    assert hq.muse.wanted(manual=False) == 3 and hq.muse.wanted(manual=True) == 5
    state = hq.muse._state()
    state["last_round_at"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(timespec="seconds")
    hq.muse._save_state(state)
    _fake_llm(monkeypatch, hq, GOOD[2:], calls)
    hq.muse.run()
    assert "Give exactly 3 ideas" in calls[-1]["prompt"] and calls[-1]["effort"] == "medium"
    assert "waits until there's room" in hq.muse.why_not_now()        # 5 open now
    assert '"team":[' in calls[-1]["prompt"]                          # facts sent compact, not pretty-printed


def test_a_round_that_fails_in_the_queue_retries_in_a_day_and_costs_nothing(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    q = _fake_queue(monkeypatch, hq, GOOD, outcome="errored")
    hq.muse.run()
    q.status = "ended"
    assert "didn't come back (errored)" in hq.muse.collect()
    assert hq.muse.pending() is None and hq.db.rows("SELECT COUNT(*) n FROM llm_usage")[0]["n"] == 0
    assert hq.muse.why_not_now() == "Next round in about 1 day(s)."
    # a round stuck past a day is cancelled and retried the same way
    q = _fake_queue(monkeypatch, hq, GOOD)
    state = hq.muse._state()
    state["last_round_at"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(timespec="seconds")
    hq.muse._save_state(state)
    hq.muse.run()
    state = hq.muse._state()
    state["batch"]["at"] = (datetime.now(timezone.utc) - timedelta(hours=27)).isoformat(timespec="seconds")
    hq.muse._save_state(state)
    assert hq.muse.batch_ready() is True
    assert "took over a day" in hq.muse.collect() and q.cancelled


def test_a_cut_off_answer_is_reported_not_crashed(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    monkeypatch.setattr(hq.llm, "HAS_LLM", True)
    monkeypatch.setattr(hq.llm, "create", lambda *a, **k: SimpleNamespace(
        content=[SimpleNamespace(type="text", text='{"ideas": [{"kind": "bus')], stop_reason="max_tokens"))
    assert hq.muse.run(manual=True).startswith("Claude's answer was cut off")
    assert hq.db.rows("SELECT COUNT(*) n FROM ideas")[0]["n"] == 0


def test_build_it_sends_the_brief_to_claude_once(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    _fake_llm(monkeypatch, hq, GOOD)
    hq.muse.run(manual=True)
    ids = [r["id"] for r in hq.db.rows("SELECT id FROM ideas ORDER BY id")]
    # not connected yet: Build it still approves and offers the brief, and nothing is sent
    monkeypatch.setattr(hq.muse, "_fire", lambda text: (_ for _ in ()).throw(AssertionError("not connected")))
    assert "paste it to Claude" in hq.muse.decide(ids[0], "build")
    assert hq.muse.latest()["build_ready"] is False
    sent = []
    monkeypatch.setattr(hq.muse, "_fire", lambda text: sent.append(text) or {
        "type": "routine_fire", "claude_code_session_url": "https://claude.ai/code/session_1"})
    monkeypatch.setenv("HQ_BUILD_TOKEN", "sk-ant-oat01-test")
    assert hq.muse.build_ready() and hq.muse.build_url().endswith("/routines/trig_01VtqaeKDHmdfWDv1C48fanf/fire")
    # the Approvals card (dashboard or phone) and the Ideas tab both send it
    card = hq.db.rows("SELECT id FROM approvals WHERE kind = 'muse_idea' AND payload LIKE ?", f'%"idea_id": {ids[1]}%')[0]
    assert "Sent to Claude to build it" in hq.approvals.decide(card["id"], "approve")
    text = sent[0]
    assert text.startswith(f"Idea #{ids[1]}: ") and "Steven pressed Build it in Agent HQ" in text
    assert "BUILD BRIEF (written by Muse)" in text and "github.com/stevenvictor247/CHADCLIP" in text
    assert "sk-ant" not in text                                              # the token never goes in the message
    row = hq.db.rows("SELECT build_status, build_url FROM ideas WHERE id = ?", ids[1])[0]
    assert row == {"build_status": "started", "build_url": "https://claude.ai/code/session_1"}
    assert "already has this one" in hq.muse.start_build(ids[1]) and len(sent) == 1   # never sent twice
    assert "Only an idea you said Build it to" in hq.muse.start_build(ids[2])
    # the first idea, approved before the token was added, can be sent from the tab
    assert "Sent to Claude" in hq.muse.start_build(ids[0]) and len(sent) == 2


def test_a_failed_send_is_explained_and_can_be_retried(monkeypatch, tmp_path):
    import io
    import urllib.error
    hq = _fresh(monkeypatch, tmp_path, HQ_BUILD_TOKEN="sk-ant-oat01-secret-token")
    _fake_llm(monkeypatch, hq, GOOD[:1])
    hq.muse.run(manual=True)
    idea = hq.db.rows("SELECT id FROM ideas")[0]["id"]
    def refuse(text):
        raise urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b'{"error": {"message": "bad token"}}'))
    monkeypatch.setattr(hq.muse, "_fire", refuse)
    out = hq.muse.decide(idea, "build")
    assert "couldn't be sent" in out and "token in Settings doesn't match" in out and "secret" not in out
    row = hq.db.rows("SELECT build_status, build_note FROM ideas WHERE id = ?", idea)[0]
    assert row["build_status"] == "failed" and "doesn't match" in row["build_note"]
    monkeypatch.setattr(hq.muse, "_fire", lambda text: {"claude_code_session_url": "javascript:alert(1)"})
    client = TestClient(hq.api.app)
    assert client.post(f"/api/muse/ideas/{idea}/send").status_code == 403          # only from the HQ page
    r = client.post(f"/api/muse/ideas/{idea}/send", headers={"X-HQ": "1"})
    assert r.status_code == 200 and "Sent to Claude" in r.json()["message"]
    assert hq.db.rows("SELECT build_status, build_url FROM ideas WHERE id = ?", idea)[0] == {
        "build_status": "started", "build_url": None}                         # only claude.ai links are kept
    assert client.post("/api/muse/ideas/999/send", headers={"X-HQ": "1"}).status_code == 404
    # a changed address must still be an Anthropic routine address
    monkeypatch.setenv("HQ_BUILD_URL", "https://evil.example.com/fire")
    assert hq.muse.build_ready() is False
