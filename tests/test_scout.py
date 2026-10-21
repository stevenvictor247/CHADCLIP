import json

import pytest

from hq import campaigns, db, llm, relay
from hq.agents import scout as scout_pkg
from hq.agents.chad import sources
from hq.agents.chad.agent import _with_required_tags

DATA = {
    "name": "Kai Cenat Funny Moments", "creator": "Kai Cenat", "platforms": ["tiktok", "instagram"],
    "rate_per_1k": 1.5, "budget_left_pct": 70, "min_views": 1000, "max_payout": 200,
    "required_tags": ["#kaicenat", "@clipfarm"], "credit": "@KaiCenat", "rules": "Tag the campaign. No reuploads.",
    "clip_style": "Funny reactions", "content_sources": [], "red_flags": [], "score": 7.5, "verdict": "Fair pay. Easy rules.",
}


@pytest.fixture(autouse=True)
def _db():
    db.init()


def test_vet_proposes_a_campaign_and_asks_on_the_phone(monkeypatch):
    monkeypatch.setattr(llm, "HAS_LLM", True)
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: dict(DATA))
    asked = []
    monkeypatch.setattr(relay, "ask", lambda text, kind, ref, **kw: asked.append((kind, ref)))
    out = scout_pkg.Scout().run({"params": json.dumps({"text": "campaign page", "url": "https://whop.com/x",
                                                       "sources": ["https://youtube.com/@kai/videos"]})})
    c = campaigns.all_campaigns()[0]
    assert c["status"] == "proposed" and c["content_sources"] == ["https://youtube.com/@kai/videos"]
    assert asked == [("campaign", c["id"])] and "Kai Cenat Funny Moments" in out
    assert any("1,000 views" in f for f in c["flags"])


def test_joined_campaign_becomes_a_permitted_creator_for_chad():
    cid = campaigns.propose(dict(DATA), "https://whop.com/y", ["https://youtube.com/@kai/videos"])
    assert not [c for c in sources.load_creators() if c.get("campaign_id") == cid]  # not joined yet
    msg = campaigns.decide(cid, "join")
    assert "Chad can clip it now" in msg
    creator = next(c for c in sources.load_creators() if c.get("campaign_id") == cid)
    assert sources.is_permitted(creator) and "whop.com/y" in creator["permission"]
    assert creator["sources"] == ["https://youtube.com/@kai/videos"] and creator["credit"] == "@KaiCenat"


def test_skipped_campaign_is_not_clipped():
    cid = campaigns.propose(dict(DATA), None, ["https://youtube.com/@a/videos"])
    campaigns.decide(cid, "skip")
    assert not [c for c in sources.load_creators() if c.get("campaign_id") == cid]


def test_required_tags_come_first_and_are_not_duplicated():
    out = _with_required_tags(["funny", "KaiCenat", "fyp"], {"required_tags": ["#kaicenat", "@clipfarm"]})
    assert out[:2] == ["kaicenat", "clipfarm"] and out.count("kaicenat") == 1 and "KaiCenat" not in out
    assert _with_required_tags(["a"], {}) == ["a"]


def test_posted_campaign_clips_become_a_submission_todo_once(monkeypatch):
    cid = campaigns.propose(dict(DATA), None, [])
    clip = db.execute("INSERT INTO clips (creator, start_s, end_s, path, title, campaign_id, created_at) "
                      "VALUES ('Kai Cenat', 0, 5, 'x.mp4', 't', ?, ?)", cid, db.now())
    db.execute("INSERT INTO posts (clip_id, platform, account, status, url, created_at) VALUES (?, 'tiktok', 'a', 'posted', 'https://tiktok.com/v/1', ?)", clip, db.now())
    notes = []
    monkeypatch.setattr(relay, "notify", notes.append)
    agent = scout_pkg.Scout()
    assert "to submit" in agent.run({"params": '{"sync": true}'}) and len(notes) == 1
    assert "No new" in agent.run({"params": '{"sync": true}'})
    sub = db.rows("SELECT * FROM submissions WHERE clip_id = ?", clip)[0]
    campaigns.record(sub["id"], views=20000, earned_usd=30.0, status="paid")
    t = next(c for c in campaigns.summary() if c["id"] == cid)["totals"]
    assert t["views"] == 20000 and t["earned_usd"] == 30.0 and t["expected_usd"] == 30.0
    with pytest.raises(ValueError):
        campaigns.record(sub["id"], status="nonsense")


def test_campaign_button_on_phone_joins_it():
    cid = campaigns.propose(dict(DATA), None, ["https://youtube.com/@a/videos"])
    assert "joined" in relay.DECIDERS["campaign"](cid, "approve")
    assert campaigns.get(cid)["status"] == "joined"


def test_dashboard_api_shows_and_decides_campaigns():
    from fastapi.testclient import TestClient

    from hq.api import app
    cid = campaigns.propose(dict(DATA), None, [])
    client = TestClient(app)
    assert any(c["id"] == cid for c in client.get("/api/state").json()["campaigns"])
    assert client.post(f"/api/campaigns/{cid}/join").json()["message"].startswith("Campaign")
    assert client.post("/api/campaigns/999999/join").status_code == 404
    assert client.post(f"/api/campaigns/{cid}/maybe").status_code == 400
