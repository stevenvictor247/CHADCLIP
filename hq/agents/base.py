"""What every agent looks like to the Boss."""

from dataclasses import dataclass, field


@dataclass
class Agent:
    name: str
    role: str
    # What the Boss may put in a task's params, shown to the Boss when it assigns work.
    params_help: str = ""
    # Tasks the agent should run on its own schedule, as (every_hours, instructions, params).
    schedule: list = field(default_factory=list)

    def run(self, task: dict) -> str:
        """Do one task and return a short summary for the Boss."""
        raise NotImplementedError
