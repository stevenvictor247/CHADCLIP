"""Scout: reads clipping-campaign rules, rates them, and keeps score of what your clips earn."""

import json
import os

from ... import campaigns, creators, db, discovery, ledger, llm, relay
from ...config import model_for
from ..base import Agent
from ..chad import twitch

SYSTEM = """You are Scout, who vets paid clipping campaigns for Steven, a beginner who clips streamers' content
into TikToks, YouTube Shorts and Instagram Reels from his own clipping accounts.

You are given the text of a campaign (rules, pay, requirements). Pull out the facts exactly as written. Never guess a
number that isn't there: use null. Then rate the campaign from 0 to 10 for Steven:
- pay per 1,000 views (under $0.50 is poor, $1 to $3 is good),
- how much budget is left,
- how easy the rules are (required tags, minimum views, face-on-camera or original footage demands),
- whether source videos are provided,
- anything that looks like a scam or unpaid-work trap (asking for money up front, login details, vague payouts).
Write the verdict in two plain sentences a beginner understands."""

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Campaign name"},
        "creator": {"type": ["string", "null"], "description": "The streamer, brand or creator being clipped"},
        "platforms": {"type": "array", "items": {"type": "string"}, "description": "tiktok, youtube, instagram, x"},
        "rate_per_1k": {"type": ["number", "null"], "description": "US dollars per 1,000 views"},
        "budget_left_pct": {"type": ["number", "null"], "description": "Percent of the budget still unspent, 0 to 100"},
        "min_views": {"type": ["integer", "null"], "description": "Views a clip needs before it pays"},
        "max_payout": {"type": ["number", "null"], "description": "Most one clip can earn, dollars"},
        "required_tags": {"type": "array", "items": {"type": "string"}, "description": "Hashtags or mentions the rules require, without #"},
        "credit": {"type": ["string", "null"], "description": "Credit or tag line the rules want in captions"},
        "rules": {"type": "string", "description": "The important rules in 2 to 4 short sentences"},
        "clip_style": {"type": "string", "description": "What kind of moments the campaign wants"},
        "content_sources": {"type": "array", "items": {"type": "string"}, "description": "Video links provided for clipping"},
        "red_flags": {"type": "array", "items": {"type": "string"}},
        "score": {"type": "number", "description": "0 to 10 for Steven"},
        "verdict": {"type": "string"},
    },
    "required": ["name", "creator", "platforms", "rate_per_1k", "budget_left_pct", "min_views", "max_payout",
                 "required_tags", "credit", "rules", "clip_style", "content_sources", "red_flags", "score", "verdict"],
    "additionalProperties": False,
}


def describe(c: dict) -> str:
    """A short message about a campaign for the phone or the Boss."""
    pay = f"${c['rate_per_1k']:g} per 1,000 views" if c.get("rate_per_1k") is not None else "pay not stated"
    lines = [f"Campaign #{c['id']}: {c['name']} ({c.get('score') or '?'}/10)", pay, c.get("verdict") or ""]
    if c["flags"]:
        lines.append("Watch out: " + "; ".join(c["flags"]))
    return "\n".join(x for x in lines if x)


def _decide_campaign(ref: int, decision: str) -> str:
    return campaigns.decide(ref, "join" if decision == "approve" else "skip")


relay.DECIDERS["campaign"] = _decide_campaign


