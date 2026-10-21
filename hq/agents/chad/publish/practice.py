"""The practice account: "posts" a clip by saving it, with its caption, to data/practice-posts instead of uploading.

Lets you run the whole chain (Chad, the Boss's review, your approval, posting) before any real account is connected.
It's on by itself until a real account is switched on; HQ_PRACTICE_POSTING=true or false overrides that.
"""

import os
import shutil
from pathlib import Path

from ....config import DATA_DIR

FOLDER = DATA_DIR / "practice-posts"


def account(real_accounts: list[dict]) -> dict:
    """The practice account, switched on or off by the setting (auto: on while no real account is on)."""
    mode = os.getenv("HQ_PRACTICE_POSTING", "auto").strip().lower()
    on = mode == "true" or (mode not in ("true", "false") and not any(a.get("enabled") for a in real_accounts))
    return {"name": "practice", "platform": "practice", "enabled": on}


def publish(clip: dict, account: dict) -> tuple[str, str | None]:
    FOLDER.mkdir(parents=True, exist_ok=True)
    stem = f"clip-{clip['id']}"
    shutil.copy2(clip["path"], FOLDER / f"{stem}{Path(clip['path']).suffix or '.mp4'}")
    (FOLDER / f"{stem}.txt").write_text(f"{clip.get('title') or ''}\n\n{clip['post_text']}\n", encoding="utf-8")
    return stem, None
