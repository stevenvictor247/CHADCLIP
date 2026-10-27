"""Dock: the loading dock. Builds approved shirts in Printify (never published) and watches for orders. Free."""

import json
import traceback

from ...etsy import printify, store, work
from ..base import Agent

PER_ROUND = 3


class Dock(Agent):
    def __init__(self):
        super().__init__(
            name="Dock",
            role="Printify manager in the Etsy village. Builds each approved shirt as a Printify product in light and "
                 "dark colours, sizes S to 3XL, ready for Steven to publish; marks shirts live once he has; and texts "
                 "him when an order is waiting. Never publishes, never sends an order to production. Free.",
            params_help='{} builds approved shirts and checks orders; {"design_id": 12} builds one now.',
            schedule=[(0.5, "Build approved shirts in Printify and check orders.", {})],
            village="etsy",
            free=True,
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        return not printify.connected()

    def run(self, task: dict) -> str:
        if not printify.connected():
            return "Nothing to do: Printify isn't connected yet (Settings, HQ_PRINTIFY_TOKEN)."
        p = json.loads(task.get("params") or "{}")
        if p.get("design_id"):
            return work.build(int(p["design_id"]))
        done = []
        for d in store.designs("approved", limit=PER_ROUND):
            try:
                done.append(work.build(d["id"]))
            except Exception as e:
                done.append(f"Couldn't build #{d['id']}: {str(e)[:160]}")
        try:
            live = work.sync_live()
            if live:
                done.append("Now live on Etsy: " + ", ".join(live))
            new = work.sync_orders()
            if new:
                done.append(f"{new} new order(s)")
        except Exception as e:
            traceback.print_exc()
            done.append(f"Couldn't read Printify: {str(e)[:160]}")
        return "\n".join(done) if done else "No new shirts to build and no new orders."
