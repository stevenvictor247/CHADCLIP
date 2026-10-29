"""The monthly clip package: 12 finished clips a month for $79, 2 revisions. Plain text and folders only; nothing here
sends, posts or charges. Steven makes the Stripe payment link himself (test mode first) and pastes it into Settings."""

import html
import re
from datetime import datetime, timezone

from .config import DATA_DIR

CLIENTS_DIR = DATA_DIR / "clients"
STRIPE_LINK = re.compile(r"^https://(buy|donate)\.stripe\.com/[A-Za-z0-9_/-]+$")


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("monthly_package"))


def _num(cfg: dict, key: str, default: int) -> int:
    try:
        return max(0, int(cfg.get(key, default)))
    except (TypeError, ValueError):
        return default


def terms(cfg: dict) -> dict:
    return {"clips": _num(cfg, "package_clips", 12), "price": _num(cfg, "package_price", 79),
            "revisions": _num(cfg, "package_revisions", 2)}


def payment_link(cfg: dict) -> str:
    """Only a real Stripe link is ever shown; anything else (a typo, a look-alike site) is ignored."""
    link = str(cfg.get("payment_link") or "").strip()
    return link if STRIPE_LINK.match(link) else ""


def offer_line(cfg: dict) -> str:
    t = terms(cfg)
    return (f"{t['clips']} finished vertical clips a month for ${t['price']}, with {t['revisions']} revisions, "
            "sent to you as a private link.")


def page(cfg: dict) -> str:
    """One simple offer page, self-contained HTML Steven can host anywhere or attach."""
    t, link = terms(cfg), payment_link(cfg)
    name = html.escape(str(cfg.get("sender_name") or "").strip() or "Your clipper")
    buy = (f'<p><a class="buy" href="{html.escape(link)}">Start for ${t["price"]} a month</a></p>' if link else
           "<p>Reply to my message and I'll send you the payment link.</p>")
    items = [f"{t['clips']} finished clips a month, cut from your best moments, captioned, ready for TikTok, YouTube Shorts and Reels",
             "A title and description for each clip",
             f"{t['revisions']} revisions per batch if something isn't right",
             "Delivered as a private link; nothing is posted without your say-so",
             "Clips come from your live streams and public clips; VODs only with your permission",
             "Cancel any time"]
    lis = "".join(f"<li>{html.escape(i)}</li>" for i in items)
    return (f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>Monthly clip package</title><style>body{{font:18px/1.5 system-ui,sans-serif;max-width:34rem;margin:2rem auto;padding:0 1rem}}"
            f".buy{{display:inline-block;background:#6441a5;color:#fff;padding:.7rem 1.2rem;border-radius:8px;text-decoration:none}}</style>"
            f"<h1>{t['clips']} clips a month for ${t['price']}</h1><ul>{lis}</ul>{buy}<p>{name}</p></html>")


def _slug(handle: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "", handle.lower())[:40]


def create_client_folder(handle: str, cfg: dict, month: str | None = None) -> str:
    """The shared delivery folder for one client: a README with the terms and a folder for this month's batch.
    Safe to repeat; existing files are never overwritten."""
    slug = _slug(handle)
    if not slug:
        raise ValueError("a client folder needs a streamer handle")
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("month must look like 2026-11")
    t = terms(cfg)
    root = CLIENTS_DIR / slug
    batch = root / f"batch-{month}"
    (batch / "clips").mkdir(parents=True, exist_ok=True)
    (batch / "revisions").mkdir(exist_ok=True)
    readme = root / "README.txt"
    if not readme.exists():
        readme.write_text(
            f"Clip package for {handle}\n\n{offer_line(cfg)}\n\n"
            "Each month has its own folder: batch-YYYY-MM/clips holds the finished clips with titles, "
            f"batch-YYYY-MM/revisions holds requested changes ({t['revisions']} per batch).\n"
            "Steven approves each batch before the link goes to the streamer.\n"
            "VOD clips are only cut once the streamer has given permission.\n", encoding="utf-8")
    return str(batch)
