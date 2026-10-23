"""Connect YouTube from the Settings page instead of a terminal command.

Two steps, both on the Settings page of the PC that runs HQ:
1. Paste the "OAuth client" file you download from Google Cloud (type: Desktop app). It's saved where accounts.yaml
   says (config/secrets/, which git never touches).
2. Press "Sign in with Google". HQ opens Google's sign-in in this computer's browser and saves the sign-in, so later
   uploads run unattended. The upload library renews it by itself.

Google ends sign-ins after 7 days while the app's consent screen is in "Testing", so the steps tell you to press
"Publish app" there first. An unverified app is fine for your own channel; Google just shows a warning screen.
"""

import json
import threading

from .agents.chad.publish import youtube
from .config import ROOT

SIGN_IN_TIMEOUT = 600  # seconds HQ waits for you to finish Google's sign-in before giving up

_jobs: dict[str, dict] = {}   # account name -> {"running": bool, "error": str, "done": bool}
_lock = threading.Lock()


class YouTubeError(Exception):
    pass


def _accounts() -> list[dict]:
    from .settings import accounts
    return [a for a in accounts() if a.get("platform") == "youtube"]


def _account(name: str) -> dict:
    for a in _accounts():
        if a.get("name") == name:
            return a
    raise YouTubeError(f"No YouTube account called {name} in accounts.yaml")


def _secret_path(account: dict):
    return ROOT / account.get("client_secrets_file", f"config/secrets/{account['name']}_client_secret.json")


def _token_path(account: dict):
    return ROOT / account.get("token_file", f"config/secrets/{account['name']}_token.json")


def status() -> list[dict]:
    out = []
    for a in _accounts():
        job = _jobs.get(a["name"], {})
        out.append({"name": a["name"], "has_client": _secret_path(a).exists(), "connected": _token_path(a).exists(),
                    "signing_in": bool(job.get("running")), "error": job.get("error", "")})
    return out


def save_client(name: str, text: str) -> str:
    """Check and save the OAuth client file Google gave you."""
    account = _account(name)
    try:
        data = json.loads(text)
    except ValueError:
        raise YouTubeError("That isn't the file from Google. Open the downloaded .json file and paste all of it.")
    if not isinstance(data, dict):
        raise YouTubeError("That isn't the file from Google. Open the downloaded .json file and paste all of it.")
    if "web" in data:
        raise YouTubeError("That client is a \"Web application\". In Google Cloud, create an OAuth client of type "
                           "\"Desktop app\" instead and paste that file.")
    client = data.get("installed") or {}
    if not client.get("client_id") or not client.get("client_secret"):
        raise YouTubeError("That file is missing the client ID or secret. Download it again from Google Cloud.")
    path = _secret_path(account)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return f"Saved the Google client for {name}. Now press Sign in with Google."


def _sign_in(account: dict):
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(str(_secret_path(account)), youtube.SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True, timeout_seconds=SIGN_IN_TIMEOUT,
                                  success_message="YouTube is connected to Agent HQ. You can close this tab.")
    path = _token_path(account)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json(), encoding="utf-8")


def _run(account: dict):
    name = account["name"]
    try:
        _sign_in(account)
        _jobs[name] = {"running": False, "done": True, "error": ""}
        from . import db
        db.log("Steven", f"Connected YouTube account {name}")
    except Exception as e:
        why = ("Google's sign-in wasn't finished within 10 minutes. Press Sign in with Google again."
               if "Timeout" in e.__class__.__name__ else str(e)[:300] or e.__class__.__name__)
        _jobs[name] = {"running": False, "done": False, "error": why}


def start_sign_in(name: str) -> str:
    """Open Google's sign-in in this computer's browser. Returns at once; status() shows how it went."""
    account = _account(name)
    if not _secret_path(account).exists():
        raise YouTubeError("Paste the Google client file first (step 1).")
    with _lock:
        if _jobs.get(name, {}).get("running"):
            return "Google's sign-in is already open. Finish it in your browser."
        _jobs[name] = {"running": True, "done": False, "error": ""}
    threading.Thread(target=_run, args=(account,), daemon=True, name=f"youtube-sign-in-{name}").start()
    return "Google's sign-in opened in this computer's browser. Pick your channel and allow uploads."


def disconnect(name: str) -> None:
    _token_path(_account(name)).unlink(missing_ok=True)
    _jobs.pop(name, None)
