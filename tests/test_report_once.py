"""The daily report fires once per day even when it fails or the worker restarts."""

from datetime import datetime

from hq import boss, llm, worker


def test_failing_report_is_not_retried_every_tick(monkeypatch):
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("db locked")

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
