"""Pitch: finds creators who might pay for clipping and drafts the message. You approve and send it yourself."""

import json
import re
from datetime import datetime, timedelta, timezone

import yaml

from ... import approvals, db, llm, relay
from ...config import CONFIG_DIR, model_for
from ..base import Agent
from ..chad import twitch

SYSTEM = """You write the first message from Steven, a clipper, to a streamer or podcaster who might pay him to clip
their content for TikTok, YouTube Shorts and Instagram Reels.

Rules:
- 4 to 6 short lines. Friendly, plain, like a real person. No hype, no emoji spam, no "I hope this finds you well".
- Open with something specific about THEM from the facts you're given (a recent clip, their game, their bio). Never
  invent facts, results, follower counts or past clients. If you know little, say less.
- Say what Steven offers, in one sentence. Mention the price only if one is given.
- Offer a free sample clip only if told to.
- End with one easy question they can answer in a few words.
- Finish with the opt-out line you're given, word for word.
- Sign with the sender name you're given.
The subject line (for email) is short and not clickbait."""

SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "message": {"type": "string"},
        "why_this_lead": {"type": "string", "description": "One sentence on why this creator might say yes"},
    },
    "required": ["subject", "message", "why_this_lead"],
    "additionalProperties": False,
}

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
STATUSES = ("new", "drafted", "pitched", "replied", "client", "dead", "dropped")


def settings() -> dict:
    path = CONFIG_DIR / "pitch.yaml"
    return (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}


