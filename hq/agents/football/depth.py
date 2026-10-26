"""Depth: builds the opponent's offensive personnel sheet (one landscape PDF) from the depth chart and stats you upload.
Every Monday morning it makes this week's sheet and waits for your OK in Approvals. Plain sorting, no AI, no cost.
Save to Outbox also puts a copy in the opponent's folder, so it prints Thursday with the rest."""

import json
import shutil
import time
from datetime import date
from pathlib import Path

from ... import approvals, db
from ...config import FOOTBALL_DATA, FOOTBALL_OUTBOX
from ...football import depth, fetch, printing, season
from ..base import Agent

DRAFTS = FOOTBALL_DATA / "drafts"


FRESH_DAYS = 5   # an upload newer than this is used as is on Monday; older (or none) and Depth fetches the site


def build(opponent: str | None = None, fetch_mode: bool | str = False) -> str:
    g = season.current_game()
    opp = season.find_opponent(opponent) if opponent else (g["opponent"] if g else None)
    if not opp:
        return "There's no game coming up to build a personnel sheet for." if not opponent else f"I don't know an opponent called {opponent}."
    path = depth.input_for(opp)
    notes = []
    fresh = path and (time.time() - path.stat().st_mtime) < FRESH_DAYS * 86400
    if fetch_mode is True or (fetch_mode == "auto" and not fresh):
        try:
            got = fetch.fetch(opp)
            notes.append(f"Fetched {opp}'s roster and stats from their website ({got['players']} offensive players, "
                         f"{got['with_stats']} with stats). " + " ".join(got["notes"]))
            path = depth.input_for(opp)
        except fetch.FetchError as e:
            if not path:
                return (f"I couldn't fetch the {opp} roster and stats: {e}. Upload their depth chart and stats in the "
                        "Warrior Village tab instead.")
            notes.append(f"Couldn't fetch the {opp} site ({e}), so I used the sheet you uploaded {path.name}.")
    if not path:
        return f"I need the {opp} depth chart and stats first. Upload them in the Warrior Village tab."
    try:
        data = depth.read(path)
    except depth.DepthError as e:
        return str(e)
    DRAFTS.mkdir(parents=True, exist_ok=True)
    name = f"{opp} offensive personnel {date.today().isoformat()}.pdf"
    draft = depth.build_pdf(opp, data, DRAFTS / name)
    cols = depth.layout(data["players"])
    top = [f"{pos}: " + ", ".join(f"{i['num']} {i['name']}" for k, i in cols[pos] if k == "p")[:90]
           for pos in ("QB", "RB", "WR", "TE") if any(k == "p" for k, _ in cols.get(pos, []))]
    preview = (f"{opp} offensive personnel, from {path.name} ({len(data['players'])} players). Tops of the columns:\n"
               + "\n".join(top) + "\n\nOrdered by reps, then starts, then your depth chart order."
               + ("\n\n" + "\n".join(notes) if notes else ""))
    approvals.request("Depth", "football_depth", f"Offensive personnel: {opp}", preview,
                      {"draft": str(draft), "name": name, "opponent": opp}, yes="Save to Outbox", no="Throw away")
    return f"The {opp} personnel sheet is ready for your OK."


def _decide(payload: dict, decision: str) -> str:
    draft = Path(payload["draft"])
    if decision == "reject":
        draft.unlink(missing_ok=True)
        return "Personnel sheet thrown away."
    if not draft.exists():
        return "That draft is gone. Ask Depth to build it again."
    FOOTBALL_OUTBOX.mkdir(parents=True, exist_ok=True)
    dest = FOOTBALL_OUTBOX / payload["name"]
    shutil.move(str(draft), dest)
    db.log("Depth", f"Saved {dest.name} to the football Outbox")
    where = ""
    try:
        copy = printing.deliver(dest, payload.get("opponent"))
        if copy:
            where = f" and in the {copy.parent.name} folder, ready to print"
    except OSError as e:
        where = f" (couldn't copy it into the opponent folder: {e})"
    return f"Saved {dest.name} in the football Outbox{where}."


approvals.HANDLERS["football_depth"] = _decide


class Depth(Agent):
    def __init__(self):
        super().__init__(
            name="Depth",
            role="Opponent offensive personnel sheet. Every Monday it builds the one-page QB/RB/WR/TE/OL sheet for this "
                 "week's opponent from the depth chart and stats you upload, ordered by who gets the most reps.",
            params_help='{} for this week\'s opponent, or {"opponent": "Davenport"}. Uses the opponent\'s uploaded depth chart '
                        'and stats; {"fetch": true} reads them from the team\'s website first.',
            village="football",
            notify_when_done=True,
        )

    def run(self, task: dict) -> str:
        p = json.loads(task.get("params") or "{}")
        return build(p.get("opponent"), p.get("fetch", False))
