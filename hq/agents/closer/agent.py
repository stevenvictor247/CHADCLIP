"""Closer: turns a streamer's reply to a pitch into a short quote with a payment link. You approve every message."""

import json

import yaml

from ... import approvals, db, llm, relay
from ...config import CONFIG_DIR, model_for
from ..base import Agent
from ..pitch import agent as pitch_agent, mailer

TIERS = ("starter", "weekly", "monthly")

REPLY_SYSTEM = """You write the opening of a reply from Steven, a clipper, to a streamer who answered his pitch email.
1 to 2 short lines, friendly and plain. Answer what they actually said, using only what their reply says. Never invent
facts, results or promises, and never mention a price (the quote comes right after your lines). No greeting and no
sign-off: they are added for you."""

REPLY_SCHEMA = {"type": "object", "properties": {"message": {"type": "string"}},
                "required": ["message"], "additionalProperties": False}


def settings() -> dict:
    path = CONFIG_DIR / "closer.yaml"
    return (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}


def _blocker(cfg: dict, tier: str) -> str | None:
    """Free checks before any tokens: is this tier fully filled in?"""
    t = (cfg.get("tiers") or {}).get(tier)
    if not t:
        return f"There is no '{tier}' tier in config/closer.yaml (use {', '.join(TIERS)})."
    link = str(t.get("payment_link") or "").strip()
    if not link.startswith("https://"):
        return f"Paste your Stripe payment link for the {tier} tier into config/closer.yaml first (it must start with https://)."
    try:
        if not float(t["price_usd"]) > 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return f"The {tier} tier in config/closer.yaml needs a price above $0."
    return None


def money(x) -> str:
    x = float(x)
    return f"${x:,.0f}" if x == int(x) else f"${x:,.2f}"


def build_quote(cfg: dict, tier: str, lead: dict, opener: str = "") -> str:
    """The email, from the template alone. Same stored shape as a pitch: 'Subject: ...', blank line, message."""
    t = cfg["tiers"][tier]
    sender = str(pitch_agent.settings().get("sender_name") or "").strip() or "Steven"
    first = (lead["name"] or "there").split()[0]
    lines = [f"Hi {first},", ""]
    if opener.strip():
        lines += [opener.strip(), ""]
    lines += [f"Here's the {t['label'].lower()}: {money(t['price_usd'])} {t['period']}.",
              f"You get {t['includes']}.", ""]
    if tier != "starter" and (s := (cfg.get("tiers") or {}).get("starter")):
        lines += [f"Want to see it first? The {s['label'].lower()} is {money(s['price_usd'])} for {s['period']}.", ""]
    lines += [f"You can pay here whenever you're ready: {t['payment_link'].strip()}", "",
              "Reply with any questions and I'll answer them today.", "", sender]
    return f"Subject: Your clip quote, {first}\n\n" + "\n".join(lines)


def _quote_row(lead_id: int) -> dict | None:
    rows = db.rows("SELECT * FROM quotes WHERE lead_id = ? AND status IN ('pending', 'sent') ORDER BY id DESC LIMIT 1", lead_id)
    return rows[0] if rows else None


def _unsent(lead: dict, quote: dict, why: str) -> str:
    approvals.request("Closer", "quote", f"Quote to {lead['name']}: NOT SENT",
                      f"Not sent: {why}\nContact: {lead['contact']}\n\n{quote['body']}",
                      {"quote_id": quote["id"], "email": True}, yes="Try again", no="Drop")
    return f"Not sent: {why} I put {lead['name']}'s quote back in Waiting for your OK."


def _handle_quote_decision(payload: dict, decision: str) -> str:
    quote = db.rows("SELECT * FROM quotes WHERE id = ?", payload["quote_id"])[0]
    lead = db.rows("SELECT * FROM leads WHERE id = ?", quote["lead_id"])[0]
    if decision == "reject":
        db.execute("UPDATE quotes SET status = 'dropped' WHERE id = ? AND status = 'pending'", quote["id"])
        return f"Dropped the quote to {lead['name']}."
    if quote["status"] != "pending":
        return f"That quote is already {quote['status']}, so nothing was sent."
    to = mailer.address_in(lead["contact"])
    if not (to and mailer.configured() and payload.get("email")):
        db.execute("UPDATE quotes SET status = 'sent', sent_at = ? WHERE id = ?", db.now(), quote["id"])
        text = f"Send this to {lead['name']} ({lead['platform']}). Contact: {lead['contact']}\n\n{quote['body']}"
        relay.notify(text)
        return f"Marked as sent. Copy it and send it yourself.\n\n{text}"
    if mailer.blocked(to):
        db.execute("UPDATE leads SET status = 'do_not_contact', updated_at = ? WHERE id = ?", db.now(), lead["id"])
        db.execute("UPDATE quotes SET status = 'dropped' WHERE id = ?", quote["id"])
        return f"{to} is on your do-not-contact list, so nothing was sent."
    cfg = pitch_agent.settings()
    blocker = pitch_agent._email_blocker(cfg)
    if blocker:
        return _unsent(lead, quote, blocker)
    with db.connect() as c:   # claim it first, so a double tap can never send twice
        claimed = c.execute("UPDATE quotes SET status = 'sending' WHERE id = ? AND status = 'pending'", (quote["id"],)).rowcount == 1
    if not claimed:
        return f"{lead['name']}'s quote is already being handled, so nothing was sent."
    try:
        mailer.send(mailer.build(cfg, to, quote["body"]))
    except mailer.SendError as e:
        db.execute("UPDATE quotes SET status = 'pending' WHERE id = ?", quote["id"])
        return _unsent(lead, quote, str(e))
    except Exception as e:
        db.execute("UPDATE quotes SET status = 'pending' WHERE id = ?", quote["id"])
        return _unsent(lead, quote, f"something went wrong ({e.__class__.__name__}).")
    db.execute("UPDATE quotes SET status = 'sent', sent_at = ? WHERE id = ?", db.now(), quote["id"])
    db.log("Closer", f"Emailed a {quote['tier']} quote to {lead['name']} at {to}")
    return f"Emailed the {quote['tier']} quote to {lead['name']} at {to}."


