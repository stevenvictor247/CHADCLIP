"""Sweep's quality control: one look a day across every agent for what would make HQ better run.

Each check reads the database (and a few files) and returns "tips": what Sweep noticed, why it matters, the one step
to take, and where to take it. Nothing here changes anything, except the one-tap fixes at the bottom, and those only
run when Steven presses the button. Every fix is small and safe: none of them posts, emails, spends money or changes a
setting. Anything like that still goes through the Approvals queue.

A tip looks like:
    {"id": "stale_approvals", "area": "organization", "severity": "medium", "title": "...", "why": "...",
     "do": "...", "link": {"label": "Open Approvals", "href": "/#approvals"}, "fix": {"id": "...", "label": "..."}}
"""

import json
import os
import re
import traceback
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db, ledger
from .config import DAILY_BUDGET, FOOTBALL_DAILY_BUDGET

AREAS = {"organization": "Organization", "efficiency": "Efficiency", "quality": "Quality", "money": "Money"}
WEIGHT = {"high": 12, "medium": 6, "low": 2}          # points off the 100-point health score
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
AREA_ORDER = {"money": 0, "quality": 1, "organization": 2, "efficiency": 3}   # within a severity: what earns first

STALE_APPROVAL_HOURS = 48
STALE_CLIP_HOURS = 24
QUEUE_LATE_HOURS = 2
BOSS_CHAT_LONG_TOKENS = 40_000     # a chat this long is worth restarting; Sweep closes it by itself at 120k when idle
REPEAT_MESSAGES = 3                # the same Boss prompt this many times in a day is a loop, not Steven
REPEAT_TASKS = 4                   # the same job asked for this many times in a day (not by the schedule)
ROUTINE_OK = ("No follow-ups due", "No new posted clips need submitting", "Every waiting pitch already has an email",
              "No posted clips to count yet")   # results of free checks that are fine to come back empty
EMPTY_RUNS = 3                     # this many empty rounds in a row from one scheduled job
REJECT_RATE = 0.4                  # share of Chad's decided clips that were rejected
SET_ASIDE_NOTE = "Sweep: video file missing, set aside."


# ---- small helpers ---------------------------------------------------------------------------------------

def _ago(**kw) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat(timespec="seconds")


def _hours_since(ts: str) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 3600
    except (TypeError, ValueError):
        return 0.0


def _usd(x: float) -> str:
    return f"${x:,.2f}" if x >= 0.01 or x == 0 else f"${x:,.3f}"


def _plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def _tip(id_: str, area: str, severity: str, title: str, why: str, do: str,
         link: tuple[str, str] | None = None, fix: tuple[str, str] | None = None) -> dict:
    do = do.strip()
    if do and do[-1] not in ".!?":
        do += "."
    return {"id": id_, "area": area, "severity": severity, "title": title, "why": why, "do": do,
            "link": {"label": link[0], "href": link[1]} if link else None,
            "fix": {"id": fix[0], "label": fix[1]} if fix else None}


def _spend(since: str, agent: str | None = None) -> float:
    sql, args = "SELECT COALESCE(SUM(cost_usd), 0) usd FROM llm_usage WHERE created_at >= ?", [since]
    if agent:
        sql += " AND agent = ?"
        args.append(agent)
    return db.rows(sql, *args)[0]["usd"] or 0.0


def _text_of(content: str) -> str:
    """The words of a Boss chat message (its content is a JSON list of blocks)."""
    try:
        blocks = json.loads(content)
    except ValueError:
        return content or ""
    if isinstance(blocks, str):
        return blocks
    return " ".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text").strip()


def _pending_clips() -> list[dict]:
    return db.rows("SELECT * FROM clips WHERE status = 'pending_approval' ORDER BY id")


def _broken_clip_ids() -> list[int]:
    """Clips waiting for approval whose video file is gone: they can never be posted."""
    return [c["id"] for c in _pending_clips() if c.get("path") and not Path(c["path"]).exists()]


def _queue_duplicates() -> list[tuple[int, int]]:
    """(duplicate task id, the earlier one it repeats) for jobs queued twice with the same agent, words and params."""
    seen, dupes = {}, []
    for t in db.rows("SELECT id, agent, instructions, params FROM tasks WHERE status = 'queued' ORDER BY id"):
        key = (t["agent"].lower(), t["instructions"].strip().lower(), t["params"] or "{}")
        if key in seen:
            dupes.append((t["id"], seen[key]))
        else:
            seen[key] = t["id"]
    return dupes


def _boss_chat_tokens() -> int:
    from . import boss
    return boss.chat_tokens()


