"""Muse: the Creative Director. Thinks up new businesses, new agents and add-ons, ranks them and brings the best to
Approvals."""

import json

from ... import muse
from ..base import Agent


class Muse(Agent):
    def __init__(self):
        super().__init__(
            name="Muse",
            role="The Creative Director. Once a week Muse looks at how HQ is doing and thinks up new ways to make "
                 "money and run better: new businesses, new agents, add-ons to what HQ already does and HQ upgrades. "
                 "Each idea comes ranked, with what it costs, how much work it is and what it could earn. The best "
                 "ones wait in Approvals; \"Build it\" gives you a brief to hand to Claude.",
            params_help='No params: think up new ideas now. {"focus": "what to think about"} to aim the ideas, e.g. '
                        '{"focus": "ways to earn from the clipping accounts"}. Muse only suggests; it never builds, '
                        'buys, posts or signs up for anything.',
            schedule=[(24, "Think up new ideas to grow HQ.", {"brainstorm": True})],
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        """Free look in code: the weekly round only happens when it's been a week, the ideas from last time have been
        answered, and the money caps allow it. Otherwise no task, no Claude call."""
        if params.get("brainstorm"):
            muse.mark_built_agents()
            return muse.why_not_now() is not None
        return None

    def run(self, task: dict) -> str:
        params = json.loads(task.get("params") or "{}")
        scheduled = task.get("created_by") == "Schedule" and params.get("brainstorm")
        return muse.run(focus=params.get("focus"), manual=not scheduled)
