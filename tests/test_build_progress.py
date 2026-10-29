"""The Ideas tab's build progress bar: stages come from the idea's pull request on GitHub."""
from datetime import datetime, timedelta, timezone

import importlib

import pytest

from tests.test_muse import GOOD, _fake_llm, _fresh


@pytest.fixture(autouse=True)
def _restore_hq():
    """_fresh() reloads HQ onto a temp data folder; point it back so test files that run next still find their DB."""
    yield
    import hq.config, hq.db
    importlib.invalidate_caches()
    for m in (hq.config, hq.db):
        importlib.reload(m)


def _setup(monkeypatch, tmp_path, minutes_ago=10):
    hq = _fresh(monkeypatch, tmp_path)
    _fake_llm(monkeypatch, hq, GOOD)
    hq.muse.run(manual=True)
    i = hq.db.rows("SELECT id FROM ideas ORDER BY id")[0]["id"]
    sent = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
    hq.db.execute("UPDATE ideas SET status = 'approved', build_status = 'started', build_at = ? WHERE id = ?", sent, i)
    return hq, i, sent


def _pr(i, sent, **kw):
    made = (datetime.fromisoformat(sent) + timedelta(minutes=3)).isoformat()
    return {"number": 9, "html_url": "https://github.com/x/y/pull/9", "title": f"Build idea #{i}", "body": "",
            "created_at": made, "state": "open", "merged_at": None, "head": {"sha": "abc"}, **kw}


def _github(monkeypatch, hq, prs, runs):
    def get(path):
        return prs if path.startswith("pulls") else {"check_runs": runs}
    monkeypatch.setattr(hq.build_progress, "_get", get)


def stage(hq, i):
    return hq.build_progress.progress(hq.db.rows("SELECT * FROM ideas WHERE id = ?", i)[0])


def test_stages_follow_the_pull_request(monkeypatch, tmp_path):
    hq, i, sent = _setup(monkeypatch, tmp_path)
    _github(monkeypatch, hq, [], [])
    assert (stage(hq, i)["key"], stage(hq, i)["pct"]) == ("building", 30)           # no PR yet
    _github(monkeypatch, hq, [_pr(i, sent)], [{"status": "in_progress", "conclusion": None}])
    assert stage(hq, i)["key"] == "tests" and stage(hq, i)["pr_number"] == 9
    _github(monkeypatch, hq, [_pr(i, sent)], [{"status": "completed", "conclusion": "success"}])
    assert stage(hq, i)["key"] == "passed" and stage(hq, i)["pct"] == 85
    _github(monkeypatch, hq, [_pr(i, sent)], [{"status": "completed", "conclusion": "failure"}])
    assert stage(hq, i)["bad"] and stage(hq, i)["label"] == "Tests failed"


def test_merged_then_live_marks_the_idea_built(monkeypatch, tmp_path):
    hq, i, sent = _setup(monkeypatch, tmp_path)
    merged = _pr(i, sent, state="closed", merged_at="2026-10-26T21:00:00Z", merge_commit_sha="deadbeef")
    _github(monkeypatch, hq, [merged], [])
    monkeypatch.setattr(hq.build_progress, "is_live", lambda sha: False)
    assert stage(hq, i)["key"] == "merged"
    monkeypatch.setattr(hq.build_progress, "is_live", lambda sha: sha == "deadbeef")
    out = hq.muse.latest()["ideas"]
    assert [x["progress"]["key"] for x in out if x["id"] == i] == ["live"]
    assert hq.db.rows("SELECT status FROM ideas WHERE id = ?", i)[0]["status"] == "built"


def test_only_this_ideas_pr_after_it_was_sent_counts(monkeypatch, tmp_path):
    hq, i, sent = _setup(monkeypatch, tmp_path)
    old = _pr(i, sent, created_at=(datetime.fromisoformat(sent) - timedelta(days=1)).isoformat())
    other = _pr(i + 50, sent)
    _github(monkeypatch, hq, [old, other], [])
    assert stage(hq, i)["key"] == "building"


def test_github_trouble_and_unsent_ideas(monkeypatch, tmp_path):
    hq, i, sent = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(hq.build_progress, "_get", lambda path: (_ for _ in ()).throw(OSError("offline")))
    assert stage(hq, i)["key"] == "unknown"                                          # says so, never crashes
    hq.db.execute("UPDATE ideas SET build_status = NULL WHERE id = ?", i)
    assert stage(hq, i) is None
