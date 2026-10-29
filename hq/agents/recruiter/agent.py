"""Recruiter: finds the holes in how HQ runs and proposes new agents to fill them."""

import json

from ... import recruiter
from ..base import Agent


class Recruiter(Agent):
    def __init__(self):
        super().__init__(
            name="Recruiter",
            role="The hiring manager. Reads what Sweep and Muse found, looks for holes in how HQ runs, and proposes "
                 "new agents to fill them. Each proposal comes with a 1 to 10 rating, what it costs to run and the gap "
                 "it fixes, and waits in Approvals. About 2 a day (4 if Recruiter is cheap to run, 1 if it is expensive).",
            params_help='No params: look for gaps now. Recruiter only proposes; it never builds, buys or starts '
                        'anything. "Build it" on an approved proposal uses the same flow as Muse\'s ideas.',
            schedule=[(1, "Check HQ for gaps that a new agent could fill.", {})],
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        """Free look in code: a round only happens when it's a new day, there's room and the money caps allow it."""
        return recruiter.why_not_now(manual=bool(params.get("manual"))) is not None

    def run(self, task: dict) -> str:
        params = json.loads(task.get("params") or "{}")
        return recruiter.run(manual=bool(params.get("manual")))
