"""Dashboard routes for Queue, the daily send list."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from . import dailyqueue

router = APIRouter()
STATIC = Path(__file__).parent / "static"


def _from_hq_page(request: Request):
    if request.headers.get("x-hq") != "1":
        raise HTTPException(403, "Use the HQ dashboard for this")


@router.get("/queue-panel.js")
def queue_panel_js():
    return FileResponse(STATIC / "queue-panel.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/api/queue")
def queue_state():
    s = dailyqueue.state()
    fields = ("id", "name", "platform", "handle", "followers", "contact", "pitch", "score", "score_why")
    s["show"] = [{k: r[k] for k in fields} for r in s["show"]]
    s["ready_count"] = len(s.pop("ready"))
    return s


@router.post("/api/queue/sent/{lead_id}")
def queue_sent(lead_id: int, request: Request):
    _from_hq_page(request)
    try:
        return {"message": dailyqueue.mark_sent(lead_id)}
    except ValueError as e:
        raise HTTPException(404, str(e))
