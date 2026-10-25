import importlib
import zipfile

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path, password):
    monkeypatch.setenv("HQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HQ_PASSWORD", password)
    import hq.config, hq.db, hq.api
    for m in (hq.config, hq.db, hq.api):
        importlib.reload(m)
    hq.db.init()
    return TestClient(hq.api.app)


def test_no_password_means_no_login(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, "")
    assert c.get("/api/state").status_code == 200


def test_password_locks_dashboard_until_login(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, "s3cret")
    assert c.get("/api/state").status_code == 401
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert c.get("/login").status_code == 200

    r = c.post("/login", data={"password": "nope"}, follow_redirects=False)
    assert r.headers["location"] == "/login?wrong=1"
    assert c.get("/api/state").status_code == 401

    c.post("/login", data={"password": "s3cret"}, follow_redirects=False)
    assert c.get("/api/state").status_code == 200
    c.get("/logout")
    assert c.get("/api/state").status_code == 401


def test_backup_has_database_and_config(monkeypatch, tmp_path):
    _client(monkeypatch, tmp_path, "")
    import hq.backup
    importlib.reload(hq.backup)
    hq.db.log("Steven", "hello")
    out = hq.backup.make_backup()
    names = zipfile.ZipFile(out).namelist()
    assert "data/hq.sqlite3" in names
    assert any(n.startswith("config/") for n in names)


def test_backup_copy_goes_elsewhere_without_keys(monkeypatch, tmp_path):
    _client(monkeypatch, tmp_path, "")
    import hq.backup
    importlib.reload(hq.backup)
    secrets = hq.backup.CONFIG_DIR / "secrets"
    made_secrets = not secrets.exists()
    secrets.mkdir(exist_ok=True)
    key = secrets / "test-key.json"
    key.write_text("{}")
    hq.backup.SETTINGS_PATH.write_text('{"ANTHROPIC_API_KEY": "sk-test"}')
    try:
        monkeypatch.setenv("HQ_BACKUP_COPY_DIR", str(tmp_path / "drive"))
        out = hq.backup.make_backup()
        local = zipfile.ZipFile(out).namelist()
        copy = zipfile.ZipFile(tmp_path / "drive" / out.name).namelist()
        assert "config/secrets/test-key.json" in local and any(n.endswith("settings.json") for n in local)
        assert "data/hq.sqlite3" in copy and any(n.startswith("config/") for n in copy)
        assert not any("secrets/" in n or n.endswith("settings.json") or n == ".env" for n in copy)
        # a Drive folder that can't be written doesn't stop the local backup
        blocker = tmp_path / "not-a-folder"
        blocker.write_text("x")
        monkeypatch.setenv("HQ_BACKUP_COPY_DIR", str(blocker / "sub"))
        assert hq.backup.make_backup().exists()
    finally:
        key.unlink()
        if made_secrets:
            secrets.rmdir()


def _fresh(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, "")
    import hq.backup, hq.standby, hq.worker
    for m in (hq.standby, hq.backup, hq.worker):
        importlib.reload(m)
    return c


def test_standby_stops_the_worker_and_shows_on_dashboard(monkeypatch, tmp_path):
    c = _fresh(monkeypatch, tmp_path)
    import hq.standby, hq.worker
    hq.db.create_task("Chad", "x", {}, created_by="Steven")
    hq.standby.set_standby(True)
    hq.worker.tick()
    assert hq.db.rows("SELECT status FROM tasks")[0]["status"] == "queued"
    assert c.get("/api/pause").json()["standby"] is True
    hq.standby.set_standby(False)
    assert c.get("/api/pause").json()["standby"] is False


def test_handoff_then_restore_moves_state_and_flips_standby(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    import hq.backup, hq.standby
    hq.db.log("Steven", "before the move")
    (hq.backup.DATA_DIR / "chad_seen.json").write_text('["abc"]')
    (hq.backup.DATA_DIR / "tiktok_tokens.json").write_text('{"t": 1}')
    out = hq.backup.make_backup()
    hq.standby.set_standby(True)
    (hq.backup.DATA_DIR / "chad_seen.json").write_text("[]")
    restored = hq.backup.restore(out)
    assert "data/chad_seen.json" in restored and "data/tiktok_tokens.json" in restored
    assert (hq.backup.DATA_DIR / "chad_seen.json").read_text() == '["abc"]'
    assert not hq.standby.is_standby()          # restoring makes this copy the one that runs
    assert any(m["message"] == "before the move" for m in hq.db.rows("SELECT message FROM activity"))


def test_backup_never_carries_the_standby_flag(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    import hq.backup, hq.standby
    hq.standby.set_standby(True)
    assert not any("standby" in n for n in zipfile.ZipFile(hq.backup.make_backup()).namelist())


def test_restore_refuses_bad_zips(monkeypatch, tmp_path):
    import pytest
    _fresh(monkeypatch, tmp_path)
    import hq.backup
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("data/hq.sqlite3", "x")
        z.writestr("../escape.txt", "x")
    with pytest.raises(ValueError):
        hq.backup.restore(evil)
    assert not (tmp_path.parent / "escape.txt").exists()
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("readme.txt", "x")
    with pytest.raises(ValueError):
        hq.backup.restore(empty)


def test_auto_update_waits_for_idle(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path)
    import hq.update
    importlib.reload(hq.update)
    calls = []
    monkeypatch.setattr(hq.update, "update", lambda: calls.append("u") or True)
    monkeypatch.setattr(hq.update, "restart", lambda: calls.append("r"))
    hq.update._status["available"] = True
    assert not hq.update.auto_apply_if_idle()            # not switched on
    monkeypatch.setenv("HQ_AUTO_UPDATE", "1")
    tid = hq.db.create_task("Chad", "x", {}, created_by="Steven")
    hq.db.update_task(tid, "running")
    assert not hq.update.auto_apply_if_idle() and not calls   # a clip is mid-run
    hq.db.update_task(tid, "done", "ok")
    assert hq.update.auto_apply_if_idle() and calls == ["u", "r"]
