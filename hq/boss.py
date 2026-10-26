"""The Boss: Steven's right hand. Takes direction, assigns work to the agents, and reports back."""

import hashlib
import json
import re
import threading

from . import agents, db, football, ledger, llm, review, tally
from .config import BOSS_MODEL, VISION_PATH

SYSTEM = """You are the Boss, the head of an AI agent team that runs parts of Steven's online business.
Steven is the owner. You turn his direction into concrete tasks for the agents, keep an eye on their work,
and report back to him plainly and briefly.

How you work:
- Steven's current vision arrives inside <vision> tags. It is the standing direction for everything you do.
- Delegate with assign_task. Give each agent clear, specific instructions and the params it understands.
  Agents run tasks in the background; tell Steven what you assigned rather than waiting for results.
- Use get_status and list_pending_clips to answer questions about what the team is doing. Never invent numbers.
- You check Chad's work. When Steven asks you to check on Chad (or his clips), and in every report, call
  review_chad. Lead with what needs Steven: failed or stuck tasks, failed posts, and flagged clips with the
  reason in plain words. Then say briefly what went fine. Use list_pending_clips to judge titles and captions
  yourself too (boring, misleading, typos, missing credit).
- When a waiting clip has a real problem, leave a short note on it with flag_clip so Steven sees it on the
  approval card. Flagging never approves, rejects or posts. If Chad keeps making the same mistake, suggest a
  fix (a setting in chad.yaml, or a task with clearer instructions) and ask Steven before assigning it.
- Anything that posts publicly, spends money or contacts people needs Steven's approval. Only call decide_clip
  when Steven has explicitly told you, in this conversation, to approve or reject those specific clips.
- When Steven states a lasting preference or goal, save it with remember so it becomes part of the vision.
- Football: Steven is also a graduate assistant on Wayne State's defensive staff. The football agents live in
  Warrior Village: Captain (runs it), Clock, Ref, Tells, Scribe and Depth (the Monday opponent personnel sheet). Give anything football to Captain with
  assign_task (plain-words instructions), or straight to the one agent when it's obvious (Clock to tick off or move
  checklist items, Ref to check a sheet, Tells for a scouting report). get_status includes the football week.
  Never invent football stats or tendencies, and nothing football goes to a coach without Steven.
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
    {"name": "review_chad", "description": "Check Chad's recent work: tasks done, failed or stuck, new clips, "
     "quality problems on clips waiting for approval (missing captions, no credit, weak moment, duplicates, "
     "too long, missing file) and failed posts.",
     "input_schema": {"type": "object", "properties": {
         "hours": {"type": "number", "description": "How far back to look. Default 24."}},
         "additionalProperties": False}},
    {"name": "flag_clip", "description": "Put a short review note on a clip waiting for approval, shown to Steven "
     "on its approval card. Empty note clears it. Does not approve, reject or post.",
     "input_schema": {"type": "object", "properties": {
         "clip_id": {"type": "integer"}, "note": {"type": "string"}},
         "required": ["clip_id", "note"], "additionalProperties": False}},
    {"name": "setup_status", "description": "The getting-started checklist: which keys, accounts and permissions HQ "
     "still needs, what's broken, and how Steven fixes each one. Use when he asks what's left to set up or why "
     "nothing is happening.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "remember", "description": "Add a lasting goal or preference of Steven's to the vision file.",
     "input_schema": {"type": "object", "properties": {"note": {"type": "string"}},
                      "required": ["note"], "additionalProperties": False}},
]


# ---- tools -----------------------------------------------------------------

def list_agents() -> dict:
    return {"agents": [{"name": a.name, "role": a.role, "params": a.params_help, "village": a.village}
                       for a in agents.AGENTS.values()]}


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
        "claude_spend": ledger.summary(),
        "views": tally.summary(),
        "football": football.status(),
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


def review_chad(hours: float = 24) -> dict:
    return review.review_chad(hours)


def flag_clip(clip_id: int, note: str) -> dict:
    found = db.rows("SELECT status FROM clips WHERE id = ?", clip_id)
    if not found:
        return {"error": f"No clip #{clip_id}"}
    if found[0]["status"] != "pending_approval":
        return {"error": f"Clip #{clip_id} is {found[0]['status']}, not waiting for approval"}
    note = note.strip()[:300]
    db.execute("UPDATE clips SET boss_note = ? WHERE id = ?", note or None, clip_id)
    db.log("Boss", f"Flagged clip #{clip_id}: {note}" if note else f"Cleared note on clip #{clip_id}")
    return {"clip_id": clip_id, "note": note}


def remember(note: str) -> dict:
    with open(VISION_PATH, "a", encoding="utf-8") as f:
        f.write(f"\n- {note.strip()}\n")
    return {"saved": True}


def setup_status() -> dict:
    from . import setup_check
    s = setup_check.summary()
    return {"ready": s["ready"], "done": f"{s['done']} of {s['total']}",
            "items": [{k: i[k] for k in ("title", "status", "detail", "fix", "required")} for i in s["items"]]}


TOOL_FUNCS = {"list_agents": list_agents, "assign_task": assign_task, "get_status": get_status,
              "list_pending_clips": list_pending_clips, "decide_clip": decide_clip, "remember": remember,
              "review_chad": review_chad, "flag_clip": flag_clip, "setup_status": setup_status}


def run_tool(name: str, args: dict) -> tuple[str, bool]:
    try:
        return json.dumps(TOOL_FUNCS[name](**args), default=str), False
    except Exception as e:
        return f"Error: {e}", True


# ---- conversation ----------------------------------------------------------
# History is append-only (never edited), which keeps Claude's thinking blocks valid and the prompt cache warm.
# Every message re-sends the whole conversation, so a long one gets expensive. Instead of trimming it in place, the
# chat rolls over: a new conversation starts with a short recap of the last few exchanges (the vision file and the
# Boss's notes are sent again by themselves). That happens by itself past AUTO_ROLL_TOKENS, and on "New conversation".

AUTO_ROLL_TOKENS = 30_000   # about what a chat costs a few cents per message at; roll over before it grows further
RECAP_TAG = "[Recap of the earlier chat, for context only]"
RECAP_ACK = "Got it. I'll carry on from there."
RECAP_TURNS = 8             # most recent text exchanges kept in the recap
RECAP_TURN_CHARS = 350
RECAP_MAX_CHARS = 3000


def current_conversation() -> int:
    r = db.rows("SELECT MAX(conversation) c FROM boss_messages")
    return r[0]["c"] or 1


def chat_tokens(conv: int | None = None) -> int:
    """Rough size of what is re-sent with every message (4 characters to a token)."""
    r = db.rows("SELECT COALESCE(SUM(LENGTH(content)), 0) chars FROM boss_messages WHERE conversation = ? "
                "AND role != 'marker'", current_conversation() if conv is None else conv)
    return r[0]["chars"] // 4


def _plain_text(blocks: list, skip_vision: bool = True) -> str:
    out = []
    for b in blocks:
        if b.get("type") == "text":
            t = b.get("text", "")
            if skip_vision and t.startswith("<vision"):
                continue
            out.append(t)
    return " ".join(" ".join(out).split())


def recap(conv: int) -> str:
    """The last few things Steven and the Boss said, as plain short lines. No tool results and no Claude call."""
    turns = []
    for m in history(conv):
        if not isinstance(m["content"], list):
            continue
        text = _plain_text(m["content"])
        if not text or text.startswith(RECAP_TAG) or text == RECAP_ACK or text == "Daily report, please.":
            continue
        who = "Steven" if m["role"] == "user" else "Boss"
        turns.append(f"{who}: {text[:RECAP_TURN_CHARS]}{'...' if len(text) > RECAP_TURN_CHARS else ''}")
    out = ""
    for line in reversed(turns[-RECAP_TURNS * 2:]):   # newest first, so the cap cuts the oldest
        if len(out) + len(line) + 1 > RECAP_MAX_CHARS:
            break
        out = line + "\n" + out
    return out.strip()


def new_conversation(carry: bool = True) -> int:
    """Start a fresh conversation. With carry (the default) it opens with a short recap of the old one."""
    old = current_conversation()
    summary = recap(old) if carry else ""
    conv = old + 1
    db.execute("INSERT INTO boss_messages (conversation, role, content, created_at) VALUES (?, 'marker', '[]', ?)", conv, db.now())
    if summary:
        _save(conv, "user", [{"type": "text", "text": f"{RECAP_TAG}\n{summary}"}])
        _save(conv, "assistant", [{"type": "text", "text": RECAP_ACK}])
    return conv


def is_recap(m: dict) -> bool:
    """Recap messages are for Claude; the dashboard chat doesn't show them."""
    if not isinstance(m.get("content"), list):
        return False
    text = _plain_text(m["content"])
    return text.startswith(RECAP_TAG) or text == RECAP_ACK


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
    if chat_tokens(conv) >= AUTO_ROLL_TOKENS:   # between messages only, never in the middle of a tool round
        conv = new_conversation()
        db.log("HQ", "The Boss chat got long, so I started a fresh one with a short recap to keep each message cheap")
    if football.notebook.is_nb(text):   # "NB: ..." goes straight to Scribe, from the dashboard or your phone
        from .agents.football.scribe import note
        reply = note(text)
        _save(conv, "user", [{"type": "text", "text": text}])
        _save(conv, "assistant", [{"type": "text", "text": reply}])
        return reply
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
        response = llm.create(BOSS_MODEL, SYSTEM, messages, tools=TOOLS, effort="medium", agent="Boss", cache=True)
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


