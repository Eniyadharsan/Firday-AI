"""
Database module — Turso (libSQL) via HTTP API.
No special packages needed — uses standard requests.
Falls back to local SQLite if Turso is unavailable.
"""

import os
import json
import sqlite3
import requests
from pathlib import Path
from typing import Any
from loguru import logger

# --- Configuration (Task 1) ---
_raw_url = os.getenv("TURSO_DATABASE_URL", "")
_raw_token = os.getenv("TURSO_AUTH_TOKEN", "")

# USE_TURSO = True only when both are non-empty AND non-whitespace
USE_TURSO: bool = bool(_raw_url.strip() and _raw_token.strip())

# URL normalization: replace libsql:// with https://, leave https:// unchanged
TURSO_URL: str = _raw_url.replace("libsql://", "https://") if _raw_url else ""
TURSO_TOKEN: str = _raw_token

# Local fallback path
LOCAL_DB = Path("/tmp/jarvis-data/jarvis.db")
LOCAL_DB.parent.mkdir(parents=True, exist_ok=True)


# --- Parameter Serialization (Task 2) ---
def _serialize_param(value: Any) -> dict:
    """Convert a Python value to Turso typed parameter format.
    
    IMPORTANT: bool check must come before int since bool is a subclass of int.
    """
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, str):
        return {"type": "text", "value": value}
    # Unsupported types -> text with str(val)
    return {"type": "text", "value": str(value)}


# --- Turso HTTP Execution (Task 3) ---
def _turso_execute(sql: str, params: list) -> list[dict]:
    """Execute via Turso HTTP Pipeline API (/v2/pipeline)."""
    try:
        url = f"{TURSO_URL}/v2/pipeline"
        headers = {
            "Authorization": f"Bearer {TURSO_TOKEN}",
            "Content-Type": "application/json",
        }

        # Build pipeline request with typed args and close request
        typed_args = [_serialize_param(p) for p in params]
        body = {
            "requests": [
                {
                    "type": "execute",
                    "stmt": {
                        "sql": sql,
                        "args": typed_args,
                    },
                },
                {"type": "close"},
            ]
        }

        r = requests.post(url, headers=headers, json=body, timeout=10)

        if r.status_code != 200:
            # Log with truncated body (≤200 chars), never log the token
            truncated_body = r.text[:200]
            logger.error(f"Turso error {r.status_code}: {truncated_body}")
            return _local_execute(sql, params)

        # Parse response for SELECT/PRAGMA into list of dicts
        data = r.json()
        results = data.get("results", [])
        if not results:
            return []

        result = results[0].get("response", {}).get("result", {})
        
        # For write operations, return empty list
        upper_sql = sql.strip().upper()
        if not upper_sql.startswith(("SELECT", "PRAGMA")):
            return []

        cols = [c.get("name", "") for c in result.get("cols", [])]
        rows = []
        for row in result.get("rows", []):
            row_dict = {}
            for i, col in enumerate(cols):
                val = row[i]
                row_dict[col] = val.get("value") if isinstance(val, dict) else val
            rows.append(row_dict)
        return rows

    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        # Log without exposing the token
        logger.error(f"Turso connection failed: {type(e).__name__}: {e}")
        return _local_execute(sql, params)
    except Exception as e:
        logger.error(f"Turso request failed: {type(e).__name__}: {e}")
        return _local_execute(sql, params)


# --- Local SQLite Execution (Task 4) ---
def _local_execute(sql: str, params: list) -> list[dict]:
    """Execute via local SQLite (fallback). Uses parameterized queries."""
    try:
        conn = sqlite3.connect(str(LOCAL_DB))
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql, params)

        upper_sql = sql.strip().upper()
        if upper_sql.startswith(("SELECT", "PRAGMA")):
            rows = [dict(r) for r in cursor.fetchall()]
        else:
            conn.commit()
            rows = []

        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Local DB error: {e}")
        return []


# --- Legacy Compatibility ---
def get_db():
    """Get a direct SQLite connection for modules that use legacy pattern.
    
    Returns a sqlite3 connection to the local database. This exists for
    backward compatibility with modules (rag, planner, long_memory) that
    use conn.execute() / conn.commit() / conn.close() directly.
    """
    conn = sqlite3.connect(str(LOCAL_DB))
    conn.row_factory = sqlite3.Row
    return conn


# --- Public API (Tasks 4-5) ---
def execute(sql: str, params: list = None) -> list[dict]:
    """Execute a read query (SELECT/PRAGMA). Returns list of row dicts."""
    if USE_TURSO:
        return _turso_execute(sql, params or [])
    return _local_execute(sql, params or [])


def execute_insert(sql: str, params: list = None) -> list[dict]:
    """Execute a write query (INSERT/UPDATE/DELETE/CREATE). Returns empty list."""
    if USE_TURSO:
        try:
            result = _turso_execute(sql, params or [])
            return result
        except Exception as turso_err:
            logger.error(f"Turso insert failed: {turso_err}")
            try:
                return _local_execute(sql, params or [])
            except Exception as local_err:
                logger.error(f"Local insert also failed: {local_err}")
                return []
    # Local-only path
    return _local_execute(sql, params or [])


# --- Schema Initialization (Task 5) ---
def init_tables() -> None:
    """Initialize all required tables using CREATE TABLE IF NOT EXISTS."""
    tables = [
        """CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_login TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            content TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS long_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            fact TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            source TEXT DEFAULT 'auto',
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            content TEXT NOT NULL,
            chunks_count INTEGER DEFAULT 0,
            uploaded_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            tasks TEXT NOT NULL,
            progress INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )""",
    ]

    for sql in tables:
        try:
            execute(sql)
        except Exception as e:
            logger.error(f"Table init error: {e}")

    logger.info(f"DB initialized ({'Turso' if USE_TURSO else 'local SQLite'})")


# Initialize on import
init_tables()
