"""
AI Planning Mode — Task breakdown, timelines, progress tracking.

Generates structured plans with milestones, tracks progress per user.
"""

import time
import json
import sqlite3
from loguru import logger
from jarvis.config import DB_PATH
from jarvis.modules import llm


def _init_db() -> None:
    """Initialize planning tables."""
    conn = sqlite3.connect(str(DB_PATH))
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
    conn.close()

_init_db()


def is_planning_request(message: str) -> bool:
    """Detect if user wants a structured plan."""
    lower = message.lower()
    return bool(re.search(r"\b(plan|roadmap|schedule|learn|study plan|career path|project plan|breakdown|step by step)\b", lower) and len(message) > 15)

import re


def generate_plan(user_id: str, message: str) -> dict:
    """Generate a structured plan with tasks, timeline, and save it."""
    plan_prompt = [
        {"role": "system", "content": """Generate a structured plan in this exact JSON format:
{
  "title": "Plan title",
  "tasks": [
    {"id": 1, "task": "Task description", "duration": "X days/weeks", "milestone": true/false},
    ...
  ],
  "total_duration": "X weeks/months",
  "tips": ["tip1", "tip2"]
}
Keep it to 5-10 tasks max. Be specific and actionable."""},
        {"role": "user", "content": message},
    ]

    response = llm.generate(plan_prompt)

    # Try to parse JSON from response
    try:
        # Extract JSON from response
        json_match = re.search(r"\{[\s\S]*\}", response)
        if json_match:
            plan_data = json.loads(json_match.group())
        else:
            # Fallback — return as text plan
            return {"title": message, "response": response, "type": "text"}
    except json.JSONDecodeError:
        return {"title": message, "response": response, "type": "text"}

    # Save plan to DB
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            "INSERT INTO plans (user_id, title, tasks, progress, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, plan_data.get("title", message), json.dumps(plan_data.get("tasks", [])), 0, time.strftime("%Y-%m-%dT%H:%M:%SZ")),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Save plan error: {e}")
    finally:
        conn.close()

    return {"type": "plan", **plan_data}


def get_plans(user_id: str) -> list[dict]:
    """Get all plans for a user."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        rows = conn.execute(
            "SELECT id, title, tasks, progress, created_at FROM plans WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
        plans = []
        for r in rows:
            tasks = json.loads(r[2]) if r[2] else []
            plans.append({"id": r[0], "title": r[1], "tasks": tasks, "progress": r[3], "created_at": r[4]})
        return plans
    except Exception:
        return []
    finally:
        conn.close()


def update_progress(user_id: str, plan_id: int, progress: int) -> bool:
    """Update plan progress percentage."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("UPDATE plans SET progress = ? WHERE id = ? AND user_id = ?", (progress, plan_id, user_id))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()