REPORT_SYSTEM = """You write Steven's short daily status report for his AI agent team, from the facts you're given.
Lead with what needs him: failed or stuck tasks, failed posts, flagged clips (with the reason in plain words),
anything waiting for his approval, and setup steps still blocking money coming in. Then say briefly what went fine.
Plain short sentences, no filler, no headings, at most about 12 lines. Never invent numbers."""


def report() -> str:
    """The daily briefing. Gathered straight from the database and written in one call on a mid-priced model, instead
    of a tool-by-tool chat on the Boss's model: same facts, a fraction of the cost. It still lands in the Boss chat,
    and clips with a real problem still get a note on their approval card."""
    from .config import model_for
    chad = review.review_chad(24)
    for f in chad["waiting_for_steven"]["flagged"]:   # what the Boss used to do with flag_clip, by rule
        if not f.get("your_earlier_note"):
            flag_clip(f["clip"], "; ".join(f["issues"]))
    facts = {"status": get_status(), "chad_review": chad, "waiting_clips": list_pending_clips()["clips"][:15],
             "setup": setup_status()}
    if llm.HAS_LLM:
        try:
            response = llm.create(model_for("report"), REPORT_SYSTEM,
                                  [{"role": "user", "content": json.dumps(facts, default=str)[:60000]}],
                                  effort="low", max_tokens=3000, agent="Boss")
            text = llm.text_of(response)
        except Exception as e:  # a report that can't be written still says the basics
            text = review.summary(chad) + f"\n(Couldn't write the full report: {e})"
    else:
        text = review.summary(chad)
    with _chat_lock:  # show it in the Boss chat too, where it used to appear
        conv = current_conversation()
        if chat_tokens(conv) >= AUTO_ROLL_TOKENS:   # the daily report adds to the chat even when nobody talks to it
            conv = new_conversation()
        _save(conv, "user", [{"type": "text", "text": "Daily report, please."}])
        _save(conv, "assistant", [{"type": "text", "text": text}])
    return text


