"""Depth: the Monday opponent personnel sheet. Every player here is made up."""

import io
import json
from datetime import datetime
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from hq import approvals, db, relay
from hq.agents.football import depth as agent
from hq.agents.football.depth import Depth
from hq.football import depth, printing, season

MONDAY = datetime(2026, 10, 26, 9, 0)


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    db.init()
    for t in ("tasks", "approvals"):
        db.execute(f"DELETE FROM {t}")
    for d in (depth.DIR,):
        d.mkdir(parents=True, exist_ok=True)
        for p in d.iterdir():
            p.unlink()
    depth.STATE.unlink(missing_ok=True)
    sent = []
    monkeypatch.setattr(relay, "notify", sent.append)
    monkeypatch.setattr(season, "current_game", lambda today=None: {"opponent": "Northern Michigan"})
    return sent


def make_xlsx(path: Path, header=("POS", "NO", "NAME", "GS", "ATT", "DEPTH")):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["LAST LINE: 73 67 65 72 58"])
    ws.append(["RECORD", "2-4 (0-2)"])
    ws.append([])
    ws.append(list(header))
    rows = [("QB", 15, "Made Up One", 6, 150, 1), ("QB", 9, "Made Up Two", 0, 20, 2), ("QB", 13, "Made Up Three", 0, 0, 3),
            ("RB", 5, "Back Five", "6-5", 90, 1), ("RB", 1, "Back One", 2, 60, 2), ("RB", 23, "Back TwentyThree", 0, 5, 3),
            ("RB", 0, "Back Zero", 0, 0, 4), ("WR", 7, "Wide Seven", 6, 40, 1), ("TE", 14, "Tight Fourteen", 6, 0, 1),
            ("TE", 84, "Tight Eighty", 0, 0, 2), ("LT", 73, "Tackle Left", 6, 0, 1), ("RG", 67, "Guard Right", 3, 0, 2),
            ("OL", 59, "Backup Line", 0, 0, 9), ("LB", 50, "Linebacker", 0, 0, 1)]
    for r in rows:
        ws.append(list(r))
    wb.save(path)
    return path


def test_reads_and_orders_by_reps(tmp_path):
    d = depth.read(make_xlsx(tmp_path / "Northern Michigan.xlsx"))
    assert d["meta"]["LAST LINE"] == "73 67 65 72 58" and d["meta"]["RECORD"] == "2-4 (0-2)"
    assert len(d["players"]) == 13   # the linebacker is left out
    cols = depth.layout(d["players"])
    names = lambda pos: [(i["num"], i["name"]) if k == "p" else i for k, i in cols[pos]]
    assert [n for n in names("QB") if isinstance(n, tuple)][:2] == [("15", "Made Up One"), ("9", "Made Up Two")]
    assert "NO ATTEMPTS RECORDED" in names("QB")
    rb = names("RB")
    assert rb[0] == ("5", "Back Five") and "NO STARTS" in rb and "NO CARRIES RECORDED" in rb
    assert ("0", "Back Zero") in rb                                  # jersey 0 survives
    assert next(p for p in d["players"] if p["name"] == "Back Five")["starts"] == 5   # "6-5" is games played - started
    assert names("TE")[-2] == "NO STARTS"
    assert names("OL")[0] == ("73", "Tackle Left") and "NO STARTS — BY NUMBER" in names("OL")
    assert [n for n in names("OL CONT.")] == [("59", "Backup Line")]


