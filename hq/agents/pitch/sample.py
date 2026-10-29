"""A private sample clip for a pitch: one 20-30 second vertical clip cut from the streamer's own public Twitch clip.

It is never posted anywhere. Steven watches it and approves it before the link goes into the email, and the file is
deleted after 14 days. Streamers open it through a private link nobody can guess.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone

from ... import approvals, db, ledger
from ...config import SAMPLES_DIR
from ..chad import editor, sources, twitch
from ..chad.transcribe import transcribe

KEEP_DAYS = 14
MIN_SECONDS, MAX_SECONDS = 20.0, 30.0


def _iso(days: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")


def link(token: str) -> str | None:
    base = os.getenv("HQ_SAMPLE_BASE_URL", "").strip().rstrip("/")
    return f"{base}/sample/{token}" if base else None


def find(token: str) -> dict | None:
    """The sample behind a private link, only while it is approved, not expired and its file still exists."""
    rows = db.rows("SELECT * FROM samples WHERE token = ? AND status = 'approved' AND expires_at > ?", token, _iso())
    if rows and os.path.exists(rows[0]["path"]):
        return rows[0]
    return None


def _delete_file(path: str) -> None:
    for p in (path, os.path.splitext(path)[0] + ".ass"):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


def make(lead_id: int) -> str:
    """Cut the sample for a lead Steven marked as good, and ask him to watch it."""
    rows = db.rows("SELECT * FROM leads WHERE id = ?", lead_id)
    if not rows:
        return f"No lead #{lead_id}."
    lead = rows[0]
    if lead["status"] != "drafted":
        return f"{lead['name']} is {lead['status']}, so no sample was made (samples go with pitches waiting for your OK)."
    if lead["platform"] != "twitch":
        return f"Chad can only cut samples from Twitch channels so far; {lead['name']} is on {lead['platform']}."
    if db.rows("SELECT 1 FROM samples WHERE lead_id = ?", lead_id):
        return f"{lead['name']} already has a sample."
    if ledger.over_budget():
        return "Today's budget is spent, so I'm paused until tomorrow."
    uid = twitch.user_id(lead["handle"])
    clips = twitch.top_clips(uid, days=30, limit=1) if uid else []
    if not clips:
        return f"{lead['name']} has no public Twitch clip from the last 30 days to cut a sample from."
    video = sources.download(clips[0]["url"])
    length = editor.duration(video["path"])
    if length < MIN_SECONDS:
        # Too short to sample: Twitch clips run under a minute and this one is too brief to impress anyone.
        return f"{lead['name']}'s best recent clip is only {length:.0f}s, shorter than {MIN_SECONDS:.0f}s, so no sample was made."
    length = min(length, MAX_SECONDS)
    token = secrets.token_urlsafe(24)
    out = SAMPLES_DIR / f"{token}.mp4"
    words = transcribe(video["path"])
    try:
        editor.render(video["path"], 0, length, out, words["words"] if words else None)
    except Exception:
        _delete_file(str(out))
        raise
    db.execute("INSERT INTO samples (lead_id, token, path, source_url, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
               lead_id, token, str(out), clips[0]["url"], db.now(), _iso(KEEP_DAYS))
    url = link(token)
    note = (f"Link for the email (works once you approve): {url}" if url else
            "HQ_SAMPLE_BASE_URL isn't set, so no link can go in the email. Set it in Settings, or send the file yourself.")
    approvals.request("Pitch", "sample", f"Private sample clip for {lead['name']}",
                      f"{length:.0f}s vertical clip with captions, cut from their public clip \"{clips[0]['title']}\".\n"
                      f"Watch it: {out}\nIt is never posted. It is deleted after {KEEP_DAYS} days.\n{note}",
                      {"lead_id": lead_id}, yes="Attach to the pitch", no="Throw it away")
    return f"Sample for {lead['name']} is waiting for your OK."


def handle_decision(payload: dict, decision: str) -> str:
    """Steven watched the sample. Approving puts the private link in the pitch draft; he still has to send that."""
    lid = payload["lead_id"]
    rows = db.rows("SELECT * FROM samples WHERE lead_id = ? AND status = 'pending'", lid)
    if not rows:
        return "That sample is no longer waiting."
    s = rows[0]
    if decision == "reject":
        _delete_file(s["path"])
        db.execute("UPDATE samples SET status = 'rejected' WHERE lead_id = ?", lid)
        return "Sample thrown away."
    db.execute("UPDATE samples SET status = 'approved', approved_at = ? WHERE lead_id = ?", db.now(), lid)
    url = link(s["token"])
    if not url:
        return "Sample approved, but HQ_SAMPLE_BASE_URL isn't set so there is no link to attach."
    lead = db.rows("SELECT * FROM leads WHERE id = ?", lid)[0]
    if lead["status"] == "drafted" and url not in (lead["pitch"] or ""):
        line = f"I cut you a private sample clip (link works for {KEEP_DAYS} days): {url}"
        pitch = (lead["pitch"] or "").rstrip("\n") + f"\n\n{line}"
        db.execute("UPDATE leads SET pitch = ?, updated_at = ? WHERE id = ?", pitch, db.now(), lid)
        with db.connect() as c:
            for a in approvals.pending():
                if a["kind"] == "pitch" and a["payload"].get("lead_id") == lid:
                    c.execute("UPDATE approvals SET preview = ? WHERE id = ?",
                              (a["preview"].rstrip("\n") + f"\n\n[Sample link added: {url}]", a["id"]))
    return "Sample approved and the private link is in the pitch draft. Send the pitch when you're ready."


def mark_replied(lead_id: int) -> None:
    db.execute("UPDATE samples SET replied = 1 WHERE lead_id = ? AND status IN ('approved', 'deleted')", lead_id)


def cleanup() -> int:
    """Delete every sample file past its 14 days. The row stays, so Steven can still see which leads replied."""
    gone = 0
    for s in db.rows("SELECT * FROM samples WHERE status IN ('pending', 'approved') AND expires_at <= ?", _iso()):
        _delete_file(s["path"])
        db.execute("UPDATE samples SET status = 'deleted' WHERE lead_id = ?", s["lead_id"])
        gone += 1
    return gone


def due_for_cleanup() -> bool:
    return bool(db.rows("SELECT 1 FROM samples WHERE status IN ('pending', 'approved') AND expires_at <= ? LIMIT 1", _iso()))


def summary() -> str:
    rows = db.rows("SELECT status, replied FROM samples")
    made = [r for r in rows if r["status"] != "rejected"]
    if not made:
        return ""
    sent = sum(1 for r in made if r["status"] in ("approved", "deleted"))
    return f"Samples: {sent} attached, {sum(r['replied'] for r in made)} of those leads replied."
