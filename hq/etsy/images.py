"""Optional pictures for shirt designs, from OpenAI's image API. Off until you paste HQ_OPENAI_API_KEY in Settings.

Without it, Loom still makes every design from words and shapes, free. With it, designs whose idea needs a picture
(a cartoon dog, a camping scene) get one above the words. Each picture is counted in the Etsy village's budget and
has its own monthly cap, so it can never run up a bill.
"""

import base64
import os
from pathlib import Path

import requests

from .. import ledger

API = "https://api.openai.com/v1/images/generations"
STYLE = ("Flat vector t-shirt graphic, bold clean outlines, limited color palette, centered, isolated on a "
         "transparent background. No text, no words, no letters, no logos, no brands, no real people and no "
         "characters from films, shows or games. Subject: ")


def key() -> str:
    return (os.getenv("HQ_OPENAI_API_KEY") or "").strip()


def model() -> str:
    return (os.getenv("HQ_ETSY_IMAGE_MODEL") or "gpt-image-1").strip()


def cost_each() -> float:
    """What one picture costs, in US dollars (medium quality, 1024 x 1024)."""
    return float(os.getenv("HQ_ETSY_IMAGE_COST", "0.05") or 0.05)


def monthly_cap() -> float:
    return float(os.getenv("HQ_ETSY_IMAGE_MONTHLY", "3") or 0)


def spent_this_month() -> float:
    from .. import db
    return db.rows("SELECT COALESCE(SUM(cost_usd), 0) s FROM llm_usage WHERE model LIKE 'image:%' AND created_at >= ?",
                   ledger._start_of_month())[0]["s"]


def why_not() -> str | None:
    """Why a picture can't be made right now, or None if it can."""
    if not key():
        return "No image key (HQ_OPENAI_API_KEY), so designs are words only"
    if monthly_cap() <= 0:
        return "Pictures are switched off (HQ_ETSY_IMAGE_MONTHLY is 0)"
    if spent_this_month() + cost_each() > monthly_cap():
        return f"This month's picture budget (${monthly_cap():.2f}) is used up"
    if ledger.over_budget("etsy"):
        return "The Etsy village's budget is used up"
    return None


def make(prompt: str, out: Path) -> Path:
    """Makes one picture and saves it as a transparent PNG. Raises with a plain reason if it can't."""
    blocked = why_not()
    if blocked:
        raise RuntimeError(blocked)
    r = requests.post(API, headers={"Authorization": f"Bearer {key()}"}, timeout=180, json={
        "model": model(), "prompt": STYLE + prompt.strip()[:800], "size": "1024x1024", "quality": "medium",
        "background": "transparent", "n": 1})
    if r.status_code != 200:
        try:
            why = r.json().get("error", {}).get("message") or r.text
        except ValueError:
            why = r.text
        raise RuntimeError(f"The image tool said no ({r.status_code}): {str(why)[:200]}")
    data = r.json()["data"][0]
    out.parent.mkdir(parents=True, exist_ok=True)
    if data.get("b64_json"):
        out.write_bytes(base64.b64decode(data["b64_json"]))
    else:
        out.write_bytes(requests.get(data["url"], timeout=60).content)
    ledger.record_cost("Loom", f"image:{model()}", cost_each())
    return out
