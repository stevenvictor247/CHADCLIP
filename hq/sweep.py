"""Sweep, HQ's janitor: finds what is wasting Claude money, tidies up after the other agents, and reports once a day.

Sweep never calls Claude itself, so it costs nothing to run. What it does on its own is limited to things that are
low risk, written to the activity log and either undoable or harmless:
  - a task stuck on "running" after a crash is put back in the queue once, then closed as failed
  - a task that failed on a network or overload error is retried once
  - old downloads, rejected clips, practice posts and big logs are moved to data/sweep/trash (restorable for a
    week), never deleted straight away
  - an idle Boss conversation that has grown huge is closed so the next chat starts small (old messages are kept)
Everything else (switching a model, posting, emailing, spending, settings and keys) is only ever reported, or asked
for through the Approvals queue.
"""

import json
import os
import re
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import approvals, db, ledger
from .config import CLIPS_DIR, DAILY_BUDGET, DATA_DIR, FOOTBALL_DAILY_BUDGET, PRICES, SOURCES_DIR

SWEEP_DIR = DATA_DIR / "sweep"
TRASH_DIR = SWEEP_DIR / "trash"
REPORTS_DIR = SWEEP_DIR / "reports"
STATE_PATH = SWEEP_DIR / "state.json"


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def report_hour() -> int:
    return _int("HQ_SWEEP_REPORT_HOUR", 8)          # local hour of the daily report


def stuck_hours() -> float:
    return float(os.getenv("HQ_SWEEP_STUCK_HOURS", "") or 1)


def keep_days() -> int:
    return _int("HQ_SWEEP_KEEP_DAYS", 7)            # how long old downloads stay before they go to the trash


TRASH_DAYS = 7                                       # how long trashed files can be restored
LOG_LIMIT = 5 * 1024 * 1024                          # logs bigger than this are cut down to their last megabyte
BOSS_CHAT_TOKENS = _int("HQ_SWEEP_BOSS_TOKENS", 120_000)   # estimated size at which an idle Boss chat is closed
LOOP_CALLS_PER_HOUR = _int("HQ_SWEEP_LOOP_CALLS", 30)
TRANSIENT = re.compile(r"timed? ?out|timeout|connection|overloaded|rate.?limit|429|\b50[0234]\b|temporarily|"
                       r"network|reset by peer|unavailable", re.I)
PROTECTED = {"boss", "pitch", "chad"}              # wording and judgement agents: never suggested for a cheaper model
STEP_DOWN = {"claude-opus-5-5": "claude-sonnet-5-5", "claude-opus-5": "claude-sonnet-5-5",
             "claude-sonnet-5-5": "claude-haiku-5-5", "claude-sonnet-5": "claude-haiku-5-5"}


# ---- small helpers ---------------------------------------------------------------------------------------

def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _ago(**kw) -> str:
    return _utc(datetime.now(timezone.utc) - timedelta(**kw))


def _local_midnight(days_back: int = 0) -> str:
    d = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_back)
    return _utc(d)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def _usd(x: float) -> str:
    return f"${x:,.2f}" if x >= 0.01 or x == 0 else f"${x:,.3f}"


def _log(message: str):
    db.log("Sweep", message)


# ---- the trash: nothing is deleted straight away ----------------------------------------------------------

def _trash_index() -> list[dict]:
    return _read_json(TRASH_DIR / "index.json", [])


def trash(path: Path, why: str, copy_only: bool = False) -> dict | None:
    """Move a file to the trash (or, for a log, copy it there first). Returns its trash record."""
    path = Path(path)
    if not path.is_file():
        return None
    index = _trash_index()
    tid = max([t["id"] for t in index], default=0) + 1
    dest = TRASH_DIR / f"{tid}-{path.name}"
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    size = path.stat().st_size
    (shutil.copy2 if copy_only else shutil.move)(str(path), str(dest))
    rec = {"id": tid, "name": path.name, "original": str(path), "stored": dest.name, "bytes": size, "why": why,
           "at": db.now(), "restored": False}
    index.append(rec)
    _write_json(TRASH_DIR / "index.json", index)
    return rec


def restore(trash_id: int) -> str:
    """Put a trashed file back where it came from."""
    index = _trash_index()
    rec = next((t for t in index if t["id"] == trash_id and not t.get("restored")), None)
    if not rec:
        raise ValueError(f"Nothing in the trash with id {trash_id}")
    src, dest = TRASH_DIR / rec["stored"], Path(rec["original"])
    if not src.exists():
        raise ValueError("That file is already gone")
    if dest.exists():
        raise ValueError(f"{dest.name} exists again, so I left the trashed copy alone")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    rec["restored"] = True
    _write_json(TRASH_DIR / "index.json", index)
    _log(f"Restored {rec['name']} from the trash")
    return f"Put {rec['name']} back."


