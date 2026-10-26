"""Podcast clip packs: 5 captioned vertical clips plus Recap's titles and post ideas from one episode, for $49.

Everything that can be checked in plain code is checked before Whisper or Claude run. Packs only works on an episode
its owner handed over, and it never sends anything: the finished pack waits in Approvals, and approving it only shows
Steven the folder and the message to send himself.
"""

import hashlib
import json
import re
from pathlib import Path

from . import approvals, db, ledger, recap, relay
from .agents.chad import editor, moments
from .agents.chad.transcribe import transcribe
from .config import PACKS_DIR

PRICE_CENTS = 4900
CLIPS = 5
MIN_CLIP_SECONDS, MAX_CLIP_SECONDS = 20.0, 59.0
MIN_EPISODE_SECONDS = 600     # five separate clips need an episode of at least 10 minutes
VIDEO_TYPES = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


class PackError(ValueError):
    """Something Steven can fix; the message says what, in plain words."""


def _fingerprint(path: Path) -> str:
    h = hashlib.sha256(str(path.stat().st_size).encode())
    with path.open("rb") as f:
        h.update(f.read(1 << 20))
    return h.hexdigest()[:24]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:30] or "pack"


def format_pack(pack: dict, client: str, folder: str = "") -> str:
    clips = "\n".join(f"{i}. {c['file']} ({c['seconds']:.0f}s): {c['title']}\n   {c['caption']}"
                      for i, c in enumerate(pack["clips"], 1))
    where = f"Files are in {folder}\n\n" if folder else ""
    return f"Clip pack for {client}\n\n{where}CLIPS\n{clips}\n\n{recap.format_pack(pack['text'])}"


def delivery_message(pack: dict, client: str) -> str:
    """The note Steven sends with the files. It asks for the testimonial and never mentions anything posted for them."""
    return (f"Hi, here is your clip pack: 5 captioned vertical clips plus titles, a description, chapters and post ideas "
            f"for your episode. The clips are yours to post wherever you like.\n\nIf you're happy with it, would you "
            f"reply with one or two sentences I can use as a testimonial?\n\n{format_pack(pack, client)}")


def make(params: dict) -> str:
    owner = " ".join(str(params.get("owner") or "").split())
    client = " ".join(str(params.get("client") or "").split())
    if len(owner) < 5 or not client:
        raise PackError('Packs only works on episodes their owner handed over. Add "client" (the podcast) and "owner" '
                        '(how they gave it to you, e.g. "emailed me episode 12 and said yes to clips, 26 Oct").')
    path = Path(str(params.get("file") or ""))
    if not path.is_file():
        raise PackError(f"I can't find the episode file {path}. Give me the path to the video file.")
    if path.suffix.lower() not in VIDEO_TYPES:
        raise PackError("A pack needs the episode as a video file (.mp4, .mov, .mkv, .webm) so the clips can be cut.")
    fp = _fingerprint(path)
    if (old := db.rows("SELECT id, status FROM clip_packs WHERE fingerprint = ?", fp)):
        return f"Pack #{old[0]['id']} already covers this episode ({old[0]['status']}). Nothing new was made."
    if ledger.over_budget():
        return "Today's budget is spent, so I'm paused until tomorrow."
    length = editor.duration(str(path))
    if length < MIN_EPISODE_SECONDS:
        raise PackError(f"That episode is only {recap.stamp(length)} long. A pack needs at least {MIN_EPISODE_SECONDS // 60} minutes.")
    transcript = transcribe(str(path))
    if not transcript or not transcript["segments"]:
        raise PackError("Transcription isn't available here (Whisper), and captions and chapters need it.")
    segs = [{"start": s["start"], "text": s["text"]} for s in transcript["segments"]]
    if recap.words(segs) < recap.MIN_WORDS:
        raise PackError(f"I only heard {recap.words(segs)} words in that episode. A pack needs at least {recap.MIN_WORDS}.")
    try:
        text = recap.write_pack(segs, int(length))
    except recap.RecapError as e:
        raise PackError(str(e)) from e
    picked = moments.pick(transcript, length, client, {"name": client}, CLIPS, MIN_CLIP_SECONDS, MAX_CLIP_SECONDS)
    if len(picked) < CLIPS:
        raise PackError(f"I found only {len(picked)} good moments of {CLIPS}. Try a longer episode or one with more talking.")
    folder = PACKS_DIR / f"{_slug(client)}-{fp[:8]}"
    clips = []
    try:
        for i, m in enumerate(picked, 1):
            out = editor.render(str(path), m["start"], m["end"], folder / f"clip-{i}.mp4", transcript["words"])
            clips.append({"file": out.name, "seconds": m["end"] - m["start"], "title": m["title"][:80],
                          "caption": m["caption"]})
    except Exception:
        for f in folder.glob("*"):
            f.unlink()
        raise
    pack = {"clips": clips, "text": text}
    (folder / "pack.txt").write_text(format_pack(pack, client), encoding="utf-8")
    pid = db.execute("INSERT INTO clip_packs (client, owner_note, source, fingerprint, folder, pack, price_cents, status, "
                     "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)", client, owner, str(path), fp, str(folder),
                     json.dumps(pack), PRICE_CENTS, db.now())
    approvals.request("Packs", "clip_pack", f"Clip pack for {client} (${PRICE_CENTS // 100})",
                      format_pack(pack, client, str(folder)), {"pack_id": pid}, yes="Approve pack", no="Reject")
    return f"Pack #{pid} for {client} is waiting for your OK."


def _decided(payload: dict, decision: str) -> str:
    rows = db.rows("SELECT * FROM clip_packs WHERE id = ?", payload["pack_id"])
    if not rows:
        return "That pack no longer exists."
    r = rows[0]
    if r["status"] != "pending":
        return f"Pack #{r['id']} is already {r['status']}."
    if decision == "reject":
        db.execute("UPDATE clip_packs SET status = 'rejected', decided_at = ? WHERE id = ?", db.now(), r["id"])
        return f"Rejected the pack for {r['client']}."
    db.execute("UPDATE clip_packs SET status = 'approved', decided_at = ? WHERE id = ?", db.now(), r["id"])
    text = f"Send {r['client']} the files in {r['folder']} yourself (Packs never sends):\n\n{delivery_message(json.loads(r['pack']), r['client'])}"
    relay.notify(text)
    return f"Approved. {text}"


approvals.HANDLERS["clip_pack"] = _decided
