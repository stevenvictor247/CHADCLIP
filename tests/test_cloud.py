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
