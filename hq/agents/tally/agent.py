"""Tally: the counting house. Reads view counts for posted clips and tells Chad what worked."""

from ... import tally
from ..base import Agent


class Tally(Agent):
    def __init__(self):
        super().__init__(
            name="Tally",
            role="The counter. Reads the views on every posted clip, fills in campaign submissions, works out what "
                 "the campaigns should pay, and tells Chad which clips did best so he picks better moments.",
            params_help="No params: count views now. Tally only reads numbers; it never posts or changes anything "
                        "on your accounts.",
            schedule=[(12, "Count views on posted clips.", {})],
            free=True,  # reads platform numbers only; never calls Claude
        )

    def run(self, task: dict) -> str:
        return tally.run()