def _pitch_cards_without_email() -> tuple[list[dict], list[dict]]:
    """Pitch cards waiting in Approvals that can't be sent from HQ: (no address found, address but no Gmail set up)."""
    from .agents.pitch import mailer
    no_address, no_mailer = [], []
    for a in db.rows("SELECT id, title, payload FROM approvals WHERE status = 'pending' AND kind = 'pitch'"):
        payload = json.loads(a["payload"] or "{}")
        if payload.get("email"):
            continue
        lead = db.rows("SELECT name, contact FROM leads WHERE id = ?", payload.get("lead_id"))
        if lead and mailer.address_in(lead[0]["contact"]):
            if not mailer.configured():
                no_mailer.append({**a, "name": lead[0]["name"]})
        else:
            no_address.append({**a, "name": lead[0]["name"] if lead else a["title"]})
    return no_address, no_mailer


def _recheck_waiting() -> bool:
    return bool(db.rows("SELECT 1 FROM tasks WHERE agent = 'Pitch' AND status IN ('queued', 'running') "
                        "AND params LIKE '%\"recheck\": true%' LIMIT 1"))


# ---- the checks ------------------------------------------------------------------------------------------
# Each one returns a list of tips. They only read.

def check_setup() -> list[dict]:
    """The first setup step still blocking the money chain (clip → approve → post → get paid)."""
    from . import setup_check
    s = setup_check.summary()
    needed = [i for i in s["items"] if i.get("required", True) and i["status"] != "done"]
    if not needed:
        return []
    first = needed[0]
    more = f" ({_plural(len(needed) - 1, 'other required step')} after it.)" if len(needed) > 1 else ""
    return [_tip(f"setup_{first['id']}", "organization", "high" if first["status"] == "problem" else "medium",
                 f"Setup step holding HQ back: {first['title']}", first["detail"] + more,
                 first.get("fix") or "Finish it on the Home tab's setup checklist.",
                 ("Open it", first["link"]) if first.get("link") else ("Open the checklist", "/#home"))]


def check_approvals() -> list[dict]:
    rows = db.rows("SELECT kind, created_at FROM approvals WHERE status = 'pending' AND created_at < ?",
                   _ago(hours=STALE_APPROVAL_HOURS))
    if not rows:
        return []
    kinds = Counter(r["kind"] for r in rows)
    oldest = max(_hours_since(r["created_at"]) for r in rows)
    what = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in kinds.most_common(4))
    return [_tip("stale_approvals", "organization", "high" if len(rows) >= 10 else "medium",
                 f"{_plural(len(rows), 'card has', 'cards have')} waited in Approvals over {STALE_APPROVAL_HOURS // 24} days",
                 f"{what}. The oldest is {oldest / 24:.0f} days old. Old cards bury the new ones, and a pitch "
                 "goes stale while it waits.",
                 "Go through them in one sitting: approve what you still want and press Drop or Reject on the rest.",
                 ("Open Approvals", "/#approvals"))]


def check_waiting_clips() -> list[dict]:
    from . import review
    pending = _pending_clips()
    if not pending:
        return []
    tips = []
    broken = _broken_clip_ids()
    old = [c for c in pending if _hours_since(c["created_at"]) > STALE_CLIP_HOURS and c["id"] not in broken]
    if old or len(pending) - len(broken) >= 15:
        n = len(pending) - len(broken)
        waited = (f"{'All' if len(old) == n else len(old)} of them for over a day. " if old else "")
        tips.append(_tip("clips_waiting", "organization", "high" if n >= 15 else "medium",
                         f"{_plural(n, 'clip is', 'clips are')} waiting for your yes or no",
                         f"{waited}Clips lose their moment fast: a funny stream moment is worth most in its first "
                         "day or two.",
                         "Approve or reject them in one go. Rejecting teaches Chad your taste, so don't skip the no's.",
                         ("Open Approvals", "/#approvals")))
    cfg = review._chad_settings()
    issues = Counter()
    flagged = 0
    for c in pending:
        if c["id"] in broken:
            continue   # they get their own tip below
        found = review.clip_issues(c, cfg)
        flagged += bool(found)
        issues.update(i.split(":")[0].split(" (")[0] for i in found)
    checked = len(pending) - len(broken)
    if broken:
        tips.append(_tip("broken_clips", "quality", "medium",
                         f"{_plural(len(broken), 'waiting clip has', 'waiting clips have')} no video file any more",
                         "Their files were moved or deleted, so they can never be posted, but they still sit in your "
                         "approval list.", "Set them aside. They leave your approval list without counting as "
                         "rejections, so Chad's sense of your taste isn't thrown off.",
                         ("Open Approvals", "/#approvals"), ("set_aside_broken", f"Set aside {_plural(len(broken), 'clip')}")))
    if flagged >= 2:
        top = "; ".join(f"{k} ({n})" for k, n in issues.most_common(3))
        tips.append(_tip("flagged_clips", "quality", "low",
                         (f"All {flagged} waiting clips have a problem" if flagged == checked
                          else f"{flagged} of the {checked} waiting clips have a problem"),
                         f"Most common: {top}. The problem is written on each clip's card.",
                         "Reject the flagged ones first; the rest are quicker to judge after that.",
                         ("Open Approvals", "/#approvals")))
    return tips


