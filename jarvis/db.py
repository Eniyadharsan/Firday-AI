"""
Database module — Turso (libSQL) cloud database.

Provides a single get_db() function that returns a connection.
All modules use this instead of local SQLite.
"""

import os
import sqlite3
from loguru import logger

TURSO_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")

_connection = None


def get_db():
    """Get a database connection. Uses Turso if configured, else local SQLite."""
    global _connection

    if TURSO_URL and TURSO_TOKEN:
        # Use libsql for Turso cloud
        try:
            import libsql_experimental as libsql
            if _connection is None:
                _connection = libsql.connect("jarvis.db", sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
                _connection.sync()
                logger.info("Connected to Turso cloud database")
            return _connection
        except ImportError:
            logger.warning("libsql_experimental not installed, falling back to local SQLite")
        except Exception as e:
            logger.error(f"Turso connection error: {e}")

    # Fallback: local SQLite
    from jarvis.config import DB_PATH
    return sqlite3.connect(str(DB_PATH))


def init_tables():
    """Initialize all database tables."""
    conn = get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_login TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS long_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                fact TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                source TEXT DEFAULT 'auto',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                content TEXT NOT NULL,
                chunks_count INTEGER DEFAULT 0,
                uploaded_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                tasks TEXT NOT NULL,
                progress INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
        logger.info("Database tables initialized")
    except Exception as e:
        logger.error(f"Table init error: {e}")


# Initialize on import
try:
    init_tables()
except Exception as e:
    logger.warning(f"DB init deferred: {e}")
