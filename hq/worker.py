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
    return json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}


def _save_state(s: dict):
    STATE_PATH.write_text(json.dumps(s))


def run_next_task() -> bool:
    queued = db.rows("SELECT * FROM tasks WHERE status = 'queued' ORDER BY id LIMIT 1")
    if not queued:
        return False
    task = queued[0]
    agent = agents.get(task["agent"])
    db.update_task(task["id"], "running")
    db.log(task["agent"], f"Started task #{task['id']}: {task['instructions'][:120]}")
    try:
        result = agent.run(task) if agent else f"No agent called {task['agent']}"
        db.update_task(task["id"], "done", result)
        db.log(task["agent"], f"Finished task #{task['id']}: {result[:200]}")
    except Exception as e:
        traceback.print_exc()
        result = f"Task #{task['id']} failed: {e}"
        db.update_task(task["id"], "failed", str(e)[:1000])
        db.log(task["agent"], result)
    if agent and agent.notify_when_done:
        from . import relay
        relay.notify(f"{agent.name}: {result}")
    return True


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
    while run_next_task():
        pass
    publish_approved()
    daily_report(state)
    daily_backup(state)
    _save_state(state)


def loop(interval: float = 15):
    db.init()
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
