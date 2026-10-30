"""Muse, the Creative Director: thinks up new ways for HQ to make money and run better, ranks them, and brings the
best ones to Approvals.

Once a week the Boss sends Muse on its round (or you press "Brainstorm now", or ask the Boss), and Muse gathers the facts HQ already has for free
(the team, the money, the views, the campaigns, the leads, Sweep's findings and your past yes and no answers) and makes
one Claude call for a handful of ideas: new businesses, new agents, add-ons to what HQ already does, and HQ upgrades.

Code, not Claude, then:
- drops ideas that repeat anything already built, already shown to you, parked or turned down (KNOWN below, plus
  every idea Muse ever had), and anything that breaks HQ's rules (OFF_LIMITS below);
- ranks the rest by one honest number: expected first-year profit for each hour of work (see score());
- puts the top few in Approvals (dashboard and Telegram). "Build it" writes a build brief and, once HQ_BUILD_TOKEN is
  set, sends it straight to Claude in Steven's project, where a new thread builds it (see start_build()).

Money: before a weekly round, free checks in code decide whether there is anything to do (no room for new ideas
because you haven't answered the last ones, too soon since the last round, the month's cap reached), so an idle week
costs nothing. The weekly round goes through Claude's batch queue at half price (no one is waiting on it; the ideas
land within the hour, a day at most), asks only for as many ideas as there is room for, and thinks at medium effort.
Every round, weekly or not, stays under HQ_DAILY_BUDGET and Muse's own monthly cap (HQ_MUSE_MONTHLY_BUDGET).
"""

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from . import approvals, build_progress, db, ledger, llm
from .config import DAILY_BUDGET, DATA_DIR, PRICES, UNKNOWN_PRICE, VISION_PATH, model_for

MUSE_DIR = DATA_DIR / "muse"
STATE_PATH = MUSE_DIR / "state.json"

KINDS = {"business": "New business", "agent": "New agent", "addon": "Add-on", "hq": "HQ upgrade"}
EFFORTS = ("small", "medium", "large")
BUILD_HOURS = {"small": 2, "medium": 6, "large": 15}   # Claude's build work, counted as if it were hours of yours
REASONS = ("Too expensive", "Too much work", "Not my thing", "Already doing it", "Bad timing")
MAX_TOKENS = 12000          # thinking plus up to 8 short ideas fits well inside this; a cut-off answer is wasted money
PROMPT_TOKENS = 8000        # a little over what the prompt is (the no-repeat list is most of it), for the estimate
BATCH_RATE = 0.5            # Claude's batch queue charges half the list price
MIN_NEW = 3                 # a weekly round waits until there is room for at least this many new ideas
BATCH_DAYS_MAX = 26 / 24    # the queue finishes within 24 hours; after this a round is given up and retried
HOUR_VALUE = 15   # dollars: what an hour of Steven's time saved is worth, for ideas that save time instead of earning


def _num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def enabled() -> bool:
    return os.getenv("HQ_MUSE", "true").strip().lower() not in ("false", "0", "no", "off")


def every_days() -> float:
    return max(1.0, _num("HQ_MUSE_EVERY_DAYS", 7))


def per_round() -> int:
    return int(min(8, max(3, _num("HQ_MUSE_IDEAS", 5))))


def to_approvals() -> int:
    return int(min(per_round(), max(0, _num("HQ_MUSE_TO_APPROVALS", 3))))


def monthly_budget() -> float:
    return max(0.0, _num("HQ_MUSE_MONTHLY_BUDGET", 3))


def use_batch() -> bool:
    """The weekly round goes through the half-price batch queue unless HQ_MUSE_BATCH=false."""
    return os.getenv("HQ_MUSE_BATCH", "true").strip().lower() not in ("false", "0", "no", "off")


def effort() -> str:
    e = os.getenv("HQ_MUSE_EFFORT", "medium").strip().lower()
    return e if e in ("low", "medium", "high") else "medium"


