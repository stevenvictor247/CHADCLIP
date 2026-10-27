"""Your Etsy sales file, read for free: Etsy > Shop Manager > Settings > Options > Download Data > Orders
(the "Order Items" CSV). HQ matches each row to a shirt by listing id or title and keeps the bigger sales count, so
it never double-counts orders Dock already saw in Printify."""

import csv
import io

from .. import db
from . import store


def _col(row: dict, *names) -> str:
    low = {k.strip().lower(): v for k, v in row.items() if k}
    for n in names:
        if n in low and low[n] not in (None, ""):
            return str(low[n]).strip()
    return ""


def load(data: bytes, name: str = "stats.csv") -> str:
    text = data.decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError("That file has no rows. Use Etsy's Order Items CSV (Download Data > Orders).")
    designs = store.designs(limit=2000)
    by_listing = {str(d["etsy_listing_id"]): d for d in designs if d["etsy_listing_id"]}
    by_title = {d["title"].strip().lower(): d for d in designs}
    counted, unmatched, units, revenue = {}, 0, 0, 0.0
    for r in rows:
        qty = int(float(_col(r, "quantity") or 1))
        units += qty
        try:
            revenue += float(_col(r, "price", "item total").replace("$", "").replace(",", "") or 0) * qty
        except ValueError:
            pass
        d = by_listing.get(_col(r, "listing id")) or by_title.get(_col(r, "item name", "title").lower())
        if d:
            counted[d["id"]] = counted.get(d["id"], 0) + qty
        else:
            unmatched += 1
    for did, n in counted.items():
        db.execute("UPDATE etsy_designs SET sales = MAX(sales, ?) WHERE id = ?", n, did)
    summary = (f"Etsy file {name}: {units} shirt(s) sold, about ${revenue:.2f} before fees; matched {len(counted)} "
               f"design(s)" + (f", {unmatched} row(s) didn't match a shirt HQ made" if unmatched else ""))
    store.add_note(summary, "stats")
    db.log("Etta", summary)
    return summary
