"""Recruiter: finds the holes in how HQ runs and proposes new agents to fill them.

Recruiter reads what HQ already knows for free: Sweep's quality tips and failed work, the gaps Muse's ideas pointed
at, the money, the team and Steven's past answers. Then it makes one Claude call for a few agent proposals. Each one
names the gap it fixes, what it would cost to run and build, and gets a 1 to 10 rating worked out in code.

It shares Muse's table, no-repeat list, rules, Approvals card and Build it flow (see muse.py): a proposal is an idea of
kind "agent" with source "recruiter". Nothing is built, bought or started unless Steven taps Build it.

Pace: how many proposals a day depends on what a round costs on Recruiter's model. Cheap model, more; expensive
model, one a day (see per_day()). Free checks in code come first, so a day with nothing to do costs nothing.
"""

import json
import os
from datetime import datetime, timedelta, timezone

from . import approvals, db, ledger, llm, muse
from .config import DAILY_BUDGET, DATA_DIR, PRICES, UNKNOWN_PRICE, model_for

RECRUIT_DIR = DATA_DIR / "recruiter"
STATE_PATH = RECRUIT_DIR / "state.json"

PROMPT_TOKENS = 9000          # a little over the prompt, for the cost estimate
THINK_TOKENS = 2500           # room for thinking before the proposals
TOKENS_PER_PROPOSAL = 1500
CHEAP_ROUND = 0.04            # a 2-proposal round at or under this many dollars: 4 proposals a day
NORMAL_ROUND = 0.12           # at or under this: 2 a day. Above it: 1 a day
RATING_STEPS = (10, 25, 50, 100, 200, 350, 600, 1000, 1500)   # muse score needed for rating 2, 3, ... 10


def _num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def enabled() -> bool:
    return os.getenv("HQ_RECRUITER", "true").strip().lower() not in ("false", "0", "no", "off")


def monthly_budget() -> float:
    return max(0.0, _num("HQ_RECRUITER_MONTHLY_BUDGET", 3))


def max_waiting() -> int:
    """Proposals waiting for Steven's answer before Recruiter stops adding more."""
    return int(min(20, max(1, _num("HQ_RECRUITER_MAX_WAITING", 6))))


def min_rating() -> int:
    """Proposals rated below this never reach Steven's Approvals."""
    return int(min(10, max(1, _num("HQ_RECRUITER_MIN_RATING", 3))))


def effort() -> str:
    e = os.getenv("HQ_RECRUITER_EFFORT", "medium").strip().lower()
    return e if e in ("low", "medium", "high") else "medium"


def max_tokens(n: int) -> int:
    return THINK_TOKENS + TOKENS_PER_PROPOSAL * n


def round_cost_estimate(n: int = 2) -> float:
    """The most a round for n proposals can cost on Recruiter's model."""
    price_in, price_out = PRICES.get(model_for("recruiter"), UNKNOWN_PRICE)
    return round((PROMPT_TOKENS * price_in + max_tokens(n) * price_out) / 1_000_000, 3)


def per_day() -> int:
    """Proposals a day. Cheap to run: 4. Normal: 2. Expensive: 1. HQ_RECRUITER_PER_DAY (1 to 6) overrides."""
    forced = _num("HQ_RECRUITER_PER_DAY", 0)
    if forced >= 1:
        return int(min(6, forced))
    cost = round_cost_estimate(2)
    return 4 if cost <= CHEAP_ROUND else 2 if cost <= NORMAL_ROUND else 1


# ---- rating ----------------------------------------------------------------------------------------------

def rating(i: dict) -> int:
    """1 to 10, from the same honest arithmetic Muse ranks by: expected first-year profit per hour of work, which
    already weighs what the new agent earns or saves against what it costs to run and to build. Low confidence caps
    it at 6, so a long shot never looks like a sure thing."""
    s = muse.score(i)
    if s <= 0:
        return 1
    r = 1 + sum(s >= step for step in RATING_STEPS)
    return int(min(r, 6 if i["confidence"] < 0.25 else 10))


# ---- state and guards ------------------------------------------------------------------------------------

def _state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(s: dict):
    RECRUIT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _today() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _midnight_utc() -> str:
    return datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0) \
        .astimezone(timezone.utc).isoformat(timespec="seconds")


def made_today() -> int:
    return db.rows("SELECT COUNT(*) n FROM ideas WHERE source = 'recruiter' AND created_at >= ?", _midnight_utc())[0]["n"]


def waiting() -> int:
    return db.rows("SELECT COUNT(*) n FROM ideas WHERE source = 'recruiter' AND status = 'proposed'")[0]["n"]


