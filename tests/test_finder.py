import json

import pytest

from hq import approvals, db, llm, relay
from hq.agents.pitch import agent as pitch_mod, finder
from hq.agents.pitch.agent import Pitch
from tests.test_pitch import CFG, DRAFT


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    db.init()
    db.execute("DELETE FROM leads")
    db.execute("DELETE FROM email_finds")
    monkeypatch.setattr(pitch_mod, "settings", lambda: dict(CFG))
    monkeypatch.setattr(llm, "HAS_LLM", True)
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: dict(DRAFT))
    monkeypatch.setattr(relay, "notify", lambda *a, **k: None)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    yield
    db.execute("DELETE FROM leads")
    db.execute("DELETE FROM email_finds")
    db.execute("DELETE FROM approvals")


def pages(monkeypatch, site: dict):
    asked = []

    def get(url):
        asked.append(url)
        return site.get(url)
    monkeypatch.setattr(finder, "_get", get)
    return asked


def test_bio_email_wins_without_any_fetch(monkeypatch):
    asked = pages(monkeypatch, {})
    r = finder.find_email("twitch", "sam", "business: Sam@Example.org")
    assert r == {"email": "sam@example.org", "source": "their Twitch bio", "url": ""} and asked == []


def test_follows_linktree_to_the_creators_own_site(monkeypatch):
    asked = pages(monkeypatch, {
        "https://linktr.ee/sam": '<a href="https://instagram.com/sam">ig</a><a href="https://sam.gg">site</a>',
        "https://sam.gg": "<p>hello</p>",
        "https://sam.gg/contact": '<a href="mailto:biz@sam.gg">email me</a>'})
    r = finder.find_email("twitch", "sam", "links: linktr.ee/sam")
    assert r["email"] == "biz@sam.gg" and r["source"] == "their website" and r["url"] == "https://sam.gg/contact"
    assert not any("instagram" in u for u in asked)


def test_never_fetches_social_sites_and_ignores_junk_emails(monkeypatch):
    asked = pages(monkeypatch, {"https://sam.gg": "noreply@sam.gg img@2x.png a@domain.com"})
    assert finder.find_email("twitch", "sam", "https://x.com/sam https://instagram.com/sam https://sam.gg") is None
    assert asked == ["https://sam.gg", "https://sam.gg/contact", "https://sam.gg/about", "https://sam.gg/business"]


def test_obfuscated_email(monkeypatch):
    pages(monkeypatch, {"https://sam.gg": "contact: sam [at] sam [dot] gg"})
    assert finder.find_email("twitch", "sam", "https://sam.gg")["email"] == "sam@sam.gg"


def test_robots_and_private_hosts_are_respected(monkeypatch):
    class R:
        status_code, text, headers = 200, "User-agent: *\nDisallow: /", {}
    monkeypatch.setattr(finder.requests, "get", lambda *a, **k: R())
    monkeypatch.setattr(finder, "_public_host", lambda h: True)
    finder._robots.clear()
    assert finder._get("https://sam.gg") is None
    monkeypatch.undo()
    assert finder._get("http://127.0.0.1/secret") is None
    assert finder._get("https://twitter.com/sam") is None


def test_results_and_misses_are_cached(monkeypatch):
    asked = pages(monkeypatch, {"https://sam.gg": "hi@sam.gg"})
    assert finder.find_email("twitch", "sam", "https://sam.gg")["email"] == "hi@sam.gg"
    assert finder.find_email("twitch", "sam", "")["email"] == "hi@sam.gg" and asked == ["https://sam.gg"]
    assert finder.find_email("twitch", "ghost", "") is None
    asked.clear()
    assert finder.find_email("twitch", "ghost", "https://ghost.gg") is None and asked == []