def purge_trash() -> int:
    """Really delete what has sat in the trash for more than a week. Returns bytes freed."""
    index, freed, keep = _trash_index(), 0, []
    cutoff = _ago(days=TRASH_DAYS)
    for rec in index:
        stored = TRASH_DIR / rec["stored"]
        if rec.get("restored") or not stored.exists():
            continue
        if rec["at"] < cutoff:
            freed += stored.stat().st_size
            stored.unlink()
        else:
            keep.append(rec)
    if len(keep) != len(index):
        _write_json(TRASH_DIR / "index.json", keep)
    return freed


def trash_summary() -> list[dict]:
    return [t for t in _trash_index() if not t.get("restored") and (TRASH_DIR / t["stored"]).exists()]


# ---- the numbers -----------------------------------------------------------------------------------------

def _usage(since: str, until: str | None = None) -> list[dict]:
    sql = ("SELECT agent, model, COUNT(*) calls, SUM(input_tokens) inp, SUM(output_tokens) outp, "
           "SUM(cache_read_tokens) cread, SUM(cache_write_tokens) cwrite, SUM(cost_usd) usd FROM llm_usage "
           "WHERE created_at >= ?")
    args = [since]
    if until:
        sql += " AND created_at < ?"
        args.append(until)
    return db.rows(sql + " GROUP BY agent, model ORDER BY usd DESC", *args)


def _total(since: str, until: str | None = None) -> float:
    return sum(r["usd"] or 0 for r in _usage(since, until))


def spend_numbers() -> dict:
    today, yesterday = _local_midnight(), _local_midnight(1)
    week_start = _local_midnight(7)
    week = _total(week_start, today)
    month = datetime.now().astimezone().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_usd = _total(_utc(month))
    days_in = max(1, (datetime.now().astimezone().date() - month.date()).days + 1)
    return {"today": _total(today), "yesterday": _total(yesterday, today), "week_avg": week / 7,
            "month": month_usd, "month_projected": month_usd / days_in * 30,
            "budget": DAILY_BUDGET or None, "football_budget": FOOTBALL_DAILY_BUDGET or None,
            "business_today": ledger.spent_today("business"), "football_today": ledger.spent_today("football")}


def by_agent(since: str) -> list[dict]:
    out: dict[str, dict] = {}
    for r in _usage(since):
        a = out.setdefault(r["agent"], {"agent": r["agent"], "calls": 0, "usd": 0.0, "models": set()})
        a["calls"] += r["calls"]
        a["usd"] += r["usd"] or 0
        a["models"].add(r["model"])
    return sorted(({**a, "usd": round(a["usd"], 4), "models": sorted(a["models"])} for a in out.values()),
                  key=lambda a: -a["usd"])


# ---- what Sweep notices (reported, not fixed) -----------------------------------------------------------

def _finding(kind: str, severity: str, title: str, detail: str, **extra) -> dict:
    return {"kind": kind, "severity": severity, "title": title, "detail": detail, **extra}


