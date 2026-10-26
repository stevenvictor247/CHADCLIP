"""Recap: free checks first, one cheap Claude call, a pack waiting for approval, and nothing ever sent."""

import json

import pytest

from hq import agents, approvals, db, llm, recap, relay
from hq.agents.recap import Recap

PACK = {"title_options": ["How I beat the final boss", "Boss fight, no deaths", "Why this build works"],
        "description": "A long stream: the boss fight, a chat Q&A and plans for next week.",
        "chapters": [{"start_seconds": 300, "title": "Boss fight"}, {"start_seconds": 1500, "title": "Chat Q&A"},
                     {"start_seconds": 2400, "title": "Next week"}],
        "posts": [f"Post idea {i}" for i in range(5)]}
OWNER = "emailed me the VOD on 26 Oct"


def transcript(minutes=60, words_per_line=20):
    return "\n".join(f"[{m // 60}:{m % 60:02d}:00] " + " ".join(["word"] * words_per_line) for m in range(minutes))


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    db.init()
    db.execute("DELETE FROM recaps")
    db.execute("DELETE FROM approvals")
    calls, sent = [], []
    monkeypatch.setattr(llm, "HAS_LLM", True)
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: calls.append((a, k)) or json.loads(json.dumps(PACK)))
    monkeypatch.setattr(relay, "notify", sent.append)
    monkeypatch.setattr(relay, "ask", lambda *a, **k: None)
    return {"calls": calls, "sent": sent}


def run(**params):
    return Recap().run({"params": json.dumps(params)})


def test_registered_and_uses_the_cheap_model():
    assert agents.get("recap") and agents.get("recap").free is False
    from hq.config import model_for
    assert model_for("recap") == "claude-haiku-5-5"


def test_needs_owner_and_client_before_anything(_setup):
    assert "handed over" in run(transcript=transcript(), client="Sam")
    assert "handed over" in run(transcript=transcript(), owner=OWNER)
    assert not _setup["calls"]


def test_too_short_costs_nothing(_setup):
    assert "only" in run(transcript=transcript(minutes=5), client="Sam", owner=OWNER)
    assert "only" in run(transcript="[0:00:00] hi\n[0:30:00] bye", client="Sam", owner=OWNER)
    assert not _setup["calls"]


def test_no_timestamps_is_explained(_setup):
    assert "timestamps" in run(transcript="just words " * 500, client="Sam", owner=OWNER)
    assert not _setup["calls"]


def test_pack_waits_for_approval_and_approving_only_shows_text(_setup):
    assert "waiting for your OK" in run(transcript=transcript(), client="Sam", owner=OWNER)
    r = db.rows("SELECT * FROM recaps")[0]
    assert r["status"] == "pending" and r["owner_note"] == OWNER
    pending = approvals.pending()
    assert len(pending) == 1 and pending[0]["kind"] == "recap"
    pack = json.loads(r["pack"])
    assert pack["chapters"][0] == {"start_seconds": 0, "title": "Intro"}   # YouTube needs a 0:00 chapter
    assert "0:00 Intro" in pending[0]["preview"] and "5:00 Boss fight" in pending[0]["preview"]
    assert not _setup["sent"]                                               # nothing leaves before Steven says so
    out = approvals.decide(pending[0]["id"], "approve")
    assert "Sam" in out and db.rows("SELECT status FROM recaps")[0]["status"] == "approved"
    assert len(_setup["sent"]) == 1 and "never sends" in _setup["sent"][0]
    assert approvals.decide(pending[0]["id"], "approve") == "Already approved."


def test_reject(_setup):
    run(transcript=transcript(), client="Sam", owner=OWNER)
    approvals.decide(approvals.pending()[0]["id"], "reject")
    assert db.rows("SELECT status FROM recaps")[0]["status"] == "rejected" and not _setup["sent"]


def test_same_transcript_is_not_paid_for_twice(_setup):
    run(transcript=transcript(), client="Sam", owner=OWNER)
    assert "already covers" in run(transcript=transcript(), client="Sam", owner=OWNER)
    assert len(_setup["calls"]) == 1


def test_long_transcript_is_trimmed_before_sending():
    segs = [{"start": i * 31, "text": "x" * 500} for i in range(1000)]
    assert len(recap.compact(segs)) < recap.MAX_CHARS + 1000 * 12


def test_clean_fixes_order_and_drops_bad_chapters():
    pack = {**PACK, "chapters": [{"start_seconds": 900, "title": "B"}, {"start_seconds": 0, "title": "A"},
                                 {"start_seconds": 905, "title": "too close"}, {"start_seconds": 99999, "title": "past end"},
                                 {"start_seconds": 1800, "title": "C"}]}
    out = recap.clean(pack, 3600)
    assert [c["title"] for c in out["chapters"]] == ["A", "B", "C"]


def test_clean_rejects_incomplete_packs():
    with pytest.raises(recap.RecapError):
        recap.clean({**PACK, "posts": ["one"]}, 3600)
    with pytest.raises(recap.RecapError):
        recap.clean({**PACK, "chapters": [{"start_seconds": 100, "title": "only"}]}, 3600)


def test_reads_srt_and_files(tmp_path, _setup):
    srt = "".join(f"{i}\n00:{i // 60:02d}:{i % 60:02d},000 --> 00:{i // 60:02d}:{i % 60:02d},500\n{'word ' * 20}\n\n"
                  for i in range(0, 3600, 30) if i < 3600)
    segs = recap.parse_text(srt)
    assert segs[1]["start"] == 30 and segs[1]["text"].startswith("word")
    f = tmp_path / "vod.srt"
    f.write_text(srt)
    assert "waiting" in run(file=str(f), client="Sam", owner=OWNER)
    assert "can't find" in run(file=str(tmp_path / "none.srt"), client="Sam", owner=OWNER)


def test_pitch_mentions_second_offer(monkeypatch):
    from hq.agents.pitch import agent as pitch_mod
    seen = []
    monkeypatch.setattr(pitch_mod, "settings", lambda: {"sender_name": "Steven", "second_offer": "Recap packs, $49"})
    monkeypatch.setattr(pitch_mod.llm, "ask_json", lambda m, s, facts, *a, **k: seen.append(facts) or
                        {"subject": "s", "message": "m", "why_this_lead": "w"})
    monkeypatch.setattr(pitch_mod.finder, "find_email", lambda *a, **k: None)
    db.execute("DELETE FROM leads")
    pitch_mod.Pitch().draft_lead({"name": "Sam", "platform": "youtube", "handle": "recap-sam", "contact": "sam@example.com"})
    assert "Recap packs, $49" in seen[0]
