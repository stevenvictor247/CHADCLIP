"""Tells' counting: tendencies from a tagged sheet, and the biggest run and pass tells (Birds and Rabbits).

Everything here is plain counting of your tags. No AI touches the numbers, so nothing can be made up: every tell
shows its count and sample size, and a tell needs enough plays and a clear lean before it's listed.
"""

import math
import statistics
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
        t["games"] = per_game(plays, t["idx"], want)
        t["median_gain"] = median_gain([plays[i] for i in sorted(t["idx"])])
        del t["idx"]
    return chosen


def gain(row: dict) -> int | None:
    return number(row.get("gain"))


def median_gain(rows: list[dict]):
    g = [x for x in map(gain, rows) if x is not None]
    return statistics.median(g) if g else None


def mean_gain(rows: list[dict]):
    g = [x for x in map(gain, rows) if x is not None]
    return sum(g) / len(g) if g else None


def per_game(plays: list[dict], idx, want: str) -> list[dict]:
    """For a tell: in each game it showed up, how many of the snaps went the tell's way."""
    out = {}
    for i in sorted(idx):
        g = plays[i].get("_g") or ""
        n, h = out.get(g, (0, 0))
        out[g] = (n + 1, h + (kind(plays[i]) == want))
    return [{"game": g, "n": n, "hits": h} for g, (n, h) in out.items()]


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


def game_label(name: str, opponent: str | None = None) -> str:
    """A short game name from an export's file name: its extension and the Hudl prefix are dropped."""
    stem = name.rsplit(".", 1)[0]
    for junk in ("PlaylistData_", "PlaylistData", "Playlist Data"):
        stem = stem.replace(junk, "")
    return " ".join(stem.replace("_", " ").split()) or "Game"


def _run_pct(rows: list[dict]) -> float:
    return 100 * sum(kind(r) == "run" for r in rows) / len(rows) if rows else 0.0


def _stat_row(label: str, rows: list[dict]) -> dict:
    return {"label": label, "snaps": len(rows), "run": sum(kind(r) == "run" for r in rows), "run_pct": _run_pct(rows),
            "avg": mean_gain(rows), "med": median_gain(rows)}


def _by_game(rows: list[dict], games: list[str]) -> list[int]:
    return [sum(r.get("_g") == g for r in rows) for g in games]


def _dd_bucket(row: dict):
    dn, dist = number(row.get("dn")), number(row.get("dist"))
    if dn not in (1, 2, 3, 4) or dist is None or dist <= 0:
        return None
    return f"{dn} & {'3 or less' if dist <= 3 else '4-7' if dist <= 7 else '8+'}"


def _dist_bucket(row: dict):
    dist = number(row.get("dist"))
    if dist is None or dist <= 0:
        return None
    return "1-2" if dist <= 2 else "3-6" if dist <= 6 else "7-9" if dist <= 9 else "10-12" if dist <= 12 else "13+"


def _group_stats(plays: list[dict], fn, games: list[str], order=None, min_snaps: int = 1, top: int | None = None) -> list[dict]:
    buckets = {}
    for r in plays:
        for v in (fn(r) if isinstance(fn(r), list) else [fn(r)]):
            if v:
                buckets.setdefault(v, []).append(r)
    keys = sorted(buckets, key=(lambda k: order.index(k) if k in order else 99) if order else (lambda k: -len(buckets[k])))
    rows = []
    for k in keys:
        if len(buckets[k]) >= min_snaps:
            row = _stat_row(k, buckets[k])
            row["by_game"] = _by_game(buckets[k], games)
            rows.append(row)
    return rows[:top] if top else rows


def _concepts(plays: list[dict], want: str, minimum: int) -> list[dict]:
    buckets = {}
    for r in plays:
        if kind(r) == want and r.get("off_play"):
            buckets.setdefault(_up(r["off_play"]), []).append(r)
    rows = []
    for k, rs in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        if len(rs) >= minimum:
            g = [x for x in map(gain, rs) if x is not None]
            rows.append({"label": k, "n": len(rs), "avg": mean_gain(rs), "med": median_gain(rs), "long": max(g) if g else None})
    return rows


def _explosive(plays: list[dict], games: list[str]) -> dict:
    ex = [r for r in plays if (gain(r) or 0) >= (12 if kind(r) == "run" else 16)]
    return {"n": len(ex), "run": sum(kind(r) == "run" for r in ex), "pass": sum(kind(r) == "pass" for r in ex),
            "by_game": _by_game(ex, games)}


