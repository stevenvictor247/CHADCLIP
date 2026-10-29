"""Per-agent daily Claude budgets: a heads-up at 80%, a stop at 100%, and a receipt for every task.

Set HQ_AGENT_BUDGETS to something like "Chad=2, Scout=0.5". An agent not listed has no cap of its own (the village
budgets in ledger.py still apply). The idea (soft alert at 80%, hard pause at 100%, a receipt per run) is ours, inspired by
paperclipai/paperclip (MIT) and Keesan12/martin-loop (Apache-2.0); no code was copied.

Hitting a cap pauses only that agent, for the rest of the day: its scheduled rounds stop being queued and any Claude call
it tries to make is refused before it is sent. Nothing is posted, sent or spent because of a pause.
"""

import os

from . import db, ledger, relay

ALERT_AT = 0.8


class BudgetPaused(RuntimeError):
    """Raised before a Claude call when the calling agent has used up its daily budget."""


def limits() -> dict[str, float]:
    """{agent name (lowercase): daily dollars} from HQ_AGENT_BUDGETS. Bad pieces are skipped, 0 means no cap."""
    out = {}
    for part in (os.getenv("HQ_AGENT_BUDGETS", "") or "").replace(";", ",").split(","):
        name, _, amount = part.partition("=")
        try:
            cap = float(amount.strip().lstrip("$"))
        except ValueError:
            continue
        if name.strip() and cap > 0:
            out[name.strip().lower()] = cap
    return out


def spent_today(agent: str) -> float:
    return db.rows("SELECT COALESCE(SUM(cost_usd), 0) c FROM llm_usage WHERE created_at >= ? AND LOWER(agent) = ?",
                   ledger._start_of_today(), agent.lower())[0]["c"]


def state(agent: str) -> dict:
    """{agent, cap, spent, pct, state}: state is none (no cap), ok, alert (80%+) or paused (100%+)."""
    cap = limits().get(agent.lower())
    spent = spent_today(agent)
    if not cap:
        return {"agent": agent, "cap": None, "spent": round(spent, 4), "pct": None, "state": "none"}
    pct = spent / cap
    return {"agent": agent, "cap": cap, "spent": round(spent, 4), "pct": round(100 * pct),
            "state": "paused" if pct >= 1 else "alert" if pct >= ALERT_AT else "ok"}


def is_paused(agent: str) -> bool:
    return agent.lower() in limits() and state(agent)["state"] == "paused"


def check(agent: str) -> None:
    """Call before a Claude call. Raises BudgetPaused when the agent's daily cap is used up."""
    if is_paused(agent):
        s = state(agent)
        raise BudgetPaused(f"{agent} used its ${s['cap']:g} daily budget (${s['spent']:.2f} spent). "
                           "It starts again tomorrow, or raise it in Settings.")


def alert(agent: str) -> str | None:
    """Tell Steven once a day when an agent passes 80% of its budget, and once more when it is paused."""
    s = state(agent)
    if s["state"] not in ("alert", "paused"):
        return None
    day = int(ledger._start_of_today()[:10].replace("-", ""))
    kind = f"budget-{s['state']}:{agent.lower()}"
    if db.rows("SELECT 1 FROM relay_sent WHERE kind = ? AND ref_id = ?", kind, day):
        return None
    db.execute("INSERT INTO relay_sent (kind, ref_id, created_at) VALUES (?, ?, ?)", kind, day, db.now())
    text = (f"{agent} has used {s['pct']}% of its ${s['cap']:g} daily budget (${s['spent']:.2f})."
            if s["state"] == "alert" else
            f"{agent} is paused for today: it used all of its ${s['cap']:g} daily budget. Nothing else is affected.")
    db.log("Budgets", text)
    relay.notify("💸 " + text)
    return text


def check_all() -> None:
    for name in limits():
        alert(name)


def receipt(task: dict, status: str, started_at: str, summary: str, paused: bool = False) -> int:
    """One line per finished task: who, how it ended, what Claude cost while it ran, and why it stopped.
    Cost is the agent's Claude spending between start and finish, so overlapping tasks of one agent share it."""
    cost = db.rows("SELECT COALESCE(SUM(cost_usd), 0) c FROM llm_usage WHERE LOWER(agent) = ? AND created_at >= ?",
                   task["agent"].lower(), started_at)[0]["c"]
    reason = "budget" if paused else "finished" if status == "done" else "error"
    return db.execute("INSERT INTO run_receipts (task_id, agent, status, stop_reason, cost_usd, summary, started_at, "
                      "finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", task["id"], task["agent"], status, reason,
                      round(cost, 4), (summary or "")[:300], started_at, db.now())


def snapshot() -> dict:
    caps = limits()
    return {"agents": [state(n) for n in caps],
            "receipts": db.rows("SELECT * FROM run_receipts ORDER BY id DESC LIMIT 20")}
