"""Move HQ to another computer in one go: your PC to the cloud server, or the cloud back to your PC.

Everything comes along: the database, Settings and keys, config/ (vision, accounts, creators, streamers), the YouTube,
TikTok and Instagram sign-ins, the football data, what Chad already clipped (so nothing is clipped or posted twice),
when the daily jobs last ran, and the video files of clips that still need them (waiting for approval, approved, or
failed somewhere). Paths are fixed up for the new computer (C:\\Users\\... on the PC, /opt/agent-hq/... on the server),
folders in Google Drive are matched to the same Drive folders, and the time zone comes too.

The move itself (send_to):
1. ask the other HQ whether it's free (on standby, or a new server waiting for your HQ) and log in to it;
2. put this copy on standby, then wait for any post in progress to finish and for the Telegram bot to go quiet;
3. pack everything into one zip and upload it; the other HQ unpacks it, takes over, and restarts;
4. wait until the other HQ says it runs the agents with this zip. Only then is the move finished.
If it fails before the other HQ took over, this copy simply carries on. If it can't tell (the other HQ stopped
answering mid-move), this copy stays on standby, so the worst case is nothing posting for a while, never posting twice.
"""

import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath

from . import db, standby
from .config import CLIPS_DIR, CONFIG_DIR, DATA_DIR, DB_PATH, ROOT, SETTINGS_PATH, saved_settings

MANIFEST = "hq-move.json"
MOVE_LOG = DATA_DIR / "move-log.json"     # what this copy last sent or took in (never carried in a move)
MOVE_CODE = DATA_DIR / "move-code.json"   # the one-time password of a new cloud server this PC set up
CLIP_BYTES_CAP = 3 * 1024 ** 3            # clip videos beyond this stay behind (the ones that still need posting go first)
EXTERNAL_BYTES_CAP = 1024 ** 3            # a football folder outside data/ and outside Google Drive
UPLOAD_LIMIT = 12 * 1024 ** 3

# Never carried: copies of backups, downloads Chad can fetch again, this copy's own identity and standby switch, the
# desktop window's browser storage, the trash, and files that only mean something on this computer.
SKIP_DIRS = ("backups", "update-backups", "sources", "clips", "desktop-app", "sweep/trash", "move-in",
             "drive", "before-move")
# Each computer keeps its own: which copy it is, its watchdog notes and which HQ versions ran fine on it.
SKIP_FILES = {"standby.json", "instance.json", "worker_alive.txt", "move-log.json", "move-code.json", "move-in.zip",
              "health.json", "good-version.txt", "bad-version.txt",
              "tiktok_state.txt", "desktop-app.log", "settings.json", DB_PATH.name, DB_PATH.name + "-wal",
              DB_PATH.name + "-shm", DB_PATH.name + ".before-restore"}
MEDIA = (".mp4", ".mov", ".mkv", ".webm", ".m4a", ".mp3", ".wav", ".part", ".ytdl")
FOLDER_SETTINGS = ("HQ_FOOTBALL_DIR", "HQ_PRINT_DIR")   # folders that may live in Google Drive

# Windows time zone names (tzutil /g) for the US and a few others, so the cloud keeps your reminder and report times.
WINDOWS_ZONES = {
    "Eastern Standard Time": "America/New_York", "US Eastern Standard Time": "America/Indiana/Indianapolis",
    "Central Standard Time": "America/Chicago", "Mountain Standard Time": "America/Denver",
    "US Mountain Standard Time": "America/Phoenix", "Pacific Standard Time": "America/Los_Angeles",
    "Alaskan Standard Time": "America/Anchorage", "Hawaiian Standard Time": "Pacific/Honolulu",
    "Atlantic Standard Time": "America/Halifax", "GMT Standard Time": "Europe/London",
    "W. Europe Standard Time": "Europe/Berlin", "Romance Standard Time": "Europe/Paris", "UTC": "UTC",
}


class MoveError(Exception):
    """Plain words for Steven about why a move didn't happen."""


def family(platform: str | None = None) -> str:
    p = platform or sys.platform
    return "windows" if p.startswith("win") else "mac" if p == "darwin" else "linux"


# ---- packing ----------------------------------------------------------------------------------------------------

