"""Memory module — SQLite-backed conversation history and personal memories."""

import time
import json
from jarvis.db import get_db
from loguru import logger
from jarvis.config import DB_PATH


# DB tables initialized by jarvis.db


def save_message(user_id: str, session_id: str, role: str, content: str) -> None:
    """Save a message to conversation history."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO conversations (user_id, session_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
            (user_id, session_id, role, content, time.strftime("%Y-%m-%dT%H:%M:%SZ")),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Save message error: {e}")
    finally:
        conn.close()


def get_history(user_id: str, session_id: str, limit: int = 50) -> list[dict[str, str]]:
    """Get conversation history for a session."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT role, content FROM conversations WHERE user_id = ? AND session_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, session_id, limit),
        ).fetchall()
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
    except Exception as e:
        logger.error(f"Get history error: {e}")
        return []
    finally:
        conn.close()


def get_all_sessions(user_id: str) -> list[dict]:
    """Get all conversation sessions for a user."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT DISTINCT session_id, MIN(timestamp) as started FROM conversations WHERE user_id = ? GROUP BY session_id ORDER BY started DESC LIMIT 20",
            (user_id,),
        ).fetchall()
        return [{"session_id": r[0], "started": r[1]} for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def add_memory(user_id: str, content: str, category: str = "general") -> dict:
    """Store a personal memory."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO memories (user_id, content, category, created_at) VALUES (?, ?, ?, ?)",
            (user_id, content, category, time.strftime("%Y-%m-%dT%H:%M:%SZ")),
        )
        conn.commit()
        return {"success": True, "content": content, "category": category}
    except Exception as e:
        logger.error(f"Add memory error: {e}")
        return {"error": str(e)}
    finally:
        conn.close()


def get_memories(user_id: str) -> list[dict]:
    """Get all memories for a user."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, content, category, created_at FROM memories WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
        return [{"id": r[0], "content": r[1], "category": r[2], "created_at": r[3]} for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def delete_memory(user_id: str, memory_id: int) -> bool:
    """Delete a memory."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM memories WHERE id = ? AND user_id = ?", (memory_id, user_id))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()