# ---- what Muse must not pitch again ----------------------------------------------------------------------
# Everything already built, already on one of Steven's ideas pages (waiting for his pick), parked or turned down.
# Muse may build on these (an add-on to a built agent is welcome), but never pitch one again as if it were new.
# " | " separates other ways the same idea tends to be named, so code catches it under those names too.
BUILT, WAITING, PARKED, DECLINED = "built", "on an earlier ideas page, waiting for Steven's pick", "parked", "turned down"
KNOWN = [
    # built and running in HQ
    ("Boss: directs every agent and sends a daily report", BUILT),
    ("Chad: clips streamers into TikToks, Shorts and Reels", BUILT),
    ("Scout: finds and rates paid clipping campaigns, suggests streamers to clip", BUILT),
    ("Pitch: finds creators who would pay for clipping, drafts pitches, one-tap Gmail send and follow-ups", BUILT),
    ("Closer: turns pitch replies into quotes with a Stripe payment link, you approve each one; Won clients count", BUILT),
    ("Relay: Telegram bot for Boss chat, alerts and approval buttons", BUILT),
    ("Ledger: Claude cost per agent, cheaper model per agent, daily budget", BUILT),
    ("Tally: view counts on posted clips, campaign pay estimate, what worked goes back to Chad", BUILT),
    ("Gate: scores waiting clips from your past approvals, holds likely rejects, sorts the best to the top", BUILT),
    ("Sweep: janitor, cost watcher and quality control with a daily How to improve HQ report", BUILT),
    ("Money strip: spent, made and net at the top of HQ", BUILT),
    ("Profit page: money in minus money out", BUILT),
    ("Shared approvals queue on the dashboard and Telegram", BUILT),
    ("Getting-started checklist with Test buttons for every key", BUILT),
    ("Practice mode: pretend posting", BUILT),
    ("Automatic tests before updates reach the PC", BUILT),
    ("Crash-proof task queue", BUILT),
    ("Database tune-up", BUILT),
    ("Prompt caching for the Boss", BUILT),
    ("Posting seatbelts and a Pause All button", BUILT),
    ("Taste trainer: Chad learns from approved and rejected clips", BUILT),
    ("Open HQ from the Mac over Tailscale", BUILT),
    ("Desktop app that updates itself", BUILT),
    ("HQ Town villages with clickable buildings and agent cards", BUILT),
    ("Dashboard tabs", BUILT),
    ("Warrior Village: Captain, Clock, Ref, Tells, Scribe and Depth for Steven's football job", BUILT),
    ("Thursday printing of the opponent folder", BUILT),
    ("Depth: Monday opponent personnel sheet with auto-fetch", BUILT),
    ("Muse: Creative Director that ranks new ideas", BUILT),
    ("Recruiter: finds gaps in HQ and proposes new agents with a 1 to 10 rating | agent recruiter | hiring agent", BUILT),
    ("Queue: daily pitch quota and send list for Pitch, best fit first | agent queue | send list | pitch quota", BUILT),
    ("Nudge: finds replies to Pitch emails in Gmail and flags replied, bounced and quiet leads | agent nudge | pitch replies | reply tracker", BUILT),
    ("Etsy village: shirt designs on Etsy through Printify, with Etta, Radar, Quill, Loom, Warden and Dock | print on demand shirts | Etsy shop", BUILT),
    # the earlier agent ideas page
    ("Penny: views and stats for every clip | clip performance dashboard | clip stats dashboard", WAITING),
    ("Medic: keeps HQ healthy while you're away | HQ health monitor", WAITING),
    ("Sunny: morning brief | daily brief | daily digest", WAITING), ("Tutor: daily coding lessons using HQ", WAITING),
    ("Dubs: clips re-captioned in other languages", WAITING), ("Pixel: stream overlays to sell", WAITING),
    ("Hype: TikTok Shop affiliate videos", WAITING), ("Bill tracker: forgotten subscriptions and bills", WAITING),
    ("Remy: reminders and to-dos by text", WAITING), ("Loot: free game alerts", WAITING),
    ("Gus: meal plans and shopping list", WAITING), ("Hawk: price watch alerts", WAITING),
    ("Sorty: inbox sorting and draft replies", WAITING), ("Keeper: receipts, returns and warranties", WAITING),
    ("Mainstreet: websites for local businesses", WAITING), ("Inky: print-on-demand designs and Etsy listings", BUILT),
    ("Echo: weekly newsletter writer | weekly newsletter", WAITING), ("Coach: daily habit check-ins", WAITING),
    ("Paper: explains letters, bills and forms from a photo", WAITING),
    ("Stars: Google review replies for local businesses", WAITING), ("Flip: resale deal finder", WAITING),
    # the earlier HQ upgrades page
    ("Explain this error button", WAITING), ("Fast clip review mode", WAITING),
    ("Keep running in the background tray mode", WAITING), ("Undo an update", WAITING),
    ("Outside alarm if the PC goes down | uptime monitor | heartbeat ping", WAITING), ("Offsite backups that survive a dead PC", WAITING),
    ("HQ as an app on your phone | phone app", WAITING), ("Smarter phone alerts with quiet hours | alert digest", WAITING),
    ("Permission locker with proof", WAITING), ("Lock up keys and the login", WAITING),
    ("Change history with Undo", WAITING), ("Half-price batch jobs", WAITING),
    ("Budgets per agent and a month forecast", WAITING), ("Let viewers pick the moments from chat spikes", WAITING),
    ("Goals the Boss works toward | goals tracker | money goals", WAITING),
    ("Post through a posting service | Upload-Post", WAITING),
    ("Posting schedule | best time to post | posting time optimizer", WAITING), ("Clip style presets", WAITING),
    ("Client page for paying creators | client portal | client onboarding page", WAITING),
    ("Account manager for clipping accounts", WAITING), ("A town that grows with your business", WAITING),
    ("Living town events", WAITING), ("Hire an agent without code", WAITING),
    ("Let the Boss look things up on the web", WAITING), ("Edit the Boss's brain in the app", WAITING),
    # the earlier online business plan
    ("Etta: Etsy shop of digital football coaching tools | practice plan templates | wristband call cards | "
     "depth chart templates | scouting report templates | youth coach starter kit | football squares printables | "
     "game day printables", WAITING), ("Print on demand in the same Etsy shop", WAITING),
    ("Own template store plus product clips", WAITING), ("Coaching newsletter", WAITING),
    ("Football IQ short videos in your voice", WAITING), ("Amazon KDP coaching logbooks", WAITING),
    ("Gear affiliate links", WAITING), ("Freelance video editing on Fiverr", WAITING),
    ("Paid sports stats spreadsheets", WAITING),
    # Steven's calls
    ("Run HQ on a cloud server 24/7", PARKED),
    ("Hudl film access for the football agents", DECLINED),
    ("Auto-send pitch emails without a tap", DECLINED),
    ("High school highlight reels", DECLINED),
]

# Ideas that break HQ's rules or Steven's calls. Checked in code on every idea's title and pitch.
OFF_LIMITS = [
    (r"\b(sports? betting|betting|gambl\w*|parlays?|day[- ]trad\w*|forex|crypto trad\w*|trading bots?)\b",
     "real-money betting or trading"),
    (r"\b(view ?bots?|buy(ing)? (views|followers|likes)|fake (views|followers|likes|reviews?|testimonials?)|"
     r"engagement pods?|review swaps?)\b", "fake engagement or fake reviews"),
    (r"\b(mass|bulk|automated|auto)[- ](dms?|direct messages?|comments?|commenting|repl(y|ies))\b", "spam bots"),
    (r"\bscrap\w*\b[^.]*\b(whop|discord)\b|\b(whop|discord)\b[^.]*\bscrap\w*", "scraping Whop or Discord"),
    (r"\b(school|university|college|team|program)'?s? (name|logo|film|footage)\b", "his school's name, logo or film"),
    (r"\b(recruits?|recruiting)\b[^.]*\b(sell|selling|reels?|paid|charge|service)\b", "selling to recruits (NCAA rules)"),
    (r"\bdropship\w*", "dropshipping"),
    (r"\b(plr|private label rights|prompt (packs?|bundles?))\b", "reselling bundles or prompts"),
    (r"\bfaceless\b", "faceless AI channels"),
    (r"\b(nfl|ncaa|nba|mlb|super bowl)\b[^.]*\b(merch|shirts?|logos?|apparel|mugs?)\b", "league trademarks"),
    (r"\bwithout (your|steven'?s|his) (approval|ok|tap)\b|\bskip(s|ping)? (the )?approvals?\b",
     "skipping Steven's approval"),
    (r"\b(cloud servers?|vps|oracle cloud|vultr|hetzner|host(ing)? hq (in|on) the cloud)\b",
     "cloud hosting (Steven put it on the back burner)"),
    (r"\bhudl\b", "Hudl film access (Steven said skip it)"),
]


