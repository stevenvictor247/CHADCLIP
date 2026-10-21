"""Settings and paths. Everything is read from environment variables (or a .env file)."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CONFIG_DIR = ROOT / "config"
DATA_DIR = Path(os.getenv("HQ_DATA_DIR", ROOT / "data"))
SOURCES_DIR = DATA_DIR / "sources"
CLIPS_DIR = DATA_DIR / "clips"
DB_PATH = DATA_DIR / "hq.sqlite3"
VISION_PATH = CONFIG_DIR / "vision.md"

for d in (DATA_DIR, SOURCES_DIR, CLIPS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Models. Each agent gets the cheapest model that does its job well. Override any of them in .env with
# HQ_MODEL_<NAME>=..., for example HQ_MODEL_CHAD=claude-opus-5-5. HQ_BOSS_MODEL still works for the Boss.
# Per million tokens (input / output): Opus 5.5 $4 / $20, Sonnet 5.5 $2 / $10, Haiku 5.5 $0.10 / $0.50.
DEFAULT_MODELS = {
    "boss": "claude-opus-5-5",      # takes direction and delegates, so it gets the strongest model
    "chad": "claude-sonnet-5-5",    # picks moments from transcripts
    "pitch": "claude-sonnet-5-5",   # writes the messages to potential clients, so wording matters
}
SIMPLE_MODEL = "claude-haiku-5-5"   # every other agent: sorting, drafting, summarising


def model_for(name: str) -> str:
    key = name.lower()
    legacy = os.getenv("HQ_BOSS_MODEL") if key == "boss" else os.getenv("HQ_AGENT_MODEL")
    return os.getenv(f"HQ_MODEL_{key.upper()}") or legacy or DEFAULT_MODELS.get(key, SIMPLE_MODEL)


BOSS_MODEL = model_for("boss")
AGENT_MODEL = model_for("chad")

# USD per million tokens (input, output). Cached reads cost 0.1x input and cache writes 1.25x.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00), "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5-5": (2.00, 10.00), "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50), "claude-fable-5-1": (10.00, 50.00), "claude-fable-5": (10.00, 50.00),
}
UNKNOWN_PRICE = (5.00, 25.00)  # for a model not listed above, assume a pricey one so the meter never under-reports

# Stop scheduled work for the rest of the day once Claude spending reaches this many US dollars. 0 means no limit.
DAILY_BUDGET = float(os.getenv("HQ_DAILY_BUDGET", "0") or 0)

# Without an API key the system still runs, using simple rules instead of Claude.
HAS_LLM = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))

# Whisper model size for transcription: tiny, base, small, medium, large-v3.
WHISPER_MODEL = os.getenv("HQ_WHISPER_MODEL", "small")

# Clips wait for your approval before posting unless this is set to "false".
REQUIRE_APPROVAL = os.getenv("HQ_REQUIRE_APPROVAL", "true").lower() != "false"

# Password for the dashboard. Leave empty on your own computer; always set it on a server.
PASSWORD = os.getenv("HQ_PASSWORD", "")

# Public base URL where data/clips is served. Instagram fetches videos from a URL,
# so it needs this to be reachable from the internet (e.g. via a tunnel or bucket).
PUBLIC_BASE_URL = os.getenv("HQ_PUBLIC_BASE_URL", "").rstrip("/")
