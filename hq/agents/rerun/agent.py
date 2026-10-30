"""Rerun: drafts a short second try for pitched leads that went quiet. Steven sends each one himself."""

from ... import rerun
from ..base import Agent


class Rerun(Agent):
    def __init__(self):
        super().__init__(
            name="Rerun",
            role="The second-try writer. Takes leads Nudge marked quiet, ranks them by followers and oldest pitch, and "
                 "drafts a 3-line second message with a different free clip idea, at most 5 a day. Two tries per lead, "
                 "then the lead is marked dead. Rules choose who and when; Claude only writes the short draft. "
                 "Nothing is sent: you copy each one and tap Mark sent.",
            params_help="No params: draft today's second tries now.",
            schedule=[(6, "Draft second tries for quiet leads.", {})],
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        return not rerun.worth_running()   # paused, nobody quiet, or today's cap reached: no round, no Claude

    def run(self, task: dict) -> str:
        return rerun.run()
