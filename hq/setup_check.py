"""The getting-started checklist: everything HQ needs to run and earn, in the order to do it.

Each item is done, todo or problem, with one line on how to fix it and a link to the right place. Network checks
reuse the last Test results (connections.py), refreshed in the background when they're older than a few hours.
"""

import os
import shutil
import threading
import time
from datetime import datetime

from . import connections, db
from .backup import BACKUP_DIR

STALE = 6 * 3600  # re-run the connection tests in the background when the last run is older than this
_refreshing = threading.Lock()


def _tested(name: str) -> dict | None:
    return connections.results().get(name)


def _from_test(name: str, set_: bool, missing: str) -> tuple[str, str]:
    """Status and detail for a key: not set, set but never tested, or the last test's result."""
    if not set_:
        return "todo", missing
    t = _tested(name)
    if not t:
        return "todo", "Saved. Press Test next to it in Settings to check it works."
    return ("done" if t["ok"] else "problem"), t["message"]


def _item(id_, title, status, detail, fix="", link="", required=True) -> dict:
    return {"id": id_, "title": title, "status": status, "detail": detail, "fix": fix, "link": link,
            "required": required}


def _permitted_creators() -> list[str]:
    from .agents.chad import twitch
    from .agents.chad.sources import is_permitted, load_creators
    names = []
    try:
        names = [c["name"] for c in load_creators() if is_permitted(c)]
    except Exception:  # a broken creators.yaml shouldn't break the checklist
        pass
    try:
        names += [login for login, why in twitch.permissions().items() if why]
    except Exception:
        pass
    return names


def _latest_backup() -> datetime | None:
    found = sorted(BACKUP_DIR.glob("hq-backup-*.zip")) if BACKUP_DIR.exists() else []
    return datetime.fromtimestamp(found[-1].stat().st_mtime) if found else None


