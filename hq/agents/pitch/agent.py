"""Pitch: finds creators who might pay for clipping and drafts the message. You approve and send it yourself."""

import json
from datetime import datetime, timedelta, timezone

import yaml

from ... import approvals, db, llm, relay
from ... import offer
from ...config import CONFIG_DIR, model_for
from ..base import Agent
from ..chad import twitch
from . import finder, mailer, sample, score as lead_score

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

FOLLOWUP_SYSTEM = """You write a short follow-up from Steven, a clipper, to a streamer or podcaster he emailed a few days ago
and who has not replied. 2 to 3 short lines. Friendly, no pressure, no guilt, no pretending they saw the first email.
Do not repeat the whole pitch, invent facts, or mention a price. Offer to answer questions or send the free sample
clip only if the original offered one. Finish with the opt-out line you're given, word for word, then sign with the
sender name you're given."""

FOLLOWUP_SCHEMA = {
    "type": "object",
    "properties": {"message": {"type": "string"}},
    "required": ["message"],
    "additionalProperties": False,
}

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

MAX_PROFILE_CHECKS = 150  # most Twitch profiles one find run looks at
STATUSES = ("new", "drafted", "pitched", "replied", "client", "won", "dead", "dropped", "do_not_contact")


def settings() -> dict:
    path = CONFIG_DIR / "pitch.yaml"
    return (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}