def local_timezone() -> str:
    """This computer's time zone as a name like America/Detroit, or "" if it can't tell."""
    if os.getenv("HQ_TZ", "").strip():
        return os.getenv("HQ_TZ").strip()
    if sys.platform == "win32":
        try:
            name = subprocess.run(["tzutil", "/g"], capture_output=True, text=True, timeout=10).stdout.strip()
            return WINDOWS_ZONES.get(name.replace("_dstoff", ""), "")
        except (OSError, subprocess.SubprocessError):
            return ""
    try:
        target = os.path.realpath("/etc/localtime")
        return target.split("zoneinfo/", 1)[1] if "zoneinfo/" in target else ""
    except OSError:
        return ""


def _skipped(rel: PurePosixPath) -> bool:
    s = rel.as_posix()
    if rel.name in SKIP_FILES or rel.name.endswith(".tmp"):
        return True
    return any(s == d or s.startswith(d + "/") for d in SKIP_DIRS) or s.startswith("before-move-")


def _clip_files() -> tuple[list[tuple[Path, str]], int]:
    """Clip videos worth carrying, the ones that still have to be posted first. Returns ([(file, zip name)], left out)."""
    order = {"pending_approval": 0, "approved": 0, "failed": 1, "posted": 2}
    rows = db.rows("SELECT id, path, status FROM clips WHERE status != 'rejected' ORDER BY id DESC")
    rows.sort(key=lambda r: order.get(r["status"], 3))
    chosen, total, left, seen = [], 0, 0, set()
    for r in rows:
        p = Path(r["path"] or "")
        if not p.is_file() or p.name in seen:
            continue
        size = p.stat().st_size
        if total + size > CLIP_BYTES_CAP and order.get(r["status"], 3) > 0:
            left += 1
            continue
        seen.add(p.name)
        total += size
        chosen.append((p, f"data/clips/{p.name}"))
    return chosen, left


def _drive_path(value: str) -> str | None:
    """'My Drive/Football/2026 WSU FOOTBALL' for a folder inside Google Drive on any computer, else None."""
    parts = re.split(r"[\\/]+", value.strip())
    for i, part in enumerate(parts):
        if part.casefold() == "my drive":
            return "/".join(["My Drive", *[p for p in parts[i + 1:] if p]])
    return None


def _outside_data(value: str) -> Path | None:
    """A football folder on this computer that's outside data/ and outside Google Drive: its files come along."""
    if not value or _drive_path(value):
        return None
    p = Path(value)
    try:
        if not p.is_dir() or p.resolve().is_relative_to(DATA_DIR.resolve()):
            return None
    except OSError:
        return None
    return p


