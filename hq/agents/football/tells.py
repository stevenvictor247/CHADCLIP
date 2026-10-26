"""Tells: builds the scouting report and Birds and Rabbits (3 biggest run tells, 3 biggest pass tells) from a
tagged sheet. The numbers are plain counting (hq/football/tendencies.py), never AI, so none can be made up.

The report waits in Approvals. Save to Outbox puts the PDF in your football Outbox; sending it to your DC is
always your move."""

import json
import shutil
from datetime import date
from pathlib import Path

from ... import approvals, db
from ...config import FOOTBALL_DATA, FOOTBALL_OUTBOX
from ...football import files, pdfreports, printing, season, sheet, tendencies
from ..base import Agent

DRAFTS = FOOTBALL_DATA / "drafts"
MIN_REPORT_PLAYS = 10


def sheets_for(path: Path, opponent: str | None) -> list[Path]:
    """The sheet itself plus every other sheet in the Inbox for the same opponent: one Hudl export per game, together
    they are the scouting sample. Oldest first, so the games read in the order they were played."""
    opp = opponent or season.find_opponent(path.stem)
    found = [path]
    if opp:
        found += [p for p in files._sheets() if p != path and season.find_opponent(p.stem) == opp]
    return sorted(set(found), key=lambda p: (p.stat().st_mtime, p.name))


def build(name: str, opponent: str | None = None, kind: str = "scouting") -> str:
    path = files.inbox_path(name)
    if not path.exists():
        return f"There's no {name} in the football Inbox."
    opp = opponent or season.find_opponent(path.stem) or "Opponent"
    try:
        data = [sheet.read(p) for p in sheets_for(path, None if opp == "Opponent" else opp)]
    except sheet.SheetError as e:
        return str(e)
    a = tendencies.analyse(data)
    if a["plays"] < MIN_REPORT_PLAYS:
        return (f"{path.name} has only {a['plays']} plays tagged run or pass (PLAY TYPE or RESULT), too few for a "
                "report. Tells needs at least 10.")
    birds = kind == "birds"
    out_name = pdfreports_name(opp, birds)
    draft = (pdfreports.birds_rabbits_pdf if birds else pdfreports.data_pdf)(a, opp, DRAFTS / out_name)
    preview = tendencies.birds_and_rabbits(a, opp)
    if len(data) > 1:
        preview += f"\n\nBuilt from {len(data)} games: " + ", ".join(a["game_names"]) + "."
    ref = db.rows("SELECT fix FROM football_files WHERE name = ? AND status = 'checked'", path.name)
    if ref and ref[0]["fix"]:
        preview += f"\n\nRef found {ref[0]['fix']} tag{'s' if ref[0]['fix'] > 1 else ''} to fix in this sheet. Fix them and rebuild for cleaner numbers."
    if opp == "Opponent":
        preview += "\n\n(I couldn't tell the opponent from the file name. Tell the Boss who it is and I'll rebuild it.)"
    label = "Birds and Rabbits" if birds else "Scouting report"
    approvals.request("Tells", "football_report", f"{label}: {opp} ({a['plays']} plays)", preview,
                      {"draft": str(draft), "name": out_name, "opponent": opp}, yes="Save to Outbox", no="Throw away")
    return f"{label} for {opp} is ready for your OK ({a['plays']} plays)."


def pdfreports_name(opp: str, birds: bool) -> str:
    from ...football.reports import safe_name
    return safe_name(f"{opp} {'birds and rabbits' if birds else 'scouting report'} {date.today().isoformat()}.pdf")


def _decide(payload: dict, decision: str) -> str:
    draft = Path(payload["draft"])
    if decision == "reject":
        draft.unlink(missing_ok=True)
        return "Report thrown away."
    if not draft.exists():
        return "That draft is gone. Ask Tells to build it again."
    FOOTBALL_OUTBOX.mkdir(parents=True, exist_ok=True)
    dest = FOOTBALL_OUTBOX / payload["name"]
    shutil.move(str(draft), dest)
    db.log("Tells", f"Saved {dest.name} to the football Outbox")
    where = ""
    try:
        copy = printing.deliver(dest, payload.get("opponent"))
        if copy:
            where = f" and in the {copy.parent.name} folder, ready to print"
    except OSError as e:
        where = f" (couldn't copy it into the opponent folder: {e})"
    return f"Saved {dest.name} in the football Outbox{where}. Sending it to your DC is up to you."


approvals.HANDLERS["football_report"] = _decide


class Tells(Agent):
    def __init__(self):
        super().__init__(
            name="Tells",
            role="Scouting report and Birds and Rabbits. Counts tendencies from a tagged sheet and lists the 3 biggest "
                 "run tells and 3 biggest pass tells, each with its sample size. Plain counting, no made-up numbers.",
            params_help='{"file": "sheet in the football Inbox", "opponent": "Davenport", "kind": "scouting" or "birds"}. '
                        'Without a file, uses the newest sheet. "birds" makes just the one-page Birds and Rabbits.',
            village="football",
        )

    def run(self, task: dict) -> str:
        p = json.loads(task.get("params") or "{}")
        name = p.get("file")
        if not name:
            newest = files.listing()
            if not newest:
                return "There are no sheets in the football Inbox yet. Drop a Hudl export in first."
            name = newest[0]["name"]
        return build(Path(name).name, p.get("opponent"), p.get("kind", "scouting"))
