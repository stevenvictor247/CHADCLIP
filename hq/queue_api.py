"""Dashboard routes for Queue's Today's 10 screen."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from . import pitchqueue

router = APIRouter()
STATIC = Path(__file__).parent / "static"


@router.get("/queue-panel.js")
def queue_panel_js():
    return FileResponse(STATIC / "queue-panel.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/api/queue")
def queue_state():
    return pitchqueue.state()


@router.post("/api/queue/{lead_id}/sent")
def queue_mark_sent(lead_id: int, request: Request):
    """Steven pressed 'Mark sent' after sending the draft himself."""
    if request.headers.get("x-hq") != "1":
        raise HTTPException(403, "Use the HQ dashboard for this")
    try:
        return {"message": pitchqueue.mark_sent(lead_id)}
    except KeyError:
        raise HTTPException(404, f"No lead #{lead_id}")