def check_clip_quality() -> list[dict]:
    """How many of Chad's clips Steven turns down, and whether one streamer is the cause."""
    rows = db.rows("SELECT creator, status FROM clips WHERE created_at >= ? AND status != 'pending_approval' "
                   "AND COALESCE(boss_note, '') NOT LIKE ?", _ago(days=7), f"%{SET_ASIDE_NOTE}%")
    if len(rows) < 5:
        return []
    rejected = [r for r in rows if r["status"] == "rejected"]
    rate = len(rejected) / len(rows)
    tips = []
    by_creator = Counter((r["creator"] or "unknown") for r in rows)
    bad_creator = [(c, sum(1 for r in rejected if (r["creator"] or "unknown") == c), n)
                   for c, n in by_creator.items()]
    bad_creator = [(c, k, n) for c, k, n in bad_creator if k >= 3 and k / n >= 0.6]
    if rate >= REJECT_RATE:
        wasted = _spend(_ago(days=7), "Chad") * rate   # rough: Chad's week of Claude, in proportion
        tips.append(_tip("reject_rate", "quality", "medium",
                         f"You rejected {rate:.0%} of Chad's clips this week",
                         f"{len(rejected)} of {len(rows)} decided clips. That's roughly {_usd(wasted)} of Chad's "
                         "Claude spend on clips nobody will see.",
                         "Tell the Boss in one sentence what you keep rejecting (too long, no punchline, wrong streamer). "
                         "Chad reads your approvals and rejections each time he picks moments.",
                         ("Talk to the Boss", "/#boss")))
    for creator, k, n in sorted(bad_creator, key=lambda x: -x[1])[:2]:
        tips.append(_tip(f"reject_creator_{re.sub(r'[^a-z0-9]+', '_', creator.lower())}", "quality", "low",
                         f"Most clips of {creator} get rejected",
                         f"You turned down {k} of {n} this week.",
                         f"Tell the Boss what's wrong with {creator}'s clips so Chad picks better ones. If they're "
                         f"never worth it, stop clipping {creator}: ask Claude in the project to take them off Chad's "
                         "list (the Clips tab can add streamers but not remove them yet).", ("Talk to the Boss", "/#boss")))
    return tips


def check_posting() -> list[dict]:
    from .agents.chad.publish import load_accounts
    tips = []
    fails = db.rows("SELECT platform, account, error FROM posts WHERE status = 'failed' AND created_at >= ?",
                    _ago(days=7))
    grouped: dict[tuple, list[str]] = {}
    for f in fails:
        grouped.setdefault((f["platform"], f["account"]), []).append((f["error"] or "no error given")[:160])
    for (platform, account), errors in grouped.items():
        if len(errors) < 2:
            continue
        common, n = Counter(errors).most_common(1)[0]
        tips.append(_tip(f"post_fail_{platform}_{re.sub(r'[^a-z0-9]+', '_', account.lower())}", "quality", "high",
                         f"Posting to {platform} ({account}) failed {len(errors)} times this week",
                         f"Most often: \"{common}\". Failed posts are never retried on their own, so these clips are "
                         "stuck until you act.",
                         "Press Test next to the account in Settings. When it passes, press Try posting again on the "
                         "failed clips (Clips tab, Failed).", ("Open Settings", "/settings#accounts")))
    try:
        real = [a for a in load_accounts() if a.get("enabled") and a["platform"] != "practice"]
    except Exception:
        real = []
    approved = db.rows("SELECT COUNT(*) n FROM clips WHERE status = 'approved'")[0]["n"]
    cap = 0
    try:
        cap = int(float(os.getenv("HQ_MAX_POSTS_PER_DAY", "") or 4))
    except ValueError:
        cap = 4
    if real and cap > 0 and approved > cap * 2:
        tips.append(_tip("post_backlog", "efficiency", "medium" if approved > cap * 4 else "low",
                         f"{approved} approved clips are queued to post: about {approved / cap:.0f} days at {cap} a day",
                         "The posting limit protects new accounts from looking like spam, so the queue drains slowly. "
                         "By the time the last ones post, their moment has passed.",
                         "Approve only your best few each day. Once the accounts are a few weeks old, raise "
                         "HQ_MAX_POSTS_PER_DAY by one at a time.", ("Open Clips", "/#clips")))
    return tips


