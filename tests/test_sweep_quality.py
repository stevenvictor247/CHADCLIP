"""Sweep's quality control: the "How to improve HQ" checks, the health score, one-tap fixes, hiding ideas, the coach's
note and getting the report to the dashboard and Telegram."""

import importlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


def _fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("HQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HQ_PASSWORD", "")
    monkeypatch.setenv("HQ_SWEEP_REPORT_HOUR", "0")
    for k in ("HQ_PAUSED", "HQ_SWEEP_COACH", "PITCH_EMAIL_ADDRESS", "PITCH_EMAIL_APP_PASSWORD", "HQ_MAX_POSTS_PER_DAY"):
        monkeypatch.delenv(k, raising=False)
    import hq.config, hq.db, hq.ledger, hq.quality, hq.sweep, hq.api, hq.setup_check
    for m in (hq.config, hq.db, hq.ledger, hq.quality, hq.sweep, hq.api):
        importlib.reload(m)
    hq.db.init()
    # setup is its own check; keep it quiet unless a test wants it
    monkeypatch.setattr(hq.setup_check, "summary", lambda: {"items": [], "done": 0, "total": 0, "ready": True, "next": None})
    import hq.relay
    monkeypatch.setattr(hq.relay, "enabled", lambda: False)
    return hq