def off_limits(text: str) -> str | None:
    low = text.lower()
    for pattern, why in OFF_LIMITS:
        if re.search(pattern, low):
            return why
    return None


_STOP = set("a an the and or for to of in on with your you my me i hq agent agents new that this from by into it its at "
            "as is be more add adds addon add-on auto automatic automated steven steven's based using via per one out up "
            "make makes get gets help helps who what how when tool tools system simple smart better".split())


def _stem(w: str) -> str:
    """Rough, but enough to match "templates" with "template" and "printables" with "printable"."""
    for suf in ("ing", "ers", "er", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            w = w[:-len(suf)]
            break
    return w[:-1] if w.endswith("e") and len(w) > 4 else w


def words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in _STOP and len(w) > 1}


def similar(a: str, b: str) -> bool:
    """Two titles name the same idea: half their words shared, or two or more shared and most of the shorter one."""
    A, B = words(a), words(b)
    if not A or not B:
        return False
    both = len(A & B)
    return both / len(A | B) >= 0.5 or (both >= 2 and both / min(len(A), len(B)) >= 0.75)


def _past_ideas() -> list[dict]:
    return db.rows("SELECT id, kind, title, name, status, reason FROM ideas ORDER BY id")


def repeat_of(title: str, extra: list[str] = ()) -> str | None:
    """The known idea (built, shown, parked, declined or one of Muse's own) that this title repeats, if any."""
    for known, _ in KNOWN:
        main, *also = known.split(" | ")
        name = main.split(":")[0]
        if any(similar(title, k) for k in [main, *also]) or (":" in main and similar(title, name) and len(words(title)) <= 2):
            return main
    for p in _past_ideas():
        if similar(title, p["title"]):
            return p["title"]
    for t in extra:
        if similar(title, t):
            return t
    return None


# ---- ranking ---------------------------------------------------------------------------------------------

def _clamp(x, lo, hi, default=0.0) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, x))


def clean(raw: dict) -> dict:
    """Make Claude's numbers sane before anything is worked out from them."""
    low = _clamp(raw.get("profit_low_usd_month"), 0, 20000)
    high = _clamp(raw.get("profit_high_usd_month"), 0, 20000)
    effort = raw.get("effort") if raw.get("effort") in EFFORTS else "medium"
    kind = raw.get("kind") if raw.get("kind") in KINDS else "addon"
    return {
        "kind": kind,
        "title": " ".join(str(raw.get("title") or "").split())[:80],
        "name": (str(raw.get("name") or "").strip()[:24] or None) if kind == "agent" else None,
        "pitch": str(raw.get("pitch") or "").strip()[:900],
        "why_now": str(raw.get("why_now") or "").strip()[:500],
        "builds_on": [str(x)[:40] for x in (raw.get("builds_on") or [])][:6],
        "first_steps": [str(x)[:220] for x in (raw.get("first_steps") or [])][:6],
        "steven_does": str(raw.get("steven_does") or "").strip()[:400],
        "risks": str(raw.get("risks") or "").strip()[:400],
        "start_cost": _clamp(raw.get("start_cost_usd"), 0, 5000),
        "monthly_cost": _clamp(raw.get("monthly_cost_usd"), 0, 2000),
        "effort": effort,
        "effort_hours": _clamp(raw.get("effort_hours"), 0.5, 200, 10),
        "profit_low": min(low, high),
        "profit_high": max(low, high),
        "months_to_first": _clamp(raw.get("months_to_first_dollar"), 0, 24, None) if raw.get("months_to_first_dollar") is not None else None,
        "confidence": _clamp(raw.get("confidence"), 0.05, 0.95, 0.3),
        "repeats": (str(raw.get("repeats")).strip() or None) if raw.get("repeats") else None,
    }


def expected_month(i: dict) -> float:
    """What it should bring in a month once running, weighed by how sure Muse is, minus what it costs to run."""
    return (i["profit_low"] + i["profit_high"]) / 2 * i["confidence"] - i["monthly_cost"]


def score(i: dict) -> float:
    """Expected first-year profit for each hour it takes: Steven's own hours plus Claude's build, counted as hours.
    Plain arithmetic, so the order never depends on how excited the write-up sounds."""
    first_year = expected_month(i) * 12 - i["start_cost"]
    return round(first_year / (i["effort_hours"] + BUILD_HOURS.get(i["effort"], 6)), 1)


def payback_months(i: dict) -> float | None:
    m = expected_month(i)
    if m <= 0:
        return None
    return round(i["start_cost"] / m, 1)


# ---- the facts Muse thinks about (all free) --------------------------------------------------------------

def _month_start() -> str:
    return datetime.now().astimezone().replace(day=1, hour=0, minute=0, second=0, microsecond=0) \
        .astimezone(timezone.utc).isoformat(timespec="seconds")