def check_pitch() -> list[dict]:
    tips = []
    no_address, no_mailer = _pitch_cards_without_email()
    if no_address:
        names = ", ".join(a["name"] for a in no_address[:4]) + ("…" if len(no_address) > 4 else "")
        busy = _recheck_waiting()
        tips.append(_tip("pitch_no_email", "quality", "medium",
                         f"{_plural(len(no_address), 'Pitch card has', 'Pitch cards have')} no email to send to",
                         f"{names}. Without an address you'd have to message them by hand.",
                         "Let Pitch look for their emails again. Any it still can't find, reach on Twitch, X or "
                         "Instagram, or press Drop.", ("Open Approvals", "/#approvals"),
                         None if busy else ("pitch_recheck", "Look for emails again")))
    if no_mailer:
        tips.append(_tip("pitch_no_mailer", "organization", "medium",
                         f"{_plural(len(no_mailer), 'pitch has', 'pitches have')} an email but HQ can't send it",
                         "Gmail sending isn't set up, so Send email turns into \"I'll send it\" and you copy each one by hand.",
                         "Add PITCH_EMAIL_ADDRESS and a Google app password in Settings, Pitch section.",
                         ("Open Settings", "/settings")))
    stuck = db.rows("SELECT name FROM leads WHERE status = 'sending' AND updated_at < ?", _ago(hours=1))
    if stuck:
        tips.append(_tip("pitch_stuck_sending", "quality", "high",
                         f"{_plural(len(stuck), 'pitch is', 'pitches are')} stuck half-sent",
                         ", ".join(s["name"] for s in stuck[:4]) + ". HQ was probably closed while it was emailing.",
                         "Look in your Gmail Sent folder. If it went, tell the Boss \"mark that lead pitched\"; if it "
                         "didn't, tell the Boss \"mark that lead drafted\" so you can send it again.", ("Talk to the Boss", "/#boss")))
    return tips


def check_tasks() -> list[dict]:
    tips = []
    # agents that fail a lot this week
    rows = db.rows("SELECT agent, status, result FROM tasks WHERE updated_at >= ? AND status IN ('done', 'failed') "
                   "AND created_by != 'Sweep' AND COALESCE(result, '') NOT LIKE 'Sweep: cancelled%'", _ago(days=7))
    by_agent: dict[str, list[dict]] = {}
    for r in rows:
        by_agent.setdefault(r["agent"], []).append(r)
    for agent, ts in sorted(by_agent.items()):
        failed = [t for t in ts if t["status"] == "failed"]
        if len(ts) >= 5 and len(failed) / len(ts) >= 0.3:
            common = Counter((t["result"] or "no error given")[:140] for t in failed).most_common(1)[0][0]
            tips.append(_tip(f"fail_rate_{agent.lower()}", "efficiency", "medium",
                             f"{agent} failed {len(failed)} of {len(ts)} jobs this week",
                             f"Most often: \"{common}\". Each failed job still costs time and sometimes Claude money.",
                             f"Ask the Boss \"why does {agent} keep failing?\" and send it that error. If it's a key or "
                             "login, press Test in Settings.", ("Talk to the Boss", "/#boss")))
    # scheduled jobs that keep coming back empty
    done = db.rows("SELECT agent, instructions, result FROM tasks WHERE status = 'done' AND created_by = 'Schedule' "
                   "AND updated_at >= ? ORDER BY id DESC", _ago(days=3))
    streaks: dict[tuple, int] = {}
    ended = set()
    for t in done:       # newest first: count the empty rounds since the last useful one
        key = (t["agent"], t["instructions"])
        if key in ended:
            continue
        if (t["result"] or "").startswith(ROUTINE_OK):
            continue     # a routine "nothing due" check is working as intended, not waste (it is free in code now)
        if re.match(r"(Made 0 clips|No |None |Nothing |Skipped)", t["result"] or ""):
            streaks[key] = streaks.get(key, 0) + 1
        else:
            ended.add(key)
    for (agent, instructions), n in streaks.items():
        if n >= EMPTY_RUNS:
            last = next(t["result"] for t in done if t["agent"] == agent and t["instructions"] == instructions)
            do, link = EMPTY_ADVICE.get(agent.lower(), (f"Ask the Boss why {agent} keeps finding nothing.",
                                                         ("Talk to the Boss", "/#boss")))
            tips.append(_tip(f"empty_{agent.lower()}", "efficiency", "low",
                             f"{agent}'s last {n} scheduled rounds found nothing",
                             f"\"{instructions}\" keeps ending with: \"{last[:140]}\"", do, link))
    # duplicate jobs sitting in the queue
    dupes = _queue_duplicates()
    if dupes:
        tips.append(_tip("queue_duplicates", "efficiency", "medium",
                         f"{_plural(len(dupes), 'job is', 'jobs are')} in the queue twice",
                         "The same agent was asked for the same thing more than once before it got to it. Running "
                         "both pays twice for one result.", "Cancel the copies (the first of each stays queued).",
                         None, ("cancel_duplicates", f"Cancel {_plural(len(dupes), 'copy', 'copies')}")))
    # the same job asked for again and again (not the schedule)
    rep = db.rows("SELECT agent, instructions, COUNT(*) n FROM tasks WHERE created_at >= ? AND created_by NOT IN "
                  "('Schedule', 'Sweep') GROUP BY agent, instructions HAVING n >= ? ORDER BY n DESC",
                  _ago(hours=24), REPEAT_TASKS)
    for r in rep[:2]:
        tips.append(_tip(f"task_repeat_{r['agent'].lower()}", "efficiency", "medium",
                         f"{r['agent']} was asked to do the same job {r['n']} times today",
                         f"\"{r['instructions'][:120]}\"",
                         "If that was you, the first run's result is on the Activity tab. If not, the Boss may be "
                         "looping: start a fresh Boss chat and tell it to check before asking again.",
                         ("Open Activity", "/#activity")))
    # jobs waiting much longer than they should
    tips += _late_queue()
    return tips


