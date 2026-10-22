import re
from pathlib import Path

STATIC = Path(__file__).parent.parent / "hq/static"


def test_every_tab_points_at_something_on_the_dashboard():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "hq-tabs.js").read_text(encoding="utf-8")
    assert html.index('src="/setup-card.js"') < html.index('src="/hq-tabs.js"')   # the setup card exists before tabs are made
    ids = {i for has in re.findall(r"has: \[([^\]]*)\]", js) for i in re.findall(r'"([^"]+)"', has)}
    assert {"apprsection", "pending", "chatlog", "campsection", "leadsection", "library", "activity"} <= ids
    for i in ids - {"setup"}:   # "setup" is added by setup-card.js
        assert f'id="{i}"' in html, f"tab section #{i} is missing from index.html"


def test_tabs_script_is_served(monkeypatch, tmp_path):
    monkeypatch.setenv("HQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HQ_PASSWORD", "")
    import importlib
    import hq.config, hq.db, hq.api
    for m in (hq.config, hq.db, hq.api):
        importlib.reload(m)
    from fastapi.testclient import TestClient
    r = TestClient(hq.api.app).get("/hq-tabs.js")
    assert r.status_code == 200 and "hqTabs" in r.text