def make_bundle(out: Path, kind: str = "move") -> dict:
    """Pack this HQ into one zip. Returns the manifest that's inside it."""
    from .config import PASSWORD
    from .football import printing
    try:
        printing.remember_hashes()   # so a file printed here isn't printed again by the other copy
    except Exception:
        pass
    clips, left_out = _clip_files()
    settings = saved_settings()
    if PASSWORD:   # it might only be in .env, which the cloud server's own password would hide
        settings["HQ_PASSWORD"] = PASSWORD
    settings.pop("HQ_PEER_URL", None)
    manifest = {"kind": kind, "bundle_id": secrets.token_hex(8), "made": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "platform": sys.platform, "data_dir": str(DATA_DIR), "root": str(ROOT), "timezone": local_timezone(),
                "from_instance": standby.instance()["id"], "clips_left_out": left_out, "external": {}}
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        snapshot = Path(tmp) / DB_PATH.name
        with closing(sqlite3.connect(DB_PATH)) as src, closing(sqlite3.connect(snapshot)) as dst:
            src.backup(dst)   # a consistent copy even while HQ is running
        z.write(snapshot, f"data/{DB_PATH.name}")
        z.writestr("data/settings.json", json.dumps(settings, indent=2, sort_keys=True))
        for p in sorted(CONFIG_DIR.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                z.write(p, p.relative_to(ROOT).as_posix())
        if (ROOT / ".env").is_file():
            z.write(ROOT / ".env", ".env")
        for p in sorted(DATA_DIR.rglob("*")):
            if not p.is_file():
                continue
            rel = PurePosixPath(p.relative_to(DATA_DIR).as_posix())
            if _skipped(rel) or (p.suffix.lower() in MEDIA and not rel.as_posix().startswith("football/")):
                continue
            z.write(p, f"data/{rel.as_posix()}")
        for p, name in clips:
            z.write(p, name)
        for key in FOLDER_SETTINGS:
            folder = _outside_data(os.getenv(key, ""))
            if not folder:
                continue
            total = 0
            for f in sorted(folder.rglob("*")):
                if f.is_file() and not f.name.startswith(("~$", ".")):
                    total += f.stat().st_size
                    if total > EXTERNAL_BYTES_CAP:
                        break
                    z.write(f, f"external/{key}/{f.relative_to(folder).as_posix()}")
            manifest["external"][key] = str(folder)
        z.writestr(MANIFEST, json.dumps(manifest, indent=2))
    return manifest


# ---- unpacking --------------------------------------------------------------------------------------------------

def _safe_parts(name: str) -> tuple[str, ...]:
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if not parts or name.startswith(("/", "\\")) or ".." in parts or ":" in parts[0]:
        raise MoveError(f"{name} would land outside the HQ folder, so this zip wasn't used.")
    return parts


def _dest(parts: tuple[str, ...]) -> Path | None:
    if parts[0] == "data":
        return DATA_DIR.joinpath(*parts[1:]) if len(parts) > 1 else None
    if parts[0] == "config" or parts == (".env",):
        return ROOT.joinpath(*parts)
    return None   # the manifest and external/ are handled on their own; anything else isn't HQ's


def _foreign(value: str) -> bool:
    """A full path written on another kind of computer (C:\\... on the server, /home/... on Windows)."""
    v = value.strip()
    windows_path = bool(re.match(r"^[A-Za-z]:[\\/]", v)) or v.startswith("\\\\")
    return windows_path if family() != "windows" else v.startswith("/")


def relocate(old: str, manifest: dict) -> str:
    """Where a file that was at `old` on the other computer is on this one."""
    pure = PureWindowsPath if family(manifest.get("platform")) == "windows" else PurePosixPath
    old_p, data = pure(old), pure(manifest.get("data_dir") or "")
    for base, new_base in ((data, DATA_DIR), (pure(manifest.get("root") or ""), ROOT)):
        try:
            rel = old_p.relative_to(base) if str(base) not in ("", ".") else None
        except ValueError:
            rel = None
        if rel is not None:
            return str(new_base.joinpath(*rel.parts))
    return str(CLIPS_DIR / old_p.name) if (CLIPS_DIR / old_p.name).exists() else old


def fix_settings(settings: dict, manifest: dict) -> dict:
    """Paths from the other computer are kept aside (and given back if HQ ever moves back there); folders in Google
    Drive point at the same Drive folders through the Drive sync; the time zone comes along."""
    settings = dict(settings)
    try:
        saved = json.loads(settings.get("HQ_SAVED_PATHS") or "{}")
    except ValueError:
        saved = {}
    there = family(manifest.get("platform"))
    for key, value in list(settings.items()):
        if isinstance(value, str) and key != "HQ_SAVED_PATHS" and _foreign(value):
            saved.setdefault(there, {})[key] = value
            del settings[key]
    for key, value in saved.get(family(), {}).items():   # coming back to a computer HQ ran on before
        settings.setdefault(key, value)
    drive = {}
    for key in FOLDER_SETTINGS:
        old = saved.get(there, {}).get(key) or ""
        if key not in settings and _drive_path(old):
            drive[key] = _drive_path(old)
    if drive and family() != "windows":
        from . import drive_sync
        for key, path in drive.items():
            settings[key] = str(drive_sync.local_folder(path))
        settings["HQ_DRIVE_FOLDERS"] = json.dumps(drive)
    if family() == "windows":
        settings.pop("HQ_DRIVE_FOLDERS", None)   # Google Drive for desktop keeps the folders in sync on the PC
    if saved:
        settings["HQ_SAVED_PATHS"] = json.dumps(saved, sort_keys=True)
    if manifest.get("timezone") and not settings.get("HQ_TZ"):
        settings["HQ_TZ"] = manifest["timezone"]
    return settings


def check_bundle(path: Path) -> dict:
    """Open the zip and make sure it's a whole HQ and safe to unpack. Returns its manifest (a plain backup gets one)."""
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        raise MoveError("That file isn't a zip from HQ.")
    with z:
        names = z.namelist()
        for n in names:
            _safe_parts(n)
        if f"data/{DB_PATH.name}" not in names:
            raise MoveError(f"{Path(path).name} isn't an HQ backup (there's no database inside).")
        if z.testzip() is not None:
            raise MoveError("The zip is damaged (it may not have finished copying). Nothing was changed.")
        manifest = json.loads(z.read(MANIFEST)) if MANIFEST in names else {"kind": "backup", "bundle_id": "",
                                                                           "platform": "", "data_dir": "", "root": ""}
    return manifest


def apply_bundle(path: Path) -> dict:
    """Unpack a move zip (or a backup) over this HQ. Stop HQ's agents first: a standby copy is fine.
    What it replaces is kept in data/before-move-<time>/. A plain backup comes back paused, because the copy it came
    from might still be running: press Resume once you're sure it isn't. Returns the manifest."""
    manifest = check_bundle(path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    keep = DATA_DIR / f"before-move-{stamp}"
    staging = DATA_DIR / "move-in"
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(path) as z:
        z.extractall(staging)   # every name was checked by check_bundle
    incoming_db = staging / "data" / DB_PATH.name
    with closing(sqlite3.connect(incoming_db)) as c:
        if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            shutil.rmtree(staging, ignore_errors=True)
            raise MoveError("The database in that zip is damaged. Nothing was changed.")

    # Keep what's here now, then put the new files in place.
    keep.mkdir(parents=True, exist_ok=True)
    for f in [DB_PATH, SETTINGS_PATH, ROOT / ".env"]:
        if f.exists():
            shutil.copy2(f, keep / f.name)
    if CONFIG_DIR.exists():
        shutil.copytree(CONFIG_DIR, keep / "config", dirs_exist_ok=True)
    for f in staging.rglob("*"):
        if not f.is_file():
            continue
        parts = f.relative_to(staging).parts
        dest = _dest(parts)
        if dest is None or dest == DB_PATH:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(f, dest) if f.stat().st_dev == dest.parent.stat().st_dev else shutil.copy2(f, dest)
    for suffix in ("-wal", "-shm"):   # the old database's journal must not be applied to the new one
        Path(str(DB_PATH) + suffix).unlink(missing_ok=True)
    os.replace(incoming_db, DB_PATH)

    # Fix paths, settings and folders for this computer.
    settings = json.loads((DATA_DIR / "settings.json").read_text(encoding="utf-8")) \
        if (DATA_DIR / "settings.json").exists() else {}
    settings = fix_settings(settings, manifest)
    for key in (manifest.get("external") or {}):
        src = staging / "external" / key
        if src.is_dir() and family() != family(manifest.get("platform")):
            dest = DATA_DIR / "moved-folders" / key
            shutil.copytree(src, dest, dirs_exist_ok=True)
            settings[key] = str(dest)
    if manifest.get("kind") != "move":
        settings["HQ_PAUSED"] = "true"
    settings.pop("HQ_PEER_URL", None)
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, SETTINGS_PATH)
    db.init()   # an older database gets any newer columns
    if manifest.get("data_dir"):
        for c in db.rows("SELECT id, path FROM clips"):
            new = relocate(c["path"] or "", manifest)
            if new != c["path"]:
                db.execute("UPDATE clips SET path = ? WHERE id = ?", new, c["id"])
    shutil.rmtree(staging, ignore_errors=True)
    return manifest


# ---- the move, over Tailscale -----------------------------------------------------------------------------------

def _log(entry: dict) -> None:
    try:
        log = json.loads(MOVE_LOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log = {}
    log.update(entry)
    MOVE_LOG.write_text(json.dumps(log, indent=2), encoding="utf-8")


def last() -> dict:
    try:
        return json.loads(MOVE_LOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def normalize_url(text: str) -> str:
    """'100.101.102.103' or 'agent-hq:8000' or a pasted address, as http://host:port."""
    t = (text or "").strip().rstrip("/")
    if not t:
        raise MoveError("Type the address of the other HQ first.")
    if not re.match(r"^https?://", t):
        t = "http://" + t
    host = re.sub(r"^https?://", "", t).split("/")[0]
    if ":" not in host.strip("[]").split("]")[-1]:
        t = t.split("://")[0] + "://" + host + ":8000"
    else:
        t = t.split("://")[0] + "://" + host
    return t


def _session(url: str, password: str):
    import requests
    s = requests.Session()
    s.headers["X-HQ"] = "1"
    try:
        health = s.get(f"{url}/healthz", timeout=10).json()
    except Exception:
        raise MoveError(f"Couldn't reach HQ at {url}. Check that the server is on and that Tailscale is on here.")
    if health.get("role") != "standby":
        raise MoveError(f"The HQ at {url} is already running the agents, so nothing was moved. "
                        "Moving onto it would make two copies post.")
    if health.get("instance") == standby.instance()["id"]:
        raise MoveError("That address is this HQ itself.")
    s.post(f"{url}/login", data={"password": password}, timeout=15, allow_redirects=False)
    r = s.get(f"{url}/api/move/ready", timeout=15)
    if r.status_code == 401:
        raise MoveError("The other HQ didn't accept the password.")
    if not r.ok:
        raise MoveError(f"The other HQ can't take a move ({r.status_code}): it may need updating first.")
    return s, health


def check_target(url: str, password: str) -> dict:
    """Can HQ move to this address? Returns what the other HQ said about itself."""
    _, health = _session(normalize_url(url), password)
    return health


def _wait_quiet(seconds: float = 45) -> None:
    from . import relay
    if not standby.posting_lock.acquire(timeout=20 * 60):   # an upload can take minutes; never cut one off
        raise MoveError("A clip has been posting for over 20 minutes, so I didn't move. Try again shortly.")
    standby.posting_lock.release()
    end = time.time() + seconds
    while relay.polling.is_set() and time.time() < end:
        time.sleep(0.5)


def send_to(url: str, password: str, progress=lambda text: None) -> dict:
    """Move this HQ to the HQ at `url` (see the top of this file). Returns {"url", "bundle_id", "clips_left_out"}."""
    url = normalize_url(url)
    if standby.is_standby() and (standby.info() or {}).get("reason") != "moving":
        raise MoveError("This copy is on standby, so it has nothing to move. Move from the copy that runs the agents.")
    progress("Checking the other HQ")
    s, _ = _session(url, password)
    standby.set_standby(True, reason="moving", moved_to=url)
    manifest = None
    try:
        progress("Waiting for any post in progress to finish")
        _wait_quiet()
        progress("Packing up HQ")
        out = DATA_DIR / "backups" / f"hq-move-{datetime.now():%Y%m%d-%H%M%S}.zip"
        manifest = make_bundle(out)
        progress(f"Sending it ({max(1, out.stat().st_size // (1024 * 1024))} MB)")
        with open(out, "rb") as f:
            r = s.post(f"{url}/api/move/in", files={"bundle": (out.name, f, "application/zip")},
                       data={"port": os.getenv("HQ_PORT", "8000")}, timeout=60 * 60)
        if not r.ok:
            raise MoveError(f"The other HQ couldn't take it: {_detail(r)}")
        progress("Waiting for the other HQ to restart")
        if not _wait_for(url, manifest["bundle_id"]):
            raise MoveError("The other HQ took the zip but didn't say it had started. Open it to check.")
    except Exception as e:
        state = _took_over(url, manifest["bundle_id"] if manifest else "")
        if state is False:     # the other HQ certainly didn't take over: this one carries on as before
            standby.set_standby(False)
            note = " This HQ carries on as before."
        elif state is True:    # it did after all
            return _moved(url, manifest)
        else:                  # can't tell: stay on standby rather than risk two copies posting
            note = (" I couldn't tell whether the other HQ took over, so this copy stays on standby to be safe. "
                    "Open the other HQ: if it shows your clips, the move worked.")
        msg = str(e) if isinstance(e, MoveError) else f"The move didn't finish: {e}"
        raise MoveError(msg + note) from e
    return _moved(url, manifest)


def _moved(url: str, manifest: dict) -> dict:
    standby.set_standby(True, reason="moved", moved_to=url)
    from . import settings
    settings.save({"HQ_PEER_URL": url})
    MOVE_CODE.unlink(missing_ok=True)
    _log({"sent_to": url, "sent_at": manifest["made"], "bundle_id": manifest["bundle_id"]})
    db.log("HQ", f"Moved HQ to {url}. This copy is on standby now: open HQ there.")
    _desktop_note(url)
    return {"url": url, "bundle_id": manifest["bundle_id"], "clips_left_out": manifest["clips_left_out"]}


def _detail(r) -> str:
    try:
        return str(r.json().get("detail"))[:300]
    except ValueError:
        return f"{r.status_code} {r.text[:200]}"


def _took_over(url: str, bundle_id: str) -> bool | None:
    """True if the other HQ runs the agents with this zip, False if it doesn't, None if it can't be asked.
    None counts as "maybe", so this copy stays on standby rather than risk two copies posting."""
    if not bundle_id:
        return False
    import requests
    try:
        h = requests.get(f"{url}/healthz", timeout=10).json()
    except Exception:
        return None
    return h.get("role") == "active" and h.get("moved_in") == bundle_id


def _wait_for(url: str, bundle_id: str, seconds: float = 300) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if _took_over(url, bundle_id):
            return True
        time.sleep(3)
    return False


def _desktop_note(url: str) -> None:
    """Leave the new address on the Windows Desktop, next to the Agent HQ icon (which opens it from now on)."""
    if sys.platform != "win32":
        return
    try:
        desktop = Path(os.path.expanduser("~")) / "Desktop"
        (desktop / "Agent HQ address.txt").write_text(
            f"Agent HQ now runs at {url}\r\nOpen it from any of your computers with Tailscale on.\r\n"
            f"The Agent HQ icon on this PC opens it too.\r\n", encoding="utf-8")
    except OSError:
        pass


def take_in(path: Path, from_url: str) -> dict:
    """The other side of send_to: unpack a move zip on this (standby) HQ and take over."""
    if not standby.is_standby():
        raise MoveError("This HQ is running the agents, so it can't take another copy over it.")
    manifest = apply_bundle(path)
    from . import settings
    if from_url:
        settings.save({"HQ_PEER_URL": from_url})
    # Still standby until HQ restarts with the new settings: running agents now, with the old keys still loaded,
    # would make posts fail (and a failed post is never retried on its own).
    standby.set_standby(True, reason="starting")
    _log({"moved_in": manifest.get("bundle_id", ""), "moved_in_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
          "from": from_url})
    db.log("HQ", f"HQ moved in from {from_url or 'a backup'}. This copy runs the agents now.")
    return manifest


# ---- setting up a new cloud server ------------------------------------------------------------------------------

def repo_url() -> str:
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True,
                             timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        url = ""
    return url if url.startswith("https://") else "https://github.com/stevenvictor247/CHADCLIP"


def move_code() -> str:
    """The one-time password a new server starts with, until your HQ moves in and brings your own password."""
    try:
        return json.loads(MOVE_CODE.read_text(encoding="utf-8"))["code"]
    except (OSError, ValueError, KeyError):
        code = secrets.token_urlsafe(18)
        MOVE_CODE.write_text(json.dumps({"code": code}), encoding="utf-8")
        return code


def cloud_script(tailscale_key: str) -> str:
    """The text to paste into the cloud provider's "user data" box: it sets up a new server with no typing."""
    key = (tailscale_key or "").strip()
    if not re.fullmatch(r"tskey-[A-Za-z0-9_-]+", key):
        raise MoveError("That doesn't look like a Tailscale auth key (it starts with tskey-). Copy it again.")
    tz = local_timezone() or "America/New_York"
    return f"""#!/bin/bash
# Agent HQ cloud server. Made by your HQ on {datetime.now():%b %d %Y}. Paste ALL of this into the
# cloud-init box when you create the server (Oracle: "Paste cloud-init script"; Vultr: "Cloud-Init User-Data"). It installs HQ by itself in about 10 minutes.
export HQ_PASSWORD='{move_code()}'
export HQ_TZ='{tz}'
export TS_AUTHKEY='{key}'
export HQ_WAITING=1
for i in 1 2 3 4 5; do apt-get update -q && apt-get install -y -q git && break; sleep 20; done
git clone {repo_url()} /opt/agent-hq || (cd /opt/agent-hq && git pull --ff-only)
bash /opt/agent-hq/deploy/cloud/install.sh > /var/log/agent-hq-install.log 2>&1
"""


def find_servers() -> list[dict]:
    """New or standby HQ servers on your Tailscale network (named agent-hq...), found without typing an address."""
    exe = shutil.which("tailscale") or next((p for p in (r"C:\Program Files\Tailscale\tailscale.exe",
                                                          "/Applications/Tailscale.app/Contents/MacOS/Tailscale")
                                             if Path(p).exists()), None)
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=15).stdout
        peers = (json.loads(out or "{}").get("Peer") or {}).values()
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    found = []
    for p in peers:
        name = (p.get("HostName") or "").lower()
        if not name.startswith("agent-hq"):
            name = (p.get("DNSName") or "").split(".")[0].lower()
        ips = [ip for ip in p.get("TailscaleIPs") or [] if "." in ip]
        if name.startswith("agent-hq") and ips:
            found.append({"name": p.get("HostName"), "url": f"http://{ips[0]}:8000", "online": bool(p.get("Online"))})
    return found
