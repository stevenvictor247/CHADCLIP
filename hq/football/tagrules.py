"""Ref's rules: checks each tagged play against Steven's written tagging rules (Coaching Notebook, Formations tab).

Only rules that can be checked from the sheet itself are here. Anything that needs the film (strength, splits,
whether a wing is really there) stays with you. Every flag says which rule it comes from, and nothing is changed:
Ref flags, you decide.

Levels: "fix" breaks a written rule. "check" is worth a second look (an open question, or something unusual).
"""

import difflib
import re

from .sheet import TAG_COLUMNS, label

BACKFIELDS = ("GUN STRONG", "GUN WEAK", "GUN SPLIT", "EMPTY", "WILDCAT", "WILDCAT GS", "ACE", "I", "PISTOL")
TAGS = ("FSL", "FIB", "SIB", "CONDENSED", "STACK")
BOUNDARY_TAGS = ("FSL", "FIB", "SIB")
BASES = ("TREY OFF", "DEUCE OFF", "PRO", "TWINS", "TREY", "TRIPS", "DEUCE", "BONE", "DOUBLES", "QUADS")  # two-word ones first
MODIFIERS = ("BUNCH", "CLOSE", "CLOSED", "T-OVER", "WANG", "WING", "OPEN")
PREFIXES = ("EMPTY", "UB")
NOT_TWO_BY_TWO = ("TRIPS", "TREY", "TREY OFF", "QUADS")   # SIB is for 2x2 sets only
OLD_HUDL_WORDS = ("WIDE", "REDUCED", "RT", "LT", "RIGHT", "LEFT", "NEAR", "FAR")  # autocomplete leftovers from other staffs
CONFIDENCE = ("HIGH", "MEDIUM", "LOW", "NONE", "COACH")
MIDDLE = ("M", "MID", "MIDDLE", "C", "CENTER")
NOT_PLAYS = ("PENALTY", "TIMEOUT", "TIME OUT")
QUESTION = "No \"?\" in a tag cell: put your best guess with a real tag, set Confidence to Low and give the reason in Notes."


def _up(v: str) -> str:
    return re.sub(r"\s+", " ", (v or "").upper()).strip()


def _suggest(word: str, choices) -> str | None:
    m = difflib.get_close_matches(word, list(choices), n=1, cutoff=0.75)
    return m[0] if m else None


def parse_form(form: str) -> dict:
    """Split a formation name into its parts: {"empty", "ub", "base", "mods", "unknown"}."""
    words = _up(form).replace("T OVER", "T-OVER").replace("TOVER", "T-OVER").split()
    out = {"empty": False, "ub": False, "base": None, "mods": [], "unknown": []}
    i = 0
    while i < len(words) and words[i] in PREFIXES:
        out["empty" if words[i] == "EMPTY" else "ub"] = True
        i += 1
    rest = " ".join(words[i:])
    for base in BASES:
        if rest == base or rest.startswith(base + " "):
            out["base"] = base
            i += len(base.split())
            break
    for w in words[i:]:
        (out["mods"] if w in MODIFIERS else out["unknown"]).append(w)
    return out


def parse_tags(tag: str) -> tuple[list[str], list[str]]:
    """Returns (tags, problems). Tags are written together with a comma, like FSL, STACK."""
    text = _up(tag)
    problems = []
    if not text:
        return [], problems
    if re.search(r"[/;|+&]| AND ", text):
        problems.append("Separate two tags with a comma, like FSL, STACK.")
    parts = [p.strip() for p in re.split(r"[,/;|+&]| AND ", text) if p.strip()]
    return parts, problems


def _flag(flags, row, level, column, message):
    flags.append({"row": row["row"], "play": row.get("play", ""), "label": label(row), "level": level,
                  "column": column, "value": row.get(column, ""), "message": message})


