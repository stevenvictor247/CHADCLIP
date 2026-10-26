"""Clock's side of the football village: the 2026 schedule, each game week's checklist, and phone reminders.

Defaults come from config/football.yaml. Your changes (a kickoff time, a due day, a date fix) are saved to
data/football/season.json, which updates never touch. Ticking items off is saved in the database.
"""

import json
import re
from datetime import date, datetime, timedelta

import yaml

from .. import db
from ..config import CONFIG_DIR, FOOTBALL_DATA

DEFAULTS_PATH = CONFIG_DIR / "football.yaml"
CHANGES_PATH = FOOTBALL_DATA / "season.json"
DAY = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _defaults() -> dict:
    return yaml.safe_load(DEFAULTS_PATH.read_text(encoding="utf-8")) or {}


def _changes() -> dict:
    try:
        return json.loads(CHANGES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_changes(c: dict) -> None:
    CHANGES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHANGES_PATH.write_text(json.dumps(c, indent=2), encoding="utf-8")


def _day(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def games() -> list[dict]:
    changed = _changes().get("games", {})
    out = []
    for g in _defaults().get("games", []):
        g = {**g, **changed.get(g["opponent"], {})}
        g["date"] = _day(g["date"])
        out.append(g)
    return sorted(out, key=lambda g: g["date"])


def items() -> list[dict]:
    c = _changes()
    changed = c.get("items", {})
    rows = _defaults().get("items", []) + [{"name": n} for n in c.get("extra_items", [])]
    out = [{**i, **changed.get(i["name"], {})} for i in rows]
    return [i for i in out if not i.get("removed") and i.get("days_before") is not None]


def site_for(opponent: str) -> str | None:
    return (_defaults().get("sites") or {}).get(opponent)


def find_opponent(text: str) -> str | None:
    """The opponent a name or file name points to, using full names and nicknames (DU, SVSU, NMU...)."""
    up = " " + re.sub(r"[^A-Z0-9]+", " ", (text or "").upper()) + " "
    nick = _defaults().get("nicknames", {})
    best = None
    for g in games():
        names = [g["opponent"].upper(), *[n.upper() for n in nick.get(g["opponent"], [])]]
        for n in names:
            clean = f" {re.sub(r'[^A-Z0-9]+', ' ', n).strip()} "
            at = up.find(clean)
            # the name that comes first in the text wins, so "SVSU at Northwood" is Saginaw Valley, not Northwood
            if at >= 0 and (best is None or (at, -len(clean)) < best[0]):
                best = ((at, -len(clean)), g["opponent"])
    return best[1] if best else None


def current_game(today: date | None = None) -> dict | None:
    """The game this week is building toward: the next game on or after today."""
    today = today or date.today()
    return next((g for g in games() if g["date"] >= today), None)


def checklist(game: dict, today: date | None = None) -> list[dict]:
    today = today or date.today()
    done = {r["item"]: r["done_at"] for r in db.rows("SELECT item, done_at FROM football_checklist WHERE opponent = ?",
                                                      game["opponent"])}
    out = []
    for i in items():
        due = game["date"] - timedelta(days=int(i["days_before"]))
        state = "done" if i["name"] in done else "late" if due < today else "today" if due == today else "coming"
        out.append({"item": i["name"], "due": due.isoformat(), "due_day": DAY[due.weekday()], "state": state,
                    "done_at": done.get(i["name"])})
    return sorted(out, key=lambda x: (x["due"], x["item"]))


def week(today: date | None = None) -> dict:
    """Everything the dashboard and the Boss need about this game week."""
    today = today or date.today()
    g = current_game(today)
    if not g:
        return {"season_over": True, "games": [_public(x) for x in games()]}
    lst = checklist(g, today)
    return {"season_over": False, "game": _public(g), "days_to_game": (g["date"] - today).days, "checklist": lst,
            "late": [x["item"] for x in lst if x["state"] == "late"],
            "due_today": [x["item"] for x in lst if x["state"] == "today"],
            "games": [_public(x) for x in games()]}


def _public(g: dict) -> dict:
    return {"opponent": g["opponent"], "date": g["date"].isoformat(), "day": DAY[g["date"].weekday()],
            "kickoff": g.get("kickoff"), "site": g.get("site"), "confirmed": bool(g.get("confirmed"))}


def _match(name: str, choices: list[str]) -> str:
    low = {c.lower(): c for c in choices}
    if name.lower() in low:
        return low[name.lower()]
    hits = [c for c in choices if name.lower() in c.lower()]
    if len(hits) == 1:
        return hits[0]
    raise ValueError(f"\"{name}\" doesn't match one of: {', '.join(choices)}")


def mark(item: str, done: bool = True, opponent: str | None = None) -> str:
    g = next((x for x in games() if x["opponent"] == _match(opponent, [x["opponent"] for x in games()])), None) \
        if opponent else current_game()
    if not g:
        raise ValueError("The season is over, so there's no game week to tick off.")
    name = _match(item, [i["name"] for i in items()])
    if done:
        db.execute("INSERT OR IGNORE INTO football_checklist (opponent, item, done_at) VALUES (?, ?, ?)",
                   g["opponent"], name, db.now())
    else:
        db.execute("DELETE FROM football_checklist WHERE opponent = ? AND item = ?", g["opponent"], name)
    return f"{name} for {g['opponent']}: {'done' if done else 'not done'}."


def set_game(opponent: str, game_date: str | None = None, kickoff: str | None = None, site: str | None = None) -> str:
    name = _match(opponent, [g["opponent"] for g in games()])
    c = _changes()
    g = c.setdefault("games", {}).setdefault(name, {})
    if game_date:
        g["date"], g["confirmed"] = _day(game_date).isoformat(), True
    if kickoff is not None:
        g["kickoff"] = kickoff.strip() or None
    if site is not None:
        if site.lower() not in ("home", "away", "neutral", ""):
            raise ValueError("site is home, away or neutral")
        g["site"] = site.lower() or None
    _save_changes(c)
    return f"Saved for {name}: " + ", ".join(f"{k} {v}" for k, v in g.items() if v not in (None, True)) + "."


def set_due(item: str, days_before: int | None = None, weekday: str | None = None, add: bool = False,
            remove: bool = False) -> str:
    """Change when a checklist item is due (days before game day, or the weekday for a Saturday game),
    add a new item, or take one off the checklist."""
    if weekday:
        days_before = (5 - DAY.index(_match(weekday, list(DAY)))) % 7 or 7   # days before a Saturday
    c = _changes()
    if add:
        name = " ".join(item.split())
        if days_before is None:
            raise ValueError("Say when the new item is due.")
        if name.lower() not in {n.lower() for n in c.get("extra_items", [])} | {i["name"].lower() for i in items()}:
            c.setdefault("extra_items", []).append(name)
        c.setdefault("items", {})[name] = {"days_before": int(days_before)}
        _save_changes(c)
        return f"Added {name}, due {days_before} days before each game."
    known = [i["name"] for i in _defaults().get("items", [])] + c.get("extra_items", [])
    name = _match(item, known)
    entry = c.setdefault("items", {}).setdefault(name, {})
    if remove:
        entry["removed"] = True
        msg = f"{name}: taken off the checklist."
    elif days_before is not None:
        entry.pop("removed", None)
        entry["days_before"] = int(days_before)
        msg = f"{name}: due {days_before} days before game day."
    else:
        raise ValueError("Say when it's due, or remove it.")
    _save_changes(c)
    return msg


def reminder(today: date | None = None) -> str | None:
    """Today's phone message, or None when nothing is due, late, or worth a Sunday heads-up."""
    today = today or date.today()
    w = week(today)
    if w["season_over"]:
        return None
    g, lst = w["game"], w["checklist"]
    left = [x for x in lst if x["state"] != "done"]
    sunday = today.weekday() == 6
    if not (w["late"] or w["due_today"] or (sunday and left)):
        return None
    when = "today" if w["days_to_game"] == 0 else "tomorrow" if w["days_to_game"] == 1 else f"in {w['days_to_game']} days"
    lines = [f"Game week: {g['opponent']}, {g['day']} {g['date'][5:].replace('-', '/')} ({when})."]
    if w["due_today"]:
        lines.append("Due today: " + ", ".join(w["due_today"]) + ".")
    if w["late"]:
        lines.append("Late: " + ", ".join(w["late"]) + ".")
    if sunday:
        coming = [f"{x['item']} ({x['due_day'][:3]})" for x in left if x["state"] == "coming"]
        if coming:
            lines.append("This week: " + ", ".join(coming) + ".")
    lines.append("Tick things off on the dashboard, or tell the Boss \"personnel sheet done\".")
    return "\n".join(lines)


def remind_if_due(hour: int, now: datetime | None = None) -> bool:
    """Send today's reminder once, at or after `hour`. Uses relay_sent so a restart never sends it twice."""
    from .. import relay
    now = now or datetime.now()
    if now.hour < hour:
        return False
    key = int(now.strftime("%Y%m%d"))
    if db.rows("SELECT 1 FROM relay_sent WHERE kind = 'clock' AND ref_id = ?", key):
        return False
    text = reminder(now.date())
    db.execute("INSERT OR IGNORE INTO relay_sent (kind, ref_id, created_at) VALUES ('clock', ?, ?)", key, db.now())
    if text:
        relay.notify("⏰ Clock\n" + text)
        db.log("Clock", text.splitlines()[0] + (" " + text.splitlines()[1] if len(text.splitlines()) > 2 else ""))
    return bool(text)
