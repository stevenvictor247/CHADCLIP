"""Run every test against a fresh throwaway data folder so tests never see (or damage) your real HQ data."""

import os
import tempfile

os.environ["HQ_DATA_DIR"] = tempfile.mkdtemp(prefix="hq-test-")

# TestClient calls HQ "testserver"; let that name through the check that only lets this computer in.
os.environ["HQ_ALLOWED_HOSTS"] = "testserver"

# Scout's daily web search spends real money, so tests turn it off unless they mock it.
os.environ["SCOUT_WEB_SEARCH"] = "0"
