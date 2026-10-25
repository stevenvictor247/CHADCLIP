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
