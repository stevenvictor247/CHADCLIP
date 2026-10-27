"""Dashboard routes for Recruiter (its strip on the Ideas tab). Its proposals are answered through the Muse routes."""

from fastapi import APIRouter, HTTPException, Request

from . import db, recruiter

router = APIRouter()


@router.get("/api/recruiter")
def recruiter_state():
    return recruiter.latest()


@router.post("/api/recruiter/run")
def recruiter_run(request: Request):
    """Look for gaps now. Runs in the background like any other job, inside the money caps."""
    if request.headers.get("x-hq") != "1":
        raise HTTPException(403, "Use the HQ dashboard for this")
    if db.rows("SELECT 1 FROM tasks WHERE agent = 'Recruiter' AND status IN ('queued', 'running') LIMIT 1"):
        return {"message": "Recruiter is already looking. New proposals show here in a minute or two."}
    blocked = recruiter.why_not_now(manual=True)
    if blocked:
        raise HTTPException(409, blocked)
    task_id = db.create_task("Recruiter", "Look for gaps in HQ now and propose new agents.", {"manual": True},
                             created_by="Steven")
    return {"task_id": task_id, "message": "Recruiter is looking. New proposals show here in a minute or two."}
