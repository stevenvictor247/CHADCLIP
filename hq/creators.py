"""Creators Scout suggests clipping. Suggestions only: Chad clips nobody until you record how you're allowed to.

Candidates come from the Twitch API (public data, your own Twitch app keys). Scout reads each channel's bio for signs
that clippers are welcome, with plain rules and no Claude call, so finding creators costs nothing.
"""

import json
import re

import yaml

from . import db
from .config import CONFIG_DIR

# Words in a bio or panel text that suggest a clipping program or a team that welcomes clippers.
SIGNALS = (
    (re.compile(r"clipping (program|campaign|team|discord)|clippers?\b|clip (program|farm|team)", re.I), "mentions clippers"),
    (re.compile(r"business|inquir|sponsor|collab", re.I), "has a business contact"),
    (re.compile(r"discord\.(gg|com)", re.I), "has a Discord"),
)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def signals_for(bio: str) -> list[str]:
    out = [label for rx, label in SIGNALS if rx.search(bio or "")]
    if EMAIL.search(bio or "") and "has a business contact" not in out:
        out.append("has a business contact")
    return out


def rank(c: dict) -> float:
    """Bigger recent clip views and clipper-friendly signals first."""
    return c["clip_views"] / 1000 + 50 * ("mentions clippers" in c["signals"]) + 10 * len(c["signals"])


def known(login: str) -> bool:
    return bool(db.rows("SELECT 1 FROM creator_picks WHERE login = ?", login.lower()))


def add(c: dict) -> int:
    return db.execute(
        "INSERT INTO creator_picks (login, name, viewers, clip_views, top_clip, bio, signals, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", c["login"].lower(), c["name"], c["viewers"], c["clip_views"],
        c.get("top_clip"), (c.get("bio") or "")[:400], json.dumps(c["signals"]), db.now())


def pending() -> list[dict]:
    out = db.rows("SELECT * FROM creator_picks WHERE status = 'new'")
    for r in out:
        r["signals"] = json.loads(r["signals"])
    return sorted(out, key=lambda c: -rank({"clip_views": c["clip_views"], "signals": c["signals"]}))


def skip(pick_id: int) -> str:
    rows = db.rows("SELECT * FROM creator_picks WHERE id = ?", pick_id)
    if not rows:
        raise ValueError(f"No creator suggestion #{pick_id}")
    db.execute("UPDATE creator_picks SET status = 'skipped' WHERE id = ?", pick_id)
    return f"Skipped {rows[0]['name']}."


def record_permission(login: str, how: str) -> None:
    """Write "login: how" into config/streamers.yaml, the file Chad reads. Raises ValueError if it can't be saved."""
    how = " ".join((how or "").split())
    login = login.lower()
    if len(how) < 5:
        raise ValueError("Say how you're allowed to clip them, for example \"clipping program, joined today\"")
    path = CONFIG_DIR / "streamers.yaml"
    original = path.read_text(encoding="utf-8") if path.exists() else "permissions:\n"
    updated = original.rstrip("\n") + f"\n  {login}: {json.dumps(how)}\n"
    if "permissions" not in (yaml.safe_load(original) or {}):
        raise ValueError("config/streamers.yaml has no permissions: section")
    if (yaml.safe_load(updated)["permissions"] or {}).get(login) != how:
        raise ValueError("Couldn't save that into config/streamers.yaml")
    path.write_text(updated, encoding="utf-8")


def permit(pick_id: int, how: str) -> str:
    """Steven says how he's allowed to clip this creator. It goes into config/streamers.yaml, which Chad reads."""
    rows = db.rows("SELECT * FROM creator_picks WHERE id = ?", pick_id)
    if not rows:
        raise ValueError(f"No creator suggestion #{pick_id}")
    record_permission(rows[0]["login"], how)
    db.execute("UPDATE creator_picks SET status = 'permitted' WHERE id = ?", pick_id)
    db.log("Steven", f"Permission recorded for {rows[0]['name']}: {' '.join(how.split())}")
    return f"Saved. Chad can now clip {rows[0]['name']}."


def clean_login(raw: str) -> str:
    """Twitch login from what Steven typed: a name, @name, or a twitch.tv link."""
    login = (raw or "").strip().lower().rstrip("/")
    login = re.sub(r"^(https?://)?(www\.)?twitch\.tv/", "", login).lstrip("@").split("/")[0].split("?")[0]
    if not re.fullmatch(r"[a-z0-9_]{3,25}", login):
        raise ValueError("That doesn't look like a Twitch name. Type it like jynxzi, or paste their twitch.tv link")
    return login


def allowed() -> list[dict]:
    """Streamers Chad may clip right now, from config/streamers.yaml."""
    path = CONFIG_DIR / "streamers.yaml"
    data = (yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None) or {}
    return [{"login": str(k).lower(), "how": str(v or "").strip()}
            for k, v in (data.get("permissions") or {}).items() if str(v or "").strip()]


def add_allowed(raw_login: str, how: str) -> str:
    """Steven adds a streamer himself, with how he's allowed to clip them. Same file and rule as permit()."""
    login = clean_login(raw_login)
    if any(a["login"] == login for a in allowed()):
        raise ValueError(f"{login} is already on the list")
    record_permission(login, how)
    db.log("Steven", f"Permission recorded for {login}: {' '.join(how.split())}")
    return f"Saved. Chad can now clip {login}."
