"""The free steps of the shirt line, in plain code: Loom draws, Warden checks, Dock builds and watches Printify.

Each step moves one design along the product board (store.STAGES). The agents in hq/agents/etsy call these; the
dashboard's buttons call them too.
"""

import json
import os
import traceback
from pathlib import Path

from .. import approvals, db, relay
from ..config import ETSY_DIR
from . import art, images, printify, rules, store

DESIGNS_DIR = ETSY_DIR / "designs"
FIRST_REVIEWS = 5   # in "auto", you see this many designs yourself before clean ones go straight through


def review_mode() -> str:
    mode = (os.getenv("HQ_ETSY_REVIEW_DESIGNS") or "auto").strip().lower()
    return mode if mode in ("auto", "always", "never") else "auto"


def needs_review(result: dict) -> bool:
    """Whether a design waits for your OK. Warnings always do; otherwise it depends on HQ_ETSY_REVIEW_DESIGNS."""
    if result["warnings"]:
        return True
    mode = review_mode()
    if mode == "always":
        return True
    if mode == "never":
        return False
    return store.steven_approved() < FIRST_REVIEWS


# ---- Loom ----------------------------------------------------------------------------------------------------

def draw(design_id: int) -> str:
    d = store.get(design_id)
    if not d:
        return f"No design #{design_id}"
    folder = DESIGNS_DIR / str(design_id)
    pic, used_ai, note = None, False, ""
    if d.get("art_prompt"):
        blocked = images.why_not()
        if blocked:
            note = f" (words only: {blocked.lower()})"
        else:
            try:
                pic = images.make(d["art_prompt"], folder / "art.png")
                used_ai = True
            except Exception as e:
                note = f" (words only: {e})"
    files = art.render(d, folder, pic)
    store.update(design_id, files=files, used_ai_art=int(used_ai), stage="drawn",
                 note="Loom drew it" + (" with a picture" if used_ai else "") + note)
    db.log("Loom", f"Drew design #{design_id}: {d['slogan']}{note}")
    return f"Drew #{design_id} \"{d['slogan']}\"{note}"


# ---- Warden --------------------------------------------------------------------------------------------------

def check(design_id: int) -> str:
    d = store.get(design_id)
    if not d:
        return f"No design #{design_id}"
    d["tags"] = rules.clean_tags(d["tags"])
    d["description"] = rules.finish_description(d["description"], bool(d["used_ai_art"]))
    result = rules.check(d)
    store.update(design_id, tags=d["tags"], description=d["description"], warden=result)
    if result["problems"]:
        store.move(design_id, "held", "Warden held it: " + "; ".join(result["problems"]))
        db.log("Warden", f"Held design #{design_id}: {'; '.join(result['problems'])}")
        return f"Held #{design_id}: " + "; ".join(result["problems"])
    if needs_review(result):
        preview = f"\"{d['slogan']}\" for {d['theme']}\nTitle: {d['title']}\nPrice: ${d['price_cents'] / 100:.2f}"
        if result["warnings"]:
            preview += "\n\nWarden says: " + "; ".join(result["warnings"])
        preview += "\n\nApprove and Dock builds it in Printify (not published). You publish it yourself."
        aid = approvals.request("Warden", "etsy_design", f"New shirt: {d['slogan']}", preview,
                                {"design_id": design_id, "draft": d["files"].get("preview")},
                                yes="Build it", no="Skip it")
        store.update(design_id, approval_id=aid)
        store.move(design_id, "review", "Waiting for your OK in Approvals")
        return f"Checked #{design_id}: waiting for your OK" + (" (has warnings)" if result["warnings"] else "")
    store.move(design_id, "approved", "Warden passed it")
    db.log("Warden", f"Passed design #{design_id}: {d['slogan']}")
    return f"Passed #{design_id}"


def decide(payload: dict, decision: str) -> str:
    """Approvals handler for a new shirt."""
    did = int(payload["design_id"])
    d = store.get(did)
    if not d:
        return "That design is gone."
    if d["stage"] != "review":
        return f"Design #{did} has already moved on ({d['stage']})."
    if decision == "approve":
        store.move(did, "approved", "You approved it")
        return f"Approved \"{d['slogan']}\". Dock builds it in Printify next."
    store.move(did, "rejected", "You skipped it")
    return f"Skipped \"{d['slogan']}\"."


approvals.HANDLERS["etsy_design"] = decide


# ---- Dock ----------------------------------------------------------------------------------------------------

def build(design_id: int) -> str:
    d = store.get(design_id)
    if not d:
        return f"No design #{design_id}"
    if d["stage"] != "approved":
        return f"Design #{design_id} isn't approved ({d['stage']})"
    store.move(design_id, "building", "Dock is building it in Printify")
    try:
        pid = printify.create_product(d)
    except Exception as e:
        traceback.print_exc()
        store.move(design_id, "approved", f"Printify build failed, will try again: {str(e)[:200]}")
        raise
    store.update(design_id, printify_product_id=pid, stage="ready",
                 note="In Printify, not published. Add a real photo, then press Publish in Printify.")
    db.log("Dock", f"Built design #{design_id} in Printify (product {pid}): ready for you to publish")
    return f"Built #{design_id} in Printify"


def sync_live() -> list[str]:
    """Designs you've published from Printify become live on the board."""
    out = []
    for d in store.designs("ready"):
        if not d.get("printify_product_id"):
            continue
        listing = printify.listing_of(d["printify_product_id"])
        if listing:
            store.update(d["id"], etsy_listing_id=listing, stage="live", note="Live on Etsy")
            db.log("Dock", f"\"{d['slogan']}\" is live on Etsy (listing {listing})")
            out.append(d["slogan"])
    return out


def sync_orders() -> int:
    """Saves Printify's recent orders. A new one waiting for you (on hold) is sent to your phone once."""
    new = 0
    for o in printify.orders():
        have = db.rows("SELECT told FROM etsy_orders WHERE id = ?", o["id"])
        db.execute("INSERT INTO etsy_orders (id, status, total_cents, cost_cents, items, created_at, updated_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET status = excluded.status, "
                   "total_cents = excluded.total_cents, cost_cents = excluded.cost_cents, items = excluded.items, "
                   "updated_at = excluded.updated_at", o["id"], o["status"], o["total_cents"], o["cost_cents"],
                   json.dumps(o["items"]), o["created_at"] or db.now(), db.now())
        if not have:
            new += 1
            for it in o["items"]:
                db.execute("UPDATE etsy_designs SET sales = sales + ? WHERE printify_product_id = ?",
                           int(it.get("quantity") or 1), str(it.get("product_id") or ""))
        if o["status"] in ("on-hold", "pending") and not (have and have[0]["told"]):
            what = ", ".join(f"{i['quantity']}x {i['title']}" for i in o["items"]) or "a shirt"
            relay.notify(f"🛍️ New Etsy order: {what}. Open Printify > Orders and press Send to production "
                         f"when it looks right. HQ never does that step for you.")
            db.execute("UPDATE etsy_orders SET told = 1 WHERE id = ?", o["id"])
            db.log("Dock", f"New Etsy order waiting for you in Printify: {what}")
    return new


def preview_path(design_id: int) -> Path | None:
    d = store.get(design_id)
    p = Path(d["files"].get("preview", "")) if d else None
    return p if p and p.is_file() else None
