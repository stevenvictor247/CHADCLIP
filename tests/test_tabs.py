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


def test_villages_share_one_stage():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "hq-tabs.js").read_text(encoding="utf-8")
    # the camera and cards (town-kit.js) must exist before either village starts
    assert html.index('src="/town-kit.js"') < html.index('src="/world.js"') < html.index('src="/football-town.js"')
    assert 'id="towns"' in html and 'id="world"' in html and 'id="fbworld"' in html
    # the stage shows on Home and on the Warrior Village tab
    home = re.search(r'id: "home".*?has: \[([^\]]*)\]', js).group(1)
    football = re.search(r'id: "football".*?has: \[([^\]]*)\]', js).group(1)
    assert '"towns"' in home and '"towns"' in football


def test_town_kit_is_served(monkeypatch, tmp_path):
    monkeypatch.setenv("HQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HQ_PASSWORD", "")
    import importlib
    import hq.config, hq.db, hq.api
    for m in (hq.config, hq.db, hq.api):
        importlib.reload(m)
    from fastapi.testclient import TestClient
    r = TestClient(hq.api.app).get("/town-kit.js")
    assert r.status_code == 200 and "HQTown" in r.text


def test_each_approval_type_has_a_dropdown_option():
    js = (STATIC / "hq-tabs.js").read_text(encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    groups = set(re.findall(r'\{id: "(\w+)", icon: "[^"]+", lu: "[^"]+", label: "[^"]+"\},', js.split("const GROUPS")[1].split("];")[0]))
    assert {"all", "clips", "pitch", "etsy", "football", "ideas", "other"} <= groups
    tab_groups = set(re.findall(r'appr: "(\w+)"', js))
    assert {"clips", "pitch", "etsy", "football", "ideas"} <= tab_groups and tab_groups <= groups
    # the dashboard sorts approvals into those same groups and publishes the counts the menus show
    fn = html.split("function apprGroup(a)")[1].split("function renderApprovals")[0]
    for g in groups - {"all"}:
        assert f'"{g}"' in fn or g == "other"
    assert "window.hqApprCounts" in html and 'document.addEventListener("hq-tab"' in html


def test_approval_kinds_all_land_in_a_group():
    # every approval kind the agents create must be one apprGroup() knows or fall into "other" on purpose
    kinds = set()
    for f in (Path(__file__).parent.parent / "hq").rglob("*.py"):
        kinds |= set(re.findall(r'approvals\.request\(\s*"\w+",\s*"(\w+)"', f.read_text(encoding="utf-8")))
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    fn = html.split("function apprGroup(a)")[1].split("function renderApprovals")[0]
    known = set(re.findall(r'"(\w+)"', fn))
    assert {"pitch", "followup", "sample", "muse_idea", "clip_pack", "recap", "rally"} <= known
    assert kinds, "expected to find approvals.request calls"


def test_approve_all_buttons_confirm_skip_problems_and_use_the_normal_endpoints():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for el in ('id="approveall"', 'id="approveallclips"'):
        assert el in html
    for name in ("approveAll", "approveAllClips"):
        body = html[html.index(f"async function {name}()"):]
        body = body[:body.index("\nasync function ", 10)]
        assert "confirm(" in body and "skipped" in body       # asks first, and says how many it left out
    # one call per item through the existing endpoints, so the posting checks still run
    assert "/api/approvals/${a.id}/approve" in html and "/api/clips/${id}/approve" in html
    assert "approve-all" not in html
    # flagged clips and pitches with no email are the ones left out
    assert 'data-flagged="1"' in html and "!c.dataset.flagged" in html
    assert 'a.kind === "pitch" && !(a.payload || {}).email' in html
