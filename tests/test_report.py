"""The daily report: one call on a mid-priced model from facts HQ gathers itself, shown in the Boss chat."""

from types import SimpleNamespace

from hq import boss, db, llm


def test_daily_report_is_one_cheap_call_and_flags_clips(monkeypatch, tmp_path):
    db.init()
    calls = []

    def fake_create(model, system, messages, tools=None, **kw):
        calls.append({"model": model, "tools": tools, "facts": messages[0]["content"]})
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="All quiet. One clip needs a look.")])

    monkeypatch.setattr(llm, "HAS_LLM", True)
    monkeypatch.setattr(llm, "create", fake_create)
    monkeypatch.delenv("HQ_MODEL_REPORT", raising=False)
    bad = db.execute("INSERT INTO clips (creator, source_url, start_s, end_s, path, title, caption, score, reason, "
                     "captioned, created_at) VALUES ('A', 'https://y/9', 0, 30, ?, 'Meh', 'meh', 2, 'filler', 0, ?)",
                     str(tmp_path / "gone.mp4"), db.now())

    text = boss.report()
    assert text == "All quiet. One clip needs a look."
    assert len(calls) == 1 and calls[0]["tools"] is None          # no tool-by-tool chat
    assert calls[0]["model"] == "claude-sonnet-5-5"                # not the Boss's Opus
    assert '"chad_review"' in calls[0]["facts"]
    note = db.rows("SELECT boss_note FROM clips WHERE id = ?", bad)[0]["boss_note"]
    assert "missing from disk" in note                             # the approval card still gets the note
    last = boss.history(boss.current_conversation())[-1]
    assert last["role"] == "assistant" and last["content"][0]["text"] == text
    db.set_clip_status(bad, "rejected")


def test_report_survives_a_claude_error(monkeypatch):
    db.init()
    monkeypatch.setattr(llm, "HAS_LLM", True)

    def broken(*a, **kw):
        raise RuntimeError("overloaded")
    monkeypatch.setattr(llm, "create", broken)
    text = boss.report()
    assert "Chad in the last 24 hours" in text and "overloaded" in text
