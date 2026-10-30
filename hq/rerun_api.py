"""Dashboard routes for Rerun, the second-try drafts."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from . import rerun

router = APIRouter()
STATIC = Path(__file__).parent / "static"


def _from_hq_page(request: Request):
    if request.headers.get("x-hq") != "1":
        raise HTTPException(403, "Use the HQ dashboard for this")


@router.get("/rerun-panel.js")
def rerun_panel_js():
    return FileResponse(STATIC / "rerun-panel.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/api/rerun")
def rerun_state():
    return rerun.state()


@router.post("/api/rerun/{try_id}/{decision}")
def rerun_decide(try_id: int, decision: str, request: Request):
    _from_hq_page(request)
    if decision not in ("sent", "skipped"):
        raise HTTPException(404, "Unknown decision")
    try:
        return {"message": rerun.decide(try_id, decision)}
    except ValueError as e:
        raise HTTPException(404, str(e))
