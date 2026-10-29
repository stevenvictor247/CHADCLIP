"""Dashboard routes for Sweep, the janitor."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from . import budgets, db, quality, sweep

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
    return {**sweep.latest(), "budgets": budgets.snapshot()}


@router.post("/api/sweep/run")
def sweep_run(request: Request):
    """Ask Sweep to tidy up and send the report now. It runs in the background like any other job."""
    _from_hq_page(request)
    return {"task_id": db.create_task("Sweep", "Tidy up and send the report now.", {"report": True}, created_by="Steven")}


@router.post("/api/sweep/fix/{fix_id}")
def sweep_fix(fix_id: str, request: Request):
    """A one-tap fix from the improvement report. Each is small and safe: none posts, emails, spends or changes settings."""
    _from_hq_page(request)
    try:
        message = quality.apply_fix(fix_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    sweep._refresh_latest()
    return {"message": message}


@router.post("/api/sweep/hide/{tip_id}")
def sweep_hide(tip_id: str, request: Request):
    """Hide one improvement idea for a week (it comes back if it's still true)."""
    _from_hq_page(request)
    return {"message": sweep.snooze(tip_id[:80])}


@router.post("/api/sweep/unhide/{tip_id}")
def sweep_unhide(tip_id: str, request: Request):
    _from_hq_page(request)
    return {"message": sweep.unsnooze(tip_id[:80])}


@router.post("/api/sweep/restore/{trash_id}")
def sweep_restore(trash_id: int, request: Request):
    _from_hq_page(request)
    try:
        return {"message": sweep.restore(trash_id)}
    except ValueError as e:
        raise HTTPException(409, str(e))
