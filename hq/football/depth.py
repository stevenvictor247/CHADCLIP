"""Depth: the opponent's offensive personnel sheet, made from the depth chart and stats you upload.

Upload one .xlsx or .csv per opponent: a row per player with POS, NO, NAME, and any of GS (starts), carries/attempts/
catches (REPS), and DEPTH (depth chart order). Above the header you can add rows like LAST LINE: 73 67 65 72 58,
RECORD: 2-4 (0-2), KICKOFF: 6:00 PM ET, SITE: Tom Adams Field, Detroit, GAMES: 6. Players are listed by who gets the
most reps (stats first, then starts, then the depth chart), with their starts next to the name. Plain sorting, no AI.
The sheet is one landscape page in Wayne State green and gold. It never draws a logo.
"""

import csv
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from ..config import FOOTBALL_DATA
from . import season
from .reports import safe_name

DIR = FOOTBALL_DATA / "depth"
STATE = FOOTBALL_DATA / "depth_state.json"
DEPTH_HOUR = int(os.getenv("HQ_DEPTH_HOUR", "").strip() or "8") % 24   # Monday, local time
TYPES = (".xlsx", ".xlsm", ".csv")
GREEN, GOLD, GOLD_TEXT = "#0C5449", "#FFCC33", "#C99712"
GROUPS = [("QB", "QB"), ("RB", "RB"), ("WR", "WR"), ("TE", "TE"), ("OL", "OL")]
POSITIONS = {"QB": "QB", "RB": "RB", "HB": "RB", "FB": "RB", "TB": "RB", "WR": "WR", "SE": "WR", "FL": "WR", "TE": "TE",
             "OL": "OL", "OT": "OL", "OG": "OL", "LT": "OL", "LG": "OL", "C": "OL", "RG": "OL", "RT": "OL", "T": "OL", "G": "OL"}
NONE_LABEL = {"QB": "NO ATTEMPTS RECORDED", "RB": "NO CARRIES RECORDED", "WR": "NO CATCHES RECORDED"}
COLUMNS = {"pos": ("POS", "POSITION"), "num": ("NO", "NO.", "#", "NUM", "NUMBER", "JERSEY"), "name": ("NAME", "PLAYER"),
           "gs": ("GS", "STARTS", "ST", "GAMES STARTED"),
           "reps": ("REPS", "SNAPS", "ATT", "ATTEMPTS", "CAR", "CARRIES", "REC", "CATCHES", "RUSH ATT", "PASS ATT"),
           "order": ("DEPTH", "DEPTH ORDER", "RANK", "ORDER")}
META = ("LAST LINE", "RECORD", "KICKOFF", "SITE", "GAMES")


class DepthError(Exception):
    pass


def _up(v) -> str:
    return re.sub(r"\s+", " ", str(v if v is not None else "")).strip().upper()


def _num(v) -> float:
    m = re.search(r"-?\d+(\.\d+)?", str(v if v is not None else "").replace(",", ""))
    return float(m.group()) if m else 0.0


def _rows(path: Path) -> list[list]:
    if path.suffix.lower() == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as f:
            return [r for r in csv.reader(f)]
    import openpyxl
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:
        raise DepthError(f"I couldn't open {path.name}. Save it again as .xlsx or .csv.")
    return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]


