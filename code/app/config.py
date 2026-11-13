"""Paths and settings, read once from the environment.

Model keys and provider addresses are read only from the four variables in
.env.example (GROQ_API_KEY, GROQ_BASE_URL, GEMINI_API_KEY, GEMINI_BASE_URL).
Model names and limits are optional settings with safe defaults.
"""

import os
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = CODE_DIR.parent


def load_env_file(path: Path) -> None:
    """Load KEY=value lines from code/.env. Variables already set take priority."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _path_setting(name: str, default: Path) -> Path:
    """An empty value in .env counts as unset."""
    value = os.environ.get(name, "").strip()
    return Path(value).resolve() if value else default.resolve()


def _setting(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


load_env_file(CODE_DIR / ".env")

# The data pack. Graders point DATA_DIR at their own copy.
DATA_DIR = _path_setting("DATA_DIR", REPO_DIR)
DB_PATH = DATA_DIR / "data" / "sales.sqlite"
DOCS_DIR = DATA_DIR / "docs"

# Everything this system writes. Only code/ is editable, so it lives here.
MOCK_SYSTEM_DIR = _path_setting("MOCK_SYSTEM_DIR", CODE_DIR / "mock_system")
REPORT_STORE_DIR = MOCK_SYSTEM_DIR / "report_store"
QUERY_LOG_PATH = MOCK_SYSTEM_DIR / "audit" / "query_log.jsonl"

# Run state (paused approvals survive a restart) and logs.
STATE_DIR = CODE_DIR / ".state"
CHECKPOINT_DB = STATE_DIR / "checkpoints.db"
PENDING_DIR = STATE_DIR / "pending"
LOG_DIR = CODE_DIR / "logs"
LLM_LOG_PATH = LOG_DIR / "llm_calls.jsonl"
TRACE_LOG_PATH = LOG_DIR / "trace.jsonl"

# Guards on every SQL query.
SQL_MAX_ROWS = 5000
SQL_TIMEOUT_S = 10.0

# Models. The orchestrator plans on Groq; specialists write on Gemini. Each
# role falls back to the other provider, so one outage never stops a run.
ORCHESTRATOR_MODEL = _setting("ORCHESTRATOR_MODEL", "openai/gpt-oss-120b")  # Groq
ORCHESTRATOR_FALLBACK_MODEL = _setting("ORCHESTRATOR_FALLBACK_MODEL", "gemini-3.6-flash")  # Gemini
SPECIALIST_MODEL = _setting("SPECIALIST_MODEL", "gemini-3.6-flash")  # Gemini
SPECIALIST_FALLBACK_MODEL = _setting("SPECIALIST_FALLBACK_MODEL", "openai/gpt-oss-20b")  # Groq

LLM_TIMEOUT_S = float(_setting("LLM_TIMEOUT_S", "30"))
LLM_MAX_CALLS_PER_RUN = int(_setting("LLM_MAX_CALLS_PER_RUN", "12"))
LLM_MAX_RATE_LIMIT_WAIT_S = 20.0
LLM_RATE_LIMIT_COOLDOWN_S = 60.0  # how long a rate-limited provider is skipped

# How many times the verifier may send work back before giving up (brief: twice at most).
MAX_SEND_BACKS = 2

# USD per 1M tokens (input, output), for cost estimates in the call log.
# Groq prices from console.groq.com/docs/models; check Gemini prices on ai.google.dev/pricing.
PRICES_PER_M_TOKENS = {
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
}
