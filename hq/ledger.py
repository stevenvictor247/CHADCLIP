"""Ledger: what Claude costs, per agent and per day. Every call through llm.py is recorded here."""

from datetime import datetime, timezone

from . import db
from .config import (DAILY_BUDGET, ETSY_AGENTS, ETSY_DAILY_BUDGET, ETSY_MONTHLY_BUDGET, FOOTBALL_AGENTS,
                     FOOTBALL_DAILY_BUDGET, PRICES, UNKNOWN_PRICE)


WEB_SEARCH_FEE = 0.01  # dollars per web search the API runs for us ($10 per 1,000)


def cost_of(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> float:
    price_in, price_out = PRICES.get(model, UNKNOWN_PRICE)
    return (input_tokens * price_in + cache_read * price_in * 0.1 + cache_write * price_in * 1.25
            + output_tokens * price_out) / 1_000_000


def record(agent: str, model: str, usage, rate: float = 1.0) -> float:
    """Save one call's token use and return its cost in dollars. Never raises: a meter must not break an agent.
    `rate` is the share of the list price paid: 0.5 for Claude's half-price batch queue."""
    try:
        i, o = usage.input_tokens or 0, usage.output_tokens or 0
        r = getattr(usage, "cache_read_input_tokens", 0) or 0
        w = getattr(usage, "cache_creation_input_tokens", 0) or 0
        searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0)
        cost = cost_of(model, i, o, r, w) * rate + (searches if isinstance(searches, int) else 0) * WEB_SEARCH_FEE
        db.init()
        db.execute("INSERT INTO llm_usage (agent, model, input_tokens, output_tokens, cache_read_tokens, "
                   "cache_write_tokens, cost_usd, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   agent, model, i, o, r, w, cost, db.now())
        return cost
    except Exception:
        return 0.0


def record_cost(agent: str, what: str, usd: float) -> float:
    """A cost that isn't a Claude call (an Etsy design image), so it counts against the same budgets. Never raises."""
    try:
        db.init()
        db.execute("INSERT INTO llm_usage (agent, model, cost_usd, created_at) VALUES (?, ?, ?, ?)",
                   agent, what, float(usd), db.now())
        return float(usd)
    except Exception:
        return 0.0


VILLAGE_AGENTS = {"football": FOOTBALL_AGENTS, "etsy": ETSY_AGENTS}


def _since(start_iso: str, village: str | None = None) -> float:
    """Spending since a time. village "football" or "etsy" counts only that village's agents, "business" everyone else."""
    sql, args = "SELECT COALESCE(SUM(cost_usd), 0) c FROM llm_usage WHERE created_at >= ?", [start_iso]
    if village in VILLAGE_AGENTS:
        names = VILLAGE_AGENTS[village]
        sql += f" AND LOWER(agent) IN ({', '.join('?' for _ in names)})"
        args += [a.lower() for a in names]
    elif village:
        names = [a for v in VILLAGE_AGENTS.values() for a in v]
        sql += f" AND LOWER(agent) NOT IN ({', '.join('?' for _ in names)})"
        args += [a.lower() for a in names]
    return db.rows(sql, *args)[0]["c"]


def _start_of_today() -> str:
    return datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0) \
        .astimezone(timezone.utc).isoformat(timespec="seconds")


def _start_of_month() -> str:
    return datetime.now().astimezone().replace(day=1, hour=0, minute=0, second=0, microsecond=0) \
        .astimezone(timezone.utc).isoformat(timespec="seconds")


def spent_today(village: str | None = None) -> float:
    return _since(_start_of_today(), village)


def spent_this_month(village: str | None = None) -> float:
    return _since(_start_of_month(), village)


def over_budget(village: str = "business") -> bool:
    """Each village has its own daily cap: hitting one never pauses another. The Etsy village also has a monthly cap."""
    if village == "etsy":
        return (ETSY_DAILY_BUDGET > 0 and spent_today("etsy") >= ETSY_DAILY_BUDGET) or \
               (ETSY_MONTHLY_BUDGET > 0 and spent_this_month("etsy") >= ETSY_MONTHLY_BUDGET)
    cap = FOOTBALL_DAILY_BUDGET if village == "football" else DAILY_BUDGET
    return cap > 0 and spent_today(village) >= cap


def summary() -> dict:
    """Numbers for the dashboard and the Boss."""
    today = _start_of_today()
    month = _start_of_month()
    by_agent = db.rows("SELECT agent, ROUND(SUM(cost_usd), 4) usd, COUNT(*) calls FROM llm_usage "
                       "WHERE created_at >= ? GROUP BY agent ORDER BY usd DESC", month)
    return {"today_usd": round(_since(today), 4), "month_usd": round(_since(month), 4),
            "daily_budget_usd": DAILY_BUDGET or None, "over_budget": over_budget(), "month_by_agent": by_agent,
            "football_today_usd": round(_since(today, "football"), 4),
            "football_budget_usd": FOOTBALL_DAILY_BUDGET or None, "football_over_budget": over_budget("football"),
            "etsy_today_usd": round(_since(today, "etsy"), 4), "etsy_month_usd": round(_since(month, "etsy"), 4),
            "etsy_budget_usd": ETSY_DAILY_BUDGET or None, "etsy_month_budget_usd": ETSY_MONTHLY_BUDGET or None,
            "etsy_over_budget": over_budget("etsy")}
