import subprocess

from hq.agents.chad import editor, moments


def test_moments_are_clamped_non_overlapping_and_sorted():
    raw = [
        {"start": 0, "end": 100, "title": "a", "caption": "a", "hashtags": ["#x"], "score": 9, "reason": ""},
        {"start": 50, "end": 80, "title": "b", "caption": "b", "hashtags": [], "score": 8, "reason": ""},
        {"start": 200, "end": 230, "title": "c", "caption": "c", "hashtags": [], "score": 7, "reason": ""},
    ]
    out = moments._clean(raw, duration=210, count=3, min_len=15, max_len=59)
    # b overlaps a, and c would be only 10 s (under the 15 s minimum), so only a survives, trimmed to 59 s
    assert [(m["start"], m["end"]) for m in out] == [(0, 59)]
    assert all(m["end"] - m["start"] <= 59 for m in out)
    assert out[0]["hashtags"] == ["x"]


def test_render_makes_vertical_clip(tmp_path):
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=6",
                    "-f", "lavfi", "-i", "sine=duration=6", "-shortest", str(src)], check=True)
    words = [{"start": 1.0, "end": 1.4, "text": "hello"}, {"start": 1.5, "end": 2.0, "text": "world"}]
    out = editor.render(str(src), 0.5, 4.5, tmp_path / "out.mp4", words)
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    assert probe == "1080,1920"
    assert 3.5 < editor.duration(str(out)) < 4.5


def test_offline_boss_chat_is_saved(monkeypatch):
    from hq import boss, db, llm
    db.init()
    monkeypatch.setattr(llm, "HAS_LLM", False)
    before = len(boss.history(boss.current_conversation()))
    boss.chat("hello")
    assert len(boss.history(boss.current_conversation())) == before + 2


def test_library_lists_decided_clips_with_posts():
    from fastapi.testclient import TestClient
    from hq import db
    from hq.api import app
    db.init()
    cid = db.execute("INSERT INTO clips (creator, start_s, end_s, path, title, status, created_at) "
                     "VALUES ('c', 0, 5, 'x.mp4', 't', 'approved', ?)", db.now())
    db.execute("INSERT INTO posts (clip_id, platform, account, status, created_at) VALUES (?, 'tiktok', 'a', 'posted', ?)",
               cid, db.now())
    pend = db.execute("INSERT INTO clips (creator, start_s, end_s, path, title, created_at) VALUES ('c', 0, 5, 'y.mp4', 'p', ?)", db.now())
    s = TestClient(app).get("/api/state").json()
    mine = [c for c in s["clips"] if c["id"] == cid]
    assert mine and mine[0]["posts"][0]["platform"] == "tiktok"
    assert all(c["id"] != pend for c in s["clips"])
    assert any(c["id"] == pend for c in s["pending"])


def test_boss_review_flags_problem_clips_and_never_approves(tmp_path):
    from hq import boss, db
    db.init()
    good = tmp_path / "good.mp4"
    good.write_bytes(b"x")
    ok = db.execute("INSERT INTO clips (creator, source_url, start_s, end_s, path, title, caption, score, reason, "
                    "captioned, created_at) VALUES ('A', 'https://y/1', 0, 30, ?, 'Big win', "
                    "'What a moment\n\nCredit: A', 8, 'funny', 1, ?)", str(good), db.now())
    bad = db.execute("INSERT INTO clips (creator, source_url, start_s, end_s, path, title, caption, score, reason, "
                     "captioned, created_at) VALUES ('A', 'https://y/1', 10, 40, ?, 'Meh', 'meh', 2, 'filler', 0, ?)",
                     str(tmp_path / "gone.mp4"), db.now())
    tid = db.create_task("Chad", "clip", {})
    db.update_task(tid, "failed", "yt-dlp could not download")

    r = boss.review_chad(24)
    flagged = {f["clip"]: " | ".join(f["issues"]) for f in r["waiting_for_steven"]["flagged"]}
    for words in ("missing from disk", "no captions", "no credit", "weak moment", f"overlaps clip #{ok}"):
        assert words in flagged[bad]
    assert any(f["task"] == tid for f in r["tasks"]["failed"])

    assert boss.flag_clip(bad, "No captions and a dull moment")["note"]
    clip = db.rows("SELECT status, boss_note FROM clips WHERE id = ?", bad)[0]
    assert clip == {"status": "pending_approval", "boss_note": "No captions and a dull moment"}
    db.set_clip_status(ok, "posted")
    assert "error" in boss.flag_clip(ok, "too late")


