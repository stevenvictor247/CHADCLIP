"""Queue: counts today's pitches against the daily goal and builds the send list."""


from ... import dailyqueue
from ..base import Agent


class Queue(Agent):
    def __init__(self):
        super().__init__(
            name="Queue",
            role="The send-list builder. Counts today's drafted, approved and sent pitches against the goal of 10 "
                 "new streamers a day, puts the best fit first, and texts Steven if fewer than 10 are ready. "
                 "Rules only, no Claude. Stays quiet while Pitch is paused.",
            params_help="No params: count now. Queue never sends anything; Steven copies each pitch and taps Mark sent.",
            schedule=[(1, "Check today's pitch quota.", {})],
            free=True,
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        return not dailyqueue.alert_due()   # paused, already texted today, or too early: no round at all

    def run(self, task: dict) -> str:
        return dailyqueue.run()