EMPTY_ADVICE = {  # agent -> (what to do, where) when its scheduled rounds keep finding nothing
    "chad": ("Add more streamers in the \"Streamers Chad can clip\" box on the Clips tab, or press \"Clip the top "
             "streamers now\" there.", ("Open Clips", "/#clips")),
    "pitch": ("Widen the viewer range (Smallest and Biggest streamer) in Settings, Pitch section.", ("Open Settings", "/settings")),
    "scout": ("Paste campaign links into the Boss chat so Scout has something to rate.", ("Talk to the Boss", "/#boss")),
}


def _late_queue() -> list[dict]:
    """Jobs waiting much longer than they should. Chad's video lane runs one long job at a time, so Chad jobs queued
    behind a running clipping job are normal; anything else waiting hours means the agents stopped or are stuck."""
    from . import worker
    from .agents.chad.publish import paused
    queued = db.rows("SELECT agent, created_at FROM tasks WHERE status = 'queued'")
    late = [q for q in queued if _hours_since(q["created_at"]) > QUEUE_LATE_HOURS]
    if not late:
        return []
    if paused():
        return [_tip("paused", "organization", "medium", "HQ is paused",
                     f"{_plural(len(queued), 'job is', 'jobs are')} waiting and nothing posts until you resume.",
                     "Press Resume at the top of HQ (or send \"resume\" in Telegram) when you're ready.",
                     ("Open Home", "/#home"))]
    quiet = worker.seconds_since_last_round()
    video_busy = db.rows("SELECT 1 FROM tasks WHERE status = 'running' AND LOWER(agent) IN ({}) LIMIT 1".format(
        ", ".join("?" for _ in worker.SLOW_AGENTS)), *worker.SLOW_AGENTS)
    if video_busy and (quiet is None or quiet < 20 * 60):
        late = [q for q in late if q["agent"].lower() not in worker.SLOW_AGENTS]
        if not late:
            return []
    oldest = max(_hours_since(q["created_at"]) for q in late)
    stopped = quiet is not None and quiet > 20 * 60
    return [_tip("queue_late", "efficiency", "high",
                 f"{_plural(len(late), 'job has', 'jobs have')} been waiting over {QUEUE_LATE_HOURS} hours",
                 f"The oldest was queued {oldest:.0f} hours ago. " +
                 (f"The agents haven't done a round for {quiet / 60:.0f} minutes, so they've stopped." if stopped else
                  "The agents are running, so one job is probably stuck and holding up the rest."),
                 ("Close HQ and open it again. The waiting jobs start on their own." if stopped else
                  "Check the Activity tab for a job that started but never finished. Sweep puts a stuck job back "
                  "in the queue after an hour; if it keeps happening, close HQ and open it again."),
                 ("Open Activity", "/#activity"))]


