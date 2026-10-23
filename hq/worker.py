"""The background loop: runs queued tasks, agents' scheduled jobs, posting, and the Boss's daily report."""

import json
import os
import threading
import time
import traceback
from datetime import datetime, timedelta

from . import agents, boss, db, ledger, llm
from .agents.chad.publish import publish_approved
from .config import DATA_DIR, FOOTBALL_REMINDER_HOUR, REQUIRE_APPROVAL

STATE_PATH = DATA_DIR / "worker_state.json"
REPORT_HOUR = int(os.getenv("HQ_REPORT_HOUR", "9"))  # local time for the Boss's daily report


def _state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(s: dict):
    tmp = STATE_PATH.with_suffix(".tmp")  # write then swap, so a crash mid-write can't leave a broken file
    tmp.write_text(json.dumps(s))
    os.replace(tmp, STATE_PATH)


# Agents whose jobs take minutes (downloading, transcribing and cutting video) run in their own lane, so a long
# clipping job never holds up Pitch, Scout, Sweep, the football agents or posting.
SLOW_AGENTS = {"chad"}
HEARTBEAT = 60  # seconds: a running task's updated_at is refreshed this often, so Sweep can tell slow from stuck


def _claim(lane: str | None) -> dict | None:
    """Take the oldest queued task in this lane and mark it running in one step, so two lanes never take the same one."""
    marks = ", ".join("?" for _ in SLOW_AGENTS)
    where = {"slow": f" AND LOWER(agent) IN ({marks})", "quick": f" AND LOWER(agent) NOT IN ({marks})"}.get(lane, "")
    args = list(SLOW_AGENTS) if lane in ("slow", "quick") else []
    with db.connect() as c:
        for row in c.execute(f"SELECT * FROM tasks WHERE status = 'queued'{where} ORDER BY id LIMIT 5", args).fetchall():
            if c.execute("UPDATE tasks SET status = 'running', updated_at = ? WHERE id = ? AND status = 'queued'",
                         (db.now(), row["id"])).rowcount == 1:
                return dict(row)
    return None


def _heartbeat(task_id: int, done: threading.Event):
    while not done.wait(HEARTBEAT):
        try:
            db.execute("UPDATE tasks SET updated_at = ? WHERE id = ? AND status = 'running'", db.now(), task_id)
        except Exception:
            pass  # a missed beat only matters after an hour of them


def run_next_task(lane: str | None = None) -> bool:
    """Run one queued task. lane "slow" takes only video jobs, "quick" everything else, None either."""
    task = _claim(lane)
    if not task:
        return False
    agent = agents.get(task["agent"])
    db.log(task["agent"], f"Started task #{task['id']}: {task['instructions'][:120]}")
    done = threading.Event()
    threading.Thread(target=_heartbeat, args=(task["id"], done), daemon=True).start()
    try:
        result = agent.run(task) if agent else f"No agent called {task['agent']}"
        db.update_task(task["id"], "done", result)
        db.log(task["agent"], f"Finished task #{task['id']}: {result[:200]}")
    except Exception as e:
        traceback.print_exc()
        result = f"Task #{task['id']} failed: {e}"
        db.update_task(task["id"], "failed", str(e)[:1000])
        db.log(task["agent"], result)
    finally:
        done.set()
    if agent and agent.notify_when_done:
        from . import relay
        relay.notify(f"{agent.name}: {result}")
    return True


def recover_interrupted():
    """Tasks left on 'running' when HQ last closed were cut off halfway: queue them again (once)."""
    for t in db.rows("SELECT id, agent FROM tasks WHERE status = 'running'"):
        again = db.rows("SELECT 1 FROM activity WHERE message LIKE ? LIMIT 1", f"HQ restarted task #{t['id']}%")
        if again:
            db.update_task(t["id"], "failed", "Cut off twice when HQ closed, so I stopped. Ask the Boss to run it again.")
        else:
            db.update_task(t["id"], "queued")
            db.log("HQ", f"HQ restarted task #{t['id']} ({t['agent']}): it was cut off when HQ last closed")


def queue_scheduled(state: dict):
    now = time.time()
    for agent in agents.AGENTS.values():
        if ledger.over_budget(agent.village) and not agent.free:
            continue  # that village's Claude budget is spent: nothing new starts on its own there until tomorrow
        for every_hours, instructions, params in agent.schedule:
            key = f"sched:{agent.name}:{instructions}"
            if now - state.get(key, 0) >= every_hours * 3600:
                db.create_task(agent.name, instructions, params, created_by="Schedule")
                state[key] = now


def daily_report(state: dict):
    if not llm.HAS_LLM:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    if datetime.now().hour >= REPORT_HOUR and state.get("last_report") != today:
        state["last_report"] = today
        report = boss.report()
        db.log("Boss", "Daily report: " + report)
        from . import relay
        relay.notify("Daily report\n\n" + report)


def football_tick():
    """Warrior Village's own rounds: Ref checks new sheets in the football Inbox, Clock sends the morning reminder."""
    from .football import files, printing, season
    try:
        for name in files.scan():
            db.create_task("Ref", f"Check {name}", {"file": name}, created_by="Inbox")
        season.remind_if_due(FOOTBALL_REMINDER_HOUR)
        printing.run_if_due()
    except Exception as e:  # never let the football side stop the business side
        traceback.print_exc()
        db.log("HQ", f"Football rounds failed: {e}")


def daily_backup(state: dict):
    today = datetime.now().strftime("%Y-%m-%d")
    if state.get("last_backup") != today:
        from .backup import make_backup
        state["last_backup"] = today
        try:
            make_backup()
        except Exception as e:  # a failed backup shouldn't stop the agents
            db.log("HQ", f"Daily backup failed: {e}")


def tick():
    state = _state()
    queue_scheduled(state)
    football_tick()
    if not REQUIRE_APPROVAL:
        db.execute("UPDATE clips SET status = 'approved' WHERE status = 'pending_approval'")
    while run_next_task("quick"):
        pass
    publish_approved()
    daily_report(state)
    daily_backup(state)
    _save_state(state)


def slow_loop(interval: float = 15):
    """The video lane: Chad's clipping jobs, one at a time, beside the main loop."""
    while True:
        try:
            if run_next_task("slow"):
                continue
        except Exception:
            traceback.print_exc()
        time.sleep(interval)


def loop(interval: float = 15):
    db.init()
    recover_interrupted()
    threading.Thread(target=slow_loop, args=(interval,), daemon=True, name="video-lane").start()
    print("[worker] running. Ctrl+C to stop.")
    while True:
        try:
            tick()
        except Exception:
            traceback.print_exc()
        time.sleep(interval)


def start_in_background():
    threading.Thread(target=loop, daemon=True).start()
    from . import relay
    relay.start_in_background()  # does nothing until TELEGRAM_BOT_TOKEN and TELEGRAM_OWNER_ID are set