def read(path: Path) -> dict:
    """{"players": [...], "meta": {...}} from an uploaded sheet."""
    rows = _rows(path)
    meta, head, cols = {}, None, {}
    for i, r in enumerate(rows):
        cells = [_up(c) for c in r]
        found = {k: [j for j, c in enumerate(cells) if c in names] for k, names in COLUMNS.items()}
        if found["name"] and found["pos"]:
            head, cols = i, found
            break
        for j, c in enumerate(cells):   # "LAST LINE: 73 67 65" in one cell, or "LAST LINE" then the value in the next
            for key in META:
                if c.startswith(key):
                    rest = str(r[j])[len(key):].lstrip(" :-").strip()
                    nxt = next((str(x).strip() for x in r[j + 1:] if x not in (None, "")), "")
                    if rest or nxt:
                        meta[key] = rest or nxt
    if head is None:
        raise DepthError("I couldn't find the header row. It needs at least POS and NAME columns.")
    players = []
    for r in rows[head + 1:]:
        get = lambda k: next((r[j] for j in cols[k] if j < len(r) and r[j] not in (None, "")), None)
        name = str(get("name") or "").strip()
        pos = POSITIONS.get(_up(get("pos")))
        if not name or not pos:
            continue   # defense, special teams, blank rows
        gs = get("gs")
        if gs is not None and re.fullmatch(r"\s*\d+\s*[-/]\s*\d+\s*", str(gs)):   # "GP-GS" like 6-5
            gs = re.split(r"[-/]", str(gs))[1]
        raw = get("num")
        num = "" if raw is None else str(raw).strip()
        players.append({"pos": pos, "slot": _up(get("pos")), "num": re.sub(r"\.0$", "", num), "name": name,
                        "starts": int(_num(gs)), "reps": sum(_num(r[j]) for j in cols["reps"] if j < len(r)),
                        "order": _num(get("order")) if get("order") is not None else 999,
                        "has_starts": bool(cols["gs"])})
    if not players:
        raise DepthError("I found the header but no QB, RB, WR, TE or OL rows under it.")
    return {"players": players, "meta": meta}


def _numkey(p) -> tuple:
    d = re.sub(r"\D", "", p["num"])
    return (int(d) if d else 999, p["name"])


def layout(players: list[dict]) -> dict:
    """The columns of the sheet: for each position, a list of ("p", player) and ("label", text) in order."""
    cols = {}
    for group, _ in GROUPS:
        ps = [p for p in players if p["pos"] == group]
        has_starts = any(p["has_starts"] for p in ps)
        ranked = sorted(ps, key=lambda p: (-p["reps"], -p["starts"], p["order"], _numkey(p)))
        out = []
        if group == "OL":
            main = sorted([p for p in ps if p["starts"] > 0], key=lambda p: (-p["starts"], p["order"], _numkey(p)))
            out = [("p", p) for p in main]
            rest = sorted([p for p in ps if p["starts"] <= 0], key=_numkey)
            cols["OL"] = out + ([("label", "NO STARTS — BY NUMBER")] if main and rest and has_starts else [])
            cols["OL CONT."] = [("p", p) for p in (rest if main or has_starts else sorted(ps, key=_numkey))]
            if not has_starts:
                cols["OL"] = [("p", p) for p in sorted(ps, key=lambda p: (p["order"], _numkey(p)))[:11]]
                cols["OL CONT."] = [("p", p) for p in sorted(ps, key=lambda p: (p["order"], _numkey(p)))[11:]]
            continue
        if group == "QB":
            main = [p for p in ranked if p["starts"] > 0 or p["reps"] > 0]
            tail = sorted([p for p in ranked if p not in main], key=_numkey)
            out = [("p", p) for p in main] + ([("label", NONE_LABEL["QB"])] if main and tail else []) + [("p", p) for p in tail]
        elif group == "TE":
            main = [p for p in ranked if p["starts"] > 0]
            tail = [p for p in ranked if p["starts"] <= 0]
            out = [("p", p) for p in main] + ([("label", "NO STARTS")] if main and tail and has_starts else []) + [("p", p) for p in tail]
        else:
            main = [p for p in ranked if p["starts"] > 0] if has_starts else [p for p in ranked if p["reps"] > 0]
            nostart = [p for p in ranked if p not in main and p["reps"] > 0]
            none = sorted([p for p in ranked if p not in main and p["reps"] <= 0], key=_numkey)
            out = [("p", p) for p in main]
            if nostart:
                out += ([("label", "NO STARTS")] if main and has_starts else []) + [("p", p) for p in nostart]
            if none:
                out += [("label", NONE_LABEL[group])] + [("p", p) for p in none]
        cols[group] = out
    return cols


