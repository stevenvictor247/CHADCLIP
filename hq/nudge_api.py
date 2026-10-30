"""Dashboard routes for Nudge, the pitch reply watcher."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from . import mailwatch

router = APIRouter()
STATIC = Path(__file__).parent / "static"


@router.get("/nudge-panel.js")
def nudge_panel_js():
    return FileResponse(STATIC / "nudge-panel.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/api/nudge")
def nudge_state():
    return mailwatch.summary()
