"""Etta: runs the Etsy village. Writes the Sunday shop report (what sold, what's waiting for you, what to make more
of) and answers the Boss about the shop. Her report is one short Claude call; without Claude it's plain numbers."""

import json
from datetime import datetime

from ... import db, ledger, llm, relay
from ...config import HAS_LLM, model_for
from ... import etsy
from ...etsy import store
from ..base import Agent

SYSTEM = """You are Etta, who runs a small Etsy t-shirt shop for Steven (designs by HQ's agents, printed by Printify).
Write his weekly shop report: 5 to 8 short lines, plain words. Lead with anything waiting for him (designs to
approve, shirts to publish with a real photo, orders to send to production). Then what sold and what to make more
or less of. Never invent numbers: use only the facts given. Say plainly if nothing has sold yet."""


def report() -> str:
    facts = etsy.status()
    facts["designs_this_week"] = db.rows("SELECT COUNT(*) n FROM etsy_designs WHERE created_at >= ?",
                                         store.week_ago())[0]["n"]
    facts["best_sellers"] = [f"{r['slogan']} ({r['sales']})" for r in db.rows(
        "SELECT slogan, sales FROM etsy_designs WHERE sales > 0 ORDER BY sales DESC LIMIT 5")]
    facts["latest_stats_file"] = (store.notes("stats", limit=1) or [{"text": None}])[0]["text"]
    if HAS_LLM and not ledger.over_budget("etsy"):
        r = llm.create(model_for("etta"), SYSTEM, [{"role": "user", "content": json.dumps(facts, default=str)}],
                       effort="low", max_tokens=2000, agent="Etta")
        text = llm.text_of(r)
    else:
        b = facts["board"]
        text = "\n".join(filter(None, [
            f"Waiting for your OK: {len(facts['waiting_for_your_ok'])}" if facts["waiting_for_your_ok"] else "",
            f"Ready for you to publish in Printify: {len(facts['ready_for_you_to_publish'])}"
            if facts["ready_for_you_to_publish"] else "",
            f"Orders waiting for Send to production: {len(facts['orders_waiting_for_you'])}"
            if facts["orders_waiting_for_you"] else "",
            f"Live shirts: {facts['live']}. Sales so far: {facts['sales']}.",
            f"New designs this week: {facts['designs_this_week']}. Board: "
            + ", ".join(f"{k} {v}" for k, v in b.items()) if b else "No designs yet.",
            "Best sellers: " + ", ".join(facts["best_sellers"]) if facts["best_sellers"] else ""]))
    store.add_note(text, "report")
    relay.notify("🛍️ Etsy weekly report\n\n" + text)
    return text


class Etta(Agent):
    def __init__(self):
        super().__init__(
            name="Etta",
            role="Runs the Etsy village (Print Street): shirt designs sold on Etsy, printed and shipped by Printify. "
                 "Sends the Sunday shop report and keeps Radar, Quill, Loom, Warden and Dock moving. Never publishes, "
                 "never sends orders to production, never answers buyers: those are Steven's.",
            params_help='{} or {"report": true} writes the shop report now.',
            schedule=[(6, "Weekly Etsy shop report.", {"weekly": True})],
            village="etsy",
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        if not params.get("weekly"):
            return None
        if datetime.now().weekday() != 6 or datetime.now().hour < 9:
            return True   # Sunday mornings only
        if not store.designs(limit=1):
            return True
        return bool(db.rows("SELECT 1 FROM etsy_notes WHERE kind = 'report' AND created_at >= ? LIMIT 1",
                            store.week_ago()[:10]))

    def run(self, task: dict) -> str:
        return report()