def _subline(opponent: str, meta: dict) -> str:
    g = next((x for x in season.games() if x["opponent"] == opponent), None)
    parts = []
    if g:
        parts.append(g["date"].strftime("%a %b %-d").upper() if hasattr(g["date"], "strftime") else str(g["date"]))
    kick = meta.get("KICKOFF") or (g or {}).get("kickoff")
    if kick:
        parts.append(str(kick).upper())
    site = meta.get("SITE") or ("TOM ADAMS FIELD, DETROIT" if g and (g.get("site") or "home").lower() == "home" else "")
    if site:
        parts.append(site.upper())
    line = "  ·  ".join(parts)
    if meta.get("RECORD"):
        line += f"     {meta['RECORD'].upper()}"
    if meta.get("LAST LINE"):
        nums = re.findall(r"\d+", meta["LAST LINE"])
        if nums:
            line += "     LAST LINE, LT to RT: " + " · ".join(nums)
    return line.strip()


def build_pdf(opponent: str, data: dict, path: Path, today: date | None = None) -> Path:
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas

    today = today or date.today()
    cols = layout(data["players"])
    meta = data["meta"]
    W, H = 792, 612
    c = canvas.Canvas(str(path), pagesize=(W, H))
    c.setTitle(f"{opponent} Offensive Personnel")
    green, gold, gtext = HexColor(GREEN), HexColor(GOLD), HexColor(GOLD_TEXT)
    grey, line = HexColor("#6b7280"), HexColor("#d9dde2")
    M = 24

    def band(y):
        c.setFillColor(green); c.rect(M, y, W - 2 * M, 7, stroke=0, fill=1)
        c.setFillColor(gold); c.rect(M, y + 7 if y > 100 else y - 2.5, W - 2 * M, 2.5, stroke=0, fill=1)
    band(H - 38)
    c.setFillColor(grey); c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(W / 2, H - 58, "WAYNE STATE FOOTBALL   ·   OPPONENT SCOUTING REPORT")
    size = 34
    while c.stringWidth(opponent.upper(), "Helvetica-Bold", size) > 520:
        size -= 2
    c.setFillColor(green); c.setFont("Helvetica-Bold", size); c.drawCentredString(W / 2, H - 92, opponent.upper())
    c.setFillColor(gtext); c.setFont("Helvetica-Bold", 10); c.drawCentredString(W / 2, H - 112, "OFFENSIVE PERSONNEL")
    c.setFillColor(HexColor("#111827")); c.setFont("Helvetica", 8)
    c.drawCentredString(W / 2, H - 134, _subline(opponent, meta))
    c.setStrokeColor(line); c.line(M, H - 144, W - M, H - 144)

    names = list(cols)
    cw = (W - 2 * M) / len(names)
    top = H - 152
    foot = 46
    rows = max([len(v) for v in cols.values()] + [1])
    rh = min(15.5, (top - 24 - foot - 20) / rows)
    fs = max(6.5, min(9.5, rh - 5))
    c.setStrokeColor(line)
    for i, name in enumerate(names):
        x = M + i * cw
        c.setFillColor(green); c.rect(x, top - 22, cw, 22, stroke=0, fill=1)
        c.setFillColor(HexColor("#ffffff")); c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(x + cw / 2, top - 15, name)
        y = top - 22
        shade = 0
        for kind, item in cols[name]:
            y -= rh
            if kind == "label":
                c.setFillColor(grey); c.setFont("Helvetica-Bold", 6)
                c.drawCentredString(x + cw / 2, y + rh / 2 - 2, item)
                c.setDash(2, 2); c.line(x + 6, y + rh - 1, x + cw - 6, y + rh - 1); c.setDash()
                shade = 0
                continue
            if shade % 2:
                c.setFillColor(HexColor("#f1f4f2")); c.rect(x, y, cw, rh, stroke=0, fill=1)
            shade += 1
            ty = y + (rh - fs) / 2 + 0.5
            c.setFillColor(green); c.setFont("Helvetica-Bold", fs + 1.5)
            c.drawRightString(x + 26, ty, item["num"])
            tag = ""
            if item["starts"] and item["has_starts"]:
                tag = f"{item['slot']} · {item['starts']}" if name == "OL" and item["slot"] != "OL" else f"{item['starts']} ST"
            room = cw - 31 - 4 - (c.stringWidth(tag, "Helvetica-Bold", 5.5) + 4 if tag else 0)
            nm, nfs = item["name"], fs
            while c.stringWidth(nm, "Helvetica-Bold", nfs) > room and nfs > 6.5:
                nfs -= 0.5
            while c.stringWidth(nm, "Helvetica-Bold", nfs) > room and len(nm) > 4:
                nm = nm[:-2].rstrip() + "…" if not nm.endswith("…") else nm[:-2] + "…"
            c.setFillColor(HexColor("#111827")); c.setFont("Helvetica-Bold", nfs)
            c.drawString(x + 31, ty, nm)
            if tag:
                c.setFillColor(grey); c.setFont("Helvetica-Bold", 5.5)
                c.drawString(x + 31 + c.stringWidth(nm, "Helvetica-Bold", nfs) + 3, ty + 1, tag)
        c.setStrokeColor(line); c.line(x, top - 22, x, foot + 8)
    c.line(M + len(names) * cw, top - 22, M + len(names) * cw, foot + 8)
    c.line(M, foot + 8, W - M, foot + 8)
    band(foot - 14)
    c.setFillColor(grey); c.setFont("Helvetica", 7)
    c.drawString(M, foot - 28, "WAYNE STATE WARRIORS   ·   WAYNE.EDU")
    games = f", {meta['GAMES']} games" if meta.get("GAMES") else ""
    c.drawRightString(W - M, foot - 28, f"Compiled {today.strftime('%a %b %-d, %Y')}   ·   ST = starts{games}")
    c.save()
    return path


