"""The agent roster. To add an agent, write its class and add it here."""

from .chad import Chad
from .football import Captain, Clock, Depth, Ref, Scribe, Tells
from .muse import Muse
from .pitch import Pitch
from .packs import Packs
from .recap import Recap
from .scout import Scout
from .sweep import Sweep
from .tally import Tally

AGENTS = {a.name.lower(): a for a in [Chad(), Scout(), Pitch(), Recap(), Packs(), Tally(), Sweep(), Muse(), Captain(), Clock(), Ref(), Tells(), Scribe(), Depth()]}


def get(name: str):
    return AGENTS.get(name.lower())