def _iso(days: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")


def _handle_pitch_decision(payload: dict, decision: str) -> str:
    lead = db.rows("SELECT * FROM leads WHERE id = ?", payload["lead_id"])[0]
    if decision == "reject":
        db.execute("UPDATE leads SET status = 'dropped', updated_at = ? WHERE id = ?", db.now(), lead["id"])
        return f"Dropped {lead['name']}."
    days = float(settings().get("followup_days", 4))
    db.execute("UPDATE leads SET status = 'pitched', followup_at = ?, updated_at = ? WHERE id = ?",
               _iso(days), db.now(), lead["id"])
    text = f"Send this to {lead['name']} ({lead['platform']}). Contact: {lead['contact']}\n\n{lead['pitch']}"
    relay.notify(text)
    return f"Marked as pitched. I'll remind you to follow up in {days:g} days.\n\n{text}"


approvals.HANDLERS["pitch"] = _handle_pitch_decision


class Pitch(Agent):
    def __init__(self):
        super().__init__(
            name="Pitch",
            role="Client finder. Finds streamers and podcasters who might pay you to clip for them, drafts a personal "
                 "message for each, and reminds you to follow up. You approve and send every message yourself.",
            params_help='{"find": 5} to find and draft pitches for new Twitch streamers (needs config/pitch.yaml filled in); '
                        '{"lead": {"name": "...", "platform": "youtube", "handle": "...", "contact": "email or link", '
                        '"notes": "what you know about them"}} to draft a pitch for someone you found; {"followups": true}; '
                        '{"mark": {"lead_id": 1, "status": "replied|client|dead", "note": "..."}}; {"report": true}.',
            schedule=self._schedule(),
        )

    @staticmethod
    def _schedule() -> list:
        out = [(24, "Check which pitched leads need a follow-up.", {"followups": True})]
        try:
            cfg = settings()
        except Exception:
            return out
        if cfg.get("auto_find"):
            out.append((24, "Find new leads and draft pitches.", {"find": int(cfg.get("daily_leads", 5))}))
        return out

    def run(self, task: dict) -> str:
        params = json.loads(task.get("params") or "{}")
        if params.get("find"):
            return self.find(int(params["find"]))
        if params.get("lead"):
            return self.draft_lead(params["lead"])
        if params.get("mark"):
            return self.mark(params["mark"])
        if params.get("followups"):
            return self.followups()
        return self.report()

    # ---- finding and drafting ----

    def _ready(self) -> str | None:
        if not llm.HAS_LLM:
            return "Pitch needs ANTHROPIC_API_KEY set to write messages."
        if not str(settings().get("sender_name") or "").strip():
            return "Fill in sender_name (and ideally about_me and price) in config/pitch.yaml first, then ask again."
        return None

    def find(self, n: int) -> str:
        problem = self._ready()
        if problem:
            return problem
        cfg = settings()
        known = {r["handle"].lower() for r in db.rows("SELECT handle FROM leads WHERE platform = 'twitch'")}
        candidates = [s for s in twitch.small_streamers(int(cfg.get("min_viewers", 50)), int(cfg.get("max_viewers", 2000)),
                                                         cfg.get("language", "en"))
                      if s["login"].lower() not in known]
        made = []
        for s in candidates:
            if len(made) >= n:
                break
            info = twitch.profile(s["id"])
            email = next(iter(EMAIL.findall(info["bio"])), None)
            clips = twitch.top_clips(s["id"], days=14, limit=1)
            facts = [f"Streams {s['game'] or 'various games'} on Twitch, about {s['viewers']} live viewers right now."]
            if info["bio"]:
                facts.append(f"Their bio: {info['bio'][:300]}")
            if clips:
                facts.append(f"Their most-viewed clip lately: \"{clips[0]['title']}\" ({clips[0]['views']:,} views).")
            lead = {"name": s["name"], "platform": "twitch", "handle": s["login"], "followers": s["viewers"],
                    "contact": email or f"https://twitch.tv/{s['login']} (no email in bio: use their Twitch chat rules, "
                                        "Discord or X; don't spam)", "notes": " ".join(facts)}
            made.append(self.draft_lead(lead, quiet=True))
        if not made:
            return "No new streamers matched your viewer range. Widen min_viewers/max_viewers in config/pitch.yaml."
        return f"Drafted {len(made)} pitch(es). Approve the ones you'll send: " + ", ".join(made)

    def draft_lead(self, lead: dict, quiet: bool = False) -> str:
        problem = self._ready()
        if problem:
            return problem
        cfg = settings()
        existing = db.rows("SELECT id FROM leads WHERE platform = ? AND handle = ?", lead["platform"], lead["handle"])
        if existing:
            return f"{lead['name']} is already a lead (#{existing[0]['id']})."
        facts = "\n".join(f"- {x}" for x in [
            f"Creator: {lead['name']} ({lead['platform']})", lead.get("notes") or "No other facts known.",
            f"Steven offers: {cfg.get('what_you_offer')}",
            f"Price to mention: {cfg.get('price')}" if cfg.get("price") else "Do not mention a price.",
            f"About Steven: {cfg.get('about_me')}" if cfg.get("about_me") else "Say nothing about Steven's background.",
            f"Portfolio link to include: {cfg.get('portfolio_url')}" if cfg.get("portfolio_url") else "No portfolio link.",
            "Offer one free sample clip." if cfg.get("free_sample") else "Do not offer a free sample.",
            f"Opt-out line: {cfg.get('opt_out_line')}", f"Sign as: {cfg.get('sender_name')}"] if x)
        draft = llm.ask_json(model_for("pitch"), SYSTEM, facts, SCHEMA, effort="low", agent="Pitch")
        text = f"Subject: {draft['subject']}\n\n{draft['message']}"
        ts = db.now()
        lid = db.execute("INSERT INTO leads (name, platform, handle, followers, contact, notes, pitch, status, created_at, "
                         "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'drafted', ?, ?)", lead["name"], lead["platform"],
                         lead["handle"], lead.get("followers"), lead.get("contact"), lead.get("notes"), text, ts, ts)
        approvals.request("Pitch", "pitch", f"Pitch to {lead['name']} ({lead['platform']})",
                          f"{draft['why_this_lead']}\nContact: {lead.get('contact')}\n\n{text}",
                          {"lead_id": lid}, yes="I'll send it", no="Drop")
        return f"{lead['name']} (lead #{lid})"

    # ---- keeping track ----

    def mark(self, m: dict) -> str:
        if m.get("status") not in STATUSES:
            return f"status must be one of {', '.join(STATUSES)}"
        db.execute("UPDATE leads SET status = ?, notes = COALESCE(notes, '') || ?, updated_at = ? WHERE id = ?",
                   m["status"], f"\n[{db.now()[:10]}] {m['note']}" if m.get("note") else "", db.now(), int(m["lead_id"]))
        return f"Lead #{m['lead_id']} is now {m['status']}."

    def followups(self) -> str:
        cfg = settings()
        limit, days = int(cfg.get("max_followups", 2)), float(cfg.get("followup_days", 4))
        due = db.rows("SELECT * FROM leads WHERE status = 'pitched' AND followup_at IS NOT NULL AND followup_at <= ?", _iso())
        lines = []
        for lead in due:
            if lead["followups"] >= limit:
                db.execute("UPDATE leads SET status = 'dead', updated_at = ? WHERE id = ?", db.now(), lead["id"])
                lines.append(f"{lead['name']}: no reply after {limit} follow-ups, marked dead.")
                continue
            db.execute("UPDATE leads SET followups = followups + 1, followup_at = ?, updated_at = ? WHERE id = ?",
                       _iso(days), db.now(), lead["id"])
            lines.append(f"Follow up with {lead['name']} ({lead['contact']}): a short, friendly nudge, no pressure.")
        if not lines:
            return "No follow-ups due."
        text = "\n".join(lines)
        relay.notify(text)
        return text

    def report(self) -> str:
        counts = {r["status"]: r["n"] for r in db.rows("SELECT status, COUNT(*) n FROM leads GROUP BY status")}
        if not counts:
            return "No leads yet."
        return "Leads: " + ", ".join(f"{n} {s}" for s, n in counts.items())
