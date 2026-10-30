"""Lens: works out why posted clips get few views, and writes Steven a one-page fix list."""

from ... import lens
from ..base import Agent


class Lens(Agent):
    def __init__(self):
        super().__init__(
            name="Lens",
            role="The why-detective. Reads what Tally counted for each posted clip and flags accounts with no reach, "
                 "odd posting hours, missing hashtags and repeated captions, as a short fix list on the dashboard. "
                 "Messages you on Telegram when an account gets zero views for 3 days. Rules only, no Claude; it never "
                 "changes an account or a post.",
            params_help="No params: look at the posted clips now and refresh the fix list.",
            schedule=[(24, "Find out why clips get few views.", {})],
            free=True,
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        return not lens.worth_checking()

    def run(self, task: dict) -> str:
        return lens.run()
