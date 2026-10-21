"""The Boss: Steven's right hand. Takes direction, assigns work to the agents, and reports back."""

import hashlib
import json
import threading

from . import agents, db, llm
from .config import BOSS_MODEL, VISION_PATH

SYSTEM = """You are the Boss, the head of an AI agent team that runs parts of Steven's online business.
Steven is the owner. You turn his direction into concrete tasks for the agents, keep an eye on their work,
and report back to him plainly and briefly.

How you work:
- Steven's current vision arrives inside <vision> tags. It is the standing direction for everything you do.
- Delegate with assign_task. Give each agent clear, specific instructions and the params it understands.
  Agents run tasks in the background; tell Steven what you assigned rather than waiting for results.
- Use get_status and list_pending_clips to answer questions about what the team is doing. Never invent numbers.
- Anything that posts publicly, spends money or contacts people needs Steven's approval. Only call decide_clip
  when Steven has explicitly told you, in this conversation, to approve or reject those specific clips.
- When Steven states a lasting preference or goal, save it with remember so it becomes part of the vision.
- If he asks for something no agent can do yet, say so and suggest what agent would handle it.
- Reply in short, plain sentences. No filler."""

TOOLS = [
    {"name": "list_agents", "description": "List the agents on the team, their roles and what params their tasks accept.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "assign_task", "description": "Queue a task for an agent. Returns the task id.",
     "input_schema": {"type": "object", "properties": {
         "agent": {"type": "string", "description": "Agent name, e.g. Chad"},
         "instructions": {"type": "string", "description": "What the agent should do, in plain words"},
         "params": {"type": "object", "description": "Structured params the agent understands (see list_agents)"}},
         "required": ["agent", "instructions"], "additionalProperties": False}},
    {"name": "get_status", "description": "Recent tasks, clip counts, recent posts and the latest team activity.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "list_pending_clips", "description": "Clips waiting for Steven's approval.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "decide_clip", "description": "Approve or reject clips. Only when Steven explicitly said so for these clips.",
     "input_schema": {"type": "object", "properties": {
         "clip_ids": {"type": "array", "items": {"type": "integer"}},
         "decision": {"type": "string", "enum": ["approve", "reject"]}},
         "required": ["clip_ids", "decision"], "additionalProperties": False}},
    {"name": "remember", "description": "Add a lasting goal or preference of Steven's to the vision file.",
     "input_schema": {"type": "object", "properties": {"note": {"type": "string"}},
                      "required": ["note"], "additionalProperties": False}},
]


# ---- tools -----------------------------------------------------------------

def list_agents() -> dict:
    return {"agents": [{"name": a.name, "role": a.role, "params": a.params_help} for a in agents.AGENTS.values()]}


def assign_task(agent: str, instructions: str, params: dict | None = None) -> dict:
    a = agents.get(agent)
    if not a:
        return {"error": f"No agent called {agent}. Available: {', '.join(x.name for x in agents.AGENTS.values())}"}
    return {"task_id": db.create_task(a.name, instructions, params or {}, created_by="Boss"), "status": "queued"}


def get_status() -> dict:
    return {
        "tasks": db.rows("SELECT id, agent, instructions, status, result, updated_at FROM tasks ORDER BY id DESC LIMIT 10"),
        "clips_by_status": {r["status"]: r["n"] for r in db.rows("SELECT status, COUNT(*) n FROM clips GROUP BY status")},
        "recent_posts": db.rows("SELECT clip_id, platform, account, status, url, error, created_at FROM posts ORDER BY id DESC LIMIT 10"),
        "activity": db.rows("SELECT agent, message, created_at FROM activity ORDER BY id DESC LIMIT 15"),
    }


def list_pending_clips() -> dict:
    return {"clips": db.rows("SELECT id, creator, title, caption, score, reason, start_s, end_s, source_title "
                             "FROM clips WHERE status = 'pending_approval' ORDER BY score DESC")}


def decide_clip(clip_ids: list[int], decision: str) -> dict:
    status = "approved" if decision == "approve" else "rejected"
    for cid in clip_ids:
        db.set_clip_status(cid, status)
        db.log("Boss", f"Clip #{cid} {status} on Steven's instruction")
    return {"updated": clip_ids, "status": status}


def remember(note: str) -> dict:
    with open(VISION_PATH, "a", encoding="utf-8") as f:
        f.write(f"\n- {note.strip()}\n")
    return {"saved": True}


