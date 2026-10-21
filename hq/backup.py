"""Zip the database and settings into data/backups so they can be downloaded or moved."""

import sqlite3
from contextlib import closing
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from .config import CLIPS_DIR, CONFIG_DIR, DATA_DIR, DB_PATH, ROOT, SETTINGS_PATH

BACKUP_DIR = DATA_DIR / "backups"


def make_backup(with_clips: bool = False, keep: int = 14) -> Path:
    """Write hq-backup-<time>.zip and delete all but the newest `keep` backups."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    out = BACKUP_DIR / f"hq-backup-{datetime.now():%Y%m%d-%H%M%S}.zip"
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        # SQLite's own backup copies a consistent snapshot even while the worker is writing
        snapshot = Path(tmp) / DB_PATH.name
        # closing(): sqlite3's own `with` doesn't close the file, and Windows can't delete an open one
        with closing(sqlite3.connect(DB_PATH)) as src, closing(sqlite3.connect(snapshot)) as dst:
            src.backup(dst)
        z.write(snapshot, f"data/{DB_PATH.name}")
        files = [p for p in CONFIG_DIR.rglob("*") if p.is_file()]
        if (ROOT / ".env").exists():
            files.append(ROOT / ".env")
        if SETTINGS_PATH.exists():
            files.append(SETTINGS_PATH)
        if with_clips:
            files += [p for p in CLIPS_DIR.rglob("*") if p.is_file()]
        for p in files:
            z.write(p, p.relative_to(ROOT) if p.is_relative_to(ROOT) else f"data/{p.relative_to(DATA_DIR)}")
    for old in sorted(BACKUP_DIR.glob("hq-backup-*.zip"))[:-keep]:
        old.unlink()
    return out
