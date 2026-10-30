"""Thursday print: once a week (Thursday 8 PM by default) Clock prints this week's opponent folder on your printer.

The print folder (2026 WSU FOOTBALL) holds one subfolder per opponent. Clock prints the documents in the subfolder for the
team Wayne State plays that week, and nothing else. HQ creates the opponent folders for you, and agents drop their finished
documents into the right one. Files stay where they are: a file prints once, and prints again only if it changes. If the
folder is empty nothing happens. Pause stops it, Print now runs it on the spot, and the last prints are listed on the
dashboard. Printing goes through whatever app Windows uses for that file type (Word for .docx, Excel for .xlsx, your PDF
reader for .pdf), so files print the way they'd print if you right-clicked them yourself.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from .. import db
from . import season
from ..config import FOOTBALL_DATA, FOOTBALL_PRINT_DIR, FOOTBALL_PRINT_HOUR, FOOTBALL_PRINT_WEEKDAY, FOOTBALL_PRINTER

STATE_PATH = FOOTBALL_DATA / "print.json"
EXTRAS_DIR = FOOTBALL_DATA / "print_extras"   # sheets that print every week, whoever the opponent is (the press box chart)
PRINTABLE = (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".xlsm", ".csv", ".txt", ".png", ".jpg", ".jpeg", ".pptx", ".ppt")
SETTLE_SECONDS = 60          # a file that changed this recently may still be syncing from Drive
LATE_HOURS = 4               # if HQ wasn't running at print time, still print up to this long after; later, just say so
PRINT_TIMEOUT = 180          # seconds to wait for one file's app to finish sending it to the printer
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

_PS = ("$ErrorActionPreference = 'Stop'; $f = $env:HQ_PRINT_FILE; $p = $env:HQ_PRINT_PRINTER; "
       "if ($p) { Start-Process -FilePath $f -Verb PrintTo -ArgumentList ('\"' + $p + '\"') -WindowStyle Hidden -Wait } "
       "else { Start-Process -FilePath $f -Verb Print -WindowStyle Hidden -Wait }")


def _state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(s: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(s), encoding="utf-8")


def _log(entry: str) -> None:
    s = _state()
    s["log"] = ([{"at": datetime.now().isoformat(timespec="minutes"), "text": entry}] + s.get("log", []))[:30]
    _save(s)
    db.log("Clock", entry[:200])


def is_paused() -> bool:
    return bool(_state().get("paused"))


def set_paused(paused: bool) -> str:
    s = _state()
    s["paused"] = bool(paused)
    _save(s)
    _log("Thursday print paused." if paused else "Thursday print resumed.")
    return "Thursday print paused." if paused else "Thursday print resumed."


def _hour_text(h: int) -> str:
    return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


def last_slot(now: datetime | None = None) -> datetime:
    """The most recent scheduled print time at or before now."""
    now = now or datetime.now()
    slot = now.replace(hour=FOOTBALL_PRINT_HOUR, minute=0, second=0, microsecond=0)
    slot -= timedelta(days=(now.weekday() - FOOTBALL_PRINT_WEEKDAY) % 7)
    return slot if slot <= now else slot - timedelta(days=7)


def next_slot(now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    slot = last_slot(now)
    return slot if slot > now else slot + timedelta(days=7)


def week_opponent(now: datetime | None = None) -> str | None:
    g = season.current_game((now or datetime.now()).date())
    return g["opponent"] if g else None


def folder_for(opponent: str) -> Path | None:
    """The subfolder for an opponent: its exact name, or any folder name that points to it (NMU, Grand Valley...)."""
    try:
        kids = sorted(p for p in FOOTBALL_PRINT_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return None
    for p in kids:
        if p.name.casefold() == opponent.casefold():
            return p
    return next((p for p in kids if season.find_opponent(p.name) == opponent), None)


def ensure_folders() -> list[str]:
    """Make a folder for every opponent on the schedule that doesn't have one yet. Returns the ones it made."""
    made = []
    for g in season.games():
        if folder_for(g["opponent"]) is None:
            try:
                (FOOTBALL_PRINT_DIR / g["opponent"]).mkdir(parents=True, exist_ok=True)
                made.append(g["opponent"])
            except OSError:
                break
    return made


def ensure_folders_daily() -> None:
    """Keeps the opponent folders there (a deleted one comes back, a new opponent gets one), checked once a day."""
    s = _state()
    today = datetime.now().strftime("%Y-%m-%d")
    if s.get("folders_day") == today:
        return
    made = ensure_folders()
    s = _state()
    s["folders_day"] = today
    _save(s)
    if made:
        _log("Made opponent folders: " + ", ".join(made) + ".")


def deliver(src: Path, opponent: str | None) -> Path | None:
    """Copy a finished document into the opponent's folder so it's ready to print. Never overwrites a file."""
    if not opponent or season.find_opponent(opponent) is None:
        return None
    folder = folder_for(opponent) or FOOTBALL_PRINT_DIR / season.find_opponent(opponent)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / src.name
    n = 2
    while dest.exists():
        dest = folder / f"{src.stem} ({n}){src.suffix}"
        n += 1
    shutil.copy2(src, dest)
    return dest