def items() -> list[dict]:
    from . import update
    out = []

    status, detail = _from_test("claude", bool(os.getenv("ANTHROPIC_API_KEY")),
                                "The Boss and every agent need it. Make one at console.anthropic.com, API Keys, and add a few dollars of credit.")
    out.append(_item("claude", "Claude API key", status, detail, "Paste it in Settings and press Test",
                     "/settings#k-ANTHROPIC_API_KEY"))

    has_ffmpeg = bool(shutil.which("ffmpeg"))
    out.append(_item("ffmpeg", "Video tools (ffmpeg)", "done" if has_ffmpeg else "problem",
                     "Installed." if has_ffmpeg else "Chad can't cut clips without ffmpeg.",
                     "Run Install-Agent-HQ.bat again; it installs ffmpeg"))

    who = _permitted_creators()
    out.append(_item("permission", "Someone Chad is allowed to clip", "done" if who else "todo",
                     f"Chad may clip: {', '.join(who[:5])}{'…' if len(who) > 5 else ''}." if who else
                     "Chad skips everyone without recorded permission, so right now he has no one to clip.",
                     "Paste a clipping campaign's rules to the Boss so Scout can vet it, or add permission in config/streamers.yaml",
                     "/#boss"))

    accounts = connections._accounts()
    on = [a for a in accounts if a.get("enabled")]
    real = [a for a in on if a.get("platform") != "practice"]
    if not on:
        out.append(_item("posting", "A posting account switched on", "todo",
                         "No accounts are on, so approved clips have nowhere to go. Try the practice account first.",
                         "Switch an account on in Settings", "/settings#accounts"))
    else:
        bad = [a["name"] for a in on if (t := _tested(f"account:{a['name']}")) and not t["ok"]]
        untested = [a["name"] for a in on if not _tested(f"account:{a['name']}")]
        names = ", ".join(a["name"] for a in on)
        if bad:
            out.append(_item("posting", "A posting account switched on", "problem",
                             f"{', '.join(bad)} failed its last test: {_tested('account:' + bad[0])['message']}",
                             "Fix the key in Settings and press Test", "/settings#accounts"))
        elif not real:
            out.append(_item("posting", "A posting account switched on", "todo",
                             "Only the practice account is on. That's perfect for trying things; switch on TikTok, "
                             "YouTube or Instagram when you're ready to post for real.",
                             "Connect a real account in Settings", "/settings#accounts"))
        elif untested:
            out.append(_item("posting", "A posting account switched on", "todo",
                             f"On: {names}. Not tested yet: {', '.join(untested)}.",
                             "Press Test next to each account in Settings", "/settings#accounts"))
        else:
            out.append(_item("posting", "A posting account switched on", "done", f"On and working: {names}."))

    budget = float(os.getenv("HQ_DAILY_BUDGET", "0") or 0)
    out.append(_item("budget", "Daily spending limit", "done" if budget > 0 else "todo",
                     f"Agents stop for the day after ${budget:g} of Claude use." if budget > 0 else
                     "No limit yet, so a runaway agent could run up a bill. $2 a day is plenty to start.",
                     "Set HQ_DAILY_BUDGET in Settings", "/settings#k-HQ_DAILY_BUDGET", required=False))

    status, detail = _from_test("telegram", bool(os.getenv("TELEGRAM_BOT_TOKEN")),
                                "Approve clips and talk to the Boss from your phone, for free.")
    out.append(_item("relay", "Phone control (Telegram)", status, detail,
                     "Message @BotFather in Telegram, send /newbot, paste the token in Settings",
                     "/settings#k-TELEGRAM_BOT_TOKEN", required=False))

    status, detail = _from_test("twitch", bool(os.getenv("TWITCH_CLIENT_ID")),
                                "Lets Chad find top Twitch clips and Pitch find streamers.")
    out.append(_item("twitch", "Twitch app keys", status, detail, "Make a free app at dev.twitch.tv/console",
                     "/settings#k-TWITCH_CLIENT_ID", required=False))

    pw = os.getenv("HQ_PASSWORD", "")
    out.append(_item("password", "Password for your other computers", "done" if len(pw) >= 10 else "todo",
                     "Set." if len(pw) >= 10 else
                     ("Too short. Use at least 10 characters." if pw else
                      "Only needed to open HQ from your Mac or phone. Without it HQ only answers this computer."),
                     "Set HQ_PASSWORD in Settings", "/settings#k-HQ_PASSWORD", required=False))

    last = _latest_backup()
    fresh = last and (datetime.now() - last).days < 2
    out.append(_item("backup", "Daily backups", "done" if fresh else "todo",
                     f"Last backup {last:%d %b %H:%M}." if last else "HQ makes one each day while it's running.",
                     "" if fresh else "Leave HQ running; the first backup happens on its own", required=False))

    copy_dir = os.getenv("HQ_BACKUP_COPY_DIR", "").strip()
    out.append(_item("backup_copy", "Backups in a second place", "done" if copy_dir else "todo",
                     f"A copy goes to {copy_dir} each day (without your keys)." if copy_dir else
                     "Backups only live on this PC, so a dead drive loses HQ and its backups together.",
                     "" if copy_dir else "Set HQ_BACKUP_COPY_DIR to a Google Drive folder in Settings",
                     "/settings#k-HQ_BACKUP_COPY_DIR", required=False))

    git = update.is_git_copy()
    out.append(_item("updates", "Automatic updates", "done" if git else "problem",
                     "HQ updates itself from GitHub." if git else "This copy came from a ZIP, so it can't update itself.",
                     "" if git else "Run Install-Agent-HQ.bat once"))
    return out


def refresh_in_background() -> bool:
    """Re-run the connection tests when they're stale. Returns True if a refresh started."""
    if time.time() - connections.results().get("_all", {}).get("at", 0) < STALE:
        return False
    if not _refreshing.acquire(blocking=False):
        return False

    def go():
        try:
            connections.run_all()
        except Exception as e:
            db.log("HQ", f"Setup check failed: {e}")
        finally:
            _refreshing.release()
    threading.Thread(target=go, daemon=True).start()
    return True


def summary() -> dict:
    """What the dashboard card and the Boss see."""
    found = items()
    needed = [i for i in found if i["required"]]
    return {"items": found, "done": sum(i["status"] == "done" for i in found), "total": len(found),
            "ready": all(i["status"] == "done" for i in needed),
            "next": next((i for i in found if i["status"] != "done"), None)}
