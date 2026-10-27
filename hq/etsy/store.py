"""The Etsy village's records: designs on the product board, Radar's briefs, your research notes and Printify orders."""

import json
import os
from datetime import datetime, timedelta, timezone

from .. import db

# The product board, left to right. Each design moves along it; held and rejected ones step off.
STAGES = ["written", "drawn", "review", "approved", "building", "ready", "live", "retired", "held", "rejected"]
WAITING = ("written", "drawn", "review")   # made, but not yet past your OK

JSON_FIELDS = ("tags", "warden", "files")


def designs_per_day() -> int:
    return max(0, int(os.getenv("HQ_ETSY_DESIGNS_PER_DAY", "4") or 0))


def max_waiting() -> int:
    return max(1, int(os.getenv("HQ_ETSY_MAX_WAITING", "8") or 8))


def _out(row: dict) -> dict:
    for k in JSON_FIELDS:
        try:
            row[k] = json.loads(row.get(k) or ("[]" if k == "tags" else "{}"))
        except ValueError:
            row[k] = [] if k == "tags" else {}
    return row


def add_design(d: dict, brief_id: int | None = None) -> int:
    ts = db.now()
    return db.execute(
        "INSERT INTO etsy_designs (brief_id, theme, slogan, subline, style, art_prompt, title, tags, description, "
        "price_cents, stage, note, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'written', ?, ?, ?)",
        brief_id, d["theme"], d["slogan"], d.get("subline") or None, d.get("style") or "bold",
        d.get("art_prompt") or None, d["title"], json.dumps(d.get("tags") or []), d.get("description") or "",
        int(d.get("price_cents") or 2499), "Quill wrote it", ts, ts)


def get(design_id: int) -> dict | None:
    rows = db.rows("SELECT * FROM etsy_designs WHERE id = ?", design_id)
    return _out(rows[0]) if rows else None


def designs(stage: str | None = None, limit: int = 200) -> list[dict]:
    if stage:
        rows = db.rows("SELECT * FROM etsy_designs WHERE stage = ? ORDER BY id LIMIT ?", stage, limit)
    else:
        rows = db.rows("SELECT * FROM etsy_designs ORDER BY id DESC LIMIT ?", limit)
    return [_out(r) for r in rows]


def update(design_id: int, **fields):
    if not fields:
        return
    for k in JSON_FIELDS:
        if k in fields and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k])
    sets = ", ".join(f"{k} = ?" for k in fields)
    db.execute(f"UPDATE etsy_designs SET {sets}, updated_at = ? WHERE id = ?", *fields.values(), db.now(), design_id)


def move(design_id: int, stage: str, note: str):
    if stage not in STAGES:
        raise ValueError(f"Unknown stage {stage}")
    update(design_id, stage=stage, note=note)


def counts() -> dict:
    out = {s: 0 for s in STAGES}
    for r in db.rows("SELECT stage, COUNT(*) n FROM etsy_designs GROUP BY stage"):
        out[r["stage"]] = r["n"]
    return out


def waiting() -> int:
    c = counts()
    return sum(c[s] for s in WAITING)


def _local_midnight_utc() -> str:
    return datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0) \
        .astimezone(timezone.utc).isoformat(timespec="seconds")


def made_today() -> int:
    return db.rows("SELECT COUNT(*) n FROM etsy_designs WHERE created_at >= ?", _local_midnight_utc())[0]["n"]


def used_slogans(limit: int = 300) -> list[str]:
    return [r["slogan"] for r in db.rows("SELECT slogan FROM etsy_designs ORDER BY id DESC LIMIT ?", limit)]


def steven_approved() -> int:
    """Designs you approved yourself, from Approvals. After the first few, design review can go automatic."""
    return db.rows("SELECT COUNT(*) n FROM approvals WHERE kind = 'etsy_design' AND status = 'approved'")[0]["n"]


# ---- briefs and notes ----------------------------------------------------------------------------------------

def add_brief(themes: list[dict], source: str, note: str = "") -> int:
    return db.execute("INSERT INTO etsy_briefs (themes, source, note, created_at) VALUES (?, ?, ?, ?)",
                      json.dumps(themes), source, note, db.now())


def latest_brief() -> dict | None:
    rows = db.rows("SELECT * FROM etsy_briefs ORDER BY id DESC LIMIT 1")
    if not rows:
        return None
    b = rows[0]
    b["themes"] = json.loads(b["themes"])
    return b


def brief_age_days() -> float | None:
    b = latest_brief()
    if not b:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(b["created_at"])).total_seconds() / 86400


def add_note(text: str, kind: str = "research") -> int:
    return db.execute("INSERT INTO etsy_notes (kind, text, created_at) VALUES (?, ?, ?)", kind, text.strip(), db.now())


def notes(kind: str | None = None, unused: bool = False, limit: int = 20) -> list[dict]:
    sql, args = "SELECT * FROM etsy_notes WHERE 1 = 1", []
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    if unused:
        sql += " AND used = 0"
    return db.rows(sql + " ORDER BY id DESC LIMIT ?", *args, limit)


def mark_notes_used(ids: list[int]):
    for i in ids:
        db.execute("UPDATE etsy_notes SET used = 1 WHERE id = ?", i)


def week_ago() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
