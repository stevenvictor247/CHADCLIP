"""Packs: a $49 podcast clip pack, 5 captioned vertical clips plus titles and post ideas from one episode."""

import json

from ... import packs
from ..base import Agent


class Packs(Agent):
    def __init__(self):
        super().__init__(
            name="Packs",
            role="Podcast clip packs. Cuts 5 captioned vertical clips from one episode a podcaster gave you, and adds "
                 "Recap's titles, description, chapters and post ideas. Steven approves the pack, then sends the files himself.",
            params_help='{"client": "podcast name", "owner": "how they gave you the episode, e.g. emailed it 26 Oct, said yes to clips", '
                        '"file": "path to the episode video file"}. Only for episodes its owner handed over. Packs never sends anything.',
        )

    def run(self, task: dict) -> str:
        try:
            return packs.make(json.loads(task.get("params") or "{}"))
        except packs.PackError as e:
            return str(e)