def spent_this_month() -> float:
    return db.rows("SELECT COALESCE(SUM(cost_usd), 0) c FROM llm_usage WHERE LOWER(agent) = 'muse' AND created_at >= ?",
                   _month_start())[0]["c"]


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def facts() -> dict:
    """A snapshot of HQ for Muse to think about. Reads only; never calls Claude."""
    from . import activity, agents, campaigns, creators, money, tally
    from .config import village_of
    team = [{"name": a.name, "role": a.role, "village": village_of(a.name)} for a in agents.AGENTS.values()]
    months = _safe(lambda: money.summary().get("periods", {}), {})
    clips = {r["status"]: r["n"] for r in db.rows("SELECT status, COUNT(*) n FROM clips GROUP BY status")}
    posts = {r["platform"]: r["n"] for r in db.rows("SELECT platform, COUNT(*) n FROM posts WHERE status = 'posted' "
                                                     "GROUP BY platform")}
    camps = _safe(campaigns.summary, []) or []
    leads = {r["status"]: r["n"] for r in db.rows("SELECT status, COUNT(*) n FROM leads GROUP BY status")}
    sweep_tips = []
    try:
        from . import sweep
        rep = sweep.latest().get("report") or {}
        sweep_tips = [t["title"] for t in (rep.get("improve") or {}).get("tips", [])[:5]]
    except Exception:
        pass
    by_agent = db.rows("SELECT agent, ROUND(SUM(cost_usd), 2) usd FROM llm_usage WHERE created_at >= ? GROUP BY agent "
                       "ORDER BY usd DESC", _month_start())
    return {
        "team": team,
        "agents_idle": _safe(lambda: [{"name": r["name"], "why": r["why"], "rounds_7d": r["runs_7d"]}
                                      for r in activity.report() if r["state"] == "waiting"], []),   # capacity to put to work
        "money": months,   # today, month and all time: made (campaigns + logged income), spent (Claude + expenses), net
        "claude_cost_this_month_by_agent": by_agent,
        "clips_by_status": clips,
        "posted_by_platform": posts,
        "views": _safe(lambda: {k: v for k, v in tally.summary().items() if k in ("views_7d", "posts_counted_7d",
                                                                                   "estimated_campaign_pay_usd")}, {}),
        "campaigns": [{"name": c["name"], "status": c["status"], "rate_per_1k": c.get("rate_per_1k"),
                       "earned_usd": (c.get("totals") or {}).get("earned_usd")} for c in camps[:8]],
        "leads_by_status": leads,
        "creators_allowed": len(_safe(creators.allowed, []) or []),
        "waiting_in_approvals": db.rows("SELECT COUNT(*) n FROM approvals WHERE status = 'pending'")[0]["n"],
        "sweep_top_tips": sweep_tips,
    }


def _vision() -> str:
    try:
        return VISION_PATH.read_text(encoding="utf-8")[:3000]
    except OSError:
        return ""


def _decisions_text() -> str:
    rows = db.rows("SELECT title, kind, status, reason FROM ideas WHERE status != 'proposed' ORDER BY decided_at DESC "
                   "LIMIT 25")
    if not rows:
        return "Steven hasn't decided on any of Muse's ideas yet."
    say = {"approved": "said BUILD IT", "built": "built it", "parked": "said LATER", "rejected": "said NO"}
    return "\n".join(f"- {r['title']} ({KINDS.get(r['kind'], r['kind'])}): {say.get(r['status'], r['status'])}"
                     + (f", because: {r['reason']}" if r["reason"] else "") for r in rows)


SYSTEM = """You are Muse, the Creative Director of Agent HQ: Steven's team of AI agents that runs parts of his online
business from his own Windows PC. Your job is to come up with fresh, specific, creative ideas that make HQ more
profitable or more useful: new online businesses HQ could run, new agents for the team, add-ons to the businesses and
agents HQ already has, and upgrades to HQ itself.

Who Steven is: a beginner with code. Claude builds what he picks; he approves everything from the dashboard or his
phone. He works full time as a college football graduate assistant, so he has a few spare hours a week and a small
budget. Never use his school's name, logo or game film, and never sell anything to high school recruits.

What makes a good idea here:
- It builds on what HQ already has (the agents, the clipping accounts, the data, Steven's football know-how, the
  approvals queue, Telegram) instead of starting from zero. Look hard at the numbers below for openings.
- It fits a few hours a week of Steven's time and a small budget. Start-up cost under $50 unless it clearly pays back.
- It is specific enough to start this week: name the platform, the product, the buyer, and the first steps.
- It is honest. A range can start at $0. Confidence is how likely the range is, not how much you like the idea.
- It keeps HQ's rules: nothing posts, sends, publishes or spends without Steven's tap; official APIs only, no
  scraping sites whose terms forbid it; no spam, fake engagement, real-money betting or trading, trademarked merch,
  or reposting anyone's content without permission.
- It is new. The list of ideas already built, already shown to Steven, parked or turned down is below. Do not pitch
  any of them again under another name. Building on them is welcome (an add-on to a built agent, a new product line
  for a waiting business). If an idea overlaps one, put that one's title in "repeats" and it will be dropped.
- It learns from Steven's past answers: more like what he said yes to, nothing like what he turned down.

Numbers, per idea:
- profit_low_usd_month / profit_high_usd_month: money in per month after platform fees, 3 to 6 months after it
  starts. For ideas that save time instead of earning, count each hour a month saved as $15 and say so in the pitch.
- monthly_cost_usd: what it costs to keep running (subscriptions, Claude, fees). start_cost_usd: one-off costs.
- effort: how much Claude has to build (small = one pull request, medium = two or three, large = a project).
- effort_hours: Steven's own hours in the first month: sign-ups, setup, his part of running it.

Write for Steven: short, plain sentences, no hype, no jargon. Titles under 8 words. Keep every field tight: a pitch
under 60 words, steps under 15 words each, one sentence each for why_now, steven_does and risks."""

ITEM = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "title": {"type": "string", "description": "Under 8 words"},
        "name": {"type": ["string", "null"], "description": "For a new agent only: a short friendly name"},
        "pitch": {"type": "string", "description": "2 to 4 sentences: what it is, who pays, how HQ does it"},
        "why_now": {"type": "string", "description": "One sentence tying it to a fact about HQ today"},
        "builds_on": {"type": "array", "items": {"type": "string"}, "description": "Agents or businesses it uses"},
        "first_steps": {"type": "array", "items": {"type": "string"}, "description": "3 to 5 concrete steps"},
        "steven_does": {"type": "string", "description": "Exactly what only Steven can do, with minutes"},
        "risks": {"type": "string"},
        "start_cost_usd": {"type": "number"},
        "monthly_cost_usd": {"type": "number"},
        "effort": {"type": "string", "enum": list(EFFORTS)},
        "effort_hours": {"type": "number"},
        "profit_low_usd_month": {"type": "number"},
        "profit_high_usd_month": {"type": "number"},
        "months_to_first_dollar": {"type": ["number", "null"]},
        "confidence": {"type": "number", "description": "0 to 1"},
        "repeats": {"type": ["string", "null"], "description": "Title of a known idea this overlaps, else null"},
    },
    "required": list(["kind", "title", "name", "pitch", "why_now", "builds_on", "first_steps", "steven_does", "risks",
                      "start_cost_usd", "monthly_cost_usd", "effort", "effort_hours", "profit_low_usd_month",
                      "profit_high_usd_month", "months_to_first_dollar", "confidence", "repeats"]),
    "additionalProperties": False,
}
SCHEMA = {"type": "object", "properties": {"ideas": {"type": "array", "items": ITEM}},
          "required": ["ideas"], "additionalProperties": False}


