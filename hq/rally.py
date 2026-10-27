"""Rally: drafts short college football posts (text plus a simple card) from public stats.

Everything checkable in plain code happens before Claude is called (season, a week's gap, facts present) and again
after (every number must come from the facts, no school marks or game film). Rally never posts: each draft waits in
Approvals, and approving it only hands Steven the text and card to post himself.
"""

import json
import re
import textwrap
from datetime import date, datetime, timedelta, timezone

import requests
import yaml

from . import approvals, db, llm, relay
from .config import CONFIG_DIR, DATA_DIR, model_for

CONFIG_PATH = CONFIG_DIR / "rally.yaml"
CARDS_DIR = DATA_DIR / "rally"
TOPICS = ("upset_watch", "rankings", "rivalry", "stat_fact")
ROUND_GAP_DAYS = 6
MIN_FACTS = 3
MAX_FACTS_CHARS = 6000
BANNED = re.compile(r"\b(logos?|trademark|highlights?|film|footage|clips? of|game video)", re.I)

SYSTEM = """You write short posts for a neutral college football fan account on TikTok and YouTube Shorts.
You get a list of public facts. Use ONLY those facts. Never invent scores, records, rankings, dates or quotes, and
never add a number that is not in the facts.
Write exactly {n} posts, each a different angle on the account's niche ({niche}). Each has:
- topic: one of upset_watch, rankings, rivalry, stat_fact
- headline: under 60 characters, plain and specific, for the card
- body: 1 to 3 short sentences (under 220 characters) stating facts, for the card
- caption: under 150 characters plus up to 3 hashtags
No school logos, mascots or marks, no mention of game film or highlights, no betting advice, no insults."""

SCHEMA = {"type": "object", "properties": {"posts": {"type": "array", "items": {
    "type": "object",
    "properties": {"topic": {"type": "string", "enum": list(TOPICS)}, "headline": {"type": "string"},
                   "body": {"type": "string"}, "caption": {"type": "string"}},
    "required": ["topic", "headline", "body", "caption"], "additionalProperties": False}}},
    "required": ["posts"], "additionalProperties": False}


class RallyError(ValueError):
    """Something Steven can fix; the message says what, in plain words."""


def config() -> dict:
    cfg = {"niche": "Weekly upset watch", "season_ends": "2027-01-12", "posts_per_round": 5, "rankings_url": ""}
    if CONFIG_PATH.exists():
        cfg.update(yaml.safe_load(CONFIG_PATH.read_text()) or {})
    return cfg


def _today() -> date:
    return date.today()


def why_not_now() -> str | None:
    """Free look: None means a round may run; otherwise the plain reason it should not."""
    cfg = config()
    if _today() > date.fromisoformat(str(cfg["season_ends"])):
        return "The season is over."
    if not llm.HAS_LLM:
        return "No Claude key."
    if db.rows("SELECT id FROM rally_posts WHERE status = 'pending' LIMIT 1"):
        return "Posts are still waiting for Steven."
    last = db.rows("SELECT MAX(created_at) AS t FROM rally_posts")[0]["t"]
    if last and datetime.fromisoformat(last) > datetime.now(timezone.utc) - timedelta(days=ROUND_GAP_DAYS):
        return "Drafted within the last week."
    return None


# ---- public facts (free) ----

def fetch_rankings(url: str | None = None) -> list[str]:
    """Turn a public rankings feed (ESPN's JSON shape) into plain fact lines. Raises RallyError if it can't."""
    url = url or config()["rankings_url"]
    if not url:
        raise RallyError("No rankings_url in config/rally.yaml. Paste facts instead.")
    try:
        data = requests.get(url, timeout=15).json()
    except Exception as e:
        raise RallyError(f"Couldn't read the public rankings ({e.__class__.__name__}). Paste facts instead.")
    facts = []
    for poll in data.get("rankings", [])[:2]:
        name = poll.get("name") or "Poll"
        for r in poll.get("ranks", [])[:25]:
            t = r.get("team") or {}
            team = t.get("location") or t.get("name")
            if team and r.get("current"):
                rec = r.get("recordSummary")
                facts.append(f"{name}: {team} is ranked {r['current']}" + (f" with a {rec} record" if rec else ""))
    return facts


def clean_facts(raw) -> list[str]:
    facts = [" ".join(str(f).split()) for f in (raw or []) if str(f).strip()]
    return facts


# ---- checking Claude's answer (free) ----

def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+", text))