def input_for(opponent: str) -> Path | None:
    """The newest uploaded sheet for an opponent."""
    try:
        found = [p for p in DIR.iterdir() if p.is_file() and p.suffix.lower() in TYPES
                 and season.find_opponent(p.stem) == opponent]
    except OSError:
        return None
    return max(found, key=lambda p: p.stat().st_mtime, default=None)


def save_upload(filename: str, data: bytes, opponent: str | None = None) -> dict:
    name = Path(filename or "depth.xlsx").name
    suffix = Path(name).suffix.lower()
    if suffix not in TYPES:
        raise DepthError("Send the depth chart and stats as an Excel (.xlsx) or CSV file.")
    opp = opponent or season.find_opponent(Path(name).stem)
    if not opp:
        raise DepthError("I couldn't tell which opponent it's for. Pick the opponent, or put their name in the file name.")
    DIR.mkdir(parents=True, exist_ok=True)
    dest = DIR / f"{safe_name(opp)}{suffix}"
    dest.write_bytes(data)
    try:
        info = read(dest)
    except DepthError:
        dest.unlink(missing_ok=True)
        raise
    for other in DIR.glob(f"{safe_name(opp)}.*"):   # one sheet per opponent: the newest wins
        if other != dest:
            other.unlink(missing_ok=True)
    return {"opponent": opp, "players": len(info["players"])}


def run_if_due(now: datetime | None = None) -> str | None:
    """Monday morning (or later that week if HQ was off): queue this week's sheet, or ask for what's missing. Once a week."""
    import json
    from .. import db, relay
    now = now or datetime.now()
    if now.weekday() > 2 or now.hour < DEPTH_HOUR and now.weekday() == 0:
        return None
    monday = (now.date() - timedelta(days=now.weekday())).isoformat()
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if state.get("week") == monday:
        return None
    g = season.current_game(now.date())
    if not g:
        return None
    state["week"] = monday
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state), encoding="utf-8")
    if input_for(g["opponent"]):
        db.create_task("Depth", f"Personnel sheet: {g['opponent']}", {"opponent": g["opponent"]}, created_by="Schedule")
        return "queued"
    relay.notify(f"📋 Depth\nI need the {g['opponent']} depth chart and stats to make this week's personnel sheet. "
                 "Upload them in the Warrior Village tab.")
    return "asked"


def listing() -> list[dict]:
    out = []
    for g in season.games():
        p = input_for(g["opponent"])
        out.append({"opponent": g["opponent"], "date": g["date"].isoformat(), "uploaded": bool(p),
                    "when": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="minutes") if p else None})
    return out
