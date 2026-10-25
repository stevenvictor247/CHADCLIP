"""Connect Instagram once; HQ turns a short-lived Meta token into a token that doesn't expire.

Steven pastes the token from Meta's Graph API Explorer (it only lasts about an hour). HQ swaps it for a 60-day
user token, then asks Meta for the Facebook Page's own token, which never expires. It also finds the Instagram
account linked to that Page, and saves both as IG_USER_ID_MAIN and IG_ACCESS_TOKEN_MAIN (the instagram_main account).
"""

import os

import requests

from . import settings

GRAPH = os.getenv("HQ_GRAPH_API", "https://graph.facebook.com/v21.0")
TIMEOUT = 30
USER_ID_KEY, TOKEN_KEY = "IG_USER_ID_MAIN", "IG_ACCESS_TOKEN_MAIN"


class InstagramError(Exception):
    pass


def _env(key: str) -> str:
    return os.getenv(key, "").strip()


def configured() -> bool:
    return bool(_env("IG_APP_ID") and _env("IG_APP_SECRET"))


def status() -> dict:
    return {"configured": configured(), "connected": bool(_env(USER_ID_KEY) and _env(TOKEN_KEY))}


def _get(path: str, **params) -> dict:
    try:
        data = requests.get(f"{GRAPH}/{path}", params=params, timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        raise InstagramError("Couldn't reach Meta. Check your internet and try again.")
    if "error" in data:
        raise InstagramError(f"Meta said: {data['error'].get('message') or data['error']}")
    return data


def connect(short_token: str) -> str:
    """Swap the pasted token for a lasting one, find the Instagram account, and save both."""
    if not configured():
        raise InstagramError("Save IG_APP_ID and IG_APP_SECRET first (from your Meta app's Settings > Basic).")
    short_token = (short_token or "").strip()
    if len(short_token) < 20:
        raise InstagramError("Paste the long access token from Meta's Graph API Explorer.")
    long_lived = _get("oauth/access_token", grant_type="fb_exchange_token", client_id=_env("IG_APP_ID"),
                      client_secret=_env("IG_APP_SECRET"), fb_exchange_token=short_token).get("access_token")
    if not long_lived:
        raise InstagramError("Meta didn't give back a token. Make a fresh one in the Graph API Explorer.")
    pages = _get("me/accounts", fields="name,access_token,instagram_business_account", access_token=long_lived,
                 limit=50).get("data") or []
    if not pages:
        raise InstagramError("That token can't see any Facebook Pages. In the Graph API Explorer, press Generate "
                             "Access Token again and tick your Page when Facebook asks which ones to allow.")
    linked = [p for p in pages if p.get("instagram_business_account")]
    if not linked:
        raise InstagramError("None of your Pages has an Instagram account linked. In Instagram: Settings > Account "
                             "type and tools > make sure it's Professional, then link it to your Facebook Page.")
    page = linked[0]
    ig_id = page["instagram_business_account"]["id"]
    name = _get(ig_id, fields="username", access_token=page["access_token"]).get("username", "")
    settings.save({USER_ID_KEY: ig_id, TOKEN_KEY: page["access_token"]})
    extra = f" (Page \"{page.get('name', '')}\" was used.)" if len(linked) > 1 else ""
    return f"Instagram connected{f' as @{name}' if name else ''}. This token doesn't expire.{extra}"


def disconnect() -> None:
    settings.save({USER_ID_KEY: "", TOKEN_KEY: ""})
