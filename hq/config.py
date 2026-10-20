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

# Models. The Boss does the thinking; Chad's moment picking can run cheaper if you want.
BOSS_MODEL = os.getenv("HQ_BOSS_MODEL", "claude-opus-5-5")
AGENT_MODEL = os.getenv("HQ_AGENT_MODEL", "claude-opus-5-5")

# Without an API key the system still runs, using simple rules instead of Claude.
HAS_LLM = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))

# Whisper model size for transcription: tiny, base, small, medium, large-v3.
WHISPER_MODEL = os.getenv("HQ_WHISPER_MODEL", "small")

# Clips wait for your approval before posting unless this is set to "false".
REQUIRE_APPROVAL = os.getenv("HQ_REQUIRE_APPROVAL", "true").lower() != "false"

# Public base URL where data/clips is served. Instagram fetches videos from a URL,
# so it needs this to be reachable from the internet (e.g. via a tunnel or bucket).
PUBLIC_BASE_URL = os.getenv("HQ_PUBLIC_BASE_URL", "").rstrip("/")
