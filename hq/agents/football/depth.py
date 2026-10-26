"""Depth: builds the opponent's offensive personnel sheet (one landscape PDF) from the depth chart and stats you upload.
Every Monday morning it makes this week's sheet and waits for your OK in Approvals. Plain sorting, no AI, no cost.
Save to Outbox also puts a copy in the opponent's folder, so it prints Thursday with the rest."""

import json
import shutil
from datetime import date
from pathlib import Path

from ... import approvals, db
from ...config import FOOTBALL_DATA, FOOTBALL_OUTBOX
from ...football import depth, printing, season
from ..base import Agent

DRAFTS = FOOTBALL_DATA / "drafts"


def build(opponent: str | None = None) -> str:
    g = season.current_game()
    opp = season.find_opponent(opponent) if opponent else (g["opponent"] if g else None)
    if not opp:
        return "There's no game coming up to build a personnel sheet for." if not opponent else f"I don't know an opponent called {opponent}."
    path = depth.input_for(opp)
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
               + "\n".join(top) + "\n\nOrdered by reps, then starts, then your depth chart order.")
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
            params_help='{} for this week\'s opponent, or {"opponent": "Davenport"}. Needs the opponent\'s depth chart and '
                        'stats uploaded first.',
            village="football",
            notify_when_done=True,
        )

    def run(self, task: dict) -> str:
        p = json.loads(task.get("params") or "{}")
        return build(p.get("opponent"))
