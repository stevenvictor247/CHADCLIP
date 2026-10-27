"""Warden: the rule gate. Checks every shirt and listing against Etsy's rules before it goes anywhere. Free."""

import json

from ...etsy import store, work
from ..base import Agent


class Warden(Agent):
    def __init__(self):
        super().__init__(
            name="Warden",
            role="Rule checker in the Etsy village. Holds any design that names a brand, team, school, character or "
                 "famous person, fixes tags and titles to Etsy's limits, adds the production-partner and AI lines, and "
                 "sends designs to Approvals (the first few, and any with warnings). Plain rules, no AI, so free.",
            params_help='{} checks the drawn designs; {"design_id": 12} checks one again.',
            schedule=[(0.25, "Check the drawn shirt designs.", {})],
            village="etsy",
            free=True,
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        return not store.designs("drawn", limit=1)

    def run(self, task: dict) -> str:
        p = json.loads(task.get("params") or "{}")
        if p.get("design_id"):
            return work.check(int(p["design_id"]))
        todo = store.designs("drawn", limit=20)
        if not todo:
            return "Nothing to check."
        return "\n".join(work.check(d["id"]) for d in todo)