TOOL_FUNCS = {"list_agents": list_agents, "assign_task": assign_task, "get_status": get_status,
              "list_pending_clips": list_pending_clips, "decide_clip": decide_clip, "remember": remember}


def run_tool(name: str, args: dict) -> tuple[str, bool]:
    try:
        return json.dumps(TOOL_FUNCS[name](**args), default=str), False
    except Exception as e:
        return f"Error: {e}", True


# ---- conversation ----------------------------------------------------------
# History is append-only (never edited), which keeps Claude's thinking blocks valid
# and the prompt cache warm. "New conversation" starts a fresh thread instead of trimming.

def current_conversation() -> int:
    r = db.rows("SELECT MAX(conversation) c FROM boss_messages")
    return r[0]["c"] or 1


def new_conversation() -> int:
    conv = current_conversation() + 1
    db.execute("INSERT INTO boss_messages (conversation, role, content, created_at) VALUES (?, 'marker', '[]', ?)", conv, db.now())
    return conv


def history(conv: int) -> list[dict]:
    return [{"role": r["role"], "content": json.loads(r["content"])} for r in
            db.rows("SELECT role, content FROM boss_messages WHERE conversation = ? AND role != 'marker' ORDER BY id", conv)]


def _save(conv: int, role: str, content: list):
    db.execute("INSERT INTO boss_messages (conversation, role, content, created_at) VALUES (?, ?, ?, ?)",
               conv, role, json.dumps(content), db.now())


def _vision_block(messages: list) -> list:
    """Send the vision again only when it changed since it was last sent in this conversation."""
    vision = VISION_PATH.read_text(encoding="utf-8") if VISION_PATH.exists() else ""
    tag = hashlib.sha1(vision.encode()).hexdigest()[:10]
    for m in messages:
        if m["role"] == "user" and isinstance(m["content"], list):
            for b in m["content"]:
                if b.get("type") == "text" and f'<vision id="{tag}">' in b.get("text", ""):
                    return []
    return [{"type": "text", "text": f'<vision id="{tag}">\n{vision}\n</vision>'}]


_chat_lock = threading.Lock()  # the dashboard and the daily report share one conversation; take turns


def chat(text: str) -> str:
    with _chat_lock:
        return _chat(text)


def _chat(text: str) -> str:
    conv = current_conversation()
    if not llm.HAS_LLM:
        reply = _offline(text)
        _save(conv, "user", [{"type": "text", "text": text}])
        _save(conv, "assistant", [{"type": "text", "text": reply}])
        return reply
    messages = history(conv)
    user = {"role": "user", "content": _vision_block(messages) + [{"type": "text", "text": text}]}
    messages.append(user)
    _save(conv, "user", user["content"])
    db.log("Steven", text[:200])

    for _ in range(25):
        response = llm.create(BOSS_MODEL, SYSTEM, messages, tools=TOOLS, effort="medium")
        content = [b.model_dump(mode="json", exclude_none=True) for b in response.content]
        messages.append({"role": "assistant", "content": content})
        _save(conv, "assistant", content)
        calls = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason != "tool_use" or not calls:
            reply = llm.text_of(response)
            db.log("Boss", reply[:200])
            return reply
        results = []
        for call in calls:
            out, is_error = run_tool(call.name, call.input)
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": out, "is_error": is_error})
        messages.append({"role": "user", "content": results})
        _save(conv, "user", results)
    return "I hit my step limit on that one. Ask again or break it into smaller asks."


def report() -> str:
    """A short status report for Steven, used for the daily briefing."""
    return chat("Give me a short status report: what each agent did since your last report, what is waiting on "
                "my approval, and anything that failed. Use get_status and list_pending_clips.")


def _offline(text: str) -> str:
    """Basic commands so the system is usable before an API key is set."""
    t = text.strip().lower()
    if t.startswith("clip"):
        rest = text.strip()[4:].strip()
        params = {"url": rest} if rest.startswith("http") else ({"creator": rest} if rest else {})
        tid = db.create_task("Chad", f"Clip {rest or 'all creators'}", params, created_by="Steven")
        return f"Queued task #{tid} for Chad."
    if t in ("status", "report"):
        s = get_status()
        return (f"Clips: {s['clips_by_status'] or 'none yet'}. Latest tasks: " +
                "; ".join(f"#{x['id']} {x['agent']} {x['status']}" for x in s["tasks"][:5]))
    return ("The Boss needs ANTHROPIC_API_KEY set to talk properly. Until then, try: "
            "'status', 'clip <creator name>' or 'clip <video link>'.")