def extras() -> list[Path]:
    try:
        return sorted(p for p in EXTRAS_DIR.iterdir() if p.is_file() and not p.name.startswith((".", "~$")))
    except OSError:
        return []


def save_extra(filename: str, data: bytes) -> str:
    from .reports import safe_name
    name = safe_name(Path(filename or "sheet.pdf").name)
    if Path(name).suffix.lower() not in PRINTABLE:
        raise ValueError("Send a PDF, Word, Excel or image file.")
    EXTRAS_DIR.mkdir(parents=True, exist_ok=True)
    (EXTRAS_DIR / name).write_bytes(data)
    _log(f"Added {name} to the sheets printed every week.")
    return name


def remove_extra(name: str) -> bool:
    path = EXTRAS_DIR / Path(name).name
    if not path.is_file():
        return False
    path.unlink()
    _log(f"Removed {path.name} from the sheets printed every week.")
    return True


def waiting(now: float | None = None) -> list[dict]:
    """Files that would print now. Each has a reason when it can't: still syncing, or a type that can't print."""
    now = now or time.time()
    s, out = _state().get("printed", {}), []
    opp = week_opponent()
    folder = folder_for(opp) if opp else None
    sources = []
    if folder is not None:
        try:
            sources += [(p, f"{folder.name}/{p.name}") for p in sorted(p for p in folder.iterdir() if p.is_file())]
        except OSError:
            pass
    if opp:   # this week's reports can print straight from the Outbox, so no opponent folder is needed
        from ..config import FOOTBALL_OUTBOX
        have = {p.name.casefold() for p, _ in sources}   # a copy already sitting in the folder isn't printed twice
        try:
            box = sorted(p for p in FOOTBALL_OUTBOX.iterdir() if p.is_file())
        except OSError:
            box = []
        sources += [(p, f"Outbox/{p.name}") for p in box
                    if season.find_opponent(p.stem) == opp and p.name.casefold() not in have
                    and p.suffix.lower() in PRINTABLE]
    if opp:   # the every-week sheets print once per game week, so the key carries the opponent
        sources += [(p, f"every week/{opp}/{p.name}") for p in extras()]
    for p, key in sources:
        if p.name.startswith(("~$", ".")) or p.suffix.lower() in (".tmp", ".crdownload", ".ini"):
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if s.get(key) == mtime:
            continue   # printed already: never print the same version twice
        item = {"name": p.name, "path": p, "key": key, "mtime": mtime, "problem": None}
        if p.suffix.lower() not in PRINTABLE:
            item["problem"] = ("A Google Doc/Sheet shortcut can't print: download it as a PDF into the folder."
                               if p.suffix.lower() in (".gdoc", ".gsheet", ".gslides") else
                               f"{p.suffix or 'This'} files can't be printed. Use PDF, Word, Excel or an image.")
        elif now - mtime < SETTLE_SECONDS:
            item["problem"] = "Still syncing. It will print next time."
        out.append(item)
    return out


SUMATRA_URL_ID = "SumatraPDF.SumatraPDF"


def sumatra() -> str | None:
    """SumatraPDF, the small free PDF viewer that can print silently, if it's installed (any usual place)."""
    found = shutil.which("SumatraPDF") or shutil.which("SumatraPDF.exe")
    if found:
        return found
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            p = Path(base) / "SumatraPDF" / "SumatraPDF.exe"
            if p.is_file():
                return str(p)
    return None


def install_sumatra() -> str | None:
    """Windows can't print a PDF without a PDF app, so install SumatraPDF for this user (winget, no admin needed)."""
    try:
        subprocess.run(["winget", "install", "--id", SUMATRA_URL_ID, "-e", "--silent", "--scope", "user",
                        "--accept-package-agreements", "--accept-source-agreements"],
                       capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return sumatra()


def _run(cmd: list[str], env: dict | None = None) -> None:
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=PRINT_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RuntimeError("the printing app didn't finish in time")
    except FileNotFoundError:
        raise RuntimeError("this computer has no print command")
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip().splitlines()
        raise RuntimeError(msg[0][:200] if msg else "Windows couldn't print it")


def _send(path: Path) -> None:
    """Send one file to the printer, raising with a plain reason if that didn't work."""
    printer = FOOTBALL_PRINTER
    if sys.platform.startswith("win"):
        if path.suffix.lower() == ".pdf":   # Windows has no print action for PDFs unless a PDF app is installed
            exe = sumatra() or install_sumatra()
            if not exe:
                raise RuntimeError("Windows has no PDF printing app and I couldn't install one. Install SumatraPDF "
                                   "(winget install SumatraPDF.SumatraPDF), then try again")
            _run([exe, *(["-print-to", printer] if printer else ["-print-to-default"]), "-silent", str(path)])
            return
        env = {**os.environ, "HQ_PRINT_FILE": str(path), "HQ_PRINT_PRINTER": printer}
        _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS], env)
    else:   # Mac/Linux: CUPS
        _run(["lp", *(["-d", printer] if printer else []), str(path)], dict(os.environ))


