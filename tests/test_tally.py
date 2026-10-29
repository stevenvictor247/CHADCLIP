"""Tally: view counts land on posts and campaign submissions, and Chad hears what worked."""

import json

import pytest

from hq import db, tally
from hq.agents import AGENTS


@pytest.fixture
def posted(monkeypatch, tmp_path):
    db.init()
    monkeypatch.setattr(tally, "INSIGHTS_PATH", tmp_path / "insights.json")
    monkeypatch.setattr(tally, "TALLY_DIR", tmp_path)
    monkeypatch.setattr(tally, "REPORT_PATH", tmp_path / "report.json")
    db.execute("UPDATE posts SET status = 'skipped' WHERE status = 'posted'")  # leftovers from other tests

    def clip(title, creator, seconds):
        cid = db.execute("INSERT INTO clips (creator, start_s, end_s, path, title, status, created_at) "
                         "VALUES (?, 0, ?, 'x.mp4', ?, 'posted', ?)", creator, seconds, title, db.now())
        pid = db.execute("INSERT INTO posts (clip_id, platform, account, status, external_id, created_at) "
                         "VALUES (?, 'youtube', 'youtube_main', 'posted', ?, ?)", cid, f"vid{cid}", db.now())
        return cid, pid
    return clip


def test_tally_is_a_free_scheduled_agent():
    t = AGENTS["tally"]
    assert t.free and t.schedule and t.schedule[0][0] == 12


def test_views_fill_posts_submissions_and_chads_prompt(posted, monkeypatch):
    a, pa = posted("Huge reaction", "Kai", 31)
    b, pb = posted("Quiet bit", "Kai", 50)
    camp = db.execute("INSERT INTO campaigns (name, creator, rate_per_1k, min_views, max_payout, status, created_at) "
                      "VALUES ('Kai clips', 'Kai', 2.0, 1000, 5, 'joined', ?)", db.now())
    sub = db.execute("INSERT INTO submissions (campaign_id, clip_id, post_id, status, views, earned_usd, created_at, "
                     "updated_at) VALUES (?, ?, ?, 'submitted', 0, 0, ?, ?)", camp, a, pa, db.now(), db.now())

    def fake_fetch():
        tally._save_views(pa, 12000)
        tally._save_views(pb, 300)
        return 2, []
    monkeypatch.setitem(tally.FETCHERS, "youtube", fake_fetch)

    out = tally.run()
    assert "Counted views on 2 posts" in out and "Huge reaction" in out
    assert db.rows("SELECT views FROM submissions WHERE id = ?", sub)[0]["views"] == 12000
    assert tally.estimated_pay() >= 5.0          # 12k views at $2/1k is $24, capped at $5 per clip
    note = tally.for_chad("Kai")
    assert note.startswith("Recent results: Kai's clips") and "Huge reaction" in note and "12,000 views" in note
    assert tally.summary()["views_7d"] >= 12300

    # views never go down (a platform glitch reporting 0 doesn't wipe the count)
    tally._save_views(pa, 0)
    assert db.rows("SELECT views FROM posts WHERE id = ?", pa)[0]["views"] == 12000


def test_nothing_posted_yet_is_said_plainly(posted, monkeypatch):
    monkeypatch.setitem(tally.FETCHERS, "youtube", lambda: (0, []))
    assert "No posted clips to count yet" in tally.run()
    assert tally.for_chad("Anyone") == ""


def test_chad_prompt_includes_results(monkeypatch, tmp_path):
    from hq import llm
    from hq.agents.chad import moments
    monkeypatch.setattr(tally, "INSIGHTS_PATH", tmp_path / "insights.json")
    (tmp_path / "insights.json").write_text(json.dumps({"best": [{"title": "Big win", "creator": "Kai", "views": 9000,
                                                                   "seconds": 30}]}))
    seen = {}

    def fake_ask(model, system, prompt, schema, **kw):
        seen["prompt"] = prompt
        return {"moments": [{"start": 0, "end": 20, "title": "t", "caption": "c", "hashtags": [], "score": 5,
                             "reason": "r"}]}
    monkeypatch.setattr(llm, "HAS_LLM", True)
    monkeypatch.setattr(llm, "ask_json", fake_ask)
    moments.pick({"segments": [{"start": 0, "end": 20, "text": "hi"}], "words": []}, 60, "Video", {"name": "Kai"}, 1, 15, 59)
    assert "Big win" in seen["prompt"] and "9,000 views" in seen["prompt"]


def test_chad_hears_what_steven_approved_and_rejected():
    db.init()
    for title, status in (("Clean comeback line", "posted"), ("Long boring intro", "rejected")):
        db.execute("INSERT INTO clips (creator, start_s, end_s, path, title, status, created_at) "
                   "VALUES ('TasteTest', 0, 30, 'x.mp4', ?, ?, ?)", title, status, db.now())
    line = tally.your_taste("TasteTest")
    assert "approved clips like \"Clean comeback line\"" in line and "rejected clips like \"Long boring intro\"" in line
    assert tally.your_taste("Nobody-yet")   # falls back to every creator


def test_daily_report_shows_change_since_yesterday(posted, monkeypatch, tmp_path):
    monkeypatch.setattr(tally, "REPORT_PATH", tmp_path / "report.json")
    sent = []
    from hq import relay
    monkeypatch.setattr(relay, "notify", sent.append)
    a, pa = posted("Huge reaction", "Kai", 31)
    b, pb = posted("Quiet bit", "Kai", 50)
    tally._save_views(pa, 1500)
    tally._save_views(pb, 300)
    db.execute("DELETE FROM view_snapshots")
    for pid, v in ((pa, 1000), (pb, 290)):
        db.execute("INSERT INTO view_snapshots (post_id, day, views) VALUES (?, '2000-01-01', ?)", pid, v)
    r = tally.build_report()
    assert r["total"] == 1800 and r["change"] == 510
    assert r["top"]["name"] == "Huge reaction" and r["top"]["change"] == 500
    text = tally.send_report()
    assert "+510 since yesterday" in text and "Youtube: 1,800" in text and sent == [text]
    assert tally.send_report() == ""                      # once a day on the schedule
    assert tally.send_report(force=True) and len(sent) == 2   # the button always sends


def test_first_report_has_no_change_yet(posted):
    a, pa = posted("Huge reaction", "Kai", 31)
    tally._save_views(pa, 40)
    db.execute("DELETE FROM view_snapshots")
    assert "first count" in tally.format_report(tally.build_report())