def test_youtube_description_via_api(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")

    class R:
        def raise_for_status(self): pass
        def json(self): return {"items": [{"snippet": {"description": "Business: yt@sam.tv"}}]}
    monkeypatch.setattr(finder.requests, "get", lambda *a, **k: R())
    r = finder.find_email("twitch", "sam", "https://youtube.com/@sam")
    assert r["email"] == "yt@sam.tv" and "YouTube" in r["source"]


def test_find_uses_other_sources_shows_source_and_skips_the_rest(monkeypatch):
    monkeypatch.setattr(pitch_mod, "settings", lambda: {**CFG, "require_email": True})
    monkeypatch.setattr(pitch_mod.twitch, "small_streamers", lambda *a, **k: [
        {"login": "linked", "name": "Linked", "id": "1", "viewers": 300, "game": "X"},
        {"login": "nothing", "name": "Nothing", "id": "2", "viewers": 300, "game": "Y"}])
    monkeypatch.setattr(pitch_mod.twitch, "profile", lambda uid: {"bio": "links https://sam.gg" if uid == "1" else "vibes", "type": ""})
    monkeypatch.setattr(pitch_mod.twitch, "top_clips", lambda *a, **k: [])
    pages(monkeypatch, {"https://sam.gg": "mailto:biz@sam.gg"})
    assert "Drafted 1" in Pitch().run({"params": json.dumps({"find": 5})})
    card = approvals.pending()[-1]
    assert "Email found via their website (https://sam.gg)" in card["preview"] and "biz@sam.gg" in card["preview"]
    assert [l["handle"] for l in db.rows("SELECT handle FROM leads")] == ["linked"]


def test_manual_lead_with_a_link_gets_an_email_looked_up(monkeypatch):
    pages(monkeypatch, {"https://sam.gg": "hi@sam.gg"})
    Pitch().run({"params": json.dumps({"lead": {"name": "Sam", "platform": "youtube", "handle": "sam",
                                                "contact": "https://sam.gg"}})})
    assert db.rows("SELECT contact FROM leads")[0]["contact"] == "hi@sam.gg"


def test_recheck_switches_waiting_cards_to_send_email(monkeypatch):
    monkeypatch.setattr(pitch_mod.mailer, "configured", lambda: True)
    monkeypatch.setattr(pitch_mod.mailer, "credentials", lambda: ("steven@gmail.com", "x"))
    pages(monkeypatch, {})
    for h in ("linked", "bare"):
        Pitch().run({"params": json.dumps({"lead": {"name": h.title(), "platform": "twitch", "handle": h,
                                                    "contact": "https://twitch.tv/" + h + " (no email in bio)",
                                                    "notes": "Their bio: site https://" + h + ".gg" if h == "linked" else "just vibes"}})})
    assert [a["yes_label"] for a in approvals.pending()] == ["I'll send it"] * 2
    monkeypatch.setattr(pitch_mod.twitch, "profile_by_login", lambda login: {"bio": "", "type": ""})
    pages(monkeypatch, {"https://linked.gg": "biz@linked.gg"})
    out = Pitch().run({"params": json.dumps({"recheck": True})})
    assert "biz@linked.gg" in out and "Bare" in out
    linked, bare = approvals.pending()
    assert linked["yes_label"] == "Send email" and linked["payload"]["email"] is True
    assert "Email found via their website" in linked["preview"] and "Contact: biz@linked.gg" in linked["preview"]
    assert bare["yes_label"] == "I'll send it"
    assert "no public email found" in bare["preview"] and "Reach them on Twitch" in bare["preview"]
    Pitch().run({"params": json.dumps({"recheck": True})})  # a second run replaces the note instead of stacking it
    assert approvals.pending()[1]["preview"].count("Checked ") == 1
    assert db.rows("SELECT contact FROM leads WHERE handle = 'linked'")[0]["contact"] == "biz@linked.gg"


def test_recheck_button_endpoint_queues_a_pitch_task():
    from fastapi.testclient import TestClient
    from hq import api
    db.execute("DELETE FROM tasks")
    r = TestClient(api.app).post("/api/pitch/recheck", headers={"X-HQ": "1"})
    assert r.status_code == 200
    t = db.rows("SELECT agent, params FROM tasks")[-1]
    assert t["agent"] == "Pitch" and json.loads(t["params"]) == {"recheck": True}
