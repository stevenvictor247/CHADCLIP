"""Read a tagged play sheet: a Hudl export (PlaylistData_*.xlsx) or your Google practice sheet saved as .xlsx or .csv.

Columns are found by their header names, so their order doesn't matter and extra columns are fine.
"""

import csv
import io
import re
from pathlib import Path

# Our name for a column -> header spellings seen in Hudl exports and the practice sheets.
COLUMNS = {
    "clip": ("CLIP",),
    "play": ("PLAY #", "PLAY", "PLAY NUMBER", "PLAY NO", "PLAY NUM"),
    "odk": ("ODK",),
    "dn": ("DN", "DOWN"),
    "dist": ("DIST", "DISTANCE"),
    "yard": ("YARD LN", "YARD LINE", "YD LN", "YDLN"),
    "hash": ("HASH",),
    "play_type": ("PLAY TYPE",),
    "result": ("RESULT",),
    "gain": ("GN/LS", "GAIN", "GN LS"),
    "personnel": ("PERSONNEL", "PERS"),
    "form": ("OFF FORM", "FORMATION", "OFF FORMATION"),
    "tag": ("FORMATION TAG", "FORM TAG", "FORMATION TAGS"),
    "backfield": ("BACKFIELD",),
    "motion": ("MOTION",),
    "off_play": ("OFF PLAY",),
    "confidence": ("CONFIDENCE",),
    "notes": ("NOTES", "NOTE"),
}
TAG_COLUMNS = ("personnel", "form", "tag", "backfield")   # the four columns you tag on every snap
SHEET_TYPES = (".xlsx", ".xlsm", ".csv")


class SheetError(ValueError):
    pass


def _norm_header(h) -> str:
    return re.sub(r"\s+", " ", str(h or "").replace("\n", " ")).strip().upper()


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v)).strip()


def personnel_text(v) -> str:
    """Hudl saves personnel as a number, so 02 comes out as 2 and 00 as 0. Put the leading zero back."""
    t = _text(v)
    return t.zfill(2) if t.isdigit() and len(t) < 2 else t


def number(v) -> int | None:
    t = _text(v).replace("+", "")
    return int(t) if re.fullmatch(r"-?\d+", t) else None


def _grid(path: Path) -> list[list]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        raw = path.read_bytes().decode("utf-8-sig", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(raw[:4000], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return [row for row in csv.reader(io.StringIO(raw), dialect)]
    if suffix in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            for ws in wb.worksheets:   # the first sheet that has tag columns
                grid = [list(r) for r in ws.iter_rows(values_only=True)]
                if _find_header(grid) is not None:
                    return grid
            return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)] if wb.worksheets else []
        finally:
            wb.close()
    raise SheetError(f"{path.name}: HQ reads .xlsx and .csv sheets. In Google Sheets use File > Download > Microsoft Excel.")


def _find_header(grid: list[list]) -> int | None:
    known = {h for spellings in COLUMNS.values() for h in spellings}
    for i, row in enumerate(grid[:15]):
        names = {_norm_header(c) for c in row}
        if len(names & known) >= 3 and names & {"PERSONNEL", "OFF FORM", "BACKFIELD", "FORMATION"}:
            return i
    return None


def read(path: str | Path) -> dict:
    """Returns {"name", "columns": [our names found], "rows": [{"row": sheet row number, <column>: text, ...}]}."""
    path = Path(path)
    grid = _grid(path)
    h = _find_header(grid)
    if h is None:
        raise SheetError(f"{path.name}: couldn't find the header row. HQ looks for columns like PERSONNEL, OFF FORM "
                         "and BACKFIELD in the first rows.")
    where = {}
    for i, cell in enumerate(grid[h]):
        name = _norm_header(cell)
        for ours, spellings in COLUMNS.items():
            if name in spellings and ours not in where:
                where[ours] = i
    rows = []
    for n, raw in enumerate(grid[h + 1:], start=h + 2):
        row = {"row": n}
        for ours, i in where.items():
            v = raw[i] if i < len(raw) else None
            row[ours] = personnel_text(v) if ours == "personnel" else _text(v)
        if any(row.get(c) for c in where):   # skip fully empty lines
            rows.append(row)
    return {"name": path.name, "columns": list(where), "rows": rows}


def label(row: dict) -> str:
    """How a row is named to you: by play number, with the sheet row when the play number repeats."""
    play = row.get("play") or "?"
    return f"Play {play} (row {row['row']})"
