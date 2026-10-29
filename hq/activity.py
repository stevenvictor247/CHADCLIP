"""What every agent is doing, and when it isn't, why not.

An agent that sits idle is almost never lazy: something it needs is missing (a streamer with permission, a key), or a
safety limit is holding it (the posting cap, the day's budget, waiting for your approval). This module reads the same
checks the agents use to decide whether to run, and says the reason in plain words, so the dashboard, the Boss and
Muse can all tell what would put an agent to work. It only reads: no Claude call, no network, nothing changes.

Each reason is (why, what unlocks it, where to do it). `report()` is what the dashboard and the Boss show.
"""

import os
import time
import traceback
from datetime import datetime, timedelta, timezone

from . import approvals, db, ledger
from .config import HAS_LLM

CACHE_SECONDS = 20   # the dashboard asks every few seconds; the answers are cheap but there is no need to redo them
_cache: dict = {"at": 0.0, "rows": []}


def _ago(**kw) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat(timespec="seconds")


def _n(sql: str, *args) -> int:
    return db.rows(sql, *args)[0]["n"]


# ---- reasons, one per agent --------------------------------------------------------------------------------
# Each returns (why, unlock, link) or None when the agent has work or nothing is known to be holding it.

def _chad():
    from . import clipbudget
    from .agents.chad import sources, twitch
    if not HAS_LLM:
        return "No Claude key.", "Add ANTHROPIC_API_KEY in Settings.", "/settings"
    left, why = clipbudget.room()
    if left <= 0:
        waiting = clipbudget.backlog()
        if waiting > clipbudget.posting_capacity():
            return (why[:1].upper() + why[1:]), "Approve or reject the waiting clips so posting can catch up.", "/#approvals"
        return (why[:1].upper() + why[1:]), "", ""
    someone = any(sources.is_permitted(c) and c.get("sources") for c in sources.load_creators())
    twitch_ok = bool(os.getenv("TWITCH_CLIENT_ID") and os.getenv("TWITCH_CLIENT_SECRET") and any(twitch.permissions().values()))
    if not (someone or twitch_ok):
        return ("Nobody it is allowed to clip yet.",
                "Add a streamer with permission on the Clips tab, or join a campaign Scout found.", "/#clips")
    return None


def _scout():
    from . import campaigns, discovery
    if not HAS_LLM:
        return "No Claude key.", "Add ANTHROPIC_API_KEY in Settings.", "/settings"
    waiting = _n("SELECT COUNT(*) n FROM campaigns WHERE status = 'proposed'")
    if waiting:
        return (f"{waiting} campaign{'s' if waiting != 1 else ''} it found {'are' if waiting != 1 else 'is'} waiting for your Join or Skip.",
                "Decide on the Campaigns tab.", "/#campaigns")
    if not (discovery.web_search_on() or discovery.feed_urls() or discovery.inbox("queued")):
        return ("Nothing to search: its daily web search is off and the inbox and feeds are empty.",
                "Turn SCOUT_WEB_SEARCH back on, or paste a campaign into the inbox.", "/#campaigns")
    if discovery.web_search_on() and not discovery.web_search_due():
        return "Searched the web today; the next search is tomorrow.", "", ""
    return None


def _pitch():
    from .agents.pitch.agent import settings
    cfg = settings()
    if not HAS_LLM:
        return "No Claude key.", "Add ANTHROPIC_API_KEY in Settings.", "/settings"
    if not str(cfg.get("sender_name") or "").strip():
        return "Can't draft pitches until it knows how you sign them.", "Fill in the Pitch section of Settings.", "/settings"
    drafts = sum(1 for a in approvals.pending() if a["kind"] == "pitch")
    if drafts:
        return f"{drafts} pitch draft{'s' if drafts != 1 else ''} waiting for you.", "Approve or skip them in Approvals.", "/#approvals"
    if not cfg.get("auto_find"):
        return ("Only finds new streamers when asked (auto_find is off).",
                "Ask the Boss \"have Pitch find 5 streamers\", or switch auto_find on in the Pitch section of Settings.", "/settings")
    return None


def _tally():
    if not _n("SELECT COUNT(*) n FROM posts WHERE status = 'posted'"):
        return "No posted clips yet, so there are no views to count.", "It starts as soon as the first clip posts.", ""
    return None


def _muse():
    from . import muse
    why = muse.why_not_now()
    if why:
        waiting = _n("SELECT COUNT(*) n FROM ideas WHERE status = 'proposed'")
        if waiting:
            return (f"{waiting} idea{'s' if waiting != 1 else ''} waiting for your answer, so it isn't thinking up more.",
                    "Answer them on the Ideas tab.", "/#ideas")
        return why[:1].upper() + why[1:], "", ""
    return None


def _rally():
    from . import rally
    why = rally.why_not_now()
    return (why, "", "") if why else None


def _etta():
    from .etsy import store
    if not store.designs(limit=1):
        return "No shirt designs yet, so there is no weekly shop report to write.", "", ""
    return "Writes its report on Sunday mornings.", "", ""


def _radar():
    from .etsy import store
    age = store.brief_age_days()
    if age is not None and age < 7:
        return f"Its trend brief is {age:.0f} day{'s' if round(age) != 1 else ''} old; it researches once a week.", "", ""
    return None


