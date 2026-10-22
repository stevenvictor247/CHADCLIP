"""Ledger: what Claude costs, per agent and per day. Every call through llm.py is recorded here."""

from datetime import datetime, timezone

from . import db
from .config import DAILY_BUDGET, FOOTBALL_AGENTS, FOOTBALL_DAILY_BUDGET, PRICES, UNKNOWN_PRICE


def cost_of(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> float:
    price_in, price_out = PRICES.get(model, UNKNOWN_PRICE)
    return (input_tokens * price_in + cache_read * price_in * 0.1 + cache_write * price_in * 1.25
            + output_tokens * price_out) / 1_000_000


def record(agent: str, model: str, usage) -> float:
    """Save one call's token use and return its cost in dollars. Never raises: a meter must not break an agent."""
    try:
        i, o = usage.input_tokens or 0, usage.output_tokens or 0
        r = getattr(usage, "cache_read_input_tokens", 0) or 0
        w = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cost = cost_of(model, i, o, r, w)
        db.init()
        db.execute("INSERT INTO llm_usage (agent, model, input_tokens, output_tokens, cache_read_tokens, "
                   "cache_write_tokens, cost_usd, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   agent, model, i, o, r, w, cost, db.now())
        return cost
    except Exception:
        return 0.0


def _since(start_iso: str, village: str | None = None) -> float:
    """Spending since a time. village "football" counts only the football agents, "business" everyone else."""
    sql, args = "SELECT COALESCE(SUM(cost_usd), 0) c FROM llm_usage WHERE created_at >= ?", [start_iso]
    if village:
        marks = ", ".join("?" for _ in FOOTBALL_AGENTS)
        sql += f" AND LOWER(agent) {'IN' if village == 'football' else 'NOT IN'} ({marks})"
        args += [a.lower() for a in FOOTBALL_AGENTS]
    return db.rows(sql, *args)[0]["c"]


def _start_of_today() -> str:
    return datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0) \
        .astimezone(timezone.utc).isoformat(timespec="seconds")


def spent_today(village: str | None = None) -> float:
    return _since(_start_of_today(), village)


def over_budget(village: str = "business") -> bool:
    """Each village has its own daily cap: hitting one never pauses the other."""
    cap = FOOTBALL_DAILY_BUDGET if village == "football" else DAILY_BUDGET
    return cap > 0 and spent_today(village) >= cap


def summary() -> dict:
    """Numbers for the dashboard and the Boss."""
    today = _start_of_today()
    month = datetime.now().astimezone().replace(day=1, hour=0, minute=0, second=0, microsecond=0) \
        .astimezone(timezone.utc).isoformat(timespec="seconds")
    by_agent = db.rows("SELECT agent, ROUND(SUM(cost_usd), 4) usd, COUNT(*) calls FROM llm_usage "
                       "WHERE created_at >= ? GROUP BY agent ORDER BY usd DESC", month)
    return {"today_usd": round(_since(today), 4), "month_usd": round(_since(month), 4),
            "daily_budget_usd": DAILY_BUDGET or None, "over_budget": over_budget(), "month_by_agent": by_agent,
            "football_today_usd": round(_since(today, "football"), 4),
            "football_budget_usd": FOOTBALL_DAILY_BUDGET or None, "football_over_budget": over_budget("football")}
