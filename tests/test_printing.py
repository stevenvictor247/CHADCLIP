"""Thursday print. No real printer: _send is replaced, and every file here is made up."""

import os
import shutil
import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from hq import db, relay, worker
from hq.agents.football.clock import Clock
from hq.football import printing, season, tagrules, tagsheet

# 2026-10-22 is a Thursday
THU_8PM = datetime(2026, 10, 22, 20, 0)


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    db.init()
    db.execute("DELETE FROM tasks")
    shutil.rmtree(printing.FOOTBALL_PRINT_DIR, ignore_errors=True)
    (printing.FOOTBALL_PRINT_DIR / "Northern Michigan").mkdir(parents=True)
    printing.STATE_PATH.unlink(missing_ok=True)
    tagsheet.clear()
    monkeypatch.setattr(season, "current_game", lambda today=None: {"opponent": "Northern Michigan"})
    sent, printed = [], []
    monkeypatch.setattr(relay, "notify", sent.append)
    monkeypatch.setattr(printing, "_send", lambda path: printed.append(path.name))
    return {"sent": sent, "printed": printed}


WEEK = printing.FOOTBALL_PRINT_DIR / "Northern Michigan"


def put(name, text="x", age=3600, folder=None):
    p = (folder or WEEK) / name
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
    assert (WEEK / "plan.pdf").exists()           # files stay where they are
    assert printing.waiting() == []               # and never print twice
    assert any("Printed 1 file" in m for m in _setup["sent"])


def test_empty_folder_prints_nothing_and_stays_quiet(_setup):
    printing.run_if_due(THU_8PM)
    assert "nothing in the Northern Michigan folder" in printing.run_if_due(THU_8PM + timedelta(days=7))
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
    assert _setup["printed"] == [] and (WEEK / "a.pdf").exists()


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
    assert (WEEK / "fresh.pdf").exists() and {f["name"] for f in printing.waiting()} == {"fresh.pdf", "sheet.gsheet"}


def test_failed_print_stays_in_the_folder(monkeypatch):
    put("bad.pdf")

    def boom(path):
        raise RuntimeError("printer offline")
    monkeypatch.setattr(printing, "_send", boom)
    out = printing.print_now()
    assert "printer offline" in out and "still in the folder" in out
    assert (WEEK / "bad.pdf").exists() and [f["name"] for f in printing.waiting()] == ["bad.pdf"]


def test_a_changed_file_prints_again_once(_setup):
    put("a.pdf", "one", age=3600)
    printing.print_now()
    printing.print_now()
    assert _setup["printed"] == ["a.pdf"]
    put("a.pdf", "two", age=1800)
    printing.print_now()
    assert _setup["printed"] == ["a.pdf", "a.pdf"]


def test_only_this_weeks_opponent_folder_prints(_setup):
    other = printing.FOOTBALL_PRINT_DIR / "Ferris State"
    other.mkdir()
    put("ferris.pdf", folder=other)
    (printing.FOOTBALL_PRINT_DIR / "loose.pdf").write_text("x")
    put("nmu.pdf")
    printing.print_now()
    assert _setup["printed"] == ["nmu.pdf"]


def test_a_folder_with_a_nickname_still_counts(_setup):
    shutil.rmtree(WEEK)
    nick = printing.FOOTBALL_PRINT_DIR / "NMU"
    nick.mkdir()
    put("a.pdf", folder=nick)
    assert printing.folder_for("Northern Michigan") == nick
    printing.print_now()
    assert _setup["printed"] == ["a.pdf"]


def test_missing_opponent_folder_says_so(_setup):
    shutil.rmtree(WEEK)
    assert "no Northern Michigan folder" in printing.print_now().replace("There's ", "no ").replace("There", "no")
    printing.run_if_due(THU_8PM)
    assert "no folder for Northern Michigan" in printing.run_if_due(THU_8PM + timedelta(days=7))
    assert any("no folder" in m for m in _setup["sent"])


def test_folders_are_made_for_every_opponent_once():
    made = printing.ensure_folders()
    assert "Northern Michigan" not in made and {"Ferris State", "Michigan Tech", "Davenport"} <= set(made)
    assert printing.ensure_folders() == []
    assert (printing.FOOTBALL_PRINT_DIR / "Ferris State").is_dir()


def test_deliver_copies_into_the_opponent_folder_without_overwriting(tmp_path):
    src = tmp_path / "Northern Michigan scouting report.docx"
    src.write_text("report")
    first = printing.deliver(src, "Northern Michigan")
    second = printing.deliver(src, "Northern Michigan")
    assert first.parent == WEEK and second.name.endswith("(2).docx") and first.read_text() == "report"
    assert printing.deliver(src, "Opponent") is None and printing.deliver(src, None) is None


def test_approved_scouting_report_lands_in_the_opponent_folder(tmp_path):
    from hq.agents.football import tells
    draft = tmp_path / "draft.docx"
    draft.write_text("r")
    msg = tells._decide({"draft": str(draft), "name": "NMU report test.docx", "opponent": "Northern Michigan"}, "approve")
    assert "Northern Michigan folder" in msg and (WEEK / "NMU report test.docx").exists()
    (WEEK / "NMU report test.docx").unlink()


