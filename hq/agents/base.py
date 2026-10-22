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
    # Which village in HQ Town the agent lives in: "business" or "football". Each village has its own budget.
    village: str = "business"
    # Send the task's result to your phone when it finishes (football asks can take a minute).
    notify_when_done: bool = False

    # Housekeeping agents that cost nothing in Claude: their scheduled jobs still run when the day's budget is spent.
    free: bool = False

    def run(self, task: dict) -> str:
        """Do one task and return a short summary for the Boss."""
        raise NotImplementedError
