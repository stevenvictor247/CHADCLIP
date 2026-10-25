"""Zip the database and settings into data/backups so they can be downloaded or moved."""

import os
import shutil
import sqlite3
from contextlib import closing
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from .config import CLIPS_DIR, CONFIG_DIR, DATA_DIR, DB_PATH, ROOT, SETTINGS_PATH

BACKUP_DIR = DATA_DIR / "backups"


def make_backup(with_clips: bool = False, keep: int = 14) -> Path:
    """Write hq-backup-<time>.zip and delete all but the newest `keep` backups. Also leaves a copy in
    HQ_BACKUP_COPY_DIR when that's set, so a dead drive can't take HQ and its backups together."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    out = BACKUP_DIR / f"hq-backup-{datetime.now():%Y%m%d-%H%M%S}.zip"
    _write(out, with_clips, secrets=True)
    _keep_newest(BACKUP_DIR, keep)
    copy_dir = os.getenv("HQ_BACKUP_COPY_DIR", "").strip()
    if copy_dir:
        _copy_elsewhere(Path(copy_dir), out.name, keep)
    return out


def _write(out: Path, with_clips: bool, secrets: bool):
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        # SQLite's own backup copies a consistent snapshot even while the worker is writing
        snapshot = Path(tmp) / DB_PATH.name
        # closing(): sqlite3's own `with` doesn't close the file, and Windows can't delete an open one
        with closing(sqlite3.connect(DB_PATH)) as src, closing(sqlite3.connect(snapshot)) as dst:
            src.backup(dst)
        z.write(snapshot, f"data/{DB_PATH.name}")
        secret_dir = CONFIG_DIR / "secrets"
        files = [p for p in CONFIG_DIR.rglob("*") if p.is_file() and (secrets or not p.is_relative_to(secret_dir))]
        if secrets and (ROOT / ".env").exists():
            files.append(ROOT / ".env")
        if secrets and SETTINGS_PATH.exists():
            files.append(SETTINGS_PATH)
        files += _state_files(secrets)
        if with_clips:
            files += [p for p in CLIPS_DIR.rglob("*") if p.is_file()]
        for p in files:
            z.write(p, p.relative_to(ROOT) if p.is_relative_to(ROOT) else f"data/{p.relative_to(DATA_DIR)}")


# Files in data/ that HQ needs to carry on where it left off: what was already clipped (so nothing posts twice), when the
# daily jobs last ran, and the football and tally folders. TikTok's sign-in lives here too, so it's kept to the full backup.
_STATE_FILES = ("worker_state.json", "chad_seen.json")
_STATE_DIRS = ("football", "tally")


def _state_files(secrets: bool) -> list[Path]:
    found = [DATA_DIR / n for n in _STATE_FILES] + ([DATA_DIR / "tiktok_tokens.json"] if secrets else [])
    for d in _STATE_DIRS:
        found += (DATA_DIR / d).rglob("*") if (DATA_DIR / d).is_dir() else []
    return [p for p in found if p.is_file()]


def restore(zip_path: Path) -> list[str]:
    """Put a backup back: database, Settings, keys, sign-ins. The database it replaces is kept beside it as
    hq.sqlite3.before-restore. This copy becomes the one that runs the agents (standby is switched off)."""
    from .standby import set_standby
    zip_path = Path(zip_path)
    restored = []
    with zipfile.ZipFile(zip_path) as z:
        if f"data/{DB_PATH.name}" not in z.namelist():
            raise ValueError(f"{zip_path.name} isn't an HQ backup (no database inside).")
        for info in z.infolist():
            if info.is_dir():
                continue
            parts = Path(info.filename).parts
            if parts[0] == "data":
                dest = DATA_DIR.joinpath(*parts[1:])
                base = DATA_DIR
            else:
                dest = ROOT.joinpath(*parts)
                base = ROOT
            if ".." in parts or not dest.resolve().is_relative_to(base.resolve()):
                raise ValueError(f"{info.filename} is outside the HQ folder; not restoring.")
            if dest == DB_PATH and dest.exists():
                shutil.copy2(dest, dest.with_name(dest.name + ".before-restore"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            restored.append(info.filename)
    set_standby(False)
    return restored


def _keep_newest(folder: Path, keep: int):
    for old in sorted(folder.glob("hq-backup-*.zip"))[:-keep]:
        old.unlink()


def _copy_elsewhere(folder: Path, name: str, keep: int):
    """The second copy leaves out your keys and passwords (.env, Settings, config/secrets): a synced folder like
    Google Drive is a fine place for your data, not for your keys. After a restore, paste the keys in Settings again."""
    from . import db
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / name
            _write(staged, with_clips=False, secrets=False)
            shutil.copy2(staged, folder / name)
        _keep_newest(folder, keep)
    except OSError as e:  # the folder is a Drive that isn't mounted, or full: say so, but keep the local backup
        db.log("HQ", f"Couldn't put the backup copy in {folder}: {e}")