def _offline(text: str) -> str:
    """Basic commands so the system is usable before an API key is set."""
    t = text.strip().lower()
    if t.startswith("clip"):
        rest = text.strip()[4:].strip()
        m = re.match(r"(?i)@?(\w+?)(?:'s)?\s+past (?:streams|vods)$", rest)
        if m:
            tid = db.create_task("Chad", f"Clip {m.group(1)}'s past streams", {"vods": m.group(1)}, created_by="Steven")
            return f"Queued task #{tid} for Chad."
        params = {"url": rest} if rest.startswith("http") else ({"creator": rest} if rest else {})
        tid = db.create_task("Chad", f"Clip {rest or 'all creators'}", params, created_by="Steven")
        return f"Queued task #{tid} for Chad."
    if "chad" in t and any(w in t for w in ("check", "review", "how")):
        return review.summary(review.review_chad())
    if t in ("status", "report"):
        s = get_status()
        return (f"Clips: {s['clips_by_status'] or 'none yet'}. Latest tasks: " +
                "; ".join(f"#{x['id']} {x['agent']} {x['status']}" for x in s["tasks"][:5]))
    return ("The Boss needs ANTHROPIC_API_KEY set to talk properly. Until then, try: "
            "'status', 'check on chad', 'clip <creator name>' or 'clip <video link>'.")
