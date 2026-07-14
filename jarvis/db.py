"""
Database module — Turso (libSQL) via HTTP API.
No special packages needed — uses standard requests.
Falls back to local SQLite if Turso is unavailable.

Performance optimizations:
- Persistent HTTP session (reuses TCP + TLS connections)
- SQLite connection pooling (thread-local, kept open)
- Reduced timeout for faster fallback
- Pre-built headers (no per-request allocation)
"""

import os
import sqlite3
import threading
import requests
from pathlib import Path
from typing import Any
from loguru import logger

# --- Configuration ---
_raw_url = os.getenv("TURSO_DATABASE_URL", "")
_raw_token = os.getenv("TURSO_AUTH_TOKEN", "")

USE_TURSO: bool = bool(_raw_url.strip() and _raw_token.strip())

TURSO_URL: str = _raw_url.replace("libsql://", "https://") if _raw_url else ""
TURSO_TOKEN: str = _raw_token

# Local fallback path
LOCAL_DB = Path("/tmp/jarvis-data/jarvis.db")
LOCAL_DB.parent.mkdir(parents=True, exist_ok=True)

# --- Persistent HTTP Session (reuses TCP/TLS connections) ---
_session: requests.Session | None = None
_pipeline_url: str = ""

if USE_TURSO:
    _session = requests.Session()
    _session.headers.update({
        "Authorization": f"Bearer {TURSO_TOKEN}",
        "Content-Type": "application/json",
    })
    # Enable connection pooling with keep-alive
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=5,
        pool_maxsize=10,
        max_retries=0,  # We handle retries via fallback
    )
    _session.mount("https://", adapter)
    _pipeline_url = f"{TURSO_URL}/v2/pipeline"

# --- SQLite Connection Pool (thread-local) ---
_local_storage = threading.local()


def _get_local_conn() -> sqlite3.Connection:
    """Get or create a thread-local SQLite connection."""
    conn = getattr(_local_storage, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(LOCAL_DB), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Performance pragmas for local SQLite
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-8000")  # 8MB cache
        _local_storage.conn = conn
    return conn


# --- Parameter Serialization ---
def _serialize_param(value: Any) -> dict:
    """Convert a Python value to Turso typed parameter format."""
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
    return {"type": "text", "value": str(value)}


# --- Turso HTTP Execution (optimized) ---
def _turso_execute(sql: str, params: list) -> list[dict]:
    """Execute via Turso HTTP Pipeline API with persistent session."""
    try:
        typed_args = [_serialize_param(p) for p in params] if params else []
        body = {
            "requests": [
                {
                    "type": "execute",
                    "stmt": {"sql": sql, "args": typed_args},
                },
                {"type": "close"},
            ]
        }

        # Use persistent session — skips TCP/TLS handshake on subsequent calls
        r = _session.post(_pipeline_url, json=body, timeout=5)

        if r.status_code != 200:
            logger.error(f"Turso error {r.status_code}: {r.text[:200]}")
            return _local_execute(sql, params)

        data = r.json()
        results = data.get("results")
        if not results:
            return []

        first = results[0]
        if first.get("type") != "ok":
            return []

        result = first.get("response", {}).get("result", {})

        # Write operations — return immediately
        if not sql.lstrip()[:7].upper().startswith(("SELECT", "PRAGMA")):
            return []

        # Parse rows into dicts
        cols = result.get("cols", [])
        rows_data = result.get("rows", [])
        
        if not cols or not rows_data:
            return []

        col_names = [c["name"] for c in cols]
        num_cols = len(col_names)

        # Fast path: pre-allocate and iterate
        rows = []
        for row in rows_data:
            row_dict = {}
            for i in range(num_cols):
                val = row[i]
                row_dict[col_names[i]] = val.get("value") if isinstance(val, dict) else val
            rows.append(row_dict)
        return rows

    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        logger.error(f"Turso connection failed: {type(e).__name__}")
        return _local_execute(sql, params)
    except Exception as e:
        logger.error(f"Turso request failed: {type(e).__name__}: {e}")
        return _local_execute(sql, params)


# --- Local SQLite Execution (optimized with pooled connection) ---
def _local_execute(sql: str, params: list) -> list[dict]:
    """Execute via local SQLite with pooled connection."""
    try:
        conn = _get_local_conn()
        cursor = conn.execute(sql, params or [])

        if sql.lstrip()[:7].upper().startswith(("SELECT", "PRAGMA")):
            return [dict(r) for r in cursor.fetchall()]
        else:
            conn.commit()
            return []
    except Exception as e:
        logger.error(f"Local DB error: {e}")
        # Reset connection on error
        _local_storage.conn = None
        return []


# --- Legacy Compatibility ---
def get_db():
    """Get a direct SQLite connection for legacy modules."""
    conn = sqlite3.connect(str(LOCAL_DB))
    conn.row_factory = sqlite3.Row
    return conn


# --- Public API ---
def execute(sql: str, params: list = None) -> list[dict]:
    """Execute a read query (SELECT/PRAGMA). Returns list of row dicts."""
    if USE_TURSO:
        return _turso_execute(sql, params or [])
    return _local_execute(sql, params or [])


def execute_insert(sql: str, params: list = None) -> list[dict]:
    """Execute a write query (INSERT/UPDATE/DELETE/CREATE). Returns empty list."""
    if USE_TURSO:
        try:
            return _turso_execute(sql, params or [])
        except Exception as turso_err:
            logger.error(f"Turso insert failed: {turso_err}")
            try:
                return _local_execute(sql, params or [])
            except Exception as local_err:
                logger.error(f"Local insert also failed: {local_err}")
                return []
    return _local_execute(sql, params or [])


# --- Schema Initialization ---
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
