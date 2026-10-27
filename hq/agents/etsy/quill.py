"""Quill: the copy desk. Writes new shirts for the brief's themes: the words on the shirt, the look, and the Etsy
title, 13 tags and description. A few a day (HQ_ETSY_DESIGNS_PER_DAY), and it stops while too many wait for you."""

import json

from ... import db, ledger, llm
from ...config import HAS_LLM, model_for
from ...etsy import art, store
from ..base import Agent

SYSTEM = """You are Quill, the copywriter of a small Etsy shop selling printed t-shirts (made to order by Printify).
You write shirts people buy as gifts or for themselves. Rules, all of them hard:
- Original words only. Never a brand, team, league, school, show, film, song lyric, character, game title, meme
  owned by someone, or famous person's name or catchphrase. Never copy a slogan you've seen on another shop.
- Short and readable from across a room: 2 to 7 words is best. Use " / " to mark where lines break.
- Warm, funny or proud. No insults about groups of people, nothing political, nothing adult.
- Etsy title: up to 140 characters, the words buyers search first, then the occasion (e.g. "Dog Mom Shirt, Funny Dog
  Lover Gift, Coffee and Dog Hair Tee, Mothers Day Gift for Her"). %, : and & at most once each.
- Exactly 13 tags, each 20 characters or fewer, letters, numbers and spaces only, all different, phrases buyers type.
- Description: 2 short friendly paragraphs about who it's for and the occasion. Don't mention fabric, sizes, care,
  Printify or AI: the shop adds those lines itself. Never say handmade.
- price_cents between 2299 and 2799 (the shirt costs the shop about $12).
- style is one of: bold (stacked block letters), retro (70s sunset), script (handwritten first line), marker
  (hand-lettered), badge (framed, vintage). Pick what fits the words.
- art_prompt: only when a simple picture would really sell it (a cartoon dog, a campfire). Describe a generic subject
  in one sentence, no text in it. Otherwise null."""

SCHEMA = {"type": "object", "properties": {"designs": {"type": "array", "items": {"type": "object", "properties": {
    "theme": {"type": "string"}, "slogan": {"type": "string"}, "subline": {"type": ["string", "null"]},
    "style": {"type": "string", "enum": list(art.STYLES)}, "art_prompt": {"type": ["string", "null"]},
    "title": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}},
    "description": {"type": "string"}, "price_cents": {"type": "integer"}},
    "required": ["theme", "slogan", "subline", "style", "art_prompt", "title", "tags", "description", "price_cents"],
    "additionalProperties": False}}}, "required": ["designs"], "additionalProperties": False}


def _key(slogan: str) -> str:
    return " ".join(slogan.lower().replace("/", " ").split())


def room() -> int:
    """How many new designs Quill may write now."""
    return max(0, min(store.designs_per_day() - store.made_today(), store.max_waiting() - store.waiting(), 6))


def pick_themes(brief: dict, n: int) -> list[dict]:
    """Themes with sales first, then the ones with the fewest designs so far, skipping themes that have run out."""
    from datetime import date
    today = date.today().isoformat()
    made = {r["theme"].lower(): (r["n"], r["s"] or 0) for r in db.rows(
        "SELECT theme, COUNT(*) n, SUM(sales) s FROM etsy_designs GROUP BY theme")}
    themes = [t for t in brief["themes"] if not t.get("until") or str(t["until"]) >= today]
    themes.sort(key=lambda t: (-made.get(t["theme"].lower(), (0, 0))[1], made.get(t["theme"].lower(), (0, 0))[0]))
    return themes[:max(1, min(n, 3))]


def write(n: int | None = None, theme: str | None = None) -> str:
    n = room() if n is None else n
    if n <= 0:
        return "Nothing to write: enough designs are waiting or today's are done."
    if not HAS_LLM:
        return "Nothing to write without a Claude key (Quill needs Claude)."
    if ledger.over_budget("etsy"):
        return "Nothing to write: the Etsy village's budget is spent."
    brief = store.latest_brief()
    if not brief and not theme:
        return "Nothing to write yet: Radar hasn't made a brief."
    themes = [{"theme": theme, "audience": "", "why": "Steven asked", "angles": []}] if theme else pick_themes(brief, n)
    used = store.used_slogans(150)
    prompt = (f"Write {n} new shirt designs, spread across these themes:\n" +
              "\n".join(f"- {t['theme']}: for {t.get('audience') or 'fans of it'}. {t.get('why') or ''} "
                        f"Angles: {', '.join(t.get('angles') or [])}" for t in themes) +
              "\n\nSlogans the shop already has (don't repeat or closely echo them):\n" +
              ("\n".join(f"- {s}" for s in used[:150]) or "- none yet"))
    data = llm.ask_json(model_for("quill"), SYSTEM, prompt, SCHEMA, effort="medium", agent="Quill")
    seen = {_key(s) for s in used}
    made = []
    for d in data.get("designs", [])[:n]:
        key = _key(d["slogan"])
        if key in seen or not d["slogan"].strip():
            continue
        seen.add(key)
        d["price_cents"] = min(max(int(d.get("price_cents") or 2499), 1999), 3499)
        made.append(store.add_design(d, brief["id"] if brief else None))
        db.log("Quill", f"Wrote a shirt for {d['theme']}: {d['slogan']}")
    return f"Wrote {len(made)} new shirt(s) for " + ", ".join(sorted({t['theme'] for t in themes})) if made \
        else "None of the new slogans were new enough, so nothing was added."


class Quill(Agent):
    def __init__(self):
        super().__init__(
            name="Quill",
            role="Copywriter in the Etsy village. Writes new shirts for Radar's themes: the words, the look, and the "
                 "Etsy title, 13 tags and description. A few a day, and pauses while too many wait for you.",
            params_help='{} writes the next few; {"theme": "nurses", "count": 3} writes for one theme now.',
            schedule=[(3, "Write new shirt designs.", {})],
            village="etsy",
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        return room() <= 0 or not store.latest_brief() or not HAS_LLM

    def run(self, task: dict) -> str:
        p = json.loads(task.get("params") or "{}")
        if p.get("theme"):
            return write(max(1, min(int(p.get("count") or 3), 6)), p["theme"])
        return write()