def prompt(focus: str | None, n: int) -> str:
    known = "\n".join(f"- {t} [{s}]" for t, s in KNOWN)
    mine = "\n".join(f"- {p['title']} [{p['status']}]" for p in _past_ideas()) or "- none yet"
    ask = (f"Steven asked you to think about: {focus.strip()[:500]}\nKeep most ideas on that, and still follow the rules."
           if focus else f"Give {n} ideas: at least one new business, one new agent and one add-on to something HQ "
                         "already does. The rest can be anything that scores well, HQ upgrades included.")
    return f"""Today is {datetime.now():%A %d %B %Y}. Think about the season too (football calendar, holidays, platform trends).

STEVEN'S VISION FILE
{_vision()}

HQ TODAY (live numbers)
{json.dumps(facts(), separators=(",", ":"), default=str)}

ALREADY BUILT, SHOWN, PARKED OR TURNED DOWN (never pitch these again)
{known}

MUSE'S OWN EARLIER IDEAS (never repeat)
{mine}

STEVEN'S ANSWERS SO FAR
{_decisions_text()}

YOUR TASK
{ask}
Give exactly {n} ideas. Make them different from each other."""


# ---- state, guards and the round -------------------------------------------------------------------------

def _state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(s: dict):
    MUSE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1), encoding="utf-8")
    tmp.replace(STATE_PATH)


def round_cost_estimate(weekly: bool = False) -> float:
    """The most one round can cost: the prompt plus a full answer, on Muse's model. A weekly round through the batch
    queue costs half."""
    price_in, price_out = PRICES.get(model_for("muse"), UNKNOWN_PRICE)
    rate = BATCH_RATE if weekly and use_batch() else 1.0
    return round((PROMPT_TOKENS * price_in + MAX_TOKENS * price_out) * rate / 1_000_000, 3)


def open_ideas() -> int:
    """Ideas waiting for Steven's answer. The Recruiter's proposals have their own cap, so they never hold Muse back."""
    return db.rows("SELECT COUNT(*) n FROM ideas WHERE status = 'proposed' AND COALESCE(source, 'muse') != 'recruiter'")[0]["n"]


def _days_since_round(state: dict | None = None) -> float | None:
    at = (state if state is not None else _state()).get("last_round_at")
    if not at:
        return None
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(at)).total_seconds() / 86400
    except ValueError:
        return None


def pending() -> dict | None:
    """The weekly round waiting in Claude's batch queue, if there is one."""
    return _state().get("batch")


def money_blocker(weekly: bool = False) -> str | None:
    """Why a round can't spend right now, or None. Holds for every round, even when you press the button."""
    est = round_cost_estimate(weekly)
    cap = monthly_budget()
    if cap <= 0:
        return "Muse's monthly budget (HQ_MUSE_MONTHLY_BUDGET) is 0, so Muse is switched off."
    if spent_this_month() + est > cap:
        return (f"Muse has used ${spent_this_month():.2f} of its ${cap:.2f} for this month, and a round can cost up to "
                f"${est:.2f}. It starts again next month, or raise HQ_MUSE_MONTHLY_BUDGET in Settings.")
    if DAILY_BUDGET > 0 and ledger.spent_today("business") + est > DAILY_BUDGET:
        return "Today's Claude budget (HQ_DAILY_BUDGET) is nearly spent. Muse will try again tomorrow."
    return None


def why_not_now(manual: bool = False) -> str | None:
    """The free look before a round. None means go ahead. A weekly round also waits for the week to pass and for room
    for at least MIN_NEW new ideas, so ideas never pile up unread and an idle week costs nothing."""
    if not llm.HAS_LLM:
        return "Muse needs the Anthropic API key (Settings) to think up ideas."
    if pending():
        return "Muse's weekly round is with Claude's half-price queue. The ideas land here within the hour, a day at most."
    if not enabled() and not manual:
        return "Muse's weekly round is switched off (HQ_MUSE=false). Brainstorm now still works."
    blocked = money_blocker(weekly=not manual)
    if blocked:
        return blocked
    if manual:
        return None
    n = open_ideas()
    if per_round() - n < MIN_NEW:
        return (f"{n} ideas are still waiting for your answer on the Ideas tab, so Muse waits until there's room for "
                f"at least {MIN_NEW} new ones.")
    days = _days_since_round()
    if days is not None and days < every_days():
        return f"Next round in about {max(1, round(every_days() - days))} day(s)."
    return None


def mark_built_agents() -> int:
    """Free check: an approved agent idea whose agent now exists in HQ is marked built."""
    from . import agents
    have = set(agents.AGENTS)
    n = 0
    for r in db.rows("SELECT id, name, title FROM ideas WHERE status = 'approved' AND kind = 'agent'"):
        if (r["name"] or "").lower() in have:
            db.execute("UPDATE ideas SET status = 'built', decided_at = ? WHERE id = ?", db.now(), r["id"])
            db.log("Muse", f"Spotted that \"{r['title']}\" is now built ({r['name']} joined the team)")
            n += 1
    return n


def _usd(x) -> str:
    x = float(x or 0)
    return f"${x:,.0f}" if x >= 10 or x == int(x) else f"${x:,.2f}"


