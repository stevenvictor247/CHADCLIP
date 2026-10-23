import importlib
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


def _fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("HQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HQ_PASSWORD", "")
    for k in ("HQ_MODEL_TELLS",):
        monkeypatch.delenv(k, raising=False)
    import hq.config, hq.db, hq.ledger, hq.sweep, hq.api
    for m in (hq.config, hq.db, hq.ledger, hq.sweep, hq.api):
        importlib.reload(m)
    hq.db.init()
    return hq


def _ago(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat(timespec="seconds")


def _task(db, agent, status, ago, result=None, created_by="boss"):
    ts = _ago(**ago)
    return db.execute("INSERT INTO tasks (agent, instructions, status, result, created_by, created_at, updated_at) "
                      "VALUES (?, 'do it', ?, ?, ?, ?, ?)", agent, status, result, created_by, ts, ts)


def _usage(db, agent, model, usd, n=1, inp=1000, outp=100, cread=0, ago=None):
    for _ in range(n):
        db.execute("INSERT INTO llm_usage (agent, model, input_tokens, output_tokens, cache_read_tokens, cost_usd, created_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?)", agent, model, inp, outp, cread, usd, _ago(**(ago or {"minutes": 5})))


def test_stuck_task_goes_back_once_then_is_closed(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    tid = _task(hq.db, "Chad", "running", {"hours": 3})
    assert "back in the queue" in hq.sweep.fix_stuck_tasks()[0]
    assert hq.db.rows("SELECT status FROM tasks WHERE id = ?", tid)[0]["status"] == "queued"
    # a fresh task that is "running" right now is left alone
    fresh = _task(hq.db, "Chad", "running", {"minutes": 5})
    hq.db.execute("UPDATE tasks SET status = 'running', updated_at = ? WHERE id = ?", _ago(hours=3), tid)
    assert "second time" in hq.sweep.fix_stuck_tasks()[0]
    assert hq.db.rows("SELECT status FROM tasks WHERE id = ?", tid)[0]["status"] == "failed"
    assert hq.db.rows("SELECT status FROM tasks WHERE id = ?", fresh)[0]["status"] == "running"


def test_only_temporary_failures_are_retried_once(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    flaky = _task(hq.db, "Chad", "failed", {"hours": 1}, "Connection timed out")
    broken = _task(hq.db, "Chad", "failed", {"hours": 1}, "KeyError: 'title'")
    assert len(hq.sweep.fix_failed_tasks()) == 1
    assert hq.sweep.fix_failed_tasks() == []                       # not twice
    made = hq.db.rows("SELECT * FROM tasks WHERE created_by = 'Sweep'")
    assert len(made) == 1 and made[0]["agent"] == "Chad"
    assert hq.db.rows("SELECT status FROM tasks WHERE id = ?", broken)[0]["status"] == "failed"
    assert flaky != made[0]["id"]


def test_old_files_go_to_the_trash_and_can_be_restored(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    old = hq.sweep.SOURCES_DIR / "abc.mp4"
    mine = hq.sweep.SOURCES_DIR / "try-20260101-mine.mp4"
    new = hq.sweep.SOURCES_DIR / "new.mp4"
    for p in (old, mine, new):
        p.write_bytes(b"x" * 100)
    long_ago = time.time() - 30 * 86400
    os.utime(old, (long_ago, long_ago))
    os.utime(mine, (long_ago, long_ago))
    acts = hq.sweep.tidy_files()
    assert any("old source download" in a for a in acts)
    assert not old.exists() and mine.exists() and new.exists()   # your own uploads and fresh files stay
    rec = hq.sweep.trash_summary()[0]
    assert "restored" in hq.sweep.restore(rec["id"]).lower() or old.exists()
    assert old.exists() and hq.sweep.trash_summary() == []


def test_trash_is_emptied_after_a_week(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    f = tmp_path / "junk.txt"
    f.write_text("junk")
    rec = hq.sweep.trash(f, "test")
    index = json.loads((hq.sweep.TRASH_DIR / "index.json").read_text())
    index[0]["at"] = _ago(days=10)
    (hq.sweep.TRASH_DIR / "index.json").write_text(json.dumps(index))
    assert hq.sweep.purge_trash() == 4
    assert hq.sweep.trash_summary() == [] and not (hq.sweep.TRASH_DIR / rec["stored"]).exists()
    with pytest.raises(ValueError):
        hq.sweep.restore(rec["id"])


def test_big_log_is_trimmed_with_a_full_copy_kept(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    log = tmp_path / "desktop-app.log"
    log.write_bytes(b"a" * (6 * 1024 * 1024))
    assert any("Trimmed" in a for a in hq.sweep.tidy_files())
    assert log.stat().st_size == 1024 * 1024
    assert hq.sweep.trash_summary()[0]["bytes"] == 6 * 1024 * 1024


def test_idle_huge_boss_chat_is_closed_but_active_one_is_not(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    import hq.boss
    importlib.reload(hq.boss)
    big = json.dumps([{"type": "text", "text": "x" * 600_000}])
    hq.db.execute("INSERT INTO boss_messages (conversation, role, content, created_at) VALUES (1, 'user', ?, ?)", big, _ago(minutes=10))
    assert hq.sweep.fix_boss_chat() == []                      # talked to a moment ago
    hq.db.execute("UPDATE boss_messages SET created_at = ?", _ago(hours=5))
    assert "fresh Boss conversation" in hq.sweep.fix_boss_chat()[0]
    assert hq.boss.current_conversation() == 2
    assert hq.sweep.fix_boss_chat() == []                      # the new one is empty


def test_problems_found(monkeypatch, tmp_path):
    monkeypatch.setenv("HQ_DAILY_BUDGET", "1")
    hq = _fresh(monkeypatch, tmp_path)
    _usage(hq.db, "Boss", "claude-opus-5-5", 0.1, n=6, inp=5000)                 # big prompts, no cache reads
    _usage(hq.db, "Scout", "claude-haiku-5-5", 0.01, n=35)                       # a burst of calls
    _usage(hq.db, "Chad", "mystery-model", 0.9)
    for _ in range(3):
        _task(hq.db, "Pitch", "failed", {"hours": 1}, "bad")
    kinds = {p["kind"] for p in hq.sweep.find_problems()}
    assert {"budget", "cache", "loop", "failing", "price"} <= kinds


def test_cheaper_model_is_asked_for_and_applied_only_on_approval(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    _usage(hq.db, "Tells", "claude-sonnet-5-5", 0.003, n=400, inp=800, outp=100)   # not protected, small requests
    _usage(hq.db, "Boss", "claude-opus-5-5", 0.01, n=400, inp=800, outp=100)        # protected: never suggested
    problems = hq.sweep.find_problems()
    assert [p["title"] for p in problems if p["kind"] == "model"] == ["Asked: switch Tells to claude-haiku-5-5?"]
    import hq.approvals
    pending = hq.approvals.pending()
    assert len(pending) == 1 and pending[0]["kind"] == "sweep_model"
    assert not os.getenv("HQ_MODEL_TELLS")
    hq.sweep.find_problems()                                                       # no second question
    assert len(hq.approvals.pending()) == 1
    hq.approvals.HANDLERS["sweep_model"] = hq.sweep._apply_model
    assert "now claude-haiku-5-5" in hq.approvals.decide(pending[0]["id"], "approve")
    assert os.environ["HQ_MODEL_TELLS"] == "claude-haiku-5-5"
    monkeypatch.delenv("HQ_MODEL_TELLS")


def test_rejecting_a_cheaper_model_changes_nothing(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    assert hq.sweep._apply_model({"setting": "HQ_MODEL_TELLS", "to": "claude-haiku-5-5"}, "reject") == "Kept the current model."
    assert not os.getenv("HQ_MODEL_TELLS")


def test_daily_report_sent_once_and_listed(monkeypatch, tmp_path):
    monkeypatch.setenv("HQ_SWEEP_REPORT_HOUR", "0")
    hq = _fresh(monkeypatch, tmp_path)
    sent = []
    import hq.relay
    monkeypatch.setattr(hq.relay, "notify", lambda text: sent.append(text))
    _usage(hq.db, "Chad", "claude-sonnet-5-5", 0.4, ago={"hours": 30})
    _task(hq.db, "Chad", "running", {"hours": 4})
    assert "Sent the daily report" in hq.sweep.run()
    assert len(sent) == 1 and "Sweep's daily report" in sent[0] and "Put task" in sent[0]
    hq.sweep.run()
    assert len(sent) == 1                                                          # only once a day
    latest = hq.sweep.latest()
    assert latest["report"]["day"] == datetime.now().strftime("%Y-%m-%d") and latest["mess"] == len(latest["report"]["problems"])


def test_sweep_is_an_agent_that_still_runs_when_the_budget_is_spent(monkeypatch, tmp_path):
    monkeypatch.setenv("HQ_DAILY_BUDGET", "1")
    hq = _fresh(monkeypatch, tmp_path)
    import hq.agents, hq.worker
    importlib.reload(hq.agents.base)
    sweep = hq.agents.get("Sweep")
    assert sweep and sweep.free and sweep.village == "business"
    _usage(hq.db, "Chad", "claude-sonnet-5-5", 2.0)
    assert hq.ledger.over_budget()
    hq.worker.queue_scheduled({})
    queued = {t["agent"] for t in hq.db.rows("SELECT agent FROM tasks")}
    assert queued == {"Sweep"}                                                     # Claude agents wait, Sweep doesn't


def test_dashboard_routes(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    c = TestClient(hq.api.app)
    assert c.get("/sweep-panel.js").status_code == 200
    assert c.get("/api/sweep").json()["report"] is None
    assert c.post("/api/sweep/run").status_code == 403                            # only from the dashboard
    r = c.post("/api/sweep/run", headers={"X-HQ": "1"})
    task = hq.db.rows("SELECT * FROM tasks WHERE id = ?", r.json()["task_id"])[0]
    assert task["agent"] == "Sweep" and json.loads(task["params"]) == {"report": True}
    assert c.post("/api/sweep/restore/99", headers={"X-HQ": "1"}).status_code == 409


def test_boss_chat_asks_for_prompt_caching(monkeypatch):
    import hq.llm as llm
    seen = {}

    class Fake:
        class beta:
            class messages:
                @staticmethod
                def create(**kw):
                    seen.update(kw)
                    raise RuntimeError("stop")

    monkeypatch.setattr(llm, "client", lambda: Fake)
    for cache, expect in ((True, True), (False, False)):
        seen.clear()
        with pytest.raises(RuntimeError):
            llm.create("claude-haiku-5-5", "sys", [], cache=cache)
        assert ("cache_control" in seen) is expect
    assert seen.get("cache_control") is None
