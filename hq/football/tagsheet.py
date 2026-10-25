"""Your tag sheet: the list of every tag you use (formations, tags, modifiers, calls) and what each one means.

Upload it once from the football panel. It's private, so it lives in data/football/ on your PC and never goes into git.
Captain reads it (so a question about a tag uses your word for it), and Ref doesn't flag a word that's on it as unknown.
Excel, CSV or a text file all work: every cell's words count.
"""

import csv
import io
import json
import re
from datetime import datetime

from ..config import FOOTBALL_DATA

PATH = FOOTBALL_DATA / "tagsheet.json"   # {"name", "text", "saved"}: the original's name and every cell as plain text
TYPES = (".xlsx", ".xlsm", ".csv", ".md", ".txt")
MAX_CHARS = 20000


def _rows(name: str, data: bytes) -> list[list[str]]:
    suffix = name[name.rfind("."):].lower()
    if suffix in (".xlsx", ".xlsm"):
        import openpyxl
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception:
            raise ValueError("I couldn't open that Excel file. Save it again as .xlsx or .csv.")
        out = []
        for ws in wb.worksheets:
            if len(wb.worksheets) > 1:
                out.append([f"[{ws.title}]"])
            for row in ws.iter_rows(values_only=True):
                cells = ["" if c is None else str(c).strip() for c in row]
                if any(cells):
                    out.append(cells)
        return out
    text = data.decode("utf-8-sig", errors="replace")
    if suffix == ".csv":
        return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    return [[line] for line in text.splitlines() if line.strip()]


def save(name: str, data: bytes) -> dict:
    if not name.lower().endswith(TYPES):
        raise ValueError("Send the tag sheet as Excel (.xlsx), CSV, or a .md/.txt file.")
    rows = _rows(name, data)
    text = "\n".join(" | ".join(c for c in r if c) for r in rows).strip()
    if len(text) < 10:
        raise ValueError("That tag sheet looks empty.")
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps({"name": name, "text": text[:MAX_CHARS], "saved": datetime.now().isoformat(timespec="minutes")}),
                    encoding="utf-8")
    return info()


def _load() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def loaded() -> bool:
    return bool(_load().get("text"))


def text() -> str:
    return _load().get("text", "")


def words() -> set[str]:
    """Every word on the sheet, upper case, so Ref can tell a tag you use from a typo."""
    return set(re.findall(r"[A-Z0-9][A-Z0-9'-]*", text().upper()))


def clear() -> None:
    PATH.unlink(missing_ok=True)


def info() -> dict:
    d = _load()
    return {"loaded": bool(d.get("text")), "name": d.get("name"), "saved": d.get("saved"), "words": len(words())}
