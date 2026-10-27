"""The scouting PDFs: Birds and Rabbits (one page of tell cards) and the Opponent Data report (several pages of tables).

Both are drawn with reportlab from the counts in tendencies.py. Wayne State green and gold, no logos (the W is never
redrawn). Every number is a count of the tags in the Hudl exports; the sentences are filled in from those counts.
"""

import re
from datetime import date
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from . import season

GREEN, GOLD, GOLD_TEXT = "#0C5449", "#FFCC33", "#B8860B"
INK, GREY, LINE, SHADE = "#111827", "#6b7280", "#d9dde2", "#f1f4f2"
W, H, M = 612, 792, 36
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    lines, cur = [], ""
    for word in str(text).split():
        trial = f"{cur} {word}".strip()
        if stringWidth(trial, font, size) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def game_info(opponent: str) -> dict:
    g = next((x for x in season.games() if x["opponent"] == opponent), None)
    if not g:
        return {}
    d = g["date"]
    return {"when": f"{DAYS[d.weekday()]} {MONTHS[d.month - 1]} {d.day}", "kickoff": g.get("kickoff"), "site": g.get("site"),
            "date": d}


def abbreviations(names: list[str]) -> list[str]:
    out = []
    tokens = [[w for w in re.split(r"[^A-Za-z0-9]+", n) if w and w.lower() not in ("at", "vs", "v", "the")] for n in names]
    common = set.intersection(*[{w.lower() for w in t} for t in tokens]) if len(tokens) > 1 else set()
    for t in tokens:
        words = [w for w in t if w.lower() not in common] or t
        ab = ("".join(w[0] for w in words) if len(words) > 1 else (words[0][:3] if words else "G")).upper()[:4]
        k = 2
        while ab in out:
            ab = f"{ab[:3]}{k}"
            k += 1
        out.append(ab)
    return out


def _fmt(v, nd=1) -> str:
    return "-" if v is None else (f"{v:.{nd}f}".rstrip("0").rstrip(".") if nd and abs(v - round(v)) < 1e-9 else f"{v:.{nd}f}")


