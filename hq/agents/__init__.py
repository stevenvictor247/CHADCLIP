"""The agent roster. To add an agent, write its class and add it here."""

from .chad import Chad
from .football import Captain, Clock, Depth, Ref, Scribe, Tells
from .pitch import Pitch
from .scout import Scout
from .sweep import Sweep
from .tally import Tally

AGENTS = {a.name.lower(): a for a in [Chad(), Scout(), Pitch(), Tally(), Sweep(), Captain(), Clock(), Ref(), Tells(), Scribe(), Depth()]}


def get(name: str):
    return AGENTS.get(name.lower())