def test_tag_sheet_is_saved_read_and_used_by_ref():
    import io, openpyxl
    wb = openpyxl.Workbook()
    wb.active.append(["TAG", "MEANING"])
    wb.active.append(["BASH", "Our name for a bunch look"])
    buf = io.BytesIO()
    wb.save(buf)
    row = {"row": 3, "play": 1, "personnel": "11", "form": "BASH", "tag": "", "backfield": "GUN STRONG"}
    before = [f["message"] for f in tagrules.check_row(row, set())]
    info = tagsheet.save("my tags.xlsx", buf.getvalue())
    assert info["loaded"] and "BASH" in tagsheet.words() and "Our name for a bunch look" in tagsheet.text()
    after = [f["message"] for f in tagrules.check_row(row, set())]
    assert any("BASH" in m for m in before) and not any("BASH" in m or "No base formation" in m for m in after)
    with pytest.raises(ValueError):
        tagsheet.save("tags.exe", b"x")


def test_clock_agent_runs_print_and_pause(_setup):
    put("a.pdf")
    clock = Clock()
    assert "Printed 1 file" in clock.run({"params": '{"print": true}'})
    assert "paused" in clock.run({"params": '{"pause": true}'})
    assert printing.is_paused()
    assert "resumed" in clock.run({"params": '{"resume": true}'})


def test_api_tag_sheet_and_folders(_setup):
    import importlib
    import hq.api, hq.config, hq.db
    for m in (hq.config, hq.db, hq.api):
        importlib.reload(m)
    c = TestClient(hq.api.app)
    h = {"X-HQ": "1"}
    assert c.post("/api/football/tagsheet", files={"file": ("tags.csv", b"TAG,MEANING\nBASH,bunch")}).status_code in (401, 403)
    r = c.post("/api/football/tagsheet", files={"file": ("tags.csv", b"TAG,MEANING\nBASH,bunch look")}, headers=h)
    assert r.status_code == 200 and r.json()["tagsheet"]["loaded"]
    assert c.post("/api/football/tagsheet", files={"file": ("tags.exe", b"xx")}, headers=h).status_code == 400
    assert c.post("/api/football/print/folders", headers=h).status_code == 200


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
    monkeypatch.setattr(season, "remind_if_due", lambda *a: False)   # needs a real game date, and only runs after 8 am
    worker.football_tick()
    assert calls == [1]


def test_an_outbox_pdf_prints_straight_from_the_outbox(monkeypatch):
    from hq.config import FOOTBALL_OUTBOX
    sent = []
    monkeypatch.setattr(printing, "_send", lambda p: sent.append(p.name))
    FOOTBALL_OUTBOX.mkdir(parents=True, exist_ok=True)
    (FOOTBALL_OUTBOX / "Report.pdf").write_bytes(b"%PDF-1.4")
    (FOOTBALL_OUTBOX / "Notes.zip").write_bytes(b"x")
    assert printing.print_outbox_file("Report.pdf").startswith("Sent Report.pdf")
    assert sent == ["Report.pdf"]
    assert "can't be printed" in printing.print_outbox_file("Notes.zip")
    assert "no Missing.pdf" in printing.print_outbox_file("Missing.pdf")
    assert "../x" not in printing.print_outbox_file("../x.pdf")   # only ever the Outbox
    assert sent == ["Report.pdf"]


def test_an_every_week_sheet_prints_once_per_game_week_with_or_without_an_opponent_folder(_setup, monkeypatch):
    shutil.rmtree(printing.EXTRAS_DIR, ignore_errors=True)
    name = printing.save_extra("Press Box Chart.pdf", b"%PDF-1.4")
    p = printing.EXTRAS_DIR / name
    t = time.time() - 3600
    os.utime(p, (t, t))
    shutil.rmtree(WEEK)   # no opponent folder this week: the chart still prints
    printing.print_now()
    printing.print_now()
    assert _setup["printed"] == ["Press Box Chart.pdf"]
    monkeypatch.setattr(season, "current_game", lambda today=None: {"opponent": "Ferris State"})
    printing.print_now()   # a new game week: it prints again
    assert _setup["printed"] == ["Press Box Chart.pdf", "Press Box Chart.pdf"]
    assert printing.state()["extras"] == ["Press Box Chart.pdf"]
    assert printing.remove_extra(name) and not printing.extras()
    with pytest.raises(ValueError):
        printing.save_extra("notes.zip", b"x")


def test_api_adds_and_removes_an_every_week_sheet(_setup):
    import importlib
    import hq.api, hq.config, hq.db
    for m in (hq.config, hq.db, hq.api):
        importlib.reload(m)
    shutil.rmtree(printing.EXTRAS_DIR, ignore_errors=True)
    c = TestClient(hq.api.app)
    r = c.post("/api/football/print/extras", files={"file": ("Chart.pdf", b"%PDF-1.4")}, headers={"X-HQ": "1"})
    assert r.status_code == 200 and r.json()["print"]["extras"] == ["Chart.pdf"]
    assert c.post("/api/football/print/extras", files={"file": ("Chart.zip", b"x")}, headers={"X-HQ": "1"}).status_code == 400
    r = c.post("/api/football/print/extras/Chart.pdf/remove", headers={"X-HQ": "1"})
    assert r.status_code == 200 and r.json()["print"]["extras"] == []