def check_row(row: dict, has: set) -> list[dict]:
    flags = []
    pers, form, tag, back = (row.get(c, "") for c in TAG_COLUMNS)
    conf, notes = _up(row.get("confidence", "")), row.get("notes", "").strip()

    # PERSONNEL: two digits, RBs then TEs, with T added for an extra OT
    if pers:
        p = _up(pers)
        m = re.fullmatch(r"(\d)(\d)(T)?", p)
        if "?" in p:
            _flag(flags, row, "fix", "personnel", QUESTION)
        elif not m:
            _flag(flags, row, "fix", "personnel", "Personnel is two digits, RBs then TEs (like 10, 11, 12), plus T "
                                                  "for an extra OT (12T).")
        elif int(m[1]) + int(m[2]) > 6:
            _flag(flags, row, "fix", "personnel", f"{p} adds up to more backs and TEs than can be on the field.")

    # BACKFIELD: one of the nine tags
    if back:
        b = _up(back)
        if "?" in b:
            _flag(flags, row, "fix", "backfield", QUESTION)
        elif b.startswith("PISTOL") and b != "PISTOL":
            _flag(flags, row, "fix", "backfield", "Pistol is always just PISTOL, never PISTOL STRONG, NEAR or FAR.")
        elif b not in BACKFIELDS:
            near = _suggest(b, BACKFIELDS)
            _flag(flags, row, "fix", "backfield", (f"Did you mean {near}? " if near else "") +
                  "Backfield must be one of: " + ", ".join(BACKFIELDS) + ".")

    # OFF FORM: [EMPTY] + base formation + modifiers
    parts = parse_form(form) if form else None
    if form:
        f = _up(form)
        if "?" in f:
            _flag(flags, row, "fix", "form", QUESTION)
        else:
            moved = [w for w in parts["unknown"] if w in TAGS + ("STACKED",)]
            old = [w for w in parts["unknown"] if w in OLD_HUDL_WORDS]
            other = [w for w in parts["unknown"] if w not in moved and w not in old]
            if moved:
                words = sorted({"STACK" if w == "STACKED" else w for w in moved})
                _flag(flags, row, "fix", "form", f"{' and '.join(words)} is a formation tag: take it out of OFF FORM "
                      f"and put {'them' if len(words) > 1 else 'it'} in the FORMATION TAG column.")
            if "WIDE" in old and parts["base"] == "DOUBLES":
                _flag(flags, row, "fix", "form", "It's DOUBLES, never DOUBLES WIDE. Delete the word Hudl added.")
            elif old:
                _flag(flags, row, "fix", "form", f"{' '.join(old)} is an old Hudl autocomplete word. Use the base name "
                      "and delete the extra word.")
            if parts["base"] == "TREY OFF" and "OPEN" in parts["mods"]:
                _flag(flags, row, "fix", "form", "TREY OFF OPEN is an old Hudl name: ignore it and use TREY OFF.")
            if "SLOT" in other:
                _flag(flags, row, "check", "form", "Slot (as in Pro Slot) is still undecided. Ask your coach what to call it.")
                other.remove("SLOT")
            for w in other:
                near = _suggest(w, BASES + MODIFIERS + PREFIXES)
                if near:
                    _flag(flags, row, "fix", "form", f"\"{w}\" looks like a typo for {near}.")
                else:
                    _flag(flags, row, "check", "form", f"\"{w}\" isn't one of your formation words. If it's a new "
                          "official name, add it to the notebook.")
            named = parts["ub"] or "T-OVER" in parts["mods"] or (parts["empty"] and "BUNCH" in parts["mods"])  # EMPTY BUNCH is an install name
            if not parts["base"] and not named and not (moved or old or other):
                _flag(flags, row, "check", "form", "No base formation in the name (like TRIPS, TREY OFF or DOUBLES).")

    # FORMATION TAG: FSL, FIB, SIB, CONDENSED, STACK, comma-separated, blank when nothing qualifies
    tags, problems = parse_tags(tag)
    for p in problems:
        _flag(flags, row, "fix", "tag", p)
    seen = set()
    for t in tags:
        if "?" in t:
            _flag(flags, row, "fix", "tag", QUESTION)
        elif t == "STACKED":
            _flag(flags, row, "fix", "tag", "Write STACK, not STACKED.")
        elif t == "EMPTY":
            _flag(flags, row, "fix", "tag", "EMPTY isn't a formation tag: it goes at the front of OFF FORM and in BACKFIELD.")
        elif t not in TAGS:
            near = _suggest(t, TAGS)
            _flag(flags, row, "fix", "tag", (f"\"{t}\" looks like a typo for {near}." if near else
                                             f"\"{t}\" isn't a formation tag. Tags are " + ", ".join(TAGS) + "."))
        elif t in seen:
            _flag(flags, row, "check", "tag", f"{t} is written twice.")
        seen.add(t)
    valid = [t for t in tags if t in TAGS] + (["STACK"] if "STACKED" in tags else [])

    if parts and "STACK" in valid and parts["base"] == "TRIPS":
        _flag(flags, row, "fix", "tag", "Never tag STACK on a Trips formation (Empty Trips included).")
    if parts and "SIB" in valid and (parts["base"] in NOT_TWO_BY_TWO or parts["empty"] or "BUNCH" in parts["mods"]):
        _flag(flags, row, "fix", "tag", "SIB is for 2x2 sets only.")
    if "hash" in has and _up(row.get("hash", "")) in MIDDLE:
        for t in valid:
            if t in BOUNDARY_TAGS:
                _flag(flags, row, "fix", "tag", f"{t} needs the ball on a hash. Ball in the middle = no boundary tag.")

    # EMPTY in the name and EMPTY in the backfield go together
    b = _up(back)
    if parts and b == "EMPTY" and not parts["empty"]:
        _flag(flags, row, "fix", "form", "BACKFIELD is EMPTY, so the formation starts with EMPTY (like EMPTY "
                                         f"{_up(form)}). A back who motions out makes it Empty.")
    if parts and parts["empty"] and b and b != "EMPTY":
        _flag(flags, row, "fix", "backfield", "The formation is an EMPTY set, so BACKFIELD is EMPTY.")

    # Pattern from the 232 coach-tagged plays (10/19): Wildcat only showed up with 14 or 24 personnel.
    if b in ("WILDCAT", "WILDCAT GS") and pers and not _up(pers).startswith(("14", "24")):
        _flag(flags, row, "check", "personnel", f"Wildcat with {_up(pers)} personnel: in the coach-tagged plays "
                                                "Wildcat only came with 14 or 24. Worth a second look.")

    # Practice-sheet columns: Confidence and Notes
    if "confidence" in has:
        filled = [c for c in TAG_COLUMNS if row.get(c)]
        if conf == "NONE" and filled:
            _flag(flags, row, "fix", "confidence", "Confidence None means no pre-snap frame: leave all four tags blank.")
        elif conf and conf not in CONFIDENCE:
            _flag(flags, row, "check", "confidence", "Confidence is High, Medium, Low, None or Coach.")
        if conf == "LOW" and "notes" in has and not notes:
            _flag(flags, row, "check", "notes", "Low confidence needs the reason in Notes.")
    if (pers or back) and not form:
        _flag(flags, row, "check", "form", "OFF FORM is blank. If it's a look that isn't in the install (like 2x1 "
                                           "split backs), leave it blank and say so in Notes." if not notes else
                                           "OFF FORM is blank. Notes explain it, so this is just a reminder it still needs a name.")
    if form and not pers:
        _flag(flags, row, "check", "personnel", "PERSONNEL is blank.")
    if form and not back:
        _flag(flags, row, "check", "backfield", "BACKFIELD is blank.")
    return flags