def _sacks(plays: list[dict]) -> list[dict]:
    return [{"game": r.get("_g"), "down": down_distance_short(r), "form": _up(r.get("form")), "back": _up(r.get("backfield")),
             "protection": _up(r.get("off_play")), "gain": gain(r)}
            for r in plays if "SACK" in _up(r.get("result")) or (kind(r) == "pass" and (gain(r) or 0) < 0)]


def down_distance_short(row: dict) -> str:
    dn, dist = number(row.get("dn")), number(row.get("dist"))
    return f"{dn}&{dist}" if dn in (1, 2, 3, 4) and dist else "-"


def analyse(sheets) -> dict:
    """Counts one tagged sheet, or a list of sheets (one game each, oldest first) as one scouting sample."""
    sheets = [sheets] if isinstance(sheets, dict) else list(sheets)
    names = [game_label(s["name"]) for s in sheets]
    has, rows = set(), []
    for s, label in zip(sheets, names):
        has |= set(s["columns"])
        for r in s["rows"]:
            if "odk" not in s["columns"] or _up(r.get("odk")) in ("", "O"):
                rows.append({**r, "_g": label})
    plays = [r for r in rows if kind(r)]
    skipped = len(rows) - len(plays)
    run = sum(kind(r) == "run" for r in plays)
    no_down = sum(down_distance(r) is None for r in plays) if "dn" in has else len(plays)
    in_game = {g: [r for r in plays if r["_g"] == g] for g in names}
    games = [dict(_stat_row(g, rs), no_form=sum(not r.get("form") for r in rs)) for g, rs in in_game.items()]
    by_down = [{"down": d, "all": _stat_row(str(d), [r for r in plays if number(r.get("dn")) == d]),
                "by_game": [_stat_row(g, [r for r in rs if number(r.get("dn")) == d]) for g, rs in in_game.items()]}
               for d in (1, 2, 3, 4)]
    stat_tables = {
        "Down and distance": _group_stats(plays, _dd_bucket, names, order=[f"{d} & {b}" for d in (1, 2, 3, 4)
                                                                           for b in ("3 or less", "4-7", "8+")]),
        "Distance to go": _group_stats(plays, _dist_bucket, names, order=["1-2", "3-6", "7-9", "10-12", "13+"]),
        "Personnel": _group_stats(plays, SINGLE["Personnel"], names),
        "Backfield": _group_stats(plays, SINGLE["Backfield"], names),
        "Formation": _group_stats(plays, SINGLE["Formation"], names, top=14),
        "Formation tag": _group_stats(plays, SINGLE["Formation tag"], names, min_snaps=3, top=12),
        "Hash": _group_stats(plays, hash_mark, names),
        "Field zone": _group_stats(plays, field_zone, names),
        "Motion": _group_stats(plays, lambda r: _up(r.get("motion")) or None, names, min_snaps=2, top=14),
    }
    return {
        "file": ", ".join(s["name"] for s in sheets), "files": [s["name"] for s in sheets], "game_names": names,
        "plays": len(plays), "run": run, "pass": len(plays) - run, "skipped": skipped,
        "no_down": no_down, "columns": sorted(has), "dead_balls": skipped,
        "run_tells": tells(plays, "run"), "pass_tells": tells(plays, "pass"),
        "tables": {f: table(plays, f, 12 if f == "Formation" else None) for f in SINGLE
                   if any(_values(f, r) for r in plays)},
        "top_plays": top_plays(plays) if "off_play" in has else [],
        "overall": _stat_row("All", plays), "games": games, "by_down": by_down, "stat_tables": stat_tables,
        "run_concepts": _concepts(plays, "run", 3) if "off_play" in has else [],
        "pass_concepts": _concepts(plays, "pass", 3) if "off_play" in has else [],
        "explosive": _explosive(plays, names), "sacks": _sacks(plays),
        "early_late": _early_late(in_game),
        "base_run_pct": _run_pct(plays),
    }


def _early_late(in_game: dict) -> list[dict]:
    out = []
    for g, rs in in_game.items():
        if len(rs) >= 10:
            half = len(rs) // 2
            a, b = rs[:half], rs[half:]
            out.append({"game": g, "early_n": len(a), "early": _run_pct(a), "late_n": len(b), "late": _run_pct(b)})
    return out


def birds_and_rabbits(a: dict, opponent: str) -> str:
    """The short version for your phone and the approval card."""
    lines = [f"Birds and Rabbits: {opponent}", f"From {a['plays']} plays ({a['run']} run, {a['pass']} pass) in {a['file']}.", ""]
    for title, key in (("Run tells", "run_tells"), ("Pass tells", "pass_tells")):
        lines.append(title)
        lines += [f"- {t['text']}" for t in a[key]] or ["- None strong enough (needs 5+ plays and a 70%+ lean)."]
        lines.append("")
    return "\n".join(lines).strip()
