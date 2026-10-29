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
    "clip_style": "Funny reactions", "content_sources": [], "red_flags": [], "score": 8.5, "verdict": "Fair pay. Easy rules.",
    "score_reasons": ["Payout: $1.5 per 1,000 views, fair", "Rules: clear"],
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
    client = TestClient(app, headers={"X-HQ": "1"})
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
    client = TestClient(app, headers={"X-HQ": "1"})
    assert client.post("/api/scout/inbox", json={"text": "  "}).status_code == 400
    assert client.post("/api/scout/inbox", json={"text": "https://a.com/x"}).status_code == 200
    assert any(i["url"] == "https://a.com/x" for i in client.get("/api/state").json()["scout_inbox"])
    keys = {f["key"] for s in settings._sections() for f in s["fields"]}
    assert {"SCOUT_FEED_URLS", "SCOUT_MIN_SCORE", "SCOUT_MAX_PER_RUN"} <= keys


# ---- finding creators -----------------------------------------------------------------------------------

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
    client = TestClient(app, headers={"X-HQ": "1"})
    picks = client.get("/api/state").json()["creator_picks"]
    assert client.post(f"/api/creators/{picks[0]['id']}/skip").status_code == 200
    assert client.post(f"/api/creators/{picks[1]['id']}/permit", json={"how": "x"}).status_code == 400
    assert client.post("/api/creators/999999/skip").status_code == 404


def test_creators_already_pitched_are_not_suggested(twitch_stub):
    db.execute("DELETE FROM leads")
    ts = db.now()
    db.execute("INSERT INTO leads (name, platform, handle, status, created_at, updated_at) "
               "VALUES ('BigSam', 'twitch', 'BigSam', 'pitched', ?, ?)", ts, ts)
    scout_pkg.Scout().run({"params": '{"creators": 5}'})
    assert [c["name"] for c in creators.pending()] == ["ClipFriendly"]
    db.execute("DELETE FROM leads")


def test_they_said_yes_records_permission_and_marks_client(twitch_stub):
    from hq.agents.pitch.agent import they_said_yes
    db.execute("DELETE FROM leads")
    ts = db.now()
    lid = db.execute("INSERT INTO leads (name, platform, handle, status, created_at, updated_at) "
                     "VALUES ('BigSam', 'twitch', 'BigSam', 'pitched', ?, ?)", ts, ts)
    they_said_yes(lid, "replied to my email, OK to clip")
    assert "bigsam: \"replied to my email, OK to clip\"" in twitch_stub.read_text()
    assert db.rows("SELECT status FROM leads WHERE id = ?", lid)[0]["status"] == "client"
    kick = db.execute("INSERT INTO leads (name, platform, handle, status, created_at, updated_at) "
                      "VALUES ('K', 'kick', 'k', 'pitched', ?, ?)", ts, ts)
    with pytest.raises(ValueError):
        they_said_yes(kick, "yes")
    db.execute("DELETE FROM leads")


def test_steven_can_add_a_streamer_himself(tmp_path, monkeypatch):
    from hq import creators
    (tmp_path / "streamers.yaml").write_text("# notes\npermissions:\n  # kaicenat: ''\n")
    monkeypatch.setattr(creators, "CONFIG_DIR", tmp_path)
    assert creators.allowed() == []
    creators.add_allowed("https://www.twitch.tv/Jynxzi/", "public open-clipping policy")
    assert creators.allowed() == [{"login": "jynxzi", "how": "public open-clipping policy"}]
    assert "# notes" in (tmp_path / "streamers.yaml").read_text()
    with pytest.raises(ValueError):
        creators.add_allowed("@jynxzi", "public open-clipping policy")   # already there
    with pytest.raises(ValueError):
        creators.add_allowed("two words", "public open-clipping policy")
    with pytest.raises(ValueError):
        creators.add_allowed("someone", "ok")   # too vague to count as permission


def _search_reply(*candidates, stop="end_turn"):
    from types import SimpleNamespace as NS
    return NS(stop_reason=stop, content=[NS(type="text", text="Here is what I found.\n" + json.dumps({"candidates": list(candidates)}))])


def _web(monkeypatch, replies):
    """Scout's web search with Claude's answers faked. Returns the list of create() calls."""
    db.execute("DELETE FROM scout_inbox")   # other tests share this database: start from a quiet Scout
    db.execute("DELETE FROM scout_seen")
    asked = _discover(monkeypatch, lambda u: (_ for _ in ()).throw(discovery.NotAllowed("robots.txt says no")))
    monkeypatch.setenv("SCOUT_WEB_SEARCH", "1")
    calls = []

    def create(model, system, messages, tools=None, **kw):
        calls.append({"model": model, "messages": messages, "tools": tools})
        return replies.pop(0)
    monkeypatch.setattr(llm, "create", create)
    return asked, calls