def _ago(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat(timespec="seconds")


def _task(db, agent, status, ago=None, result=None, created_by="boss", instructions="do it", params="{}"):
    ts = _ago(**(ago or {"minutes": 5}))
    return db.execute("INSERT INTO tasks (agent, instructions, params, status, result, created_by, created_at, updated_at) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", agent, instructions, params, status, result, created_by, ts, ts)


def _clip(db, status="pending_approval", path="", ago=None, creator="Jynxzi", **kw):
    cols = {"creator": creator, "source_url": kw.get("source_url", "https://youtu.be/x"), "start_s": 0, "end_s": 30,
            "path": path, "title": "A clip", "caption": kw.get("caption", "So funny. Credit: @jynxzi"), "hashtags": "[]", "score": 8,
            "reason": "big laugh", "captioned": 1, "status": status, "created_at": _ago(**(ago or {"hours": 1}))}
    return db.execute(f"INSERT INTO clips ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", *cols.values())


def _ids(hq):
    return {t["id"] for t in hq.quality.find_tips()[0]}


def _tip(hq, tid):
    return next(t for t in hq.quality.find_tips()[0] if t["id"] == tid)


# ---- the checks ------------------------------------------------------------------------------------------

def test_clean_hq_scores_100_with_nothing_to_do(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    tips, broken = hq.quality.find_tips()
    assert tips == [] and broken == []
    assert hq.quality.score(tips) == 100


def test_setup_step_blocking_money_comes_first(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    items = [{"id": "posting", "title": "A posting account switched on", "status": "todo", "required": True,
              "detail": "Only the practice account is on.", "fix": "Connect a real account in Settings",
              "link": "/settings#accounts"},
             {"id": "backup_copy", "title": "Backups", "status": "todo", "required": False, "detail": "", "fix": "", "link": ""}]
    monkeypatch.setattr(hq.setup_check, "summary", lambda: {"items": items})
    tip = _tip(hq, "setup_posting")
    assert tip["link"]["href"] == "/settings#accounts" and tip["do"] == "Connect a real account in Settings."
    assert "setup_backup_copy" not in _ids(hq)                     # optional steps are not nagged about


def test_stale_approvals_and_waiting_clips(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    for _ in range(2):
        hq.db.execute("INSERT INTO approvals (agent, kind, title, preview, created_at) VALUES ('Pitch', 'pitch', 't', 'p', ?)",
                      _ago(days=3))
    hq.db.execute("INSERT INTO approvals (agent, kind, title, preview, created_at) VALUES ('Pitch', 'pitch', 't', 'p', ?)",
                  _ago(hours=1))
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    _clip(hq.db, path=str(clip), ago={"hours": 30})
    tip = _tip(hq, "stale_approvals")
    assert tip["title"].startswith("2 cards") and "2 pitch" in tip["why"] and tip["link"]["href"] == "/#approvals"
    assert "1 clip is waiting" in _tip(hq, "clips_waiting")["title"]


def test_broken_and_flagged_clips(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    ok = tmp_path / "ok.mp4"
    ok.write_bytes(b"x")
    _clip(hq.db, path=str(ok))
    gone = _clip(hq.db, path=str(tmp_path / "gone.mp4"))
    _clip(hq.db, path=str(tmp_path / "gone2.mp4"), caption="")
    tip = _tip(hq, "broken_clips")
    assert tip["fix"]["id"] == "set_aside_broken" and "2 waiting clips" in tip["title"]
    assert "flagged_clips" not in _ids(hq)              # the missing files have their own tip, not counted twice
    assert gone in hq.quality._broken_clip_ids()
    assert "Set aside 2 clips" in hq.quality.apply_fix("set_aside_broken")
    # set aside as failed, not rejected: Chad learns your taste from rejections, and a lost file says nothing about taste
    statuses = [r["status"] for r in hq.db.rows("SELECT status FROM clips ORDER BY id")]
    assert statuses == ["pending_approval", "failed", "failed"]
    assert "broken_clips" not in _ids(hq)
    import hq.tally
    assert "rejected" not in hq.tally.your_taste()


def test_flagged_clips_tip(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    for i in range(3):
        f = tmp_path / f"{i}.mp4"
        f.write_bytes(b"x")
        _clip(hq.db, path=str(f), caption="" if i < 2 else "Fine one. Credit: @j")
    tip = _tip(hq, "flagged_clips")
    assert tip["title"] == "2 of the 3 waiting clips have a problem" and "caption has no credit" in tip["why"]


def test_waiting_clips_wording(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    f = tmp_path / "c.mp4"
    f.write_bytes(b"x")
    for _ in range(15):
        _clip(hq.db, path=str(f), ago={"hours": 2})
    tip = _tip(hq, "clips_waiting")
    assert tip["severity"] == "high" and "over a day" not in tip["why"]       # many, but none old yet
    hq.db.execute("UPDATE clips SET created_at = ?", _ago(hours=30))
    assert _tip(hq, "clips_waiting")["why"].startswith("All of them for over a day.")


def test_rejection_rate_and_the_streamer_behind_it(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    for _ in range(4):
        _clip(hq.db, status="rejected", creator="Loud")
    for _ in range(2):
        _clip(hq.db, status="posted", creator="Jynxzi")
    hq.db.execute("INSERT INTO llm_usage (agent, model, cost_usd, created_at) VALUES ('Chad', 'claude-sonnet-5-5', 1.2, ?)", _ago(hours=2))
    tip = _tip(hq, "reject_rate")
    assert "67%" in tip["title"] and "$0.80" in tip["why"]
    assert "Loud" in _tip(hq, "reject_creator_loud")["title"]
    assert "reject_creator_jynxzi" not in _ids(hq)
    hq.db.log("Steven", "Took loud off Chad's clip list")     # removing them clears that tip
    assert "reject_creator_loud" not in _ids(hq)


def test_posting_failures_and_backlog(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    import hq.agents.chad.publish as publish
    monkeypatch.setattr(publish, "load_accounts", lambda: [{"platform": "tiktok", "name": "main", "enabled": True}])
    for _ in range(2):
        hq.db.execute("INSERT INTO posts (clip_id, platform, account, status, error, created_at) "
                      "VALUES (1, 'tiktok', 'main', 'failed', 'token expired', ?)", _ago(hours=3))
    for _ in range(9):
        _clip(hq.db, status="approved")
    assert "token expired" in _tip(hq, "post_fail_tiktok_main")["why"]
    tip = _tip(hq, "post_backlog")
    assert "9 approved clips" in tip["title"] and "2 days at 4 a day" in tip["title"]


def test_pitch_cards_without_email_offer_a_recheck(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    ts = _ago(hours=2)
    no_mail = hq.db.execute("INSERT INTO leads (name, platform, handle, contact, status, created_at, updated_at) "
                            "VALUES ('Ann', 'twitch', 'ann', 'twitch.tv/ann', 'drafted', ?, ?)", ts, ts)
    has_mail = hq.db.execute("INSERT INTO leads (name, platform, handle, contact, status, created_at, updated_at) "
                             "VALUES ('Bo', 'twitch', 'bo', 'bo@example.com', 'drafted', ?, ?)", ts, ts)
    for lid in (no_mail, has_mail):
        hq.db.execute("INSERT INTO approvals (agent, kind, title, preview, payload, created_at) VALUES "
                      "('Pitch', 'pitch', 'Pitch', 'p', ?, ?)", json.dumps({"lead_id": lid, "email": False}), ts)
    tip = _tip(hq, "pitch_no_email")
    assert "Ann" in tip["why"] and "Bo" not in tip["why"] and tip["fix"]["id"] == "pitch_recheck"
    assert "Bo" not in _tip(hq, "pitch_no_mailer")["why"] and "1 pitch has" in _tip(hq, "pitch_no_mailer")["title"]
    # pressing it queues one Pitch recheck; pressing again doesn't queue another
    assert "task #" in hq.quality.apply_fix("pitch_recheck")
    assert "already looking" in hq.quality.apply_fix("pitch_recheck")
    assert _tip(hq, "pitch_no_email")["fix"] is None
    assert len(hq.db.rows("SELECT * FROM tasks WHERE agent = 'Pitch'")) == 1


def test_failing_agents_empty_rounds_and_repeated_jobs(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    for i in range(5):
        _task(hq.db, "Scout", "failed" if i < 2 else "done", {"hours": 2}, "feed returned 403")
    for _ in range(3):
        _task(hq.db, "Chad", "done", {"hours": 2}, "Made 0 clips. Nobody was live.", created_by="Schedule",
              instructions="Check creators for new videos and clip them.")
    for _ in range(4):
        _task(hq.db, "Pitch", "done", {"hours": 1}, "ok", instructions="Find 5 streamers to pitch.")
    ids = _ids(hq)
    assert {"fail_rate_scout", "empty_chad", "task_repeat_pitch"} <= ids
    assert "403" in _tip(hq, "fail_rate_scout")["why"]
    # a useful round since the empty ones ends the streak
    _task(hq.db, "Chad", "done", {"minutes": 1}, "Made 2 clips.", created_by="Schedule",
          instructions="Check creators for new videos and clip them.")
    assert "empty_chad" not in _ids(hq)


def test_duplicate_jobs_are_cancelled_but_the_first_stays(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    first = _task(hq.db, "Chad", "queued", {"minutes": 3}, instructions="Clip Jynxzi")
    dup = _task(hq.db, "Chad", "queued", {"minutes": 2}, instructions="clip jynxzi ")
    other = _task(hq.db, "Chad", "queued", {"minutes": 1}, instructions="Clip Jynxzi", params='{"vod": true}')
    assert _tip(hq, "queue_duplicates")["fix"]["id"] == "cancel_duplicates"
    assert "Cancelled 1 duplicate job" in hq.quality.apply_fix("cancel_duplicates")
    status = {t["id"]: t["status"] for t in hq.db.rows("SELECT id, status FROM tasks")}
    assert status == {first: "queued", dup: "failed", other: "queued"}
    assert "queue_duplicates" not in _ids(hq)


def test_late_queue_and_pause(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    _task(hq.db, "Pitch", "queued", {"hours": 3})
    assert _tip(hq, "queue_late")["severity"] == "high"
    monkeypatch.setenv("HQ_PAUSED", "true")
    ids = _ids(hq)
    assert "paused" in ids and "queue_late" not in ids


def test_repeated_boss_prompts_and_long_chat(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    import hq.boss
    importlib.reload(hq.boss)
    msg = json.dumps([{"type": "text", "text": "Daily report, please."}])
    for _ in range(3):
        hq.db.execute("INSERT INTO boss_messages (conversation, role, content, created_at) VALUES (1, 'user', ?, ?)", msg, _ago(hours=1))
    tip = _tip(hq, "boss_repeats")
    assert "3 times" in tip["title"] and tip["fix"]["id"] == "fresh_boss_chat"
    hq.db.execute("DELETE FROM boss_messages")
    big = json.dumps([{"type": "text", "text": "x" * 200_000}])
    hq.db.execute("INSERT INTO boss_messages (conversation, role, content, created_at) VALUES (1, 'assistant', ?, ?)", big, _ago(hours=1))
    assert "50k tokens" in _tip(hq, "boss_chat_long")["title"]
    assert "fresh Boss chat" in hq.quality.apply_fix("fresh_boss_chat")
    assert hq.boss.current_conversation() == 2 and "boss_chat_long" not in _ids(hq)
    assert "already fresh" in hq.quality.apply_fix("fresh_boss_chat")


def test_money_checks(monkeypatch, tmp_path):
    monkeypatch.setenv("HQ_DAILY_BUDGET", "1")
    hq = _fresh(monkeypatch, tmp_path)
    for days in (1, 2):
        hq.db.execute("INSERT INTO llm_usage (agent, model, cost_usd, created_at) VALUES ('Chad', 'claude-sonnet-5-5', 1.5, ?)",
                      _shift(hq.quality._day_start(days), hours=3))
    assert {"spend_no_output", "budget_hits"} <= _ids(hq)
    assert "2 of the last 7 days" in _tip(hq, "budget_hits")["title"]
    hq.db.execute("INSERT INTO posts (clip_id, platform, account, status, created_at) VALUES (1, 'youtube', 'main', 'posted', ?)", _ago(hours=1))
    assert "spend_no_output" not in _ids(hq)                       # something went out, so the spend wasn't for nothing


def _shift(iso, **kw):
    return (datetime.fromisoformat(iso) + timedelta(**kw)).isoformat(timespec="seconds")


def test_scout_and_football_leftovers(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    hq.db.execute("INSERT INTO campaigns (name, created_at) VALUES ('Old one', ?)", _ago(days=5))
    hq.db.execute("INSERT INTO creator_picks (login, name, created_at) VALUES ('a', 'A', ?)", _ago(days=9))
    hq.db.execute("INSERT INTO football_files (name, status, added_at) VALUES ('wk3.xlsx', 'failed', ?)", _ago(days=1))
    assert {"scout_waiting", "creator_picks_waiting", "football_failed_sheets"} <= _ids(hq)


def test_a_broken_check_never_stops_the_others(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    _task(hq.db, "Pitch", "queued", {"hours": 3})

    def boom():
        raise RuntimeError("bad table")
    monkeypatch.setattr(hq.quality, "CHECKS", [boom] + hq.quality.CHECKS)
    tips, broken = hq.quality.find_tips()
    assert "queue_late" in {t["id"] for t in tips} and broken == ["boom: bad table"]


def test_tips_are_sorted_and_scored(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    tips = [{"severity": "low"}, {"severity": "high"}, {"severity": "medium"}]
    assert hq.quality.score(tips) == 100 - 12 - 6 - 2
    assert hq.quality.score([{"severity": "high"}] * 20) == 0


def test_unknown_fix_is_refused(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        hq.quality.apply_fix("post_everything")


def test_no_fix_posts_emails_or_changes_settings(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    import hq.settings, hq.relay
    touched = []
    monkeypatch.setattr(hq.settings, "save", lambda *a, **k: touched.append("settings"))
    monkeypatch.setattr(hq.relay, "notify", lambda *a, **k: touched.append("relay"))
    from hq.agents.pitch import mailer
    monkeypatch.setattr(mailer, "send", lambda *a, **k: touched.append("email"), raising=False)
    for fid in hq.quality.FIXES:
        hq.quality.apply_fix(fid)
    assert touched == []
    assert hq.db.rows("SELECT COUNT(*) n FROM posts")[0]["n"] == 0
    assert hq.db.rows("SELECT COUNT(*) n FROM approvals")[0]["n"] == 0
    assert len({n for n, _ in hq.quality.FIXES.values()}) == len(hq.quality.FIXES)   # Telegram numbers are unique


# ---- the daily report ------------------------------------------------------------------------------------

def test_report_has_score_top_three_hiding_and_fixed_since_yesterday(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    _task(hq.db, "Pitch", "queued", {"hours": 3})                                   # queue_late (high)
    hq.db.execute("INSERT INTO campaigns (name, created_at) VALUES ('Old', ?)", _ago(days=5))   # scout_waiting (low)
    hq.sweep.run(force_report=True)
    imp = hq.sweep.latest()["report"]["improve"]
    assert imp["score"] == 100 - 12 - 2 and imp["top"][0] == "queue_late" and imp["change"] is None
    assert imp["tips"][0]["open_days"] == 0
    text = hq.sweep.latest()["report"]["text"]
    assert "HQ health: 86/100" in text and "How to improve HQ today:" in text and "1. " in text

    # hiding takes it off the report and out of the score, straight away
    assert "Hidden for 7 days" in hq.sweep.snooze("scout_waiting")
    imp = hq.sweep.latest()["report"]["improve"]
    assert imp["score"] == 88 and imp["hidden"] == 1 and "scout_waiting" in hq.sweep.latest()["snoozed"]
    hq.sweep.unsnooze("scout_waiting")
    assert hq.sweep.latest()["report"]["improve"]["hidden"] == 0

    # the next day: the late job is gone, so it's listed as fixed and the score went up
    hq.db.execute("UPDATE tasks SET status = 'done'")
    state = json.loads(hq.sweep.STATE_PATH.read_text())
    state["last_report"] = state["last_report_day"] = "2000-01-01"
    state["first_seen"]["scout_waiting"] = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    hq.sweep.STATE_PATH.write_text(json.dumps(state))
    (hq.sweep.REPORTS_DIR / f"{datetime.now():%Y-%m-%d}.json").unlink(missing_ok=True)   # "it is a new day"
    hq.sweep.SENT_PATH.unlink(missing_ok=True)
    hq.sweep.run()
    imp = hq.sweep.latest()["report"]["improve"]
    assert imp["change"] == 12 and any("waiting over 2 hours" in f for f in imp["fixed"])
    assert imp["tips"][0]["open_days"] == 2
    assert [h["score"] for h in hq.sweep.latest()["history"]] == [98]              # one daily file per day
    hq.sweep.run(force_report=True)                    # a second report the same day still compares with yesterday
    assert hq.sweep.latest()["report"]["improve"]["change"] == 12


def test_snoozes_expire(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    hq.sweep.snooze("x", days=7)
    state = json.loads(hq.sweep.STATE_PATH.read_text())
    state["snoozed"]["x"] = _ago(minutes=1)
    hq.sweep.STATE_PATH.write_text(json.dumps(state))
    assert hq.sweep.snoozed() == {}


def test_coach_note_once_a_day_and_never_over_budget(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    import hq.llm
    calls = []

    def fake(model, system, prompt, schema, effort="medium", agent="Boss"):
        calls.append({"model": model, "agent": agent, "facts": json.loads(prompt)})
        return {"note": "Approve your waiting clips first; it unblocks posting."}
    monkeypatch.setattr(hq.llm, "ask_json", fake)
    monkeypatch.setattr(hq.config, "HAS_LLM", True)
    _task(hq.db, "Pitch", "queued", {"hours": 3})
    hq.sweep.run(force_report=True)
    assert len(calls) == 1 and calls[0]["agent"] == "Sweep" and calls[0]["model"] == "claude-sonnet-5-5"
    assert calls[0]["facts"]["findings"][0]["title"].startswith("1 job has")
    rep = hq.sweep.latest()["report"]
    assert rep["improve"]["coach"].startswith("Approve") and "Coach's note: Approve" in rep["text"]
    hq.sweep.run()                                     # a normal round: no new call, the day's note stays on the tab
    assert len(calls) == 1 and hq.sweep.latest()["report"]["improve"]["coach"].startswith("Approve")
    hq.sweep.run(force_report=True)                    # pressing "send the report" again the same day: no second call
    assert len(calls) == 1 and hq.sweep.latest()["report"]["improve"]["coach"].startswith("Approve")
    # a new day with the budget spent, or the note switched off: no call, and the report still goes out
    state = json.loads(hq.sweep.STATE_PATH.read_text())
    state["coach_day"] = "2000-01-01"
    hq.sweep.STATE_PATH.write_text(json.dumps(state))
    monkeypatch.setattr(hq.ledger, "over_budget", lambda village="business": True)
    assert "Sent the daily report" in hq.sweep.run(force_report=True)
    assert len(calls) == 1 and hq.sweep.latest()["report"]["improve"]["coach"] is None
    monkeypatch.setattr(hq.ledger, "over_budget", lambda village="business": False)
    monkeypatch.setenv("HQ_SWEEP_COACH", "false")
    hq.sweep.run(force_report=True)
    assert len(calls) == 1 and hq.sweep.latest()["report"]["improve"]["coach"] is None


def test_coach_failure_is_logged_and_report_still_sent(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    import hq.llm, hq.relay
    monkeypatch.setattr(hq.config, "HAS_LLM", True)
    monkeypatch.setattr(hq.llm, "ask_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("overloaded")))
    sent = []
    monkeypatch.setattr(hq.relay, "notify", lambda text: sent.append(text))
    assert "Sent the daily report" in hq.sweep.run(force_report=True)
    assert sent and hq.db.rows("SELECT 1 FROM activity WHERE message LIKE '%coach%overloaded%'")


def test_telegram_gets_the_report_and_fix_buttons_that_work(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    import hq.relay
    calls = []
    monkeypatch.setattr(hq.relay, "enabled", lambda: True)
    monkeypatch.setattr(hq.relay, "owner_id", lambda: 7)
    monkeypatch.setattr(hq.relay, "api", lambda method, files=None, **p: calls.append((method, p)) or {})
    _task(hq.db, "Chad", "queued", {"minutes": 3}, instructions="Clip Jynxzi")
    _task(hq.db, "Chad", "queued", {"minutes": 2}, instructions="Clip Jynxzi")
    hq.sweep.run(force_report=True)
    texts = [p["text"] for m, p in calls if m == "sendMessage"]
    assert "Sweep's daily report" in texts[0] and "1 job is in the queue twice" in texts[0]
    buttons = [p for m, p in calls if m == "sendMessage" and "reply_markup" in p]
    assert len(buttons) == 1
    rows = json.loads(buttons[0]["reply_markup"])["inline_keyboard"]
    data = rows[0][0]["callback_data"]
    assert data == "sweepfix:approve:2" and "Cancel 1 copy" in rows[0][0]["text"]
    # a stranger's tap does nothing; Steven's tap cancels the copy
    hq.relay.handle_callback({"id": "x", "from": {"id": 99}, "data": data, "message": {}})
    assert hq.db.rows("SELECT COUNT(*) n FROM tasks WHERE status = 'queued'")[0]["n"] == 2
    hq.relay.handle_callback({"id": "y", "from": {"id": 7}, "data": data, "message": {}})
    assert hq.db.rows("SELECT COUNT(*) n FROM tasks WHERE status = 'queued'")[0]["n"] == 1
    answer = [p for m, p in calls if m == "answerCallbackQuery"][-1]
    assert "Cancelled 1 duplicate job" in answer["text"]
    assert "queue_duplicates" not in {t["id"] for t in hq.sweep.latest()["report"]["improve"]["tips"]}


def test_no_buttons_when_nothing_is_fixable(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    import hq.relay
    calls = []
    monkeypatch.setattr(hq.relay, "enabled", lambda: True)
    monkeypatch.setattr(hq.relay, "owner_id", lambda: 7)
    monkeypatch.setattr(hq.relay, "api", lambda method, files=None, **p: calls.append((method, p)) or {})
    hq.sweep.run(force_report=True)
    assert len(calls) == 1 and "Nothing to improve today" in calls[0][1]["text"]


def test_dashboard_routes_for_fixes_and_hiding(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    c = TestClient(hq.api.app)
    _task(hq.db, "Chad", "queued", {"minutes": 3}, instructions="Clip Jynxzi")
    _task(hq.db, "Chad", "queued", {"minutes": 2}, instructions="Clip Jynxzi")
    hq.sweep.run(force_report=True)
    d = c.get("/api/sweep").json()
    assert d["report"]["improve"]["tips"][0]["fix"]["id"] == "cancel_duplicates" and d["coach_on"] is True
    assert c.post("/api/sweep/fix/cancel_duplicates").status_code == 403           # only from the dashboard
    assert c.post("/api/sweep/fix/nope", headers={"X-HQ": "1"}).status_code == 404
    r = c.post("/api/sweep/fix/cancel_duplicates", headers={"X-HQ": "1"})
    assert "Cancelled 1" in r.json()["message"]
    assert c.get("/api/sweep").json()["report"]["improve"]["tips"] == []           # the tab updates straight away
    assert c.post("/api/sweep/hide/scout_waiting").status_code == 403
    assert c.post("/api/sweep/hide/scout_waiting", headers={"X-HQ": "1"}).status_code == 200
    assert "scout_waiting" in c.get("/api/sweep").json()["snoozed"]
    assert c.post("/api/sweep/unhide/scout_waiting", headers={"X-HQ": "1"}).status_code == 200
    assert c.get("/api/sweep").json()["snoozed"] == {}
    assert hq.db.rows("SELECT 1 FROM activity WHERE message LIKE 'One-tap fix (Steven)%'")


# ---- second-pass checks ----------------------------------------------------------------------------------

def test_chad_jobs_behind_a_long_clipping_job_are_normal(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    import hq.worker
    monkeypatch.setattr(hq.worker, "seconds_since_last_round", lambda: 30)
    _task(hq.db, "Chad", "running", {"minutes": 1})
    _task(hq.db, "Chad", "queued", {"hours": 3})
    assert "queue_late" not in _ids(hq)                          # the video lane is busy: waiting is expected
    _task(hq.db, "Pitch", "queued", {"hours": 3})
    tip = _tip(hq, "queue_late")
    assert tip["title"].startswith("1 job has") and "probably stuck" in tip["why"]
    monkeypatch.setattr(hq.worker, "seconds_since_last_round", lambda: 3600)
    tip = _tip(hq, "queue_late")
    assert "60 minutes" in tip["why"] and tip["do"].startswith("Close HQ and open it again")


def test_pitch_with_an_address_and_gmail_set_up_is_not_flagged(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    monkeypatch.setenv("PITCH_EMAIL_ADDRESS", "me@gmail.com")
    monkeypatch.setenv("PITCH_EMAIL_APP_PASSWORD", "abcd efgh")
    ts = _ago(hours=2)
    lid = hq.db.execute("INSERT INTO leads (name, platform, handle, contact, status, created_at, updated_at) "
                        "VALUES ('Bo', 'twitch', 'bo', 'bo@example.com', 'drafted', ?, ?)", ts, ts)
    hq.db.execute("INSERT INTO approvals (agent, kind, title, preview, payload, created_at) VALUES "
                  "('Pitch', 'pitch', 'Pitch', 'p', ?, ?)", json.dumps({"lead_id": lid, "email": False}), ts)
    assert not {"pitch_no_email", "pitch_no_mailer"} & _ids(hq)


def test_cancelled_copies_dont_count_as_failures(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    for _ in range(5):
        _task(hq.db, "Chad", "queued", {"minutes": 3}, instructions="Clip Jynxzi")
    hq.quality.apply_fix("cancel_duplicates")
    _task(hq.db, "Chad", "done", {"minutes": 1}, "Made 2 clips.")
    assert "fail_rate_chad" not in _ids(hq)


def test_boss_cost_per_message_counts_only_typed_messages(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    text = json.dumps([{"type": "text", "text": "hi"}])
    tool = json.dumps([{"type": "tool_result", "tool_use_id": "x", "content": "{}"}])
    for content in (text, tool, tool):
        hq.db.execute("INSERT INTO boss_messages (conversation, role, content, created_at) VALUES (1, 'user', ?, ?)", content, _ago(hours=1))
    hq.db.execute("INSERT INTO llm_usage (agent, model, cost_usd, created_at) VALUES ('Boss', 'claude-opus-5-5', 0.3, ?)", _ago(hours=1))
    boss = next(u for u in hq.quality.unit_costs() if u["agent"] == "Boss")
    assert boss["count"] == 1 and boss["each"] == 0.3


def test_worker_queues_the_daily_report_on_time_once(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    assert hq.sweep.queue_report_if_due() is True
    assert hq.sweep.queue_report_if_due() is False               # never twice, even if that round fails
    assert [t["agent"] for t in hq.db.rows("SELECT agent FROM tasks")] == ["Sweep"]
    hq.sweep.run()
    assert hq.sweep.report_due() is False


def test_tapping_one_telegram_fix_keeps_the_other_buttons(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    import hq.relay
    calls = []
    monkeypatch.setattr(hq.relay, "owner_id", lambda: 7)
    monkeypatch.setattr(hq.relay, "api", lambda method, files=None, **p: calls.append((method, p)) or {})
    keyboard = {"inline_keyboard": [[{"text": "a", "callback_data": "sweepfix:approve:2"}],
                                    [{"text": "b", "callback_data": "sweepfix:approve:4"}]]}
    hq.relay.handle_callback({"id": "y", "from": {"id": 7}, "data": "sweepfix:approve:2",
                              "message": {"message_id": 5, "chat": {"id": 7}, "reply_markup": keyboard}})
    edit = next(p for m, p in calls if m == "editMessageReplyMarkup")
    assert json.loads(edit["reply_markup"])["inline_keyboard"] == [keyboard["inline_keyboard"][1]]
    # an approve/reject pair still loses both buttons once answered
    calls.clear()
    pair = json.loads(hq.relay._buttons("clip", 1))
    _clip(hq.db)
    hq.relay.handle_callback({"id": "z", "from": {"id": 7}, "data": "clip:approve:1",
                              "message": {"message_id": 6, "chat": {"id": 7}, "reply_markup": pair}})
    edit = next(p for m, p in calls if m == "editMessageReplyMarkup")
    assert json.loads(edit["reply_markup"])["inline_keyboard"] == []


def test_score_change_between_reports_compares_with_the_last_daily_report(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    _task(hq.db, "Pitch", "queued", {"hours": 3})
    hq.sweep.run(force_report=True)                              # today's report: 88
    state = json.loads(hq.sweep.STATE_PATH.read_text())
    state["last_report_day"] = state["last_report"] = "2000-01-01"   # pretend that was yesterday
    hq.sweep.STATE_PATH.write_text(json.dumps(state))
    hq.db.execute("UPDATE tasks SET status = 'done'")
    monkeypatch.setenv("HQ_SWEEP_REPORT_HOUR", "24")             # a round before today's report is due
    assert "Sent the daily report" not in hq.sweep.run()
    imp = hq.sweep.latest()["report"]["improve"]
    assert imp["change"] == 12 and imp["fixed"]


def test_routine_nothing_due_checks_are_not_flagged_as_waste(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    for _ in range(4):
        _task(hq.db, "Pitch", "done", {"hours": 2}, "No follow-ups due.", created_by="Schedule",
              instructions="Check which pitched leads need a follow-up.")
    assert "empty_pitch" not in _ids(hq)
    for _ in range(3):   # a different empty result still counts
        _task(hq.db, "Pitch", "done", {"hours": 1}, "No new streamers matched.", created_by="Schedule",
              instructions="Find new leads and draft pitches.")
    assert "empty_pitch" in _ids(hq)
