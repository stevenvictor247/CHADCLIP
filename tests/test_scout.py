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


# ---- discovery ----------------------------------------------------------------------------------------

from hq import discovery, ledger  # noqa: E402


def _discover(monkeypatch, fetcher=None):
    monkeypatch.setattr(llm, "HAS_LLM", True)
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: dict(DATA))
    asked = []
    monkeypatch.setattr(relay, "ask", lambda text, kind, ref, **kw: asked.append(ref))
    if fetcher:
        monkeypatch.setattr(discovery, "fetch", fetcher)
    return asked


def test_whop_and_discord_links_are_never_fetched():
    for u in ("https://whop.com/discover/content-rewards/", "https://www.whop.com/x", "https://discord.gg/abc"):
        with pytest.raises(discovery.NotAllowed):
            discovery.fetch(u)


def test_robots_txt_is_respected(monkeypatch):
    class R:
        status_code, ok, text = 200, True, "User-agent: *\nDisallow: /private"
    monkeypatch.setattr(discovery.requests, "get", lambda *a, **k: R())
    discovery._robots.clear()
    assert discovery.robots_allows("https://example.com/campaigns")
    assert not discovery.robots_allows("https://example.com/private/x")
    R.ok, R.status_code = False, 403
    discovery._robots.clear()
    assert not discovery.robots_allows("https://other.example/a")  # unreadable robots.txt means no


def test_paste_splits_links_but_keeps_page_text_whole():
    assert [i["url"] for i in discovery.split_paste("https://a.com/1\nhttps://a.com/2")] == ["https://a.com/1", "https://a.com/2"]
    one = discovery.split_paste("Campaign pays $2 per 1k views. " * 5 + "https://a.com/1")
    assert len(one) == 1 and one[0]["text"] and one[0]["url"] == "https://a.com/1"


def test_inbox_text_is_rated_and_good_ones_ask_steven(monkeypatch):
    asked = _discover(monkeypatch)
    discovery.add_to_inbox("Kai campaign rules " * 10)
    out = scout_pkg.Scout().run({"params": '{"discover": true}'})
    c = campaigns.all_campaigns()[0]
    assert c["status"] == "proposed" and c["source"] == "inbox" and asked == [c["id"]]  # never joined by itself
    assert "1 new" in out
    assert not discovery.inbox("queued")


def test_blocked_inbox_link_asks_for_pasted_text(monkeypatch):
    asked = _discover(monkeypatch)
    discovery.add_to_inbox("https://whop.com/some-campaign/")
    out = scout_pkg.Scout().run({"params": '{"discover": true}'})
    item = discovery.inbox("needs_text")[0]
    assert "paste" in item["note"] and not asked and "need you to paste" in out


def test_same_campaign_is_not_rated_twice_and_low_scores_stay_quiet(monkeypatch):
    low = dict(DATA, score=3)
    monkeypatch.setattr(llm, "HAS_LLM", True)
    calls = []
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: calls.append(1) or low)
    asked = []
    monkeypatch.setattr(relay, "ask", lambda *a, **k: asked.append(1))
    for _ in range(2):
        discovery.add_to_inbox("Same rules text " * 10)
        scout_pkg.Scout().run({"params": '{"discover": true}'})
    assert len(calls) == 1 and not asked


def test_feed_links_are_read_and_nearly_spent_campaigns_are_skipped(monkeypatch):
    pages = {"https://ok.example/feed": '<a href="/c/1">one</a><a href="https://elsewhere.com/x">x</a>',
             "https://ok.example/c/1": "<p>Pays $1 per 1k</p>"}
    asked = _discover(monkeypatch, lambda u: pages[u])
    monkeypatch.setenv("SCOUT_FEED_URLS", "https://ok.example/feed")
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: dict(DATA, budget_left_pct=5))
    scout_pkg.Scout().run({"params": '{"discover": true}'})
    c = next(c for c in campaigns.all_campaigns() if c["url"] == "https://ok.example/c/1")
    assert c["source"] == "feed" and c["status"] == "skipped" and not asked


def test_discovery_stops_when_over_budget_and_is_scheduled(monkeypatch):
    _discover(monkeypatch)
    monkeypatch.setattr(ledger, "over_budget", lambda: True)
    discovery.add_to_inbox("Rules text " * 10)
    scout_pkg.Scout().run({"params": '{"discover": true}'})
    assert discovery.inbox("queued")  # still waiting, nothing rated
    assert any(p.get("discover") for _, _, p in scout_pkg.Scout().schedule)


