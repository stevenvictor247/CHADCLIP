"""The agent roster. To add an agent, write its class and add it here."""

from .chad import Chad
from .scout import Scout

AGENTS = {a.name.lower(): a for a in [Chad(), Scout()]}


def get(name: str):
    return AGENTS.get(name.lower())
