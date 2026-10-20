"""The agent roster. To add an agent, write its class and add it here."""

from .chad import Chad

AGENTS = {a.name.lower(): a for a in [Chad()]}


def get(name: str):
    return AGENTS.get(name.lower())