def check_boss() -> list[dict]:
    tips = []
    msgs = db.rows("SELECT content FROM boss_messages WHERE role = 'user' AND created_at >= ?", _ago(hours=24))
    texts = Counter(t for t in (_text_of(m["content"]) for m in msgs) if t)
    for text, n in texts.most_common(1):
        if n < REPEAT_MESSAGES:
            break
        tips.append(_tip("boss_repeats", "efficiency", "high",
                         f"The same message went to the Boss {n} times today",
                         f"\"{text[:100]}\". Each copy re-sends the whole Boss chat to Claude. This is how the "
                         "repeating daily report looked before it was fixed.",
                         "If you didn't send these, something is looping. Start a fresh Boss chat now and tell "
                         "Claude in the project which message keeps repeating.", ("Open the Boss", "/#boss"),
                         ("fresh_boss_chat", "Start a fresh Boss chat")))
    tokens = _boss_chat_tokens()
    if tokens >= BOSS_CHAT_LONG_TOKENS and not tips:
        from .config import PRICES, UNKNOWN_PRICE, model_for
        per = tokens * PRICES.get(model_for("boss"), UNKNOWN_PRICE)[0] / 1e6 * 0.1   # cached reads cost a tenth
        tips.append(_tip("boss_chat_long", "efficiency", "low",
                         f"The Boss chat is long (about {tokens // 1000}k tokens)",
                         f"All of it is sent again with every message. Even cached that's about {_usd(per)} a message, "
                         "and much more whenever the cache has gone cold.",
                         "Start a fresh chat when you change topic. Your vision file and the Boss's notes carry over.",
                         ("Open the Boss", "/#boss"), ("fresh_boss_chat", "Start a fresh Boss chat")))
    return tips


def check_money() -> list[dict]:
    tips = []
    week = _spend(_ago(days=7))
    posted = db.rows("SELECT COUNT(*) n FROM posts WHERE status = 'posted' AND platform != 'practice' AND created_at >= ?",
                     _ago(days=7))[0]["n"]
    pitched = db.rows("SELECT COUNT(*) n FROM pitch_sent WHERE sent_at >= ?", _ago(days=7))[0]["n"]
    if week >= 1 and not posted and not pitched:
        tips.append(_tip("spend_no_output", "money", "high",
                         f"HQ spent {_usd(week)} on Claude this week and nothing went out",
                         "No clip was posted to a real account and no pitch was emailed. Money only comes in after "
                         "one of those happens.",
                         "Fix whatever stops the first one: usually connecting a real posting account, or approving "
                         "the clips and pitches that are waiting.", ("Open Settings", "/settings#accounts")))
    # days the budget ran out
    hit, football_hit = 0, 0
    for d in range(1, 8):
        start = _day_start(d)
        end = _day_start(d - 1)
        business, football = _village_spend(start, end)
        hit += bool(DAILY_BUDGET and business >= DAILY_BUDGET)
        football_hit += bool(FOOTBALL_DAILY_BUDGET and football >= FOOTBALL_DAILY_BUDGET)
    if hit >= 2:
        tips.append(_tip("budget_hits", "money", "medium",
                         f"The daily budget ran out on {hit} of the last 7 days",
                         f"After {_usd(DAILY_BUDGET)} scheduled work stops for the day, so agents keep finishing late.",
                         "Say yes when Sweep offers a cheaper model for a small agent in Approvals, or raise "
                         "HQ_DAILY_BUDGET a little in Settings.", ("Open Settings", "/settings#k-HQ_DAILY_BUDGET")))
    if football_hit >= 2:
        tips.append(_tip("football_budget_hits", "money", "low",
                         f"Warrior Village ran out of budget on {football_hit} of the last 7 days",
                         f"After {_usd(FOOTBALL_DAILY_BUDGET)} its scheduled work stops for the day.",
                         "Raise HQ_FOOTBALL_DAILY_BUDGET a little in Settings, or ask fewer big football questions.",
                         ("Open Settings", "/settings#k-HQ_FOOTBALL_DAILY_BUDGET")))
    return tips


