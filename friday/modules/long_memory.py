"""
Long-Term Memory — Auto-extracts and stores user preferences/facts.
Optimized: uses pooled execute/execute_insert instead of get_db() per call.
"""

import re
import time
from loguru import logger
from friday.db import execute, execute_insert


# Patterns that indicate user is sharing personal info
EXTRACTION_PATTERNS: list[tuple[str, str]] = [
    (r"\bmy name is (\w+)", "identity"),
    (r"\bi(?:'m| am) (\w+)", "identity"),
    (r"\bi work (?:at|for|in) (.+?)(?:\.|,|$)", "work"),
    (r"\bi live in (.+?)(?:\.|,|$)", "location"),
    (r"\bi(?:'m| am) from (.+?)(?:\.|,|$)", "location"),
    (r"\bi (?:like|love|enjoy|prefer) (.+?)(?:\.|,|$)", "preference"),
    (r"\bi (?:hate|dislike|don't like) (.+?)(?:\.|,|$)", "preference"),
    (r"\bi(?:'m| am) learning (.+?)(?:\.|,|$)", "learning"),
    (r"\bi(?:'m| am) working on (.+?)(?:\.|,|$)", "project"),
    (r"\bmy (?:goal|target) is (.+?)(?:\.|,|$)", "goal"),
    (r"\bremember (?:that |this: ?)(.+?)(?:\.|$)", "explicit"),
]

# Pre-compile patterns for speed
_COMPILED_PATTERNS = [(re.compile(p, re.IGNORECASE), cat) for p, cat in EXTRACTION_PATTERNS]


def auto_extract(user_id: str, message: str) -> list[str]:
    """Auto-extract facts from a message and store them."""
    extracted: list[str] = []

    for pattern, category in _COMPILED_PATTERNS:
        matches = pattern.findall(message)
        for match in matches:
            fact = match.strip()
            if len(fact) > 2 and not _is_duplicate(user_id, fact):
                _store_fact(user_id, fact, category)
                extracted.append(fact)

    return extracted


def _store_fact(user_id: str, fact: str, category: str = "general") -> None:
    """Store a long-term fact using pooled connection."""
    execute_insert(
        "INSERT INTO long_memory (user_id, fact, category, source, created_at) VALUES (?, ?, ?, 'auto', ?)",
        [user_id, fact, category, time.strftime("%Y-%m-%dT%H:%M:%SZ")],
    )


def _is_duplicate(user_id: str, fact: str) -> bool:
    """Check if a similar fact already exists."""
    rows = execute("SELECT fact FROM long_memory WHERE user_id = ?", [user_id])
    fact_lower = fact.lower()
    for row in rows:
        existing = row["fact"].lower()
        if fact_lower in existing or existing in fact_lower:
            return True
    return False


def get_user_context(user_id: str) -> str:
    """Get all known facts about a user as context string."""
    rows = execute(
        "SELECT fact, category FROM long_memory WHERE user_id = ? ORDER BY id DESC LIMIT 20",
        [user_id],
    )
    if not rows:
        return ""
    facts = [f"- {r['fact']} ({r['category']})" for r in rows]
    return "[User Profile — things I know about this user]:\n" + "\n".join(facts)


def get_all_facts(user_id: str) -> list[dict]:
    """Get all stored facts for a user."""
    rows = execute(
        "SELECT id, fact, category, created_at FROM long_memory WHERE user_id = ? ORDER BY id DESC",
        [user_id],
    )
    return [{"id": r["id"], "fact": r["fact"], "category": r["category"], "created_at": r["created_at"]} for r in rows]


def delete_fact(user_id: str, fact_id: int) -> bool:
    """Delete a stored fact."""
    execute_insert("DELETE FROM long_memory WHERE id = ? AND user_id = ?", [fact_id, user_id])
    return True