approvals.HANDLERS["quote"] = _handle_quote_decision


def won_count() -> int:
    return db.rows("SELECT COUNT(*) n FROM leads WHERE status = 'won'")[0]["n"]


def _waiting() -> list[dict]:
    """Replied leads with no live quote yet: a plain database look, no tokens."""
    return db.rows("SELECT * FROM leads WHERE status = 'replied' AND id NOT IN "
                   "(SELECT lead_id FROM quotes WHERE status IN ('pending', 'sending', 'sent')) ORDER BY id")


class Closer(Agent):
    def __init__(self):
        super().__init__(
            name="Closer",
            role="Turns a yes into a paying client. When a pitched streamer replies, drafts a short quote from your "
                 "templates (first-week trial, weekly or monthly) with your Stripe payment link. You approve every message.",
            params_help='No params: draft a quote for each replied lead that has none. {"quote": {"lead_id": 1, "tier": '
                        '"starter|weekly|monthly", "reply": "what they wrote, optional"}} for one lead; '
                        '{"won": 1} when lead #1 has paid; {"report": true}. Prices and payment links live in config/closer.yaml.',
            schedule=[(24, "Draft quotes for leads who replied to a pitch.", {})],
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        if not params:
            return not _waiting()
        return None

    def run(self, task: dict) -> str:
        params = json.loads(task.get("params") or "{}")
        if params.get("won"):
            return self.won(int(params["won"]))
        if params.get("quote"):
            q = params["quote"]
            return self.quote(int(q["lead_id"]), q.get("tier"), q.get("reply") or "")
        if params.get("report"):
            return self.report()
        waiting = _waiting()
        if not waiting:
            return "No replied leads are waiting for a quote."
        return "\n".join(self.quote(l["id"]) for l in waiting)

    def quote(self, lead_id: int, tier: str | None = None, reply: str = "") -> str:
        rows = db.rows("SELECT * FROM leads WHERE id = ?", lead_id)
        if not rows:
            return f"No lead #{lead_id}."
        lead = rows[0]
        if lead["status"] != "replied":
            return f"{lead['name']} is {lead['status']}, not replied, so no quote was drafted."
        if _quote_row(lead_id) or db.rows("SELECT 1 FROM quotes WHERE lead_id = ? AND status = 'sending'", lead_id):
            return f"{lead['name']} already has a quote."
        cfg = settings()
        tier = (tier or cfg.get("default_tier") or "starter").lower()
        if problem := _blocker(cfg, tier):
            return problem
        opener = ""
        if reply.strip() and llm.HAS_LLM:   # Claude only writes the short reply to what they said; the quote is the template
            try:
                opener = llm.ask_json(model_for("closer"), REPLY_SYSTEM, f"Creator: {lead['name']}\nTheir reply:\n{reply.strip()[:1500]}",
                                      REPLY_SCHEMA, effort="low", agent="Closer")["message"]
            except Exception:
                opener = ""
        body = build_quote(cfg, tier, lead, opener)
        qid = db.execute("INSERT INTO quotes (lead_id, tier, price_usd, link, body, status, created_at) "
                         "VALUES (?, ?, ?, ?, ?, 'pending', ?)", lead_id, tier, float(cfg["tiers"][tier]["price_usd"]),
                         cfg["tiers"][tier]["payment_link"].strip(), body, db.now())
        to = mailer.address_in(lead["contact"])
        by_email = bool(to and mailer.configured())
        how = f"Pressing Send email sends this from {mailer.credentials()[0]} to {to}.\n" if by_email else ""
        approvals.request("Closer", "quote", f"{tier.title()} quote to {lead['name']} ({money(cfg['tiers'][tier]['price_usd'])})",
                          f"{how}Contact: {lead['contact']}\n\n{body}", {"quote_id": qid, "email": by_email},
                          yes="Send email" if by_email else "I'll send it", no="Drop")
        return f"{lead['name']}: {tier} quote is ready in Waiting for your OK."

    def won(self, lead_id: int) -> str:
        rows = db.rows("SELECT name FROM leads WHERE id = ?", lead_id)
        if not rows:
            return f"No lead #{lead_id}."
        pitch_agent.set_status(lead_id, "won", "Paid")
        db.log("Closer", f"{rows[0]['name']} is a paying client")
        return f"{rows[0]['name']} is now a won client. Log the payment as income in the money strip."

    def report(self) -> str:
        n = {r["status"]: r["c"] for r in db.rows("SELECT status, COUNT(*) c FROM quotes GROUP BY status")}
        return (f"Won clients: {won_count()}. Replied and waiting for a quote: {len(_waiting())}. Quotes: "
                + (", ".join(f"{c} {s}" for s, c in n.items()) or "none yet") + ".")
