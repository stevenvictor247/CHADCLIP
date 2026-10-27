"""Loom: the design studio. Draws each written shirt into print files, free (plus an optional picture)."""

import json

from ...etsy import store, work
from ..base import Agent

PER_ROUND = 3


class Loom(Agent):
    def __init__(self):
        super().__init__(
            name="Loom",
            role="Shirt designer in the Etsy village. Turns Quill's words into print-ready art (4500 x 5400, "
                 "transparent): a dark-ink version for light shirts and a light-ink one for dark shirts, plus a "
                 "preview on a shirt. Adds a picture when the image key is set. Free unless a picture is made.",
            params_help='{} draws the next written designs; {"design_id": 12} redraws one design.',
            schedule=[(0.25, "Draw the written shirt designs.", {})],
            village="etsy",
            free=True,
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        return not store.designs("written", limit=1)

    def run(self, task: dict) -> str:
        p = json.loads(task.get("params") or "{}")
        if p.get("design_id"):
            return work.draw(int(p["design_id"]))
        todo = store.designs("written", limit=PER_ROUND)
        if not todo:
            return "Nothing to draw."
        return "\n".join(work.draw(d["id"]) for d in todo)
