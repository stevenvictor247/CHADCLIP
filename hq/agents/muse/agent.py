"""Muse: the Creative Director. Thinks up new businesses, new agents and add-ons, ranks them and brings the best to
Approvals."""

import json

from ... import muse
from ..base import Agent


class Muse(Agent):
    def __init__(self):
        super().__init__(
            name="Muse",
            role="The Creative Director. Once a week the Boss sends Muse to look at how HQ is doing and think up "
                 "new ways to make money and run better: new businesses, new agents, add-ons to what HQ already does and HQ upgrades. "
                 "Each idea comes ranked, with what it costs, how much work it is and what it could earn. The best "
                 "ones wait in Approvals; \"Build it\" gives you a brief to hand to Claude.",
            params_help='No params: think up new ideas now. {"focus": "what to think about"} to aim the ideas, e.g. '
                        '{"focus": "ways to earn from the clipping accounts"}. Muse only suggests; it never builds, '
                        'buys, posts or signs up for anything.',
            # The weekly round itself is sent by the Boss (boss.WEEKLY_ORDERS). This only picks its ideas up from
            # Claude's half-price queue, and costs nothing until they are there.
            schedule=[(0.25, "Pick up the weekly ideas from Claude's queue.", {"collect": True})],
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        """Free look in code: the weekly round only happens when it's been a week, there's room for new ideas, and the
        money caps allow it; the pick-up only when the queue has finished. Otherwise no task, no Claude call."""
        if params.get("collect"):
            return not muse.batch_ready()
        if params.get("weekly") or params.get("brainstorm"):
            muse.mark_built_agents()
            return muse.why_not_now() is not None
        return None

    def run(self, task: dict) -> str:
        params = json.loads(task.get("params") or "{}")
        if params.get("collect"):
            return muse.collect()
        weekly = params.get("weekly") or (params.get("brainstorm") and task.get("created_by") in ("Schedule", "Boss"))
        return muse.run(focus=params.get("focus"), manual=not weekly)
