"""Relay: the Boss and your approval buttons on your phone, through a private Telegram bot.

Only the Telegram account named in TELEGRAM_OWNER_ID is ever answered. Without a bot token Relay stays off.
Setup: message @BotFather on Telegram, send /newbot, put the token in .env as TELEGRAM_BOT_TOKEN, then message
your new bot once and run `python -m hq relay-id` to find your TELEGRAM_OWNER_ID.
"""

import json
import os
import threading
import time
import traceback
from pathlib import Path

import requests

from . import db

MAX_VIDEO_BYTES = 49 * 1024 * 1024  # Telegram bots can upload files up to 50 MB


def token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def owner_id() -> int | None:
    v = os.getenv("TELEGRAM_OWNER_ID", "").strip()
    return int(v) if v.isdigit() else None


def enabled() -> bool:
    return bool(token() and owner_id())


def api(method: str, files: dict | None = None, **params) -> dict:
    r = requests.post(f"https://api.telegram.org/bot{token()}/{method}", data=params, files=files, timeout=60)
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {body.get('description')}")
    return body["result"]


def notify(text: str) -> None:
    """Send you a message. Any agent can call this; it does nothing when Relay isn't set up."""
    if enabled():
        try:
            api("sendMessage", chat_id=owner_id(), text=text[:4000])
        except Exception:
            traceback.print_exc()


def ask(text: str, kind: str, ref: int, yes: str = "✅ Approve", no: str = "❌ Reject") -> None:
    """Send you a message with two buttons. `kind` picks which handler in DECIDERS runs on a tap."""
    if enabled():
        try:
            api("sendMessage", chat_id=owner_id(), text=text[:3800], reply_markup=_buttons(kind, ref, yes, no))
        except Exception:
            traceback.print_exc()


def _buttons(kind: str, ref: int, yes: str = "✅ Approve", no: str = "❌ Reject") -> str:
    return json.dumps({"inline_keyboard": [[{"text": yes, "callback_data": f"{kind}:approve:{ref}"},
                                            {"text": no, "callback_data": f"{kind}:reject:{ref}"}]]})


# ---- what you can do from your phone ---------------------------------------------------------------

DECIDERS = {}  # kind -> function(ref_id, decision) -> short confirmation text; other agents can register more


def _decide_clip(clip_id: int, decision: str) -> str:
    status = "approved" if decision == "approve" else "rejected"
    db.set_clip_status(clip_id, status)
    db.log("Steven", f"Clip #{clip_id} {status} (from Relay)")
    return f"Clip #{clip_id} {status}."


DECIDERS["clip"] = _decide_clip


def handle_callback(cb: dict) -> None:
    if cb["from"]["id"] != owner_id():
        return
    try:
        kind, decision, ref = cb["data"].split(":")
        done = DECIDERS[kind](int(ref), decision)
    except Exception as e:
        done = f"Couldn't do that: {e}"
    api("answerCallbackQuery", callback_query_id=cb["id"], text=done[:200])
    msg = cb.get("message") or {}
    if msg.get("message_id"):
        # a message of several separate buttons (Sweep's fixes) keeps the ones not tapped yet; yes/no pairs all go
        rows = [r for r in (msg.get("reply_markup") or {}).get("inline_keyboard", [])
                if len(r) == 1 and r[0].get("callback_data") != cb["data"]]
        api("editMessageReplyMarkup", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
            reply_markup=json.dumps({"inline_keyboard": rows}))
        api("sendMessage", chat_id=msg["chat"]["id"], text=done, reply_to_message_id=msg["message_id"])


