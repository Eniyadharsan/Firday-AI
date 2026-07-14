"""Configuration — loads from .env or environment variables."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- Server ---
PORT: int = int(os.getenv("PORT", "7860"))
DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

# --- AI ---
CEREBRAS_API_KEY: str = os.getenv("CEREBRAS_API_KEY", "")
LLM_MODELS: list[str] = ["gemma-4-31b", "gpt-oss-120b"]
LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "2048"))
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.6"))

# --- Database (Turso) ---
TURSO_DATABASE_URL: str = os.getenv("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN: str = os.getenv("TURSO_AUTH_TOKEN", "")

# --- Storage (local fallback) ---
DATA_DIR: Path = Path("/tmp/jarvis-data")
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    DATA_DIR = Path(".")
DB_PATH: Path = DATA_DIR / "jarvis.db"

# --- Auth ---
JWT_SECRET: str = os.getenv("JWT_SECRET", "jarvis-secret-change-in-prod")

# --- External ---
RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
NEWS_REFRESH_INTERVAL: int = 300