class Page:
    """A canvas with the Wayne State look: green and gold bands, a title block, a running footer."""

    def __init__(self, path: Path, title: str, footer: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.c = canvas.Canvas(str(path), pagesize=(W, H))
        self.c.setTitle(title)
        self.footer, self.n = footer, 0
        self.y = H - M
        self.new_page(first=True)

    def col(self, hexcolor):
        self.c.setFillColor(HexColor(hexcolor))
        self.c.setStrokeColor(HexColor(hexcolor))

    def text(self, x, y, s, size=8, font="Helvetica", color=INK, align="l", spacing=0):
        c = self.c
        self.col(color)
        c.setFont(font, size)
        if spacing:
            t = c.beginText()
            width = stringWidth(s, font, size) + spacing * len(s)
            t.setTextOrigin(x - width / 2 if align == "c" else x - width if align == "r" else x, y)
            t.setFont(font, size)
            t.setCharSpace(spacing)
            t.textOut(s)
            t.setCharSpace(0)
            c.drawText(t)
        else:
            {"l": c.drawString, "r": c.drawRightString, "c": c.drawCentredString}[align](x, y, s)

    def bands(self, y, h=7):
        self.col(GREEN); self.c.rect(M, y, W - 2 * M, h, stroke=0, fill=1)
        self.col(GOLD); self.c.rect(M, y - 2.5, W - 2 * M, 2.5, stroke=0, fill=1)

    def new_page(self, first: bool = False):
        if not first:
            self.footer_line()
            self.c.showPage()
        self.n += 1
        self.bands(H - 24)
        self.y = H - 44

    def footer_line(self):
        self.col(LINE); self.c.line(M, 34, W - M, 34)
        self.text(M, 22, self.footer, 6.5, color=GREY)
        self.text(W - M, 22, f"Page {self.n}", 6.5, color=GREY, align="r")

    def need(self, h: float):
        if self.y - h < 46:
            self.new_page()

    def title_block(self, kicker, title, sub, line):
        y = H - 62
        self.text(W / 2, y, kicker, 7.5, "Helvetica-Bold", GREY, "c", spacing=1.5)
        size = 30
        while stringWidth(title, "Helvetica-Bold", size) > W - 2 * M - 20:
            size -= 2
        self.text(W / 2, y - 32, title, size, "Helvetica-Bold", GREEN, "c")
        self.text(W / 2, y - 48, sub, 8.5, "Helvetica-Bold", GOLD_TEXT, "c", spacing=2)
        self.text(W / 2, y - 68, line, 8, "Helvetica", INK, "c")
        self.col(LINE); self.c.line(M, y - 78, W - M, y - 78)
        self.y = y - 96

    def section(self, name: str, note: str = ""):
        self.need(60)
        self.y -= 6
        self.text(M, self.y, name.upper(), 10.5, "Helvetica-Bold", GREEN, spacing=1.6)
        if note:
            self.text(M + stringWidth(name.upper(), "Helvetica-Bold", 10.5) + 8 + len(name) * 1.6, self.y, note, 7, "Helvetica", GREY)
        self.col(GREEN); self.c.line(M, self.y - 5, W - M, self.y - 5)
        self.y -= 18

    def sub(self, name: str):
        self.need(40)
        self.text(M, self.y, name.upper(), 6.5, "Helvetica-Bold", GREY, spacing=1)
        self.y -= 8

    def para(self, s: str, size=8, color=INK, box=False):
        lines = _wrap(s, "Helvetica", size, W - 2 * M - (16 if box else 0))
        h = len(lines) * (size + 3) + (10 if box else 0)
        self.need(h + 4)
        if box:
            self.col("#fbf4de"); self.c.rect(M, self.y - h + size, W - 2 * M, h, stroke=0, fill=1)
            self.col(GOLD); self.c.rect(M, self.y - h + size, 2.5, h, stroke=0, fill=1)
        for ln in lines:
            self.text(M + (9 if box else 0), self.y - (4 if box else 0), ln, size, color=color)
            self.y -= size + 3
        self.y -= 8 if box else 5

    def table(self, headers: list[str], rows: list[list], widths: list[float], bold_last: bool = False,
              grey_cols: tuple = ()):
        """widths are fractions of the page width; the first column is left aligned, the rest right aligned."""
        total = W - 2 * M
        xs = [M]
        for w in widths:
            xs.append(xs[-1] + w * total)
        rh = 14
        self.need(rh * 2 + 4)

        def head():
            self.col(GREEN); self.c.rect(M, self.y - rh + 4, total, rh, stroke=0, fill=1)
            for i, hd in enumerate(headers):
                self.text(xs[i] + 4 if i == 0 else xs[i + 1] - 4, self.y - 6 + 4, hd.upper(), 6, "Helvetica-Bold", "#ffffff",
                          "l" if i == 0 else "r", spacing=0.4)
            self.y -= rh
        head()
        for n, row in enumerate(rows):
            if self.y - rh < 46:
                self.new_page()
                head()
            if n % 2:
                self.col(SHADE); self.c.rect(M, self.y - rh + 4, total, rh, stroke=0, fill=1)
            last = bold_last and n == len(rows) - 1
            for i, v in enumerate(row):
                font = "Helvetica-Bold" if (last or i == 0) else "Helvetica"
                color = GREY if i in grey_cols else INK
                s = str(v)
                while i == 0 and stringWidth(s, font, 7.5) > xs[1] - xs[0] - 8 and len(s) > 4:
                    s = s[:-2].rstrip() + "…"
                self.text(xs[i] + 4 if i == 0 else xs[i + 1] - 4, self.y - 6 + 4, s, 7.5, font, color, "l" if i == 0 else "r")
            self.y -= rh
        self.col(LINE); self.c.line(M, self.y + 4, W - M, self.y + 4)
        self.y -= 10

    def bar(self, label: str, pct: float, right: str, width: float = 150):
        """A labelled run-rate bar: green for the share of runs, gold for passes."""
        self.need(14)
        self.text(M, self.y, label, 7.5, "Helvetica-Bold")
        x = M + 120
        self.col("#e5e7eb"); self.c.rect(x, self.y - 2, width, 8, stroke=0, fill=1)
        self.col(GREEN); self.c.rect(x, self.y - 2, width * max(0, min(100, pct)) / 100, 8, stroke=0, fill=1)
        self.text(x + width + 8, self.y, right, 7.5, color=GREY)
        self.y -= 14

    def save(self):
        self.footer_line()
        self.c.save()


# ---------------------------------------------------------------- Birds and Rabbits

TE_WORD = {0: "no tight end", 1: "one tight end", 2: "two tight ends", 3: "three tight ends"}
BACK_WORD = {"GUN STRONG": "Shotgun, back set to the strong side", "GUN WEAK": "Shotgun, back set to the weak side",
             "EMPTY": "No back beside the quarterback", "UNDER CENTER": "Quarterback under center"}
ZONE_WORD = {"Low red zone (12 and in)": "Inside the opponent 12", "Red zone (20 to 13)": "From the opponent 20 to the 13",
             "High red zone (35 to 21)": "From the opponent 35 to the 21"}


def _describe_one(feature: str, value: str) -> str:
    v = value.strip()
    if feature == "Personnel":
        m = re.match(r"(\d)(\d) pers", v, re.I) or re.match(r"(\d) pers", v, re.I)
        if m:
            rb = int(m.group(1)) if len(m.groups()) == 1 else int(m.group(1))
            te = int(m.group(2)) if len(m.groups()) == 2 else 0
            wr = max(0, 5 - rb - te)
            return f"{rb} back{'s' if rb != 1 else ''}, {TE_WORD.get(te, f'{te} tight ends')}, {wr} receiver{'s' if wr != 1 else ''}."
    if feature == "Backfield":
        return BACK_WORD.get(v.upper(), f"Backfield: {v.title()}.") + ("." if v.upper() in BACK_WORD else "")
    if feature == "Field zone":
        return ZONE_WORD.get(v, v) + "."
    if feature == "Hash":
        return {"Left hash": "Ball on the left hash.", "Right hash": "Ball on the right hash.",
                "Middle of the field": "Ball in the middle of the field."}.get(v, v + ".")
    if feature == "Down and distance":
        return v[0].upper() + v[1:] + "."
    if feature == "Formation":
        return f"{v.title()} formation."
    if feature == "Formation tag":
        return f"Tagged {v.title()}."
    if feature == "Motion":
        return f"Motion: {v.title()}."
    return v.title() + "."


def describe(t: dict) -> str:
    fa, fb = (t["feature"].split(" + ") + [None])[:2]
    va, vb = (t["value"].split(" + ") + [None])[:2]
    parts = [_describe_one(fa, va)]
    if fb and vb:
        parts.append(_describe_one(fb, vb))
    return " ".join(parts)


def tell_title(t: dict) -> str:
    return t["value"].upper().replace(" PERS", " PERSONNEL")


def insight(t: dict, want: str) -> str:
    bits = []
    n, hits = t["plays"], t["hits"]
    if hits == n and len(t.get("games", [])) > 1:
        bits.append(f"Every snap was a {want} in all {len(t['games'])} games.")
    elif len(t.get("games", [])) > 1:
        miss = [g for g in t["games"] if g["hits"] < g["n"]]
        if miss and len(miss) < len(t["games"]):
            bits.append(f"{len(t['games']) - len(miss)} of {len(t['games'])} games it was clean.")
    if t.get("median_gain") is not None:
        mg = t["median_gain"]
        bits.append(f"Median gain {_fmt(mg)} yard{'' if abs(mg) == 1 else 's'}.")
    if n < 10:
        bits.append("Thin sample.")
    return " ".join(bits)


def _card(p: Page, x, y, w, h, rank, t, want, color, text_color):
    c = p.c
    p.col("#ffffff"); c.rect(x, y - h, w, h, stroke=0, fill=1)
    p.col(LINE); c.rect(x, y - h, w, h, stroke=1, fill=0)
    p.col(color); c.rect(x, y - h, 3.5, h, stroke=0, fill=1)
    inner = w - 20
    p.text(x + 12, y - 18, str(rank), 11, "Helvetica-Bold", "#9ca3af")
    ty = y - 18
    for line in _wrap(tell_title(t), "Helvetica-Bold", 10.5, inner - 14)[:2]:
        p.text(x + 26, ty, line, 10.5, "Helvetica-Bold", INK)
        ty -= 12.5
    ty -= 0
    for line in _wrap(describe(t), "Helvetica", 7.2, inner)[:3]:
        p.text(x + 12, ty, line, 7.2, color=GREY)
        ty -= 9
    ty -= 8
    word = "runs" if want == "run" else "passes"
    p.text(x + 12, ty, f"{t['hits']} {word} in {t['plays']}  ·  {round(100 * t['share'])}%", 11, "Helvetica-Bold", text_color)
    ty -= 14
    ab = abbreviations([g["game"] for g in t.get("games", [])])
    row = "     ".join(f"{a} {g['hits']}/{g['n']}" for a, g in zip(ab, t.get("games", [])))
    for line in _wrap(row, "Helvetica", 6.3, inner)[:2]:
        p.text(x + 12, ty, line, 6.3, color=GREY)
        ty -= 8
    ty -= 6
    for line in _wrap(insight(t, want), "Helvetica", 7.4, inner)[:5]:
        p.text(x + 12, ty, line, 7.4, color=INK)
        ty -= 9.5


def birds_rabbits_pdf(a: dict, opponent: str, path: Path, today: date | None = None) -> Path:
    today = today or date.today()
    info = game_info(opponent)
    p = Page(path, f"{opponent} Birds and Rabbits", "WAYNE STATE WARRIORS   ·   WAYNE.EDU")
    base_r = round(a["base_run_pct"], 1)
    bits = [info.get("when"), info.get("kickoff"), f"{a['plays']} SNAPS", f"{len(a['games'])} GAME{'S' if len(a['games']) != 1 else ''}"]
    sub = "  ·  ".join(b for b in bits if b) + f"   BASE: {_fmt(base_r)}% RABBIT / {_fmt(100 - base_r)}% BIRD"
    p.title_block(f"WAYNE STATE FOOTBALL  ·  {opponent.upper()}", "BIRDS & RABBITS", "PRE-SNAP  TELLS", sub)
    cw = (W - 2 * M - 2 * 12) / 3
    ch = 150
    for want, name, small, color, tcol, key in (("run", "RABBITS", "run tells", GREEN, GREEN, "run_tells"),
                                                ("pass", "BIRDS", "pass tells", GOLD, GOLD_TEXT, "pass_tells")):
        p.text(M, p.y, name, 13, "Helvetica-Bold", tcol, spacing=2.5)
        p.text(M + stringWidth(name, "Helvetica-Bold", 13) + len(name) * 2.5 + 8, p.y, small, 8, "Helvetica-Oblique", GREY)
        p.col(tcol); p.c.line(M, p.y - 6, W - M, p.y - 6)
        p.y -= 16
        tells = a[key]
        if not tells:
            p.text(M, p.y - 8, f"No {want} tell is strong enough yet: a tell needs 5+ snaps and a 70%+ lean.", 8, color=GREY)
        for i, t in enumerate(tells[:3]):
            _card(p, M + i * (cw + 12), p.y, cw, ch, i + 1, t, want, color, tcol)
        p.y -= ch + 30
    p.para("How to read it: a tell is a pre-snap look that went the same way at least 70% of the time over at least 5 snaps, "
           "and is clearly more than they do anyway. Each line under a tell shows hits/snaps in each game. Every number is a "
           "count of your Hudl tags.", 6.8, GREY)
    notes = []
    if a.get("skipped"):
        notes.append(f"{a['skipped']} dead-ball rows (penalties, timeouts) left out.")
    if notes:
        p.para(" ".join(notes), 6.8, GREY)
    p.save()
    return path


# ---------------------------------------------------------------- Opponent data

def _fmt_pct(v) -> str:
    return f"{v:.1f}%"


def data_pdf(a: dict, opponent: str, path: Path, today: date | None = None) -> Path:
    today = today or date.today()
    info = game_info(opponent)
    games = a["game_names"]
    ab = abbreviations(games)
    p = Page(path, f"{opponent} Offensive Data", f"{opponent}  ·  Offensive Data")
    bits = [info.get("when"), info.get("kickoff"), info.get("site")]
    p.title_block("WAYNE STATE FOOTBALL  ·  OPPONENT DATA", opponent.upper(), "OFFENSE", "  ·  ".join(b for b in bits if b) or " ")

    o = a["overall"]
    p.section("Sample")
    p.para(f"{len(games)} Hudl file{'s' if len(games) != 1 else ''}, one game each. {a['plays']} live snaps "
           f"({a['run']} run, {a['pass']} pass)" + (f", {a['skipped']} dead-ball rows excluded." if a["skipped"] else "."), 8, box=True)
    if a["no_down"]:
        p.para(f"{a['no_down']} snaps have no down tagged, so they are left out of the down tables.", 7.5, GREY)

    p.section("Game by game")
    rows = [[g["label"], g["snaps"], g["run"], _fmt_pct(g["run_pct"]), _fmt(g["avg"]), _fmt(g["med"]), g["no_form"]]
            for g in a["games"]]
    if len(a["games"]) > 1:
        rows.append(["All games", o["snaps"], o["run"], _fmt_pct(o["run_pct"]), _fmt(o["avg"]), _fmt(o["med"]),
                     sum(g["no_form"] for g in a["games"])])
    p.table(["Game", "Snaps", "Run", "Run %", "Avg", "Med", "No formation"], rows, [0.34, 0.1, 0.1, 0.12, 0.1, 0.1, 0.14],
            bold_last=len(a["games"]) > 1)

    p.sub("Run rate by down, per game (snaps in grey)")
    hdr = ["Down"] + ab + ["All"]
    rows = []
    for d in a["by_down"]:
        if not d["all"]["snaps"]:
            continue
        rows.append([{1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}[d["down"]]] +
                    [f"{_fmt_pct(g['run_pct'])} ({g['snaps']})" if g["snaps"] else "-" for g in d["by_game"]] +
                    [f"{_fmt_pct(d['all']['run_pct'])} ({d['all']['snaps']})"])
    if rows:
        k = len(hdr) - 1
        p.table(hdr, rows, [0.12] + [0.88 / k] * k)

    if a["early_late"]:
        p.sub("Run rate, first half of snaps vs second (split at the middle of each game)")
        p.table(["Game", "Early snaps", "Early run %", "Late snaps", "Late run %", "Change"],
                [[e["game"], e["early_n"], _fmt_pct(e["early"]), e["late_n"], _fmt_pct(e["late"]), f"{e['late'] - e['early']:+.1f}"]
                 for e in a["early_late"]], [0.3, 0.14, 0.14, 0.14, 0.14, 0.14])

    st = a["stat_tables"]

    def stat(name: str, title: str, label: str):
        rows = st.get(name) or []
        if not rows:
            return
        p.section(title)
        multi = len(ab) > 1
        hdr = [label, "Snaps", "Run %", "Avg", "Med"] + (ab if multi else [])
        body = [[r["label"], r["snaps"], _fmt_pct(r["run_pct"]), _fmt(r["avg"]), _fmt(r["med"])] +
                (r["by_game"] if multi else []) for r in rows]
        widths = [0.3, 0.1, 0.12, 0.09, 0.09] + [0.3 / len(ab)] * len(ab) if multi else [0.4, 0.15, 0.15, 0.15, 0.15]
        p.table(hdr, body, widths)

    stat("Down and distance", "Down and distance", "Situation")
    stat("Distance to go", "By distance to go", "To go")
    stat("Personnel", "Personnel", "Personnel")
    stat("Backfield", "Backfield", "Backfield")
    stat("Formation", "Formation, exact tag", "Formation")
    stat("Formation tag", "Formation modifiers", "Tag")
    stat("Hash", "Hash", "Hash")
    stat("Field zone", "Field zone", "Zone")
    stat("Motion", "Motion used twice or more", "Motion")

    for key, title in (("run_concepts", "Run concepts (3+ carries)"), ("pass_concepts", "Pass concepts (3+ throws)")):
        if a[key]:
            p.section(title)
            p.table(["Concept", "N", "Avg", "Med", "Long"],
                    [[r["label"], r["n"], _fmt(r["avg"]), _fmt(r["med"]), r["long"] if r["long"] is not None else "-"]
                     for r in a[key]], [0.4, 0.15, 0.15, 0.15, 0.15])

    ex = a["explosive"]
    p.section("Explosive plays", "runs 12+, passes 16+")
    p.para(f"{ex['n']} of {a['plays']} snaps ({ex['run']} runs, {ex['pass']} passes)"
           + (". By game: " + ", ".join(f"{x} {n}" for x, n in zip(ab, ex["by_game"])) + "." if len(ab) > 1 else "."), 8)

    if a["sacks"]:
        p.section(f"Negative pass plays ({len(a['sacks'])})")
        p.table(["Game", "Down", "Formation", "Backfield", "Call", "Yds"],
                [[s["game"], s["down"], s["form"] or "-", s["back"] or "-", s["protection"] or "-",
                  s["gain"] if s["gain"] is not None else "-"] for s in a["sacks"]], [0.2, 0.1, 0.25, 0.2, 0.17, 0.08])

    p.section("Tells")
    for title, key in (("Rabbits (run tells)", "run_tells"), ("Birds (pass tells)", "pass_tells")):
        p.sub(title)
        if not a[key]:
            p.para("None strong enough (5+ snaps and a 70%+ lean).", 7.5, GREY)
        for t in a[key]:
            p.para(f"{tell_title(t)}: {t['hits']} of {t['plays']} ({round(100 * t['share'])}%). {describe(t)}", 7.8)
    p.save()
    return path