def test_bad_sheets_say_why(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n")
    with pytest.raises(depth.DepthError, match="header"):
        depth.read(p)
    p.write_text("POS,NAME\nLB,Someone\n")
    with pytest.raises(depth.DepthError, match="no QB"):
        depth.read(p)


def test_pdf_is_one_landscape_page(tmp_path):
    out = depth.build_pdf("Northern Michigan", depth.read(make_xlsx(tmp_path / "Northern Michigan.xlsx")), tmp_path / "o.pdf")
    raw = out.read_bytes()
    assert raw.startswith(b"%PDF") and raw.count(b"/Type /Page\n") + raw.count(b"/Type /Page ") >= 1
    assert b"792" in raw   # landscape width


def test_upload_matches_opponent_by_name_or_choice(tmp_path):
    src = make_xlsx(tmp_path / "NMU depth chart.xlsx")
    info = depth.save_upload("NMU depth chart.xlsx", src.read_bytes())
    assert info["opponent"] == "Northern Michigan" and depth.input_for("Northern Michigan")
    with pytest.raises(depth.DepthError, match="which opponent"):
        depth.save_upload("mystery.xlsx", src.read_bytes())
    depth.save_upload("mystery.xlsx", src.read_bytes(), "Ferris State")
    assert depth.input_for("Ferris State")
    with pytest.raises(depth.DepthError):
        depth.save_upload("notes.pdf", b"x", "Ferris State")
    assert any(x["opponent"] == "Ferris State" and x["uploaded"] for x in depth.listing())


def test_monday_asks_when_nothing_is_uploaded_and_only_once(_setup, monkeypatch):
    monkeypatch.setattr(season, "site_for", lambda opp: None)
    assert depth.run_if_due(MONDAY) == "asked" and "Northern Michigan" in _setup[0]
    assert depth.run_if_due(MONDAY) is None
    assert depth.run_if_due(datetime(2026, 10, 27, 9, 0)) is None


def test_monday_queues_the_agent_when_the_sheet_is_there(tmp_path, _setup):
    depth.save_upload("x.xlsx", make_xlsx(tmp_path / "x.xlsx").read_bytes(), "Northern Michigan")
    assert depth.run_if_due(datetime(2026, 10, 26, 7, 0)) is None     # before 8 AM
    assert depth.run_if_due(MONDAY) == "queued"
    task = db.rows("SELECT agent, params FROM tasks")[0]
    assert task["agent"] == "Depth" and "Northern Michigan" in task["params"]
    assert depth.run_if_due(datetime(2026, 10, 29, 9, 0)) is None     # Thursday: too late to start the week's sheet


def test_agent_builds_for_approval_then_saves_to_outbox_and_folder(tmp_path):
    shutil_root = printing.FOOTBALL_PRINT_DIR / "Northern Michigan"
    shutil_root.mkdir(parents=True, exist_ok=True)
    assert "I need the Northern Michigan" in Depth().run({"params": "{}"})
    depth.save_upload("x.xlsx", make_xlsx(tmp_path / "x.xlsx").read_bytes(), "Northern Michigan")
    assert "ready for your OK" in Depth().run({"params": "{}"})
    ap = db.rows("SELECT id, kind, title FROM approvals WHERE status = 'pending'")[0]
    assert ap["kind"] == "football_depth" and "Northern Michigan" in ap["title"]
    msg = agent._decide(__import__("json").loads(db.rows("SELECT payload FROM approvals WHERE id = ?", ap["id"])[0]["payload"]), "approve")
    assert "Northern Michigan folder" in msg
    made = list(shutil_root.glob("Northern Michigan offensive personnel*.pdf"))
    assert made
    for p in made:
        p.unlink()


def test_api_upload_and_build(tmp_path):
    import importlib
    import hq.api, hq.config, hq.db
    for m in (hq.config, hq.db, hq.api):
        importlib.reload(m)
    c = TestClient(hq.api.app)
    h = {"X-HQ": "1"}
    body = make_xlsx(tmp_path / "a.xlsx").read_bytes()
    assert c.post("/api/football/depth/upload", files={"file": ("a.xlsx", body)}, data={"opponent": "Ferris State"}).status_code in (401, 403)
    r = c.post("/api/football/depth/upload", files={"file": ("a.xlsx", body)}, data={"opponent": "Ferris State"}, headers=h)
    assert r.status_code == 200 and r.json()["players"] == 13
    assert c.post("/api/football/depth/upload", files={"file": ("a.xlsx", body)}, headers=h).status_code == 400
    assert c.post("/api/football/depth/build?opponent=Ferris%20State", headers=h).json()["task_id"]


# ---- the Monday 5 PM scouting report ----

def test_monday_5pm_queues_tells_for_the_newest_export_or_asks(_setup):
    from hq.config import FOOTBALL_INBOX
    from hq.football import scouting
    scouting.STATE.unlink(missing_ok=True)
    db.execute("DELETE FROM football_files")
    assert scouting.run_if_due(datetime(2026, 10, 26, 16, 59)) is None           # not yet 5 PM
    assert scouting.run_if_due(datetime(2026, 10, 26, 17, 0)) == "asked" and "Northern Michigan" in _setup[-1]
    assert scouting.run_if_due(datetime(2026, 10, 26, 18, 0)) is None            # once a week
    scouting.STATE.unlink(missing_ok=True)
    for n in ("NMU old.xlsx", "NMU new.xlsx", "Ferris.xlsx"):
        (FOOTBALL_INBOX / n).write_bytes(b"x")
        db.execute("INSERT INTO football_files (name, status, modified, added_at) VALUES (?, 'checked', 0, ?)", n, db.now())
    assert scouting.run_if_due(datetime(2026, 10, 26, 17, 5)) == "queued"
    t = db.rows("SELECT agent, params FROM tasks WHERE agent = 'Tells'")[0]
    assert "NMU new.xlsx" in t["params"] and "Northern Michigan" in t["params"]
    kinds = [json.loads(x["params"]).get("kind", "scouting") for x in db.rows("SELECT params FROM tasks WHERE agent = 'Tells' ORDER BY id")]
    assert kinds == ["scouting", "birds"]                                       # the one-page Birds and Rabbits too
    for n in ("NMU old.xlsx", "NMU new.xlsx", "Ferris.xlsx"):
        (FOOTBALL_INBOX / n).unlink()


# ---- fetching from the team's website ----

ROSTER_TABLE = """<h2>Roster</h2><table><thead><tr><th>No.</th><th>Name</th><th>Pos.</th><th>Cl.</th></tr></thead><tbody>
<tr><td>15</td><td>Connor Test</td><td>QB</td><td>Sr.</td></tr><tr><td>5</td><td>Devin Back</td><td>RB</td><td>Jr.</td></tr>
<tr><td>7</td><td>JT Wide</td><td>WR</td><td>So.</td></tr><tr><td>73</td><td>Kaiden Tackle</td><td>OL</td><td>Sr.</td></tr>
<tr><td>50</td><td>Dee Fender</td><td>LB</td><td>Sr.</td></tr></tbody></table>"""
ROSTER_CARDS = """<ul><li class="sidearm-roster-player"><span class="sidearm-roster-player-jersey-number">9</span>
<div class="sidearm-roster-player-name"><a href="/x">Jayden Cards</a></div><span class="sidearm-roster-player-position">QB</span></li></ul>"""
STATS = """<h3>Rushing</h3><table><tr><th>Player</th><th>GP-GS</th><th>Att</th><th>Gain</th></tr>
<tr><td>Back, Devin</td><td>6-6</td><td>90</td><td>400</td></tr><tr><td>Total</td><td>6</td><td>200</td><td>0</td></tr></table>
<h3>Passing</h3><table><tr><th>Player</th><th>GP-GS</th><th>Att-Cmp-Int</th></tr><tr><td>Connor Test</td><td>6-6</td><td>150-90-4</td></tr></table>
<h3>Receiving</h3><table><tr><th>Player</th><th>GP-GS</th><th>Rec</th></tr><tr><td>J. Wide</td><td>6-5</td><td>30</td></tr></table>"""


def test_parses_roster_tables_cards_and_stats():
    from hq.football import fetch
    roster = fetch.roster_players(fetch.parse(ROSTER_TABLE))
    assert [(p["no"], p["name"], p["pos"]) for p in roster][:2] == [("15", "Connor Test", "QB"), ("5", "Devin Back", "RB")]
    cards = fetch.roster_players(fetch.parse(ROSTER_CARDS))
    assert cards == [{"name": "Jayden Cards", "pos": "QB", "no": "9"}]
    stats = fetch.stat_lines(fetch.parse(STATS))
    assert stats["devin back"] == {"gs": 6, "reps": 90, "no": ""} and stats["connor test"]["reps"] == 150
    rows = fetch.combine(roster, stats)
    by = {r[2]: r for r in rows}
    assert by["Devin Back"][3:5] == [6, 90] and by["JT Wide"][3:5] == [5, 30]   # "J. Wide" matched by initial + last name
    assert "Dee Fender" not in by                                             # defense is left out


def test_fetch_writes_the_sheet_and_the_agent_uses_it(monkeypatch):
    from hq.football import fetch
    pages = {"/sports/football/roster/2026": ROSTER_TABLE, "/sports/football/stats/2026": STATS}
    monkeypatch.setattr(fetch, "_get", lambda url: pages[url.split(".com")[1]] if url.split(".com")[1] in pages
                        else (_ for _ in ()).throw(fetch.FetchError(f"{url} answered 404")))
    got = fetch.fetch("Northern Michigan", "https://example.com", 2026)
    assert got["players"] == 4 and got["with_stats"] == 3 and any("line starts" in n for n in got["notes"])
    assert depth.read(depth.input_for("Northern Michigan"))["players"][0]["name"]
    msg = Depth().run({"params": '{"fetch": true}'})
    assert "ready for your OK" in msg or "website" in msg or "couldn't" in msg.lower()


def test_fetch_failures_say_which_page_failed(monkeypatch):
    from hq.football import fetch
    monkeypatch.setattr(fetch, "_get", lambda url: (_ for _ in ()).throw(fetch.FetchError(f"{url} answered 404")))
    with pytest.raises(fetch.FetchError, match="roster: .*404"):
        fetch.fetch("Northern Michigan", "https://example.com", 2026)
    monkeypatch.setattr(fetch, "_get", lambda url: "<html><body>nothing here</body></html>")
    with pytest.raises(fetch.FetchError, match="no roster table"):
        fetch.fetch("Northern Michigan", "https://example.com", 2026)
    monkeypatch.setattr(season, "site_for", lambda opp: None)
    with pytest.raises(fetch.FetchError, match="don't have a website"):
        fetch.fetch("Northern Michigan")


def test_agent_falls_back_to_the_upload_when_the_site_fails(tmp_path, monkeypatch):
    from hq.football import fetch
    monkeypatch.setattr(fetch, "fetch", lambda opp: (_ for _ in ()).throw(fetch.FetchError("site down")))
    assert "couldn't fetch" in Depth().run({"params": '{"fetch": true}'}).lower()           # nothing uploaded: says so
    depth.save_upload("x.xlsx", make_xlsx(tmp_path / "x.xlsx").read_bytes(), "Northern Michigan")
    assert "ready for your OK" in Depth().run({"params": '{"fetch": true}'})
    preview = db.rows("SELECT preview FROM approvals WHERE status = 'pending'")
    assert preview and "site down" in preview[0]["preview"]


def test_monday_fetches_when_the_upload_is_missing_or_old(tmp_path, monkeypatch):
    monkeypatch.setattr(season, "site_for", lambda opp: "https://example.com")
    assert depth.run_if_due(MONDAY) == "queued"
    assert '"fetch": "auto"' in db.rows("SELECT params FROM tasks")[0]["params"]
