"""Connect TikTok once; HQ keeps the access token fresh from then on.

TikTok access tokens only last about a day, but the refresh token that comes with them lasts a year, so HQ renews the
access token itself whenever it is about to run out. The tokens are saved in data/tiktok_tokens.json, outside git.

Flow: open the TikTok login link from the Settings page, approve, and TikTok sends you to your redirect page
(TIKTOK_REDIRECT_URI), which shows the address it was sent to. Paste that address back into Settings.
"""

import json
import os
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from .config import DATA_DIR

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
SCOPES = "user.info.basic,video.upload"
TOKENS_PATH = DATA_DIR / "tiktok_tokens.json"
STATE_PATH = DATA_DIR / "tiktok_state.txt"
RENEW_BEFORE = 10 * 60  # renew when less than this many seconds are left
TIMEOUT = 30


class TikTokError(Exception):
    pass


def _env(key: str) -> str:
    return os.getenv(key, "").strip()


def configured() -> bool:
    return bool(_env("TIKTOK_CLIENT_KEY") and _env("TIKTOK_CLIENT_SECRET") and _env("TIKTOK_REDIRECT_URI"))


def _load() -> dict:
    try:
        return json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(tokens: dict) -> None:
    tmp = TOKENS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(tokens), encoding="utf-8")
    tmp.replace(TOKENS_PATH)


def connected() -> bool:
    return bool(_load().get("refresh_token"))


def authorize_url() -> str:
    """The TikTok login link. A fresh random `state` is remembered so a pasted answer can be checked against it."""
    if not configured():
        raise TikTokError("Save TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET and TIKTOK_REDIRECT_URI in Settings first.")
    state = secrets.token_urlsafe(16)
    STATE_PATH.write_text(state, encoding="utf-8")
    return AUTH_URL + "?" + urlencode({"client_key": _env("TIKTOK_CLIENT_KEY"), "scope": SCOPES, "response_type": "code",
                                       "redirect_uri": _env("TIKTOK_REDIRECT_URI"), "state": state})


def parse_answer(text: str) -> str:
    """The code from what you pasted: the whole address TikTok sent you to, or just the code."""
    text = (text or "").strip()
    if not text:
        raise TikTokError("Paste the address from the page TikTok sent you to.")
    if "://" not in text and "code=" not in text and "error=" not in text:
        return text  # a bare code
    q = parse_qs(urlparse(text).query)
    if q.get("error"):
        raise TikTokError(f"TikTok said no: {(q.get('error_description') or q['error'])[0]}")
    if not q.get("code"):
        raise TikTokError("That address has no code in it. Copy the whole address from the page TikTok sent you to.")
    try:
        expected = STATE_PATH.read_text(encoding="utf-8")
    except OSError:
        expected = ""
    if q.get("state") and expected and q["state"][0] != expected:
        raise TikTokError("That login was started somewhere else. Press Connect TikTok again and use the newest link.")
    return q["code"][0]


def _token_call(data: dict) -> dict:
    try:
        r = requests.post(TOKEN_URL, data={"client_key": _env("TIKTOK_CLIENT_KEY"),
                                           "client_secret": _env("TIKTOK_CLIENT_SECRET"), **data},
                          headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=TIMEOUT)
        body = r.json()
    except (requests.RequestException, ValueError):
        raise TikTokError("Couldn't reach TikTok. Check your internet and try again.")
    if not body.get("access_token"):
        raise TikTokError(f"TikTok answered: {body.get('error_description') or body.get('error') or r.text[:200]}")
    now = time.time()
    return {"access_token": body["access_token"], "refresh_token": body.get("refresh_token", ""),
            "open_id": body.get("open_id", ""), "scope": body.get("scope", ""),
            "expires_at": now + int(body.get("expires_in", 86400)),
            "refresh_expires_at": now + int(body.get("refresh_expires_in", 365 * 86400))}


def connect(answer: str) -> str:
    """Trade the pasted login answer for tokens and save them."""
    if not configured():
        raise TikTokError("Save TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET and TIKTOK_REDIRECT_URI in Settings first.")
    tokens = _token_call({"code": parse_answer(answer), "grant_type": "authorization_code",
                          "redirect_uri": _env("TIKTOK_REDIRECT_URI")})
    _save(tokens)
    return "TikTok is connected. HQ will keep it signed in by itself."


def access_token() -> str | None:
    """A working access token, renewed first if it is about to expire. None when TikTok isn't connected."""
    tokens = _load()
    if not tokens.get("refresh_token"):
        return None
    if tokens.get("expires_at", 0) - time.time() > RENEW_BEFORE:
        return tokens["access_token"]
    fresh = _token_call({"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]})
    fresh["refresh_token"] = fresh["refresh_token"] or tokens["refresh_token"]
    fresh["open_id"] = fresh["open_id"] or tokens.get("open_id", "")
    _save(fresh)
    return fresh["access_token"]


def disconnect() -> None:
    for p in (TOKENS_PATH, STATE_PATH):
        p.unlink(missing_ok=True)


def status() -> dict:
    """What the Settings page shows."""
    t = _load()
    days = max(0, int((t.get("refresh_expires_at", 0) - time.time()) / 86400)) if t else 0
    return {"configured": configured(), "connected": bool(t.get("refresh_token")), "days_left": days,
            "redirect_uri": _env("TIKTOK_REDIRECT_URI")}
