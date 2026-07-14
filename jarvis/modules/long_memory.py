"""
Long-Term Memory — Auto-extracts and stores user preferences/facts.

Stores:
- User preferences (likes, dislikes, style)
- Personal facts (name, location, work, interests)
- Ongoing context (current projects, goals)

Automatically injected into every conversation for personalization.
"""

import re
from jarvis.db import get_db
from loguru import logger
from jarvis.config import DB_PATH


# DB tables initialized by jarvis.db


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


def auto_extract(user_id: str, message: str) -> list[str]:
    """Auto-extract facts from a message and store them."""
    import time
    extracted: list[str] = []
    lower = message.lower()

    for pattern, category in EXTRACTION_PATTERNS:
        matches = re.findall(pattern, lower)
        for match in matches:
            fact = match.strip()
            if len(fact) > 2 and not is_duplicate(user_id, fact):
                store_fact(user_id, fact, category)
                extracted.append(fact)
                logger.info(f"Auto-extracted [{category}]: {fact}")

    return extracted


def store_fact(user_id: str, fact: str, category: str = "general") -> None:
    """Store a long-term fact."""
    import time
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO long_memory (user_id, fact, category, source, created_at) VALUES (?, ?, ?, 'auto', ?)",
            (user_id, fact, category, time.strftime("%Y-%m-%dT%H:%M:%SZ")),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Store fact error: {e}")
    finally:
        conn.close()


def is_duplicate(user_id: str, fact: str) -> bool:
    """Check if a similar fact already exists."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT fact FROM long_memory WHERE user_id = ?", (user_id,)
        ).fetchall()
        for row in rows:
            if fact.lower() in row[0].lower() or row[0].lower() in fact.lower():
                return True
        return False
    except Exception:
        return False
    finally:
        conn.close()


def get_user_context(user_id: str) -> str:
    """Get all known facts about a user as context string."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT fact, category FROM long_memory WHERE user_id = ? ORDER BY id DESC LIMIT 20",
            (user_id,),
        ).fetchall()
        if not rows:
            return ""
        facts = [f"- {r[0]} ({r[1]})" for r in rows]
        return "[User Profile — things I know about this user]:\n" + "\n".join(facts)
    except Exception:
        return ""
    finally:
        conn.close()


def get_all_facts(user_id: str) -> list[dict]:
    """Get all stored facts for a user."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, fact, category, created_at FROM long_memory WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
        return [{"id": r[0], "fact": r[1], "category": r[2], "created_at": r[3]} for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def delete_fact(user_id: str, fact_id: int) -> bool:
    """Delete a stored fact."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM long_memory WHERE id = ? AND user_id = ?", (fact_id, user_id))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()
