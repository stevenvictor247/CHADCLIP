"""Gate: checks waiting clips against Steven's past approvals and rejections."""

from ... import gate
from ..base import Agent


class Gate(Agent):
    def __init__(self):
        super().__init__(
            name="Gate",
            role="The doorman. Scores each waiting clip from your past approvals and rejections (creator, length, "
                 "caption, title), holds the likely rejects in their own tab and puts the best clips first. It only "
                 "sorts: you still approve or reject every clip.",
            params_help="No params: score the waiting clips now.",
            schedule=[(6, "Score the waiting clips.", {})],
            free=True,  # plain rules in code; never calls Claude
        )

    def run(self, task: dict) -> str:
        return gate.run()
