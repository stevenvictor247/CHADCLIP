"""Dashboard routes for Trim, the queue trimmer."""

from fastapi import APIRouter, HTTPException, Request

from . import db, trim

router = APIRouter()


@router.get("/api/trim")
def trim_state():
    return {"ranking": trim.ranking(), "auto": bool(trim._state().get("approved")), "can_undo": "undo" in trim._state()}


@router.post("/api/trim/undo")
def trim_undo(request: Request):
    if request.headers.get("x-hq") != "1":
        raise HTTPException(403, "Use the HQ dashboard for this")
    return {"message": trim.undo()}


@router.post("/api/trim/run")
def trim_run(request: Request):
    if request.headers.get("x-hq") != "1":
        raise HTTPException(403, "Use the HQ dashboard for this")
    return {"task_id": db.create_task("Trim", "Rank the clip queue now.", {}, created_by="Steven")}