def test_inbox_api_and_settings_field():
    from fastapi.testclient import TestClient

    from hq import settings
    from hq.api import app
    client = TestClient(app)
    assert client.post("/api/scout/inbox", json={"text": "  "}).status_code == 400
    assert client.post("/api/scout/inbox", json={"text": "https://a.com/x"}).status_code == 200
    assert any(i["url"] == "https://a.com/x" for i in client.get("/api/state").json()["scout_inbox"])
    keys = {f["key"] for s in settings._sections() for f in s["fields"]}
    assert {"SCOUT_FEED_URLS", "SCOUT_MIN_SCORE", "SCOUT_MAX_PER_RUN"} <= keys


# ---- finding creators -----------------------------------------------------------------------------------

from hq import config as hq_config  # noqa: E402
from hq import creators  # noqa: E402

STREAMERS = [{"login": "bigsam", "name": "BigSam", "id": "1", "viewers": 90000},
             {"login": "clipfriendly", "name": "ClipFriendly", "id": "2", "viewers": 3000},
             {"login": "already", "name": "Already", "id": "3", "viewers": 50000}]
BIOS = {"1": "Variety streamer.", "2": "Business: biz@example.com. Clippers welcome! discord.gg/x", "3": "hi"}


@pytest.fixture
def twitch_stub(monkeypatch, tmp_path):
    db.execute("DELETE FROM creator_picks")
    monkeypatch.setenv("TWITCH_CLIENT_ID", "x")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "y")
    t = scout_pkg.agent.twitch
    monkeypatch.setattr(t, "top_streamers", lambda n: STREAMERS)
    monkeypatch.setattr(t, "profile", lambda i: {"bio": BIOS[i], "type": "partner"})
    monkeypatch.setattr(t, "top_clips", lambda i, days=1, limit=1: [{"title": "lol", "views": 40000 if i == "1" else 500}])
    monkeypatch.setattr(t, "permissions", lambda: {"already": "campaign"})
    streamers = tmp_path / "streamers.yaml"
    streamers.write_text("# notes\npermissions:\n  # kaicenat: \"x\"\n", encoding="utf-8")
    monkeypatch.setattr(creators, "CONFIG_DIR", tmp_path)
    return streamers


def test_creator_suggestions_rank_clipper_friendly_first_and_skip_permitted(twitch_stub):
    out = scout_pkg.Scout().run({"params": '{"creators": 5}'})
    names = [c["name"] for c in creators.pending()]
    assert names == ["ClipFriendly", "BigSam"] and "Already" not in names and "2 creator" in out
    assert "mentions clippers" in creators.pending()[0]["signals"]
    scout_pkg.Scout().run({"params": '{"creators": 5}'})  # nothing is suggested twice
    assert len(creators.pending()) == 2


def test_creators_need_twitch_keys(monkeypatch):
    monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
    assert "Twitch keys" in scout_pkg.Scout().run({"params": '{"creators": 5}'})


def test_recording_permission_writes_streamers_yaml_for_chad(twitch_stub):
    scout_pkg.Scout().run({"params": '{"creators": 5}'})
    pick = creators.pending()[0]
    with pytest.raises(ValueError):
        creators.permit(pick["id"], "ok")  # too vague to count as a recorded permission
    creators.permit(pick["id"], 'clipping program, joined "today"')
    import yaml
    assert yaml.safe_load(twitch_stub.read_text())["permissions"]["clipfriendly"] == 'clipping program, joined "today"'
    assert "# notes" in twitch_stub.read_text() and pick["id"] not in [c["id"] for c in creators.pending()]


def test_creator_api(twitch_stub):
    from fastapi.testclient import TestClient

    from hq.api import app
    scout_pkg.Scout().run({"params": '{"creators": 5}'})
    client = TestClient(app)
    picks = client.get("/api/state").json()["creator_picks"]
    assert client.post(f"/api/creators/{picks[0]['id']}/skip").status_code == 200
    assert client.post(f"/api/creators/{picks[1]['id']}/permit", json={"how": "x"}).status_code == 400
    assert client.post("/api/creators/999999/skip").status_code == 404