def test_scheduled_round_is_skipped_when_nobody_can_be_clipped(monkeypatch, tmp_path):
    from hq import agents
    from hq.agents.chad import sources, twitch
    chad = agents.get("Chad")
    sched = "Check creators for new videos and clip them."
    monkeypatch.setattr(sources, "load_creators", lambda: [
        {"name": "Example Creator", "sources": ["https://example.com"], "permission": ""},
        {"name": "No Source", "permission": "written OK"}])
    monkeypatch.setattr(twitch, "permissions", lambda: {"jynxzi": ""})
    monkeypatch.setenv("TWITCH_CLIENT_ID", "id")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "secret")
    assert chad.nothing_to_do(sched, {}) is True
    monkeypatch.setattr(twitch, "permissions", lambda: {"jynxzi": "open clipping policy"})
    assert chad.nothing_to_do(sched, {}) is None                       # someone to check: back off if empty
    monkeypatch.delenv("TWITCH_CLIENT_SECRET")
    assert chad.nothing_to_do(sched, {}) is True                       # can't look streamers up without keys
    monkeypatch.setattr(sources, "load_creators", lambda: [{"name": "Real", "sources": ["u"], "permission": "OK"}])
    assert chad.nothing_to_do(sched, {}) is None
    assert chad.nothing_to_do("Clip jynxzi", {"url": "x"}) is None     # asked-for jobs always run


def test_example_creator_placeholder_is_ignored(monkeypatch, tmp_path):
    from hq.agents.chad import sources
    monkeypatch.setattr(sources, "CONFIG_DIR", tmp_path)
    (tmp_path / "creators.yaml").write_text(
        "creators:\n  - name: Example Creator\n    sources: [u]\n    permission: ''\n"
        "  - name: Real\n    sources: [u]\n    permission: ok\n")
    assert [c["name"] for c in sources.load_creators()] == ["Real"]


def test_boss_chat_rolls_over_with_a_recap(monkeypatch):
    from hq import boss, db
    db.init()
    db.execute("DELETE FROM boss_messages")
    boss._save(1, "user", [{"type": "text", "text": '<vision id="a">\nbig vision\n</vision>'},
                           {"type": "text", "text": "Have Pitch find 5 streamers"}])
    boss._save(1, "assistant", [{"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": "Queued task #7."}])
    boss._save(1, "user", [{"type": "tool_result", "tool_use_id": "t", "content": "x" * 5000}])
    r = boss.recap(1)
    assert "Steven: Have Pitch find 5 streamers" in r and "Boss: Queued task #7." in r
    assert "vision" not in r and "xxxx" not in r
    conv = boss.new_conversation()
    msgs = boss.history(conv)
    assert conv == 2 and len(msgs) == 2 and msgs[0]["content"][0]["text"].startswith(boss.RECAP_TAG)
    assert all(boss.is_recap(m) for m in msgs) and boss.chat_tokens(conv) < 2000
    assert boss.new_conversation(carry=False) == 3 and boss.history(3) == []
    # an empty chat has nothing to carry over
    assert boss.history(boss.new_conversation()) == []


def test_long_chat_rolls_over_before_the_next_message(monkeypatch):
    from hq import boss, db, llm
    db.init()
    db.execute("DELETE FROM boss_messages")
    boss._save(1, "user", [{"type": "text", "text": "Plan the week"}])
    boss._save(1, "assistant", [{"type": "text", "text": "y" * (boss.AUTO_ROLL_TOKENS * 4)}])
    seen = {}

    class R:
        stop_reason, content = "end_turn", []

    def fake_create(model, system, messages, **kw):
        seen["n"] = len(messages)
        seen["first"] = messages[0]["content"][0]["text"]
        return R()

    monkeypatch.setattr(llm, "HAS_LLM", True)
    monkeypatch.setattr(llm, "create", fake_create)
    monkeypatch.setattr(llm, "text_of", lambda r: "ok")
    assert boss.chat("What next?") == "ok"
    assert boss.current_conversation() == 2
    assert seen["n"] == 3 and seen["first"].startswith(boss.RECAP_TAG)   # recap, ack, new message: not 30k tokens


