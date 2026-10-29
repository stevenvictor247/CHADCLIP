"""Gate: scores waiting clips from Steven's past decisions, holds likely rejects, sorts best first, measures accuracy."""

import pytest

from hq import db, gate
from hq.agents import AGENTS


@pytest.fixture
def clips():
    db.init()
    before = {r["id"] for r in db.rows("SELECT id FROM clips")}
    db.execute("UPDATE clips SET status = 'failed' WHERE status IN ('pending_approval', 'approved', 'posted', 'rejected')")

    def make(creator, status="pending_approval", seconds=30, title="A clip", caption="a decent caption for this clip",
             gate_held=None, decided_at=None):
        return db.execute("INSERT INTO clips (creator, start_s, end_s, path, title, caption, status, created_at, "
                          "gate_held, decided_at) VALUES (?, 0, ?, 'x.mp4', ?, ?, ?, ?, ?, ?)",
                          creator, seconds, title, caption, status, db.now(), gate_held, decided_at)

    def history(creator, approved, rejected):
        for _ in range(approved):
            make(creator, "approved")
        for _ in range(rejected):
            make(creator, "rejected")
    make.history = history
    yield make
    db.execute("DELETE FROM clips WHERE id NOT IN (%s)" % ", ".join(map(str, before or {0})))


def test_gate_is_a_free_scheduled_agent():
    g = AGENTS["gate"]
    assert g.free and g.schedule


def test_little_history_holds_nothing(clips):
    clips.history("HasanAbi", 0, 5)
    cid = clips("HasanAbi")
    r = gate.score_clip(db.rows("SELECT * FROM clips WHERE id = ?", cid)[0], gate.history(cid))
    assert r["learning"] and r["held"] is None


def test_rejected_creator_is_held_and_liked_creator_sorts_first(clips):
    clips.history("HasanAbi", 2, 7)
    clips.history("Kai", 8, 1)
    bad, good = clips("HasanAbi"), clips("Kai")
    out = gate.score_pending()
    assert [c["id"] for c in out] == [good, bad]
    assert out[0]["gate_held"] == 0 and out[1]["gate_held"] == 1
    assert out[0]["gate_score"] > 70 and out[1]["gate_score"] < gate.HOLD_BELOW
    saved = db.rows("SELECT gate_score, gate_held FROM clips WHERE id = ?", bad)[0]   # the call is saved on the clip
    assert saved["gate_held"] == 1


def test_new_creator_is_not_held(clips):
    clips.history("HasanAbi", 1, 9)
    new = clips("Nobody")
    c = next(c for c in gate.score_pending() if c["id"] == new)
    assert not c["gate_held"]


def test_short_caption_lowers_score(clips):
    clips.history("Kai", 5, 5)
    a, b = clips("Kai"), clips("Kai", caption="lol")
    by = {c["id"]: c["gate_score"] for c in gate.score_pending()}
    assert by[b] < by[a]


def test_deciding_a_clip_stamps_the_time(clips):
    cid = clips("Kai")
    db.set_clip_status(cid, "rejected")
    assert db.rows("SELECT decided_at FROM clips WHERE id = ?", cid)[0]["decided_at"]


def test_accuracy_counts_only_gated_recent_decisions(clips):
    now = db.now()
    clips("A", "rejected", gate_held=1, decided_at=now)       # held, rejected: right
    clips("A", "approved", gate_held=1, decided_at=now)       # held, approved: wrong
    clips("A", "approved", gate_held=0, decided_at=now)       # not held, approved: right
    clips("A", "rejected", gate_held=None, decided_at=now)    # gate was still learning: not counted
    clips("A", "rejected", gate_held=1, decided_at="2020-01-01T00:00:00+00:00")   # too old
    a = gate.accuracy()
    assert (a["checked"], a["right"], a["percent"]) == (3, 2, 67)
    assert a["time_saved_usd"] == round(gate.SECONDS_PER_CLIP / 3600 * gate.HOURLY_RATE, 2)


def test_run_logs_once_a_week_and_never_decides_anything(clips):
    clips.history("Kai", 6, 6)
    cid = clips("Kai")
    clips("Kai", "rejected", gate_held=1, decided_at=db.now())
    assert "Scored 1 waiting clips" in gate.run()
    gate.run()
    weekly = db.rows("SELECT * FROM activity WHERE agent = 'Gate' AND message LIKE 'Gate this week%'")
    assert len(weekly) == 1
    assert db.rows("SELECT status FROM clips WHERE id = ?", cid)[0]["status"] == "pending_approval"


def test_dashboard_state_has_gate_and_scores(clips):
    from fastapi.testclient import TestClient
    from hq.api import app
    clips.history("Kai", 6, 6)
    cid = clips("Kai")
    s = TestClient(app).get("/api/state").json()
    assert s["gate"]["history"] >= 12
    assert any(c["id"] == cid and c["gate_score"] is not None for c in s["pending"])
