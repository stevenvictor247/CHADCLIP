"""The Settings page: every setting HQ reads, so nobody has to edit .env or config files by hand.

The list of settings comes from .env.example (its comments become the help text), so a new agent's settings
show up here as soon as they're added there. Values are saved to data/settings.json, outside git.
"""

import json
import os
import re

import yaml

from . import config
from .config import CONFIG_DIR, ROOT, SETTINGS_PATH

_KEY = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=(.*)$")
_SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
_HELP_ONLY = ("Copy to .env", "Uncomment to change")  # .env.example lines meant for people editing the file


def is_secret(key: str) -> bool:
    return any(w in key for w in _SECRET_WORDS)


def _sections() -> list[dict]:
    """Read .env.example into sections of {key, help, example}. A blank line starts a new section."""
    sections, help_lines, current = [], [], None
    path = ROOT / ".env.example"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for line in lines + [""]:
        line = line.strip()
        m = _KEY.match(line)
        if not line:
            current, help_lines = None, []
        elif m:
            if current is None:
                current = {"title": "", "fields": []}
                sections.append(current)
            text = " ".join(h for h in help_lines if not h.startswith(_HELP_ONLY))
            current["fields"].append({"key": m.group(1), "help": text, "example": m.group(2).strip()})
            help_lines = []
        elif line.startswith("#"):
            help_lines.append(line.lstrip("# ").strip())
    for s in sections:
        s["title"] = s["fields"][0]["help"].split(". ")[0].split(": ")[0][:80] if s["fields"][0]["help"] else s["fields"][0]["key"]
    return sections


# The Settings page groups every setting under the agent it belongs to, one collapsible bar each.
# (id, icon, title, blurb, exact keys, key prefixes). A key matching no group lands in General.
GROUPS = [
    ("general", "⚙️", "General and budget", "Your Claude key, the daily spending limit, Pause All, password and backups.",
     ("ANTHROPIC_API_KEY", "HQ_DAILY_BUDGET", "HQ_PAUSED", "HQ_PASSWORD", "HQ_BACKUP_COPY_DIR", "HQ_MODEL_REPORT"), ()),
    ("boss", "🎩", "Boss", "The Boss's brain, daily report, phone chat (Telegram) and the Build it button.",
     ("HQ_MODEL_BOSS", "HQ_BOSS_MODEL", "HQ_REPORT_HOUR", "HQ_BUILD_TOKEN", "HQ_BUILD_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_OWNER_ID"), ()),
    ("chad", "🎬", "Chad (clips and posting)", "How many posts a day, approval, practice mode, and your TikTok, Instagram, YouTube and Twitch accounts.",
     ("HQ_MODEL_CHAD", "HQ_MAX_POSTS_PER_DAY", "HQ_MAX_CLIPS_PER_DAY", "HQ_POST_GAP_MINUTES", "HQ_REQUIRE_APPROVAL", "HQ_PRACTICE_POSTING", "HQ_WHISPER_MODEL",
      "HQ_PUBLIC_BASE_URL"), ("IG_", "TIKTOK_", "TWITCH_")),
    ("pitch", "✉️", "Pitch (finding clients)", "Your Gmail for sending, and the pitch wording and limits.",
     ("HQ_MODEL_PITCH",), ("PITCH_",)),
    ("scout", "🔭", "Scout (finding campaigns)", "Where Scout looks and how picky it is.", ("HQ_MODEL_SCOUT",), ("SCOUT_",)),
    ("tally", "💰", "Tally (money)", "Which Claude model Tally uses.", ("HQ_MODEL_TALLY",), ()),
    ("sweep", "🧹", "Sweep (janitor and quality control)", "Daily report time, clean-up and warning limits.", ("HQ_MODEL_SWEEP",), ("HQ_SWEEP_",)),
    ("muse", "💡", "Muse (Creative Director)", "How often Muse brainstorms, what it may spend, and how bold it is.", (), ("HQ_MUSE", "HQ_MODEL_MUSE")),
    ("recruiter", "🧲", "Recruiter (finds new agents)", "How many agent proposals a day, what Recruiter may spend, and how picky it is.", (), ("HQ_RECRUITER", "HQ_MODEL_RECRUITER")),
    ("football", "🏈", "Warrior Village (football)", "Football folders, budget, reminders and the Thursday print.",
     ("HQ_MODEL_CAPTAIN", "HQ_DEPTH_HOUR", "HQ_SCOUTING_HOUR"), ("HQ_FOOTBALL_", "HQ_PRINT_", "HQ_PRINTER")),
    ("etsy", "🛍️", "Etsy Village (shirts)", "Printify connection, shirt pace, review, budget and the optional image key.",
     ("HQ_MODEL_ETTA", "HQ_MODEL_RADAR", "HQ_MODEL_QUILL"), ("HQ_ETSY_", "HQ_PRINTIFY_", "HQ_OPENAI")),
]