def handle_message(m: dict) -> None:
    if m.get("from", {}).get("id") != owner_id():
        return  # anyone else is ignored completely
    text = (m.get("text") or "").strip()
    if not text:
        return
    if text.lower().strip("!. /") in ("pause", "pause all", "stop", "resume", "unpause"):
        from . import settings
        stop = text.lower().strip("!. /") in ("pause", "pause all", "stop")
        settings.save({"HQ_PAUSED": "true" if stop else "false"})
        db.log("Steven", "Paused HQ (from Relay)" if stop else "Resumed HQ (from Relay)")
        api("sendMessage", chat_id=m["chat"]["id"], text="⏸ HQ paused. No agent works and nothing posts. "
            "Send \"resume\" to start again." if stop else "▶️ HQ resumed.")
        return
    from . import boss  # imported here because the Boss imports the agents, and agents import Relay
    api("sendChatAction", chat_id=m["chat"]["id"], action="typing")
    try:
        reply = boss.chat(text)
    except Exception as e:
        reply = f"The Boss hit a problem: {e}"
    api("sendMessage", chat_id=m["chat"]["id"], text=reply[:4000] or "(no reply)")


def handle_update(u: dict) -> None:
    if "callback_query" in u:
        handle_callback(u["callback_query"])
    elif "message" in u:
        handle_message(u["message"])


# ---- sending clips for approval --------------------------------------------------------------------

def _sent(kind: str, ref: int) -> bool:
    return bool(db.rows("SELECT 1 FROM relay_sent WHERE kind = ? AND ref_id = ?", kind, ref))


def _mark_sent(kind: str, ref: int) -> None:
    db.execute("INSERT OR IGNORE INTO relay_sent (kind, ref_id, created_at) VALUES (?, ?, ?)", kind, ref, db.now())


def push_pending_clips() -> int:
    """Send each clip that is waiting for approval to your phone, once."""
    sent = 0
    for c in db.rows("SELECT * FROM clips WHERE status = 'pending_approval' ORDER BY id"):
        if _sent("clip", c["id"]):
            continue
        caption = f"#{c['id']} {c.get('title') or ''}\n{c.get('creator') or ''}"
        if c.get("score") is not None:
            caption += f" · score {c['score']:g}"
        if c.get("reason"):
            caption += f"\n{c['reason']}"
        path = Path(c["path"])
        try:
            if path.exists() and path.stat().st_size <= MAX_VIDEO_BYTES:
                with open(path, "rb") as f:
                    api("sendVideo", files={"video": f}, chat_id=owner_id(), caption=caption[:1000],
                        supports_streaming="true", reply_markup=_buttons("clip", c["id"]))
            else:
                api("sendMessage", chat_id=owner_id(), reply_markup=_buttons("clip", c["id"]),
                    text=caption[:3500] + "\n\n(The video is too big to send here. Preview it on the dashboard.)")
            _mark_sent("clip", c["id"])
            sent += 1
        except Exception:
            traceback.print_exc()
            break  # try again next loop rather than skipping this clip
    return sent


# ---- the loop --------------------------------------------------------------------------------------

def loop() -> None:
    db.init()
    offset = None
    print("[relay] connected to Telegram.")
    from .standby import is_standby
    while True:
        if is_standby():  # two bots can't both listen to one Telegram bot, so the standby copy stays quiet
            time.sleep(10)
            continue
        try:
            params = {"timeout": 25, "allowed_updates": '["message", "callback_query"]'}
            if offset:
                params["offset"] = offset
            for u in api("getUpdates", **params):
                offset = u["update_id"] + 1
                try:
                    handle_update(u)
                except Exception:
                    traceback.print_exc()
            push_pending_clips()
        except Exception:
            traceback.print_exc()
            time.sleep(10)


def start_in_background() -> bool:
    if not enabled():
        return False
    threading.Thread(target=loop, daemon=True, name="relay").start()
    return True


def find_owner_id() -> str:
    """Prints who has messaged the bot lately, so you can copy your own ID into .env."""
    seen = {}
    for u in api("getUpdates"):
        m = u.get("message") or {}
        if m.get("from"):
            seen[m["from"]["id"]] = m["from"].get("first_name", "")
    if not seen:
        return "No messages found. Open your bot in Telegram, send it \"hi\", then run this again."
    return "\n".join(f"TELEGRAM_OWNER_ID={i}   ({n})" for i, n in seen.items())
