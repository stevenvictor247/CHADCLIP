"""Radar: the research lab. Once a week finds which shirt themes are selling, as a brief for Quill.

Claude searches the web (Anthropic runs the searches, so HQ scrapes nothing, and etsy.com is left out so Radar
learns themes, never copies other shops' designs). Your own research pastes from the Etsy tab go in too. Without a
Claude key, or when the budget is spent, the brief comes from the holiday calendar and evergreen themes for free.
"""

import json
import re

from ... import db, ledger, llm
from ...config import HAS_LLM, model_for
from ...etsy import season, store
from ..base import Agent

SEARCH_USES = 6
SEARCH_TURNS = 4
BLOCKED = ["etsy.com", "www.etsy.com"]

SYSTEM = """You are Radar, the research lab of a small Etsy shop that sells printed t-shirts made to order by
Printify. You find shirt THEMES that sell: who buys them and what angles work. Rules:
- Themes only, never another shop's design or exact slogan. Never a brand, team, league, school, show, character,
  game title or famous person: those are trademarks and get shops closed.
- Prefer big, steady gift markets (jobs, hobbies, pets, family roles, milestones) and the next holidays.
- Be honest: say why each theme sells, and what you saw. No made-up numbers."""

PROMPT = """Today is {today}. Find 10 to 12 shirt themes to design for in the next few weeks.

Holidays coming up (have designs listed by the "start by" date):
{holidays}

Notes Steven pasted from his own research (trust these most):
{notes}

What's on the board already, with sales:
{board}

Search the web for what's trending in gift t-shirts and print on demand right now (blogs, Google Trends write-ups,
print on demand newsletters). Then answer with a short paragraph, and finish with exactly one JSON object:
{{"themes": [{{"theme": "...", "audience": "who buys it", "why": "why now, in one sentence",
"angles": ["3 to 5 slogan directions"], "keywords": ["3 to 6 search words buyers use"],
"until": "YYYY-MM-DD the theme stops being useful, or null if evergreen"}}], "note": "one line on what you saw"}}"""


def _last_json(text: str) -> dict:
    decoder = json.JSONDecoder()
    for m in reversed(list(re.finditer(r"\{\s*\"themes\"", text))):
        try:
            data, _ = decoder.raw_decode(text[m.start():])
            if isinstance(data, dict) and isinstance(data.get("themes"), list):
                return data
        except ValueError:
            continue
    return {}


def _board() -> str:
    rows = db.rows("SELECT theme, COUNT(*) n, SUM(sales) s FROM etsy_designs WHERE stage NOT IN ('rejected', 'held') "
                   "GROUP BY theme ORDER BY s DESC, n DESC LIMIT 15")
    return "\n".join(f"- {r['theme']}: {r['n']} designs, {r['s'] or 0} sales" for r in rows) or "- nothing yet"


def research() -> str:
    from datetime import date
    holidays = season.upcoming()
    notes = store.notes("research", unused=True, limit=10)
    if not HAS_LLM or ledger.over_budget("etsy"):
        why = "no Claude key" if not HAS_LLM else "the Etsy budget is spent"
        store.add_brief(season.free_brief(), "calendar", f"Free brief from the calendar ({why})")
        return f"Made a free brief from the holiday calendar and evergreen themes ({why})."
    prompt = PROMPT.format(
        today=date.today().isoformat(),
        holidays="\n".join(f"- {h['name']} {h['date']}, start by {h['start_by']}" for h in holidays) or "- none soon",
        notes="\n".join(f"- {n['text'][:600]}" for n in notes) or "- none",
        board=_board())
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": SEARCH_USES, "blocked_domains": BLOCKED}]
    messages = [{"role": "user", "content": prompt}]
    for _ in range(SEARCH_TURNS):
        response = llm.create(model_for("radar"), SYSTEM, messages, tools=tools, effort="low", agent="Radar")
        if response.stop_reason != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": response.content}]
    data = _last_json(llm.text_of(response))
    themes = [t for t in data.get("themes", []) if isinstance(t, dict) and t.get("theme")]
    if not themes:
        store.add_brief(season.free_brief(), "calendar", "Radar's search came back empty, so this is the free brief")
        return "Radar's search found nothing usable, so I made the free brief from the calendar."
    store.add_brief(themes[:14], "radar", str(data.get("note") or "")[:400])
    store.mark_notes_used([n["id"] for n in notes])
    return f"New brief with {len(themes[:14])} themes: " + ", ".join(t["theme"] for t in themes[:6])


class Radar(Agent):
    def __init__(self):
        super().__init__(
            name="Radar",
            role="Trend researcher in the Etsy village. Once a week finds which shirt themes are selling and the next "
                 "holidays to design for, as a brief for Quill. Reads your research notes from the Etsy tab. Never "
                 "scrapes Etsy and never copies another shop's design.",
            params_help='{} makes a new brief now (it also runs once a week by itself).',
            schedule=[(6, "Weekly trend brief.", {})],
            village="etsy",
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        age = store.brief_age_days()
        if age is None:
            return False
        fresh_notes = store.notes("research", unused=True, limit=1)
        return age < 7 and not (fresh_notes and age >= 1)

    def run(self, task: dict) -> str:
        return research()
