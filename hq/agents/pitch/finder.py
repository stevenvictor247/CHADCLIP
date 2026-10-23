"""Finds a creator's public business email beyond their Twitch bio.

Only public pages the creator links themselves: links in their Twitch bio, link-in-bio pages (Linktree and the like),
their own website's contact page, and (with YOUTUBE_API_KEY in .env) their YouTube channel description. It obeys
robots.txt, never fetches X, Instagram, TikTok or Facebook (their terms forbid scraping), and never logs in anywhere.
Results, including "nothing found", are cached so a creator is only looked up once in a while.
"""

import ipaddress
import os
import re
import socket
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from ... import db

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
OBFUSCATED = re.compile(r"([A-Za-z0-9._%+-]+)\s*[\[(]\s*at\s*[\])]\s*([A-Za-z0-9-]+(?:\s*[\[(]?\s*dot\s*[\])]?\s*[A-Za-z0-9-]+)+)", re.I)
DOT = re.compile(r"\s*[\[(]?\s*dot\s*[\])]?\s*", re.I)
HREF = re.compile(r"""href\s*=\s*["']([^"'#][^"']*)["']""", re.I)
AGENT = "ChadclipContactFinder/1.0 (+public contact pages only)"

# Their terms forbid scraping, or the pages need a login. Never fetched.
BLOCKED_HOSTS = ("twitter.com", "x.com", "instagram.com", "tiktok.com", "facebook.com", "fb.com", "threads.net",
                 "twitch.tv", "discord.gg", "discord.com", "reddit.com", "linkedin.com", "snapchat.com")
YOUTUBE_HOSTS = ("youtube.com", "youtu.be")
# Link-in-bio pages: fetched, and the creator's own sites linked from them are followed one level.
AGGREGATORS = ("linktr.ee", "beacons.ai", "carrd.co", "bio.link", "lnk.bio", "allmylinks.com", "solo.to", "linktree.com",
               "campsite.bio", "taplink.cc")
JUNK_LOCAL = ("noreply", "no-reply", "donotreply", "sentry", "postmaster", "abuse", "privacy", "support@twitch")
JUNK_DOMAINS = ("sentry.io", "wixpress.com", "twitch.tv", "twitter.com", "youtube.com", "google.com",
                "domain.com", "email.com")
JUNK_SUFFIX = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")
CONTACT_PATHS = ("/contact", "/about", "/business")

URL = re.compile(r"(?:https?://|www\.|(?:%s)/)[^\s<>\"')\]]+" % "|".join(re.escape(a) for a in AGGREGATORS), re.I)
MAX_BYTES = 400_000
CACHE_DAYS = 30
MISS_DAYS = 7
MAX_FETCHES = 6  # pages fetched per creator


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _in(host: str, domains) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _public_host(host: str) -> bool:
    """Refuse addresses on the user's own network, in case a bio links to one."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return bool(infos) and not any(not ipaddress.ip_address(i[4][0]).is_global for i in infos)


_robots: dict = {}


def _allowed(url: str) -> bool:
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    rp = _robots.get(base)
    if rp is None:
        rp = RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", headers={"User-Agent": AGENT}, timeout=10)
            if r.status_code in (401, 403):
                rp.disallow_all = True
            elif r.status_code >= 400:
                rp.allow_all = True
            else:
                rp.parse(r.text.splitlines())
        except requests.RequestException:
            rp.disallow_all = True  # can't tell, so don't
        _robots[base] = rp
    return rp.can_fetch(AGENT, url)


def _get(url: str) -> str | None:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname or _in(_host(url), BLOCKED_HOSTS):
        return None
    if not _public_host(p.hostname) or not _allowed(url):
        return None
    try:
        r = requests.get(url, headers={"User-Agent": AGENT}, timeout=15, stream=True)
        ctype = r.headers.get("content-type", "")
        if r.status_code != 200 or ("html" not in ctype and "text" not in ctype):
            return None
        final = r.url  # a redirect could leave for a blocked or private host
        if _in(_host(final), BLOCKED_HOSTS) or not _public_host(urlparse(final).hostname or ""):
            return None
        return r.raw.read(MAX_BYTES, decode_content=True).decode(r.encoding or "utf-8", errors="ignore")
    except (requests.RequestException, OSError):
        return None


def clean(email: str) -> str | None:
    e = email.strip().strip(".,;:").lower()
    local, _, domain = e.partition("@")
    if not domain or e.endswith(JUNK_SUFFIX) or _in(domain, JUNK_DOMAINS) or any(local.startswith(j) for j in JUNK_LOCAL):
        return None
    return e


def emails_in(text: str) -> list[str]:
    """Emails in a page, mailto links first, then plain text, then 'name [at] site [dot] com' spellings."""
    text = unescape(text)
    found = [m for m in re.findall(r"mailto:([^\"'?\s<>]+)", text, re.I)]
    found += EMAIL.findall(text)
    for user, dom in OBFUSCATED.findall(text):
        found.append(user + "@" + DOT.sub(".", dom))
    out = []
    for f in found:
        c = clean(f)
        if c and c not in out:
            out.append(c)
    return out


def urls_in(text: str) -> list[str]:
    out = []
    for u in URL.findall(text or ""):
        u = u.rstrip(".,;:!")
        u = u if u.lower().startswith("http") else "https://" + u
        if u not in out:
            out.append(u)
    return out


def _youtube(url: str) -> tuple[str, str] | None:
    """Email in a YouTube channel's public description, via the official API (needs YOUTUBE_API_KEY)."""
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        return None
    path = urlparse(url).path.strip("/").split("/")
    params = {"part": "snippet", "key": key}
    if path[0].startswith("@"):
        params["forHandle"] = path[0]
    elif path[0] == "channel" and len(path) > 1:
        params["id"] = path[1]
    else:
        return None
    try:
        r = requests.get("https://www.googleapis.com/youtube/v3/channels", params=params, timeout=15)
        r.raise_for_status()
        items = r.json().get("items") or []
    except (requests.RequestException, ValueError):
        return None
    desc = items[0]["snippet"].get("description", "") if items else ""
    found = emails_in(desc)
    return (found[0], url) if found else None


