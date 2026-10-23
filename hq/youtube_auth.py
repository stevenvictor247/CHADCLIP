"""Connect YouTube from the Settings page instead of a terminal command.

Two steps, both on the Settings page of the PC that runs HQ:
1. Paste the "OAuth client" file you download from Google Cloud (type: Desktop app). It's saved where accounts.yaml
   says (config/secrets/, which git never touches).
2. Press "Open Google sign-in" and approve in ANY browser (the Mac works). Google then sends you to a page on
   "localhost" that can't load; that's expected. Copy the address from the address bar and paste it back into
   Settings. HQ swaps it for a sign-in saved on the PC, so later uploads run unattended. The upload library renews it.

Google ends sign-ins after 7 days while the app's consent screen is in "Testing", so the steps tell you to press
"Publish app" there first. An unverified app is fine for your own channel; Google just shows a warning screen.
"""

import json
from urllib.parse import parse_qs, urlparse

from .agents.chad.publish import youtube
from .config import ROOT

REDIRECT = "http://localhost:8080/"  # Desktop-app clients accept any localhost address; the page never has to load

_pending: dict[str, dict] = {}   # account name -> {"state": ..., "verifier": ...} while a sign-in is open


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
    return [{"name": a["name"], "has_client": _secret_path(a).exists(), "connected": _token_path(a).exists(),
             "waiting": a["name"] in _pending} for a in _accounts()]


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
    return f"Saved the Google client for {name}. Now press Open Google sign-in."


def _flow(account: dict):
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_secrets_file(str(_secret_path(account)), scopes=youtube.SCOPES, redirect_uri=REDIRECT)


def start_sign_in(name: str) -> str:
    """The Google sign-in link. Open it in any browser, approve, then paste back the address you end up on."""
    account = _account(name)
    if not _secret_path(account).exists():
        raise YouTubeError("Paste the Google client file first (step 1).")
    flow = _flow(account)
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    _pending[name] = {"state": state, "verifier": flow.code_verifier}
    return url


def parse_answer(text: str, state: str) -> str:
    """The code from what you pasted: the whole address Google sent you to, or just the code."""
    text = (text or "").strip()
    if not text:
        raise YouTubeError("Paste the address from the page Google sent you to.")
    if "://" not in text and "code=" not in text and "error=" not in text:
        return text
    q = parse_qs(urlparse(text).query)
    if q.get("error"):
        raise YouTubeError(f"Google said no: {q['error'][0]}")
    if not q.get("code"):
        raise YouTubeError("That address has no code in it. Copy the whole address from the address bar.")
    if q.get("state") and q["state"][0] != state:
        raise YouTubeError("That address is from an older sign-in. Press Open Google sign-in again and use the new one.")
    return q["code"][0]


def finish_sign_in(name: str, answer: str) -> str:
    account = _account(name)
    pending = _pending.get(name)
    if not pending:
        raise YouTubeError("Press Open Google sign-in first (step 2).")
    code = parse_answer(answer, pending["state"])
    flow = _flow(account)
    flow.code_verifier = pending["verifier"]
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise YouTubeError(f"Google wouldn't accept that: {str(e)[:200] or e.__class__.__name__}. "
                           "Press Open Google sign-in again for a fresh one.")
    path = _token_path(account)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(flow.credentials.to_json(), encoding="utf-8")
    _pending.pop(name, None)
    from . import db
    db.log("Steven", f"Connected YouTube account {name}")
    return f"YouTube is connected for {name}."


def disconnect(name: str) -> None:
    _token_path(_account(name)).unlink(missing_ok=True)
    _pending.pop(name, None)
