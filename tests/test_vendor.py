from datetime import datetime, timedelta, timezone


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("HQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HQ_PASSWORD", "")
    import importlib

    import hq.api
    import hq.config
    import hq.db
    import hq.money
    for m in (hq.config, hq.db, hq.money, hq.api):
        importlib.reload(m)
    from fastapi.testclient import TestClient
    return TestClient(hq.api.app), hq


def test_vendor_libraries_are_served_and_nothing_else(monkeypatch, tmp_path):
    c, _ = _client(monkeypatch, tmp_path)
    for name in ("lucide.min.js", "motion.min.js", "uPlot.iife.min.js", "uPlot.min.css", "pixi.min.js"):
        r = c.get("/vendor/" + name)
        assert r.status_code == 200 and len(r.content) > 1000, name
    assert c.get("/vendor/..%2Fapi.py").status_code == 404
    assert c.get("/vendor/LICENSE-lucide").status_code == 404
    assert c.get("/hq-polish.js").status_code == 200


def test_every_page_script_exists_and_icons_have_fallback():
    from pathlib import Path
    static = Path(__file__).parent.parent / "hq/static"
    html = (static / "index.html").read_text(encoding="utf-8")
    assert html.index('/vendor/lucide.min.js') < html.index('/hq-tabs.js')   # icons library loads before the tabs use it
    assert html.index('/hq-tabs.js') < html.index('/hq-polish.js')
    assert "window.lucide ?" in (static / "hq-tabs.js").read_text(encoding="utf-8")   # emoji still show if Lucide is missing


def test_money_daily_sums_each_day(monkeypatch, tmp_path):
    c, hq = _client(monkeypatch, tmp_path)
    hq.db.init()
    today = datetime.now().astimezone().date()
    hq.money.add("expense", 5, "tool", today.isoformat())
    hq.money.add("income", 12.5, "payout", (today - timedelta(days=2)).isoformat())
    hq.db.execute("INSERT INTO llm_usage (agent, model, cost_usd, created_at) VALUES (?, ?, ?, ?)",
                  "Chad", "m", 0.25, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    d = c.get("/api/money/daily?days=7").json()
    assert len(d["days"]) == 7 and d["days"][-1] == today.isoformat()
    assert d["spent"][-1] == 5.25
    assert d["made"][-3] == 12.5 and sum(d["made"]) == 12.5
