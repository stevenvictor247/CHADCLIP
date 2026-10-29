"""Print Street, the Etsy village: shirt designs sold on Etsy, printed and shipped by Printify.

Agents (code in hq/agents/etsy): Etta runs the shop and writes the weekly report, Radar finds what's selling,
Quill writes the shirts and listings, Loom draws them, Warden checks every rule, Dock builds them in Printify and
watches orders. Steven's taps: approving the first designs, pressing Publish in Printify (with a real photo) and
pressing Send to production on each order. HQ never does those for him.

This village never reads Warrior Village files, and nothing here scrapes Etsy.
"""

import json
import os

from .. import db, ledger
from ..config import ETSY_AGENTS
from . import images, printify, rules, season, store


def shirt_cost() -> float:
    """What Printify charges for one shirt, before shipping (the buyer pays shipping). Bella+Canvas 3001: about $12."""
    return float(os.getenv("HQ_ETSY_SHIRT_COST", "12") or 12)


def profit_each(price_cents: int) -> float:
    """About what one sale leaves you, in US dollars: price minus Etsy's listing ($0.20), transaction (6.5%) and
    payment processing (3% + $0.25) fees and the shirt. Offsite Ads, when Etsy charges them, take more."""
    p = price_cents / 100
    return round(p - 0.20 - 0.065 * p - 0.03 * p - 0.25 - shirt_cost(), 2)


def pending_approvals() -> list[dict]:
    marks = ", ".join("?" for _ in ETSY_AGENTS)
    return db.rows(f"SELECT id, agent, title FROM approvals WHERE status = 'pending' AND agent IN ({marks})",
                   *ETSY_AGENTS)


def _card(d: dict) -> dict:
    return {"id": d["id"], "theme": d["theme"], "slogan": d["slogan"], "subline": d["subline"], "style": d["style"],
            "title": d["title"], "tags": d["tags"], "price": d["price_cents"] / 100, "stage": d["stage"],
            "note": d["note"], "warden": d["warden"], "has_preview": bool(d["files"].get("preview")),
            "ai_art": bool(d["used_ai_art"]), "printify_product_id": d["printify_product_id"],
            "etsy_listing_id": d["etsy_listing_id"], "photo_added": bool(d["photo_added"]), "sales": d["sales"],
            "profit_each": profit_each(d["price_cents"]), "approval_id": d["approval_id"], "updated_at": d["updated_at"]}


def orders(limit: int = 10) -> list[dict]:
    rows = db.rows("SELECT * FROM etsy_orders ORDER BY created_at DESC LIMIT ?", limit)
    for r in rows:
        r["items"] = json.loads(r["items"] or "[]")
    return rows


def state() -> dict:
    """Everything the Etsy tab and Print Street show."""
    spend = ledger.summary()
    brief = store.latest_brief()
    return {
        "counts": store.counts(),
        "designs": [_card(d) for d in store.designs(limit=120)],
        "brief": brief,
        "holidays": season.upcoming(),
        "notes": store.notes(limit=8),
        "orders": orders(),
        "rules": rules.RULES,
        "pace": {"per_day": store.designs_per_day(), "max_waiting": store.max_waiting(),
                 "made_today": store.made_today(), "waiting": store.waiting(), "review_mode": os.getenv(
                     "HQ_ETSY_REVIEW_DESIGNS", "auto") or "auto", "you_approved": store.steven_approved()},
        "connections": {"claude": bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")),
                        "printify": printify.connected(), "images": bool(images.key()),
                        "images_why_not": images.why_not()},
        "money": {"today_usd": spend["etsy_today_usd"], "month_usd": spend["etsy_month_usd"],
                  "budget_usd": spend["etsy_budget_usd"], "month_budget_usd": spend["etsy_month_budget_usd"],
                  "over_budget": spend["etsy_over_budget"], "images_month_usd": round(images.spent_this_month(), 2),
                  "images_cap_usd": images.monthly_cap(), "shirt_cost": shirt_cost(),
                  "sales": sum(d["sales"] for d in store.designs(limit=1000))},
        "waiting_for_you": pending_approvals(),
    }


def status() -> dict:
    """The short version for the Boss and Etta."""
    c = store.counts()
    brief = store.latest_brief()
    return {"board": {k: v for k, v in c.items() if v},
            "ready_for_you_to_publish": [d["slogan"] for d in store.designs("ready")][:10],
            "live": c["live"], "sales": sum(d["sales"] for d in store.designs(limit=1000)),
            "brief_themes": [t["theme"] for t in (brief["themes"] if brief else [])][:8],
            "next_holidays": [f"{h['name']} {h['date']} (start by {h['start_by']})" for h in season.upcoming()[:3]],
            "orders_waiting_for_you": [o["id"] for o in orders(20) if o["status"] in ("on-hold", "pending")],
            "waiting_for_your_ok": [a["title"] for a in pending_approvals()],
            "printify_connected": printify.connected(),
            "spend_today_usd": ledger.spent_today("etsy"), "spend_month_usd": ledger.spent_this_month("etsy"),
            "over_budget": ledger.over_budget("etsy")}