def card_text(i: dict) -> str:
    """The approval card: short enough for a phone."""
    steps = json.loads(i["first_steps"]) if isinstance(i["first_steps"], str) else i["first_steps"]
    pay = payback_months(i)
    lines = [
        f"{KINDS.get(i['kind'], i['kind'])} · score {i['score']:g}",
        i["pitch"],
        f"💰 About {_usd(i['profit_low'])} to {_usd(i['profit_high'])} a month · costs {_usd(i['start_cost'])} to start"
        + (f" + {_usd(i['monthly_cost'])}/month" if i["monthly_cost"] else ""),
        f"⏱️ {i['effort'].title()} build · about {i['effort_hours']:g} h of your time"
        + (f" · first dollar in ~{i['months_to_first']:g} month(s)" if i.get("months_to_first") is not None else "")
        + (f" · pays back in ~{pay:g} month(s)" if pay else ""),
    ]
    if i.get("why_now"):
        lines.append(f"Why now: {i['why_now']}")
    if steps:
        lines.append("First steps: " + " ".join(f"{n}) {s}" for n, s in enumerate(steps[:3], 1)))
    return "\n".join(lines)


def brief(i: dict) -> str:
    """What to paste to Claude to build an approved idea."""
    steps = json.loads(i["first_steps"]) if isinstance(i["first_steps"], str) else i["first_steps"]
    builds = json.loads(i["builds_on"]) if isinstance(i["builds_on"], str) else i["builds_on"]
    parts = [f"Build this for Agent HQ (github.com/stevenvictor247/CHADCLIP): {i['title']}"
             + (f", a new agent called {i['name']}" if i.get("name") else ""),
             f"\nWhat it is: {i['pitch']}"]
    if i.get("why_now"):
        parts.append(f"Why now: {i['why_now']}")
    if builds:
        parts.append("Builds on: " + ", ".join(builds))
    if steps:
        parts.append("First steps:\n" + "\n".join(f"{n}. {s}" for n, s in enumerate(steps, 1)))
    if i.get("steven_does"):
        parts.append(f"What I'll do myself: {i['steven_does']}")
    if i.get("risks"):
        parts.append(f"Watch out for: {i['risks']}")
    parts.append(f"Money: about {_usd(i['start_cost'])} to start, {_usd(i['monthly_cost'])} a month; Muse expects "
                 f"{_usd(i['profit_low'])} to {_usd(i['profit_high'])} a month.")
    parts.append("Follow HQ's rules: nothing posts, sends, publishes or spends without my approval; stay inside the "
                 "Claude budget; free checks in code before spending tokens; tests before merging.")
    return "\n".join(parts)


def _row(idea_id: int) -> dict:
    rows = db.rows("SELECT * FROM ideas WHERE id = ?", idea_id)
    if not rows:
        raise ValueError(f"No idea #{idea_id}")
    return rows[0]


def save(i: dict, focus: str | None) -> int:
    i["score"] = score(i)
    return db.execute(
        "INSERT INTO ideas (kind, title, name, pitch, why_now, builds_on, first_steps, steven_does, risks, start_cost, "
        "monthly_cost, effort, effort_hours, profit_low, profit_high, months_to_first, confidence, score, focus, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        i["kind"], i["title"], i["name"], i["pitch"], i["why_now"], json.dumps(i["builds_on"]),
        json.dumps(i["first_steps"]), i["steven_does"], i["risks"], i["start_cost"], i["monthly_cost"], i["effort"],
        i["effort_hours"], i["profit_low"], i["profit_high"], i["months_to_first"], i["confidence"], i["score"],
        (focus or None), db.now())


def sift(raw_ideas: list[dict]) -> tuple[list[dict], list[str]]:
    """Clean every idea, then drop repeats and rule breakers. Returns (kept, why each dropped one was dropped)."""
    kept, dropped = [], []
    for raw in raw_ideas:
        i = clean(raw)
        if not i["title"] or not i["pitch"]:
            continue
        rule = off_limits(f"{i['title']}. {i['pitch']}")
        if rule:
            dropped.append(f"\"{i['title']}\" ({rule})")
            continue
        same = repeat_of(i["title"], [k["title"] for k in kept])
        if i["name"] and not same:
            same = repeat_of(i["name"])
            same = same if same and similar(i["name"], same.split(":")[0]) else None
        if same or i["repeats"]:
            dropped.append(f"\"{i['title']}\" (repeats {same or i['repeats']})")
            continue
        kept.append(i)
    return kept, dropped


def _params(focus: str | None, n: int) -> dict:
    """The one Claude request a round makes, the same whether it goes live or through the batch queue."""
    return dict(model=model_for("muse"), max_tokens=MAX_TOKENS, system=SYSTEM,
                messages=[{"role": "user", "content": prompt(focus, n)}], thinking={"type": "adaptive"},
                output_config={"effort": effort(), "format": {"type": "json_schema", "schema": SCHEMA}})


def wanted(manual: bool) -> int:
    """How many ideas to ask for. A weekly round only fills the free places, so Claude never writes ideas that would
    sit behind ones you haven't answered yet."""
    return per_round() if manual else max(MIN_NEW, per_round() - open_ideas())


def run(focus: str | None = None, manual: bool = False) -> str:
    """One round. Free checks first; then one Claude call (the weekly round through the half-price batch queue); then
    code sifts, ranks and files the ideas."""
    mark_built_agents()
    blocked = why_not_now(manual)
    if blocked:
        return ("Skipped: " if not manual else "") + blocked
    n = wanted(manual)
    state = _state()
    state["last_round_at"] = db.now()   # saved before the call: a failing round must not be retried every tick
    _save_state(state)
    params = _params(focus, n)
    if not manual and use_batch():
        batch = llm.client().messages.batches.create(requests=[{"custom_id": "muse", "params": params}])
        state["batch"] = {"id": batch.id, "at": db.now(), "n": n, "focus": focus or None}
        _save_state(state)
        out = (f"Asked Claude for {n} ideas through the half-price queue. They land on the Ideas tab within the hour, "
               "a day at most.")
        db.log("Muse", out)
        return out
    p = dict(params)
    response = llm.create(p.pop("model"), p.pop("system"), p.pop("messages"), effort=effort(),
                          max_tokens=MAX_TOKENS, output_schema=SCHEMA, agent="Muse")
    return _file(llm.text_of(response), focus, getattr(response, "stop_reason", None))


