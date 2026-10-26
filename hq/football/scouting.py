"""The Monday scouting report: at 5 PM Monday (or later that week if HQ was off) Tells builds this week's scouting report
and the one-page Birds and Rabbits from the newest tagged Hudl export for the opponent. Both wait in Approvals for your OK.
If there's no export for that opponent yet, it texts you what it needs. Once a week."""

import json
import os
from datetime import datetime, timedelta

from .. import db
from ..config import FOOTBALL_DATA
from . import files, season

STATE = FOOTBALL_DATA / "scouting_state.json"
SCOUTING_HOUR = int(os.getenv("HQ_SCOUTING_HOUR", "").strip() or "17") % 24   # Monday, local time


def newest_export(opponent: str) -> str | None:
    """The newest sheet in the Inbox with this opponent's name in its file name (the listing is newest first)."""
    return next((r["name"] for r in files.listing() if season.find_opponent(r["name"].rsplit(".", 1)[0]) == opponent), None)


def run_if_due(now: datetime | None = None) -> str | None:
    from .. import relay
    now = now or datetime.now()
    if now.weekday() > 2 or (now.weekday() == 0 and now.hour < SCOUTING_HOUR):
        return None
    monday = (now.date() - timedelta(days=now.weekday())).isoformat()
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if state.get("week") == monday:
        return None
    g = season.current_game(now.date())
    if not g:
        return None
    state["week"] = monday
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state), encoding="utf-8")
    name = newest_export(g["opponent"])
    if name:
        db.create_task("Tells", f"Scouting report from {name}", {"file": name, "opponent": g["opponent"]}, created_by="Schedule")
        db.create_task("Tells", f"Birds and Rabbits from {name}", {"file": name, "opponent": g["opponent"], "kind": "birds"},
                       created_by="Schedule")
        return "queued"
    relay.notify(f"📊 Tells\nI need the tagged Hudl export for {g['opponent']} to make this week's scouting report. Drop it in "
                 "the Inbox (put the team name in the file name).")
    return "asked"
