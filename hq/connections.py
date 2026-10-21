"""Test buttons: one harmless call per service, to check a key works before an agent needs it.

Nothing here posts, uploads or spends more than a fraction of a cent. Each test returns
{"ok": bool, "message": plain words for Steven}. Results are remembered in data/connection_tests.json so the
getting-started checklist can show them without calling every service on each page load.
"""

import json
import os
import time

import requests

from .config import DATA_DIR, ROOT

RESULTS_PATH = DATA_DIR / "connection_tests.json"
TIMEOUT = 20


def _v(key: str, values: dict | None) -> str:
    """A value typed on the Settings page (not saved yet) wins over the saved one."""
    if values and values.get(key, "").strip():
        return values[key].strip()
    return os.getenv(key, "").strip()


def _ok(message: str) -> dict:
    return {"ok": True, "message": message}


def _bad(message: str) -> dict:
    return {"ok": False, "message": message}


def _offline(service: str) -> dict:
    return _bad(f"Couldn't reach {service}. Check this computer is online, then try again.")


def claude(values=None) -> dict:
    key = _v("ANTHROPIC_API_KEY", values)
    if not key:
        return _bad("No key yet. Make one at console.anthropic.com under API Keys and paste it here.")
    try:
        # A one-token reply from the cheapest model: costs a tiny fraction of a cent and also proves billing works.
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=TIMEOUT, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-5-5", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]})
    except requests.RequestException:
        return _offline("Claude")
    if r.status_code == 200:
        return _ok("Claude key works.")
    detail = ""
    try:
        detail = r.json().get("error", {}).get("message", "")
    except ValueError:
        pass
    if r.status_code == 401:
        return _bad("Claude says this key is wrong or was deleted. Copy a fresh one from console.anthropic.com, API Keys.")
    if "credit" in detail.lower() or "billing" in detail.lower():
        return _bad("The key is fine but the account has no credit. Add some under Billing at console.anthropic.com.")
    if r.status_code == 403:
        return _bad("This key isn't allowed to use Claude models. Check the key's workspace in console.anthropic.com.")
    if r.status_code == 429:
        return _ok("Claude key works (it's busy right now, so agents may wait a little).")
    if r.status_code >= 500:
        return _bad("Claude is having trouble right now. Try again in a few minutes.")
    return _bad(f"Claude answered {r.status_code}: {detail or 'unknown problem'}")


def telegram(values=None, send: bool = True) -> dict:
    token, owner = _v("TELEGRAM_BOT_TOKEN", values), _v("TELEGRAM_OWNER_ID", values)
    if not token:
        return _bad("No bot token yet. In Telegram, message @BotFather, send /newbot and paste the token it gives you.")
    try:
        me = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        return _offline("Telegram")
    if not me.get("ok"):
        return _bad("Telegram doesn't recognise this bot token. Copy it again from @BotFather (send /mybots, pick the bot, API Token).")
    name = "@" + me["result"].get("username", "your bot")
    if not owner:
        return _bad(f"The token works ({name}), but TELEGRAM_OWNER_ID is empty. Send {name} \"hi\", then run "
                    "python -m hq relay-id and paste the number here.")
    if not owner.isdigit():
        return _bad("TELEGRAM_OWNER_ID should be a number, like 123456789.")
    if not send:  # the checklist's background check shouldn't message you every time
        return _ok(f"Connected to {name}.")
    try:
        sent = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=TIMEOUT,
                             data={"chat_id": owner, "text": "✅ Agent HQ is connected. This is a test message."}).json()
    except (requests.RequestException, ValueError):
        return _offline("Telegram")
    if not sent.get("ok"):
        return _bad(f"The token works, but {name} can't message you yet. Open Telegram, send {name} \"hi\", "
                    "and check TELEGRAM_OWNER_ID is your own number.")
    return _ok(f"Connected to {name}. Check Telegram for a test message.")


def twitch(values=None) -> dict:
    cid, secret = _v("TWITCH_CLIENT_ID", values), _v("TWITCH_CLIENT_SECRET", values)
    if not cid or not secret:
        return _bad("Needs both the Client ID and Client Secret from dev.twitch.tv/console (Applications, Manage).")
    try:
        r = requests.post("https://id.twitch.tv/oauth2/token", timeout=TIMEOUT,
                          data={"client_id": cid, "client_secret": secret, "grant_type": "client_credentials"})
    except requests.RequestException:
        return _offline("Twitch")
    if r.status_code == 200:
        return _ok("Twitch app keys work.")
    return _bad("Twitch doesn't accept this Client ID and Secret. In dev.twitch.tv/console, open your app, press "
                "New Secret, and paste both again.")


