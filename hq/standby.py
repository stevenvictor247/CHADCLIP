"""Standby: this copy of HQ opens and shows its data, but its agents, posting, and Telegram bot are off.

Only one computer should run HQ's agents at a time, or the PC and the cloud server would post everything twice. The
flag is a plain file in data/ that backups never include, so restoring a backup can't carry it to another computer.
"""

from .config import DATA_DIR

FLAG = DATA_DIR / "standby.flag"


def is_standby() -> bool:
    return FLAG.exists()


def set_standby(on: bool):
    if on:
        FLAG.write_text("This copy of HQ is on standby: another computer runs the agents.\n", encoding="utf-8")
    else:
        FLAG.unlink(missing_ok=True)
