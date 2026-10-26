"""Recap: turns a long video's transcript into a pack a streamer can paste (title, description, chapters, 5 posts).

Everything that can be checked in plain code is checked before Claude is called, and the answer is checked again
after. Recap only works on content its owner handed over, and it never sends anything: the finished pack waits in
Approvals, and approving it only shows Steven the text to send himself.
"""

import hashlib
import json
import re
from pathlib import Path

from . import approvals, db, llm, relay
from .config import model_for

MIN_WORDS = 300            # shorter than this isn't worth a pack
MIN_SECONDS = 600          # chapters need a video of at least 10 minutes
MAX_CHARS = 60000          # most transcript text sent to Claude; longer ones are trimmed evenly (keeps the bill small)
LINE_SECONDS = 30          # transcript lines are merged to about this long before sending
MIN_CHAPTER_GAP = 10       # YouTube needs chapters at least 10 seconds apart
TEXT_TYPES = {".txt", ".srt", ".vtt"}

SYSTEM = """You write a ready-to-paste pack for a streamer or podcaster from the transcript of one of their long videos.
You get lines that start with a timestamp (H:MM:SS) and the words spoken then.

Rules:
- Use only what is in the transcript. Never invent guests, results, numbers, products or quotes.
- title_options: 3 different YouTube titles, each under 70 characters, honest, specific, no clickbait or ALL CAPS.
- description: 2 to 4 short sentences on what happens in the video, plain and friendly. No hashtags, no links.
- chapters: 5 to 15 chapters in time order. start_seconds is the timestamp where the topic really begins, taken from
  the transcript's timestamps. The first chapter starts at 0. Titles are 2 to 6 words.
- posts: exactly 5 short social posts the creator could publish, each a different angle (a funny moment, a lesson,
  a question for fans, a quote from the video, a teaser). Each under 240 characters. No hashtag spam."""

SCHEMA = {
    "type": "object",
    "properties": {
        "title_options": {"type": "array", "items": {"type": "string"}},
        "description": {"type": "string"},
        "chapters": {"type": "array", "items": {
            "type": "object",
            "properties": {"start_seconds": {"type": "integer"}, "title": {"type": "string"}},
            "required": ["start_seconds", "title"], "additionalProperties": False}},
        "posts": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title_options", "description", "chapters", "posts"],
    "additionalProperties": False,
}


class RecapError(ValueError):
    """Something Steven can fix; the message says what, in plain words."""


# ---- reading a transcript (free) ----

_STAMP = r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,]\d+)?"
_LINE = re.compile(rf"^\s*[\[(]?{_STAMP}[\])]?\s*(?:-->\s*{_STAMP}\s*)?[\])]?\s*[-:]?\s*(.*)$")


def _secs(h, m, s) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s)


def parse_text(text: str) -> list[dict]:
    """Segments from timestamped text: '[0:01:23] words', SRT or VTT. Lines without a time continue the last segment."""
    segs = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or line.isdigit():
            continue
        m = _LINE.match(line)
        if m:
            g = m.groups()
            segs.append({"start": _secs(*g[:3]), "text": g[-1].strip()})
        elif segs:
            segs[-1]["text"] = f"{segs[-1]['text']} {line}".strip()
    return [s for s in segs if s["text"]]


def load(params: dict) -> list[dict]:
    """The transcript segments for a task: given as text, as a text/SRT/VTT file, or made from audio/video by Chad's Whisper."""
    if params.get("transcript"):
        segs = parse_text(str(params["transcript"]))
    elif params.get("file"):
        path = Path(str(params["file"]))
        if not path.is_file():
            raise RecapError(f"I can't find the file {path}.")
        if path.suffix.lower() in TEXT_TYPES:
            segs = parse_text(path.read_text(encoding="utf-8", errors="replace"))
        else:
            from .agents.chad.transcribe import transcribe
            result = transcribe(str(path))
            if not result:
                raise RecapError("Transcription isn't available here (Whisper). Give me a .txt, .srt or .vtt transcript instead.")
            segs = [{"start": s["start"], "text": s["text"]} for s in result["segments"]]
    else:
        raise RecapError('Give me {"transcript": "..."} or {"file": "path"}, plus "owner" and "client".')
    if not segs:
        raise RecapError("I found no timestamps in that transcript, and chapters need them. Lines should start like [0:12:30] or use SRT/VTT.")
    return segs


def words(segs: list[dict]) -> int:
    return sum(len(s["text"].split()) for s in segs)


def duration(segs: list[dict]) -> int:
    return int(max(s["start"] for s in segs))