def _is_play(row: dict, has: set) -> bool:
    if "odk" in has and _up(row.get("odk", "")) not in ("", "O"):
        return False   # defense and kicking rows aren't tagged for offense
    nothing_tagged = not any(row.get(c) for c in TAG_COLUMNS)
    if nothing_tagged and not row.get("play_type") and _up(row.get("result", "")) in NOT_PLAYS:
        return False   # a penalty or timeout with no snap to tag
    return True


def ranges(plays: list[str]) -> str:
    """'52, 53, 54, 57' -> '52-54, 57'."""
    nums = [int(p) for p in plays if str(p).isdigit()]
    if len(nums) != len(plays):
        return ", ".join(str(p) for p in plays)
    out, start, prev = [], None, None
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}-{prev}" if prev != start else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}-{prev}" if prev != start else str(start))
    return ", ".join(out)


def check_sheet(sheet: dict) -> dict:
    has = set(sheet["columns"])
    missing = [c for c in TAG_COLUMNS if c not in has]
    plays = [r for r in sheet["rows"] if _is_play(r, has)]
    flags, untagged, tagged = [], [], 0
    for r in plays:
        if not any(r.get(c) for c in TAG_COLUMNS):
            if _up(r.get("confidence", "")) != "NONE":
                untagged.append(r.get("play") or f"row {r['row']}")
            continue
        tagged += 1
        flags += check_row(r, has)
    fix = sum(f["level"] == "fix" for f in flags)
    check = len(flags) - fix
    parts = [f"{tagged} tagged plays checked", f"{fix} to fix", f"{check} to check"]
    if untagged:
        parts.append(f"{len(untagged)} not tagged yet ({ranges(untagged)})")
    summary = f"{sheet['name']}: " + ", ".join(parts) + "."
    if missing:
        summary += " No " + ", ".join(c.upper().replace("FORM", "OFF FORM") for c in missing) + " column, so those weren't checked."
    return {"file": sheet["name"], "plays": len(plays), "tagged": tagged, "untagged": untagged,
            "fix": fix, "check": check, "flags": flags, "summary": summary, "missing_columns": missing}
