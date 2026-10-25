"""Clock: the game-week checklist. Knows the schedule and what's due each week, and pings your phone each morning
when something is due or late. Plain rules, no AI, so it costs nothing."""

import json

from ...football import printing, season
from ..base import Agent


def summary() -> str:
    w = season.week()
    if w["season_over"]:
        return "The season is over. No game week to track."
    g = w["game"]
    lines = [f"Game week: {g['opponent']}, {g['day']} {g['date']} ({w['days_to_game']} days)"
             + ("" if g["confirmed"] else " (date not confirmed yet)")]
    for x in w["checklist"]:
        mark = {"done": "✓", "late": "LATE", "today": "TODAY", "coming": "·"}[x["state"]]
        lines.append(f"{mark} {x['item']} (due {x['due_day']})")
    return "\n".join(lines)


class Clock(Agent):
    def __init__(self):
        super().__init__(
            name="Clock",
            role="Game-week planner. Keeps each week's checklist (scouting report, Birds and Rabbits, personnel sheet, "
                 "stunt sheet, scout cards, itinerary) and texts your phone when something is due or late.",
            params_help='{} for this week\'s checklist; {"done": "Personnel sheet"} or {"undo": "..."} to tick an item '
                        '(add "opponent" for another week); {"game": {"opponent": "Davenport", "date": "2026-10-24", '
                        '"kickoff": "1:00 PM", "site": "home"}}; {"due": {"item": "Teamworks itinerary", "weekday": '
                        '"Thursday"}} or {"due": {"item": "...", "days_before": 3, "add": true}} or {"due": {"item": "...", '
                        '"remove": true}}; {"folders": true} makes the opponent folders; {"print": true} prints '
                        'the Thursday print folder now; {"pause": true} or {"resume": true} for the Thursday print',
            village="football",
            notify_when_done=True,
        )

    def run(self, task: dict) -> str:
        p = json.loads(task.get("params") or "{}")
        done = []
        if p.get("done"):
            done.append(season.mark(p["done"], True, p.get("opponent")))
        if p.get("undo"):
            done.append(season.mark(p["undo"], False, p.get("opponent")))
        if p.get("game"):
            g = p["game"]
            done.append(season.set_game(g["opponent"], g.get("date"), g.get("kickoff"), g.get("site")))
        if p.get("due"):
            d = p["due"]
            done.append(season.set_due(d["item"], d.get("days_before"), d.get("weekday"), bool(d.get("add")),
                                       bool(d.get("remove"))))
        if p.get("folders"):
            made = printing.ensure_folders()
            return ("Made folders for " + ", ".join(made) + ".") if made else "Every opponent already has a folder."
        if p.get("print"):
            return printing.print_now("Print now")
        if p.get("pause") or p.get("resume"):
            return printing.set_paused(bool(p.get("pause")))
        return "\n".join(done + [summary()])
