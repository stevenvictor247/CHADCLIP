"""Dashboard routes for the Etsy village (Print Street): the product board, research notes, stats file and buttons."""

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import agents, approvals, db, etsy
from .etsy import printify, stats, store, work

router = APIRouter()
STATIC = Path(__file__).parent / "static"
ETSY_AGENT_NAMES = {"etta", "radar", "quill", "loom", "warden", "dock"}


def _from_hq_page(request: Request):
    if request.headers.get("x-hq") != "1":
        raise HTTPException(403, "Use the HQ dashboard for this")


def _design(design_id: int) -> dict:
    d = store.get(design_id)
    if not d:
        raise HTTPException(404, f"No design #{design_id}")
    return d


class NoteIn(BaseModel):
    text: str


class RunIn(BaseModel):
    theme: str | None = None
    count: int | None = None


class EditIn(BaseModel):
    slogan: str | None = None
    subline: str | None = None
    title: str | None = None
    tags: list[str] | None = None
    price: float | None = None
    style: str | None = None


@router.get("/etsy-town.js")
def etsy_town_js():
    return FileResponse(STATIC / "etsy-town.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/etsy-panel.js")
def etsy_panel_js():
    return FileResponse(STATIC / "etsy-panel.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/api/etsy")
def etsy_state():
    return etsy.state()


@router.get("/api/etsy/designs/{design_id}/file/{which}")
def etsy_file(design_id: int, which: str):
    """The preview, or a print file (dark or light ink), to look at or download."""
    if which not in ("preview", "dark", "light"):
        raise HTTPException(404, "No such file")
    d = _design(design_id)
    path = Path(d["files"].get(which) or "").resolve() if d["files"].get(which) else None
    if not path or path.parent.parent != work.DESIGNS_DIR.resolve() or not path.is_file():
        raise HTTPException(404, "That file isn't drawn yet")
    return FileResponse(path, media_type="image/png", filename=f"design-{design_id}-{which}.png",
                        content_disposition_type="inline" if which == "preview" else "attachment")


@router.get("/api/etsy/designs/{design_id}/listing")
def etsy_listing(design_id: int):
    """The listing text, to copy into Etsy if you ever list by hand."""
    d = _design(design_id)
    return {"title": d["title"], "tags": d["tags"], "description": d["description"], "price": d["price_cents"] / 100}


@router.post("/api/etsy/designs/{design_id}/edit")
def etsy_edit(design_id: int, body: EditIn, request: Request):
    """Change the words, title, tags, price or look. The design is drawn and checked again."""
    _from_hq_page(request)
    d = _design(design_id)
    if d["stage"] in ("building", "ready", "live"):
        raise HTTPException(409, "It's already in Printify: change it there, or retire it and make a new one.")
    fields = {}
    for k in ("slogan", "subline", "title", "style"):
        v = getattr(body, k)
        if v is not None:
            fields[k] = v.strip()[:200]
    if body.tags is not None:
        fields["tags"] = body.tags[:13]
    if body.price is not None:
        fields["price_cents"] = int(round(min(max(body.price, 10), 80) * 100))
    if fields.get("style") and fields["style"] not in ("bold", "retro", "script", "marker", "badge"):
        raise HTTPException(400, "Style must be bold, retro, script, marker or badge")
    if d["approval_id"] and d["stage"] == "review":
        db.execute("UPDATE approvals SET status = 'rejected', decided_at = ? WHERE id = ? AND status = 'pending'",
                   db.now(), d["approval_id"])
    store.update(design_id, **fields, stage="written", note="You edited it: Loom draws it again")
    db.log("Steven", f"Edited Etsy design #{design_id}")
    return {"message": "Saved. Loom redraws it and Warden checks it again in a minute."}


@router.post("/api/etsy/designs/{design_id}/{action}")
def etsy_action(design_id: int, action: str, request: Request):
    _from_hq_page(request)
    d = _design(design_id)
    if action in ("approve", "reject"):
        if d["stage"] == "review" and d["approval_id"]:
            return {"message": approvals.decide(int(d["approval_id"]), action)}
        if action == "approve" and d["stage"] == "held":
            raise HTTPException(409, "Warden held it for a rule problem. Edit it so the problem's gone.")
        if action == "reject":
            store.move(design_id, "rejected", "You skipped it")
            return {"message": "Skipped."}
        raise HTTPException(409, f"It isn't waiting for your OK ({d['stage']}).")
    if action == "retire":
        store.move(design_id, "retired", "You retired it. Unpublish it in Printify or Etsy if it's live.")
        db.log("Steven", f"Retired Etsy design #{design_id}")
        return {"message": "Retired. If it's on Etsy, delete or deactivate it there yourself."}
    if action == "redraw":
        if d["stage"] in ("building", "ready", "live"):
            raise HTTPException(409, "It's already in Printify.")
        store.move(design_id, "written", "Loom draws it again")
        return {"message": "Loom redraws it in a minute."}
    if action == "photo":
        store.update(design_id, photo_added=0 if d["photo_added"] else 1)
        return {"message": "Ticked: real photo added." if not d["photo_added"] else "Unticked."}
    if action == "build":
        if not printify.connected():
            raise HTTPException(409, "Connect Printify first: paste your API token in Settings.")
        if d["stage"] != "approved":
            raise HTTPException(409, f"Only approved designs can be built ({d['stage']}).")
        tid = db.create_task("Dock", f"Build design #{design_id} in Printify", {"design_id": design_id},
                             created_by="Steven")
        return {"task_id": tid, "message": "Dock is building it in Printify."}
    raise HTTPException(404, f"Unknown action {action}")


@router.post("/api/etsy/notes")
def etsy_note(body: NoteIn, request: Request):
    """Paste what you saw (Etsy search suggestions, eRank, a trend). Radar reads it in its next brief."""
    _from_hq_page(request)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Paste something first")
    store.add_note(text[:4000], "research")
    db.log("Steven", "Added an Etsy research note for Radar")
    return {"message": "Saved. Radar uses it in the next brief (within a day)."}


@router.post("/api/etsy/stats")
def etsy_stats(request: Request, file: UploadFile = File(...)):
    _from_hq_page(request)
    data = file.file.read(5_000_000)
    try:
        return {"message": stats.load(data, Path(file.filename or "stats.csv").name)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/etsy/run/{agent}")
def etsy_run(agent: str, body: RunIn, request: Request):
    """Run one Etsy agent now (it still keeps to the budget)."""
    _from_hq_page(request)
    a = agents.get(agent)
    if not a or agent.lower() not in ETSY_AGENT_NAMES:
        raise HTTPException(404, f"No Etsy agent called {agent}")
    if db.rows("SELECT 1 FROM tasks WHERE agent = ? AND status IN ('queued', 'running') LIMIT 1", a.name):
        return {"message": f"{a.name} is already on it."}
    params = {}
    if a.name == "Quill" and body.theme:
        params = {"theme": body.theme.strip()[:120], "count": body.count or 3}
    if a.name == "Etta":
        params = {"report": True}
    tid = db.create_task(a.name, f"{a.name}: run now", params, created_by="Steven")
    return {"task_id": tid, "message": f"{a.name} is on it."}
