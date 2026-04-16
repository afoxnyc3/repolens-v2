"""Application configuration loaded from environment variables."""

import os
from pathlib import Path


# Required — hard fail if missing at call time (not at import)
def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError(
            "ANTHROPIC_API_KEY is not set. Export it before running repolens."
        )
    return key


# Model selection — default reviewed each release; see docs/decisions/ADR-006.
REPOLENS_MODEL: str = os.getenv("REPOLENS_MODEL", "claude-opus-4-7")

# Max tokens for AI completions
REPOLENS_MAX_TOKENS: int = int(os.getenv("REPOLENS_MAX_TOKENS", "4096"))

# Token budget for context bundles
REPOLENS_TOKEN_BUDGET: int = int(os.getenv("REPOLENS_TOKEN_BUDGET", "32000"))

# DB path — defaults to ~/.repolens/repolens.db
def get_db_path() -> Path:
    env_path = os.getenv("REPOLENS_DB", "")
    if env_path:
        return Path(env_path)
    default = Path.home() / ".repolens" / "repolens.db"
    default.parent.mkdir(parents=True, exist_ok=True)
    return default


# Module-level constant for convenience — resolved once at import time.
# Respects REPOLENS_DB env var (set before importing this module).
DB_PATH: Path = get_db_path()
