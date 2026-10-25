"""The dashboard and its API. Run with: python -m hq serve"""

import hashlib
import hmac
import os
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agents, approvals, boss, campaigns, connections, creators, db, discovery, football, instagram_auth, ledger, money, settings, setup_check, tiktok_auth, update, youtube_auth
from . import drive_sync, move, standby, sweep_api
from .config import CLIPS_DIR, FOOTBALL_OUTBOX, HAS_LLM, PASSWORD, SOURCES_DIR, village_of

app = FastAPI(title="Agent HQ")
app.include_router(sweep_api.router)
app.mount("/clips", StaticFiles(directory=CLIPS_DIR), name="clips")
STATIC = Path(__file__).parent / "static"
SESSION_COOKIE = "hq_session"
STARTED = time.time()


def _session_token() -> str:
    """The cookie value a logged-in browser holds. Changing HQ_PASSWORD logs everyone out."""
    return hmac.new(PASSWORD.encode(), b"agent-hq-session", hashlib.sha256).hexdigest()


# Without a password HQ only listens on this computer, so only these names may reach it. This stops a website
# from pointing its own domain at 127.0.0.1 ("DNS rebinding") to read HQ or press its buttons.
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"} | {
    h.strip().lower() for h in os.getenv("HQ_ALLOWED_HOSTS", "").split(",") if h.strip()}
CHANGES = ("POST", "PUT", "PATCH", "DELETE")
# A standby copy is read-only (see standby.py). These still work there: updating HQ, restarting it, and moving.
STANDBY_ALLOWED = ("/api/update", "/api/restart", "/api/move/")


def _host(request: Request) -> str:
    host = request.headers.get("host", "").lower()
    if host.startswith("["):  # [::1]:8000
        return host[1:].split("]")[0]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


@app.middleware("http")
async def guard(request: Request, call_next):
    """Two locks against other websites open in the same browser:
    - without HQ_PASSWORD, only requests addressed to this computer by name are answered;
    - anything that changes something (approve, post, send, save) must come from HQ's own pages, which add an X-HQ
      header that other websites can't send. Without this a web page could quietly press Approve on a pitch email."""
    if not PASSWORD and _host(request) not in LOCAL_HOSTS:
        return JSONResponse({"detail": "HQ only answers this computer. Set HQ_PASSWORD to open it from others."},
                            status_code=403)
    if (request.method in CHANGES and request.url.path.startswith("/api/")
            and request.headers.get("x-hq") != "1"):
        return JSONResponse({"detail": "Use the HQ dashboard for this"}, status_code=403)
    if (request.method in CHANGES and request.url.path.startswith("/api/")
            and not request.url.path.startswith(STANDBY_ALLOWED) and standby.is_standby()):
        return JSONResponse({"detail": standby.blocked(), "standby": standby.info()}, status_code=409)
    return await call_next(request)


@app.middleware("http")
async def require_login(request: Request, call_next):
    """With HQ_PASSWORD set, every page except the login page needs the session cookie."""
    if not PASSWORD or request.url.path in ("/login", "/logout", "/healthz"):
        return await call_next(request)
    if hmac.compare_digest(request.cookies.get(SESSION_COOKIE, ""), _session_token()):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Log in first"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


class ChatIn(BaseModel):
    text: str


class TaskIn(BaseModel):
    agent: str
    instructions: str
    params: dict = {}


class SettingsIn(BaseModel):
    values: dict[str, str] = {}
    accounts: dict[str, bool] = {}
    pitch: dict[str, str] = {}


def _from_hq_page(request: Request):
    """Settings, updates and restarts only answer HQ's own pages (a custom header other websites can't send)."""
    if request.headers.get("x-hq") != "1":
        raise HTTPException(403, "Use the HQ dashboard for this")


class TestIn(BaseModel):
    values: dict[str, str] = {}   # keys typed on the Settings page but not saved yet


class ClipEdit(BaseModel):
    title: str | None = None
    caption: str | None = None