def check_other_agents() -> list[dict]:
    tips = []
    camp = db.rows("SELECT COUNT(*) n FROM campaigns WHERE status = 'proposed' AND created_at < ?", _ago(days=3))[0]["n"]
    picks = db.rows("SELECT COUNT(*) n FROM creator_picks WHERE status = 'new' AND created_at < ?", _ago(days=7))[0]["n"]
    if camp:
        tips.append(_tip("scout_waiting", "organization", "low",
                         f"{_plural(camp, 'campaign Scout found has', 'campaigns Scout found have')} waited over 3 days",
                         "Campaign budgets run out, so the good ones fill up fast.",
                         "Join or skip them on the Campaigns tab.", ("Open Campaigns", "/#campaigns")))
    if picks:
        tips.append(_tip("creator_picks_waiting", "organization", "low",
                         f"{_plural(picks, 'streamer suggestion is', 'streamer suggestions are')} over a week old",
                         "They clutter the Pitch tab and their numbers are out of date.",
                         "Skip the ones you won't use.", ("Open Pitch", "/#pitch")))
    ideas = db.rows("SELECT COUNT(*) n FROM ideas WHERE status = 'proposed' AND created_at < ?", _ago(days=7))[0]["n"]
    if ideas:
        tips.append(_tip("muse_waiting", "organization", "low",
                         f"{_plural(ideas, 'idea from Muse has', 'ideas from Muse have')} waited over a week",
                         "Muse doesn't think up more until you've answered these, so new ideas stop coming.",
                         "Press Build it, Later or Not for me on each one on the Ideas tab.", ("Open Ideas", "/#ideas")))
    sheets = db.rows("SELECT COUNT(*) n FROM football_files WHERE status = 'failed'")[0]["n"]
    if sheets:
        tips.append(_tip("football_failed_sheets", "quality", "low",
                         f"Ref couldn't check {_plural(sheets, 'football sheet')}",
                         "Those files are sitting unchecked in the football Inbox.",
                         "Open each one on the Warrior Village tab and press Check again, or save it again as .xlsx.",
                         ("Open Warrior Village", "/#football")))
    return tips


CHECKS = [check_setup, check_approvals, check_waiting_clips, check_clip_quality, check_posting, check_pitch,
          check_tasks, check_boss, check_money, check_other_agents]


def _day_start(days_back: int) -> str:
    d = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_back)
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")


def _village_spend(start: str, end: str) -> tuple[float, float]:
    from .config import village_of
    business = football = 0.0
    for r in db.rows("SELECT agent, SUM(cost_usd) usd FROM llm_usage WHERE created_at >= ? AND created_at < ? "
                     "GROUP BY agent", start, end):
        if village_of(r["agent"]) == "football":
            football += r["usd"] or 0
        elif village_of(r["agent"]) == "etsy":
            pass   # the Etsy village has its own caps, so it never counts toward the business budget
        else:
            business += r["usd"] or 0
    return business, football


# ---- putting it together ---------------------------------------------------------------------------------

def find_tips() -> tuple[list[dict], list[str]]:
    """Every check, most urgent first. A check that breaks is skipped and named, never stopping the rest."""
    tips, broken = [], []
    for check in CHECKS:
        try:
            tips += check()
        except Exception as e:
            traceback.print_exc()
            broken.append(f"{check.__name__}: {e}")
    # setup steps first within their severity: they block everything after them
    tips.sort(key=lambda t: (SEVERITY_ORDER[t["severity"]], not t["id"].startswith("setup_"), AREA_ORDER[t["area"]], t["id"]))
    return tips, broken


def score(tips: list[dict]) -> int:
    return max(0, 100 - sum(WEIGHT[t["severity"]] for t in tips))


def unit_costs() -> list[dict]:
    """What each useful thing cost in Claude this week: cheap to read, and the clearest sign of waste."""
    since = _ago(days=7)
    made = {
        "Chad": (db.rows("SELECT COUNT(*) n FROM clips WHERE created_at >= ?", since)[0]["n"], "clip"),
        "Pitch": (db.rows("SELECT COUNT(*) n FROM leads WHERE created_at >= ?", since)[0]["n"], "draft"),
        "Boss": (sum(1 for m in db.rows("SELECT content FROM boss_messages WHERE role = 'user' AND created_at >= ?", since)
                     if _text_of(m["content"])), "message"),
        "Scout": (db.rows("SELECT COUNT(*) n FROM campaigns WHERE created_at >= ?", since)[0]["n"], "campaign"),
    }
    out = []
    for agent, (n, unit) in made.items():
        usd = _spend(since, agent)
        if usd >= 0.01:
            out.append({"agent": agent, "usd": round(usd, 4), "count": n, "unit": unit,
                        "each": round(usd / n, 4) if n else None})
    return out


