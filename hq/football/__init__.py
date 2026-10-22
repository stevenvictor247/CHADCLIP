"""Warrior Village: the football side of HQ (Steven's work as a defensive GA at Wayne State).

Agents: Captain (runs the village), Clock (game-week checklist), Ref (tag checker), Tells (scouting report and
Birds and Rabbits) and Scribe (Coaching Notebook). Their code is in hq/agents/football; what they share is here.
"""

from .. import db, ledger
from ..config import FOOTBALL_AGENTS, FOOTBALL_INBOX, FOOTBALL_OUTBOX
from . import files, notebook, rulebook, season


def pending_approvals() -> list[dict]:
    marks = ", ".join("?" for _ in FOOTBALL_AGENTS)
    return db.rows(f"SELECT id, agent, title FROM approvals WHERE status = 'pending' AND agent IN ({marks})",
                   *FOOTBALL_AGENTS)


def state() -> dict:
    """Everything the dashboard's football panel and Warrior Village show."""
    all_notes = notebook.notes()
    spend = ledger.summary()
    return {
        "week": season.week(),
        "files": files.listing(),
        "outbox": files.outbox(),
        "notes": [{"id": n["id"], "tab": n["tab"], "text": notebook.shown(n)} for n in all_notes[-8:]][::-1],
        "notes_total": len(all_notes),
        "rulebook_loaded": rulebook.loaded(),
        "inbox_path": str(FOOTBALL_INBOX),
        "outbox_path": str(FOOTBALL_OUTBOX),
        "spend_today_usd": spend["football_today_usd"],
        "budget_usd": spend["football_budget_usd"],
        "over_budget": spend["football_over_budget"],
    }


def status() -> dict:
    """The short version for the Boss and Captain."""
    w = season.week()
    out = {"rulebook_loaded": rulebook.loaded(), "notebook_entries": len(notebook.notes()),
           "waiting_for_your_ok": [a["title"] for a in pending_approvals()],
           "inbox": [{"file": f["name"], "status": f["status"], "ref": f["summary"]} for f in files.listing()[:8]],
           "spend_today_usd": ledger.spent_today("football"), "over_budget": ledger.over_budget("football")}
    if w["season_over"]:
        out["season"] = "over"
    else:
        out["game_week"] = {**w["game"], "days_to_game": w["days_to_game"], "late": w["late"],
                            "due_today": w["due_today"],
                            "still_to_do": [f"{x['item']} (due {x['due_day']})" for x in w["checklist"] if x["state"] == "coming"],
                            "done": [x["item"] for x in w["checklist"] if x["state"] == "done"]}
        out["unconfirmed_dates"] = [g["opponent"] for g in w["games"] if not g["confirmed"] and g["date"] >= w["game"]["date"]]
    return out
