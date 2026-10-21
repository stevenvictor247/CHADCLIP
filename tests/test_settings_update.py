import importlib
import json
import shutil
import subprocess

from fastapi.testclient import TestClient


def _fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("HQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HQ_PASSWORD", "")
    import hq.config, hq.db, hq.settings, hq.update, hq.api
    for m in (hq.config, hq.db, hq.settings, hq.update, hq.api):
        importlib.reload(m)
    hq.db.init()
    return hq


def test_settings_page_lists_env_example_and_hides_secrets(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "abcdefghijkl-1234")
    d = hq.settings.describe()
    fields = {f["key"]: f for s in d["sections"] for f in s["fields"]}
    assert {"ANTHROPIC_API_KEY", "HQ_DAILY_BUDGET", "TELEGRAM_BOT_TOKEN"} <= set(fields)
    secret = fields["TWITCH_CLIENT_SECRET"]
    assert secret["set"] and secret["hint"] == "ends in 1234" and "value" not in secret
    assert "abcdefghijkl" not in json.dumps(d)
    assert fields["HQ_WHISPER_MODEL"]["secret"] is False


def test_saved_settings_survive_a_restart_and_beat_env(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    monkeypatch.setenv("HQ_DAILY_BUDGET", "0")
    assert hq.settings.save({"HQ_DAILY_BUDGET": "2.5", "TELEGRAM_OWNER_ID": "42"}) == ["HQ_DAILY_BUDGET", "TELEGRAM_OWNER_ID"]
    assert json.loads((tmp_path / "settings.json").read_text())["HQ_DAILY_BUDGET"] == "2.5"
    monkeypatch.setenv("HQ_DAILY_BUDGET", "0")  # as if .env still said 0
    importlib.reload(hq.config)
    assert hq.config.DAILY_BUDGET == 2.5
    hq.settings.save({"TELEGRAM_OWNER_ID": ""})
    assert json.loads((tmp_path / "settings.json").read_text())["TELEGRAM_OWNER_ID"] == ""


def test_settings_reject_bad_names(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    for bad in ({"lower": "x"}, {"OK": "two\nlines"}):
        try:
            hq.settings.save(bad)
            assert False, bad
        except ValueError:
            pass


def test_account_switch_keeps_comments(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    cfg = tmp_path / "config"
    shutil.copytree(hq.config.CONFIG_DIR, cfg)
    monkeypatch.setattr(hq.settings, "CONFIG_DIR", cfg)
    hq.settings.set_account_enabled("youtube_main", True)
    text = (cfg / "accounts.yaml").read_text()
    assert "# Clipping accounts" in text
    enabled = {a["name"]: a["enabled"] for a in hq.settings.accounts()}
    assert enabled == {"tiktok_main": False, "youtube_main": True, "instagram_main": False}


def test_settings_api_needs_the_hq_page(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    c = TestClient(hq.api.app)
    assert c.get("/settings").status_code == 200
    assert c.get("/hq-bar.js").status_code == 200
    assert c.get("/api/settings").json()["sections"]
    assert c.post("/api/settings", json={"values": {"HQ_REPORT_HOUR": "8"}}).status_code == 403
    r = c.post("/api/settings", json={"values": {"HQ_REPORT_HOUR": "8"}}, headers={"X-HQ": "1"})
    assert r.status_code == 200 and r.json()["changed"] == ["HQ_REPORT_HOUR"]
    assert c.post("/api/restart").status_code == 403
    assert c.post("/api/update").status_code == 403


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo, files, msg):
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)


def test_update_never_gets_stuck_on_local_edits(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path / "data")
    upstream, origin, home = tmp_path / "upstream", tmp_path / "origin.git", tmp_path / "home"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    _commit(upstream, {"config/vision.md": "v1\n", "hq/code.py": "old\n"}, "first")
    _git(tmp_path, "clone", "-q", "--bare", str(upstream), str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(home))
    monkeypatch.setattr(hq.update, "ROOT", home)
    monkeypatch.setattr(hq.update, "DATA_DIR", tmp_path / "data")

    first = hq.update.check(force=True)
    assert first["available"] is False and first["version"].count(",") == 1  # the bar shows "Version abc1234, Oct 21"
    assert hq.update.update() is False

    # On Steven's PC: the Boss remembers something, a code file got edited, and he made a config file by hand.
    (home / "config/vision.md").write_text("v1\nremember: be funny\n")
    (home / "hq/code.py").write_text("my edit\n")
    (home / "config/scout.yaml").write_text("mine: true\n")
    # On GitHub: new code that also adds config/scout.yaml.
    _commit(upstream, {"hq/code.py": "new\n", "config/scout.yaml": "default: true\n", "config/vision.md": "v2\n"},
            "Add Scout")
    _git(upstream, "push", "-q", str(origin), "main")

    status = hq.update.check(force=True)
    assert status["available"] and status["count"] == 1 and status["changes"] == ["Add Scout"]
    assert hq.update.update() is True
    assert (home / "hq/code.py").read_text() == "new\n"
    assert (home / "config/vision.md").read_text() == "v1\nremember: be funny\n"  # your config wins
    assert (home / "config/scout.yaml").read_text() == "mine: true\n"
    backups = list((tmp_path / "data" / "update-backups").iterdir())
    assert (backups[0] / "hq/code.py").read_text() == "my edit\n"
    assert _git(home, "rev-parse", "HEAD") == _git(upstream, "rev-parse", "HEAD")
    assert hq.update.check(force=True)["available"] is False


def test_zip_copy_says_it_cannot_update(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path / "data")
    (tmp_path / "zip").mkdir()
    monkeypatch.setattr(hq.update, "ROOT", tmp_path / "zip")
    assert hq.update.check(force=True)["git"] is False
    assert hq.update.update() is False


def test_updates_wait_until_github_tests_pass(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path / "data")
    upstream, origin, home = tmp_path / "upstream", tmp_path / "origin.git", tmp_path / "home"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    _commit(upstream, {"hq/code.py": "v1\n"}, "first")
    _git(tmp_path, "clone", "-q", "--bare", str(upstream), str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(home))
    monkeypatch.setattr(hq.update, "ROOT", home)
    monkeypatch.setattr(hq.update, "DATA_DIR", tmp_path / "data")

    # GitHub marks v1 as tested, then a v2 lands on main whose tests haven't passed yet.
    _git(upstream, "push", "-q", str(origin), "main:tested")
    _commit(upstream, {"hq/code.py": "v2\n"}, "Untested change")
    _git(upstream, "push", "-q", str(origin), "main")
    status = hq.update.check(force=True)
    assert status["tested"] and not status["available"] and status["testing"] == 1
    assert hq.update.update() is False
    assert (home / "hq/code.py").read_text() == "v1\n"

    # The tests pass, GitHub moves tested forward, and now the update installs.
    _git(upstream, "push", "-q", str(origin), "main:tested")
    status = hq.update.check(force=True)
    assert status["available"] and status["changes"] == ["Untested change"] and status["testing"] == 0
    assert hq.update.update() is True
    assert (home / "hq/code.py").read_text() == "v2\n"


def test_update_bar_is_always_shown_and_has_a_check_button():
    from pathlib import Path
    js = (Path(__file__).parent.parent / "hq/static/hq-bar.js").read_text(encoding="utf-8")
    assert "HQ is up to date" in js and "hq-recheck" in js and "Couldn't check for updates" in js
    assert 'bar.style.display = "none"' not in js  # a missing bar must never look like a broken updater