def _quill():
    from .agents.etsy import quill
    from .etsy import store
    if not HAS_LLM:
        return "No Claude key.", "Add ANTHROPIC_API_KEY in Settings.", "/settings"
    if not store.latest_brief():
        return "Waiting for Radar's first trend brief.", "", ""
    if quill.room() <= 0:
        return ("Too many shirt designs are waiting for you, so it paused.", "Approve or reject them in Approvals.", "/#approvals")
    return None


def _loom():
    from .etsy import store
    return ("Waiting for Quill to write a design.", "", "") if not store.designs("written", limit=1) else None


def _warden():
    from .etsy import store
    return ("Waiting for Loom to draw a design.", "", "") if not store.designs("drawn", limit=1) else None


def _dock():
    from .etsy import printify, store
    if not printify.connected():
        return "Printify isn't connected.", "Add your Printify token in Settings (HQ_PRINTIFY_TOKEN).", "/settings"
    if not store.designs("approved", limit=1):
        return "Waiting for a shirt you approve.", "", ""
    return None


def _on_request(text: str, unlock: str = "", link: str = ""):
    return lambda: (text, unlock, link)


REASONS = {
    "chad": _chad, "scout": _scout, "pitch": _pitch, "tally": _tally, "muse": _muse, "rally": _rally,
    "etta": _etta, "radar": _radar, "quill": _quill, "loom": _loom, "warden": _warden, "dock": _dock,
    "gate": _on_request("Scores waiting clips against your past approvals; holds none until it has 10 decided clips.", "", "/#pending"),
    "recap": _on_request("Works when you give it a long video or podcast transcript.", "Ask the Boss, or use the Recap box.", "/#boss"),
    "packs": _on_request("Works when a podcaster gives you an episode.", "Ask the Boss to make a clip pack.", "/#boss"),
    "captain": _on_request("Answers football questions and hands out football work when you ask.", "", "/#football"),
    "clock": _on_request("Keeps the game-week checklist and texts you when something is due.", "", "/#football"),
    "ref": _on_request("Checks tagged sheets as soon as one lands in the football Inbox.", "Drop a sheet in the football Inbox.", "/#football"),
    "tells": _on_request("Counts tendencies when a tagged sheet and an opponent are set.", "", "/#football"),
    "scribe": _on_request("Files notes when you send it one (start the message with NB:).", "", "/#football"),
    "depth": _on_request("Builds the opponent personnel sheet every Monday during the season.", "Upload the depth chart and stats.", "/#football"),
}


# ---- the report --------------------------------------------------------------------------------------------

def _why(agent) -> dict | None:
    """Why this agent has nothing to do right now, as {why, unlock, link}, or None when it has work."""
    from .agents.chad.publish import paused
    if paused():
        return {"why": "HQ is paused (Pause All).", "unlock": "Press Resume in the top bar.", "link": ""}
    if not agent.free and agent.schedule and ledger.over_budget(agent.village):
        return {"why": "Today's Claude budget is spent. It starts again tomorrow.", "unlock": "", "link": ""}
    check = REASONS.get(agent.name.lower())
    if not check:
        return None
    try:
        got = check()
    except Exception:
        traceback.print_exc()   # a broken look must never break the dashboard
        return None
    return {"why": got[0], "unlock": got[1], "link": got[2]} if got else None


def build() -> list[dict]:
    from . import agents
    since = _ago(days=7)
    out = []
    for agent in agents.AGENTS.values():
        name = agent.name
        running = db.rows("SELECT instructions FROM tasks WHERE agent = ? AND status = 'running' LIMIT 1", name)
        queued = _n("SELECT COUNT(*) n FROM tasks WHERE agent = ? AND status = 'queued'", name)
        runs = _n("SELECT COUNT(*) n FROM tasks WHERE agent = ? AND created_at >= ? AND status IN ('done', 'failed')", name, since)
        failed = _n("SELECT COUNT(*) n FROM tasks WHERE agent = ? AND created_at >= ? AND status = 'failed'", name, since)
        last = db.rows("SELECT updated_at, result FROM tasks WHERE agent = ? AND status IN ('done', 'failed') ORDER BY id DESC LIMIT 1", name)
        reason = None if (running or queued) else _why(agent)
        if running:
            state = "working"
        elif queued:
            state = "queued"
        elif reason:
            state = "waiting"
        else:
            state = "ready"
        out.append({"name": name, "village": agent.village, "state": state, "doing": running[0]["instructions"] if running else None,
                    "runs_7d": runs, "failed_7d": failed, "last_run": last[0]["updated_at"] if last else None,
                    "last_result": (last[0]["result"] or "")[:160] if last else None,
                    "why": reason["why"] if reason else None, "unlock": reason["unlock"] if reason else None,
                    "link": reason["link"] if reason else None,
                    "scheduled": bool(agent.schedule)})
    return out


def report() -> list[dict]:
    if time.time() - _cache["at"] > CACHE_SECONDS:
        _cache["rows"] = build()
        _cache["at"] = time.time()
    return _cache["rows"]


def by_name() -> dict:
    return {r["name"]: r for r in report()}


def brief() -> list[str]:
    """One line per agent, for the Boss: who is working, who is waiting and what for."""
    lines = []
    for r in report():
        if r["state"] in ("working", "queued"):
            lines.append(f"{r['name']}: {r['state']}" + (f" on \"{r['doing']}\"" if r["doing"] else ""))
        elif r["state"] == "waiting":
            lines.append(f"{r['name']}: idle. {r['why']}" + (f" To fix: {r['unlock']}" if r["unlock"] else ""))
        else:
            lines.append(f"{r['name']}: ready ({r['runs_7d']} rounds in 7 days)")
    return lines