def find_problems(spend: dict | None = None) -> list[dict]:
    """Things that waste money or look broken. Pure reading: nothing is changed."""
    spend = spend or spend_numbers()
    found: list[dict] = []
    day_ago, week_ago = _ago(hours=24), _ago(days=7)

    # budget
    for label, today, cap in (("The HQ", spend["business_today"], spend["budget"]),
                              ("Warrior Village", spend["football_today"], spend["football_budget"])):
        if cap and today >= cap:
            found.append(_finding("budget", "high", f"{label} hit its daily Claude budget",
                                  f"{_usd(today)} of {_usd(cap)} used. Scheduled work there is paused until tomorrow."))
        elif cap and today >= cap * 0.8:
            found.append(_finding("budget", "medium", f"{label} is near its daily Claude budget",
                                  f"{_usd(today)} of {_usd(cap)} used."))
    if spend["week_avg"] > 0 and spend["today"] > max(0.5, spend["week_avg"] * 2):
        found.append(_finding("spike", "medium", "Today is costing about double a normal day",
                              f"{_usd(spend['today'])} so far against a 7-day average of {_usd(spend['week_avg'])}."))

    # prompt caching not paying off where it should
    for r in _usage(day_ago):
        if r["agent"] == "Boss" and r["calls"] >= 5 and (r["inp"] or 0) / r["calls"] > 2000 and not r["cread"]:
            found.append(_finding("cache", "medium", "The Boss is not getting cached prompts",
                                  f"{r['calls']} Boss calls in 24 hours with about {(r['inp'] or 0) // r['calls']:,} "
                                  "input tokens each and none read from the cache. Every one was billed at full price."))

    # loops: one agent making a burst of calls in a single hour
    rows = db.rows("SELECT agent, substr(created_at, 1, 13) hour, COUNT(*) n, SUM(cost_usd) usd FROM llm_usage "
                   "WHERE created_at >= ? GROUP BY agent, hour HAVING n >= ? ORDER BY n DESC", day_ago, LOOP_CALLS_PER_HOUR)
    for r in rows[:3]:
        found.append(_finding("loop", "high", f"{r['agent']} made {r['n']} Claude calls in one hour",
                              f"That hour cost {_usd(r['usd'] or 0)}. It may be stuck in a loop (hour starting {r['hour']}:00 UTC)."))

    # the same job failing again and again
    fails = db.rows("SELECT agent, substr(instructions, 1, 80) what, COUNT(*) n FROM tasks WHERE status = 'failed' "
                    "AND updated_at >= ? AND created_by != 'Sweep' GROUP BY agent, what HAVING n >= 3", day_ago)
    for r in fails:
        found.append(_finding("failing", "medium", f"{r['agent']}'s job keeps failing ({r['n']} times today)",
                              f"\"{r['what']}\". Repeating it won't help until the cause is fixed."))

    # models the price table doesn't know are billed at a pessimistic guess
    for r in _usage(week_ago):
        if r["model"] not in PRICES:
            found.append(_finding("price", "low", f"No price on file for {r['model']}",
                                  "The Ledger guesses a high price for it, so the numbers may look worse than they are."))
            break

    # cheaper model for small jobs, asked for through Approvals
    found += _model_suggestions()

    # disk
    try:
        free = shutil.disk_usage(DATA_DIR).free
        if free < 5 * 1024 ** 3:
            found.append(_finding("disk", "high", "The computer is almost out of disk space",
                                  f"{free / 1024 ** 3:.1f} GB free. Source downloads and clips are the usual cause."))
    except OSError:
        pass
    return found


def _model_suggestions() -> list[dict]:
    out = []
    for r in _usage(_ago(days=7)):
        key = r["agent"].lower()
        smaller = STEP_DOWN.get(r["model"])
        if not smaller or key in PROTECTED or not r["calls"] or (r["usd"] or 0) < 0.25:
            continue
        if (r["inp"] or 0) / r["calls"] > 6000 or (r["outp"] or 0) / r["calls"] > 600:
            continue   # big prompts or long answers: this is real work, not a small job
        pin, pout = PRICES[r["model"]]
        sin, sout = PRICES[smaller]
        cheaper = (r["inp"] * sin + r["outp"] * sout) / 1e6
        costly = (r["inp"] * pin + r["outp"] * pout) / 1e6
        saving = max(0.0, costly - cheaper)
        if saving < 0.1:
            continue
        setting = f"HQ_MODEL_{r['agent'].upper()}"
        asked = db.rows("SELECT id, status, decided_at FROM approvals WHERE kind = 'sweep_model' AND payload LIKE ? "
                        "ORDER BY id DESC LIMIT 1", f'%"{setting}"%')
        if asked and (asked[0]["status"] == "pending" or (asked[0]["decided_at"] or "") > _ago(days=30)):
            continue   # already asked recently
        previous = os.getenv(setting, "")
        approvals.request("Sweep", "sweep_model", f"Switch {r['agent']} to a cheaper model?",
                          f"{r['agent']} makes small requests (about {(r['inp'] or 0) // r['calls']:,} tokens in, "
                          f"{(r['outp'] or 0) // r['calls']:,} out). On {smaller} the last 7 days would have cost "
                          f"about {_usd(saving)} less. If quality drops you can change it back in Settings.",
                          {"setting": setting, "to": smaller, "previous": previous}, yes="Switch", no="Keep it")
        out.append(_finding("model", "low", f"Asked: switch {r['agent']} to {smaller}?",
                            f"Would have saved about {_usd(saving)} last week. It is waiting in Approvals."))
    return out


def _apply_model(payload: dict, decision: str) -> str:
    if decision != "approve":
        return "Kept the current model."
    from . import settings
    settings.save({payload["setting"]: payload["to"]})
    _log(f"Switched {payload['setting']} to {payload['to']} (was {payload.get('previous') or 'the default'}) after Steven approved")
    return f"{payload['setting']} is now {payload['to']}. To go back, set it to {payload.get('previous') or 'nothing'} in Settings."


approvals.HANDLERS["sweep_model"] = _apply_model


