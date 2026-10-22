"""Ref: checks tagged sheets against Steven's tagging rules. Plain rules (hq/football/tagrules.py), no AI.

Every new or changed sheet in the football Inbox gets checked on its own. Ref writes a copy of the sheet to the
Outbox with each flagged cell colored and a REF column saying why. Your original file is never changed."""

import json
from pathlib import Path

from ... import db
from ...config import FOOTBALL_OUTBOX
from ...football import files, reports, sheet, tagrules
from ..base import Agent


def check_file(name: str) -> str:
    path = files.inbox_path(name)
    if not path.exists():
        return f"There's no {name} in the football Inbox."
    if not db.rows("SELECT 1 FROM football_files WHERE name = ?", path.name):
        db.execute("INSERT INTO football_files (name, added_at) VALUES (?, ?)", path.name, db.now())
    db.execute("UPDATE football_files SET status = 'checking', modified = ? WHERE name = ?", path.stat().st_mtime, path.name)
    try:
        result = tagrules.check_sheet(sheet.read(path))
    except Exception as e:  # a broken or odd file: say so, don't crash the worker
        msg = str(e) if isinstance(e, sheet.SheetError) else f"{path.name}: couldn't read it ({e})."
        db.execute("UPDATE football_files SET status = 'failed', summary = ?, checked_at = ? WHERE name = ?",
                   msg, db.now(), path.name)
        return msg
    copy = None
    if result["flags"]:
        try:
            copy = reports.ref_copy(path, result, FOOTBALL_OUTBOX / f"{path.stem} - Ref check.xlsx")
        except Exception as e:
            result["summary"] += f" (Couldn't write the marked-up copy: {e})"
    db.execute("UPDATE football_files SET status = 'checked', summary = ?, fix = ?, check_count = ?, result = ?, "
               "ref_copy = ?, checked_at = ? WHERE name = ?", result["summary"], result["fix"], result["check"],
               json.dumps(result), copy.name if copy else None, db.now(), path.name)
    lines = [result["summary"]]
    fixes = [f for f in result["flags"] if f["level"] == "fix"]
    for f in fixes[:3]:
        lines.append(f"- {f['label']}: {f['message']}")
    if len(fixes) > 3:
        lines.append(f"...and {len(fixes) - 3} more to fix.")
    if copy:
        lines.append(f"Marked-up copy: {copy.name} in the football Outbox.")
    return "\n".join(lines)


class Ref(Agent):
    def __init__(self):
        super().__init__(
            name="Ref",
            role="Tag checker. Checks your tagged sheets (Hudl exports or practice sheets) against your tagging rules "
                 "and marks what to fix. Never changes your file.",
            params_help='{"file": "name of a sheet in the football Inbox"}. Without a file, checks every new sheet.',
            village="football",
            notify_when_done=True,
        )

    def run(self, task: dict) -> str:
        p = json.loads(task.get("params") or "{}")
        if p.get("file"):
            return check_file(Path(p["file"]).name)
        names = files.scan() or [r["name"] for r in db.rows("SELECT name FROM football_files WHERE status = 'new'")]
        if not names:
            return "No new sheets in the football Inbox."
        return "\n\n".join(check_file(n) for n in names)
