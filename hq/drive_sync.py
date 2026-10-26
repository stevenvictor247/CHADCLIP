"""Your football folders in Google Drive, on the cloud server.

On the PC, Google Drive for desktop keeps folders like "2026 WSU FOOTBALL" in sync and HQ reads them like any folder.
The cloud server has no Drive for desktop, so HQ syncs those same Drive folders itself, every few minutes:
- a file added or changed in Drive (from any of your computers or your phone) comes down to the server;
- a file HQ makes there (an opponent folder, a Ref copy, a scouting report) goes up to Drive;
- nothing is ever deleted on either side. If a file changed on both sides, Drive's version wins and HQ's is kept
  beside it as "name (HQ copy)".
Google Docs, Sheets and Slides come down as Word, Excel and PowerPoint files, so Ref can read them and the Thursday
print can print them (on the PC a Google Doc can't print at all).

Which folders: moving HQ from the PC brings them (HQ_DRIVE_FOLDERS, filled in from the PC's folder settings when they
were inside "My Drive"). Connect once on the Settings page, with the same Google client file as YouTube.
Daily backups also get a copy in "My Drive/Agent HQ backups" (without your keys), so a lost server loses nothing.
"""

import io
import json
import os
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import CONFIG_DIR, DATA_DIR

LOCAL_ROOT = DATA_DIR / "drive"          # the Drive folders, mirrored here by their Drive path
STATE_PATH = DATA_DIR / "drive-sync.json"
TOKEN_PATH = CONFIG_DIR / "secrets" / "drive_token.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]
REDIRECT = "http://localhost:8080/"
EVERY = 3 * 60                           # seconds between syncs
BACKUP_FOLDER = "My Drive/Agent HQ backups"
FOLDER = "application/vnd.google-apps.folder"
EXPORTS = {   # Google's own files, saved as the Office file of the same kind
    "application/vnd.google-apps.document": (".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "application/vnd.google-apps.spreadsheet": (".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "application/vnd.google-apps.presentation": (".pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
}
FIELDS = "nextPageToken, files(id, name, mimeType, modifiedTime, size)"

_pending: dict = {}
_status = {"last": None, "problem": None, "down": 0, "up": 0}


class DriveError(Exception):
    pass


# ---- which folders ----------------------------------------------------------------------------------------------

def local_folder(drive_path: str) -> Path:
    return LOCAL_ROOT.joinpath(*[p for p in drive_path.split("/") if p])


def folders() -> dict:
    try:
        data = json.loads(os.getenv("HQ_DRIVE_FOLDERS", "") or "{}")
        return {k: v for k, v in data.items() if isinstance(v, str) and v.startswith("My Drive")}
    except ValueError:
        return {}


def roots() -> list[str]:
    """The Drive folders to sync, leaving out any that sit inside another one on the list."""
    paths = sorted(set(folders().values()), key=len)
    out = []
    for p in paths:
        if not any(p == r or p.startswith(r + "/") for r in out):
            out.append(p)
    return out


def configured() -> bool:
    return bool(roots())


def connected() -> bool:
    return TOKEN_PATH.exists()


# ---- connecting (paste-back sign-in, like YouTube) --------------------------------------------------------------

def client_file() -> Path | None:
    secrets = CONFIG_DIR / "secrets"
    own = secrets / "drive_client_secret.json"
    if own.exists():
        return own
    found = sorted(secrets.glob("*_client_secret.json")) if secrets.exists() else []
    return found[0] if found else None


def save_client(text: str) -> str:
    try:
        data = json.loads(text)
    except ValueError:
        raise DriveError("That isn't the file from Google. Open the downloaded .json file and paste all of it.")
    if not isinstance(data, dict) or not (data.get("installed") or {}).get("client_id"):
        raise DriveError("That isn't a \"Desktop app\" client file from Google Cloud. Download that kind and paste it.")
    path = CONFIG_DIR / "secrets" / "drive_client_secret.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return "Saved. Now press Open Google sign-in."


def _flow():
    from google_auth_oauthlib.flow import Flow
    f = client_file()
    if not f:
        raise DriveError("Paste a Google client file first (the same kind as for YouTube).")
    return Flow.from_client_secrets_file(str(f), scopes=SCOPES, redirect_uri=REDIRECT)


def start_sign_in() -> str:
    flow = _flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    _pending.update(state=state, verifier=flow.code_verifier)
    return url


def finish_sign_in(answer: str) -> str:
    if not _pending:
        raise DriveError("Press Open Google sign-in first.")
    text = (answer or "").strip()
    code = text
    if "://" in text or "code=" in text:
        q = parse_qs(urlparse(text).query)
        if q.get("error"):
            raise DriveError(f"Google said no: {q['error'][0]}")
        if not q.get("code"):
            raise DriveError("That address has no code in it. Copy the whole address from the address bar.")
        if q.get("state") and q["state"][0] != _pending["state"]:
            raise DriveError("That address is from an older sign-in. Press Open Google sign-in again.")
        code = q["code"][0]
    flow = _flow()
    flow.code_verifier = _pending["verifier"]
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise DriveError(f"Google wouldn't accept that: {str(e)[:200]}. Press Open Google sign-in again.")
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(flow.credentials.to_json(), encoding="utf-8")
    _pending.clear()
    return "Google Drive is connected. Your football folders sync within a few minutes."


def disconnect() -> None:
    TOKEN_PATH.unlink(missing_ok=True)


def service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ---- syncing ----------------------------------------------------------------------------------------------------

def _state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(s: dict) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def _q(name: str) -> str:
    return name.replace("\\", "\\\\").replace("'", "\\'")


def _children(svc, folder_id: str) -> list[dict]:
    out, token = [], None
    while True:
        r = svc.files().list(q=f"'{folder_id}' in parents and trashed = false", fields=FIELDS, pageSize=1000,
                             pageToken=token, spaces="drive").execute()
        out += r.get("files", [])
        token = r.get("nextPageToken")
        if not token:
            return out


def _child_folder(svc, parent: str, name: str, create: bool = False) -> str | None:
    r = svc.files().list(q=f"'{parent}' in parents and name = '{_q(name)}' and mimeType = '{FOLDER}' and trashed = false",
                         fields="files(id)", spaces="drive").execute().get("files", [])
    if r:
        return r[0]["id"]
    if not create:
        return None
    return svc.files().create(body={"name": name, "mimeType": FOLDER, "parents": [parent]}, fields="id").execute()["id"]


def folder_id(svc, drive_path: str, create: bool = False) -> str | None:
    """The Drive id of 'My Drive/A/B', or None if there's no such folder."""
    current = "root"
    for name in [p for p in drive_path.split("/") if p][1:]:
        current = _child_folder(svc, current, name, create)
        if not current:
            return None
    return current


def _stamp(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _download(svc, f: dict, dest: Path) -> None:
    from googleapiclient.http import MediaIoBaseDownload
    if f["mimeType"] in EXPORTS:
        req = svc.files().export_media(fileId=f["id"], mimeType=EXPORTS[f["mimeType"]][1])
    else:
        req = svc.files().get_media(fileId=f["id"])
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(buf.getvalue())
    os.replace(tmp, dest)
    t = _stamp(f["modifiedTime"])
    os.utime(dest, (t, t))   # the file keeps Drive's time, like Drive for desktop does


def _kept_aside(p: Path) -> Path:
    n, dest = 1, p.with_name(f"{p.stem} (HQ copy){p.suffix}")
    while dest.exists():
        n += 1
        dest = p.with_name(f"{p.stem} (HQ copy {n}){p.suffix}")
    return dest


def _skip(name: str) -> bool:
    return name.startswith(("~$", ".")) or name.endswith((".tmp", ".part", ".crdownload"))


def _pull(svc, fid: str, local: Path, rel: str, files: dict, counts: dict) -> None:
    local.mkdir(parents=True, exist_ok=True)
    for f in _children(svc, fid):
        if _skip(f["name"]) or "/" in f["name"]:
            continue
        if f["mimeType"] == FOLDER:
            _pull(svc, f["id"], local / f["name"], f"{rel}{f['name']}/", files, counts)
            continue
        if f["mimeType"].startswith("application/vnd.google-apps") and f["mimeType"] not in EXPORTS:
            continue   # forms, shortcuts, maps: nothing to bring down
        name = f["name"] + (EXPORTS[f["mimeType"]][0] if f["mimeType"] in EXPORTS and
                            not f["name"].lower().endswith(EXPORTS[f["mimeType"]][0]) else "")
        key, dest = rel + name, local / name
        known = files.get(key, {})
        if known.get("modified") == f["modifiedTime"] and dest.exists():
            continue
        if dest.exists() and (not known or abs(dest.stat().st_mtime - known.get("local", 0)) > 1):
            os.replace(dest, _kept_aside(dest))   # changed here and in Drive: Drive wins, HQ's copy stays beside it
        try:
            _download(svc, f, dest)
        except Exception as e:   # one file that won't come down mustn't stop the rest
            counts["problems"].append(f"Couldn't bring down {key}: {str(e)[:150]}")
            continue
        files[key] = {"id": f["id"], "modified": f["modifiedTime"], "local": dest.stat().st_mtime,
                      "native": f["mimeType"] in EXPORTS}
        counts["down"] += 1


def _push(svc, fid: str, local: Path, rel: str, files: dict, counts: dict, ids: dict) -> None:
    from googleapiclient.http import MediaFileUpload
    for p in sorted(local.iterdir()):
        if _skip(p.name):
            continue
        key = rel + p.name
        if p.is_dir():
            sub = ids.get(key) or _child_folder(svc, fid, p.name, create=True)
            ids[key] = sub
            _push(svc, sub, p, key + "/", files, counts, ids)
            continue
        known = files.get(key)
        mtime = p.stat().st_mtime
        if known and (known.get("native") or abs(mtime - known.get("local", 0)) <= 1):
            continue   # unchanged here (a Google Doc's Word copy is never sent back over the Doc)
        try:
            media = MediaFileUpload(str(p), resumable=p.stat().st_size > 5 * 1024 * 1024)
            if known and known.get("id"):
                r = svc.files().update(fileId=known["id"], media_body=media, fields="id, modifiedTime").execute()
            else:
                r = svc.files().create(body={"name": p.name, "parents": [fid]}, media_body=media,
                                       fields="id, modifiedTime").execute()
        except Exception as e:
            counts["problems"].append(f"Couldn't send up {key}: {str(e)[:150]}")
            continue
        files[key] = {"id": r["id"], "modified": r["modifiedTime"], "local": mtime, "native": False}
        counts["up"] += 1


def sync_once(svc=None) -> dict:
    """One round for every folder. Returns {"down": n, "up": n, "problems": [...]}."""
    svc = svc or service()
    state = _state()
    counts = {"down": 0, "up": 0, "problems": []}
    problems = counts["problems"]
    for root in roots():
        rs = state.setdefault(root, {"id": None, "files": {}, "folders": {}})
        rs["id"] = rs.get("id") or folder_id(svc, root)
        if not rs["id"]:
            problems.append(f"There's no Drive folder \"{root}\" any more. Was it renamed or moved?")
            continue
        local = local_folder(root)
        _pull(svc, rs["id"], local, "", rs["files"], counts)
        _push(svc, rs["id"], local, "", rs["files"], counts, rs.setdefault("folders", {}))
        _save(state)
    return counts


def run_once() -> None:
    from . import db
    from .standby import blocked
    if not (configured() and connected()) or blocked():
        return
    try:
        r = sync_once()
        _status.update(last=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       problem="; ".join(r["problems"]) or None, down=r["down"], up=r["up"])
        if r["down"] or r["up"]:
            db.log("HQ", f"Google Drive sync: {r['down']} file(s) down, {r['up']} up")
    except Exception as e:
        traceback.print_exc()
        text = str(e)
        if "accessNotConfigured" in text or "has not been used" in text or "is disabled" in text:
            text = ("Google Drive API is off in your Google Cloud project. Turn it on at "
                    "console.cloud.google.com/apis/library/drive.googleapis.com, then wait a minute.")
        _status["problem"] = f"Drive sync failed: {text[:300]}"


def start_in_background() -> None:
    def loop():
        while True:
            run_once()
            time.sleep(EVERY)
    threading.Thread(target=loop, daemon=True, name="drive-sync").start()


def status() -> dict:
    import sys
    return {"configured": configured(), "connected": connected(), "has_client": bool(client_file()),
            "on_windows": sys.platform == "win32",
            "folders": roots(), "waiting": bool(_pending), **_status}


# ---- backups ----------------------------------------------------------------------------------------------------

def upload_backup(path: Path, keep: int = 14) -> None:
    """Put a backup zip (the copy without keys) in My Drive/Agent HQ backups and keep the newest `keep` there."""
    from googleapiclient.http import MediaFileUpload
    svc = service()
    fid = folder_id(svc, BACKUP_FOLDER, create=True)
    svc.files().create(body={"name": path.name, "parents": [fid]},
                       media_body=MediaFileUpload(str(path), resumable=True), fields="id").execute()
    old = sorted((f for f in _children(svc, fid) if f["name"].startswith("hq-backup-")), key=lambda f: f["name"])
    for f in old[:-keep]:
        svc.files().update(fileId=f["id"], body={"trashed": True}).execute()   # Drive's trash keeps it 30 more days
