"""Tells' counting: tendencies from a tagged sheet, and the biggest run and pass tells (Birds and Rabbits).

Everything here is plain counting of your tags. No AI touches the numbers, so nothing can be made up: every tell
shows its count and sample size, and a tell needs enough plays and a clear lean before it's listed.
"""

import math
from collections import Counter

from .sheet import number

MIN_PLAYS = 5       # a tell needs at least this many plays
MIN_SHARE = 0.70    # and at least this share run (or pass)
Z = 1.28            # how sure we want to be (80%) that the lean is real and not a small-sample fluke
RUN_RESULTS = ("RUSH",)
PASS_RESULTS = ("COMPLETE", "INCOMPLETE", "SACK", "INTERCEPTION", "SCRAMBLE")


def _up(v) -> str:
    return " ".join(str(v or "").upper().split())


def kind(row: dict) -> str | None:
    """run, pass, or None for snaps that aren't either (penalties, timeouts, kneels with no type)."""
    t = _up(row.get("play_type"))
    if t in ("RUN", "PASS"):
        return t.lower()
    first = _up(row.get("result")).split(",")[0].strip()
    if first in RUN_RESULTS:
        return "run"
    if first in PASS_RESULTS:
        return "pass"
    return None


def down_distance(row: dict) -> str | None:
    dn, dist = number(row.get("dn")), number(row.get("dist"))
    if dn == 1:
        return "1st down"
    if dn in (2, 3, 4) and dist is not None and dist > 0:
        n = {2: "2nd", 3: "3rd", 4: "4th"}[dn]
        return f"{n} & {'long (7+)' if dist >= 7 else 'medium (4-6)' if dist >= 4 else 'short (1-3)'}"
    return None   # DN 0 or blank: down not tagged


def field_zone(row: dict) -> str | None:
    """Your zones: low red zone = the 12 and in, red zone = the 20 to the 12, high red zone = their 35 to the 20."""
    y = number(row.get("yard"))
    if y is None or y <= 0:
        return None
    if y <= 12:
        return "Low red zone (12 and in)"
    if y <= 20:
        return "Red zone (20 to 13)"
    if y <= 35:
        return "High red zone (35 to 21)"
    return None


def hash_mark(row: dict) -> str | None:
    return {"L": "Left hash", "R": "Right hash", "M": "Middle of the field"}.get(_up(row.get("hash"))[:1] or "-")


def _tags(row: dict) -> list[str]:
    return [t.strip() for t in _up(row.get("tag")).replace("/", ",").split(",") if t.strip()]


SINGLE = {
    "Personnel": lambda r: f"{_up(r.get('personnel'))} pers" if r.get("personnel") else None,
    "Formation": lambda r: _up(r.get("form")) or None,
    "Backfield": lambda r: _up(r.get("backfield")) or None,
    "Formation tag": _tags,
    "Hash": hash_mark,
    "Down and distance": down_distance,
    "Field zone": field_zone,
    "Motion": lambda r: _up(r.get("motion")) or None,
}
PAIRS = [("Personnel", "Backfield"), ("Formation", "Backfield"), ("Personnel", "Formation"),
         ("Down and distance", "Personnel"), ("Formation", "Hash")]


def _values(feature: str, row: dict) -> list[str]:
    v = SINGLE[feature](row)
    return v if isinstance(v, list) else ([v] if v else [])


def wilson_low(hits: int, n: int, z: float = Z) -> float:
    if n == 0:
        return 0.0
    p = hits / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def _groups(plays: list[dict]) -> dict:
    """(feature label, value label) -> list of play indexes."""
    groups = {}
    for i, r in enumerate(plays):
        for f in SINGLE:
            for v in _values(f, r):
                groups.setdefault((f, v), []).append(i)
        for a, b in PAIRS:
            for va in _values(a, r):
                for vb in _values(b, r):
                    groups.setdefault((f"{a} + {b}", f"{va} + {vb}"), []).append(i)
    return groups