class Scout(Agent):
    def __init__(self):
        super().__init__(
            name="Scout",
            role="Campaign finder. Reads the rules of paid clipping campaigns you paste in, rates them, and once you "
                 "join one lets Chad clip for it. Tracks which posted clips still need submitting and what they earn.",
            params_help='{"text": "pasted campaign page or rules", "url": "campaign link", "sources": ["video links to clip"]} '
                        'to vet a campaign; {"add_sources": {"campaign_id": 1, "urls": ["..."]}}; {"sync": true} to list '
                        'posted clips that need submitting; {"record": {"submission_id": 1, "views": 5000, '
                        '"earned_usd": 7.5, "status": "paid"}}; {"report": true} for earnings so far.',
            schedule=[(6, "Find posted campaign clips that still need submitting.", {"sync": True}),
                      (6, "Look for new campaigns in the inbox and the feeds.", {"discover": True}),
                      (168, "Suggest creators worth clipping.", {"creators": 5})],
        )

    def run(self, task: dict) -> str:
        params = json.loads(task.get("params") or "{}")
        if params.get("discover"):
            return self.discover()
        if params.get("creators"):
            return self.find_creators(int(params["creators"]))
        if params.get("text"):
            return self.vet(params["text"], params.get("url"), params.get("sources") or [])
        if params.get("add_sources"):
            a = params["add_sources"]
            campaigns.add_sources(int(a["campaign_id"]), a.get("urls") or [])
            return f"Added {len(a.get('urls') or [])} source link(s) to campaign #{a['campaign_id']}."
        if params.get("record"):
            r = params["record"]
            campaigns.record(int(r["submission_id"]), r.get("views"), r.get("earned_usd"), r.get("status"))
            return f"Updated submission #{r['submission_id']}."
        if params.get("sync"):
            return self.sync()
        return self.report()

    def _rate(self, text: str, url: str | None, sources: list, source: str = "manual") -> int:
        data = llm.ask_json(model_for("scout"), SYSTEM, f"Campaign link: {url or 'not given'}\n\n{text[:20000]}",
                            SCHEMA, effort="low", agent="Scout")
        return campaigns.propose(data, url, sources, source)

    def vet(self, text: str, url: str | None, sources: list) -> str:
        if not llm.HAS_LLM:
            return "Scout needs ANTHROPIC_API_KEY set to read campaign rules."
        cid = self._rate(text, url, sources)
        c = campaigns.get(cid)
        db.log("Scout", f"Found campaign #{cid}: {c['name']} ({c['score']}/10)")
        relay.ask(describe(c) + "\n\nJoin it?", "campaign", cid, yes="✅ Join", no="⏭ Skip")
        return describe(c) + "\n\nApprove it on the dashboard (or on your phone) to let Chad start clipping."

    def discover(self) -> str:
        """Rate what's in the inbox and what the feeds list. Nothing is ever joined here: good ones wait for Steven."""
        if not llm.HAS_LLM:
            return "Scout needs ANTHROPIC_API_KEY set to rate campaigns."
        cap = int(os.getenv("SCOUT_MAX_PER_RUN", "10") or 10)
        min_score = float(os.getenv("SCOUT_MIN_SCORE", "6") or 6)
        found, notes = [], []

        def rate(text, url, source):
            if len(found) >= cap or ledger.over_budget():
                return False
            cid = self._rate(text, url, [], source)
            c = campaigns.get(cid)
            if c["budget_left_pct"] is not None and c["budget_left_pct"] < 20:
                campaigns.decide(cid, "skip")  # mostly spent: it may run dry before you're paid
                c = campaigns.get(cid)
            found.append(c)
            return True

        for item in discovery.inbox("queued"):
            key = item["url"] or item["text"]
            if discovery.seen(key):
                discovery.set_inbox(item["id"], "done", "already rated")
                continue
            text = item["text"]
            try:
                text = text or discovery.to_text(discovery.fetch(item["url"]))
            except Exception as e:
                reason = str(e) if isinstance(e, discovery.NotAllowed) else f"couldn't open it ({e})"
                discovery.set_inbox(item["id"], "needs_text", f"{reason}. Open the page yourself and paste its text here.")
                continue
            if not rate(text, item["url"], "inbox"):
                break  # cap or budget reached: the rest stay queued for the next run
            discovery.mark_seen(key)
            discovery.set_inbox(item["id"], "done")

        for feed in discovery.feed_urls():
            try:
                links = discovery.links_on(discovery.fetch(feed), feed)
            except Exception as e:
                notes.append(f"feed {feed}: {e}")
                continue
            for link in links:
                if discovery.seen(link) or campaigns.by_url(link):
                    continue
                try:
                    page = discovery.fetch(link)
                except Exception:
                    continue
                if not rate(discovery.to_text(page), link, "feed"):
                    break
                discovery.mark_seen(link)

        good = sorted((c for c in found if c["status"] == "proposed" and (c["score"] or 0) >= min_score),
                      key=lambda c: -(c["score"] or 0))
        for c in good[:3]:
            relay.ask(describe(c) + "\n\nJoin it?", "campaign", c["id"], yes="✅ Join", no="⏭ Skip")
        stuck = len(discovery.inbox("needs_text"))
        db.log("Scout", f"Discovery: rated {len(found)} new campaign(s), {len(good)} worth a look")
        text = f"Rated {len(found)} new campaign(s); {len(good)} scored {min_score:g}+ and wait for your Join decision."
        if stuck:
            text += f" {stuck} inbox link(s) need you to paste the page text."
        return " ".join([text] + notes)

    def find_creators(self, n: int) -> str:
        """Suggest streamers who are big right now and whose clips are getting views. Free: no Claude call."""
        if not (os.getenv("TWITCH_CLIENT_ID") and os.getenv("TWITCH_CLIENT_SECRET")):
            return "To suggest creators Scout needs the Twitch keys (TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET) on the Settings page."
        perms = twitch.permissions()
        found = []
        for s in twitch.top_streamers(50):
            if creators.known(s["login"]) or perms.get(s["login"].lower()):
                continue
            info = twitch.profile(s["id"])
            clips = twitch.top_clips(s["id"], days=1, limit=1)
            found.append({**s, "clip_views": clips[0]["views"] if clips else 0, "top_clip": clips[0]["title"] if clips else None,
                          "bio": info["bio"], "signals": creators.signals_for(info["bio"])})
        best = sorted(found, key=lambda c: -creators.rank(c))[:n]
        for c in best:
            creators.add(c)
        db.log("Scout", f"Suggested {len(best)} creator(s) to clip")
        if not best:
            return "No new creators to suggest right now."
        return f"Suggested {len(best)} creator(s): " + ", ".join(c["name"] for c in best) + \
               ". Check how each one lets clippers in, then record the permission on the dashboard."

    def sync(self) -> str:
        new = campaigns.sync_submissions()
        if not new:
            return "No new posted clips need submitting."
        names = {c["id"]: c["name"] for c in campaigns.all_campaigns()}
        lines = [f"{names.get(n['campaign_id'], 'campaign')}: {n['url'] or '(no link yet)'} on {n['platform']}" for n in new]
        text = f"{len(new)} posted clip(s) to submit to their campaigns:\n" + "\n".join(lines)
        relay.notify(text)
        return text

    def report(self) -> str:
        rows = campaigns.summary()
        if not rows:
            return "No campaigns yet. Paste a campaign's rules and Scout will vet it."
        return "; ".join(
            f"#{c['id']} {c['name']} ({c['status']}): {c['totals']['submissions']} clips, {c['totals']['views']:,} views, "
            f"${c['totals']['earned_usd']:.2f} earned (about ${c['totals']['expected_usd']:.2f} expected)" for c in rows)
