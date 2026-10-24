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
        s["fields"] = [{**f, **_value(f["key"]), "test": connections.KEY_TESTS.get(f["key"])} for f in s["fields"]]
    accts = []
    for a in accounts():
        keys = [v for k, v in a.items() if k.endswith("_env") and isinstance(v, str)]
        accts.append({"name": a.get("name"), "platform": a.get("platform"), "enabled": bool(a.get("enabled")),
                      "test": f"account:{a.get('name')}",
                      "fields": [{"key": k, "help": "", "example": "", **_value(k)} for k in keys if k not in listed]})
    last = {name: {"ok": r["ok"], "message": r["message"]} for name, r in tests.items()}
    from . import tiktok_auth
    from . import youtube_auth
    return {"tiktok": tiktok_auth.status(), "youtube": youtube_auth.status(), "sections": sections, "accounts": accts, "tests": last, "pitch": pitch_describe()}


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