# Plain-English names for the settings people look for most. Anything not listed shows its setting name.
LABELS = {
    "HQ_MAX_POSTS_PER_DAY": "Posts per day (each account)",
    "HQ_MAX_CLIPS_PER_DAY": "New clips per day (Chad, 4 or more)",
    "HQ_POST_GAP_MINUTES": "Minutes between posts",
    "HQ_DAILY_BUDGET": "Daily Claude spending limit ($)",
    "HQ_REQUIRE_APPROVAL": "Wait for my approval before posting",
    "HQ_PAUSED": "Pause All",
    "HQ_REPORT_HOUR": "Daily report hour",
    "HQ_BACKUP_COPY_DIR": "Second backup folder",
    "HQ_PRINT_DIR": "Thursday print folder",
    "HQ_PRINTER": "Printer",
    "HQ_BUILD_URL": "Build it address",
    "HQ_BUILD_TOKEN": "Build it token",
    "HQ_PRINTIFY_TOKEN": "Printify API token",
    "HQ_ETSY_DESIGNS_PER_DAY": "New shirt designs per day",
    "HQ_ETSY_REVIEW_DESIGNS": "Show me new designs before they're built",
    "HQ_ETSY_DAILY_BUDGET": "Etsy village daily Claude limit ($)",
    "HQ_ETSY_MONTHLY_BUDGET": "Etsy village monthly limit ($)",
    "HQ_OPENAI_API_KEY": "Image key (OpenAI, optional)",
}


def group_of(key: str) -> str:
    for gid, _, _, _, keys, prefixes in GROUPS:
        if key in keys or key.startswith(prefixes):
            return gid
    return "general"


def accounts() -> list[dict]:
    path = CONFIG_DIR / "accounts.yaml"
    if not path.exists():
        return []
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("accounts") or []


# The fields of config/pitch.yaml shown on the Settings page: (key, label, kind, help). kind: text, number, yesno.
PITCH_FIELDS = [
    ("sender_name", "Your name", "text", "How you sign each message, e.g. Steven. Pitch writes nothing until this is filled in."),
    ("about_me", "About you", "text", "One honest line, e.g. I run clipping accounts for Twitch streamers. Leave blank if unsure."),
    ("what_you_offer", "What you offer", "text", "One sentence about what the streamer gets."),
    ("price", "Price", "text", "e.g. $150 a month for 10 clips. Blank means Pitch won't mention a price."),
    ("monthly_package", "Pitch the monthly package", "yesno", "Adds the 12 clips for $79 offer line to every draft."),
    ("package_clips", "Package: clips a month", "number", "Clips in the monthly package."),
    ("package_price", "Package: price ($)", "number", "Dollars a month."),
    ("package_revisions", "Package: revisions", "number", "Revisions per batch."),
    ("payment_link", "Stripe payment link", "text", "From your Stripe account (test mode first). Only https://buy.stripe.com links are used."),
    ("portfolio_url", "Link to your clips", "text", "Your clipping account or best clips. Blank means no link."),
    ("free_sample", "Offer a free sample clip", "yesno", "Each message offers to make one clip for free."),
    ("opt_out_line", "Opt-out line", "text", "Added word for word to every message. Please keep one."),
    ("postal_address", "Postal address", "text", "Required to send email: spam law wants a real mailing address in the message (a PO box is fine)."),
    ("daily_send_cap", "Most emails per day", "number", "Pitch won't send more than this in 24 hours (never above 20). Keeps Gmail happy."),
    ("daily_leads", "New pitches per run", "number", "How many streamers to draft pitches for each time."),
    ("min_viewers", "Smallest streamer (viewers)", "number", "Live viewers, lowest to look for."),
    ("max_viewers", "Biggest streamer (viewers)", "number", "Live viewers, highest to look for."),
    ("language", "Streamer language", "text", "Two-letter code, e.g. en."),
    ("auto_find", "Find streamers every day", "yesno", "Off by default. Pitch still only drafts; you approve and send everything."),
    ("followup_days", "Follow-up reminder (days)", "number", "Days after you send a pitch before Pitch reminds you."),
    ("max_followups", "Most follow-ups", "number", "After this many reminders with no reply, the lead is marked dead."),
]
_PITCH_KINDS = {k: kind for k, _, kind, _ in PITCH_FIELDS}


def pitch_describe() -> list[dict]:
    path = CONFIG_DIR / "pitch.yaml"
    data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}
    out = []
    for key, label, kind, help_ in PITCH_FIELDS:
        v = data.get(key)
        out.append({"key": key, "label": label, "kind": kind, "help": help_,
                    "value": ("true" if v else "false") if kind == "yesno" else ("" if v is None else str(v))})
    return out


