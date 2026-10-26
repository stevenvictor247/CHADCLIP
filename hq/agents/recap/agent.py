"""Recap: titles, descriptions, chapters and post ideas for a streamer's long videos."""

import json

from ... import recap
from ..base import Agent


class Recap(Agent):
    def __init__(self):
        super().__init__(
            name="Recap",
            role="Pack maker. Turns a long VOD or podcast transcript into a ready-to-paste pack: 3 title options, a "
                 "description, chapter timestamps and 5 post ideas. Steven approves every pack, then sends it himself.",
            params_help='{"client": "streamer name", "owner": "how they handed you the video, e.g. emailed it 26 Oct", '
                        '"file": "path to a .txt/.srt/.vtt transcript or an audio/video file"} or {"transcript": "[0:00:05] words..."} '
                        'instead of file. Only for content its owner gave you. Recap never sends anything.',
        )

    def run(self, task: dict) -> str:
        try:
            return recap.make(json.loads(task.get("params") or "{}"))
        except recap.RecapError as e:
            return str(e)
