"""The daily report fires once per day even when it fails or the worker restarts."""

from datetime import datetime

from hq import boss, llm, worker


def test_failing_report_is_not_retried_every_tick(monkeypatch):
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("db locked")

    from hq import db
    db.init()
    db.execute("DELETE FROM boss_messages")
    saved = []
    monkeypatch.setattr(llm, "HAS_LLM", True)
    monkeypatch.setattr(worker, "REPORT_HOUR", 0)
    monkeypatch.setattr(worker, "_save_state", lambda s: saved.append(dict(s)))
    monkeypatch.setattr(boss, "report", boom)
    state = {}
    for _ in range(5):          # five worker ticks
        worker.daily_report(state)
    assert len(calls) == 1
    assert saved and saved[0]["last_report"] == datetime.now().strftime("%Y-%m-%d")


def test_report_skipped_if_one_ran_recently(monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "HAS_LLM", True)
    monkeypatch.setattr(worker, "REPORT_HOUR", 0)
    monkeypatch.setattr(worker, "_save_state", lambda s: None)
    monkeypatch.setattr(boss, "report", lambda: calls.append(1) or "ok")
    import time
    worker.daily_report({"last_report": "2000-01-01", "last_report_at": time.time() - 3600})
    assert calls == []


def test_sweep_report_claimed_once_a_day(tmp_path, monkeypatch):
    from hq import sweep
    monkeypatch.setattr(sweep, "SENT_PATH", tmp_path / "sent.txt")
    monkeypatch.setattr(sweep, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(sweep, "_state", lambda: {})      # even a lost state file can't resend
    monkeypatch.setattr(sweep, "report_hour", lambda: 0)
    assert sweep.report_due()
    assert sweep._claim_report_day("2026-10-24") is True
    assert sweep._claim_report_day("2026-10-24") is False
    assert not sweep.report_due() or datetime.now().strftime("%Y-%m-%d") != "2026-10-24"


def test_scheduled_rounds_back_off_and_do_not_stack(monkeypatch):
    from hq import db, worker
    db.init()
    for _ in range(6):
        t = db.create_task("Scout", "Find things.", {}, created_by="Schedule")
        db.update_task(t, "done", "Nothing new.")
    assert worker.backoff("Scout", "Find things.") == 3
    t = db.create_task("Scout", "Find things.", {}, created_by="Schedule")
    db.update_task(t, "done", "Found 2 campaigns.")
    assert worker.backoff("Scout", "Find things.") == 1
