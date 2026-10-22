"""The agent roster. To add an agent, write its class and add it here."""

from .chad import Chad
from .football import Captain, Clock, Ref, Scribe, Tells
from .pitch import Pitch
from .scout import Scout
from .sweep import Sweep

AGENTS = {a.name.lower(): a for a in [Chad(), Scout(), Pitch(), Sweep(), Captain(), Clock(), Ref(), Tells(), Scribe()]}


def get(name: str):
    return AGENTS.get(name.lower())
