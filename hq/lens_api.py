"""Dashboard routes for Lens, the low-views detective."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from . import lens

router = APIRouter()
STATIC = Path(__file__).parent / "static"


@router.get("/lens-panel.js")
def lens_panel_js():
    return FileResponse(STATIC / "lens-panel.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/api/lens")
def lens_state():
    return lens.summary()


@router.post("/api/lens/fix")
def lens_fix(key: str, state: str):
    if not lens.decide(key, state):
        raise HTTPException(400, "state must be done or ignored")
    return {"ok": True}
