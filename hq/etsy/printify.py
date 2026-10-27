"""Printify: where Dock builds each approved design into a shirt product, ready for you to publish to Etsy.

What HQ does here: reads your shops, the shirt catalog and your orders, uploads print files and creates products.
What HQ never does: publish a product to Etsy, send an order to production (that charges your card), or change an
order. Those are your taps in Printify. The request helper below only allows the two kinds of writes HQ needs, so a
mistake elsewhere in the code can't turn into a publish or a charge.

Settings: HQ_PRINTIFY_TOKEN (Printify > My account > Connections > API tokens), and optionally HQ_PRINTIFY_SHOP_ID,
HQ_PRINTIFY_BLUEPRINT (12 = Bella+Canvas 3001 unisex tee) and HQ_PRINTIFY_PROVIDER.
"""

import base64
import os
import re
from pathlib import Path

import requests

BASE = "https://api.printify.com/v1"
# The only writes HQ may make: upload an image, create a product. Anything else is refused before it is sent.
ALLOWED_WRITES = [re.compile(r"^/uploads/images\.json$"), re.compile(r"^/shops/\d+/products\.json$")]

LIGHT_SHIRTS = ["White", "Natural", "Soft Cream", "Athletic Heather", "Heather Dust", "Ash", "Heather Peach"]
DARK_SHIRTS = ["Black", "Navy", "Dark Grey Heather", "Heather Forest", "Maroon", "Heather Navy", "Black Heather"]
SIZES = ["S", "M", "L", "XL", "2XL", "3XL"]
UPCHARGE = {"2XL": 200, "3XL": 400}   # cents added for the big sizes, which cost Printify more


class PrintifyError(RuntimeError):
    pass


def token() -> str:
    return (os.getenv("HQ_PRINTIFY_TOKEN") or "").strip()


def connected() -> bool:
    return bool(token())


def blueprint() -> int:
    return int(os.getenv("HQ_PRINTIFY_BLUEPRINT", "12") or 12)


def _call(method: str, path: str, **kw):
    if not connected():
        raise PrintifyError("Printify isn't connected: paste your API token in Settings (HQ_PRINTIFY_TOKEN)")
    if method != "GET" and not any(p.match(path) for p in ALLOWED_WRITES):
        raise PrintifyError(f"HQ is not allowed to {method} {path} on Printify")
    r = requests.request(method, BASE + path, timeout=60, **kw, headers={
        "Authorization": f"Bearer {token()}", "User-Agent": "CHADCLIP-HQ", "Content-Type": "application/json"})
    if r.status_code == 401:
        raise PrintifyError("Printify turned the token down: make a new one and paste it in Settings")
    if r.status_code >= 400:
        raise PrintifyError(f"Printify said {r.status_code}: {r.text[:300]}")
    return r.json()


def shops() -> list[dict]:
    return _call("GET", "/shops.json")


def shop_id() -> int:
    chosen = (os.getenv("HQ_PRINTIFY_SHOP_ID") or "").strip()
    if chosen:
        return int(chosen)
    found = shops()
    if not found:
        raise PrintifyError("Your Printify account has no shop yet: connect your Etsy shop in Printify first")
    etsy = [s for s in found if str(s.get("sales_channel", "")).lower() == "etsy"]
    return int((etsy or found)[0]["id"])


def test() -> str:
    """For the Test button: says which shop Dock will use."""
    found = shops()
    if not found:
        return "Connected, but there's no shop yet. In Printify, connect your Etsy shop."
    sid = shop_id()
    name = next((s.get("title") for s in found if int(s["id"]) == sid), sid)
    channel = next((s.get("sales_channel") for s in found if int(s["id"]) == sid), "")
    return f"Connected. Dock will use the shop \"{name}\"" + (f" ({channel})." if channel else ".")


