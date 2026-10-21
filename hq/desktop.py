"""HQ as a desktop app: the dashboard in its own window, plus a Desktop shortcut that opens it."""

import subprocess
import sys
import threading
import time
from pathlib import Path

from .config import DATA_DIR, PASSWORD, ROOT

PORT = 8000
ICON = ROOT / "hq" / "static" / "hq.ico"


from .update import port_in_use as _running


def _serve(host, port):
    import uvicorn

    from .worker import start_in_background
    start_in_background()
    uvicorn.run("hq.api:app", host=host, port=port)


def open_app(port=PORT, update=True, wait_port=False):
    """Open HQ in its own window. Starts HQ first unless it's already running (e.g. from start-hq.bat)."""
    # The shortcut runs without a console window, so send output to a log file you can read if something breaks.
    if sys.stdout is None or not sys.stdout.isatty():
        log = open(DATA_DIR / "desktop-app.log", "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stderr = log

    if wait_port:  # restarting: let the old HQ finish closing first
        from .update import wait_for_port
        wait_for_port(port)
    if not _running(port):
        from .update import update as pull_latest
        if update and pull_latest():
            # New code arrived: start again so it's the new code that runs.
            subprocess.Popen([sys.executable, "-m", "hq", "app", "--no-update"], cwd=ROOT)
            return
        # With a password set, keep HQ reachable from your other computers while the window is open.
        host = "0.0.0.0" if PASSWORD else "127.0.0.1"
        threading.Thread(target=_serve, args=(host, port), daemon=True).start()
        for _ in range(100):
            if _running(port):
                break
            time.sleep(0.2)

    try:
        import webview
    except ImportError:
        # pywebview didn't install: use Edge's app mode instead, and keep HQ running until you sign out.
        subprocess.Popen([r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                          f"--app=http://127.0.0.1:{port}"])
        threading.Event().wait()

    webview.create_window("Agent HQ", f"http://127.0.0.1:{port}", width=1400, height=900, min_size=(900, 600))
    # Remember the login between launches.
    webview.start(private_mode=False, storage_path=str(DATA_DIR / "desktop-app"))


def install_shortcut():
    """Put an "Agent HQ" icon on the Windows Desktop that opens the app with no console window."""
    if sys.platform != "win32":
        sys.exit("The desktop shortcut is for Windows. Run `python -m hq app` to open the window here.")
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    q = lambda p: str(p).replace("'", "''")  # PowerShell quoting
    script = f"""
$desktop = [Environment]::GetFolderPath('Desktop')
$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop 'Agent HQ.lnk'))
$s.TargetPath = '{q(pythonw)}'
$s.Arguments = '-m hq app'
$s.WorkingDirectory = '{q(ROOT)}'
$s.IconLocation = '{q(ICON)}'
$s.Description = 'Open Agent HQ'
$s.Save()
Write-Output (Join-Path $desktop 'Agent HQ.lnk')
"""
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True)
    if out.returncode:
        sys.exit(out.stderr)
    return out.stdout.strip()