def clean(posts: list[dict], facts: list[str], want: int) -> list[dict]:
    allowed = _numbers(" ".join(facts))
    out = []
    for p in posts:
        h, b, c = (" ".join(str(p.get(k, "")).split()) for k in ("headline", "body", "caption"))
        text = f"{h} {b} {c}"
        if not h or not b or p.get("topic") not in TOPICS or BANNED.search(text):
            continue
        if _numbers(text) - allowed:   # a number that is not in the facts is an invented stat
            continue
        out.append({"topic": p["topic"], "headline": h[:70], "body": b[:240], "caption": c[:180]})
    if len(out) < 1:
        raise RallyError("Claude's drafts all failed the checks (invented numbers or school marks). Try again.")
    return out[:want]


# ---- the card (plain text on a solid colour: no logos, no school colours) ----

def make_card(post_id: int, headline: str, body: str):
    from PIL import Image, ImageDraw, ImageFont
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (1080, 1920), (16, 24, 40))
    d = ImageDraw.Draw(img)
    big, mid, small = (ImageFont.load_default(size=s) for s in (88, 56, 36))
    y = 380
    for line in textwrap.wrap(headline, 16):
        d.text((90, y), line, font=big, fill=(255, 255, 255))
        y += 110
    y += 60
    for line in textwrap.wrap(body, 30):
        d.text((90, y), line, font=mid, fill=(200, 210, 225))
        y += 74
    d.text((90, 1780), "Public stats only", font=small, fill=(120, 135, 160))
    path = CARDS_DIR / f"post-{post_id}.png"
    img.save(path)
    return path


# ---- drafting and approving ----

def format_post(p: dict) -> str:
    return f"[{p['topic']}] {p['headline']}\n{p['body']}\n\nCaption: {p['caption']}"


def draft(params: dict) -> str:
    why = why_not_now() if not params.get("facts") else None
    if params.get("facts") and not llm.HAS_LLM:
        why = "No Claude key."
    if why:
        raise RallyError(f"Nothing drafted: {why}")
    cfg = config()
    facts = clean_facts(params.get("facts")) or fetch_rankings()
    if len(facts) < MIN_FACTS:
        raise RallyError(f"Only {len(facts)} facts. Rally needs at least {MIN_FACTS} (paste more in \"facts\").")
    n = int(cfg["posts_per_round"])
    prompt = "Facts:\n" + "\n".join(f"- {f}" for f in facts)[:MAX_FACTS_CHARS]
    out = llm.ask_json(model_for("rally"), SYSTEM.format(n=n, niche=cfg["niche"]), prompt, SCHEMA, effort="low", agent="Rally")
    posts = clean(out.get("posts", []), facts, n)
    for p in posts:
        pid = db.execute("INSERT INTO rally_posts (topic, headline, body, caption, created_at) VALUES (?, ?, ?, ?, ?)",
                         p["topic"], p["headline"], p["body"], p["caption"], db.now())
        path = make_card(pid, p["headline"], p["body"])
        db.execute("UPDATE rally_posts SET card_path = ? WHERE id = ?", str(path), pid)
        approvals.request("Rally", "rally", f"Rally post: {p['headline']} (NOT POSTED)", format_post(p),
                          {"rally_id": pid}, yes="Approve post", no="Reject")
    return f"Drafted {len(posts)} posts. Each is waiting for your OK; Rally never posts."


def _decided(payload: dict, decision: str) -> str:
    rows = db.rows("SELECT * FROM rally_posts WHERE id = ?", payload["rally_id"])
    if not rows:
        return "That post no longer exists."
    r = rows[0]
    status = "approved" if decision == "approve" else "rejected"
    db.execute("UPDATE rally_posts SET status = ?, decided_at = ? WHERE id = ?", status, db.now(), r["id"])
    if decision == "reject":
        return f"Rejected: {r['headline']}"
    relay.notify(f"Post this yourself (Rally never posts):\n\n{format_post(r)}\n\nCard: {r['card_path']}")
    return f"Approved. Post it yourself with the card {r['card_path']}:\n\n{format_post(r)}"


approvals.HANDLERS["rally"] = _decided


# ---- learning what works ----

def record_views(post_id: int, views: int) -> str:
    rows = db.rows("SELECT status FROM rally_posts WHERE id = ?", post_id)
    if not rows:
        return f"No Rally post #{post_id}."
    if rows[0]["status"] not in ("approved", "posted"):
        return f"Rally post #{post_id} isn't approved, so it can't have views yet."
    db.execute("UPDATE rally_posts SET status = 'posted', views = MAX(views, ?) WHERE id = ?", max(views, 0), post_id)
    return f"Saved {views:,} views for Rally post #{post_id}."


def topic_report() -> str:
    rows = db.rows("SELECT topic, COUNT(*) AS n, AVG(views) AS avg FROM rally_posts WHERE status = 'posted' "
                   "GROUP BY topic ORDER BY avg DESC")
    if not rows:
        return "No Rally posts have views yet."
    return "Rally topics by average views:\n" + "\n".join(f"- {r['topic']}: {int(r['avg']):,} ({r['n']} posts)" for r in rows)