def spent_this_month() -> float:
    return db.rows("SELECT COALESCE(SUM(cost_usd), 0) c FROM llm_usage WHERE LOWER(agent) = 'recruiter' "
                   "AND created_at >= ?", muse._month_start())[0]["c"]


def money_blocker(n: int) -> str | None:
    est = round_cost_estimate(n)
    cap = monthly_budget()
    if cap <= 0:
        return "Recruiter's monthly budget (HQ_RECRUITER_MONTHLY_BUDGET) is 0, so Recruiter is switched off."
    if spent_this_month() + est > cap:
        return (f"Recruiter has used ${spent_this_month():.2f} of its ${cap:.2f} for this month, and a round can cost up "
                f"to ${est:.2f}. It starts again next month, or raise HQ_RECRUITER_MONTHLY_BUDGET in Settings.")
    if DAILY_BUDGET > 0 and ledger.spent_today("business") + est > DAILY_BUDGET:
        return "Today's Claude budget (HQ_DAILY_BUDGET) is nearly spent. Recruiter will try again tomorrow."
    return None


def wanted(manual: bool) -> int:
    """How many proposals to ask for: what is left of today's allowance (a button press asks for a full day's worth),
    and never more than there is room for in the waiting list."""
    room = max_waiting() - waiting()
    left = per_day() if manual else per_day() - made_today()
    return max(0, min(left, room))


def why_not_now(manual: bool = False) -> str | None:
    """The free look before a round. None means go ahead."""
    if not llm.HAS_LLM:
        return "Recruiter needs the Anthropic API key (Settings) to find gaps."
    if not enabled() and not manual:
        return "Recruiter is switched off (HQ_RECRUITER=false). Recruit now still works."
    if waiting() >= max_waiting():
        return (f"{waiting()} proposals are still waiting for your answer on the Ideas tab, so Recruiter waits until "
                "you've answered some.")
    if not manual:
        if _state().get("last_day") == _today():
            return "Recruiter already looked today. It looks again tomorrow."
        if made_today() >= per_day():
            return "Recruiter has made today's proposals. It looks again tomorrow."
    n = wanted(manual)
    if n < 1:
        return "No room for new proposals right now."
    return money_blocker(n)


# ---- what Recruiter reads (all free) ---------------------------------------------------------------------

def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def facts() -> dict:
    """The holes in HQ's operations, as far as HQ can see them without spending anything."""
    base = _safe(muse.facts, {}) or {}
    sweep_report = _safe(lambda: __import__("hq.sweep", fromlist=["x"]).latest().get("report") or {}, {}) or {}
    improve = sweep_report.get("improve") or {}
    tips = [{"area": t.get("area"), "severity": t.get("severity"), "title": t.get("title"), "why": t.get("why")}
            for t in (improve.get("tips") or [])[:10]]
    problems = [str(p.get("message") if isinstance(p, dict) else p)[:160] for p in (sweep_report.get("problems") or [])[:8]]
    failed = {r["agent"]: r["n"] for r in db.rows(
        "SELECT agent, COUNT(*) n FROM tasks WHERE status = 'failed' AND created_at >= ? GROUP BY agent", _ago(14))}
    busy = {r["agent"]: r["n"] for r in db.rows(
        "SELECT agent, COUNT(*) n FROM tasks WHERE created_at >= ? GROUP BY agent", _ago(14))}
    quiet = [a["name"] for a in base.get("team", []) if not busy.get(a["name"])]
    # What Muse thinks is missing: its agent ideas still waiting, parked, or approved and not built yet.
    muse_gaps = [{"title": r["title"], "name": r["name"], "status": r["status"], "pitch": (r["pitch"] or "")[:160]}
                 for r in db.rows("SELECT title, name, status, pitch FROM ideas WHERE COALESCE(source, 'muse') = 'muse' "
                                  "AND kind = 'agent' AND status IN ('proposed', 'parked', 'approved') "
                                  "ORDER BY score DESC LIMIT 8")]
    return {
        **{k: base.get(k) for k in ("team", "money", "claude_cost_this_month_by_agent", "views", "campaigns",
                                    "leads_by_status", "waiting_in_approvals")},
        "sweep_health_score": improve.get("score"),
        "sweep_tips": tips,
        "sweep_problems": problems,
        "failed_tasks_14d_by_agent": failed,
        "agents_with_no_work_14d": quiet,
        "muse_missing_agents": muse_gaps,
        "agents_in_hq": len(base.get("team", [])),
    }


