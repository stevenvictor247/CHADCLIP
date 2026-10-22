"""The football Inbox and Outbox.

Inbox: drop Hudl exports (PlaylistData_*.xlsx) or practice sheets (.xlsx or .csv) here, or upload them on the
dashboard. Ref checks every new or changed sheet on its own. Outbox: everything HQ makes for you.
"""

import json
from pathlib import Path

from .. import db
from ..config import FOOTBALL_INBOX, FOOTBALL_OUTBOX
from . import notebook, rulebook
from .reports import safe_name
from .sheet import SHEET_TYPES

KEEP_TYPES = SHEET_TYPES + (".pdf",)   # PDFs (Hudl cards, scripts) are kept for later agents
TEXT_TYPES = (".md", ".txt")
MAX_BYTES = 40 * 1024 * 1024


def inbox_path(name: str) -> Path:
    p = (FOOTBALL_INBOX / Path(name).name).resolve()
    if p.parent != FOOTBALL_INBOX.resolve():
        raise ValueError("Bad file name")
    return p


def _sheets() -> list[Path]:
    try:
        return sorted(p for p in FOOTBALL_INBOX.iterdir() if p.is_file() and p.suffix.lower() in SHEET_TYPES
                      and not p.name.startswith(("~$", ".")))   # ~$ = Excel's lock file while a sheet is open
    except OSError:
        return []


def scan() -> list[str]:
    """New or changed sheets since Ref last looked. Each one is marked new so Ref checks it once."""
    found = []
    known = {r["name"]: r for r in db.rows("SELECT name, modified, status FROM football_files")}
    for p in _sheets():
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        row = known.get(p.name)
        if row is None:
            db.execute("INSERT INTO football_files (name, status, modified, added_at) VALUES (?, 'new', ?, ?)",
                       p.name, mtime, db.now())
            found.append(p.name)
        elif row["modified"] != mtime and row["status"] != "checking":
            db.execute("UPDATE football_files SET status = 'new', modified = ? WHERE name = ?", mtime, p.name)
            found.append(p.name)
    return found


def listing() -> list[dict]:
    present = {p.name for p in _sheets()}
    out = []
    for r in db.rows("SELECT id, name, status, summary, fix, check_count, ref_copy, result, checked_at, added_at "
                     "FROM football_files ORDER BY id DESC"):
        if r["name"] not in present:
            continue
        flags = json.loads(r.pop("result") or "{}").get("flags", [])
        r["flags"] = flags[:60]
        r["more_flags"] = max(0, len(flags) - 60)
        out.append(r)
    return out


def outbox() -> list[dict]:
    try:
        files = sorted((p for p in FOOTBALL_OUTBOX.iterdir() if p.is_file() and not p.name.startswith(("~$", "."))),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
    return [{"name": p.name, "bytes": p.stat().st_size} for p in files[:30]]


def save_upload(filename: str, stream, max_bytes: int = MAX_BYTES) -> dict:
    """An upload from the dashboard. Sheets and PDFs go to the Inbox; a rulebook or notebook (.md/.txt) is loaded."""
    name = safe_name(Path(filename or "file").name)
    suffix = Path(name).suffix.lower()
    if suffix not in KEEP_TYPES + TEXT_TYPES:
        raise ValueError("HQ takes .xlsx or .csv sheets, PDFs, and your rulebook or notebook as .md or .txt.")
    data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("That file is over 40 MB.")
    if suffix in TEXT_TYPES:
        text = data.decode("utf-8-sig", errors="replace")
        low = name.lower()
        if "notebook" in low:
            n = notebook.import_markdown(text)
            db.log("Scribe", f"Imported {n} notebook entries from {name}")
            return {"kind": "notebook", "message": f"Imported {n} notebook entries."}
        if "rulebook" in low or "rules" in low:
            rulebook.save(text)
            db.log("Captain", f"Loaded the football rulebook from {name}")
            return {"kind": "rulebook", "message": "Rulebook loaded. Every football agent reads it from now on."}
        raise ValueError("Name the text file with rulebook or notebook in it, so HQ knows what it is.")
    dest = inbox_path(name)
    dest.write_bytes(data)
    if suffix == ".pdf":
        return {"kind": "pdf", "message": f"Saved {name} in the football Inbox. (No agent reads PDFs yet.)"}
    return {"kind": "sheet", "message": f"Saved {name}. Ref is checking it now.", "name": name}