# ---- what Sweep fixes by itself --------------------------------------------------------------------------

def fix_stuck_tasks() -> list[str]:
    """A task still 'running' while Sweep itself is running is a leftover from a crash: the worker does one at a time."""
    acts = []
    for t in db.rows("SELECT id, agent, instructions FROM tasks WHERE status = 'running' AND updated_at < ?",
                     _ago(hours=stuck_hours())):
        again = db.rows("SELECT 1 FROM activity WHERE message LIKE ? LIMIT 1", f"Sweep put task #{t['id']} back%")
        if again:
            db.update_task(t["id"], "failed", "Sweep: stuck twice, so I closed it. Ask the Boss to run it again if you still want it.")
            acts.append(f"Closed task #{t['id']} ({t['agent']}): it got stuck a second time")
        else:
            db.update_task(t["id"], "queued")
            acts.append(f"Put task #{t['id']} ({t['agent']}) back in the queue: it was stuck on running")
            _log(f"Sweep put task #{t['id']} back in the queue")
    for a in acts:
        _log(a)
    return acts


def fix_failed_tasks(limit: int = 3) -> list[str]:
    """Retry, once, jobs that failed on a network or overload hiccup. Skipped when the day's budget is spent."""
    from . import agents
    acts = []
    for t in db.rows("SELECT id, agent, instructions, params, result FROM tasks WHERE status = 'failed' AND updated_at >= ? "
                     "AND created_by != 'Sweep' ORDER BY id", _ago(hours=24)):
        if len(acts) >= limit:
            break
        agent = agents.get(t["agent"])
        if not agent or agent.free or ledger.over_budget(agent.village) or not TRANSIENT.search(t["result"] or ""):
            continue
        if db.rows("SELECT 1 FROM activity WHERE message LIKE ? LIMIT 1", f"Sweep retried task #{t['id']}%"):
            continue
        new = db.create_task(agent.name, t["instructions"], json.loads(t["params"] or "{}"), created_by="Sweep")
        msg = f"Sweep retried task #{t['id']} ({agent.name}) as #{new}: it failed on a temporary problem"
        _log(msg)
        acts.append(msg)
    return acts


def tidy_files() -> list[str]:
    acts: list[str] = []
    running = db.rows("SELECT 1 FROM tasks WHERE status = 'running' LIMIT 1")
    old = time.time() - keep_days() * 86400
    moved = []
    # downloaded source videos can be fetched again from their link; videos you handed Chad ("try-") cannot
    for p in ([] if running else sorted(SOURCES_DIR.glob("*"))):
        if p.is_file() and not p.name.startswith("try-") and p.stat().st_mtime < old:
            if trash(p, f"source download older than {keep_days()} days"):
                moved.append(p)
    if moved:
        acts.append(f"Moved {len(moved)} old source download(s) to the trash ({_size(_trash_bytes(moved))})")
    # clips you rejected, or that failed to post, and are not wanted any more
    gone = 0
    for c in db.rows("SELECT id, path FROM clips WHERE status IN ('rejected', 'failed') AND created_at < ?", _ago(days=14)):
        if c["path"] and CLIPS_DIR.resolve() in Path(c["path"]).resolve().parents and trash(Path(c["path"]), f"clip #{c['id']} was rejected"):
            gone += 1
    if gone:
        acts.append(f"Moved {gone} rejected clip file(s) to the trash")
    # practice posts saved by the practice account
    practice = DATA_DIR / "practice-posts"
    n = 0
    for p in (practice.rglob("*") if practice.exists() else []):
        if p.is_file() and p.stat().st_mtime < time.time() - 30 * 86400 and trash(p, "practice post older than 30 days"):
            n += 1
    if n:
        acts.append(f"Moved {n} old practice post file(s) to the trash")
    # logs that grew huge: keep a full copy in the trash, then cut the live one down to its last megabyte
    for p in DATA_DIR.glob("*.log"):
        if p.stat().st_size > LOG_LIMIT and trash(p, "log was over 5 MB", copy_only=True):
            tail = p.read_bytes()[-1024 * 1024:]
            p.write_bytes(tail)
            acts.append(f"Trimmed {p.name} to its last megabyte (full copy in the trash)")
    # old activity lines (the daily backup still holds them)
    cut = _ago(days=90)
    old_rows = db.rows("SELECT COUNT(*) n FROM activity WHERE created_at < ?", cut)[0]["n"]
    if old_rows:
        db.execute("DELETE FROM activity WHERE created_at < ?", cut)
        acts.append(f"Cleared {old_rows} activity lines older than 90 days")
    freed = purge_trash()
    if freed:
        acts.append(f"Emptied the trash of things older than {TRASH_DAYS} days ({_size(freed)})")
    for a in acts:
        _log(a)
    return acts


