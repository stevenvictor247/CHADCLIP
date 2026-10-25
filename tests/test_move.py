"""Running HQ in the cloud: standby, the peer check, moving HQ between computers, printing by email, the Google Drive
sync, the watchdog and rollback. The rule behind most of these: the PC and the cloud must never both post."""

import importlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
import zipfile
from email import message_from_bytes
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_ENV_KEYS = ("HQ_DATA_DIR", "HQ_PASSWORD", "HQ_PEER_URL", "HQ_PAUSED", "HQ_TZ", "HQ_DRIVE_FOLDERS", "HQ_PRINTER_EMAIL",
             "HQ_FOOTBALL_DIR", "HQ_PRINT_DIR", "HQ_AUTO_UPDATE", "TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY",
             "HQ_BACKUP_COPY_DIR", "HQ_SAVED_PATHS", "PITCH_EMAIL_ADDRESS", "PITCH_EMAIL_APP_PASSWORD")
_ORIGINAL = {k: os.environ.get(k) for k in _ENV_KEYS}


@pytest.fixture(autouse=True)
def _back_to_normal():
    """Put HQ back on the shared test data folder afterwards, so tests in other files see what they expect."""
    yield
    for k, v in _ORIGINAL.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    import hq.config, hq.db, hq.standby, hq.settings, hq.update, hq.drive_sync, hq.move, hq.health, hq.backup, hq.api
    for m in (hq.config, hq.db, hq.standby, hq.settings, hq.update, hq.drive_sync, hq.move, hq.health, hq.backup,
              hq.api):
        importlib.reload(m)
    hq.db.init()


