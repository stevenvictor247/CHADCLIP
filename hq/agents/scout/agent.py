"""Scout: reads clipping-campaign rules, rates them, and keeps score of what your clips earn."""

import json
import os
import re

from ... import campaigns, creators, db, discovery, ledger, llm, relay
from ...config import model_for
from ..base import Agent
from ..chad import twitch

SYSTEM = """You are Scout, who vets paid clipping campaigns for Steven, a beginner who clips streamers' content
into TikToks, YouTube Shorts and Instagram Reels from his own clipping accounts.

You are given the text of a campaign (rules, pay, requirements). Pull out the facts exactly as written. Never guess a
number that isn't there: use null. Then score the campaign from 0 to 10 for Steven. Only a campaign that is clearly
worth his time scores 8 or more; be strict. Weigh these seven things:
- payout rate per 1,000 views (under $0.50 is poor, $1 to $3 is good),
- clear rules (required tags, minimum views, face-on-camera or original footage demands; vague rules score low),
- a reliable payer (a named creator, agency or brand with a stated payout process; vague or unproven payouts and
  anything that asks for money or login details up front is a scam risk and caps the score at 4),
- fit with Chad: the campaign itself is the permission to clip, so it must say clipping that creator's content is
  allowed and ideally provide source videos,
- effort: how hard a good clip is to make,
- competition: how many clippers likely share the budget,
- deadline and budget left (a nearly spent or soon-ending campaign scores low).
Give score_reasons: one short plain line per thing above, each starting with its name and a verdict, e.g.
"Payout: $2 per 1,000 views, good". Write the verdict in two plain sentences a beginner understands."""

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
        "score_reasons": {"type": "array", "items": {"type": "string"},
                          "description": "One short line each for payout, rules, payer, fit, effort, competition, deadline"},
        "verdict": {"type": "string"},
    },
    "required": ["name", "creator", "platforms", "rate_per_1k", "budget_left_pct", "min_views", "max_payout",
                 "required_tags", "credit", "rules", "clip_style", "content_sources", "red_flags", "score", "score_reasons",
                 "verdict"],
    "additionalProperties": False,
}


SEARCH_SYSTEM = """You are Scout's researcher. You search the open web for paid clipping campaigns that Steven, a beginner, could
clip for: a streamer, creator or brand pays people per 1,000 views of short clips posted to their own TikTok, YouTube
Shorts or Instagram accounts.

Find campaigns that are open right now and publicly described on a page anyone can read without logging in: a
creator's or agency's own site, a public sign-up page, a news or blog roundup that links the real page. Search a few
different ways (streamer clipping programs, "clipper" pay per view programs, brand clipping campaigns).

Skip anything that asks for money, a deposit or login details up front, promises vague or guaranteed riches, or has no
stated pay. Never invent a campaign, a link or a number. For each one give the page link exactly as found, the
campaign name, and an excerpt copied as written from the page or search result (rules, pay per 1,000 views, budget).
It is fine to return few or none.

Finish with one JSON object and nothing after it, shaped exactly like this:
{"candidates": [{"name": "...", "url": "...", "excerpt": "..."}]}"""

SEARCH_PROMPT = "Find up to {n} open paid clipping campaigns. Return only ones you actually found, with their real page links."

SEARCH_TURNS = 4   # a long search can pause; this many resumes at most
SEARCH_USES = 6    # web searches per run, about 6 cents


