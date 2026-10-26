"""Dashboard routes for Muse, the Creative Director (the Ideas tab)."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import db, muse

router = APIRouter()
STATIC = Path(__file__).parent / "static"


def _from_hq_page(request: Request):
    if request.headers.get("x-hq") != "1":
        raise HTTPException(403, "Use the HQ dashboard for this")


class RunIn(BaseModel):
    focus: str | None = None


class DecideIn(BaseModel):
    reason: str | None = None


@router.get("/muse-panel.js")
def muse_panel_js():
    return FileResponse(STATIC / "muse-panel.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/api/muse")
def muse_state():
    return muse.latest()


@router.post("/api/muse/run")
def muse_run(body: RunIn, request: Request):
    """Brainstorm now, optionally on a topic. Runs in the background like any other job, inside the money caps."""
    _from_hq_page(request)
    if db.rows("SELECT 1 FROM tasks WHERE agent = 'Muse' AND status IN ('queued', 'running') LIMIT 1"):
        return {"message": "Muse is already thinking. New ideas show here in a minute or two."}
    blocked = muse.why_not_now(manual=True)
    if blocked:
        raise HTTPException(409, blocked)
    focus = (body.focus or "").strip()[:500] or None
    words = f"Think up new ideas about: {focus}" if focus else "Think up new ideas now."
    task_id = db.create_task("Muse", words, {"focus": focus} if focus else {}, created_by="Steven")
    return {"task_id": task_id, "message": "Muse is thinking. New ideas show here in a minute or two."}


@router.post("/api/muse/ideas/{idea_id}/send")
def muse_send_build(idea_id: int, request: Request):
    """Send an approved idea to Claude to build (again, if the last try failed)."""
    _from_hq_page(request)
    try:
        return {"message": muse.start_build(idea_id)}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/api/muse/ideas/{idea_id}/{decision}")
def muse_decide(idea_id: int, decision: str, body: DecideIn, request: Request):
    _from_hq_page(request)
    try:
        return {"message": muse.decide(idea_id, decision, body.reason)}
    except ValueError as e:
        raise HTTPException(404 if "No idea" in str(e) else 400, str(e))
