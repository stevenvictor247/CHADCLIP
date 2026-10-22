"""Scribe's Coaching Notebook inside HQ: every "NB:" you send becomes a short dated entry under the right section.

The notebook lives in HQ's database on your PC (it holds the team's real calls, so it never goes into git).
Bring your existing notebook in once with Import, and download it any time as a Markdown file.
"""

import re
from datetime import date

from .. import db

# The sections of your 2026 Coaching Notebook (both tabs), in notebook order.
TABS = ("Terminology", "Field zones", "DL techniques and alignments", "Fronts", "Coverages", "Pressures and blitzes",
        "Technique by position", "Offensive concepts and beaters", "Formations", "Personnel", "Backfield sets",
        "Formation tags", "Motions", "Tagging film", "Scout cards", "Scouting reports", "Press box and charting",
        "Hudl", "Lessons learned", "General")
_DATED = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*[—–-]+\s*(.+)$")


def is_nb(text: str) -> bool:
    return bool(re.match(r"^\s*nb\s*[:\-]", text or "", re.I))


def strip_nb(text: str) -> str:
    return re.sub(r"^\s*nb\s*[:\-]\s*", "", text or "", flags=re.I).strip()


def tab_for(name: str) -> str:
    """Match a section name loosely (Formations tab sub-headings, plurals, case)."""
    n = (name or "").strip().lower()
    for t in TABS:
        if n == t.lower() or n.rstrip("s") == t.lower().rstrip("s"):
            return t
    for t in TABS:
        if t.lower() in n or (len(n) >= 4 and n in t.lower()):
            return t
    aliases = {"install": "Formations", "wr motion": "Motions", "te motion": "Motions", "technique": "Technique by position",
               "blitz": "Pressures and blitzes", "stunt": "Pressures and blitzes", "pressure": "Pressures and blitzes",
               "coverage": "Coverages", "front": "Fronts", "zone": "Field zones", "lesson": "Lessons learned",
               "charting": "Press box and charting", "card": "Scout cards", "tag": "Formation tags"}
    return next((t for k, t in aliases.items() if k in n), "General")


def short_date(day: str) -> str:
    if not day:
        return ""
    y, m, d = day.split("-")
    return f"{int(m)}/{int(d)}/{y[2:]}"


def shown(n: dict) -> str:
    return f"{short_date(n['day'])} — {n['entry']}" if n.get("day") else n["entry"]


def notes(include_replaced: bool = False) -> list[dict]:
    where = "" if include_replaced else "WHERE status = 'active'"
    return db.rows(f"SELECT id, day, tab, entry, status, source, created_at FROM football_notes {where} ORDER BY id")


def add(entry: str, tab: str, raw: str = "", source: str = "nb", day: str | None = None) -> int:
    return db.execute("INSERT INTO football_notes (day, tab, entry, raw, source, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                      day if day is not None else date.today().isoformat(), tab_for(tab), entry.strip(), raw,
                      source, db.now())


def replace(old_ids: list[int]) -> None:
    for i in old_ids:
        db.execute("UPDATE football_notes SET status = 'replaced' WHERE id = ?", int(i))


def search(query: str, limit: int = 20) -> list[dict]:
    words = [w for w in re.findall(r"[\w-]+", (query or "").lower()) if len(w) > 1]
    scored = []
    for n in notes():
        text = f"{n['tab']} {n['entry']}".lower()
        score = sum(text.count(w) for w in words)
        if score:
            scored.append((score, n))
    scored.sort(key=lambda x: (-x[0], -x[1]["id"]))
    return [n for _, n in scored[:limit]]


def import_markdown(text: str) -> int:
    """Bring in an exported notebook: "## Section" headings, then one entry per line, bullet or table row.
    Text under the "# Title" heading is skipped, so a downloaded notebook imports back cleanly.
    Lines that are already in the notebook are skipped, so importing the same file twice is harmless."""
    have = {(n["tab"], n["entry"].lower()) for n in notes()}
    tab, added, lines, intro = "General", 0, text.splitlines(), False
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        h = re.match(r"^(#{1,4})\s+(.+)$", s)
        if h:
            intro = len(h[1]) == 1   # the lines under the title ("Downloaded from Agent HQ...") aren't entries
            if len(h[1]) == 2 or (len(h[1]) > 2 and tab_for(h[2]) != "General"):
                tab = tab_for(h[2])
            continue
        if intro:
            continue
        if re.fullmatch(r"\|?[\s:|-]+\|?", s):
            continue   # a table's |---| line
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if s.startswith("|") and re.fullmatch(r"\|?[\s:|-]+\|?", nxt):
            continue   # a table's header row
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            cells = [c for c in cells if c]
            if not cells:
                continue
            s = cells[0] + (": " + " · ".join(cells[1:]) if len(cells) > 1 else "")
        s = re.sub(r"^([-*•]|\d+\.)\s+", "", s).strip()
        day = ""
        m = _DATED.match(s)
        if m:
            mo, d, y = int(m[1]), int(m[2]), int(m[3])
            y = y + 2000 if y < 100 else y
            try:
                day, s = date(y, mo, d).isoformat(), m[4].strip()
            except ValueError:
                pass
        if len(s) < 3 or (tab, s.lower()) in have:
            continue
        add(s, tab, raw=line, source="import", day=day)
        have.add((tab, s.lower()))
        added += 1
    return added


def export_markdown() -> str:
    out = ["# 2026 Coaching Notebook", f"Downloaded from Agent HQ on {date.today().isoformat()}.", ""]
    by_tab = {}
    for n in notes():
        by_tab.setdefault(n["tab"], []).append(n)
    for t in TABS:
        if t in by_tab:
            out.append(f"## {t}")
            out += [f"- {shown(n)}" for n in by_tab[t]]
            out.append("")
    return "\n".join(out)
