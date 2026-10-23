"""The worker: a long clipping job runs in its own lane, tasks are never taken twice, and cut-off tasks come back."""

import threading
import time

import pytest

from hq import agents, db, worker
from hq.agents.base import Agent


class Fake(Agent):
    def __init__(self, name, gate=None):
        super().__init__(name=name, role="test")
        self.gate, self.ran = gate, []

    def run(self, task):
        self.ran.append(task["id"])
        if self.gate:
            self.gate.wait(5)
        return "ok"


@pytest.fixture
def fakes(monkeypatch):
    db.init()
    db.execute("UPDATE tasks SET status = 'done' WHERE status IN ('queued', 'running')")  # leftovers from other tests
    gate = threading.Event()
    chad, scout = Fake("Chad", gate), Fake("Scout")
    monkeypatch.setitem(agents.AGENTS, "chad", chad)
    monkeypatch.setitem(agents.AGENTS, "scout", scout)
    yield chad, scout, gate
    gate.set()


def _status(task_id):
    return db.rows("SELECT status FROM tasks WHERE id = ?", task_id)[0]["status"]


def test_quick_jobs_run_while_a_clipping_job_is_busy(fakes):
    chad, scout, gate = fakes
    slow = db.create_task("Chad", "clip a long video", created_by="test")
    quick = db.create_task("Scout", "rate a campaign", created_by="test")
    t = threading.Thread(target=worker.run_next_task, args=("slow",))
    t.start()
    for _ in range(50):
        if chad.ran:
            break
        time.sleep(0.05)
    assert _status(slow) == "running"
    assert worker.run_next_task("quick")           # Scout doesn't wait for Chad
    assert _status(quick) == "done" and scout.ran == [quick]
    assert not worker.run_next_task("quick")       # and the quick lane never takes Chad's job
    gate.set()
    t.join(5)
    assert _status(slow) == "done"


def test_a_task_is_only_taken_once(fakes):
    _, scout, _ = fakes
    tid = db.create_task("Scout", "once", created_by="test")
    assert worker._claim("quick")["id"] == tid
    assert worker._claim("quick") is None and worker._claim(None) is None


def test_long_jobs_keep_their_running_mark_fresh(fakes, monkeypatch):
    chad, _, gate = fakes
    monkeypatch.setattr(worker, "HEARTBEAT", 0.05)
    tid = db.create_task("Chad", "long", created_by="test")
    db.execute("UPDATE tasks SET updated_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", tid)
    t = threading.Thread(target=worker.run_next_task, args=("slow",))
    t.start()
    time.sleep(0.3)
    beat = db.rows("SELECT updated_at FROM tasks WHERE id = ?", tid)[0]["updated_at"]
    assert beat > "2026"                            # Sweep won't mistake it for a stuck task
    gate.set()
    t.join(5)


def test_tasks_cut_off_by_a_restart_run_again_once(fakes):
    tid = db.create_task("Scout", "cut off", created_by="test")
    db.update_task(tid, "running")
    worker.recover_interrupted()
    assert _status(tid) == "queued"
    db.update_task(tid, "running")
    worker.recover_interrupted()
    assert _status(tid) == "failed"                 # cut off twice: stop instead of looping


def test_database_uses_wal():
    db.init()
    assert db.rows("PRAGMA journal_mode")[0]["journal_mode"] == "wal"


def test_broken_state_file_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "STATE_PATH", tmp_path / "worker_state.json")
    (tmp_path / "worker_state.json").write_text("{half")
    assert worker._state() == {}
    worker._save_state({"a": 1})
    assert worker._state() == {"a": 1}