def _library() -> list[dict]:
    """Clips that have left the approval queue, newest first, with where each was posted."""
    clips = db.rows("SELECT * FROM clips WHERE status != 'pending_approval' ORDER BY id DESC LIMIT 100")
    posts = db.rows("SELECT clip_id, platform, account, status, url, error FROM posts ORDER BY id")
    for c in clips:
        c["posts"] = [p for p in posts if p["clip_id"] == c["id"]]
    return clips


def _tally_summary() -> dict:
    from . import tally
    return tally.summary()


@app.on_event("startup")
def _startup():
    standby.stopping.clear()
    db.init()
    update.check_in_background()


@app.on_event("shutdown")
def _shutdown():
    """HQ is stopping (a restart, an update or the server rebooting): let a clip that's being posted finish first, so
    it's recorded as posted and never goes out a second time."""
    standby.stopping.set()
    if standby.posting_lock.acquire(timeout=10 * 60):
        standby.posting_lock.release()


@app.get("/healthz")
def healthz():
    """Is this HQ alive, and does it run the agents? Open without logging in: the other copy of HQ asks this before
    it posts (so the PC and the cloud never both post), and so can an uptime checker. It shows nothing private."""
    from .worker import seconds_since_last_round
    ago = seconds_since_last_round()
    return {**standby.role(), "moved_in": move.last().get("moved_in", ""),
            "worker_seconds_ago": None if ago is None else round(ago), "uptime": round(time.time() - STARTED),
            "version": update._status.get("version", "")}


@app.get("/login")
def login_page():
    return FileResponse(STATIC / "login.html")