def print_now(reason: str = "Print now") -> str:
    """Print everything waiting. Returns the one-line summary (also logged and sent to your phone by the caller)."""
    opp = week_opponent()
    if opp and folder_for(opp) is None:
        ensure_folders()   # a missing opponent folder never blocks printing: make it
    files = waiting()
    ready = [f for f in files if not f["problem"]]
    if not files and opp and folder_for(opp) is None:
        msg = f"Couldn't make the {opp} folder in {FOOTBALL_PRINT_DIR} (is the folder there?), and nothing was waiting in the Outbox."
        _log(msg)
        return msg
    notes = [f"{f['name']}: {f['problem']}" for f in files if f["problem"]]
    if not ready:
        msg = "Nothing to print." if not files else "Nothing ready to print yet."
        _log(msg + (" " + " ".join(notes) if notes else ""))
        return msg + ("\n" + "\n".join(notes) if notes else "")
    printed, failed = [], []
    for f in ready:
        try:
            _send(f["path"])
        except Exception as e:
            failed.append(f"{f['name']} ({e})")
            continue
        printed.append(f["name"])
        s = _state()
        s.setdefault("printed", {})[f["key"]] = f["mtime"]
        _save(s)
    lines = []
    if printed:
        lines.append(f"Printed {len(printed)} file{'s' if len(printed) > 1 else ''} from the {opp} folder: " + ", ".join(printed) + ".")
    if failed:
        lines.append("Couldn't print: " + "; ".join(failed) + ". They're still in the folder.")
    lines += notes
    text = "\n".join(lines)
    _log(f"{reason}: " + " ".join(lines))
    return text


def print_outbox_file(name: str) -> str:
    """Print one file straight from the Outbox, on demand. Doesn't touch the Thursday print's record."""
    from ..config import FOOTBALL_OUTBOX
    path = (FOOTBALL_OUTBOX / Path(name).name).resolve()
    if path.parent != FOOTBALL_OUTBOX.resolve() or not path.is_file():
        return f"There's no {Path(name).name} in the football Outbox."
    if path.suffix.lower() not in PRINTABLE:
        return f"{path.name}: {path.suffix or 'This'} files can't be printed. Use PDF, Word, Excel or an image."
    try:
        _send(path)
    except Exception as e:
        msg = f"Couldn't print {path.name} ({e})."
    else:
        msg = f"Sent {path.name} to {FOOTBALL_PRINTER or 'the default printer'}."
    _log(msg)
    return msg


def run_if_due(now: datetime | None = None) -> str | None:
    """The scheduled print. Called every few seconds by the worker; acts once per scheduled slot."""
    from .. import relay
    now = now or datetime.now()
    slot = last_slot(now)
    s = _state()
    done = s.get("done")
    if not done:   # first look: start from the current slot so turning this on never prints out of the blue
        s["done"] = slot.isoformat()
        _save(s)
        return None
    if datetime.fromisoformat(done) >= slot:
        return None
    if s.get("paused"):
        return None   # stays pending: resume within LATE_HOURS and it still prints, after that it's reported as missed
    s["done"] = slot.isoformat()
    _save(s)
    if now - slot > timedelta(hours=LATE_HOURS):
        n = len([f for f in waiting() if not f["problem"]])
        if not n:
            return None
        msg = (f"🖨️ The {DAYS[slot.weekday()]} print didn't run because HQ wasn't running at {_hour_text(slot.hour)}. "
               f"{n} file{'s are' if n > 1 else ' is'} waiting in the print folder. Press Print now on the dashboard.")
        _log(msg)
        relay.notify(msg)
        return msg
    opp = week_opponent()
    if opp and folder_for(opp) is None:
        ensure_folders()
    if not waiting():
        msg = ("Thursday print: " + (f"nothing in the {opp} folder, so nothing printed." if opp and folder_for(opp)
                                    else f"no folder for {opp} yet, so nothing printed." if opp else "no game this week."))
        _log(msg)
        if opp and not folder_for(opp):
            relay.notify("🖨️ Clock\n" + msg)
        return msg
    text = print_now("Thursday print")
    relay.notify("🖨️ Clock\n" + text)
    return text


def state() -> dict:
    s = _state()
    files = waiting()
    return {
        "folder": str(FOOTBALL_PRINT_DIR), "folder_found": FOOTBALL_PRINT_DIR.is_dir(),
        "opponent": week_opponent(), "week_folder": (folder_for(week_opponent() or "") or Path("")).name or None,
        "printer": FOOTBALL_PRINTER or "Windows default printer",
        "when": f"{DAYS[FOOTBALL_PRINT_WEEKDAY]}s at {_hour_text(FOOTBALL_PRINT_HOUR)}",
        "next": next_slot().isoformat(timespec="minutes"), "paused": bool(s.get("paused")),
        "files": [{"name": f["name"], "problem": f["problem"]} for f in files],
        "extras": [p.name for p in extras()],
        "log": s.get("log", [])[:8],
    }
