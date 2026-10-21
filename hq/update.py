"""Keep HQ up to date: check GitHub for new code, pull it, and restart.

Only works when the HQ folder is a git copy (the installer makes one). data/ and .env aren't in git so they're never
touched. If you (or the Boss) changed a file in config/, your version is kept. Any other file you edited is copied
to data/update-backups/ and then replaced with the new version, so an edit can never block an update again.

Updates come from the "tested" branch, which GitHub moves forward only after every test passed on Linux and Windows
(.github/workflows/tests.yml). Newer changes on main wait there until their tests pass. A copy whose GitHub has no
"tested" branch yet updates from main as before.
"""

import hashlib
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from .config import DATA_DIR, ROOT

# Run git and pip without flashing a console window when started from the Desktop icon.
_QUIET = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
CHECK_EVERY = 30 * 60  # seconds between "is there an update?" checks while HQ runs
RESTART_CODE = 3       # start-hq.bat (and the cloud server) start HQ again when it exits with this
TESTED = "origin/tested"  # moved forward by GitHub once a version passed every test
_status = {"checked": 0}
_lock = threading.Lock()


def _git():
    found = shutil.which("git")
    if not found and sys.platform == "win32":  # installed a moment ago and PATH hasn't caught up
        for p in (r"C:\Program Files\Git\cmd\git.exe", os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe")):
            if Path(p).exists():
                return p
    return found or "git"


def _run(*cmd, timeout=60):
    if cmd[0] == "git":
        cmd = (_git(),) + cmd[1:]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, **_QUIET)


def _out(*cmd, timeout=60):
    r = _run(*cmd, timeout=timeout)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip() or f"{' '.join(cmd)} failed")
    return r.stdout.strip()


def _requirements_hash():
    path = ROOT / "requirements.txt"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def is_git_copy() -> bool:
    return (ROOT / ".git").exists()


def _target() -> str:
    """Where updates come from: the last version that passed the tests, or main if GitHub has no tested branch."""
    return TESTED if _run("git", "rev-parse", "--verify", "--quiet", TESTED).returncode == 0 else "@{u}"


def check(force: bool = False) -> dict:
    """Is there new code on GitHub? Cached for CHECK_EVERY seconds unless force."""
    with _lock:
        if not force and time.time() - _status["checked"] < CHECK_EVERY:
            return dict(_status)
        status = {"checked": time.time(), "git": is_git_copy(), "available": False, "count": 0, "changes": [],
                  "tested": False, "testing": 0, "error": "", "version": ""}
        if status["git"]:
            try:
                status["version"] = _out("git", "log", "-1", "--format=%h, %cd", "--date=format:%b %d")
                _out("git", "fetch", "--quiet", "origin", timeout=120)
                target = _target()
                status["tested"] = target == TESTED
                status["count"] = int(_out("git", "rev-list", "--count", f"HEAD..{target}") or 0)
                status["available"] = status["count"] > 0
                if status["tested"]:  # changes on GitHub still waiting for their tests to pass
                    status["testing"] = int(_out("git", "rev-list", "--count", f"HEAD..@{{u}}", f"^{TESTED}") or 0)
                if status["available"]:
                    log = _out("git", "log", "--no-merges", "--format=%s", "-n", "8", f"HEAD..{target}")
                    status["changes"] = [line for line in log.splitlines() if line]
            except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as e:
                status["error"] = str(e)[:300]
        _status.clear()
        _status.update(status)
        return dict(_status)


def _backup(paths, stamp):
    dest = DATA_DIR / "update-backups" / stamp
    for rel in paths:
        src = ROOT / rel
        if src.is_file():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)
    return dest


def update():
    """Pull new code if there is any. Returns True when HQ's code changed and it should be restarted."""
    if not is_git_copy():
        print("Update skipped: this HQ folder isn't a git copy. Run Install-Agent-HQ.bat once to fix that.")
        return False
    try:
        _out("git", "fetch", "--quiet", "origin", timeout=120)
        target = _target()
        if _out("git", "rev-list", "--count", f"HEAD..{target}") == "0":
            return False
        before, reqs = _out("git", "rev-parse", "HEAD"), _requirements_hash()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

        # Files you changed, and files you made that the update would add too.
        edited = _out("git", "diff", "--name-only", "HEAD").splitlines()
        incoming = _out("git", "diff", "--name-only", "--diff-filter=A", "HEAD", target).splitlines()
        clashing = [p for p in incoming if (ROOT / p).exists()]
        touched = [p for p in dict.fromkeys(edited + clashing) if p]
        keep = {p: (ROOT / p).read_bytes() for p in touched if p.startswith("config/") and (ROOT / p).is_file()}
        if touched:
            print(f"Saved your copies of {', '.join(touched)} in {_backup(touched, stamp)}")
            tracked = [p for p in touched if p in edited]
            if tracked:
                _out("git", "checkout", "--", *tracked)
            for p in clashing:
                (ROOT / p).unlink()

        if _run("git", "merge", "--ff-only", target).returncode:
            # Someone committed in this folder. Keep those commits on a branch, then take GitHub's version.
            _out("git", "branch", f"before-update-{stamp}")
            _out("git", "reset", "--hard", target)
            print(f"Local commits kept on branch before-update-{stamp}")
        for p, data in keep.items():
            (ROOT / p).parent.mkdir(parents=True, exist_ok=True)
            (ROOT / p).write_bytes(data)
        if keep:
            print(f"Kept your version of {', '.join(keep)}")

        print("Updated HQ:\n" + _out("git", "log", "--no-merges", "--format=  %s", f"{before}..HEAD"))
        if _requirements_hash() != reqs:
            pip = _run(sys.executable, "-m", "pip", "install", "-r", "requirements.txt", timeout=900)
            print(pip.stdout[-2000:] + pip.stderr[-2000:])
        with _lock:
            _status["checked"] = 0
        return True
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:  # no git, offline, or git refused
        print(f"Update skipped: {e}")
        return False


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for_port(port: int, seconds: float = 20):
    """After a restart, wait for the old HQ to let go of its port."""
    end = time.time() + seconds
    while port_in_use(port) and time.time() < end:
        time.sleep(0.3)


def restart(delay: float = 1.0):
    """Start HQ again (new code, new settings). Runs after a short delay so the web page gets its answer first."""
    def go():
        time.sleep(delay)
        if os.getenv("HQ_SUPERVISED"):  # start-hq.bat or the cloud service will start HQ again
            os._exit(RESTART_CODE)
        args = [a for a in sys.argv[1:] if a != "--wait-port"]
        if args[:1] == ["app"] and "--no-update" not in args:
            args.append("--no-update")
        subprocess.Popen([sys.executable, "-m", "hq", *args, "--wait-port"], cwd=ROOT)
        os._exit(0)
    threading.Thread(target=go, daemon=True).start()


def check_in_background():
    """Look for updates every CHECK_EVERY seconds so the dashboard can say when one is ready."""
    def loop():
        while True:
            check(force=True)
            time.sleep(CHECK_EVERY)
    threading.Thread(target=loop, daemon=True).start()