def _decisions_text() -> str:
    rows = db.rows("SELECT title, status, reason FROM ideas WHERE source = 'recruiter' AND status != 'proposed' "
                   "ORDER BY decided_at DESC LIMIT 20")
    if not rows:
        return "Steven hasn't answered any of Recruiter's proposals yet."
    say = {"approved": "said BUILD IT", "built": "built it", "parked": "said LATER", "rejected": "said NO"}
    return "\n".join(f"- {r['title']}: {say.get(r['status'], r['status'])}" + (f", because: {r['reason']}" if r["reason"] else "")
                     for r in rows)


SYSTEM = """You are Recruiter, the hiring manager of Agent HQ: Steven's team of AI agents that runs parts of his online
business from his own Windows PC. Your one job is to find holes in how HQ runs today and propose NEW AGENTS that fill
them, so HQ makes more money, earns from more places, and runs smoother and cheaper.

The goal behind everything: make as much money as possible, diversify Steven's income, and help his current
endeavors (clipping streamers, and his college football job). Steven is a beginner with code and has a few spare
hours a week. Claude builds what he picks. He approves everything. Never use his school's name, logo or game film,
and never sell anything to high school recruits.

How to find a hole:
- Sweep's tips, problems and the failed tasks show where work breaks, repeats, wastes money or waits on Steven.
- Muse's missing-agent ideas show what Muse thinks HQ lacks. Turn the best of them into a proposal, but only when a
  real gap in the numbers backs them. Do not just copy Muse.
- Agents with no work show where a role is idle or a step has no owner.
- Look at the money: where does the path from work to income break or have no agent at all?

What a good proposal is:
- ONE new agent with a short friendly name, a clear job, and the single gap it fixes (say what is broken or missing
  today, with a fact from the numbers).
- It must not overlap an agent HQ already has or anything on the no-repeat list. If it overlaps one, put that title
  in "repeats" and it is dropped. Extending an agent HQ has is not a new agent: skip it.
- Cheap to run: say honestly what it costs each month (Claude, subscriptions), and prefer agents that run on rules in
  code with little or no Claude use.
- Specific enough to build this week, with concrete first steps.
- It keeps HQ's rules: nothing posts, sends, publishes or spends without Steven's tap; official APIs only; no
  scraping sites whose terms forbid it; no spam, fake engagement, real-money betting or trading, or reposting anyone's
  content without permission.
- Learn from Steven's past answers: more like what he approved, nothing like what he turned down.

Numbers, per proposal:
- profit_low_usd_month / profit_high_usd_month: money in per month after fees, 3 to 6 months after it starts. For an
  agent that saves time or cost instead, count each hour a month saved as $15 and each dollar of waste cut as $1, and
  say so in the pitch. Be honest: a range can start at $0.
- monthly_cost_usd: what the agent costs to keep running. start_cost_usd: one-off costs.
- effort: how much Claude has to build (small = one pull request, medium = two or three, large = a project).
- effort_hours: Steven's own hours in the first month.
- confidence: how likely the range is, 0 to 1. Not how much you like it.

Write for Steven: short, plain sentences, no hype, no jargon. Titles under 8 words. A pitch under 60 words, steps
under 15 words each, one sentence each for why_now, steven_does, risks and gap."""

_PROPS = {k: v for k, v in muse.ITEM["properties"].items() if k != "kind"}
_PROPS["name"] = {"type": "string", "description": "A short friendly agent name, one word"}
_PROPS["gap"] = {"type": "string", "description": "One sentence: the hole in HQ today this agent fills, with a fact"}
ITEM = {"type": "object", "properties": _PROPS, "required": list(_PROPS), "additionalProperties": False}
SCHEMA = {"type": "object", "properties": {"ideas": {"type": "array", "items": ITEM}},
          "required": ["ideas"], "additionalProperties": False}


def prompt(n: int) -> str:
    known = "\n".join(f"- {t} [{s}]" for t, s in muse.KNOWN)
    past = "\n".join(f"- {p['title']}" + (f" ({p['name']})" if p["name"] else "") + f" [{p['status']}]"
                     for p in muse._past_ideas()) or "- none yet"
    return f"""Today is {datetime.now():%A %d %B %Y}.

STEVEN'S VISION FILE
{muse._vision()}

HQ TODAY (live numbers, Sweep's findings and what Muse says is missing)
{json.dumps(facts(), separators=(",", ":"), default=str)}

ALREADY BUILT, SHOWN, PARKED OR TURNED DOWN (never propose these again)
{known}

EVERY IDEA OR PROPOSAL SO FAR (never repeat)
{past}

STEVEN'S ANSWERS TO RECRUITER SO FAR
{_decisions_text()}

YOUR TASK
Propose exactly {n} new agent(s), each fixing a different gap. Make each one earn or save more than it costs."""


