"""Packs: free checks first, one Recap call, five clips, a pack waiting for approval, and nothing ever sent."""

import json

import pytest

from hq import agents, approvals, db, ledger, packs, recap, relay
from hq.agents.chad import editor, moments
from hq.agents.packs import Packs
from tests.test_recap import PACK as TEXT

OWNER = "emailed me episode 12 and said yes to clips, 26 Oct"
WORDS = [{"start": float(i), "end": i + 0.5, "text": "word"} for i in range(0, 3000, 2)]
SEGS = [{"start": float(m * 60), "end": m * 60 + 50.0, "text": " ".join(["word"] * 60)} for m in range(60)]
MOMENTS = [{"start": 100.0 * i, "end": 100.0 * i + 40, "title": f"Moment {i}", "caption": f"Cap {i}"} for i in range(5)]


@pytest.fixture(autouse=True)
def _setup(monkeypatch, tmp_path):
    db.init()
    db.execute("DELETE FROM clip_packs")
    db.execute("DELETE FROM approvals")
    ep = tmp_path / "ep12.mp4"
    ep.write_bytes(b"episode")
    sent, rendered, writes = [], [], []
    monkeypatch.setattr(packs, "PACKS_DIR", tmp_path / "packs")
    monkeypatch.setattr(packs, "transcribe", lambda p: {"segments": SEGS, "words": WORDS})
    monkeypatch.setattr(editor, "duration", lambda p: 3600.0)
    monkeypatch.setattr(editor, "render", lambda src, s, e, out, words=None, **k: (
        rendered.append((s, e)), out.parent.mkdir(parents=True, exist_ok=True), out.write_bytes(b"v"), out)[-1])
    monkeypatch.setattr(moments, "pick", lambda *a, **k: [dict(m) for m in MOMENTS])
    monkeypatch.setattr(recap, "write_pack", lambda segs, length: writes.append(length) or json.loads(json.dumps(
        recap.clean(TEXT, length))))
    monkeypatch.setattr(ledger, "over_budget", lambda *a, **k: False)
    monkeypatch.setattr(relay, "notify", sent.append)
    monkeypatch.setattr(relay, "ask", lambda *a, **k: None)
    return {"file": str(ep), "sent": sent, "rendered": rendered, "writes": writes, "tmp": tmp_path}


def run(**params):
    return Packs().run({"params": json.dumps(params)})


def test_registered_and_runs_in_the_slow_lane():
    from hq import worker
    assert agents.get("packs") and "packs" in worker.SLOW_AGENTS


def test_needs_permission_note_and_a_real_video_before_anything(_setup):
    assert "handed over" in run(file=_setup["file"], client="Sam's Pod")
    assert "handed over" in run(file=_setup["file"], owner=OWNER)
    assert "can't find" in run(file="/nope.mp4", client="Sam", owner=OWNER)
    txt = _setup["tmp"] / "a.txt"
    txt.write_text("x")
    assert "video file" in run(file=str(txt), client="Sam", owner=OWNER)
    assert not _setup["rendered"] and not _setup["writes"]


def test_short_episode_costs_nothing(_setup, monkeypatch):
    monkeypatch.setattr(editor, "duration", lambda p: 300.0)
    assert "only" in run(file=_setup["file"], client="Sam", owner=OWNER)
    assert not _setup["writes"] and not _setup["rendered"]


def test_no_whisper_is_explained(_setup, monkeypatch):
    monkeypatch.setattr(packs, "transcribe", lambda p: None)
    assert "Whisper" in run(file=_setup["file"], client="Sam", owner=OWNER)
    assert not _setup["writes"]


def test_budget_stops_before_any_work(_setup, monkeypatch):
    monkeypatch.setattr(ledger, "over_budget", lambda *a, **k: True)
    assert "budget" in run(file=_setup["file"], client="Sam", owner=OWNER)
    assert not _setup["writes"] and not _setup["rendered"]


def test_too_few_moments_makes_no_clips(_setup, monkeypatch):
    monkeypatch.setattr(moments, "pick", lambda *a, **k: [dict(m) for m in MOMENTS[:3]])
    assert "only 3" in run(file=_setup["file"], client="Sam", owner=OWNER)
    assert not _setup["rendered"] and not db.rows("SELECT * FROM clip_packs")


def test_makes_five_clips_and_waits_for_approval(_setup):
    assert "waiting for your OK" in run(file=_setup["file"], client="Sam's Pod", owner=OWNER)
    assert len(_setup["rendered"]) == 5 and _setup["writes"] == [3600]
    row = db.rows("SELECT * FROM clip_packs")[0]
    assert row["status"] == "pending" and row["price_cents"] == 4900
    folder = _setup["tmp"] / "packs"
    assert sorted(p.name for p in next(folder.iterdir()).iterdir()) == [f"clip-{i}.mp4" for i in range(1, 6)] + ["pack.txt"]
    ask = approvals.pending()[0]
    assert ask["kind"] == "clip_pack" and "$49" in ask["title"] and "TITLE OPTIONS" in ask["preview"]
    assert not _setup["sent"]  # nothing sent until Steven approves, and then only shown to him


def test_same_episode_is_not_made_twice(_setup):
    run(file=_setup["file"], client="Sam", owner=OWNER)
    assert "already covers" in run(file=_setup["file"], client="Sam", owner=OWNER)
    assert len(_setup["rendered"]) == 5 and len(_setup["writes"]) == 1


def test_approve_shows_message_with_testimonial_ask_and_sends_nothing(_setup):
    run(file=_setup["file"], client="Sam", owner=OWNER)
    out = approvals.decide(approvals.pending()[0]["id"], "approve")
    assert "testimonial" in out and "Packs never sends" in out
    assert db.rows("SELECT status FROM clip_packs")[0]["status"] == "approved"
    assert len(_setup["sent"]) == 1 and "testimonial" in _setup["sent"][0]
    assert "already approved" in packs._decided({"pack_id": db.rows("SELECT id FROM clip_packs")[0]["id"]}, "approve")


def test_reject(_setup):
    run(file=_setup["file"], client="Sam", owner=OWNER)
    assert "Rejected" in approvals.decide(approvals.pending()[0]["id"], "reject")
    assert db.rows("SELECT status FROM clip_packs")[0]["status"] == "rejected" and not _setup["sent"]