def _trash_bytes(paths) -> int:
    ids = {p.name for p in paths}
    return sum(t["bytes"] for t in _trash_index() if t["name"] in ids and not t.get("restored"))


def _size(n: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def fix_boss_chat() -> list[str]:
    """Every Boss message re-sends the whole conversation. Close one that is huge and has been quiet for hours."""
    from . import boss
    conv = boss.current_conversation()
    r = db.rows("SELECT COALESCE(SUM(LENGTH(content)), 0) chars, MAX(created_at) last FROM boss_messages "
                "WHERE conversation = ? AND role != 'marker'", conv)[0]
    tokens = r["chars"] // 4
    if tokens < BOSS_CHAT_TOKENS or not r["last"] or r["last"] > _ago(hours=3):
        return []
    boss.new_conversation()
    msg = (f"Started a fresh Boss conversation: the old one was about {tokens // 1000}k tokens and was re-sent on "
           "every message. It is still saved, and your vision file carries over")
    _log(msg)
    return [msg]


# ---- the run, the report ---------------------------------------------------------------------------------

def _state() -> dict:
    return _read_json(STATE_PATH, {})


def build_report(spend: dict, problems: list[dict], actions: list[str]) -> dict:
    day = datetime.now().strftime("%Y-%m-%d")
    agents24 = by_agent(_ago(hours=24))
    lines = [f"Sweep's daily report for {day}", ""]
    cap = f" of {_usd(spend['budget'])} budget" if spend["budget"] else ""
    lines.append(f"Claude cost: {_usd(spend['yesterday'])} yesterday, {_usd(spend['today'])} so far today{cap}. "
                 f"7-day average {_usd(spend['week_avg'])}/day. This month {_usd(spend['month'])} "
                 f"(on pace for about {_usd(spend['month_projected'])}).")
    if agents24:
        lines.append("Last 24 hours by agent: " + ", ".join(f"{a['agent']} {_usd(a['usd'])}" for a in agents24[:5]) + ".")
    lines.append("")
    lines.append("What I tidied up on my own:" if actions else "I had nothing to tidy up today.")
    lines += [f"- {a}" for a in actions]
    if problems:
        lines += ["", "Needs a look:"] + [f"- {p['title']}. {p['detail']}" for p in problems]
    else:
        lines += ["", "Nothing is wasting money right now."]
    trash_n = len(trash_summary())
    if trash_n:
        lines.append(f"\n{trash_n} file(s) are in the trash for {TRASH_DAYS} days. You can put any back from the Sweep card.")
    return {"day": day, "created_at": db.now(), "spend": spend, "by_agent": agents24, "actions": actions,
            "problems": problems, "text": "\n".join(lines)}


def run(force_report: bool = False) -> str:
    """One round: fix what is safe to fix, look for waste, and send the report if it is due. Returns a summary."""
    spend = spend_numbers()
    actions = fix_stuck_tasks() + fix_failed_tasks() + tidy_files() + fix_boss_chat()
    problems = find_problems(spend)
    state = _state()
    today = datetime.now().strftime("%Y-%m-%d")
    due = force_report or (datetime.now().hour >= report_hour() and state.get("last_report") != today)
    # the report and the dashboard list what Sweep did in the last 24 hours
    cutoff = _ago(hours=24)
    state["recent"] = [r for r in state.get("recent", []) if r["at"] >= cutoff] + [{"at": db.now(), "what": a} for a in actions]
    report = build_report(spend, problems, [r["what"] for r in state["recent"]])
    _write_json(REPORTS_DIR / "latest.json", report)    # the dashboard always shows the newest round
    if due:
        state["last_report"] = today
        _write_json(REPORTS_DIR / f"{today}.json", report)
        for old in sorted(REPORTS_DIR.glob("2*.json"))[:-30]:
            old.unlink()
        _log("Daily report sent: " + report["text"].split("\n")[2])
        from . import relay
        relay.notify(report["text"])
    _write_json(STATE_PATH, state)
    n = len(actions)
    return (f"{'Sent the daily report. ' if due else ''}Tidied up {n} thing(s), {len(problems)} thing(s) need a look."
            if n or problems or due else "All clean.")


def latest() -> dict:
    """For the dashboard: the newest report, what is in the trash, and how much mess is open."""
    rep = _read_json(REPORTS_DIR / "latest.json", {})
    return {"report": rep or None, "trash": trash_summary(), "mess": len(rep.get("problems", [])) if rep else 0,
            "hour": report_hour()}