def test_scout_scheduled_rounds_are_free_when_nothing_is_due(monkeypatch):
    from hq import agents, campaigns, db, discovery, llm
    db.init()
    db.execute("DELETE FROM posts")
    db.execute("DELETE FROM submissions")
    scout = agents.get("Scout")
    assert scout.nothing_to_do("Find posted campaign clips that still need submitting.", {"sync": True}) is True
    cid = db.execute("INSERT INTO campaigns (name, status, created_at) VALUES ('c', 'joined', ?)",
                     db.now())
    clip = db.execute("INSERT INTO clips (task_id, creator, source_url, source_title, start_s, end_s, path, title, caption, "
                      "hashtags, status, campaign_id, created_at) VALUES (1, 'x', 'u', 't', 0, 1, 'p', 't', 'c', '[]', "
                      "'approved', ?, ?)", cid, db.now())
    db.execute("INSERT INTO posts (clip_id, platform, account, status, url, created_at) VALUES (?, 'tiktok', 'a', "
               "'posted', 'http://x', ?)", clip, db.now())
    assert scout.nothing_to_do("x", {"sync": True}) is False             # a posted campaign clip needs logging
    campaigns.sync_submissions()
    assert scout.nothing_to_do("x", {"sync": True}) is True              # logged: nothing left
    monkeypatch.setattr(llm, "HAS_LLM", True)
    monkeypatch.setattr(discovery, "inbox", lambda status=None: [])
    monkeypatch.setattr(discovery, "feed_urls", lambda: [])
    assert scout.nothing_to_do("Look for new campaigns", {"discover": True}) is True
    monkeypatch.setattr(discovery, "feed_urls", lambda: ["http://feed"])
    assert scout.nothing_to_do("Look for new campaigns", {"discover": True}) is None
    monkeypatch.setattr(discovery, "inbox", lambda status=None: [{"id": 1}])
    assert scout.nothing_to_do("Look for new campaigns", {"discover": True}) is False
    assert scout.nothing_to_do("vet", {"text": "rules"}) is None


def test_pitch_recheck_round_is_free_when_every_card_has_an_email(monkeypatch):
    from hq import agents, approvals
    pitch = agents.get("Pitch")
    monkeypatch.setattr("hq.agents.pitch.agent.settings", lambda: {"paused": False})
    monkeypatch.setattr(approvals, "pending", lambda: [{"kind": "pitch", "payload": {"email": True}}])
    assert pitch.nothing_to_do("x", {"recheck": True}) is True
    monkeypatch.setattr(approvals, "pending", lambda: [{"kind": "pitch", "payload": {"email": False}}])
    assert pitch.nothing_to_do("x", {"recheck": True}) is None or pitch.nothing_to_do("x", {"recheck": True}) is False


def test_report_rolls_a_long_chat_over_too(monkeypatch):
    from hq import boss, db
    db.init()
    db.execute("DELETE FROM boss_messages")
    boss._save(1, "assistant", [{"type": "text", "text": "z" * (boss.AUTO_ROLL_TOKENS * 4)}])
    boss.report()
    assert boss.current_conversation() == 2 and boss.chat_tokens(2) < 5000


def test_captions_tolerate_words_just_past_the_cut(tmp_path):
    words = [{"start": 1.0, "end": 1.4, "text": "hello"}, {"start": 58.8, "end": 59.3, "text": "end"},
             {"start": 70.0, "end": 70.5, "text": "later"}]
    assert [w["text"] for w in editor.caption_words(words, 0, 59)] == ["hello", "end"]
    assert editor.write_captions(words, 0, 59, tmp_path / "c.ass")
    assert "END" in (tmp_path / "c.ass").read_text()


def test_short_titles_get_a_real_post_caption():
    from hq.agents.chad.agent import Chad as ChadAgent
    t = {"segments": [{"start": 1, "end": 3, "text": "no way he did that"}]}
    assert ChadAgent.post_caption("A very good title here", "Kai", t) == "A very good title here"
    cap = ChadAgent.post_caption("lol", "Kai", t, 0, 30)
    assert len(cap) > 5 and "no way he did that" in cap
    assert ChadAgent.post_caption("", "Kai", None) == "Kai moment"


def test_reject_flagged_only_rejects_clips_with_problems(monkeypatch):
    from hq import db, review
    db.init()
    db.execute("DELETE FROM clips")
    monkeypatch.setattr(review, "_chad_settings", lambda: {"captions": True})
    ts = db.now()
    ins = ("INSERT INTO clips (creator, source_url, start_s, end_s, path, title, caption, reason, captioned, score, status, created_at) "
           "VALUES ('kai', ?, 0, 30, 'x.mp4', 't', ?, 'why', ?, 9, 'pending_approval', ?)")
    bad = db.execute(ins, "http://v/1", "Good one\n\nCredit: Kai", 0, ts)
    good = db.execute(ins, "http://v/2", "Good one\n\nCredit: Kai", 1, ts)
    # file is missing for both, so give "good" no file problem by pointing at a real file
    import tempfile, os
    f = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False); f.close()
    db.execute("UPDATE clips SET path = ?", f.name)
    res = review.reject_flagged()
    os.unlink(f.name)
    assert res["rejected"] == [bad] and res["left"] == 1
    status = {r["id"]: r["status"] for r in db.rows("SELECT id, status FROM clips")}
    assert status == {bad: "rejected", good: "pending_approval"}
