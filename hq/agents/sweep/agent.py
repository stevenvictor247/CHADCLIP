"""Sweep: the janitor. Keeps Claude costs down, tidies up after the other agents and reports once a day."""

import json

from ... import sweep
from ..base import Agent


class Sweep(Agent):
    def __init__(self):
        super().__init__(
            name="Sweep",
            role="The janitor. Watches what Claude costs, tidies up after the other agents (stuck jobs, old files, "
                 "big logs), fixes the safe problems by itself and sends you one cost report a day.",
            params_help='{"report": true} to send the daily report right now. Sweep never posts, emails, spends '
                        'money or changes settings without your approval.',
            schedule=[(6, "Tidy up and check what Claude is costing.", {})],
            free=True,
        )

    def run(self, task: dict) -> str:
        params = json.loads(task.get("params") or "{}")
        return sweep.run(force_report=bool(params.get("report")))