@app.post("/login")
def login(password: str = Form("")):
    if not PASSWORD or not hmac.compare_digest(password.encode(), PASSWORD.encode()):
        return RedirectResponse("/login?wrong=1", status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(SESSION_COOKIE, _session_token(), max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax")
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/")
def index():
    # no-cache: the browser checks for a newer page each time, so updates show up without Ctrl+F5
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/move")
def move_page():
    return FileResponse(STATIC / "move.html", headers={"Cache-Control": "no-cache"})


@app.get("/settings")
def settings_page():
    return FileResponse(STATIC / "settings.html", headers={"Cache-Control": "no-cache"})


@app.get("/hq-bar.js")
def hq_bar():
    return FileResponse(STATIC / "hq-bar.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/setup-card.js")
def setup_card():
    return FileResponse(STATIC / "setup-card.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/hq-tabs.js")
def hq_tabs():
    return FileResponse(STATIC / "hq-tabs.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/money-bar.js")
def money_bar():
    return FileResponse(STATIC / "money-bar.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/town-kit.js")
def town_kit():
    return FileResponse(STATIC / "town-kit.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/world.js")
def world():
    return FileResponse(STATIC / "world.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/football-town.js")
def football_town():
    return FileResponse(STATIC / "football-town.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/football-panel.js")
def football_panel():
    return FileResponse(STATIC / "football-panel.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


class PauseIn(BaseModel):
    paused: bool


@app.get("/api/pause")
def pause_status():
    """Paused or not, and how long since the agents' background loop last went round (None = not started yet)."""
    from .agents.chad.publish import paused
    from .worker import seconds_since_last_round
    ago = seconds_since_last_round()
    return {"paused": paused(), "standby": standby.info(), "clash": None if standby.is_standby() else standby.clash(),
            "worker_seconds_ago": None if ago is None else round(ago)}


@app.post("/api/pause")
def pause(body: PauseIn):
    """Pause All: stops every agent and all posting until Resume. The Boss still chats."""
    from .agents.chad.publish import paused
    settings.save({"HQ_PAUSED": "true" if body.paused else "false"})
    db.log("Steven", "Paused HQ: no agent works and nothing posts" if body.paused else "Resumed HQ")
    return {"paused": paused()}


@app.get("/api/state")
def state():
    from .agents.chad.publish import paused
    running = {r["agent"]: r["instructions"] for r in db.rows("SELECT agent, instructions FROM tasks WHERE status = 'running'")}
    return {
        "has_llm": HAS_LLM,
        "paused": paused(),
        "spend": ledger.summary(),
        "money": money.summary(),
        "campaigns": campaigns.summary(),
        "scout_inbox": discovery.inbox(),
        "creator_picks": creators.pending(),
        "allowed_creators": creators.allowed(),
        "approvals": [{**a, "village": village_of(a["agent"])} for a in approvals.pending()],
        "football": football.state(),
        "tally": _tally_summary(),
        "leads": db.rows("SELECT id, name, platform, handle, contact, status, followups, followup_at FROM leads "
                         "ORDER BY id DESC LIMIT 50"),
        "agents": [{"name": "Boss", "role": "Directs the team and reports to you.", "doing": None, "village": "business"}] +
                  [{"name": a.name, "role": a.role, "doing": running.get(a.name), "village": a.village}
                   for a in agents.AGENTS.values()],
        "counts": {r["status"]: r["n"] for r in db.rows("SELECT status, COUNT(*) n FROM clips GROUP BY status")},
        "pending": db.rows("SELECT * FROM clips WHERE status = 'pending_approval' ORDER BY score DESC, id"),
        "clips": _library(),
        "tasks": db.rows("SELECT * FROM tasks ORDER BY id DESC LIMIT 20"),
        "posts": db.rows("SELECT * FROM posts ORDER BY id DESC LIMIT 20"),
        "activity": db.rows("SELECT * FROM activity ORDER BY id DESC LIMIT 40"),
        "chat": [m for m in boss.history(boss.current_conversation())
                 if not boss.is_recap(m) and isinstance(m["content"], list) and any(b.get("type") == "text" for b in m["content"])
                 and not any(b.get("type") == "tool_result" for b in m["content"])],
    }


@app.post("/api/chat")
def chat(body: ChatIn):
    try:
        return {"reply": boss.chat(body.text)}
    except Exception as e:  # show the problem in the chat instead of failing silently
        return {"reply": f"Something went wrong talking to Claude: {e}"}


@app.post("/api/conversation/new")
def new_conversation():
    return {"conversation": boss.new_conversation()}


@app.post("/api/tasks")
def add_task(body: TaskIn):
    if not agents.get(body.agent):
        raise HTTPException(404, f"No agent called {body.agent}")
    return {"task_id": db.create_task(body.agent, body.instructions, body.params, created_by="Steven")}


class SubmissionIn(BaseModel):
    views: int | None = None
    earned_usd: float | None = None
    status: str | None = None


@app.post("/api/campaigns/{campaign_id}/{decision}")
def decide_campaign(campaign_id: int, decision: str):
    if decision not in ("join", "skip"):
        raise HTTPException(400, "decision must be join or skip")
    try:
        return {"message": campaigns.decide(campaign_id, decision)}
    except ValueError as e:
        raise HTTPException(404, str(e))


class MoneyIn(BaseModel):
    kind: str
    amount_usd: float
    note: str = ""
    day: str | None = None


@app.post("/api/money")
def add_money(body: MoneyIn, request: Request):
    _from_hq_page(request)
    try:
        entry_id = money.add(body.kind, body.amount_usd, body.note, body.day)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": entry_id, "money": money.summary()}


@app.delete("/api/money/{entry_id}")
def delete_money(entry_id: int, request: Request):
    _from_hq_page(request)
    try:
        money.delete(entry_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"money": money.summary()}


class InboxIn(BaseModel):
    text: str


@app.post("/api/scout/inbox")
def scout_inbox(body: InboxIn):
    n = discovery.add_to_inbox(body.text)
    if not n:
        raise HTTPException(400, "Paste a campaign link or its rules first")
    db.create_task("Scout", "Rate what was pasted into the inbox.", {"discover": True}, created_by="Steven")
    return {"message": f"Added {n} to Scout's inbox. Scout is rating it now."}


class PermitIn(BaseModel):
    how: str


class AddCreatorIn(BaseModel):
    login: str
    how: str


@app.post("/api/creators/add")
def add_creator(body: AddCreatorIn):
    try:
        return {"message": creators.add_allowed(body.login, body.how)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/creators/{pick_id}/skip")
def skip_creator(pick_id: int):
    try:
        return {"message": creators.skip(pick_id)}
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/creators/{pick_id}/permit")
def permit_creator(pick_id: int, body: PermitIn):
    try:
        return {"message": creators.permit(pick_id, body.how)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/campaigns/{campaign_id}/submissions")
def campaign_submissions(campaign_id: int):
    return db.rows("SELECT * FROM submissions WHERE campaign_id = ? ORDER BY id DESC", campaign_id)


@app.post("/api/submissions/{submission_id}")
def update_submission(submission_id: int, body: SubmissionIn):
    try:
        campaigns.record(submission_id, body.views, body.earned_usd, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/tally/report")
def tally_report():
    return {"task_id": db.create_task("Tally", "Count views and send the daily view report now.", {"report": True}, created_by="Steven")}


@app.post("/api/pitch/recheck")
def pitch_recheck():
    db.create_task("Pitch", "Look for emails for pitches waiting for approval that have none.", {"recheck": True}, created_by="Steven")
    return {"message": "Pitch is looking for emails now. Cards update when it finds one."}


@app.post("/api/approvals/{approval_id}/{decision}")
def decide_approval(approval_id: int, decision: str):
    if decision not in ("approve", "reject"):
        raise HTTPException(400, "decision must be approve or reject")
    try:
        return {"message": approvals.decide(approval_id, decision)}
    except ValueError as e:
        raise HTTPException(404, str(e))


class LeadIn(BaseModel):
    status: str


@app.post("/api/leads/{lead_id}")
def update_lead(lead_id: int, body: LeadIn):
    from .agents.pitch.agent import STATUSES, set_status
    if body.status not in STATUSES:
        raise HTTPException(400, f"status must be one of {', '.join(STATUSES)}")
    try:
        set_status(lead_id, body.status)
    except KeyError:
        raise HTTPException(404, f"No lead #{lead_id}")
    return {"ok": True}


class YesIn(BaseModel):
    how: str = ""


@app.post("/api/leads/{lead_id}/yes")
def lead_said_yes(lead_id: int, body: YesIn):
    from .agents.pitch.agent import they_said_yes
    try:
        return {"ok": True, "message": they_said_yes(lead_id, body.how)}
    except KeyError:
        raise HTTPException(404, f"No lead #{lead_id}")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/clips/{clip_id}/retry")
def retry_clip(clip_id: int):
    from .agents.chad.publish import retry
    try:
        return {"message": retry(clip_id)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/clips/{clip_id}/{decision}")
def decide(clip_id: int, decision: str):
    if decision not in ("approve", "reject"):
        raise HTTPException(400, "decision must be approve or reject")
    status = "approved" if decision == "approve" else "rejected"
    db.set_clip_status(clip_id, status)
    db.log("Steven", f"Clip #{clip_id} {status}")
    return {"clip_id": clip_id, "status": status}


@app.patch("/api/clips/{clip_id}")
def edit_clip(clip_id: int, body: ClipEdit):
    if body.title is not None:
        db.execute("UPDATE clips SET title = ? WHERE id = ?", body.title, clip_id)
    if body.caption is not None:
        db.execute("UPDATE clips SET caption = ? WHERE id = ?", body.caption, clip_id)
    return {"ok": True}


@app.get("/api/settings")
def get_settings():
    return settings.describe()


@app.post("/api/settings")
def save_settings(body: SettingsIn, request: Request):
    _from_hq_page(request)
    try:
        changed = settings.save(body.values) + settings.save_pitch(body.pitch)
        for name, enabled in body.accounts.items():
            settings.set_account_enabled(name, enabled)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    if changed or body.accounts:
        db.log("Steven", "Changed settings: " + ", ".join(changed + [f"{n} account" for n in body.accounts]))
    return {"changed": changed}


@app.post("/api/test/{name}")
def test_connection(name: str, body: TestIn, request: Request):
    """One harmless call to a service (the Test buttons). Typed-but-unsaved keys are tested as typed."""
    _from_hq_page(request)
    return connections.run(name, body.values)


class TikTokIn(BaseModel):
    answer: str


@app.get("/api/tiktok/login")
def tiktok_login(request: Request):
    _from_hq_page(request)
    try:
        return {"url": tiktok_auth.authorize_url()}
    except tiktok_auth.TikTokError as e:
        raise HTTPException(400, str(e))


@app.post("/api/tiktok/connect")
def tiktok_connect(body: TikTokIn, request: Request):
    _from_hq_page(request)
    try:
        message = tiktok_auth.connect(body.answer)
    except tiktok_auth.TikTokError as e:
        raise HTTPException(400, str(e))
    db.log("Steven", "Connected TikTok")
    return {"message": message, **tiktok_auth.status()}


@app.post("/api/tiktok/disconnect")
def tiktok_disconnect(request: Request):
    _from_hq_page(request)
    tiktok_auth.disconnect()
    db.log("Steven", "Disconnected TikTok")
    return tiktok_auth.status()


class InstagramIn(BaseModel):
    token: str


@app.post("/api/instagram/connect")
def instagram_connect(body: InstagramIn, request: Request):
    _from_hq_page(request)
    try:
        message = instagram_auth.connect(body.token)
    except instagram_auth.InstagramError as e:
        raise HTTPException(400, str(e))
    db.log("Steven", "Connected Instagram")
    return {"message": message, **instagram_auth.status()}


@app.post("/api/instagram/disconnect")
def instagram_disconnect(request: Request):
    _from_hq_page(request)
    instagram_auth.disconnect()
    db.log("Steven", "Disconnected Instagram")
    return instagram_auth.status()


class YouTubeIn(BaseModel):
    account: str
    text: str = ""


@app.get("/api/youtube")
def youtube_status(request: Request):
    _from_hq_page(request)
    return youtube_auth.status()


@app.post("/api/youtube/client")
def youtube_client(body: YouTubeIn, request: Request):
    _from_hq_page(request)
    try:
        return {"message": youtube_auth.save_client(body.account, body.text), "accounts": youtube_auth.status()}
    except youtube_auth.YouTubeError as e:
        raise HTTPException(400, str(e))


@app.post("/api/youtube/sign-in")
def youtube_sign_in(body: YouTubeIn, request: Request):
    _from_hq_page(request)
    try:
        return {"url": youtube_auth.start_sign_in(body.account), "accounts": youtube_auth.status()}
    except youtube_auth.YouTubeError as e:
        raise HTTPException(400, str(e))


@app.post("/api/youtube/connect")
def youtube_connect(body: YouTubeIn, request: Request):
    _from_hq_page(request)
    try:
        return {"message": youtube_auth.finish_sign_in(body.account, body.text), "accounts": youtube_auth.status()}
    except youtube_auth.YouTubeError as e:
        raise HTTPException(400, str(e))


@app.post("/api/youtube/disconnect")
def youtube_disconnect(body: YouTubeIn, request: Request):
    _from_hq_page(request)
    try:
        youtube_auth.disconnect(body.account)
    except youtube_auth.YouTubeError as e:
        raise HTTPException(400, str(e))
    db.log("Steven", f"Disconnected YouTube account {body.account}")
    return {"accounts": youtube_auth.status()}


@app.get("/api/setup")
def setup_status():
    setup_check.refresh_in_background()
    return setup_check.summary()


@app.post("/api/setup/check")
def setup_check_now(request: Request):
    _from_hq_page(request)
    connections.run_all()
    return setup_check.summary()


@app.post("/api/try-chad")
def try_chad(request: Request, video: UploadFile = File(...)):
    """Upload a video you made and have Chad clip it, to watch the whole chain work (it's your own content)."""
    _from_hq_page(request)
    name = Path(video.filename or "video.mp4").name
    if Path(name).suffix.lower() not in (".mp4", ".mov", ".mkv", ".webm", ".m4v"):
        raise HTTPException(400, "Pick a video file (mp4, mov, mkv or webm).")
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
    dest = SOURCES_DIR / f"try-{db.now().replace(':', '')[:15]}-{safe}"
    with dest.open("wb") as out:
        while chunk := video.file.read(1024 * 1024):
            out.write(chunk)
    task_id = db.create_task("Chad", f"Clip {name} (your own video, to try HQ out)",
                             {"file": str(dest), "creator": "You"}, created_by="Steven")
    return {"task_id": task_id}


# ---- Warrior Village (football) ----------------------------------------------------------------------

class FootballItemIn(BaseModel):
    item: str
    done: bool = True
    opponent: str | None = None


class FootballReportIn(BaseModel):
    opponent: str | None = None


class TextIn(BaseModel):
    text: str


class PauseIn(BaseModel):
    paused: bool


def _football_file(file_id: int) -> str:
    rows = db.rows("SELECT name FROM football_files WHERE id = ?", file_id)
    if not rows:
        raise HTTPException(404, f"No football file #{file_id}")
    return rows[0]["name"]


@app.post("/api/football/upload")
def football_upload(request: Request, file: UploadFile = File(...)):
    _from_hq_page(request)
    from .football import files
    try:
        result = files.save_upload(file.filename, file.file)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if result["kind"] == "sheet":
        for name in files.scan():
            db.create_task("Ref", f"Check {name}", {"file": name}, created_by="Steven")
    return result


@app.post("/api/football/files/{file_id}/check")
def football_check(file_id: int, request: Request):
    _from_hq_page(request)
    name = _football_file(file_id)
    db.execute("UPDATE football_files SET status = 'new' WHERE id = ?", file_id)
    return {"task_id": db.create_task("Ref", f"Check {name}", {"file": name}, created_by="Steven")}


@app.post("/api/football/files/{file_id}/report")
def football_report(file_id: int, body: FootballReportIn, request: Request):
    _from_hq_page(request)
    name = _football_file(file_id)
    params = {"file": name, **({"opponent": body.opponent.strip()} if body.opponent and body.opponent.strip() else {})}
    return {"task_id": db.create_task("Tells", f"Scouting report from {name}", params, created_by="Steven")}


@app.post("/api/football/checklist")
def football_checklist(body: FootballItemIn, request: Request):
    _from_hq_page(request)
    from .football import season
    try:
        return {"message": season.mark(body.item, body.done, body.opponent)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/football/print/now")
def football_print_now(request: Request):
    _from_hq_page(request)
    return {"task_id": db.create_task("Clock", "Print now", {"print": True}, created_by="Steven")}


@app.post("/api/football/print/folders")
def football_print_folders(request: Request):
    _from_hq_page(request)
    from .football import printing
    made = printing.ensure_folders()
    return {"message": ("Made folders for " + ", ".join(made) + ".") if made else "Every opponent already has a folder.",
            "print": printing.state()}


@app.post("/api/football/tagsheet")
def football_tagsheet(request: Request, file: UploadFile = File(...)):
    _from_hq_page(request)
    from .football import tagsheet
    data = file.file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "That file is over 5 MB.")
    try:
        info = tagsheet.save(Path(file.filename or "tags.xlsx").name, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.log("Steven", f"Loaded the football tag sheet ({info['name']})")
    return {"message": f"Tag sheet loaded ({info['words']} words). Captain and Ref use it from now on.", "tagsheet": info}


@app.post("/api/football/tagsheet/clear")
def football_tagsheet_clear(request: Request):
    _from_hq_page(request)
    from .football import tagsheet
    tagsheet.clear()
    return {"message": "Tag sheet removed."}


@app.post("/api/football/print/pause")
def football_print_pause(body: PauseIn, request: Request):
    _from_hq_page(request)
    from .football import printing
    return {"message": printing.set_paused(body.paused), "print": printing.state()}


@app.post("/api/football/note")
def football_note(body: TextIn, request: Request):
    _from_hq_page(request)
    from .agents.football.scribe import note
    text = body.text.strip()
    return {"message": note(text if football.notebook.is_nb(text) else "NB: " + text, source="dashboard")}


@app.get("/api/football/notebook")
def football_notebook():
    return [{"id": n["id"], "tab": n["tab"], "text": football.notebook.shown(n)} for n in football.notebook.notes()]


@app.get("/api/football/notebook.md")
def football_notebook_md():
    return Response(football.notebook.export_markdown(), media_type="text/markdown",
                    headers={"Content-Disposition": 'attachment; filename="Coaching Notebook.md"'})


@app.get("/api/football/rulebook")
def football_rulebook():
    return {"loaded": football.rulebook.loaded(), "text": football.rulebook.text() if football.rulebook.loaded() else ""}


@app.post("/api/football/rulebook")
def football_rulebook_save(body: TextIn, request: Request):
    _from_hq_page(request)
    try:
        football.rulebook.save(body.text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.log("Steven", "Updated the football rulebook")
    return {"message": "Rulebook saved."}


@app.get("/api/football/outbox/{name}")
def football_outbox_file(name: str):
    path = (FOOTBALL_OUTBOX / Path(name).name).resolve()
    if path.parent != FOOTBALL_OUTBOX.resolve() or not path.is_file():
        raise HTTPException(404, "Not in the football Outbox")
    return FileResponse(path, filename=path.name)


@app.get("/api/update")
def update_status(refresh: bool = False):
    return update.check(force=refresh)


@app.post("/api/update")
def install_update(request: Request):
    _from_hq_page(request)
    if not update.update():
        status = update.check(force=True)
        return {"updated": False, "message": status["error"] or "HQ is already up to date."}
    db.log("Steven", "Updated HQ to the newest version")
    update.restart()
    return {"updated": True, "message": "Updated. HQ is restarting."}


@app.post("/api/restart")
def restart(request: Request):
    _from_hq_page(request)
    update.restart()
    return {"restarting": True}


# ---- moving HQ to another computer (see move.py) ------------------------------------------------------------------

_move_job: dict = {"running": False, "steps": [], "error": None, "result": None}


class MoveIn(BaseModel):
    url: str = ""
    password: str = ""


class CloudScriptIn(BaseModel):
    tailscale_key: str


def _passwords(typed: str) -> list[str]:
    """What to log in to the other HQ with: what you typed, else a new server's one-time code, else your password."""
    if typed.strip():
        return [typed.strip()]
    code = [move.move_code()] if move.MOVE_CODE.exists() else []
    return code + ([PASSWORD] if PASSWORD else [])


@app.get("/api/move/ready")
def move_ready():
    """The other HQ asks this (logged in) before it sends itself here."""
    return {"ready": standby.is_standby(), "standby": standby.info()}


@app.get("/api/move/status")
def move_status():
    return {"standby": standby.info(), "role": standby.role(), "last": move.last(), "job": _move_job,
            "password_set": bool(PASSWORD), "peer": standby.peer_url(), "clash": standby.clash(),
            "family": move.family(), "has_move_code": move.MOVE_CODE.exists()}


@app.get("/api/move/find")
def move_find():
    """HQ servers on your Tailscale network, and whether each is ready to take your HQ."""
    import requests
    found = []
    for s in move.find_servers():
        try:
            h = requests.get(f"{s['url']}/healthz", timeout=4).json()
        except Exception:
            h = {}
        found.append({**s, "answering": bool(h.get("ok")), "role": h.get("role"), "waiting": bool(h.get("waiting"))})
    return {"servers": found}


@app.post("/api/move/check")
def move_check(body: MoveIn):
    last_error = "Set a dashboard password in Settings first (HQ_PASSWORD): the cloud HQ needs one."
    for pw in _passwords(body.password):
        try:
            return {"ok": True, **move.check_target(body.url, pw)}
        except move.MoveError as e:
            last_error = str(e)
            if "password" not in last_error:
                break
    raise HTTPException(400, last_error)


@app.post("/api/move/start")
def move_start(body: MoveIn):
    if _move_job["running"]:
        raise HTTPException(409, "A move is already going.")
    if not PASSWORD:
        raise HTTPException(400, "Set a dashboard password in Settings first (HQ_PASSWORD). The cloud HQ uses it.")
    import threading

    def go():
        _move_job.update(running=True, steps=[], error=None, result=None)
        try:
            for pw in _passwords(body.password):
                try:
                    _move_job["result"] = move.send_to(body.url, pw, progress=_move_job["steps"].append)
                    break
                except move.MoveError as e:
                    if "didn't accept the password" not in str(e):
                        raise
                    _move_job["error"] = str(e)
            else:
                raise move.MoveError(_move_job["error"] or "No password to log in with.")
            _move_job["error"] = None
        except Exception as e:
            _move_job["error"] = str(e)
        finally:
            _move_job["running"] = False
    threading.Thread(target=go, daemon=True, name="move").start()
    return {"started": True}


@app.post("/api/move/in")
async def move_in(request: Request, bundle: UploadFile = File(...), port: str = Form("8000")):
    """The other HQ sends itself here. Only a standby HQ takes it; it then runs the agents and restarts."""
    if not standby.is_standby():
        raise HTTPException(409, "This HQ is running the agents, so it won't take another copy over it.")
    dest = move.DATA_DIR / "move-in.zip"
    total = 0
    with open(dest, "wb") as out:
        while chunk := await bundle.read(4 * 1024 * 1024):
            total += len(chunk)
            if total > move.UPLOAD_LIMIT:
                raise HTTPException(413, "That's too big to move in one go.")
            out.write(chunk)
    host = request.client.host if request.client else ""
    from_url = (f"http://[{host}]:{int(port)}" if ":" in host else f"http://{host}:{int(port)}") if host else ""
    try:
        manifest = move.take_in(dest, from_url)
    except move.MoveError as e:
        raise HTTPException(400, str(e))
    finally:
        dest.unlink(missing_ok=True)
    update.restart(delay=2)
    return {"ok": True, "bundle_id": manifest.get("bundle_id", "")}


@app.post("/api/move/cloud-script")
def move_cloud_script(body: CloudScriptIn):
    if not PASSWORD:
        raise HTTPException(400, "Set a dashboard password in Settings first (HQ_PASSWORD). The cloud HQ uses it.")
    try:
        return {"script": move.cloud_script(body.tailscale_key)}
    except move.MoveError as e:
        raise HTTPException(400, str(e))


# ---- Google Drive folders on the cloud server (see drive_sync.py) --------------------------------------------------

class DriveIn(BaseModel):
    text: str = ""


@app.get("/api/drive")
def drive_status():
    return drive_sync.status()


@app.post("/api/drive/client")
def drive_client(body: DriveIn):
    try:
        return {"message": drive_sync.save_client(body.text)}
    except drive_sync.DriveError as e:
        raise HTTPException(400, str(e))


@app.post("/api/drive/sign-in")
def drive_sign_in():
    try:
        return {"url": drive_sync.start_sign_in()}
    except drive_sync.DriveError as e:
        raise HTTPException(400, str(e))


@app.post("/api/drive/connect")
def drive_connect(body: DriveIn):
    try:
        message = drive_sync.finish_sign_in(body.text)
    except drive_sync.DriveError as e:
        raise HTTPException(400, str(e))
    db.log("Steven", "Connected Google Drive")
    import threading
    threading.Thread(target=drive_sync.run_once, daemon=True).start()
    return {"message": message}


@app.post("/api/drive/disconnect")
def drive_disconnect():
    drive_sync.disconnect()
    db.log("Steven", "Disconnected Google Drive")
    return drive_sync.status()


@app.post("/api/drive/sync")
def drive_sync_now():
    drive_sync.run_once()
    return drive_sync.status()
