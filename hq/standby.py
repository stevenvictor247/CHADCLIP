"""Only one copy of HQ runs the agents: your PC or the cloud server, never both.

The copy that isn't running them is on standby. A standby copy still opens and shows its data, but it is read-only:
no agent works, nothing posts or sends, the Telegram bot is quiet, the Thursday print is off, and every button that
would change something says where HQ runs now. Without this the PC and the cloud would post every clip twice.

Two locks make sure of it:
- standby.json in data/ (backups never carry it, so restoring a backup can't copy it to another computer);
- the peer check: the copy that runs the agents asks the other one (HQ_PEER_URL) whether it runs them too before it
  posts. If both do, the one that took over last stops and tells you. If the other one can't be reached (the PC is
  off), nothing changes.
"""

import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone

from .config import DATA_DIR

FLAG = DATA_DIR / "standby.json"
INSTANCE = DATA_DIR / "instance.json"   # this copy's own id; never in a backup, so every copy has its own
PEER_EVERY = 60                         # seconds between asks to the other copy
PEER_TIMEOUT = 5

# Held while clips are being posted, so a move or an update restart can wait for a post to finish instead of
# cutting it off halfway (a half-finished post that isn't recorded would go out again on the other computer).
posting_lock = threading.RLock()
stopping = threading.Event()   # set while HQ shuts down: no new post starts


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read(path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def info() -> dict | None:
    """Why this copy is on standby: {"reason": ..., "moved_to": url, "since": time}. Reasons: "waiting" (a new server
    waiting for your HQ), "moving" (sending itself right now), "moved" (it went to moved_to), "starting" (your HQ just
    moved in and it's restarting to take over) and "manual"."""
    if not FLAG.exists():
        return None
    return _read(FLAG) or {"reason": "manual"}


def is_standby() -> bool:
    return FLAG.exists()


def set_standby(on: bool, reason: str = "manual", moved_to: str = "") -> None:
    if on:
        _write(FLAG, {"reason": reason, "moved_to": moved_to.rstrip("/"), "since": _now()})
    else:
        FLAG.unlink(missing_ok=True)
        inst = instance()
        inst["active_since"] = _now()   # the newest copy to take over is the one that steps back in a clash
        _write(INSTANCE, inst)
    _peer_cache.clear()


def finish_takeover() -> bool:
    """HQ just restarted after another copy moved in: from now on this copy runs the agents."""
    if (info() or {}).get("reason") == "starting":
        set_standby(False)
        return True
    return False


def instance() -> dict:
    """{"id": ..., "active_since": ...}, made the first time it's asked for."""
    inst = _read(INSTANCE)
    if not inst.get("id"):
        inst = {"id": secrets.token_hex(8), "active_since": inst.get("active_since") or _now()}
        _write(INSTANCE, inst)
    return inst


def role() -> dict:
    """What this copy tells the other one (and anyone checking it's alive) at /healthz."""
    s, inst = info(), instance()
    return {"ok": True, "role": "standby" if s else "active", "waiting": bool(s and s.get("reason") == "waiting"),
            "moved_to": (s or {}).get("moved_to", ""), "instance": inst["id"], "active_since": inst["active_since"]}


# ---- the peer check ------------------------------------------------------------------------------------------

_peer_cache: dict = {}


def peer_url() -> str:
    return os.getenv("HQ_PEER_URL", "").strip().rstrip("/")


def _ask_peer(url: str) -> dict | None:
    import requests
    try:
        r = requests.get(f"{url}/healthz", timeout=PEER_TIMEOUT)
        data = r.json() if r.ok else None
        return data if isinstance(data, dict) and data.get("ok") else None
    except Exception:   # off, asleep, or no Tailscale right now: that's normal for a PC
        return None


def clash() -> str | None:
    """A plain reason when the other copy also runs the agents and this one should step back, else None."""
    url = peer_url()
    if not url or is_standby():
        return None
    cached = _peer_cache.get(url)
    if cached and time.time() - cached[0] < PEER_EVERY:
        return cached[1]
    peer, me = _ask_peer(url), instance()
    reason = None
    if peer and peer.get("role") == "active" and peer.get("instance") != me["id"]:
        theirs, mine = str(peer.get("active_since") or ""), str(me["active_since"])
        if (theirs, str(peer.get("instance"))) < (mine, me["id"]):   # they took over first, so they keep running
            reason = (f"The copy of HQ at {url} is also running the agents. This copy took over after it, so it "
                      f"stopped to avoid posting twice. Put one of them on standby.")
    _peer_cache[url] = (time.time(), reason)
    return reason


def blocked() -> str | None:
    """Why this copy must not run agents, post or send right now, or None when it may."""
    s = info()
    if s:
        where = f" HQ runs at {s['moved_to']}." if s.get("moved_to") else ""
        if s.get("reason") == "waiting":
            return "This new HQ is waiting for your HQ to move in."
        return "This copy of HQ is on standby." + where
    return clash()
