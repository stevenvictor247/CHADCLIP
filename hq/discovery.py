"""How Scout finds campaigns without breaking anyone's rules.

Three ways in:
- Web search: once a day Scout asks Claude to search the open web for open campaigns (Anthropic runs the search; Whop and
  Discord are excluded). Switch off with SCOUT_WEB_SEARCH=0.
- The inbox: Steven pastes campaign links or page text on the dashboard. Pasted text is rated as is. A pasted link
  is only fetched when its site allows it.
- Feeds: public pages or RSS feeds listed in SCOUT_FEED_URLS. Scout reads the campaign links on them.

Every fetch checks robots.txt first and identifies itself. Sites that forbid automated access in their terms
(BLOCKED_HOSTS) are never fetched: for those, paste the page text from your own browser instead.
"""

import hashlib
import html
import os
import re
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import requests

from . import db

USER_AGENT = "AgentHQ-Scout/1.0 (personal campaign finder; respects robots.txt)"
TIMEOUT = 20
MAX_BYTES = 1_500_000

# Terms of service ban automated access (Whop: "scraping our services without our written consent").
BLOCKED_HOSTS = {"whop.com": "Whop's terms forbid automated access",
                 "discord.com": "Discord forbids automated access with a personal account",
                 "discord.gg": "Discord forbids automated access with a personal account"}

_URL = re.compile(r"https?://[^\s<>\"')\]]+")
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


class NotAllowed(Exception):
    pass


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def blocked_reason(url: str) -> str | None:
    host = _host(url)
    for h, why in BLOCKED_HOSTS.items():
        if host == h or host.endswith("." + h):
            return why
    return None


def robots_allows(url: str) -> bool:
    """False when robots.txt forbids us. If robots.txt can't be read at all, the answer is no: be polite."""
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            if r.status_code in (404, 410):
                rp.allow_all = True
            elif r.ok:
                rp.parse(r.text.splitlines())
            else:
                rp = None
        except requests.RequestException:
            rp = None
        _robots[base] = rp
    rp = _robots[base]
    return bool(rp and rp.can_fetch(USER_AGENT, url))


def fetch(url: str) -> str:
    """The raw page. Raises NotAllowed with a plain-words reason when the site doesn't permit it."""
    if not url.lower().startswith(("http://", "https://")):
        raise NotAllowed("not a web link")
    why = blocked_reason(url)
    if why:
        raise NotAllowed(f"{why}, so Scout won't open it")
    if not robots_allows(url):
        raise NotAllowed("the site's robots.txt doesn't allow automated reading")
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, stream=True)
    r.raise_for_status()
    return r.raw.read(MAX_BYTES, decode_content=True).decode(r.encoding or "utf-8", errors="replace")


def to_text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    return re.sub(r"\s+", " ", html.unescape(page)).strip()


def links_on(page: str, base_url: str, limit: int = 30) -> list[str]:
    """Same-site links from an HTML page or an RSS/Atom feed."""
    found = re.findall(r"""(?is)<link>\s*(https?://[^<\s]+)\s*</link>|href=["']([^"'#]+)["']""", page)
    out = []
    for a, b in found:
        u = urljoin(base_url, html.unescape(a or b))
        if _host(u) == _host(base_url) and u.rstrip("/") != base_url.rstrip("/") and u not in out:
            out.append(u)
    return out[:limit]


def web_search_on() -> bool:
    return os.getenv("SCOUT_WEB_SEARCH", "1").strip().lower() not in ("0", "false", "no", "off")


def _today_key() -> str:
    return "websearch:" + db.now()[:10]


def web_search_due() -> bool:
    """Scout's own web search runs once a day, and only if it's switched on."""
    return web_search_on() and not seen(_today_key())


def mark_web_search_done() -> None:
    mark_seen(_today_key())


def feed_urls() -> list[str]:
    return [u.strip() for u in re.split(r"[,\s]+", os.getenv("SCOUT_FEED_URLS", "")) if u.strip()]


def split_paste(text: str) -> list[dict]:
    """Pasted text becomes inbox items. Only links, one per line: one item per link. Anything else: one item of text."""
    text = text.strip()
    if not text:
        return []
    leftover = _URL.sub("", text).strip()
    urls = list(dict.fromkeys(_URL.findall(text)))
    if urls and len(leftover) < 20 * len(urls):
        return [{"url": u.rstrip(".,;"), "text": None} for u in urls]
    return [{"url": urls[0].rstrip(".,;") if urls else None, "text": text}]


def add_to_inbox(text: str) -> int:
    items = split_paste(text)
    for i in items:
        db.execute("INSERT INTO scout_inbox (url, text, status, created_at) VALUES (?, ?, 'queued', ?)",
                   i["url"], i["text"], db.now())
    return len(items)


def inbox(status: str | None = None) -> list[dict]:
    if status:
        return db.rows("SELECT * FROM scout_inbox WHERE status = ? ORDER BY id", status)
    return db.rows("SELECT * FROM scout_inbox ORDER BY id DESC LIMIT 30")


def set_inbox(item_id: int, status: str, note: str | None = None) -> None:
    db.execute("UPDATE scout_inbox SET status = ?, note = ? WHERE id = ?", status, note, item_id)


def seen(key: str) -> bool:
    return bool(db.rows("SELECT 1 FROM scout_seen WHERE key = ?", _key(key)))


def mark_seen(key: str) -> None:
    db.execute("INSERT OR IGNORE INTO scout_seen (key, created_at) VALUES (?, ?)", _key(key), db.now())


def _key(s: str) -> str:
    return hashlib.sha1(s.strip().lower().encode()).hexdigest()
