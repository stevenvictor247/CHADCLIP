"""How far along is an idea Steven pressed Build it on?

Free: reads this public repo's pull requests on GitHub (no key, no Claude spend). The build session is told to put
"Idea #N" in its pull request, so the PR is found by that. Stages and the share of the bar they fill:
sent 10, building 30, PR open 55, tests running 70, tests passed 85, merged 92, live on this PC 100.
"""

import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone

from . import db, update

REPO = "stevenvictor247/CHADCLIP"
TTL = 120          # seconds a GitHub answer is reused, so the Ideas tab can refresh often without hammering GitHub
TOO_LONG_MIN = 90  # a build with no pull request after this long probably needs a look
_cache: dict = {}


def _get(path: str):
    hit = _cache.get(path)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/{path}", headers={
        "Accept": "application/vnd.github+json", "User-Agent": "agent-hq"})
    with urllib.request.urlopen(req, timeout=6) as r:
        data = json.loads(r.read().decode())
    _cache[path] = (time.time(), data)
    return data


def _when(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def find_pr(idea_id: int, since: datetime) -> dict | None:
    """The newest pull request opened since the build was sent that names this idea."""
    pat = re.compile(rf"\bidea\s*#{idea_id}\b", re.I)
    for p in _get("pulls?state=all&sort=created&direction=desc&per_page=30"):
        made = _when(p.get("created_at"))
        if made and made >= since and pat.search((p.get("title") or "") + "\n" + (p.get("body") or "")):
            return p
    return None


def tests_state(sha: str) -> str:
    """'passed', 'failed' or 'running' for a commit's checks."""
    runs = _get(f"commits/{sha}/check-runs?per_page=50").get("check_runs", [])
    if any(r.get("conclusion") in ("failure", "timed_out", "cancelled", "action_required") for r in runs):
        return "failed"
    if runs and all(r.get("status") == "completed" for r in runs):
        return "passed"
    return "running"


def is_live(sha: str | None) -> bool:
    """True once this PC's HQ code includes the merged change (HQ updates itself from GitHub)."""
    if not sha or not update.is_git_copy():
        return False
    try:
        return update._run("git", "merge-base", "--is-ancestor", sha, "HEAD").returncode == 0
    except Exception:
        return False


def _out(key: str, pct: int, label: str, detail: str, pr: dict | None = None, bad: bool = False) -> dict:
    return {"key": key, "pct": pct, "label": label, "detail": detail, "bad": bad,
            "pr_url": (pr or {}).get("html_url"), "pr_number": (pr or {}).get("number")}


def progress(idea: dict) -> dict | None:
    """Stage of a sent idea, or None when it hasn't been sent to Claude."""
    if idea.get("build_status") != "started":
        return None
    sent = _when(idea.get("build_at")) or datetime.now(timezone.utc)
    mins = max(0, int((datetime.now(timezone.utc) - sent).total_seconds() // 60))
    try:
        pr = find_pr(idea["id"], sent)
        if not pr:
            if mins < 2:
                return _out("sent", 10, "Sent to Claude", "Claude is starting the build session.")
            if mins >= TOO_LONG_MIN:
                return _out("building", 30, "Building", f"No pull request after {mins} minutes. Check its session under "
                            "Code on claude.ai.", bad=True)
            return _out("building", 30, "Building", f"Claude is writing the code ({mins} min so far).")
        if pr.get("merged_at"):
            if is_live(pr.get("merge_commit_sha")):
                return _out("live", 100, "Live on this PC", "Built, tested and part of your HQ now.", pr)
            return _out("merged", 92, "Merged", "Approved and merged. It reaches this PC the next time HQ updates "
                        "(open the Agent HQ icon).", pr)
        if pr.get("state") == "closed":
            return _out("closed", 55, "PR closed", "The pull request was closed without merging.", pr, bad=True)
        t = tests_state(pr["head"]["sha"])
        if t == "failed":
            return _out("tests", 70, "Tests failed", "Claude's pull request has a failing test and needs a fix.", pr, bad=True)
        if t == "passed":
            return _out("passed", 85, "Tests passed", "Waiting for Claude to merge it.", pr)
        return _out("tests", 70, "Testing", "The pull request is open and its tests are running.", pr)
    except Exception as e:   # GitHub unreachable or rate-limited: say so rather than guess
        return _out("unknown", 30, "Building", f"Couldn't check GitHub just now ({type(e).__name__}).")


def add_to(ideas: list[dict]) -> list[dict]:
    """Attach .progress to every sent idea; an idea that went live is marked built."""
    for i in ideas:
        if i["status"] == "approved":
            i["progress"] = progress(i)
            if i["progress"] and i["progress"]["key"] == "live":
                db.execute("UPDATE ideas SET status = 'built', decided_at = ? WHERE id = ?", db.now(), i["id"])
                db.log("Muse", f"\"{i['title']}\" is built and live")
                i["status"] = "built"
    return ideas