def _fresh(monkeypatch, tmp_path, password=""):
    data = tmp_path / "data"
    monkeypatch.setenv("HQ_DATA_DIR", str(data))
    monkeypatch.setenv("HQ_PASSWORD", password)
    for k in ("HQ_PEER_URL", "HQ_PAUSED", "HQ_TZ", "HQ_DRIVE_FOLDERS", "HQ_PRINTER_EMAIL", "HQ_FOOTBALL_DIR",
              "HQ_PRINT_DIR", "HQ_AUTO_UPDATE", "TELEGRAM_BOT_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    import hq.config, hq.db, hq.standby, hq.settings, hq.update, hq.drive_sync, hq.move, hq.health, hq.relay
    import hq.backup, hq.worker, hq.agents.chad.publish, hq.agents.pitch.mailer, hq.football.printing, hq.api
    for m in (hq.config, hq.db, hq.standby, hq.settings, hq.update, hq.drive_sync, hq.move, hq.health, hq.backup,
              hq.api):
        importlib.reload(m)
    # Modules other tests hold on to aren't reloaded; their data paths are pointed at this test's folder instead.
    p = hq.football.printing
    monkeypatch.setattr(p, "FOOTBALL_PRINT_DIR", hq.config.FOOTBALL_PRINT_DIR)
    monkeypatch.setattr(p, "FOOTBALL_DATA", hq.config.FOOTBALL_DATA)
    monkeypatch.setattr(p, "STATE_PATH", hq.config.FOOTBALL_DATA / "print.json")
    monkeypatch.setattr(p, "FOOTBALL_PRINTER_EMAIL", "")
    monkeypatch.setattr(hq.worker, "STATE_PATH", data / "worker_state.json")
    monkeypatch.setattr(hq.worker, "ALIVE_PATH", data / "worker_alive.txt")
    monkeypatch.setattr(hq.worker, "_clash", {"reason": None})
    monkeypatch.setattr(hq.relay, "polling", __import__("threading").Event())
    hq.db.init()
    # This copy's code folder: config/ and .env are written here by a restore, never into the real repo.
    root = tmp_path / "root"
    (root / "config" / "secrets").mkdir(parents=True)
    (root / "config" / "vision.md").write_text("be funny\n")
    (root / "config" / "secrets" / "yt_token.json").write_text('{"t": "yt"}')
    for m in (hq.move,):
        monkeypatch.setattr(m, "ROOT", root)
        monkeypatch.setattr(m, "CONFIG_DIR", root / "config")
    return hq


def _clip(hq, status, name, data=b"video"):
    path = hq.config.CLIPS_DIR / name
    path.write_bytes(data)
    return hq.db.execute("INSERT INTO clips (task_id, creator, source_url, title, start_s, end_s, path, status, created_at) "
                         "VALUES (1, 'Jynxzi', 'u', 't', 0, 10, ?, ?, ?)", str(path), status, hq.db.now())


# ---- standby -------------------------------------------------------------------------------------------------------

def test_standby_copy_is_read_only_and_does_nothing(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    c = TestClient(hq.api.app)
    tid = hq.db.create_task("Chad", "x", {}, created_by="Steven")
    _clip(hq, "approved", "a.mp4")
    hq.standby.set_standby(True, reason="moved", moved_to="http://100.1.2.3:8000/")
    hq.worker.tick()
    assert hq.db.rows("SELECT status FROM tasks WHERE id = ?", tid)[0]["status"] == "queued"
    assert hq.agents.chad.publish.publish_approved()[0].startswith("Nothing posted")
    assert not hq.db.rows("SELECT 1 FROM posts")
    s = c.get("/api/pause").json()["standby"]
    assert s["reason"] == "moved" and s["moved_to"] == "http://100.1.2.3:8000"
    r = c.post("/api/clips/1/reject", headers={"X-HQ": "1"})
    assert r.status_code == 409 and "100.1.2.3" in r.json()["detail"]
    assert c.post("/api/pause", json={"paused": True}, headers={"X-HQ": "1"}).status_code == 409
    assert c.get("/api/state").status_code == 200        # still shows everything
    assert c.get("/api/move/status").status_code == 200  # and the move page works
    with pytest.raises(hq.agents.pitch.mailer.SendError):
        hq.agents.pitch.mailer.send(object())
    assert hq.football.printing.print_now().startswith("Nothing printed")
    hq.standby.set_standby(False)
    assert c.post("/api/clips/1/reject", headers={"X-HQ": "1"}).status_code == 200


def test_standby_flag_and_identity_never_travel_in_backups_or_moves(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    hq.standby.set_standby(True)
    hq.standby.instance()
    names = zipfile.ZipFile(hq.backup.make_backup()).namelist()
    out = tmp_path / "m.zip"
    hq.move.make_bundle(out)
    names += zipfile.ZipFile(out).namelist()
    assert not any(n.endswith(("standby.json", "instance.json")) for n in names)


def test_healthz_is_open_without_login_and_says_the_role(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path, password="pw")
    c = TestClient(hq.api.app)
    assert c.get("/api/state").status_code == 401
    h = c.get("/healthz").json()
    assert h["ok"] and h["role"] == "active" and h["instance"] and "HQ_PASSWORD" not in json.dumps(h)
    hq.standby.set_standby(True, reason="waiting")
    h = c.get("/healthz").json()
    assert h["role"] == "standby" and h["waiting"] is True


def test_peer_check_stops_the_copy_that_took_over_last(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(hq.relay, "notify", sent.append)
    monkeypatch.setenv("HQ_PEER_URL", "http://100.9.9.9:8000")
    me = hq.standby.instance()
    peer = {"ok": True, "role": "active", "instance": "other", "active_since": "2020-01-01T00:00:00+00:00"}
    monkeypatch.setattr(hq.standby, "_ask_peer", lambda url: peer)
    assert "also running the agents" in hq.standby.clash()     # they were first: this one steps back
    hq.db.create_task("Scout", "x", {}, created_by="Steven")
    _clip(hq, "approved", "b.mp4")
    hq.worker.tick()
    hq.worker.tick()
    assert hq.db.rows("SELECT status FROM tasks")[0]["status"] == "queued"
    assert hq.agents.chad.publish.publish_approved()[0].startswith("Nothing posted")
    assert len(sent) == 1 and "also running" in sent[0]        # told once, not every round
    # The other copy goes on standby: this one carries on and says so.
    peer["role"] = "standby"
    hq.standby._peer_cache.clear()
    assert hq.standby.clash() is None
    hq.worker.tick()
    assert "carries on" in sent[1]
    # The other one took over later than this one: it's the one that steps back, so this one keeps going.
    peer.update(role="active", active_since="2999-01-01T00:00:00+00:00")
    hq.standby._peer_cache.clear()
    assert hq.standby.clash() is None
    # Can't reach the other copy (the PC is off): nothing changes.
    monkeypatch.setattr(hq.standby, "_ask_peer", lambda url: None)
    hq.standby._peer_cache.clear()
    assert hq.standby.clash() is None
    assert me["id"] == hq.standby.instance()["id"]


def test_relay_on_standby_confirms_what_it_handled_and_stops_listening(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    calls, handled = [], []
    monkeypatch.setattr(hq.relay, "api", lambda method, **p: calls.append((method, p)) or
                        [{"update_id": 7, "message": {}}, {"update_id": 8, "message": {}}])
    monkeypatch.setattr(hq.relay, "handle_update", handled.append)
    monkeypatch.setattr(hq.relay, "push_pending_clips", lambda: 0)
    assert hq.relay.poll_once(None, timeout=0) == 9 and len(handled) == 2 and hq.relay.polling.is_set()
    hq.standby.set_standby(True, reason="moving")
    calls.clear()
    assert hq.relay.poll_once(9, timeout=0) is None
    assert calls == [("getUpdates", {"offset": 9, "limit": 1, "timeout": 0})]   # marks 7 and 8 done, nothing more
    assert not hq.relay.polling.is_set()
    calls.clear()
    assert hq.relay.poll_once(None, timeout=0) is None and calls == []


def test_posts_in_progress_finish_before_a_move_or_restart(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    import threading
    got = []
    hq.standby.posting_lock.acquire()
    def wait_turn():
        got.append(hq.standby.posting_lock.acquire(timeout=5))
        hq.standby.posting_lock.release()
    t = threading.Thread(target=wait_turn)
    t.start()
    time.sleep(0.3)
    assert not got                        # waits while a post is going
    hq.standby.posting_lock.release()
    t.join()
    assert got == [True]


# ---- moving --------------------------------------------------------------------------------------------------------

def _pc_with_data(hq, tmp_path):
    """An HQ like Steven's PC: clips in every state, sign-ins, football data, a Drive folder setting, a password."""
    hq.db.log("Steven", "before the move")
    pend = _clip(hq, "pending_approval", "pending.mp4", b"P" * 100)
    _clip(hq, "approved", "approved.mp4", b"A" * 100)
    _clip(hq, "posted", "old-posted.mp4", b"O" * 100)
    _clip(hq, "rejected", "rejected.mp4", b"R" * 100)
    d = hq.config.DATA_DIR
    (d / "chad_seen.json").write_text('["abc"]')
    (d / "tiktok_tokens.json").write_text('{"refresh_token": "r1"}')
    (d / "worker_state.json").write_text('{"last_report": "2026-10-24"}')
    (d / "football" / "rulebook.md").write_text("rules")
    (d / "sources" / "big.mp4").write_bytes(b"x" * 1000)
    (d / "backups").mkdir(exist_ok=True)
    (d / "backups" / "old.zip").write_bytes(b"z")
    hq.settings.save({"ANTHROPIC_API_KEY": "sk-1", "HQ_FOOTBALL_DIR": r"G:\My Drive\Football",
                      "HQ_BACKUP_COPY_DIR": r"D:\Backups"})
    return pend


def test_move_zip_carries_everything_hq_needs_and_nothing_it_doesnt(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path, password="pw")
    _pc_with_data(hq, tmp_path)
    out = tmp_path / "move.zip"
    m = hq.move.make_bundle(out)
    names = set(zipfile.ZipFile(out).namelist())
    for need in ("data/hq.sqlite3", "data/settings.json", "data/chad_seen.json", "data/tiktok_tokens.json",
                 "data/worker_state.json", "data/football/rulebook.md", "data/clips/pending.mp4",
                 "data/clips/approved.mp4", "data/clips/old-posted.mp4", "config/vision.md",
                 "config/secrets/yt_token.json", "hq-move.json"):
        assert need in names, need
    for never in ("data/clips/rejected.mp4", "data/sources/big.mp4", "data/backups/old.zip"):
        assert never not in names, never
    settings = json.loads(zipfile.ZipFile(out).read("data/settings.json"))
    assert settings["HQ_PASSWORD"] == "pw"     # even when it only came from .env
    assert m["kind"] == "move" and m["platform"] and m["bundle_id"]


def test_clip_videos_that_still_need_posting_go_first(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    _pc_with_data(hq, tmp_path)
    monkeypatch.setattr(hq.move, "CLIP_BYTES_CAP", 250)
    out = tmp_path / "move.zip"
    m = hq.move.make_bundle(out)
    names = zipfile.ZipFile(out).namelist()
    assert "data/clips/pending.mp4" in names and "data/clips/approved.mp4" in names
    assert "data/clips/old-posted.mp4" not in names and m["clips_left_out"] == 1


def _windows_manifest(z_path, data_dir=r"C:\Users\gator\CHADCLIP\data"):
    """Make a move zip look like it came from Steven's Windows PC."""
    with zipfile.ZipFile(z_path) as z:
        items = {n: z.read(n) for n in z.namelist()}
    m = json.loads(items["hq-move.json"])
    m.update(platform="win32", data_dir=data_dir, root=r"C:\Users\gator\CHADCLIP", timezone="America/Detroit")
    items["hq-move.json"] = json.dumps(m).encode()
    db = Path(str(z_path) + ".db")
    db.write_bytes(items["data/hq.sqlite3"])
    with sqlite3.connect(db) as c:
        for cid, path in c.execute("SELECT id, path FROM clips").fetchall():
            c.execute("UPDATE clips SET path = ? WHERE id = ?", (data_dir + "\\clips\\" + Path(path).name, cid))
    items["data/hq.sqlite3"] = db.read_bytes()
    with zipfile.ZipFile(z_path, "w") as z:
        for n, b in items.items():
            z.writestr(n, b)
    return m


def test_moving_in_from_windows_fixes_paths_settings_and_time_zone(monkeypatch, tmp_path):
    pc = _fresh(monkeypatch, tmp_path / "pc", password="pw")
    pend = _pc_with_data(pc, tmp_path)
    out = tmp_path / "move.zip"
    pc.move.make_bundle(out)
    _windows_manifest(out)

    cloud = _fresh(monkeypatch, tmp_path / "cloud", password="one-time-code")
    real = cloud.move.family
    monkeypatch.setattr(cloud.move, "family", lambda platform=None: "linux" if platform is None else real(platform))
    cloud.standby.set_standby(True, reason="waiting")
    m = cloud.move.take_in(out, "http://100.64.0.5:8000")
    assert m["bundle_id"] and cloud.standby.info()["reason"] == "starting"   # takes over after its restart
    assert cloud.move.last()["moved_in"] == m["bundle_id"]

    d = cloud.config.DATA_DIR
    clip = cloud.db.rows("SELECT path FROM clips WHERE id = ?", pend)[0]["path"]
    assert clip == str(d / "clips" / "pending.mp4") and Path(clip).read_bytes() == b"P" * 100
    assert any(r["message"] == "before the move" for r in cloud.db.rows("SELECT message FROM activity"))
    assert json.loads((d / "chad_seen.json").read_text()) == ["abc"]
    assert (d / "tiktok_tokens.json").exists() and (d / "football" / "rulebook.md").read_text() == "rules"
    s = json.loads((d / "settings.json").read_text())
    assert s["HQ_PASSWORD"] == "pw" and s["ANTHROPIC_API_KEY"] == "sk-1" and s["HQ_TZ"] == "America/Detroit"
    assert s["HQ_PEER_URL"] == "http://100.64.0.5:8000"
    saved = json.loads(s["HQ_SAVED_PATHS"])["windows"]
    assert saved == {"HQ_FOOTBALL_DIR": r"G:\My Drive\Football", "HQ_BACKUP_COPY_DIR": r"D:\Backups"}
    assert "HQ_BACKUP_COPY_DIR" not in s                                   # a D:\ drive means nothing here
    assert json.loads(s["HQ_DRIVE_FOLDERS"]) == {"HQ_FOOTBALL_DIR": "My Drive/Football"}
    assert s["HQ_FOOTBALL_DIR"] == str(d / "drive" / "My Drive" / "Football")
    assert (cloud.move.ROOT / "config" / "vision.md").read_text() == "be funny\n"
    assert list(d.glob("before-move-*"))                                   # what was there is kept

    # HQ restarts: now it runs the agents.
    assert cloud.standby.finish_takeover() and not cloud.standby.is_standby()


def test_moving_back_to_the_pc_gives_its_folders_back(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    monkeypatch.setattr(hq.move, "family", lambda platform=None: "windows" if platform is None or platform.startswith("win") else "linux")
    settings = {"HQ_FOOTBALL_DIR": "/opt/agent-hq/data/drive/My Drive/Football", "HQ_DRIVE_FOLDERS": "{}",
                "HQ_SAVED_PATHS": json.dumps({"windows": {"HQ_FOOTBALL_DIR": r"G:\My Drive\Football"}})}
    out = hq.move.fix_settings(settings, {"platform": "linux"})
    assert out["HQ_FOOTBALL_DIR"] == r"G:\My Drive\Football" and "HQ_DRIVE_FOLDERS" not in out
    assert json.loads(out["HQ_SAVED_PATHS"])["linux"]["HQ_FOOTBALL_DIR"].startswith("/opt/")


def test_a_running_hq_never_takes_a_move_over_itself(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    out = tmp_path / "m.zip"
    hq.move.make_bundle(out)
    with pytest.raises(hq.move.MoveError):
        hq.move.take_in(out, "")
    c = TestClient(hq.api.app)
    r = c.post("/api/move/in", files={"bundle": ("m.zip", out.read_bytes())}, headers={"X-HQ": "1"})
    assert r.status_code == 409


def test_bad_zips_change_nothing(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    hq.db.log("Steven", "keep me")
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("data/hq.sqlite3", "x")
        z.writestr("../escape.txt", "x")
    nodb = tmp_path / "nodb.zip"
    with zipfile.ZipFile(nodb, "w") as z:
        z.writestr("config/a.yaml", "x")
    broken = tmp_path / "broken.zip"
    with zipfile.ZipFile(broken, "w") as z:
        z.writestr("data/hq.sqlite3", "this is not a database at all" * 100)
    for bad in (evil, nodb, broken, tmp_path / "missing.zip"):
        with pytest.raises((hq.move.MoveError, sqlite3.DatabaseError)):
            hq.move.apply_bundle(bad)
    assert not (tmp_path / "escape.txt").exists()
    assert any(r["message"] == "keep me" for r in hq.db.rows("SELECT message FROM activity"))


def test_a_plain_backup_comes_back_paused(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    backup = hq.backup.make_backup()
    m = hq.move.apply_bundle(backup)
    assert m["kind"] == "backup"
    assert json.loads(hq.config.SETTINGS_PATH.read_text())["HQ_PAUSED"] == "true"


def test_relocate_handles_windows_mac_and_unknown_paths(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    d = hq.config.DATA_DIR
    win = {"platform": "win32", "data_dir": r"C:\Users\gator\CHADCLIP\data", "root": r"C:\Users\gator\CHADCLIP"}
    assert hq.move.relocate(r"c:\users\GATOR\chadclip\data\clips\x.mp4", win) == str(d / "clips" / "x.mp4")
    mac = {"platform": "darwin", "data_dir": "/Users/s/CHADCLIP/data", "root": "/Users/s/CHADCLIP"}
    assert hq.move.relocate("/Users/s/CHADCLIP/data/clips/y.mp4", mac) == str(d / "clips" / "y.mp4")
    assert hq.move.relocate(r"E:\elsewhere\z.mp4", win) == r"E:\elsewhere\z.mp4"


def test_drive_paths_are_found_on_any_computer():
    from hq.move import _drive_path
    assert _drive_path(r"G:\My Drive\Football\2026 WSU FOOTBALL") == "My Drive/Football/2026 WSU FOOTBALL"
    assert _drive_path(r"C:\Users\gator\My Drive\WSU") == "My Drive/WSU"
    assert _drive_path("/Users/s/Library/CloudStorage/GoogleDrive-s@gmail.com/My Drive/WSU/") == "My Drive/WSU"
    assert _drive_path(r"C:\Users\gator\Documents\WSU") is None


def test_addresses_are_tidied_up():
    from hq.move import normalize_url
    assert normalize_url("100.1.2.3") == "http://100.1.2.3:8000"
    assert normalize_url("http://agent-hq:8000/") == "http://agent-hq:8000"
    assert normalize_url(" https://agent-hq.tail1.ts.net ") == "https://agent-hq.tail1.ts.net:8000"


def test_server_setup_text_needs_a_real_key_and_holds_a_one_time_password(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path, password="pw")
    with pytest.raises(hq.move.MoveError):
        hq.move.cloud_script("not a key")
    text = hq.move.cloud_script("tskey-auth-abc123-XYZ")
    code = hq.move.move_code()
    assert text.startswith("#!/bin/bash") and "tskey-auth-abc123-XYZ" in text and code in text
    assert "pw" not in text.replace("pwd", "")          # never your own password
    assert "HQ_WAITING=1" in text and "install.sh" in text and "github.com" in text
    assert hq.move.cloud_script("tskey-auth-abc123-XYZ").count(code) == 1   # same code until the move is done


class _FakeResp:
    def __init__(self, ok=True, data=None, status=200):
        self.ok, self._data, self.status_code, self.text = ok, data or {}, status, ""

    def json(self):
        return self._data


def test_failed_move_leaves_this_copy_running_unless_it_cant_tell(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path, password="pw")

    class Session:
        def post(self, url, **kw):
            return _FakeResp(False, {"detail": "disk full"}, 500)
    monkeypatch.setattr(hq.move, "_session", lambda url, pw: (Session(), {}))
    monkeypatch.setattr(hq.move, "_took_over", lambda url, bid: False)
    with pytest.raises(hq.move.MoveError, match="disk full.*carries on"):
        hq.move.send_to("100.1.1.1", "pw")
    assert not hq.standby.is_standby()

    monkeypatch.setattr(hq.move, "_took_over", lambda url, bid: None)    # the other side stopped answering
    with pytest.raises(hq.move.MoveError, match="stays on standby"):
        hq.move.send_to("100.1.1.1", "pw")
    assert hq.standby.info()["reason"] == "moving"


def test_successful_move_puts_this_copy_on_standby_pointing_at_the_new_one(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path, password="pw")
    seen = {}

    class Session:
        def post(self, url, files=None, data=None, timeout=None):
            seen["url"], seen["zip"] = url, files["bundle"][1].read()
            return _FakeResp(True, {"ok": True})
    monkeypatch.setattr(hq.move, "_session", lambda url, pw: (Session(), {}))
    monkeypatch.setattr(hq.move, "_wait_for", lambda url, bid: True)
    r = hq.move.send_to("100.1.1.1", "pw")
    assert seen["url"] == "http://100.1.1.1:8000/api/move/in" and seen["zip"][:2] == b"PK"
    assert r["url"] == "http://100.1.1.1:8000"
    assert hq.standby.info() ["reason"] == "moved" and hq.standby.info()["moved_to"] == r["url"]
    assert hq.standby.peer_url() == r["url"]
    with pytest.raises(hq.move.MoveError, match="nothing to move"):
        hq.move.send_to("100.1.1.1", "pw")


# ---- printing ------------------------------------------------------------------------------------------------------

def _print_week(monkeypatch, hq, tmp_path):
    folder = hq.config.FOOTBALL_PRINT_DIR / "Ferris State"
    folder.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(hq.football.printing, "week_opponent", lambda now=None: "Ferris State")
    monkeypatch.setattr(hq.football.printing, "SETTLE_SECONDS", 0)
    return folder


def test_cloud_prints_by_email_one_file_per_email(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    folder = _print_week(monkeypatch, hq, tmp_path)
    (folder / "Scouting report.pdf").write_bytes(b"%PDF-1.4 x")
    (folder / "Tags.csv").write_text("a,b\n")
    monkeypatch.setattr(hq.football.printing, "FOOTBALL_PRINTER_EMAIL", "envy@hpeprint.com")
    monkeypatch.setenv("PITCH_EMAIL_ADDRESS", "steven@gmail.com")
    monkeypatch.setenv("PITCH_EMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    sent = []
    monkeypatch.setattr(hq.agents.pitch.mailer, "send", lambda msg: sent.append(msg))
    text = hq.football.printing.print_now()
    assert "Printed 2 files" in text and len(sent) == 2
    by_name = {m.get_filename() if False else list(m.iter_attachments())[0].get_filename(): m for m in sent}
    assert set(by_name) == {"Scouting report.pdf", "Tags.txt"}       # a .csv goes as text
    m = by_name["Scouting report.pdf"]
    assert m["To"] == "envy@hpeprint.com" and m["From"] == "steven@gmail.com"
    assert not [p for p in m.walk() if p.get_content_type() == "text/plain" and not p.get_filename()]  # no body page
    assert hq.football.printing.print_now() == "Nothing to print."   # never twice


def test_a_printed_file_isnt_printed_again_after_a_move_changes_its_time(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    folder = _print_week(monkeypatch, hq, tmp_path)
    f = folder / "Report.pdf"
    f.write_bytes(b"%PDF same")
    sent = []
    monkeypatch.setattr(hq.football.printing, "_send", sent.append)
    hq.football.printing.print_now()
    assert len(sent) == 1
    import os
    os.utime(f, (time.time() - 5000, time.time() - 5000))             # the Drive copy has another modified time
    assert hq.football.printing.print_now() == "Nothing to print."
    f.write_bytes(b"%PDF changed")                                     # a real change prints again
    os.utime(f, (time.time() - 100, time.time() - 100))
    hq.football.printing.print_now()
    assert len(sent) == 2


def test_on_a_server_without_a_printer_email_it_says_what_to_do(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    folder = _print_week(monkeypatch, hq, tmp_path)
    (folder / "R.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(hq.football.printing.sys, "platform", "linux")
    monkeypatch.setattr(hq.football.printing.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    assert "HQ_PRINTER_EMAIL" in hq.football.printing.print_now()


# ---- Google Drive sync ---------------------------------------------------------------------------------------------

class FakeDrive:
    """Just enough of the Drive API: folders, files, export, create, update."""

    def __init__(self):
        self.items = {"root": {"id": "root", "name": "My Drive", "mimeType": "folder", "parents": []}}
        self.data, self.n = {}, 0

    def add(self, name, parent, mime="application/pdf", data=b"", modified="2026-10-20T10:00:00.000Z"):
        self.n += 1
        fid = f"f{self.n}"
        self.items[fid] = {"id": fid, "name": name, "mimeType": mime, "parents": [parent], "modifiedTime": modified}
        self.data[fid] = data
        return fid

    def files(self):
        return self

    def _run(self, value):
        class R:
            def execute(_):
                return value
        return R()

    def list(self, q, fields=None, pageSize=None, pageToken=None, spaces=None):
        import re
        parent = re.search(r"'([^']+)' in parents", q).group(1)
        name = re.search(r"name = '((?:[^'\\]|\\.)*)'", q)
        out = [dict(i) for i in self.items.values() if parent in i.get("parents", [])
               and (not name or i["name"] == name.group(1).replace("\\'", "'"))
               and ("mimeType = 'application/vnd.google-apps.folder'" not in q or i["mimeType"] == hq_folder())]
        return self._run({"files": out})

    def create(self, body, media_body=None, fields=None):
        fid = self.add(body["name"], body["parents"][0], body.get("mimeType", "application/octet-stream"),
                       Path(media_body._filename).read_bytes() if media_body else b"", "2026-10-25T01:00:00.000Z")
        return self._run({"id": fid, "modifiedTime": self.items[fid]["modifiedTime"]})

    def update(self, fileId, media_body=None, body=None, fields=None):
        if media_body:
            self.data[fileId] = Path(media_body._filename).read_bytes()
            self.items[fileId]["modifiedTime"] = "2026-10-25T02:00:00.000Z"
        if body and body.get("trashed"):
            self.items[fileId]["parents"] = []
        return self._run({"id": fileId, "modifiedTime": self.items[fileId]["modifiedTime"]})

    def get_media(self, fileId):
        return ("media", fileId)

    def export_media(self, fileId, mimeType):
        return ("export", fileId)


def hq_folder():
    return "application/vnd.google-apps.folder"


def test_drive_sync_brings_files_down_sends_hq_files_up_and_never_deletes(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    ds = hq.drive_sync
    drive = FakeDrive()
    fb = drive.add("Football", "root", hq_folder())
    wsu = drive.add("2026 WSU FOOTBALL", fb, hq_folder())
    ferris = drive.add("Ferris State", wsu, hq_folder())
    drive.add("Scout.pdf", ferris, data=b"%PDF scout")
    drive.add("Depth chart", ferris, "application/vnd.google-apps.spreadsheet", b"XLSX")
    drive.add("Form", ferris, "application/vnd.google-apps.form")
    monkeypatch.setenv("HQ_DRIVE_FOLDERS", json.dumps({"HQ_FOOTBALL_DIR": "My Drive/Football",
                                                       "HQ_PRINT_DIR": "My Drive/Football/2026 WSU FOOTBALL"}))
    assert ds.roots() == ["My Drive/Football"]

    def fake_download(svc, f, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(drive.data[f["id"]])
        t = ds._stamp(f["modifiedTime"])
        import os
        os.utime(dest, (t, t))
    monkeypatch.setattr(ds, "_download", fake_download)
    import googleapiclient.http
    monkeypatch.setattr(googleapiclient.http, "MediaFileUpload",
                        type("M", (), {"__init__": lambda self, f, resumable=False: setattr(self, "_filename", f)}))

    r = ds.sync_once(drive)
    local = ds.local_folder("My Drive/Football") / "2026 WSU FOOTBALL" / "Ferris State"
    assert (local / "Scout.pdf").read_bytes() == b"%PDF scout"
    assert (local / "Depth chart.xlsx").read_bytes() == b"XLSX"      # a Google Sheet comes down as Excel
    assert not (local / "Form").exists() and r["down"] == 2 and r["up"] == 0
    assert ds.sync_once(drive) == {"down": 0, "up": 0, "problems": []}   # nothing changed, nothing moves

    # HQ makes a report and an opponent folder: both go up to Drive.
    (local / "Tells report.docx").write_bytes(b"DOCX")
    (local.parent / "Northwood").mkdir()
    r = ds.sync_once(drive)
    names = {i["name"] for i in drive.items.values()}
    assert {"Tells report.docx", "Northwood"} <= names and r["up"] == 1
    # The exported Excel copy is never sent back over the Google Sheet.
    assert sum(1 for i in drive.items.values() if i["name"].startswith("Depth chart")) == 1

    # Changed in both places: Drive wins and HQ's copy is kept beside it.
    sid = next(i["id"] for i in drive.items.values() if i["name"] == "Scout.pdf")
    drive.data[sid], drive.items[sid]["modifiedTime"] = b"%PDF v2", "2026-10-26T00:00:00.000Z"
    (local / "Scout.pdf").write_bytes(b"%PDF mine")
    ds.sync_once(drive)
    assert (local / "Scout.pdf").read_bytes() == b"%PDF v2"
    assert (local / "Scout (HQ copy).pdf").read_bytes() == b"%PDF mine"

    # Deleting a file in either place deletes nothing in the other.
    (local / "Tells report.docx").unlink()
    ds.sync_once(drive)
    assert any(i["name"] == "Tells report.docx" and i["parents"] for i in drive.items.values())


def test_drive_sync_waits_on_standby_and_without_a_sign_in(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    called = []
    monkeypatch.setattr(hq.drive_sync, "sync_once", lambda svc=None: called.append(1) or {"down": 0, "up": 0, "problems": []})
    monkeypatch.setenv("HQ_DRIVE_FOLDERS", json.dumps({"HQ_FOOTBALL_DIR": "My Drive/Football"}))
    hq.drive_sync.run_once()
    assert not called                                   # not signed in
    hq.drive_sync.TOKEN_PATH = tmp_path / "token.json"
    hq.drive_sync.TOKEN_PATH.write_text("{}")
    hq.standby.set_standby(True)
    hq.drive_sync.run_once()
    assert not called                                   # on standby
    hq.standby.set_standby(False)
    hq.drive_sync.run_once()
    assert called


# ---- watchdog, rollback and updates ---------------------------------------------------------------------------------

def test_watchdog_restarts_a_stuck_hq_and_remembers_a_good_version(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(hq.relay, "notify", sent.append)
    monkeypatch.setattr(hq.health, "_tailscale_expiry", lambda: None)
    monkeypatch.setattr(hq.health, "_healthz", lambda port: None)
    with pytest.raises(SystemExit) as e:
        hq.health.check(fix=True)
    assert e.value.code == 2 and "restarted" in sent[0]
    monkeypatch.setattr(hq.health, "_healthz", lambda port: {"role": "active", "worker_seconds_ago": 30 * 60, "uptime": 99})
    with pytest.raises(SystemExit):
        hq.health.check(fix=True)
    assert len(sent) == 1                               # one alert an hour, not one every 5 minutes
    monkeypatch.setattr(hq.health, "_healthz", lambda port: {"role": "standby", "worker_seconds_ago": None, "uptime": 99})
    assert hq.health.check(fix=True) == []              # a standby copy is supposed to be quiet
    monkeypatch.setattr(hq.health, "_healthz", lambda port: {"role": "active", "worker_seconds_ago": 5, "uptime": 3600})
    monkeypatch.setattr(hq.health, "_git", lambda *a: "abc123")
    assert hq.health.check(fix=True) == []
    assert hq.health.GOOD_PATH.read_text() == "abc123"


def test_watchdog_warns_about_tailscale_key_expiry_once_a_week(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(hq.relay, "notify", sent.append)
    monkeypatch.setattr(hq.health, "_healthz", lambda port: {"role": "active", "worker_seconds_ago": 5, "uptime": 1})
    monkeypatch.setattr(hq.health, "_tailscale_expiry", lambda: "2027-04-20T00:00:00Z")
    hq.health.check(fix=True)
    hq.health.check(fix=True)
    assert len(sent) == 1 and "Disable key expiry" in sent[0]


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_rollback_goes_back_to_the_good_version_and_keeps_config(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "config").mkdir()
    (repo / "config" / "vision.md").write_text("v1\n")
    (repo / "app.py").write_text("good\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "good")
    good = _git(repo, "rev-parse", "HEAD")
    (repo / "app.py").write_text("broken\n")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "bad")
    bad = _git(repo, "rev-parse", "HEAD")
    (repo / "config" / "vision.md").write_text("v1\nremember this\n")    # Steven's edit
    monkeypatch.setattr(hq.health, "ROOT", repo)
    monkeypatch.setattr(hq.relay, "notify", lambda t: None)
    assert "no earlier version" in hq.health.rollback()
    hq.health.GOOD_PATH.write_text(good)
    assert "went back" in hq.health.rollback()
    assert _git(repo, "rev-parse", "HEAD") == good and (repo / "app.py").read_text() == "good\n"
    assert (repo / "config" / "vision.md").read_text() == "v1\nremember this\n"
    assert hq.update.BAD_PATH.read_text() == bad


def test_update_skips_a_version_that_was_rolled_back(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    upstream, origin, home = tmp_path / "up", tmp_path / "origin.git", tmp_path / "home"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    (upstream / "a.txt").write_text("1")
    _git(upstream, "add", "-A")
    _git(upstream, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one")
    _git(tmp_path, "clone", "-q", "--bare", str(upstream), str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(home))
    (upstream / "a.txt").write_text("2")
    _git(upstream, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "two")
    _git(upstream, "push", "-q", str(origin), "main")
    monkeypatch.setattr(hq.update, "ROOT", home)
    hq.update.BAD_PATH.write_text(_git(upstream, "rev-parse", "HEAD"))
    assert hq.update.check(force=True)["available"] is False
    assert hq.update.update() is False
    hq.update.BAD_PATH.unlink()
    assert hq.update.update() is True


def test_auto_update_waits_for_idle(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(hq.update, "update", lambda: calls.append("u") or True)
    monkeypatch.setattr(hq.update, "restart", lambda: calls.append("r"))
    hq.update._status["available"] = True
    assert not hq.update.auto_apply_if_idle()            # not switched on (only the cloud server turns it on)
    monkeypatch.setenv("HQ_AUTO_UPDATE", "1")
    tid = hq.db.create_task("Chad", "x", {}, created_by="Steven")
    hq.db.update_task(tid, "running")
    assert not hq.update.auto_apply_if_idle() and not calls   # a clip is being made
    hq.db.update_task(tid, "done", "ok")
    assert hq.update.auto_apply_if_idle() and calls == ["u", "r"]


def test_shutting_down_stops_new_posts(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    tried = []
    _clip(hq, "approved", "c.mp4")
    monkeypatch.setattr(hq.agents.chad.publish, "accounts_for",
                        lambda creator: [{"platform": "youtube", "name": "main", "enabled": True}])
    monkeypatch.setattr(hq.agents.chad.publish.youtube, "publish", lambda clip, acct: tried.append(1) or ("id", "url"))
    hq.standby.stopping.set()
    try:
        hq.agents.chad.publish.publish_approved()
    finally:
        hq.standby.stopping.clear()
    assert not tried and hq.db.rows("SELECT status FROM clips")[0]["status"] == "approved"
    hq.agents.chad.publish.publish_approved()
    assert tried == [1]
