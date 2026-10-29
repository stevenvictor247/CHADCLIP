"""Queue: counts today's pitches against the daily goal and texts Steven when too few are ready. No Claude."""

from ... import pitchqueue
from ..base import Agent


class Queue(Agent):
    def __init__(self):
        super().__init__(
            name="Queue",
            role="The quota keeper. Counts today's drafted, approved and sent pitches against the daily goal, orders the "
                 "unsent drafts by Pitch's lead score for the Today's 10 screen, and texts you at a set time if fewer "
                 "than the goal are ready. It never sends anything; you send each pitch yourself.",
            params_help="No params: check the quota now and text you if it's short. Queue only reads the leads table.",
            schedule=[(1, "Check today's pitch quota.", {})],
            free=True,  # plain rules in code; never calls Claude
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        return not pitchqueue.alert_due()

    def run(self, task: dict) -> str:
        return pitchqueue.check_and_alert()
