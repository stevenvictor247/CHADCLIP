"""Thursday print. No real printer: _send is replaced, and every file here is made up."""

import os
import shutil
import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from hq import db, relay, worker
from hq.agents.football.clock import Clock
from hq.football import printing

# 2026-10-22 is a Thursday
THU_8PM = datetime(2026, 10, 22, 20, 0)


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    db.init()
    db.execute("DELETE FROM tasks")
    shutil.rmtree(printing.FOOTBALL_PRINT_DIR, ignore_errors=True)
    printing.FOOTBALL_PRINT_DIR.mkdir(parents=True)
    printing.STATE_PATH.unlink(missing_ok=True)
    sent, printed = [], []
    monkeypatch.setattr(relay, "notify", sent.append)
    monkeypatch.setattr(printing, "_send", lambda path: printed.append(path.name))
    return {"sent": sent, "printed": printed}


def put(name, text="x", age=3600):
    p = printing.FOOTBALL_PRINT_DIR / name
    p.write_text(text)
    t = time.time() - age
    os.utime(p, (t, t))
    return p


def test_slots_are_thursday_8pm():
    assert printing.last_slot(datetime(2026, 10, 23, 9, 0)) == THU_8PM
    assert printing.last_slot(THU_8PM) == THU_8PM
    assert printing.last_slot(datetime(2026, 10, 22, 19, 59)) == THU_8PM - timedelta(days=7)
    assert printing.next_slot(datetime(2026, 10, 23, 9, 0)) == THU_8PM + timedelta(days=7)
    assert printing.next_slot(datetime(2026, 10, 22, 12, 0)) == THU_8PM


def test_first_look_never_prints_then_prints_once_at_the_slot(_setup):
    put("plan.pdf")
    assert printing.run_if_due(THU_8PM + timedelta(minutes=5)) is None   # first look: just remembers this slot
    assert _setup["printed"] == []
    nxt = THU_8PM + timedelta(days=7)
    assert "Printed 1 file" in printing.run_if_due(nxt + timedelta(minutes=1))
    assert _setup["printed"] == ["plan.pdf"]
    assert printing.run_if_due(nxt + timedelta(minutes=2)) is None
    assert not (printing.FOOTBALL_PRINT_DIR / "plan.pdf").exists()
    assert list((printing.FOOTBALL_PRINT_DIR / "Printed").rglob("plan.pdf"))
    assert any("Printed 1 file" in m for m in _setup["sent"])


def test_empty_folder_prints_nothing_and_stays_quiet(_setup):
    printing.run_if_due(THU_8PM)
    assert printing.run_if_due(THU_8PM + timedelta(days=7)) == "Nothing to print."
    assert _setup["printed"] == [] and _setup["sent"] == []


def test_paused_does_not_print_and_resume_prints_within_window(_setup):
    printing.run_if_due(THU_8PM)
    put("a.docx")
    printing.set_paused(True)
    nxt = THU_8PM + timedelta(days=7)
    assert printing.run_if_due(nxt + timedelta(minutes=1)) is None
    assert _setup["printed"] == []
    printing.set_paused(False)
    assert "Printed 1 file" in printing.run_if_due(nxt + timedelta(hours=1))


def test_missed_run_texts_instead_of_printing_late(_setup):
    printing.run_if_due(THU_8PM)
    put("a.pdf")
    msg = printing.run_if_due(THU_8PM + timedelta(days=7, hours=9))
    assert "didn't run" in msg and "8 PM" in msg
    assert _setup["printed"] == [] and (printing.FOOTBALL_PRINT_DIR / "a.pdf").exists()


def test_problem_files_are_skipped_with_a_reason(_setup):
    put("sheet.gsheet")
    put("fresh.pdf", age=5)
    put("~$lock.docx")
    put("ok.pdf")
    by = {f["name"]: f["problem"] for f in printing.waiting()}
    assert set(by) == {"sheet.gsheet", "fresh.pdf", "ok.pdf"}
    assert "PDF" in by["sheet.gsheet"] and "syncing" in by["fresh.pdf"] and by["ok.pdf"] is None
    printing.print_now()
    assert _setup["printed"] == ["ok.pdf"]
    assert (printing.FOOTBALL_PRINT_DIR / "fresh.pdf").exists()


def test_failed_print_stays_in_the_folder(monkeypatch):
    put("bad.pdf")

    def boom(path):
        raise RuntimeError("printer offline")
    monkeypatch.setattr(printing, "_send", boom)
    out = printing.print_now()
    assert "printer offline" in out and "still in the folder" in out
    assert (printing.FOOTBALL_PRINT_DIR / "bad.pdf").exists()


def test_same_name_twice_in_one_day_is_kept(_setup):
    put("a.pdf", "one")
    printing.print_now()
    put("a.pdf", "two")
    printing.print_now()
    assert len(list((printing.FOOTBALL_PRINT_DIR / "Printed").rglob("a*.pdf"))) == 2


def test_unmovable_file_is_never_printed_twice(monkeypatch, _setup):
    put("a.pdf")
    monkeypatch.setattr(printing, "_archive", lambda p: (_ for _ in ()).throw(OSError("locked")))
    printing.print_now()
    printing.print_now()
    assert _setup["printed"] == ["a.pdf"]


def test_clock_agent_runs_print_and_pause(_setup):
    put("a.pdf")
    clock = Clock()
    assert "Printed 1 file" in clock.run({"params": '{"print": true}'})
    assert "paused" in clock.run({"params": '{"pause": true}'})
    assert printing.is_paused()
    assert "resumed" in clock.run({"params": '{"resume": true}'})


def test_api_state_print_and_pause(_setup):
    import importlib
    import hq.api, hq.config, hq.db
    for m in (hq.config, hq.db, hq.api):
        importlib.reload(m)
    c = TestClient(hq.api.app)
    h = {"X-HQ": "1"}
    assert c.post("/api/football/print/now").status_code in (401, 403)
    r = c.post("/api/football/print/now", headers=h)
    assert r.status_code == 200 and r.json()["task_id"]
    r = c.post("/api/football/print/pause", json={"paused": True}, headers=h)
    assert r.json()["print"]["paused"] is True
    assert "next" in c.post("/api/football/print/pause", json={"paused": False}, headers=h).json()["print"]


def test_worker_tick_calls_the_scheduled_print(monkeypatch):
    calls = []
    monkeypatch.setattr(printing, "run_if_due", lambda *a: calls.append(1))
    worker.football_tick()
    assert calls == [1]
