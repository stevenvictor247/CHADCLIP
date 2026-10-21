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
