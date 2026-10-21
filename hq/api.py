"""The dashboard and its API. Run with: python -m hq serve"""

import hashlib
import hmac
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agents, boss, db
from .config import CLIPS_DIR, HAS_LLM, PASSWORD

app = FastAPI(title="Agent HQ")
app.mount("/clips", StaticFiles(directory=CLIPS_DIR), name="clips")
STATIC = Path(__file__).parent / "static"
SESSION_COOKIE = "hq_session"


def _session_token() -> str:
    """The cookie value a logged-in browser holds. Changing HQ_PASSWORD logs everyone out."""
    return hmac.new(PASSWORD.encode(), b"agent-hq-session", hashlib.sha256).hexdigest()


@app.middleware("http")
async def require_login(request: Request, call_next):
    """With HQ_PASSWORD set, every page except the login page needs the session cookie."""
    if not PASSWORD or request.url.path in ("/login", "/logout"):
        return await call_next(request)
    if hmac.compare_digest(request.cookies.get(SESSION_COOKIE, ""), _session_token()):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Log in first"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


class ChatIn(BaseModel):
    text: str


class TaskIn(BaseModel):
    agent: str
    instructions: str
    params: dict = {}


class ClipEdit(BaseModel):
    title: str | None = None
    caption: str | None = None


def _library() -> list[dict]:
    """Clips that have left the approval queue, newest first, with where each was posted."""
    clips = db.rows("SELECT * FROM clips WHERE status != 'pending_approval' ORDER BY id DESC LIMIT 100")
    posts = db.rows("SELECT clip_id, platform, account, status, url, error FROM posts ORDER BY id")
    for c in clips:
        c["posts"] = [p for p in posts if p["clip_id"] == c["id"]]
    return clips


@app.on_event("startup")
def _startup():
    db.init()


@app.get("/login")
def login_page():
    return FileResponse(STATIC / "login.html")


@app.post("/login")
def login(password: str = Form("")):
    if not PASSWORD or not hmac.compare_digest(password.encode(), PASSWORD.encode()):
        return RedirectResponse("/login?wrong=1", status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(SESSION_COOKIE, _session_token(), max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax")
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/")
def index():
    # no-cache: the browser checks for a newer page each time, so updates show up without Ctrl+F5
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/world.js")
def world():
    return FileResponse(STATIC / "world.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/api/state")
def state():
    running = {r["agent"]: r["instructions"] for r in db.rows("SELECT agent, instructions FROM tasks WHERE status = 'running'")}
    return {
        "has_llm": HAS_LLM,
        "agents": [{"name": "Boss", "role": "Directs the team and reports to you.", "doing": None}] +
                  [{"name": a.name, "role": a.role, "doing": running.get(a.name)} for a in agents.AGENTS.values()],
        "counts": {r["status"]: r["n"] for r in db.rows("SELECT status, COUNT(*) n FROM clips GROUP BY status")},
        "pending": db.rows("SELECT * FROM clips WHERE status = 'pending_approval' ORDER BY score DESC, id"),
        "clips": _library(),
        "tasks": db.rows("SELECT * FROM tasks ORDER BY id DESC LIMIT 20"),
        "posts": db.rows("SELECT * FROM posts ORDER BY id DESC LIMIT 20"),
        "activity": db.rows("SELECT * FROM activity ORDER BY id DESC LIMIT 40"),
        "chat": [m for m in boss.history(boss.current_conversation())
                 if isinstance(m["content"], list) and any(b.get("type") == "text" for b in m["content"])
                 and not any(b.get("type") == "tool_result" for b in m["content"])],
    }


@app.post("/api/chat")
def chat(body: ChatIn):
    try:
        return {"reply": boss.chat(body.text)}
    except Exception as e:  # show the problem in the chat instead of failing silently
        return {"reply": f"Something went wrong talking to Claude: {e}"}


@app.post("/api/conversation/new")
def new_conversation():
    return {"conversation": boss.new_conversation()}


@app.post("/api/tasks")
def add_task(body: TaskIn):
    if not agents.get(body.agent):
        raise HTTPException(404, f"No agent called {body.agent}")
    return {"task_id": db.create_task(body.agent, body.instructions, body.params, created_by="Steven")}


@app.post("/api/clips/{clip_id}/{decision}")
def decide(clip_id: int, decision: str):
    if decision not in ("approve", "reject"):
        raise HTTPException(400, "decision must be approve or reject")
    status = "approved" if decision == "approve" else "rejected"
    db.set_clip_status(clip_id, status)
    db.log("Steven", f"Clip #{clip_id} {status}")
    return {"clip_id": clip_id, "status": status}


@app.patch("/api/clips/{clip_id}")
def edit_clip(clip_id: int, body: ClipEdit):
    if body.title is not None:
        db.execute("UPDATE clips SET title = ? WHERE id = ?", body.title, clip_id)
    if body.caption is not None:
        db.execute("UPDATE clips SET caption = ? WHERE id = ?", body.caption, clip_id)
    return {"ok": True}
