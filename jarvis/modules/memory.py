"""Memory module — conversation history and personal memories via Turso/SQLite."""

import time
from loguru import logger
from jarvis.db import execute, execute_insert


def save_message(user_id: str, session_id: str, role: str, content: str) -> None:
    """Save a message to conversation history."""
    execute_insert(
        "INSERT INTO conversations (user_id, session_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        [user_id, session_id, role, content, time.strftime("%Y-%m-%dT%H:%M:%SZ")],
    )


def get_history(user_id: str, session_id: str, limit: int = 50) -> list[dict[str, str]]:
    """Get conversation history for a session."""
    rows = execute(
        "SELECT role, content FROM conversations WHERE user_id = ? AND session_id = ? ORDER BY id DESC LIMIT ?",
        [user_id, session_id, limit],
    )
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def get_all_sessions(user_id: str) -> list[dict]:
    """Get all conversation sessions for a user."""
    rows = execute(
        "SELECT DISTINCT session_id, MIN(timestamp) as started FROM conversations WHERE user_id = ? GROUP BY session_id ORDER BY started DESC LIMIT 20",
        [user_id],
    )
    return [{"session_id": r["session_id"], "started": r["started"]} for r in rows]


def add_memory(user_id: str, content: str, category: str = "general") -> dict:
    """Store a personal memory."""
    execute_insert(
        "INSERT INTO memories (user_id, content, category, created_at) VALUES (?, ?, ?, ?)",
        [user_id, content, category, time.strftime("%Y-%m-%dT%H:%M:%SZ")],
    )
    return {"success": True, "content": content, "category": category}


def get_memories(user_id: str) -> list[dict]:
    """Get all memories for a user."""
    rows = execute(
        "SELECT id, content, category, created_at FROM memories WHERE user_id = ? ORDER BY id DESC",
        [user_id],
    )
    return [{"id": r["id"], "content": r["content"], "category": r["category"], "created_at": r["created_at"]} for r in rows]


def delete_memory(user_id: str, memory_id: int) -> bool:
    """Delete a memory."""
    execute_insert("DELETE FROM memories WHERE id = ? AND user_id = ?", [memory_id, user_id])
    return True