def compact(segs: list[dict]) -> str:
    """Transcript lines of about LINE_SECONDS each, trimmed evenly so the whole thing fits MAX_CHARS."""
    lines, start, buf = [], None, []
    for s in sorted(segs, key=lambda s: s["start"]):
        if start is None:
            start = s["start"]
        elif s["start"] - start >= LINE_SECONDS:
            lines.append((start, " ".join(buf)))
            start, buf = s["start"], []
        buf.append(s["text"])
    if buf:
        lines.append((start, " ".join(buf)))
    room = max(40, MAX_CHARS // len(lines) - 10)
    return "\n".join(f"{stamp(t)} {txt[:room]}" for t, txt in lines)


def stamp(seconds: float) -> str:
    s = int(seconds)
    h, m = divmod(s // 60, 60)
    return f"{h}:{m:02d}:{s % 60:02d}" if h else f"{m}:{s % 60:02d}"


def fingerprint(segs: list[dict]) -> str:
    return hashlib.sha256(" ".join(s["text"] for s in segs).encode()).hexdigest()[:24]


# ---- checking Claude's answer (free) ----

def clean(pack: dict, length: int) -> dict:
    """Fix what code can fix (order, chapter 0:00, too-close or out-of-range chapters) and reject what it can't."""
    titles = [t.strip() for t in pack.get("title_options", []) if t.strip()]
    posts = [p.strip() for p in pack.get("posts", []) if p.strip()]
    if len(titles) < 3 or len(posts) < 5 or not str(pack.get("description", "")).strip():
        raise RecapError("Claude's pack was incomplete (needs 3 titles, a description and 5 posts). Try again.")
    chapters = []
    for c in sorted(pack.get("chapters", []), key=lambda c: c["start_seconds"]):
        t, title = int(c["start_seconds"]), c["title"].strip()
        if not title or t < 0 or t > length:
            continue
        if chapters and t - chapters[-1]["start_seconds"] < MIN_CHAPTER_GAP:
            continue
        chapters.append({"start_seconds": t, "title": title})
    if not chapters or chapters[0]["start_seconds"] != 0:
        if chapters and chapters[0]["start_seconds"] < MIN_CHAPTER_GAP:
            chapters[0]["start_seconds"] = 0
        else:
            chapters.insert(0, {"start_seconds": 0, "title": "Intro"})
    if len(chapters) < 3:  # YouTube only shows chapters from three up
        raise RecapError("Claude gave fewer than 3 usable chapters. Try again.")
    return {"title_options": [t[:100] for t in titles[:3]], "description": pack["description"].strip(),
            "chapters": chapters, "posts": [p[:280] for p in posts[:5]]}


def format_pack(pack: dict, client: str = "") -> str:
    chapters = "\n".join(f"{stamp(c['start_seconds'])} {c['title']}" for c in pack["chapters"])
    posts = "\n\n".join(f"{i}. {p}" for i, p in enumerate(pack["posts"], 1))
    titles = "\n".join(f"- {t}" for t in pack["title_options"])
    head = f"Recap pack for {client}\n\n" if client else ""
    return (f"{head}TITLE OPTIONS\n{titles}\n\nDESCRIPTION\n{pack['description']}\n\n"
            f"CHAPTERS (paste at the end of the description)\n{chapters}\n\nPOST IDEAS\n{posts}")


# ---- making and approving a pack ----

def make(params: dict) -> str:
    owner = " ".join(str(params.get("owner") or "").split())
    client = " ".join(str(params.get("client") or "").split())
    if len(owner) < 5 or not client:
        raise RecapError('Recap only works on content its owner handed over. Add "client" (their name) and "owner" '
                         '(how they gave it to you, e.g. "emailed me this VOD on 26 Oct").')
    segs = load(params)
    if words(segs) < MIN_WORDS:
        raise RecapError(f"That transcript is only {words(segs)} words. A pack needs at least {MIN_WORDS}.")
    length = duration(segs)
    if length < MIN_SECONDS:
        raise RecapError(f"That video is only {stamp(length)} long. Chapters need at least {MIN_SECONDS // 60} minutes.")
    fp = fingerprint(segs)
    if (old := db.rows("SELECT id, status FROM recaps WHERE fingerprint = ?", fp)):
        return f"Recap #{old[0]['id']} already covers this transcript ({old[0]['status']}). Nothing new was made."
    if not llm.HAS_LLM:
        raise RecapError("Recap needs ANTHROPIC_API_KEY set to write the pack.")
    prompt = f"Video length: {stamp(length)}\n\nTranscript:\n{compact(segs)}"
    pack = clean(llm.ask_json(model_for("recap"), SYSTEM, prompt, SCHEMA, effort="low", agent="Recap"), length)
    rid = db.execute("INSERT INTO recaps (client, owner_note, source, fingerprint, pack, status, created_at) "
                     "VALUES (?, ?, ?, ?, ?, 'pending', ?)", client, owner, str(params.get("file") or "pasted text"),
                     fp, json.dumps(pack), db.now())
    approvals.request("Recap", "recap", f"Recap pack for {client}", format_pack(pack, client), {"recap_id": rid},
                      yes="Approve pack", no="Reject")
    return f"Recap #{rid} for {client} is waiting for your OK."


def _decided(payload: dict, decision: str) -> str:
    rows = db.rows("SELECT * FROM recaps WHERE id = ?", payload["recap_id"])
    if not rows:
        return "That recap no longer exists."
    r = rows[0]
    if decision == "reject":
        db.execute("UPDATE recaps SET status = 'rejected', decided_at = ? WHERE id = ?", db.now(), r["id"])
        return f"Rejected the pack for {r['client']}."
    db.execute("UPDATE recaps SET status = 'approved', decided_at = ? WHERE id = ?", db.now(), r["id"])
    text = format_pack(json.loads(r["pack"]), r["client"])
    relay.notify(f"Send this to {r['client']} yourself (Recap never sends):\n\n{text}")
    return f"Approved. Send this to {r['client']} by email or Discord:\n\n{text}"


approvals.HANDLERS["recap"] = _decided