def _search(bio: str, extra_urls: list[str]) -> dict | None:
    hit = next(iter(emails_in(bio)), None)
    if hit:
        return {"email": hit, "source": "their Twitch bio", "url": ""}
    queue = [(u, 0) for u in list(dict.fromkeys(urls_in(bio) + extra_urls))]
    seen, fetches = set(), 0
    while queue and fetches < MAX_FETCHES:
        url, depth = queue.pop(0)
        host = _host(url)
        if url in seen or _in(host, BLOCKED_HOSTS):
            continue
        seen.add(url)
        if _in(host, YOUTUBE_HOSTS):
            if found := _youtube(url):
                return {"email": found[0], "source": "their YouTube channel description", "url": found[1]}
            continue
        fetches += 1
        html = _get(url)
        if not html:
            continue
        if found := emails_in(html):
            kind = "their link-in-bio page" if _in(host, AGGREGATORS) else "their website"
            return {"email": found[0], "source": kind, "url": url}
        if _in(host, AGGREGATORS):  # follow the creator's own links one level
            if depth == 0:
                for href in HREF.findall(html):
                    link = urljoin(url, href)
                    if link.startswith("http") and _host(link) != host and not _in(_host(link), BLOCKED_HOSTS):
                        queue.append((link, 1))
        elif depth < 2:  # their own site: try the usual contact pages
            root = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
            queue += [(root + p, 2) for p in CONTACT_PATHS]
    return None


def find_email(platform: str, handle: str, bio: str = "", extra_urls: list[str] | None = None) -> dict | None:
    """{'email', 'source', 'url'} for a public email the creator posted, or None. Cached, misses too."""
    handle = handle.lower()
    cached = db.rows("SELECT * FROM email_finds WHERE platform = ? AND handle = ?", platform, handle)
    if cached:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached[0]["found_at"])).days
        if age < (CACHE_DAYS if cached[0]["email"] else MISS_DAYS):
            c = cached[0]
            return {"email": c["email"], "source": c["source"], "url": c["url"]} if c["email"] else None
    try:
        result = _search(bio or "", extra_urls or [])
    except Exception:  # one odd page must never stop a find run
        result = None
    db.execute("INSERT OR REPLACE INTO email_finds (platform, handle, email, source, url, found_at) VALUES (?, ?, ?, ?, ?, ?)",
               platform, handle, result and result["email"], result and result["source"], result and result["url"], db.now())
    return result


def describe(found: dict) -> str:
    return f"Email found via {found['source']}" + (f" ({found['url']})" if found.get("url") else "")
