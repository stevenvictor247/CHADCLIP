"""Rally: drafts Saturday college football posts from public stats. Steven approves each one and posts it himself."""

import json

from ... import rally
from ..base import Agent


class Rally(Agent):
    def __init__(self):
        super().__init__(
            name="Rally",
            role="The Saturday college football account. Drafts short text-and-card posts for TikTok and Shorts from "
                 "public rankings and stats (upset watch, rivalry history, weekly stat facts). No school logos, no game "
                 "film. Every post waits in Approvals; Rally never posts anything.",
            params_help='No params: draft this week\'s posts from the public rankings. {"facts": ["Team A is ranked 3rd '
                        'in the AP poll", ...]} to draft from facts you pasted. {"views": {"id": 4, "views": 1200}} to '
                        'tell Rally how a post did after you posted it ("report": true shows which topics work).',
            schedule=[(24, "Draft this week's college football posts.", {"weekly": True})],
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        if params.get("weekly"):
            return rally.why_not_now() is not None
        return None

    def run(self, task: dict) -> str:
        params = json.loads(task.get("params") or "{}")
        if params.get("views"):
            return rally.record_views(int(params["views"]["id"]), int(params["views"]["views"]))
        if params.get("report"):
            return rally.topic_report()
        try:
            return rally.draft(params)
        except rally.RallyError as e:
            return str(e)
