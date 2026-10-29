"""Trim: keeps the approved-clip queue fresh, best first."""

from ... import trim
from ..base import Agent


class Trim(Agent):
    def __init__(self):
        super().__init__(
            name="Trim",
            role="The queue trimmer. Ranks the approved clips by how fresh they are and how well each creator's clips "
                 "did (from Tally), posts the best first, and offers clips waiting over a week for a one-tap drop. "
                 "Rules only, no Claude.",
            params_help="No params: rank the queue now. Trim never posts, sends or spends; the first reorder waits for "
                        "your OK, and every reorder can be undone.",
            schedule=[(6, "Rank the clip queue.", {})],
            free=True,
        )

    def run(self, task: dict) -> str:
        return trim.run()