def _iso(days: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")


def _unsent(lead: dict, why: str) -> str:
    """The email didn't go: put the same draft back in the queue so one tap tries again."""
    approvals.request("Pitch", "pitch", f"Pitch to {lead['name']} ({lead['platform']}): NOT SENT",
                      f"Not sent: {why}\nContact: {lead['contact']}\n\n{lead['pitch']}",
                      {"lead_id": lead["id"], "email": True}, yes="Try again", no="Drop")
    return f"Not sent: {why} I put {lead['name']}'s draft back in Waiting for your OK."


def _claim(lead_id: int) -> bool:
    """Take the lead from drafted to sending in one step, so a double tap can never send twice."""
    with db.connect() as c:
        return c.execute("UPDATE leads SET status = 'sending', updated_at = ? WHERE id = ? AND status = 'drafted'",
                         (db.now(), lead_id)).rowcount == 1


PAUSED_MSG = "Pitch emails are paused (Settings > Pitch > Pause Pitch emails). Nothing was drafted or sent."


def paused(cfg: dict | None = None) -> bool:
    return bool((settings() if cfg is None else cfg).get("paused", True))   # paused until Steven turns it off


def _email_blocker(cfg: dict) -> str | None:
    if paused(cfg):
        return "Pitch emails are paused. Turn off Pause Pitch emails in Settings to send."
    if not str(cfg.get("sender_name") or "").strip():
        return "fill in your name on the Settings page (Pitch section)."
    if not str(cfg.get("postal_address") or "").strip():
        return "fill in your postal address in the Pitch section of the Settings page (spam law needs one; a PO box is fine)."
    if mailer.sent_last_day() >= mailer.cap(cfg):
        return f"you've reached today's limit of {mailer.cap(cfg)} emails. Try again tomorrow."
    return None


def _handle_pitch_decision(payload: dict, decision: str) -> str:
    lead = db.rows("SELECT * FROM leads WHERE id = ?", payload["lead_id"])[0]
    if decision == "reject":
        db.execute("UPDATE leads SET status = 'dropped', updated_at = ? WHERE id = ? AND status = 'drafted'",
                   db.now(), lead["id"])
        return f"Dropped {lead['name']}."
    if lead["status"] != "drafted":
        return f"{lead['name']} is already {lead['status']}, so nothing was sent."
    cfg = settings()
    days = float(cfg.get("followup_days", 4))
    to = mailer.address_in(lead["contact"])
    if to and mailer.configured() and payload.get("email"):  # only if the card said "Send email" when Steven read it
        if mailer.blocked(to):
            db.execute("UPDATE leads SET status = 'do_not_contact', updated_at = ? WHERE id = ?", db.now(), lead["id"])
            return f"{to} is on your do-not-contact list, so nothing was sent."
        blocker = _email_blocker(cfg)
        if blocker:
            return _unsent(lead, blocker)
        if not _claim(lead["id"]):
            return f"{lead['name']} is already being handled, so nothing was sent."
        try:
            mailer.send(mailer.build(cfg, to, lead["pitch"]))
        except mailer.SendError as e:
            db.execute("UPDATE leads SET status = 'drafted', updated_at = ? WHERE id = ?", db.now(), lead["id"])
            return _unsent(lead, str(e))
        except Exception as e:  # never leave a lead stuck in 'sending' without telling Steven
            db.execute("UPDATE leads SET status = 'drafted', updated_at = ? WHERE id = ?", db.now(), lead["id"])
            return _unsent(lead, f"something went wrong ({e.__class__.__name__}).")
        db.execute("INSERT OR IGNORE INTO pitch_sent (lead_id, email, subject, sent_at) VALUES (?, ?, ?, ?)",
                   lead["id"], to, mailer.split_pitch(lead["pitch"])[0], db.now())
        db.execute("UPDATE leads SET status = 'pitched', followup_at = ?, updated_at = ? WHERE id = ?",
                   _iso(days), db.now(), lead["id"])
        db.log("Pitch", f"Emailed {lead['name']} at {to}")
        return f"Emailed {lead['name']} at {to}. I'll remind you to follow up in {days:g} days."
    db.execute("UPDATE leads SET status = 'pitched', followup_at = ?, updated_at = ? WHERE id = ?",
               _iso(days), db.now(), lead["id"])
    text = f"Send this to {lead['name']} ({lead['platform']}). Contact: {lead['contact']}\n\n{lead['pitch']}"
    relay.notify(text)
    return f"Marked as pitched. I'll remind you to follow up in {days:g} days.\n\n{text}"


def set_status(lead_id: int, status: str, note: str = "") -> None:
    """Change a lead's status. do_not_contact also blocks their email address for good."""
    rows = db.rows("SELECT contact FROM leads WHERE id = ?", lead_id)
    if not rows:
        raise KeyError(lead_id)
    if status == "do_not_contact" and (email := mailer.address_in(rows[0]["contact"])):
        mailer.add_do_not_contact(email, note)
    db.execute("UPDATE leads SET status = ?, notes = COALESCE(notes, '') || ?, updated_at = ? WHERE id = ?",
               status, f"\n[{db.now()[:10]}] {note}" if note else "", db.now(), lead_id)
    if status in ("replied", "client"):
        sample.mark_replied(lead_id)


def they_said_yes(lead_id: int, how: str = "") -> str:
    """A pitched streamer agreed. Record the permission where Chad reads it, and mark the lead a client."""
    from ... import creators
    rows = db.rows("SELECT * FROM leads WHERE id = ?", lead_id)
    if not rows:
        raise KeyError(lead_id)
    lead = rows[0]
    if lead["platform"] != "twitch":
        raise ValueError("Chad only clips Twitch channels so far; this lead isn't on Twitch")
    how = " ".join(how.split()) or f"said yes to my pitch, {db.now()[:10]}"
    creators.record_permission(lead["handle"], how)
    set_status(lead_id, "client", f"Said yes: {how}")
    db.log("Steven", f"Permission recorded for {lead['name']}: {how}")
    if offer.enabled(settings()):
        offer.create_client_folder(lead["handle"], settings())
    return f"Saved. Chad can now clip {lead['name']}."


def _unsent_followup(lead: dict, n: int, pitch: str, why: str) -> str:
    approvals.request("Pitch", "followup", f"Follow-up to {lead['name']} ({lead['platform']}): NOT SENT",
                      f"Not sent: {why}\nContact: {lead['contact']}\n\n{pitch}",
                      {"lead_id": lead["id"], "n": n, "pitch": pitch}, yes="Try again", no="Skip")
    return f"Not sent: {why} I put the follow-up back in Waiting for your OK."


def _handle_followup_decision(payload: dict, decision: str) -> str:
    lead = db.rows("SELECT * FROM leads WHERE id = ?", payload["lead_id"])[0]
    if decision == "reject":
        return f"Skipped the follow-up to {lead['name']}."
    n, pitch = int(payload["n"]), payload["pitch"]
    if lead["status"] != "pitched":  # they replied, said no, or became a client since the draft was made
        return f"{lead['name']} is now {lead['status']}, so no follow-up was sent."
    to = mailer.address_in(lead["contact"])
    if not to or not mailer.configured():
        return f"Can't email {lead['name']}: copy the follow-up and send it yourself.\n\n{pitch}"
    if mailer.blocked(to):
        db.execute("UPDATE leads SET status = 'do_not_contact', updated_at = ? WHERE id = ?", db.now(), lead["id"])
        return f"{to} is on your do-not-contact list, so nothing was sent."
    cfg = settings()
    blocker = _email_blocker(cfg)
    if blocker:
        return _unsent_followup(lead, n, pitch, blocker)
    with db.connect() as c:  # claim this follow-up number first, so a double tap can never send it twice
        claimed = c.execute("INSERT OR IGNORE INTO followup_sent (lead_id, n, email, sent_at) VALUES (?, ?, ?, ?)",
                            (lead["id"], n, to, db.now())).rowcount == 1
    if not claimed:
        return f"Follow-up {n} to {lead['name']} was already sent."
    try:
        mailer.send(mailer.build(cfg, to, pitch))
    except mailer.SendError as e:
        db.execute("DELETE FROM followup_sent WHERE lead_id = ? AND n = ?", lead["id"], n)
        return _unsent_followup(lead, n, pitch, str(e))
    except Exception as e:
        db.execute("DELETE FROM followup_sent WHERE lead_id = ? AND n = ?", lead["id"], n)
        return _unsent_followup(lead, n, pitch, f"something went wrong ({e.__class__.__name__}).")
    db.log("Pitch", f"Emailed follow-up {n} to {lead['name']} at {to}")
    return f"Emailed follow-up {n} to {lead['name']} at {to}."


approvals.HANDLERS["pitch"] = _handle_pitch_decision
approvals.HANDLERS["followup"] = _handle_followup_decision
approvals.HANDLERS["sample"] = sample.handle_decision


class Pitch(Agent):
    def __init__(self):
        super().__init__(
            name="Pitch",
            role="Client finder. Finds streamers and podcasters who might pay you to clip for them, drafts a personal "
                 "message for each, and reminds you to follow up. You approve and send every message yourself.",
            params_help='{"find": 5} to find and draft pitches for new Twitch streamers (needs config/pitch.yaml filled in); '
                        '{"lead": {"name": "...", "platform": "youtube", "handle": "...", "contact": "email or link", '
                        '"notes": "what you know about them"}} to draft a pitch for someone you found; {"followups": true}; '
                        '{"mark": {"lead_id": 1, "status": "replied|client|won|dead|do_not_contact", "note": "..."}}; '
                        '{"sample": 1} to cut a private sample clip for a drafted lead you marked as good (you approve it before its link goes in the pitch); {"do_not_contact": "email@example.com"}; {"recheck": true} to look for emails for pitches already waiting for your OK; {"report": true}.',
            schedule=self._schedule(),
        )

    @staticmethod
    def _schedule() -> list:
        out = [(24, "Check which pitched leads need a follow-up.", {"followups": True}),
               (24, "Delete private sample clips older than 14 days.", {"sample_cleanup": True}),
               (24, "Look for emails for pitches waiting for approval that have none.", {"recheck": True})]
        try:
            cfg = settings()
        except Exception:
            return out
        if cfg.get("auto_find"):
            out.append((24, "Find new leads and draft pitches.", {"find": int(cfg.get("daily_leads", 5))}))
        return out

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        """Follow-up rounds are a plain database look: when no pitched lead is due, no task is queued at all."""
        if paused() and params != {"sample_cleanup": True}:
            return True   # paused: no scheduled round queues anything but old-file cleanup
        if params.get("followups") and set(params) == {"followups"}:
            return not db.rows("SELECT 1 FROM leads WHERE status = 'pitched' AND followup_at IS NOT NULL "
                               "AND followup_at <= ? LIMIT 1", _iso())
        if params == {"sample_cleanup": True}:
            return not sample.due_for_cleanup()
        if params == {"recheck": True}:   # only cards still without an email are worth another look
            return not any(a["kind"] == "pitch" and not a["payload"].get("email") for a in approvals.pending())
        return None

    def run(self, task: dict) -> str:
        params = json.loads(task.get("params") or "{}")
        if paused() and not (params.keys() & {"mark", "do_not_contact", "sample_cleanup"}):
            return PAUSED_MSG   # keeps leads and drafts as they are; only bookkeeping still runs
        if params.get("find"):
            return self.find(int(params["find"]))
        if params.get("sample"):
            return sample.make(int(params["sample"]))
        if params.get("sample_cleanup"):
            return f"Deleted {sample.cleanup()} old sample clip(s)."
        if params.get("lead"):
            return self.draft_lead(params["lead"])
        if params.get("do_not_contact"):
            mailer.add_do_not_contact(str(params["do_not_contact"]).strip(), "added by Steven")
            return f"{params['do_not_contact']} is on the do-not-contact list. Pitch will never email it."
        if params.get("mark"):
            return self.mark(params["mark"])
        if params.get("followups"):
            return self.followups()
        if params.get("recheck"):
            return self.recheck()
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
                                                         cfg.get("language", "en"), max_pages=20)
                      if s["login"].lower() not in known]
        made, checked = [], 0
        for s in candidates:
            if len(made) >= n or checked >= MAX_PROFILE_CHECKS:
                break
            checked += 1
            info = twitch.profile(s["id"])
            pts, why = lead_score.lookup(s["login"], s["id"], info["bio"], info["type"], s["viewers"])
            if pts < int(cfg.get("min_score", lead_score.MIN_SHOWN)):   # free check first: no email lookup or tokens on weak leads
                continue
            found = finder.find_email("twitch", s["login"], info["bio"])
            email = found and found["email"]
            if not email:  # Pitch only drafts for creators it can email
                continue
            clips = twitch.top_clips(s["id"], days=14, limit=1)
            facts = [f"Streams {s['game'] or 'various games'} on Twitch, about {s['viewers']} live viewers right now."]
            if info["bio"]:
                facts.append(f"Their bio: {info['bio'][:300]}")
            if clips:
                facts.append(f"Their most-viewed clip lately: \"{clips[0]['title']}\" ({clips[0]['views']:,} views).")
            lead = {"name": s["name"], "platform": "twitch", "handle": s["login"], "followers": s["viewers"],
                    "contact": email, "notes": " ".join(facts), "score": pts, "score_why": why,
                    "email_source": found and finder.describe(found)}
            made.append(self.draft_lead(lead, quiet=True))
        if not made:
            if checked:
                return (f"None of the {checked} streamers I checked had a public email I could find. Try again later or "
                        "widen the viewer range in Settings.")
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
        if not mailer.address_in(lead.get("contact")):  # a link or a note, not an email: look for one on their public pages
            links = finder.urls_in(f"{lead.get('contact') or ''} {lead.get('notes') or ''}")
            if found := finder.find_email(lead["platform"], lead["handle"], extra_urls=links):
                lead = {**lead, "contact": found["email"], "email_source": finder.describe(found)}
        facts = "\n".join(f"- {x}" for x in [
            f"Creator: {lead['name']} ({lead['platform']})", lead.get("notes") or "No other facts known.",
            f"Steven offers: {cfg.get('what_you_offer')}",
            f"Price to mention: {cfg.get('price')}" if cfg.get("price") else "Do not mention a price.",
            f"About Steven: {cfg.get('about_me')}" if cfg.get("about_me") else "Say nothing about Steven's background.",
            f"Portfolio link to include: {cfg.get('portfolio_url')}" if cfg.get("portfolio_url") else "No portfolio link.",
            f"Second, cheaper offer: mention it in one sentence after the first: {cfg.get('second_offer')}" if cfg.get("second_offer") else None,
            f"Main offer, state it plainly and mention no other price: {offer.offer_line(cfg)}" if offer.enabled(cfg) else None,
            "Offer one free sample clip." if cfg.get("free_sample") else "Do not offer a free sample.",
            f"Opt-out line: {cfg.get('opt_out_line')}", f"Sign as: {cfg.get('sender_name')}"] if x)
        draft = llm.ask_json(model_for("pitch"), SYSTEM, facts, SCHEMA, effort="low", agent="Pitch")
        text = f"Subject: {draft['subject']}\n\n{draft['message']}"
        ts = db.now()
        lid = db.execute("INSERT INTO leads (name, platform, handle, followers, contact, notes, pitch, status, created_at, "
                         "updated_at, score, score_why) VALUES (?, ?, ?, ?, ?, ?, ?, 'drafted', ?, ?, ?, ?)", lead["name"],
                         lead["platform"], lead["handle"], lead.get("followers"), lead.get("contact"), lead.get("notes"),
                         text, ts, ts, lead.get("score"), lead.get("score_why"))
        to = mailer.address_in(lead.get("contact"))
        by_email = bool(to and mailer.configured())
        how = (f"Pressing Send email sends this from {mailer.credentials()[0]} to {to}.\n" if by_email else "")
        if to and lead.get("email_source"):
            how += f"{lead['email_source']}.\n"
        approvals.request("Pitch", "pitch", f"Pitch to {lead['name']} ({lead['platform']})",
                          f"{draft['why_this_lead']}\n{how}Contact: {lead.get('contact')}\n\n{text}",
                          {"lead_id": lid, "email": by_email}, yes="Send email" if by_email else "I'll send it", no="Drop")
        return f"{lead['name']} (lead #{lid})"

    def recheck(self) -> str:
        """Look for emails for pitches already waiting for approval with no address, and switch those cards to Send email."""
        fixed, missing = [], []
        for a in approvals.pending():
            if a["kind"] != "pitch" or a["payload"].get("email"):
                continue
            rows = db.rows("SELECT * FROM leads WHERE id = ? AND status = 'drafted'", a["payload"]["lead_id"])
            if not rows:
                continue
            lead = rows[0]
            bio = lead["notes"] or ""
            if lead["platform"] == "twitch":
                try:
                    bio = twitch.profile_by_login(lead["handle"])["bio"] or bio
                except Exception:  # no Twitch keys or no network: fall back on the bio saved with the lead
                    pass
            links = finder.urls_in(f"{lead['contact'] or ''} {lead['notes'] or ''}")
            found = finder.find_email(lead["platform"], lead["handle"], bio, links, retry_misses=True)
            if not found:
                missing.append(lead["name"])
                looked = ", ".join(finder.LAST_CHECKED[:3]) or "no links in their bio"
                note = f"Checked {db.now()[:10]}: no public email found (Twitch bio, {looked}). Reach them on Twitch, X or Instagram."
                lines = [l for l in a["preview"].split("\n") if not l.startswith("Checked ")]
                with db.connect() as c:
                    c.execute("UPDATE approvals SET preview = ? WHERE id = ? AND status = 'pending'",
                              ("\n".join(lines[:1] + [note] + lines[1:]), a["id"]))
                continue
            to, cfg_ok = found["email"], mailer.configured()
            how = f"Pressing Send email sends this from {mailer.credentials()[0]} to {to}.\n" if cfg_ok else ""
            why = a["preview"].split("\n", 1)[0]
            text = lead["pitch"]
            with db.connect() as c:
                c.execute("UPDATE leads SET contact = ? WHERE id = ?", (to, lead["id"]))
                c.execute("UPDATE approvals SET preview = ?, payload = ?, yes_label = ? WHERE id = ? AND status = 'pending'",
                          (f"{why}\n{how}{finder.describe(found)}.\nContact: {to}\n\n{text}",
                           json.dumps({"lead_id": lead["id"], "email": cfg_ok}),
                           "Send email" if cfg_ok else "I'll send it", a["id"]))
            fixed.append(f"{lead['name']} ({to})")
        if not fixed and not missing:
            return "Every waiting pitch already has an email."
        out = f"Found emails for {len(fixed)}: " + ", ".join(fixed) + "." if fixed else "Found no new emails."
        return out + (f" Still no public email for: {', '.join(missing)}." if missing else "")

    # ---- keeping track ----

    def mark(self, m: dict) -> str:
        if m.get("status") not in STATUSES:
            return f"status must be one of {', '.join(STATUSES)}"
        try:
            set_status(int(m["lead_id"]), m["status"], m.get("note") or "")
        except KeyError:
            return f"No lead #{m['lead_id']}."
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
            if self._draft_followup(lead, lead["followups"] + 1, cfg):
                lines.append(f"Follow-up email to {lead['name']} is ready in Waiting for your OK.")
            else:
                lines.append(f"Follow up with {lead['name']} ({lead['contact']}): a short, friendly nudge, no pressure.")
        if not lines:
            return "No follow-ups due."
        text = "\n".join(lines)
        relay.notify(text)
        return text

    def _draft_followup(self, lead: dict, n: int, cfg: dict) -> bool:
        """Draft a follow-up email for approval. False means Steven follows up by hand (no email, no Gmail, no Claude)."""
        to = mailer.address_in(lead["contact"])
        if not (to and mailer.configured() and llm.HAS_LLM and not mailer.blocked(to)):
            return False
        subject = mailer.split_pitch(lead["pitch"])[0]
        facts = (f"Creator: {lead['name']}\nThis is follow-up number {n}.\nOriginal email:\n{lead['pitch']}\n"
                 f"Opt-out line: {cfg.get('opt_out_line')}\nSign as: {cfg.get('sender_name')}\n"
                 + ("The original offered a free sample clip." if cfg.get("free_sample") else "No free sample was offered."))
        try:
            message = llm.ask_json(model_for("pitch"), FOLLOWUP_SYSTEM, facts, FOLLOWUP_SCHEMA, effort="low",
                                   agent="Pitch")["message"]
        except Exception:
            return False
        text = f"Subject: {subject if subject.lower().startswith('re:') else 'Re: ' + subject}\n\n{message}"
        approvals.request("Pitch", "followup", f"Follow-up {n} to {lead['name']} ({lead['platform']})",
                          f"Pressing Send follow-up emails this from {mailer.credentials()[0]} to {to}.\n\n{text}",
                          {"lead_id": lead["id"], "n": n, "pitch": text}, yes="Send follow-up", no="Skip")
        return True

    def report(self) -> str:
        counts = {r["status"]: r["n"] for r in db.rows("SELECT status, COUNT(*) n FROM leads GROUP BY status")}
        if not counts:
            return "No leads yet."
        return "Leads: " + ", ".join(f"{n} {s}" for s, n in counts.items()) + (f". {sample.summary()}" if sample.summary() else "")