def describe(c: dict) -> str:
    """A short message about a campaign for the phone or the Boss."""
    pay = f"${c['rate_per_1k']:g} per 1,000 views" if c.get("rate_per_1k") is not None else "pay not stated"
    lines = [f"Campaign #{c['id']}: {c['name']} ({c.get('score') or '?'}/10)", pay, c.get("verdict") or ""]
    lines += [f"• {r}" for r in c.get("score_reasons") or []]
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
                      (6, "Look for new campaigns in the inbox and the feeds.", {"discover": True})],
        )

    def nothing_to_do(self, instructions: str, params: dict) -> bool | None:
        """Free looks in code before a scheduled round is queued: no posted clip waiting to be logged, or nothing in
        the inbox and no feeds to read, means no task at all."""
        if params == {"sync": True}:
            return not campaigns.has_unsynced_posts()
        if params == {"discover": True}:
            if not llm.HAS_LLM:
                return True
            if discovery.inbox("queued"):
                return False   # links waiting to be rated
            if discovery.web_search_due():
                return False   # the daily web search hasn't run yet today
            return None if discovery.feed_urls() else True   # feeds may or may not have new links: back off if empty
        return None

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
        min_score = campaigns.min_score()
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

        if discovery.web_search_due() and len(found) < cap and not ledger.over_budget():
            try:
                for cand in self._search():
                    if discovery.seen(cand["url"]) or campaigns.by_url(cand["url"]):
                        continue
                    text, how = self._read_candidate(cand)
                    if not rate(text, cand["url"], how):
                        break
                    discovery.mark_seen(cand["url"])
            except Exception as e:
                notes.append(f"web search: {str(e)[:200]}")
            discovery.mark_web_search_done()

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

    def _search(self) -> list[dict]:
        """Ask Claude to search the web for open campaigns. Anthropic runs the searches, so no site is scraped by HQ;
        Whop and Discord are excluded from the results. Returns candidates with a link and an excerpt."""
        cap = int(os.getenv("SCOUT_MAX_PER_RUN", "10") or 10)
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": SEARCH_USES,
                  "blocked_domains": sorted(discovery.BLOCKED_HOSTS)}]
        messages = [{"role": "user", "content": SEARCH_PROMPT.format(n=cap)}]
        for _ in range(SEARCH_TURNS):
            # No output schema: web search results always carry citations, which structured outputs can't combine with.
            response = llm.create(model_for("scout_search"), SEARCH_SYSTEM, messages, tools=tools, effort="low",
                                  agent="Scout")
            if response.stop_reason != "pause_turn":
                break
            messages = messages + [{"role": "assistant", "content": response.content}]  # the API resumes by itself
        out = []
        for c in self._candidates_in(llm.text_of(response)):
            url = (c.get("url") or "").strip()
            if url.lower().startswith(("http://", "https://")) and not discovery.blocked_reason(url) and c.get("excerpt"):
                out.append({**c, "url": url})
        return out[:cap]

    @staticmethod
    def _candidates_in(text: str) -> list[dict]:
        """The candidates object the search answer ends with. Anything before it is ignored; unreadable means none."""
        decoder = json.JSONDecoder()
        for start in [m.start() for m in re.finditer(r"\{\s*\"candidates\"", text)][::-1]:
            try:
                data, _ = decoder.raw_decode(text[start:])
            except ValueError:
                continue
            found = data.get("candidates") if isinstance(data, dict) else None
            return [c for c in found if isinstance(c, dict)] if isinstance(found, list) else []
        return []

    @staticmethod
    def _read_candidate(cand: dict) -> tuple[str, str]:
        """The page itself when its site allows it (robots.txt, no blocked hosts), otherwise the excerpt the search
        found. The second kind is marked, so Steven knows the rules weren't read from the page."""
        try:
            return discovery.to_text(discovery.fetch(cand["url"])), "web"
        except Exception:
            return "From a web search result, not the full page:\n" + cand["excerpt"], "web (excerpt only)"

    def find_creators(self, n: int) -> str:
        """Suggest streamers who are big right now and whose clips are getting views. Free: no Claude call."""
        if not (os.getenv("TWITCH_CLIENT_ID") and os.getenv("TWITCH_CLIENT_SECRET")):
            return "To suggest creators Scout needs the Twitch keys (TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET) on the Settings page."
        perms = twitch.permissions()
        pitched = {r["handle"].lower() for r in db.rows("SELECT handle FROM leads WHERE platform = 'twitch'")}
        found = []
        for s in twitch.top_streamers(50):
            if creators.known(s["login"]) or perms.get(s["login"].lower()) or s["login"].lower() in pitched:
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
