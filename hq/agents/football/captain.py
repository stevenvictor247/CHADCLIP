"""Captain: runs Warrior Village. The Boss hands Captain anything football; Captain knows your rulebook and terms,
hands work to Clock, Ref, Tells and Scribe, and answers football questions from what's actually in HQ."""

import json

from ... import football, ledger, llm
from ...config import model_for
from ...football import notebook, rulebook, season
from ..base import Agent

SYSTEM = """You are Captain, who runs Warrior Village: the football agents helping Steven, a graduate assistant on
Wayne State's defensive staff. Your team: Clock (game-week checklist and reminders), Ref (checks tagged sheets),
Tells (scouting report and Birds and Rabbits from a tagged sheet) and Scribe (Coaching Notebook).

How you work:
- Use the tools to do what Steven asked, then answer in a few short lines. Tells first, short bullets.
- Never invent stats, players, plays or tendencies. Numbers only come from Tells' counts or Ref's checks.
- Steven's Hudl tags beat anything else. If something conflicts with them, flag it.
- Nothing goes to a coach, Hudl or Teamworks from here. Reports wait in Approvals; sending is Steven's job.
- If he uses a term you don't know, or one the rulebook marks undefined, ask him.
- Steven's rulebook is inside <rulebook> tags. It's his reference, use its terms."""

TOOLS = [
    {"name": "football_status", "description": "This game week (opponent, date, checklist, late items), sheets in the "
     "football Inbox with Ref's results, approvals waiting, notebook size, today's football spend.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "mark_done", "description": "Tick a checklist item done (or not done) for this week, or another opponent's week.",
     "input_schema": {"type": "object", "properties": {"item": {"type": "string"}, "done": {"type": "boolean"},
                      "opponent": {"type": "string"}}, "required": ["item"], "additionalProperties": False}},
    {"name": "set_game", "description": "Save a game's date (YYYY-MM-DD), kickoff time or site (home, away, neutral).",
     "input_schema": {"type": "object", "properties": {"opponent": {"type": "string"}, "date": {"type": "string"},
                      "kickoff": {"type": "string"}, "site": {"type": "string"}}, "required": ["opponent"],
                      "additionalProperties": False}},
    {"name": "set_due", "description": "Change when a checklist item is due: days_before game day (Saturday game: 6 = "
     "Sunday, 5 = Monday, 4 = Tuesday, 3 = Wednesday) or a weekday. add=true makes a new item, remove=true drops one.",
     "input_schema": {"type": "object", "properties": {"item": {"type": "string"}, "days_before": {"type": "integer"},
                      "weekday": {"type": "string"}, "add": {"type": "boolean"}, "remove": {"type": "boolean"}},
                      "required": ["item"], "additionalProperties": False}},
    {"name": "check_sheet", "description": "Have Ref check a sheet in the football Inbox now. Returns Ref's result.",
     "input_schema": {"type": "object", "properties": {"file": {"type": "string"}}, "required": ["file"],
                      "additionalProperties": False}},
    {"name": "build_report", "description": "Have Tells build the scouting report and Birds and Rabbits from a sheet. "
     "It waits in Approvals for Steven.",
     "input_schema": {"type": "object", "properties": {"file": {"type": "string"}, "opponent": {"type": "string"}},
                      "required": ["file"], "additionalProperties": False}},
    {"name": "add_note", "description": "File something Steven learned in the Coaching Notebook (Scribe).",
     "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"],
                      "additionalProperties": False}},
    {"name": "search_notebook", "description": "Search the Coaching Notebook.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"],
                      "additionalProperties": False}},
]


def _tool(name: str, args: dict):
    from .ref import check_file
    from .scribe import note
    from .tells import build
    if name == "football_status":
        return football.status()
    if name == "mark_done":
        return season.mark(args["item"], args.get("done", True), args.get("opponent"))
    if name == "set_game":
        return season.set_game(args["opponent"], args.get("date"), args.get("kickoff"), args.get("site"))
    if name == "set_due":
        return season.set_due(args["item"], args.get("days_before"), args.get("weekday"), bool(args.get("add")),
                              bool(args.get("remove")))
    if name == "check_sheet":
        return check_file(args["file"])
    if name == "build_report":
        return build(args["file"], args.get("opponent"))
    if name == "add_note":
        return note(args["text"], source="boss")
    if name == "search_notebook":
        return [{"id": n["id"], "tab": n["tab"], "entry": notebook.shown(n)} for n in notebook.search(args["query"])]
    raise ValueError(f"No tool {name}")


def ask(text: str) -> str:
    if not llm.HAS_LLM:
        return "Claude is off, so here's the football status:\n" + json.dumps(football.status(), indent=1, default=str)
    if ledger.over_budget("football"):
        return "Today's football budget is spent, so I'm paused until tomorrow. Clock, Ref and Tells still work."
    system = SYSTEM + f"\n\n<rulebook>\n{rulebook.text()}\n</rulebook>"
    messages = [{"role": "user", "content": text}]
    for _ in range(10):
        response = llm.create(model_for("Captain"), system, messages, tools=TOOLS, effort="medium", max_tokens=6000,
                              agent="Captain")
        content = [b.model_dump(mode="json", exclude_none=True) for b in response.content]
        messages.append({"role": "assistant", "content": content})
        calls = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason != "tool_use" or not calls:
            return llm.text_of(response) or "Done."
        results = []
        for call in calls:
            try:
                out, err = json.dumps(_tool(call.name, call.input), default=str), False
            except Exception as e:
                out, err = f"Error: {e}", True
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": out, "is_error": err})
        messages.append({"role": "user", "content": results})
    return "I hit my step limit on that one. Ask again in smaller pieces."


class Captain(Agent):
    def __init__(self):
        super().__init__(
            name="Captain",
            role="Runs Warrior Village, the football side. Knows your terms and rules, hands football work to Clock, "
                 "Ref, Tells and Scribe, and answers football questions.",
            params_help="Plain-words instructions about anything football. No params needed.",
            village="football",
            notify_when_done=True,
        )

    def run(self, task: dict) -> str:
        return ask(task.get("instructions", ""))
