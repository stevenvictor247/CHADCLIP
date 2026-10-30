"""Lens: flags zero-reach accounts, odd hours, missing hashtags and repeated captions, alerts once, and keeps decisions."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from hq import db, lens, relay
from hq.agents import get


def ts(days=0):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    db.init()
    for t in ("posts", "clips", "lens_fixes", "lens_alerts"):
        db.execute(f"DELETE FROM {t}")
    notes = []
    monkeypatch.setattr(relay, "notify", lambda text: notes.append(text))
    yield notes
    for t in ("posts", "clips", "lens_fixes", "lens_alerts"):
        db.execute(f"DELETE FROM {t}")


def post(account, views, days=5, caption="Fun clip #fun", tags=("#fun",), platform="youtube", created=None):
    cid = db.execute("INSERT INTO clips (creator, start_s, end_s, path, title, caption, hashtags, status, created_at) "
                     "VALUES ('x', 0, 30, 'p', 't', ?, ?, 'posted', ?)", caption, json.dumps(list(tags)), ts(days))
    db.execute("INSERT INTO posts (clip_id, platform, account, status, external_id, created_at, views) "
               "VALUES (?, ?, ?, 'posted', 'e', ?, ?)", cid, platform, account, created or ts(days), views)


def rules(fixes):
    return sorted(f["rule"] for f in fixes)


def test_zero_reach_needs_old_posts_and_two_or_more():
    post("dead", 0), post("dead", 0)
    post("new", 0, days=1), post("new", 0, days=1)
    post("lone", 0)
    post("ok", 0), post("ok", 40)
    assert [f["account"] for f in lens.zero_reach(lens.pull())] == ["dead"]


def test_missing_hashtags_and_repeated_captions():
    post("a", 5, caption="Plain words", tags=())
    for _ in range(3):
        post("b", 5, caption="Same   Caption #x")
    found = lens.find_fixes()
    assert "missing_hashtags" in rules(found) and "repeated_captions" in rules(found)
    assert "no_hashtags" == [f for f in found if f["rule"] == "missing_hashtags"][0]["key"]


def test_odd_hours_only_when_they_do_worse():
    night = datetime.now().astimezone().replace(hour=3, minute=0).astimezone(timezone.utc).isoformat(timespec="seconds")
    day = datetime.now().astimezone().replace(hour=15, minute=0).astimezone(timezone.utc).isoformat(timespec="seconds")
    post("a", 0, created=night), post("a", 0, created=night), post("a", 50, created=day)
    assert rules(lens.odd_hours(lens.pull())) == ["odd_hours"]
    db.execute("UPDATE posts SET views = 100 WHERE created_at = ?", night)
    assert lens.odd_hours(lens.pull()) == []


def test_groups_sum_views():
    post("a", 3), post("a", 4), post("b", 1)
    acc = {g["account"]: g for g in lens.group_by_account(lens.pull())}
    assert acc["a"]["posts"] == 2 and acc["a"]["views"] == 7
    assert sum(g["posts"] for g in lens.group_by_hour(lens.pull())) == 3


def test_telegram_note_once_and_decisions_hide_fixes(_setup):
    post("dead", 0), post("dead", 0)
    lens.run(), lens.run()
    assert len(_setup) == 1 and "dead" in _setup[0]
    key = [f for f in lens.open_fixes() if f["rule"] == "zero_reach"][0]["key"]
    assert lens.decide(key, "ignored") and not lens.decide(key, "bogus")
    assert all(f["key"] != key for f in lens.open_fixes())


def test_agent_is_free_and_idle_without_posts():
    a = get("lens")
    assert a.free and a.nothing_to_do("", {}) is True
    post("a", 1)
    assert a.nothing_to_do("", {}) is False and "Looked at 1 posts" in a.run({})