def tiktok(account: dict, values=None) -> dict:
    token = _v(account.get("access_token_env", ""), values)
    if not token:
        return _bad(f"No access token for {account['name']} yet.")
    try:
        r = requests.get("https://open.tiktokapis.com/v2/user/info/", timeout=TIMEOUT,
                         params={"fields": "display_name"}, headers={"Authorization": f"Bearer {token}"})
        data = r.json()
    except (requests.RequestException, ValueError):
        return _offline("TikTok")
    code = (data.get("error") or {}).get("code", "ok")
    if code == "ok":
        name = (data.get("data") or {}).get("user", {}).get("display_name")
        return _ok(f"TikTok token works{f' ({name})' if name else ''}.")
    if code == "scope_not_authorized":
        return _ok("TikTok token works. (It can't read the profile name, which is fine for posting.)")
    if code == "access_token_invalid":
        return _bad("TikTok says this token has expired or is wrong. TikTok access tokens only last about a day, "
                    "so make a new one in your TikTok developer app and paste it here.")
    return _bad(f"TikTok answered: {(data.get('error') or {}).get('message') or code}")


def instagram(account: dict, values=None) -> dict:
    user_id = _v(account.get("ig_user_id_env", ""), values)
    token = _v(account.get("access_token_env", ""), values)
    if not user_id or not token:
        return _bad(f"{account['name']} needs both the Instagram user ID and the access token.")
    graph = os.getenv("HQ_GRAPH_API", "https://graph.facebook.com/v21.0")
    try:
        data = requests.get(f"{graph}/{user_id}", timeout=TIMEOUT,
                            params={"fields": "username", "access_token": token}).json()
    except (requests.RequestException, ValueError):
        return _offline("Instagram")
    if "username" in data:
        note = "" if os.getenv("HQ_PUBLIC_BASE_URL") else " Posting also needs HQ_PUBLIC_BASE_URL, so Instagram can fetch clips."
        return {"ok": not note, "message": f"Instagram works (@{data['username']}).{note}"}
    err = (data.get("error") or {})
    if err.get("code") == 190:
        return _bad("Instagram says this token has expired. Make a new long-lived token in Meta's developer tools.")
    return _bad(f"Instagram answered: {err.get('message') or data}")


def youtube(account: dict, values=None) -> dict:
    token_file = ROOT / account.get("token_file", "")
    if not account.get("token_file") or not token_file.exists():
        return _bad(f"{account['name']} isn't signed in to YouTube yet. Run: python -m hq connect-youtube {account['name']}")
    try:
        from .agents.chad.publish import youtube as yt
        yt._credentials(account)  # refreshes the sign-in if needed; never opens a browser here
    except Exception as e:
        return _bad(f"The YouTube sign-in no longer works ({str(e)[:120]}). "
                    f"Run python -m hq connect-youtube {account['name']} again.")
    return _ok("YouTube sign-in works.")


def practice(account: dict, values=None) -> dict:
    return _ok("Practice account: clips are saved to data/practice-posts instead of being uploaded.")


# Settings keys with a Test button, and which test each one runs.
KEY_TESTS = {"ANTHROPIC_API_KEY": "claude", "TELEGRAM_BOT_TOKEN": "telegram", "TELEGRAM_OWNER_ID": "telegram",
             "TWITCH_CLIENT_ID": "twitch", "TWITCH_CLIENT_SECRET": "twitch"}
SERVICE_TESTS = {"claude": claude, "telegram": telegram, "twitch": twitch}
ACCOUNT_TESTS = {"tiktok": tiktok, "instagram": instagram, "youtube": youtube, "practice": practice}


def _accounts() -> list[dict]:
    from .agents.chad.publish import load_accounts
    try:
        return load_accounts()
    except OSError:
        return []


def account_for_key(key: str) -> dict | None:
    for a in _accounts():
        if key in [v for k, v in a.items() if k.endswith("_env")]:
            return a
    return None


def test_name_for_key(key: str) -> str | None:
    if key in KEY_TESTS:
        return KEY_TESTS[key]
    a = account_for_key(key)
    return f"account:{a['name']}" if a else None


def results() -> dict:
    try:
        return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _remember(name: str, result: dict) -> None:
    saved = results()
    saved[name] = {**result, "at": time.time()}
    RESULTS_PATH.write_text(json.dumps(saved, indent=2), encoding="utf-8")


def run(name: str, values: dict | None = None, quiet: bool = False) -> dict:
    """Run a test by name: a service ("claude", "telegram", "twitch") or "account:<name>"."""
    if name.startswith("account:"):
        account = next((a for a in _accounts() if a.get("name") == name[8:]), None)
        if not account:
            return _bad(f"There's no account called {name[8:]}.")
        test = ACCOUNT_TESTS.get(account.get("platform"))
        result = test(account, values) if test else _bad(f"No test for {account.get('platform')} accounts yet.")
    elif name == "telegram":
        result = telegram(values, send=not quiet)
    elif name in SERVICE_TESTS:
        result = SERVICE_TESTS[name](values)
    else:
        return _bad(f"No test called {name}.")
    _remember(name, result)
    return result


def run_all() -> dict:
    """Test everything that has something to test. Used by the checklist's "Check again" button."""
    out = {}
    if os.getenv("ANTHROPIC_API_KEY"):
        out["claude"] = run("claude")
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        out["telegram"] = run("telegram", quiet=True)
    if os.getenv("TWITCH_CLIENT_ID"):
        out["twitch"] = run("twitch")
    for a in _accounts():
        if a.get("enabled"):
            out[f"account:{a['name']}"] = run(f"account:{a['name']}")
    _remember("_all", _ok("Checked everything."))
    return out
