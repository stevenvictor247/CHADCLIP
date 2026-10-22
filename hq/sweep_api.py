"""Dashboard routes for Sweep, the janitor."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from . import db, sweep

router = APIRouter()
STATIC = Path(__file__).parent / "static"


def _from_hq_page(request: Request):
    if request.headers.get("x-hq") != "1":
        raise HTTPException(403, "Use the HQ dashboard for this")


@router.get("/sweep-panel.js")
def sweep_panel_js():
    return FileResponse(STATIC / "sweep-panel.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/api/sweep")
def sweep_state():
    return sweep.latest()


@router.post("/api/sweep/run")
def sweep_run(request: Request):
    """Ask Sweep to tidy up and send the report now. It runs in the background like any other job."""
    _from_hq_page(request)
    return {"task_id": db.create_task("Sweep", "Tidy up and send the report now.", {"report": True}, created_by="Steven")}


@router.post("/api/sweep/restore/{trash_id}")
def sweep_restore(trash_id: int, request: Request):
    _from_hq_page(request)
    try:
        return {"message": sweep.restore(trash_id)}
    except ValueError as e:
        raise HTTPException(409, str(e))