def _file(text: str, focus: str | None, stop_reason: str | None = None) -> str:
    """Code's half of a round: sift, rank, save, and bring the best to Approvals."""
    try:
        data = json.loads(text or "{}")
    except ValueError:
        out = ("Claude's answer was cut off before the ideas were complete" if stop_reason == "max_tokens"
               else "Claude's answer couldn't be read") + ", so this round added nothing."
        db.log("Muse", out)
        return out
    kept, dropped = sift(data.get("ideas") or [])
    for i in kept:
        i["id"] = save(i, focus)
    ranked = sorted(kept, key=lambda i: -i["score"])
    sent = 0
    for i in ranked:
        if sent >= to_approvals() or i["score"] <= 0:
            break
        aid = approvals.request("Muse", "muse_idea", f"💡 {i['title']}", card_text(i), {"idea_id": i["id"]},
                                yes="👍 Build it", no="👎 Not for me")
        db.execute("UPDATE ideas SET approval_id = ? WHERE id = ?", aid, i["id"])
        sent += 1
    state = _state()
    state.update(last_round_at=db.now(), last_round={"at": db.now(), "kept": len(kept), "dropped": dropped,
                                                     "focus": focus or None})
    _save_state(state)
    if not kept:
        out = "No new ideas this round: everything Muse came up with repeated an earlier idea or broke a rule."
    else:
        best = ranked[0]
        out = (f"{len(kept)} new idea(s), {sent} brought to Approvals. Best: \"{best['title']}\" "
               f"(score {best['score']:g}, about {_usd(best['profit_low'])} to {_usd(best['profit_high'])} a month).")
    if dropped:
        out += f" Dropped {len(dropped)}: " + "; ".join(dropped)
    db.log("Muse", out[:600])
    return out


# ---- the half-price queue --------------------------------------------------------------------------------

def _age_days(at: str) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(at)).total_seconds() / 86400
    except ValueError:
        return BATCH_DAYS_MAX + 1


def batch_ready() -> bool:
    """Free look (one status check, no tokens): is the weekly round back from the queue, or overdue?"""
    b = pending()
    if not b:
        return False
    if _age_days(b.get("at") or "") > BATCH_DAYS_MAX:
        return True
    try:
        return llm.client().messages.batches.retrieve(b["id"]).processing_status == "ended"
    except Exception:
        return False   # offline for a moment: look again at the next check


def _give_up(b: dict, why: str) -> str:
    """A round that came back without ideas is tried again in about a day, not a week. Failed requests aren't billed."""
    state = _state()
    state.pop("batch", None)
    retry_from = datetime.now(timezone.utc) - timedelta(days=max(0.0, every_days() - 1))
    state["last_round_at"] = retry_from.isoformat(timespec="seconds")
    _save_state(state)
    out = f"Muse's weekly round didn't come back ({why}). Muse tries again in about a day."
    db.log("Muse", out)
    return out


def collect() -> str:
    """Pick up the weekly round from the queue, record its half-price cost, and file the ideas."""
    b = pending()
    if not b:
        return "No round waiting in the queue."
    try:
        batch = llm.client().messages.batches.retrieve(b["id"])
        if batch.processing_status != "ended":
            if _age_days(b.get("at") or "") <= BATCH_DAYS_MAX:
                return "Muse's ideas are still with Claude's queue."
            llm.client().messages.batches.cancel(b["id"])
            return _give_up(b, "it took over a day")
        results = list(llm.client().messages.batches.results(b["id"]))
    except Exception as e:
        return f"Couldn't reach Claude to pick up Muse's ideas ({e}). Muse looks again shortly."
    got = next((r.result for r in results if r.custom_id == "muse"), None)
    if got is None or got.type != "succeeded":
        return _give_up(b, getattr(got, "type", "no answer"))
    msg = got.message
    ledger.record("Muse", getattr(msg, "model", None) or model_for("muse"), msg.usage, rate=BATCH_RATE)
    state = _state()
    state.pop("batch", None)
    _save_state(state)
    if msg.stop_reason == "refusal":
        out = "Claude declined this round, so it added nothing."
        db.log("Muse", out)
        return out
    return _file(llm.text_of(msg), b.get("focus"), msg.stop_reason)


# ---- your answers ----------------------------------------------------------------------------------------

DECISIONS = {"build": "approved", "pass": "rejected", "later": "parked", "built": "built", "reopen": "proposed"}


def decide(idea_id: int, decision: str, reason: str | None = None, from_card: bool = False) -> str:
    if decision not in DECISIONS:
        raise ValueError("decision must be one of " + ", ".join(DECISIONS))
    i = _row(idea_id)
    status = DECISIONS[decision]
    reason = (reason or "").strip()[:200] or None
    db.execute("UPDATE ideas SET status = ?, reason = ?, decided_at = ? WHERE id = ?",
               status, reason if decision in ("pass", "later") else None, None if status == "proposed" else db.now(),
               idea_id)
    if i["approval_id"] and not from_card and decision != "reopen":   # close its Approvals card too
        db.execute("UPDATE approvals SET status = ?, decided_at = ? WHERE id = ? AND status = 'pending'",
                   "approved" if decision in ("build", "built") else "rejected", db.now(), i["approval_id"])
    if decision == "build":
        db.log("Muse", f"Steven wants to build \"{i['title']}\". The build brief is on the Ideas tab.")
        if build_ready():
            return f"👍 \"{i['title']}\" is approved. " + start_build(idea_id)
        return f"👍 \"{i['title']}\" is approved. Its build brief is on the Ideas tab: paste it to Claude to build it."
    if decision == "pass":
        db.log("Muse", f"Steven passed on \"{i['title']}\"" + (f": {reason}" if reason else ""))
        return f"Got it. Muse won't pitch \"{i['title']}\" again" + (" and will keep that reason in mind." if reason else ".")
    if decision == "later":
        return f"\"{i['title']}\" is parked. It stays on the Ideas tab under Later."
    if decision == "built":
        db.log("Muse", f"\"{i['title']}\" is built")
        return f"🎉 \"{i['title']}\" is marked built."
    return f"\"{i['title']}\" is back with the new ideas."