def test_web_search_finds_campaigns_by_itself_once_a_day(monkeypatch):
    good = {"name": "Streamer clip program", "url": "https://clips.example/program", "excerpt": "Pays $2 per 1,000 views. Tag @x."}
    whop = {"name": "Whop thing", "url": "https://whop.com/some-campaign/", "excerpt": "Pays $3 per 1k"}
    asked, calls = _web(monkeypatch, [_search_reply(good, whop)])
    out = scout_pkg.Scout().run({"params": '{"discover": true}'})
    found = [c for c in campaigns.all_campaigns() if (c["source"] or "").startswith("web")]
    assert [c["url"] for c in found] == ["https://clips.example/program"]   # the Whop link never gets through
    assert found[0]["source"] == "web (excerpt only)" and found[0]["status"] == "proposed" and asked == [found[0]["id"]]
    tool = calls[0]["tools"][0]
    assert tool["name"] == "web_search" and "whop.com" in tool["blocked_domains"] and "discord.com" in tool["blocked_domains"]
    assert "1 new" in out
    # a second run the same day does not search again, and Scout knows there is nothing to start
    scout_pkg.Scout().run({"params": '{"discover": true}'})
    assert len(calls) == 1
    assert scout_pkg.Scout().nothing_to_do("", {"discover": True}) is True


def test_a_paused_web_search_is_resumed(monkeypatch):
    from types import SimpleNamespace as NS
    paused = NS(stop_reason="pause_turn", content=[NS(type="server_tool_use")])
    _, calls = _web(monkeypatch, [paused, _search_reply()])
    scout_pkg.Scout().run({"params": '{"discover": true}'})
    assert len(calls) == 2 and calls[1]["messages"][-1]["role"] == "assistant"   # no extra "continue" message


def test_web_search_can_be_switched_off(monkeypatch):
    _, calls = _web(monkeypatch, [])
    monkeypatch.setenv("SCOUT_WEB_SEARCH", "0")
    scout_pkg.Scout().run({"params": '{"discover": true}'})
    assert not calls and scout_pkg.Scout().nothing_to_do("", {"discover": True}) is True


def test_web_search_due_means_a_round_is_queued(monkeypatch):
    _web(monkeypatch, [])
    assert scout_pkg.Scout().nothing_to_do("", {"discover": True}) is False


def test_a_failed_web_search_is_reported_not_retried_all_day(monkeypatch):
    _, calls = _web(monkeypatch, [])   # create() has no answers left: pop from empty list raises
    out = scout_pkg.Scout().run({"params": '{"discover": true}'})
    assert "web search:" in out and not discovery.web_search_due()


def test_web_searches_are_billed_in_the_ledger():
    from types import SimpleNamespace as NS
    from hq import ledger
    usage = NS(input_tokens=0, output_tokens=0, server_tool_use=NS(web_search_requests=5))
    assert ledger.record("Scout", "claude-sonnet-5-5", usage) == pytest.approx(0.05)


def test_search_answer_without_json_means_no_candidates():
    assert scout_pkg.Scout._candidates_in("I found nothing useful.") == []
    assert scout_pkg.Scout._candidates_in('{"candidates": "oops"}') == []


# ---- the 8/10 bar ----------------------------------------------------------------------------------------

def test_default_bar_is_eight_and_can_be_changed(monkeypatch):
    monkeypatch.delenv("SCOUT_MIN_SCORE", raising=False)
    assert campaigns.min_score() == 8
    monkeypatch.setenv("SCOUT_MIN_SCORE", "9")
    assert campaigns.min_score() == 9
    monkeypatch.setenv("SCOUT_MIN_SCORE", "junk")
    assert campaigns.min_score() == 8


def test_plain_rules_hold_the_score_down():
    assert campaigns.capped_score(dict(DATA, score=9.5, red_flags=["asks for a deposit"]), []) == 5
    assert campaigns.capped_score(dict(DATA, score=9.5, rate_per_1k=None), []) == 6
    assert campaigns.capped_score(dict(DATA, score=9.5, budget_left_pct=10), []) == 4
    assert campaigns.capped_score(dict(DATA, score=9.5), []) == 9.5


def test_only_eight_plus_found_campaigns_are_shown_and_asked_about(monkeypatch):
    pages = {"https://bar.example/feed": '<a href="/c/1">one</a><a href="/c/2">two</a>',
             "https://bar.example/c/1": "<p>great</p>", "https://bar.example/c/2": "<p>meh</p>"}
    asked = _discover(monkeypatch, lambda u: pages[u])
    monkeypatch.delenv("SCOUT_MIN_SCORE", raising=False)
    monkeypatch.setenv("SCOUT_FEED_URLS", "https://bar.example/feed")
    scores = iter([8.5, 7.5])
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: dict(DATA, score=next(scores), name="c"))
    scout_pkg.Scout().run({"params": '{"discover": true}'})
    mine = lambda rows: [c for c in rows if (c["url"] or "").startswith("https://bar.example/c/")]
    shown = mine(campaigns.summary())
    assert [c["score"] for c in shown] == [8.5] and len(mine(campaigns.all_campaigns())) == 2
    assert asked == [shown[0]["id"]]
    assert shown[0]["score_reasons"][0].startswith("Payout")
    monkeypatch.setenv("SCOUT_MIN_SCORE", "7")   # lowering the bar in Settings reveals the other one
    assert len(mine(campaigns.summary())) == 2


def test_campaigns_steven_pasted_always_show(monkeypatch):
    monkeypatch.setattr(llm, "HAS_LLM", True)
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: dict(DATA, score=3))
    monkeypatch.setattr(relay, "ask", lambda *a, **k: None)
    before = len(campaigns.summary())
    scout_pkg.Scout().run({"params": json.dumps({"text": "rules"})})
    assert len(campaigns.summary()) == before + 1
