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
LLM_MODELS: list[str] = ["gpt-oss-120b", "gemma-4-31b"]
LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "4096"))
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.6"))

# --- Storage ---
DATA_DIR: Path = Path("/data/jarvis") if Path("/data").exists() else Path(".jarvis-data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH: Path = DATA_DIR / "jarvis.db"

# --- Auth ---
JWT_SECRET: str = os.getenv("JWT_SECRET", "jarvis-secret-change-in-prod")
BCRYPT_ROUNDS: int = 12

# --- External ---
RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
NEWS_REFRESH_INTERVAL: int = 300  # seconds