# ---- the round -------------------------------------------------------------------------------------------

def sift(raw_ideas: list[dict]) -> tuple[list[dict], list[str]]:
    """Clean every proposal as a new agent, rate it, then drop repeats, rule breakers and weak ones."""
    gaps = {}
    for raw in raw_ideas:
        raw["kind"] = "agent"
        gaps[" ".join(str(raw.get("title") or "").split())[:80]] = str(raw.get("gap") or "").strip()[:400]
    kept, dropped = muse.sift(raw_ideas)
    out = []
    for i in kept:
        if not i["name"]:
            dropped.append(f"\"{i['title']}\" (no agent name)")
            continue
        i["gap"] = gaps.get(i["title"], "")
        i["rating"] = rating(i)
        if i["rating"] < min_rating():
            dropped.append(f"\"{i['title']}\" (rated {i['rating']}/10, under your {min_rating()}/10 bar)")
            continue
        out.append(i)
    return out, dropped


def card_text(i: dict) -> str:
    return f"Rating {i['rating']}/10 · gap: {i['gap']}\n" + muse.card_text({**i, "kind": "agent"}).split("\n", 1)[1]


def run(manual: bool = False) -> str:
    blocked = why_not_now(manual)
    if blocked:
        return ("Skipped: " if not manual else "") + blocked
    n = wanted(manual)
    state = _state()
    state["last_day"] = _today()   # saved before the call: a failing round must not be retried every hour
    _save_state(state)
    response = llm.create(model_for("recruiter"), SYSTEM, [{"role": "user", "content": prompt(n)}], effort=effort(),
                          max_tokens=max_tokens(n), output_schema=SCHEMA, agent="Recruiter")
    return _file(llm.text_of(response), n, getattr(response, "stop_reason", None))


def _file(text: str, n: int, stop_reason: str | None = None) -> str:
    try:
        data = json.loads(text or "{}")
    except ValueError:
        out = ("Claude's answer was cut off before the proposals were complete" if stop_reason == "max_tokens"
               else "Claude's answer couldn't be read") + ", so this round added nothing."
        db.log("Recruiter", out)
        return out
    kept, dropped = sift((data.get("ideas") or [])[:n + 2])
    kept = sorted(kept, key=lambda i: (-i["rating"], -muse.score(i)))[:n]
    for i in kept:
        i["id"] = muse.save(i, None)
        db.execute("UPDATE ideas SET source = 'recruiter', rating = ?, gap = ? WHERE id = ?", i["rating"], i["gap"], i["id"])
        aid = approvals.request("Recruiter", "recruit_idea", f"🧲 {i['title']} ({i['rating']}/10)", card_text(i),
                                {"idea_id": i["id"]}, yes="👍 Build it", no="👎 Not for me")
        db.execute("UPDATE ideas SET approval_id = ? WHERE id = ?", aid, i["id"])
    state = _state()
    state["last_round"] = {"at": db.now(), "kept": len(kept), "dropped": dropped}
    _save_state(state)
    if kept:
        best = kept[0]
        out = (f"{len(kept)} proposal(s) sent to Approvals. Best: \"{best['title']}\" ({best['rating']}/10), "
               f"fixes: {best['gap']}")
    else:
        out = "No proposals this round: each one repeated something, broke a rule or rated too low."
    if dropped:
        out += f" Dropped {len(dropped)}: " + "; ".join(dropped)
    db.log("Recruiter", out[:600])
    return out


approvals.HANDLERS["recruit_idea"] = muse._decide_card


# ---- for the dashboard -----------------------------------------------------------------------------------

def _next_text() -> str:
    reason = why_not_now()
    return "Recruiter looks for gaps at its next hourly check." if reason is None else reason


def latest() -> dict:
    state = _state()
    running = bool(db.rows("SELECT 1 FROM tasks WHERE agent = 'Recruiter' AND status IN ('queued', 'running') LIMIT 1"))
    return {
        "enabled": enabled(),
        "running": running,
        "next": _next_text(),
        "per_day": per_day(),
        "made_today": made_today(),
        "waiting": waiting(),
        "max_waiting": max_waiting(),
        "min_rating": min_rating(),
        "round_cost": round_cost_estimate(per_day()),
        "spent_month": round(spent_this_month(), 2),
        "monthly_budget": monthly_budget(),
        "model": model_for("recruiter"),
        "has_llm": llm.HAS_LLM,
        "last_round": state.get("last_round"),
        "how": "Recruiter rates each proposed agent 1 to 10 from what it should earn or save, minus what it costs to run "
               "and build, per hour of work. Cheap-to-run Recruiter makes up to 4 a day, normal 2, expensive 1.",
    }
