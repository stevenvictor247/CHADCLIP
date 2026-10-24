"""Sweep: the janitor and quality control. Keeps Claude costs down, tidies up after the other agents, and once a day
reports how HQ could run better."""

import json

from ... import sweep
from ..base import Agent


class Sweep(Agent):
    def __init__(self):
        super().__init__(
            name="Sweep",
            role="The janitor and quality control. Watches what Claude costs, tidies up after the other agents (stuck "
                 "jobs, old files, big logs) and fixes the safe problems by itself. Once a day it checks every agent's "
                 "work and sends a \"How to improve HQ\" report: a health score, the top things to do, and one-tap "
                 "fixes for the safe ones.",
            params_help='{"report": true} to send the daily report right now. Sweep never posts, emails, spends '
                        'money or changes settings without your approval.',
            schedule=[(6, "Tidy up and check what Claude is costing.", {})],
            free=True,   # rules only; its one coach's note a day is skipped once the budget is spent
        )

    def run(self, task: dict) -> str:
        params = json.loads(task.get("params") or "{}")
        return sweep.run(force_report=bool(params.get("report")))