def save_pitch(values: dict) -> list[str]:
    """Write changed values into config/pitch.yaml line by line, keeping the file's comments."""
    path = CONFIG_DIR / "pitch.yaml"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = []
    for key, value in values.items():
        kind = _PITCH_KINDS.get(key)
        if kind is None:
            raise ValueError(f"{key} isn't a Pitch setting")
        value = str(value).strip()
        if "\n" in value or "\r" in value:
            raise ValueError(f"{key} can't have more than one line")
        if kind == "number":
            if not re.fullmatch(r"\d{1,6}", value):
                raise ValueError(f"{key} must be a whole number")
            text = value
        elif kind == "yesno":
            text = "true" if value.lower() in ("true", "yes") else "false"
        else:
            text = json.dumps(value, ensure_ascii=False)
        for i, line in enumerate(lines):
            m = re.match(rf"^({key}:\s*)(\"(?:[^\"\\\\]|\\\\.)*\"|[^#\n]*?)(\s*(?:#.*)?\r?\n?)$", line)
            if m:
                tail = m.group(3) if m.group(3).strip() else "\n"
                lines[i] = f"{m.group(1)}{text}{'  ' + tail.lstrip() if tail.lstrip().startswith('#') else tail}"
                break
        else:
            lines.append(f"{key}: {text}\n")
        changed.append(key)
    path.write_text("".join(lines), encoding="utf-8")
    return changed


def _value(key: str) -> dict:
    v = os.getenv(key, "")
    if is_secret(key):
        return {"key": key, "secret": True, "set": bool(v), "hint": f"ends in {v[-4:]}" if len(v) >= 12 else ""}
    return {"key": key, "secret": False, "value": v}


def describe() -> dict:
    """Everything the Settings page shows. Secrets never leave HQ, only whether they're set."""
    from . import connections
    tests = connections.results()
    sections = _sections()
    listed = {f["key"] for s in sections for f in s["fields"]}
    for s in sections:
        s["fields"] = [{**f, **_value(f["key"]), "test": connections.KEY_TESTS.get(f["key"]), "label": LABELS.get(f["key"], ""),
                        "group": group_of(f["key"])} for f in s["fields"]]
    order = list(LABELS)  # settings with a plain-English name come first, in that order
    groups = [{"id": gid, "icon": icon, "title": title, "blurb": blurb, "fields": sorted(
        (f for sec in sections for f in sec["fields"] if f["group"] == gid),
        key=lambda f: order.index(f["key"]) if f["key"] in order else len(order))} for gid, icon, title, blurb, _, _ in GROUPS]
    accts = []
    for a in accounts():
        keys = [v for k, v in a.items() if k.endswith("_env") and isinstance(v, str)]
        accts.append({"name": a.get("name"), "platform": a.get("platform"), "enabled": bool(a.get("enabled")),
                      "test": f"account:{a.get('name')}",
                      "fields": [{"key": k, "help": "", "example": "", **_value(k)} for k in keys if k not in listed]})
    last = {name: {"ok": r["ok"], "message": r["message"]} for name, r in tests.items()}
    from . import tiktok_auth
    from . import youtube_auth
    from . import instagram_auth
    return {"instagram": instagram_auth.status(), "tiktok": tiktok_auth.status(), "youtube": youtube_auth.status(), "sections": sections, "groups": groups, "accounts": accts, "tests": last, "pitch": pitch_describe()}


def save(values: dict) -> list[str]:
    """Save settings (an empty value clears one). Returns the keys that changed."""
    saved = config.saved_settings()
    changed = []
    for key, value in values.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"{key} isn't a setting name")
        value = str(value).strip()
        if "\n" in value or "\r" in value:
            raise ValueError(f"{key} can't have more than one line")
        if os.getenv(key, "") != value:
            changed.append(key)
        saved[key] = os.environ[key] = value
    if values:
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(saved, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(SETTINGS_PATH)
    return changed


def set_account_enabled(name: str, enabled: bool):
    """Flip `enabled:` for one account in config/accounts.yaml, keeping the file's comments."""
    path = CONFIG_DIR / "accounts.yaml"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    inside = False
    for i, line in enumerate(lines):
        m = re.match(r"\s*-\s*name:\s*(\S+)", line)
        if m:
            inside = m.group(1) == name
        elif inside and re.match(r"\s*enabled:", line):
            lines[i] = re.sub(r"enabled:\s*\w+", f"enabled: {'true' if enabled else 'false'}", line)
            path.write_text("".join(lines), encoding="utf-8")
            return
    raise KeyError(name)
