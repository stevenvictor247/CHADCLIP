"""Keep HQ up to date: pull the latest code from GitHub before starting.

Only works when the HQ folder is a git copy. data/ and .env aren't in git so they're never touched, and
the pull refuses to run (and changes nothing) if it would overwrite files you've edited, like config/.
"""

import hashlib
import subprocess
import sys

from .config import ROOT

# Run git and pip without flashing a console window when started from the Desktop icon.
_QUIET = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def _run(*cmd, timeout=60):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, **_QUIET)


def _requirements_hash():
    path = ROOT / "requirements.txt"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def update():
    """Pull new code if there is any. Returns True when HQ's code changed and it should be restarted."""
    if not (ROOT / ".git").exists():
        print("Update skipped: this HQ folder isn't a git copy.")
        return False
    try:
        before, reqs = _run("git", "rev-parse", "HEAD").stdout.strip(), _requirements_hash()
        pull = _run("git", "pull", "--ff-only")
        if pull.returncode:
            print(f"Update skipped: {pull.stderr.strip()}")
            return False
        if _run("git", "rev-parse", "HEAD").stdout.strip() == before:
            return False
        print(f"Updated HQ:\n{pull.stdout.strip()}")
        if _requirements_hash() != reqs:
            pip = _run(sys.executable, "-m", "pip", "install", "-r", "requirements.txt", timeout=900)
            print(pip.stdout[-2000:] + pip.stderr[-2000:])
        return True
    except (OSError, subprocess.TimeoutExpired) as e:  # no git installed, or offline and it hung
        print(f"Update skipped: {e}")
        return False
