"""Fetches an opponent's roster and stats from their athletics site and writes the same sheet you'd upload for Depth.

Most GLIAC schools run their site on SIDEARM Sports, so the roster page and the cumulative stats page look alike. This reads
those pages with plain code (no AI), joins stats to the roster by name, and saves data/football/depth/<opponent>.xlsx. What
a site doesn't show is left out and said plainly: offensive line starts are rarely published, and a depth chart often isn't.
If a page can't be read, the message says which one, so you can fix the address or upload the sheet by hand.
"""

import re
from datetime import date
from html.parser import HTMLParser

from . import depth, season

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
           "Accept": "text/html,application/xhtml+xml"}
TIMEOUT = 25


class FetchError(Exception):
    pass


class _Page(HTMLParser):
    """Collects every table (header cells + rows of cell text) and every SIDEARM roster card on a page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.cards = [], []
        self._table = self._row = self._cell = self._card = self._field = None
        self._depth = 0
        self._caption = ""
        self._recent = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "table":
            self._table = {"caption": self._recent, "head": [], "rows": []}
        elif self._table is not None and tag == "tr":
            self._row = []
        elif self._table is not None and tag in ("td", "th") and self._row is not None:
            self._cell = {"th": tag == "th", "text": ""}
        elif tag in ("h2", "h3", "h4", "caption"):
            self._recent = ""
            self._field = "heading"
        if "sidearm-roster-player" in cls.split() and tag in ("li", "div", "tr"):
            self._card = {"no": "", "name": "", "pos": ""}
            self.cards.append(self._card)
        if self._card is not None:
            if "jersey-number" in cls:
                self._field = "no"
            elif "player-name" in cls or "roster-player-name" in cls:
                self._field = "name"
            elif "player-position" in cls or "roster-player-position" in cls:
                self._field = "pos"

    def handle_data(self, data):
        t = data.strip()
        if not t:
            return
        if self._cell is not None:
            self._cell["text"] += (" " if self._cell["text"] else "") + t
        elif self._field == "heading":
            self._recent += (" " if self._recent else "") + t
        if self._card is not None and self._field in ("no", "name", "pos"):
            cur = self._card[self._field]
            self._card[self._field] = (cur + " " + t).strip() if cur and self._field != "no" else (cur or t)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if self._row and all(c["th"] for c in self._row) and not self._table["head"]:
                self._table["head"] = [c["text"] for c in self._row]
            elif self._row:
                self._table["rows"].append([c["text"] for c in self._row])
            self._row = None
        elif tag == "table" and self._table is not None:
            if not self._table["head"] and self._table["rows"]:   # headers written as plain cells
                self._table["head"], self._table["rows"] = self._table["rows"][0], self._table["rows"][1:]
            self.tables.append(self._table)
            self._table = None
        elif tag in ("h2", "h3", "h4", "caption"):
            self._field = None
        elif tag in ("span", "a", "div", "li") and self._field in ("no", "name", "pos"):
            self._field = None


def parse(html: str) -> _Page:
    p = _Page()
    p.feed(html)
    return p


def _key(name: str) -> str:
    n = name.strip()
    if "," in n:
        last, first = [x.strip() for x in n.split(",", 1)]
        n = f"{first} {last}"
    return re.sub(r"[^a-z ]", "", re.sub(r"\s+", " ", n.lower().replace("jr.", "").replace("sr.", ""))).strip()


def _clean_name(name: str) -> str:
    n = re.sub(r"^\s*#?\d+\s*", "", name).strip()
    if "," in n:
        last, first = [x.strip() for x in n.split(",", 1)]
        n = f"{first} {last}"
    return re.sub(r"\s+", " ", n)


def roster_players(page: _Page) -> list[dict]:
    out = []
    for t in page.tables:
        head = [h.upper().strip(". ") for h in t["head"]]
        name_i = next((i for i, h in enumerate(head) if h in ("NAME", "PLAYER", "FULL NAME")), None)
        pos_i = next((i for i, h in enumerate(head) if h in ("POS", "POSITION")), None)
        no_i = next((i for i, h in enumerate(head) if h in ("NO", "#", "NUM", "NUMBER", "JERSEY")), None)
        if name_i is None or pos_i is None:
            continue
        for r in t["rows"]:
            if len(r) > max(name_i, pos_i):
                out.append({"name": _clean_name(r[name_i]), "pos": r[pos_i].strip(), "no": (r[no_i].strip() if no_i is not None and no_i < len(r) else "")})
    for c in page.cards:   # SIDEARM's card-style roster
        if c["name"] and c["pos"]:
            out.append({"name": _clean_name(c["name"]), "pos": c["pos"].split()[0], "no": re.sub(r"\D", "", c["no"])})
    seen, uniq = set(), []
    for p in out:
        k = (_key(p["name"]), p["no"])
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def _int(v) -> int:
    m = re.search(r"\d+", str(v))
    return int(m.group()) if m else 0


def stat_lines(page: _Page) -> dict:
    """{player key: {"gs": int, "reps": int, "no": str}} from rushing, receiving and passing tables."""
    out = {}
    for t in page.tables:
        head = [h.upper().strip() for h in t["head"]]
        name_i = next((i for i, h in enumerate(head) if h in ("PLAYER", "NAME")), None)
        if name_i is None:
            for i, h in enumerate(head):   # SIDEARM puts the name under the first column
                if i == 0 and h not in ("NO", "#", "NO."):
                    name_i = i
        gs_i = next((i for i, h in enumerate(head) if h in ("GP-GS", "GS", "GP/GS")), None)
        rep_i = next((i for i, h in enumerate(head) if h in ("ATT", "CAR", "REC", "ATT-CMP-INT", "NO")), None)
        no_i = next((i for i, h in enumerate(head) if h in ("#", "NO", "NO.")), None)
        if name_i is None or (gs_i is None and rep_i is None):
            continue
        if rep_i is not None and rep_i == no_i:   # "No." was the jersey column, not a stat
            rep_i = next((i for i, h in enumerate(head) if h in ("ATT", "CAR", "REC", "ATT-CMP-INT")), None)
        for r in t["rows"]:
            if len(r) <= name_i or not re.search(r"[A-Za-z]", r[name_i]) or re.match(r"(?i)\s*(total|opponents?)", r[name_i]):
                continue
            k = _key(_clean_name(r[name_i]))
            d = out.setdefault(k, {"gs": 0, "reps": 0, "no": ""})
            if gs_i is not None and gs_i < len(r) and r[gs_i]:
                parts = re.findall(r"\d+", r[gs_i])
                d["gs"] = max(d["gs"], int(parts[-1]) if parts else 0)
            if rep_i is not None and rep_i < len(r):
                d["reps"] += _int(r[rep_i])
            if no_i is not None and no_i < len(r):
                d["no"] = d["no"] or r[no_i].strip()
    return out


def combine(roster: list[dict], stats: dict) -> list[list]:
    rows = []
    for p in roster:
        pos = depth.POSITIONS.get(re.sub(r"[^A-Z]", "", p["pos"].upper().split("/")[0]))
        if not pos:
            continue
        s = stats.get(_key(p["name"]))
        if s is None:   # last name + first initial, for "J. Smith" style stat names
            parts = _key(p["name"]).split()
            s = next((v for k, v in stats.items() if parts and k.split()[-1:] == parts[-1:] and k[:1] == parts[0][:1]), None)
        rows.append([p["pos"].split("/")[0].upper(), p["no"], p["name"], (s or {}).get("gs", 0), (s or {}).get("reps", 0), 999])
    return rows


def _get(url: str) -> str:
    import requests
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise FetchError(f"couldn't reach {url} ({type(e).__name__})")
    if r.status_code != 200:
        raise FetchError(f"{url} answered {r.status_code}")
    return r.text


def _first(base: str, paths: list[str], what: str, ok) -> tuple[_Page, str]:
    errors = []
    for p in paths:
        try:
            page = parse(_get(base.rstrip("/") + p))
        except FetchError as e:
            errors.append(str(e))
            continue
        if ok(page):
            return page, p
        errors.append(f"{base.rstrip('/')}{p} loaded but had no {what} table I could read")
    raise FetchError(f"{what}: " + "; ".join(errors))


def fetch(opponent: str, base: str | None = None, year: int | None = None) -> dict:
    """Fetch, join and save the opponent's sheet. Returns {"players": n, "with_stats": n, "notes": [...]}."""
    base = base or season.site_for(opponent)
    if not base:
        raise FetchError(f"I don't have a website for {opponent}. Add it under sites: in config/football.yaml.")
    year = year or date.today().year
    roster_page, _ = _first(base, [f"/sports/football/roster/{year}", f"/sports/football/roster/{year - 1}-{str(year)[2:]}",
                                   "/sports/football/roster"], "roster", lambda p: bool(roster_players(p)))
    stats_page, _ = _first(base, [f"/sports/football/stats/{year}", "/sports/football/stats"], "stats", lambda p: bool(stat_lines(p)))
    rows = combine(roster_players(roster_page), stat_lines(stats_page))
    if not rows:
        raise FetchError(f"{opponent}'s roster loaded but I found no QB, RB, WR, TE or OL on it.")
    with_stats = sum(1 for r in rows if r[3] or r[4])
    notes = []
    if not any(r[3] for r in rows if depth.POSITIONS.get(r[0]) == "OL"):
        notes.append("Their site doesn't show offensive line starts, so the OL is listed by number.")
    notes.append("Their depth chart isn't read from the site: players are ordered by reps, then starts.")
    depth.write_sheet(opponent, rows)
    return {"players": len(rows), "with_stats": with_stats, "notes": notes}