def tells(plays: list[dict], want: str, how_many: int = 3, min_plays: int = MIN_PLAYS) -> list[dict]:
    """The biggest `want` ("run" or "pass") tells: strong leans with enough plays, strongest first, no repeats."""
    if not plays:
        return []
    base = sum(kind(r) == want for r in plays) / len(plays)
    found = []
    for (feature, value), idx in _groups(plays).items():
        n = len(idx)
        hits = sum(kind(plays[i]) == want for i in idx)
        if n < min_plays or n == len(plays) or hits / n < MIN_SHARE:
            continue
        low = wilson_low(hits, n)
        if low <= base + 0.05:
            continue   # not clearly more than they do anyway
        found.append({"feature": feature, "value": value, "plays": n, "hits": hits, "share": hits / n,
                      "low": low, "idx": set(idx)})
    found.sort(key=lambda t: (-t["low"], -t["plays"], t["value"]))
    chosen = []
    for t in found:
        if any(len(t["idx"] & c["idx"]) >= 0.8 * min(len(t["idx"]), len(c["idx"])) for c in chosen):
            continue   # mostly the same snaps as a tell already listed
        chosen.append(t)
        if len(chosen) == how_many:
            break
    for t in chosen:
        t["text"] = f"{t['value']}: {want} {t['hits']} of {t['plays']} ({round(100 * t['share'])}%)"
        del t["idx"]
    return chosen


def table(plays: list[dict], feature: str, top: int | None = None) -> list[dict]:
    counts, runs = Counter(), Counter()
    for r in plays:
        for v in _values(feature, r):
            counts[v] += 1
            runs[v] += kind(r) == "run"
    rows = [{"value": v, "plays": n, "pct": round(100 * n / len(plays)) if plays else 0, "run": runs[v],
             "pass": n - runs[v], "run_pct": round(100 * runs[v] / n)} for v, n in counts.most_common()]
    return rows[:top] if top else rows


def top_plays(plays: list[dict], formations: int = 6, per: int = 3) -> list[dict]:
    """The plays they run most from their most used formations (from the OFF PLAY column)."""
    out = []
    for f in table(plays, "Formation", formations):
        calls = Counter(_up(r.get("off_play")) for r in plays if _up(r.get("form")) == f["value"] and r.get("off_play"))
        if calls:
            out.append({"formation": f["value"], "plays": f["plays"],
                        "calls": [{"call": c, "n": n} for c, n in calls.most_common(per)]})
    return out


def analyse(sheet: dict) -> dict:
    has = set(sheet["columns"])
    rows = [r for r in sheet["rows"] if "odk" not in has or _up(r.get("odk")) in ("", "O")]
    plays = [r for r in rows if kind(r)]
    skipped = len(rows) - len(plays)
    run = sum(kind(r) == "run" for r in plays)
    no_down = sum(down_distance(r) is None for r in plays) if "dn" in has else len(plays)
    return {
        "file": sheet["name"], "plays": len(plays), "run": run, "pass": len(plays) - run, "skipped": skipped,
        "no_down": no_down, "columns": sorted(has),
        "run_tells": tells(plays, "run"), "pass_tells": tells(plays, "pass"),
        "tables": {f: table(plays, f, 12 if f == "Formation" else None) for f in SINGLE
                   if any(_values(f, r) for r in plays)},
        "top_plays": top_plays(plays) if "off_play" in has else [],
    }


def birds_and_rabbits(a: dict, opponent: str) -> str:
    """The short version for your phone and the approval card."""
    lines = [f"Birds and Rabbits: {opponent}", f"From {a['plays']} plays ({a['run']} run, {a['pass']} pass) in {a['file']}.", ""]
    for title, key in (("Run tells", "run_tells"), ("Pass tells", "pass_tells")):
        lines.append(title)
        lines += [f"- {t['text']}" for t in a[key]] or ["- None strong enough (needs 5+ plays and a 70%+ lean)."]
        lines.append("")
    return "\n".join(lines).strip()
