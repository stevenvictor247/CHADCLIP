"""Money: what HQ has cost and what it has made, for the strip at the top of the dashboard.

Spent = Claude calls (from the Ledger) + expenses Steven logs (subscriptions, tools...).
Made = campaign earnings recorded on submissions + income Steven logs (Whop, Etsy and other payouts paid outside HQ).
HQ can't see bank accounts, so income is only what is logged here or recorded on a campaign.
"""

from datetime import date, datetime, timezone

from . import db

KINDS = ("expense", "income")


def _utc(local: datetime) -> str:
    return local.astimezone(timezone.utc).isoformat(timespec="seconds")


def _bounds() -> dict[str, tuple[str, str]]:
    """(local day it starts, UTC timestamp it starts) for each period. Manual entries carry a day, the rest a timestamp."""
    now = datetime.now().astimezone()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = today.replace(day=1)
    return {"today": (today.date().isoformat(), _utc(today)),
            "month": (month.date().isoformat(), _utc(month)),
            "all": ("", "")}


def _logged(kind: str, day_from: str) -> float:
    return db.rows("SELECT COALESCE(SUM(amount_usd), 0) s FROM money_entries WHERE kind = ? AND day >= ?", kind, day_from)[0]["s"]


def _claude(ts_from: str) -> float:
    return db.rows("SELECT COALESCE(SUM(cost_usd), 0) s FROM llm_usage WHERE created_at >= ?", ts_from)[0]["s"]


def _campaigns(ts_from: str) -> float:
    # Earnings count from when they were recorded; a submission marked unpaid made nothing.
    return db.rows("SELECT COALESCE(SUM(earned_usd), 0) s FROM submissions WHERE status != 'unpaid' AND updated_at >= ?",
                   ts_from)[0]["s"]


def add(kind: str, amount_usd: float, note: str = "", day: str | None = None) -> int:
    if kind not in KINDS:
        raise ValueError("kind must be expense or income")
    try:
        amount = round(float(amount_usd), 2)
    except (TypeError, ValueError):
        raise ValueError("Type an amount, like 12.50")
    if not amount > 0:
        raise ValueError("The amount must be more than $0")
    day = (day or "").strip() or date.today().isoformat()
    try:
        day = date.fromisoformat(day).isoformat()
    except ValueError:
        raise ValueError("The date must look like 2026-10-21")
    note = (note or "").strip()[:200]
    entry_id = db.execute("INSERT INTO money_entries (kind, amount_usd, note, day, created_at) VALUES (?, ?, ?, ?, ?)",
                          kind, amount, note, day, db.now())
    db.log("Steven", f"Logged {kind} ${amount:,.2f}" + (f" ({note})" if note else ""))
    return entry_id


def delete(entry_id: int) -> None:
    if not db.rows("SELECT id FROM money_entries WHERE id = ?", entry_id):
        raise ValueError(f"No money entry #{entry_id}")
    db.execute("DELETE FROM money_entries WHERE id = ?", entry_id)


def summary() -> dict:
    """Spent, made and net for today, this month and all time, with where each number came from."""
    periods = {}
    for name, (day_from, ts_from) in _bounds().items():
        claude, expenses = _claude(ts_from), _logged("expense", day_from)
        campaigns, income = _campaigns(ts_from), _logged("income", day_from)
        spent, made = claude + expenses, campaigns + income
        periods[name] = {"spent": round(spent, 2), "made": round(made, 2), "net": round(made - spent, 2),
                         "claude": round(claude, 2), "expenses": round(expenses, 2),
                         "campaigns": round(campaigns, 2), "income": round(income, 2)}
    entries = db.rows("SELECT id, kind, amount_usd, note, day FROM money_entries ORDER BY day DESC, id DESC LIMIT 30")
    return {"periods": periods, "entries": entries}