def provider() -> int:
    chosen = (os.getenv("HQ_PRINTIFY_PROVIDER") or "").strip()
    if chosen:
        return int(chosen)
    found = _call("GET", f"/catalog/blueprints/{blueprint()}/print_providers.json")
    if not found:
        raise PrintifyError(f"No print provider makes blueprint {blueprint()}")
    choice = [p for p in found if "choice" in str(p.get("title", "")).lower()]
    return int((choice or found)[0]["id"])


def pick_variants(variants: list[dict]) -> dict:
    """Splits the catalog's variants into light shirts (dark ink) and dark shirts (light ink): up to 4 colours each,
    sizes S to 3XL. Returns {"light": [variant, ...], "dark": [...]}."""
    out = {}
    for shade, colours in (("light", LIGHT_SHIRTS), ("dark", DARK_SHIRTS)):
        have = []
        for c in colours:
            match = [v for v in variants if str(v.get("options", {}).get("color", "")).lower() == c.lower()
                     and v.get("options", {}).get("size") in SIZES]
            if match:
                have.append(match)
            if len(have) == 4:
                break
        out[shade] = [v for group in have for v in group]
    return out


def upload(path: Path) -> str:
    data = base64.b64encode(Path(path).read_bytes()).decode()
    return _call("POST", "/uploads/images.json", json={"file_name": Path(path).name, "contents": data})["id"]


def create_product(design: dict) -> str:
    """Builds the shirt as a Printify product (not published). Returns the product id."""
    bp, pp, sid = blueprint(), provider(), shop_id()
    catalog = _call("GET", f"/catalog/blueprints/{bp}/print_providers/{pp}/variants.json")
    groups = pick_variants(catalog.get("variants", []))
    if not groups["light"] and not groups["dark"]:
        raise PrintifyError("Couldn't find any shirt colours to offer from that print provider")
    files = design["files"]
    image = {"light": upload(Path(files["dark"])), "dark": upload(Path(files["light"]))}   # dark ink on light shirts
    variants, areas = [], []
    for shade in ("light", "dark"):
        ids = [v["id"] for v in groups[shade]]
        for v in groups[shade]:
            variants.append({"id": v["id"], "is_enabled": True,
                             "price": int(design["price_cents"]) + UPCHARGE.get(v["options"]["size"], 0)})
        if ids:
            areas.append({"variant_ids": ids, "placeholders": [{"position": "front", "images": [
                {"id": image[shade], "x": 0.5, "y": 0.5, "scale": 1, "angle": 0}]}]})
    body = {"title": design["title"], "description": design["description"], "blueprint_id": bp,
            "print_provider_id": pp, "variants": variants, "print_areas": areas, "tags": design["tags"]}
    return str(_call("POST", f"/shops/{sid}/products.json", json=body)["id"])


def product(product_id: str) -> dict:
    return _call("GET", f"/shops/{shop_id()}/products/{product_id}.json")


def listing_of(product_id: str) -> str | None:
    """The Etsy listing id once you've published the product, else None."""
    ext = product(product_id).get("external") or {}
    return str(ext["id"]) if ext.get("id") else None


def orders(limit: int = 20) -> list[dict]:
    """Recent orders, newest first, in HQ's own shape."""
    data = _call("GET", f"/shops/{shop_id()}/orders.json", params={"limit": limit}).get("data", [])
    out = []
    for o in data:
        items = [{"title": (li.get("metadata") or {}).get("title", ""), "quantity": li.get("quantity", 1),
                  "product_id": li.get("product_id")} for li in o.get("line_items", [])]
        cost = sum(int(li.get("cost") or 0) + int(li.get("shipping_cost") or 0) for li in o.get("line_items", []))
        out.append({"id": str(o["id"]), "status": o.get("status", ""), "total_cents": int(o.get("total_price") or 0),
                    "cost_cents": cost, "items": items, "created_at": o.get("created_at", "")})
    return out


def app_link(product_id: str | None = None) -> str:
    """Where to click in Printify."""
    return "https://printify.com/app/products" if product_id else "https://printify.com/app/orders"
