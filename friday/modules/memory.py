"""Memory module — conversation history and personal memories via Turso/SQLite."""

import time
from loguru import logger
from friday.db import execute, execute_insert


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
    """Get all conversation sessions for a user, most recently active first.

    Each session includes a title (first user message) and last-activity time
    so recent conversations surface at the top of the history list.
    """
    rows = execute(
        """SELECT session_id,
                  MIN(timestamp) as started,
                  MAX(timestamp) as last_active,
                  COUNT(*) as msg_count
           FROM conversations
           WHERE user_id = ?
           GROUP BY session_id
           ORDER BY last_active DESC
           LIMIT 50""",
        [user_id],
    )

    sessions = []
    for r in rows:
        session_id = r["session_id"]
        # Fetch the first user message as a readable title
        title_rows = execute(
            "SELECT content FROM conversations WHERE user_id = ? AND session_id = ? AND role = 'user' ORDER BY id ASC LIMIT 1",
            [user_id, session_id],
        )
        title = title_rows[0]["content"] if title_rows else "New conversation"
        if len(title) > 40:
            title = title[:40].rstrip() + "…"
        sessions.append({
            "session_id": session_id,
            "started": r["started"],
            "last_active": r["last_active"],
            "title": title,
            "msg_count": r["msg_count"],
        })
    return sessions


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
