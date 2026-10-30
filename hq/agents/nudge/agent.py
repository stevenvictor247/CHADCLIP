"""Nudge: watches your Gmail inbox for replies to Pitch emails and tells you who answered, who bounced and who went quiet."""

from ... import mailwatch
from ..base import Agent


class Nudge(Agent):
    def __init__(self):
        super().__init__(
            name="Nudge",
            role="The reply watcher. Reads your Gmail inbox (read-only, nothing is ever sent or changed) for answers from "
                 "leads Pitch emailed, marks each lead replied, bounced or quiet after 5 days, and puts every reply on "
                 "your phone with a Draft quote button. Rules only, no Claude.",
            params_help="No params: check the inbox now. Needs the same Gmail address and app password Pitch uses (IMAP on).",
            schedule=[(4, "Check Gmail for replies to pitches.", {})],
            free=True,
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        return not mailwatch.worth_checking()   # no Gmail login, or no pitched lead to watch: no round at all

    def run(self, task: dict) -> str:
        return mailwatch.run()
