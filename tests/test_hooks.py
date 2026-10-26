"""Hook Lab: three opening lines per clip, Steven picks one, Tally learns which style gets the views."""

import json

import pytest
from fastapi.testclient import TestClient

from hq import api, db, hooks, tally
from hq.agents.chad import moments


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    db.init()
    monkeypatch.setattr(tally, "INSIGHTS_PATH", tmp_path / "insights.json")
    monkeypatch.setattr(tally, "TALLY_DIR", tmp_path)
    monkeypatch.setattr(tally, "REPORT_PATH", tmp_path / "report.json")
    db.execute("UPDATE clips SET hook_style = NULL")
    db.execute("UPDATE posts SET status = 'skipped' WHERE status = 'posted'")


def make_clip(style=None, views=None, caption="Great bit\n\nCredit: Kai"):
    cid = db.execute("INSERT INTO clips (start_s, end_s, path, title, caption, status, hooks, hook_style, created_at) "
                     "VALUES (0, 30, 'x.mp4', 'Great bit', ?, 'posted', ?, ?, ?)",
                     caption, json.dumps(hooks.build(None, "Great bit")), style, db.now())
    if views is not None:
        db.execute("INSERT INTO posts (clip_id, platform, account, status, views, created_at) "
                   "VALUES (?, 'youtube', 'a', 'posted', ?, ?)", cid, views, db.now())
    return cid


def test_build_always_gives_three_labeled_styles_and_winner_goes_first():
    out = hooks.build(["Why?", "", None], "My title")
    assert [o["label"] for o in out] == ["A", "B", "C"]
    assert len({o["style"] for o in out}) == 3
    assert out[0]["text"] == "Why?" and all(o["text"] for o in out)   # blanks are filled from templates
    assert hooks.build(None, "t", "tease")[0]["style"] == "tease"
    assert hooks.build(None, "t", "nonsense")[0]["style"] == "question"


def test_chad_fallback_moments_still_get_hooks_without_claude(monkeypatch):
    monkeypatch.setattr(moments.llm, "HAS_LLM", False)
    picked = moments.pick(None, 100, "Title", {"name": "Kai"}, 1, 15, 59)
    assert len(hooks.build(picked[0].get("hooks"), picked[0]["title"])) == 3


def test_choosing_a_hook_rewrites_caption_and_replaces_earlier_pick():
    cid = make_clip()
    r = hooks.choose(cid, "b")
    assert r["caption"].startswith(r["caption"].split("\n\n")[0]) and r["caption"].endswith("Credit: Kai")
    first = db.rows("SELECT hook_text FROM clips WHERE id = ?", cid)[0]["hook_text"]
    hooks.choose(cid, "C")
    row = db.rows("SELECT caption, hook_label, hook_style FROM clips WHERE id = ?", cid)[0]
    assert row["hook_label"] == "C" and first not in row["caption"] and row["caption"].count("Credit: Kai") == 1
    with pytest.raises(ValueError):
        hooks.choose(cid, "Z")
    with pytest.raises(ValueError):
        hooks.choose(999999, "A")


def test_api_pick_hook():
    cid = make_clip()
    c = TestClient(api.app, headers={"X-HQ": "1"})
    assert c.post(f"/api/clips/{cid}/hook", json={"label": "A"}).json()["label"] == "A"
    assert c.post(f"/api/clips/{cid}/hook", json={"label": "Q"}).status_code == 400


def test_no_winner_until_20_clips_then_best_average_wins():
    for _ in range(5):
        make_clip("question", 10)
    assert hooks.stats()["winner"] is None and "no winner yet" in hooks.report_line()
    for _ in range(8):
        make_clip("tease", 100)
    for _ in range(7):
        make_clip("bold_claim", 50)
    s = hooks.stats()
    assert s["counted"] == 20 and s["winner"] == "tease"
    assert "tease won" in hooks.report_line() and "tease" in hooks.for_chad()
    assert hooks.build(None, "t", hooks.winning_style())[0]["style"] == "tease"   # Chad leads with the winner
    assert tally.summary()["hooks"]["winner"] == "tease"


def test_a_tie_or_thin_style_is_no_win():
    for style in ("question", "tease", "bold_claim"):
        for _ in range(7):
            make_clip(style, 20)
    assert hooks.stats()["counted"] == 21 and hooks.stats()["winner"] is None
