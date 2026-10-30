"""The agent roster. To add an agent, write its class and add it here."""

from .chad import Chad
from .closer import Closer
from .etsy import Dock, Etta, Loom, Quill, Radar, Warden
from .football import Captain, Clock, Depth, Ref, Scribe, Tells
from .gate import Gate
from .muse import Muse
from .nudge import Nudge
from .pitch import Pitch
from .packs import Packs
from .rally import Rally
from .queue import Queue
from .recap import Recap
from .recruiter import Recruiter
from .rerun import Rerun
from .scout import Scout
from .sweep import Sweep
from .tally import Tally
from .trim import Trim

AGENTS = {a.name.lower(): a for a in [Chad(), Scout(), Pitch(), Queue(), Nudge(), Rerun(), Closer(), Recap(), Packs(), Tally(), Gate(), Trim(), Sweep(), Muse(), Recruiter(), Captain(), Clock(), Ref(), Tells(), Scribe(), Depth(), Rally(),
                                     Etta(), Radar(), Quill(), Loom(), Warden(), Dock()]}


def get(name: str):
    return AGENTS.get(name.lower())