# ---- Build it -> Claude ----------------------------------------------------------------------------------
# "Build it" fires a Claude Code routine over HTTP (its API trigger). Steven makes the routine once on claude.ai
# (Scheduled, New task, Code, repo CHADCLIP, Add trigger, API, Generate token) and pastes its token and its /fire
# address into Settings. Each press starts a Claude Code session that builds the idea and opens a PR. The token only
# lets HQ start that one routine, and never leaves this PC except to Anthropic.
BUILD_URL_RE = re.compile(r"^https://api\.anthropic\.com/v1/claude_code/routines/trig_[A-Za-z0-9]+/fire$")


def build_url() -> str:
    return (os.getenv("HQ_BUILD_URL") or "").strip()


def build_ready() -> bool:
    return bool((os.getenv("HQ_BUILD_TOKEN") or "").strip()) and bool(BUILD_URL_RE.match(build_url()))


def _fire(text: str) -> dict:
    req = urllib.request.Request(build_url(), method="POST", data=json.dumps({"text": text}).encode(), headers={
        "Authorization": "Bearer " + os.getenv("HQ_BUILD_TOKEN", "").strip(), "anthropic-version": "2026-10-21",
        "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode() or "{}")


def _fire_error(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        try:
            msg = json.loads(e.read().decode()).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        why = {401: "the build token in Settings doesn't match (make a new one and paste it again)",
               400: "Claude turned the request down (is the routine paused?)",
               404: "the routine wasn't found (check HQ_BUILD_URL)",
               429: "too many builds this hour, try again later"}.get(e.code, f"Claude answered {e.code}")
        return why + (f": {msg[:150]}" if msg and e.code not in (401, 429) else "")
    return f"couldn't reach Claude ({type(e).__name__})"


def start_build(idea_id: int) -> str:
    """Send an approved idea's build brief to Claude. Each idea is sent once; a failed send can be tried again."""
    i = _row(idea_id)
    if i["status"] != "approved":
        return "Only an idea you said Build it to can be sent to Claude."
    if i.get("build_status") == "started":
        return "Claude already has this one. Look for its session under Code on claude.ai."
    if not build_ready():
        return "Build it isn't connected to Claude yet: add HQ_BUILD_TOKEN and HQ_BUILD_URL in Settings, or copy the build brief."
    text = (f"Idea #{i['id']}: {i['title']}\nSteven pressed Build it in Agent HQ on {datetime.now():%A %d %B %Y %H:%M}."
            f"\nPut \"Idea #{i['id']}\" in the title of your pull request: Agent HQ finds your PR by it to show Steven's progress bar."
            f"\n\nBUILD BRIEF (written by Muse)\n{brief(i)}")[:60000]
    try:
        out = _fire(text)
    except Exception as e:
        note = _fire_error(e)
        db.execute("UPDATE ideas SET build_status = 'failed', build_note = ?, build_at = ? WHERE id = ?",
                   note, db.now(), idea_id)
        db.log("Muse", f"Couldn't send \"{i['title']}\" to Claude to build: {note}")
        return f"It couldn't be sent to Claude to build: {note}. Try again from the Ideas tab, or copy the brief."
    url = out.get("claude_code_session_url")
    url = url if isinstance(url, str) and url.startswith("https://claude.ai/") else None
    db.execute("UPDATE ideas SET build_status = 'started', build_url = ?, build_note = NULL, build_at = ? WHERE id = ?",
               url, db.now(), idea_id)
    db.log("Muse", f"Sent \"{i['title']}\" to Claude to build")
    return "Sent to Claude to build it: its session shows up under Code on claude.ai shortly."


def _decide_card(payload: dict, decision: str) -> str:
    return decide(int(payload["idea_id"]), "build" if decision == "approve" else "pass", from_card=True)


approvals.HANDLERS["muse_idea"] = _decide_card


# ---- for the dashboard and the Boss ----------------------------------------------------------------------

def _shape(r: dict) -> dict:
    r = dict(r)
    for k in ("builds_on", "first_steps"):
        try:
            r[k] = json.loads(r[k] or "[]")
        except ValueError:
            r[k] = []
    r["expected_month"] = round(expected_month(r), 2)
    r["payback_months"] = payback_months(r)
    if r["status"] in ("approved", "built"):
        r["brief"] = brief(r)
    return r


def ideas(status: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM ideas", []
    if status:
        sql, args = sql + " WHERE status = ?", [status]
    return [_shape(r) for r in db.rows(sql + " ORDER BY score DESC, id DESC", *args)]


def summary() -> dict:
    """Small, for /api/state (the village) and the Boss."""
    top = db.rows("SELECT id, kind, title, score, profit_low, profit_high FROM ideas WHERE status = 'proposed' "
                  "ORDER BY score DESC, id DESC LIMIT 3")
    counts = {r["status"]: r["n"] for r in db.rows("SELECT status, COUNT(*) n FROM ideas GROUP BY status")}
    return {"open": counts.get("proposed", 0), "approved": counts.get("approved", 0), "built": counts.get("built", 0),
            "top": top, "thinking": bool(pending())}


def _next_round_text(state: dict) -> str:
    reason = why_not_now()
    if reason is None:
        return "The Boss sends Muse on its weekly round at the next check (within the hour)."
    return reason


def latest() -> dict:
    """Everything the Ideas tab shows."""
    mark_built_agents()
    state = _state()
    running = bool(db.rows("SELECT 1 FROM tasks WHERE agent = 'Muse' AND status IN ('queued', 'running') LIMIT 1"))
    return {
        "ideas": build_progress.add_to(ideas()),
        "last_round": state.get("last_round"),
        "next": _next_round_text(state),
        "running": running,
        "spent_month": round(spent_this_month(), 2),
        "monthly_budget": monthly_budget(),
        "round_cost": round_cost_estimate(),
        "weekly_cost": round_cost_estimate(weekly=True),
        "queued": bool(pending()),
        "every_days": every_days(),
        "per_round": per_round(),
        "model": model_for("muse"),
        "has_llm": llm.HAS_LLM,
        "reasons": list(REASONS),
        "kinds": KINDS,
        "build_ready": build_ready(),
        "how": "Muse ranks every idea by expected first-year profit for each hour of work: the middle of its money "
               "range times how sure Muse is, minus running costs, times 12, minus start-up costs, divided by your "
               "hours plus Claude's build time.",
    }