# ---- one-tap fixes ---------------------------------------------------------------------------------------
# Only run when Steven presses the button (dashboard or Telegram). Each one re-checks the facts first, does one small
# safe thing, writes it to the activity log and says what it did. None of them posts, emails, spends or changes settings.

def _fix_pitch_recheck() -> str:
    if _recheck_waiting():
        return "Pitch is already looking for those emails."
    if not _pitch_cards_without_email()[0]:
        return "Every waiting pitch already has an email."
    tid = db.create_task("Pitch", "Look for emails for pitches waiting for approval that have none.",
                         {"recheck": True}, created_by="Sweep")
    return f"Asked Pitch to look for the missing emails (task #{tid}). The cards update by themselves."


def _fix_cancel_duplicates() -> str:
    n = 0
    for dup, first in _queue_duplicates():
        with db.connect() as c:
            n += c.execute("UPDATE tasks SET status = 'failed', result = ?, updated_at = ? WHERE id = ? AND status = 'queued'",
                           (f"Sweep: cancelled, it repeats task #{first}", db.now(), dup)).rowcount
    return f"Cancelled {_plural(n, 'duplicate job')}. The first of each is still queued." if n else "No duplicates left."


def _fix_set_aside_broken() -> str:
    """Marked failed, not rejected: Chad learns Steven's taste from his rejections, and a lost file says nothing
    about taste. Failed clips never post and drop out of the approval list."""
    ids = _broken_clip_ids()
    for cid in ids:
        db.execute("UPDATE clips SET status = 'failed', boss_note = COALESCE(boss_note || ' ', '') || ? "
                   "WHERE id = ? AND status = 'pending_approval'", SET_ASIDE_NOTE, cid)
    return (f"Set aside {_plural(len(ids), 'clip')} with no video file: " + ", ".join(f"#{i}" for i in ids) + "."
            if ids else "Every waiting clip still has its video.")


def _fix_fresh_boss_chat() -> str:
    from . import boss
    if _boss_chat_tokens() < 2000:
        return "The Boss chat is already fresh."
    boss.new_conversation()
    return ("Started a fresh Boss chat. The old one is saved, and your vision file and the Boss's notes carry over "
            "along with a short recap of the last few messages.")


FIXES = {  # id -> (number used on Telegram buttons, what it does)
    "pitch_recheck": (1, _fix_pitch_recheck),
    "cancel_duplicates": (2, _fix_cancel_duplicates),
    "set_aside_broken": (3, _fix_set_aside_broken),
    "fresh_boss_chat": (4, _fix_fresh_boss_chat),
}


def apply_fix(fix_id: str, who: str = "Steven") -> str:
    if fix_id not in FIXES:
        raise ValueError(f"Sweep has no fix called {fix_id}")
    done = FIXES[fix_id][1]()
    db.log("Sweep", f"One-tap fix ({who}): {done}")
    return done


def fix_by_number(n: int) -> str | None:
    return next((k for k, (num, _) in FIXES.items() if num == n), None)


# ---- the coach's note: Sweep's one small Claude call a day -----------------------------------------------

COACH_SYSTEM = """You are Sweep, the quality-control agent of Steven's AI business HQ. You get today's facts and the
rule-based findings (with the steps already suggested for each). Write a short coach's note for Steven: the one
pattern or priority the separate findings don't say on their own (for example which finding unblocks the others, or a
habit that would stop several of them coming back). Plain words for a beginner, at most 3 sentences and 70 words, no
lists, no headings. Use only the facts given and never invent numbers. Never suggest that an agent posts, emails or
spends without Steven's approval. If everything looks fine, say so in one sentence."""

COACH_SCHEMA = {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"],
                "additionalProperties": False}


def coach_enabled() -> bool:
    return os.getenv("HQ_SWEEP_COACH", "true").strip().lower() not in ("false", "0", "no", "off")


def coach_note(facts: dict) -> str | None:
    """One call on a mid-priced model, about a cent. Skipped without a key, when switched off, or once the day's
    budget is spent (Sweep's other work keeps running either way)."""
    from . import llm
    from .config import HAS_LLM, model_for
    if not (HAS_LLM and coach_enabled()) or ledger.over_budget("business"):
        return None
    try:
        out = llm.ask_json(model_for("sweep"), COACH_SYSTEM, json.dumps(facts, default=str)[:12000], COACH_SCHEMA,
                           effort="low", agent="Sweep")
        return (out.get("note") or "").strip()[:600] or None
    except Exception as e:
        db.log("Sweep", f"Couldn't write the coach's note: {e}")
        return None
