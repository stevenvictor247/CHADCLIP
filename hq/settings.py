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


def _value(key: str) -> dict:
    v = os.getenv(key, "")
    if is_secret(key):
        return {"key": key, "secret": True, "set": bool(v), "hint": f"ends in {v[-4:]}" if len(v) >= 12 else ""}
    return {"key": key, "secret": False, "value": v}


def describe() -> dict:
    """Everything the Settings page shows. Secrets never leave HQ, only whether they're set."""
    sections = _sections()
    listed = {f["key"] for s in sections for f in s["fields"]}
    for s in sections:
        s["fields"] = [{**f, **_value(f["key"])} for f in s["fields"]]
    accts = []
    for a in accounts():
        keys = [v for k, v in a.items() if k.endswith("_env") and isinstance(v, str)]
        accts.append({"name": a.get("name"), "platform": a.get("platform"), "enabled": bool(a.get("enabled")),
                      "fields": [{"key": k, "help": "", "example": "", **_value(k)} for k in keys if k not in listed]})
    return {"sections": sections, "accounts": accts}


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
