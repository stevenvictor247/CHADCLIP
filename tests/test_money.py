import importlib
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


def _fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("HQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HQ_PASSWORD", "")
    import hq.config, hq.db, hq.api
    for m in (hq.config, hq.db, hq.api):
        importlib.reload(m)
    hq.db.init()
    return hq


def _claude_call(db, usd, when):
    db.execute("INSERT INTO llm_usage (agent, model, cost_usd, created_at) VALUES ('Chad', 'm', ?, ?)",
               usd, when.astimezone(timezone.utc).isoformat(timespec="seconds"))


def _earning(db, usd, status="paid", when=None):
    ts = (when or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    db.execute("INSERT INTO submissions (campaign_id, clip_id, post_id, status, earned_usd, created_at, updated_at) "
               "VALUES (1, 1, ?, ?, ?, ?, ?)", int(datetime.now().timestamp() * 1e6) % 10**9, status, usd, ts, ts)


def test_spent_made_and_net_per_period(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    from hq import db, money
    now = datetime.now().astimezone()
    long_ago = now - timedelta(days=400)
    _claude_call(db, 1.25, now)
    _claude_call(db, 3.00, long_ago)
    money.add("expense", 10, "CapCut", date.today().isoformat())
    money.add("expense", 20, "old tool", long_ago.date().isoformat())
    money.add("income", 50, "Whop payout")
    _earning(db, 7.5)
    _earning(db, 99, status="unpaid")   # a campaign that didn't pay made nothing
    p = money.summary()["periods"]
    assert p["today"] == {"spent": 11.25, "made": 57.5, "net": 46.25, "claude": 1.25, "expenses": 10.0,
                          "campaigns": 7.5, "income": 50.0}
    assert p["month"]["spent"] == 11.25
    assert p["all"]["spent"] == 34.25 and p["all"]["made"] == 57.5 and p["all"]["net"] == pytest.approx(23.25)


def test_bad_entries_are_refused(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    from hq import money
    for args in (("gift", 5), ("income", 0), ("income", -3), ("income", "lots"), ("expense", 5, "", "21/10/2026")):
        with pytest.raises(ValueError):
            money.add(*args)
    assert money.summary()["entries"] == []


def test_money_api_adds_lists_and_deletes(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    c = TestClient(hq.api.app)
    assert c.get("/money-bar.js").status_code == 200
    body = {"kind": "income", "amount_usd": 12.5, "note": "Etsy sale", "day": "2026-10-01"}
    assert c.post("/api/money", json=body).status_code == 403   # only HQ's own page can log money
    r = c.post("/api/money", json=body, headers={"X-HQ": "1"})
    assert r.status_code == 200
    entry = r.json()["money"]["entries"][0]
    assert entry["note"] == "Etsy sale" and entry["amount_usd"] == 12.5 and entry["day"] == "2026-10-01"
    assert c.get("/api/state").json()["money"]["periods"]["all"]["made"] == 12.5
    assert c.post("/api/money", json={**body, "amount_usd": 0}, headers={"X-HQ": "1"}).status_code == 400
    assert c.delete(f"/api/money/{entry['id']}").status_code == 403
    assert c.delete(f"/api/money/{entry['id']}", headers={"X-HQ": "1"}).json()["money"]["entries"] == []
    assert c.delete(f"/api/money/{entry['id']}", headers={"X-HQ": "1"}).status_code == 404


def test_money_strip_sits_above_the_header_and_update_bar():
    from pathlib import Path
    static = Path(__file__).parent.parent / "hq/static"
    html = (static / "index.html").read_text(encoding="utf-8")
    assert html.index('src="/money-bar.js"') < html.index('src="/hq-bar.js"')
    assert "HQMoney?.update(s.money)" in html
    js = (static / "money-bar.js").read_text(encoding="utf-8")
    assert 'insertAdjacentHTML("afterbegin"' in js and "Add expense" in js and "Add income" in js
