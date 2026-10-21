"""The agent roster. To add an agent, write its class and add it here."""

from .chad import Chad
from .pitch import Pitch
from .scout import Scout

AGENTS = {a.name.lower(): a for a in [Chad(), Scout(), Pitch()]}


def get(name: str):
    return AGENTS.get(name.lower())
