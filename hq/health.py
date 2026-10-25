"""The cloud server's watchdog: every 5 minutes it checks HQ is alive and well, fixes what it can, and tells you.

What it checks (python -m hq health --fix, run by a systemd timer on the server):
- the dashboard answers, and the agents' loop went round in the last 10 minutes. If not, HQ is restarted
  (exit code 2 tells the timer to restart it) and you get a Telegram message;
- the disk isn't nearly full, the last backup isn't more than a day and a half old, and Tailscale won't sign the server
  out (key expiry), each sent to your phone at most once a day;
- HQ_HEALTHCHECK_URL (optional, from healthchecks.io) gets a ping when all is well. That service messages you when the
  pings stop, which covers the one thing HQ can't report itself: the whole server being down.
After HQ has run fine for 10 minutes on a version, that version is remembered as good. If a new version won't start,
`python -m hq rollback` (run by systemd when HQ fails 8 times in 5 minutes) goes back to it and skips the bad one
until a newer update arrives.
"""

import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .config import DATA_DIR, ROOT

STATE_PATH = DATA_DIR / "health.json"
GOOD_PATH = DATA_DIR / "good-version.txt"
STUCK_MINUTES = 10
GOOD_AFTER = 10 * 60
DISK_FULL = 0.90
ALERT_EVERY = 24 * 3600


def _state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(s: dict) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def _alert(key: str, text: str, every: float = ALERT_EVERY) -> None:
    """Tell Steven (Telegram and the activity feed), but the same problem at most once per `every` seconds."""
    from . import db, relay
    s = _state()
    sent = s.setdefault("alerts", {})
    if time.time() - sent.get(key, 0) < every:
        return
    sent[key] = time.time()
    _save(s)
    db.log("HQ", text)
    relay.notify(f"🩺 {text}")


def _healthz(port: int) -> dict | None:
    import requests
    try:
        r = requests.get(f"http://127.0.0.1:{port}/healthz", timeout=20)
        return r.json() if r.ok else None
    except Exception:
        return None


def _git(*args) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip() or "git failed")
    return r.stdout.strip()


def _newest_backup_age() -> float | None:
    zips = sorted((DATA_DIR / "backups").glob("hq-backup-*.zip"), key=lambda p: p.stat().st_mtime)
    return time.time() - zips[-1].stat().st_mtime if zips else None


def _tailscale_expiry() -> str | None:
    exe = shutil.which("tailscale")
    if not exe:
        return None
    try:
        me = json.loads(subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=15).stdout
                        or "{}").get("Self") or {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return me.get("KeyExpiry") or None


def check(fix: bool = False, port: int | None = None) -> list[str]:
    """Problems found (empty when healthy). With fix, alerts go out and SystemExit(2) asks for a restart."""
    port = port or int(os.getenv("HQ_PORT", "8000"))
    problems, restart = [], False
    h = _healthz(port)
    if h is None:
        problems.append("HQ's dashboard isn't answering.")
        restart = True
    else:
        quiet = h.get("worker_seconds_ago")
        if h.get("role") == "active" and quiet is not None and quiet > STUCK_MINUTES * 60:
            problems.append(f"The agents' loop hasn't gone round for {round(quiet / 60)} minutes.")
            restart = True
        if h.get("role") == "active" and not restart and (h.get("uptime") or 0) > GOOD_AFTER:
            try:
                GOOD_PATH.write_text(_git("rev-parse", "HEAD"), encoding="utf-8")
            except (OSError, RuntimeError, subprocess.SubprocessError):
                pass

    usage = shutil.disk_usage(DATA_DIR)
    if usage.used / usage.total > DISK_FULL:
        msg = (f"The server's disk is {round(100 * usage.used / usage.total)}% full. Sweep clears old downloads; "
               "if it stays full, ask the Boss what's using the space.")
        problems.append(msg)
        if fix:
            _alert("disk", msg)
    age = _newest_backup_age()
    if h and h.get("role") == "active" and age is not None and age > 36 * 3600:
        msg = f"HQ's last backup is {round(age / 3600)} hours old (it should be daily)."
        problems.append(msg)
        if fix:
            _alert("backup", msg)
    expiry = _tailscale_expiry()
    if expiry:
        msg = ("Tailscale will sign the cloud server out on " + expiry[:10] + ". In the Tailscale admin page, open "
               "Machines, click agent-hq's ⋯ menu and choose Disable key expiry.")
        problems.append(msg)
        if fix:
            _alert("tailscale", msg, every=7 * 24 * 3600)

    if fix:
        if restart:
            s = _state()
            recent = [t for t in s.get("restarts", []) if time.time() - t < 3600] + [time.time()]
            s["restarts"] = recent
            _save(s)
            _alert("restart", ("HQ stopped responding, so I restarted it. " + " ".join(problems[:2])) if len(recent) < 3
                   else "HQ keeps getting stuck: restarted 3 times in an hour. Ask Claude to look at the server log.",
                   every=3600)
        url = os.getenv("HQ_HEALTHCHECK_URL", "").strip()
        if url:
            import requests
            try:
                requests.get(url + ("/fail" if restart else ""), timeout=10)
            except Exception:
                pass
        if restart:
            raise SystemExit(2)
    return problems


def rollback() -> str:
    """Go back to the last version that ran fine here, keeping your config/ files, and skip the one that didn't."""
    from . import db, relay
    from .update import BAD_PATH
    try:
        good = GOOD_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        good = ""
    head = _git("rev-parse", "HEAD")
    if not good or good == head:
        msg = "HQ won't start, and there's no earlier version that ran fine here to go back to."
        db.log("HQ", msg)
        relay.notify(f"🩺 {msg} Ask Claude to look at the server log.")
        return msg
    edited = [p for p in _git("diff", "--name-only", "HEAD").splitlines() if p.startswith("config/")]
    keep = {p: (ROOT / p).read_bytes() for p in edited if (ROOT / p).is_file()}
    reqs = (ROOT / "requirements.txt").read_bytes() if (ROOT / "requirements.txt").exists() else b""
    _git("reset", "--hard", good)
    for p, data in keep.items():
        (ROOT / p).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / p).write_bytes(data)
    BAD_PATH.write_text(head, encoding="utf-8")
    if (ROOT / "requirements.txt").exists() and (ROOT / "requirements.txt").read_bytes() != reqs:
        import sys
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"], cwd=ROOT, timeout=900)
    msg = (f"A new HQ version ({head[:7]}) wouldn't start, so I went back to the last one that worked ({good[:7]}). "
           f"HQ will take the next update once it's fixed. {datetime.now():%b %d %H:%M}")
    db.log("HQ", msg)
    relay.notify(f"🩺 {msg}")
    return msg
