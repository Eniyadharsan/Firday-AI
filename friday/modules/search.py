"""Web search module — DuckDuckGo instant answers."""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from loguru import logger

# Reuse connections
_session = requests.Session()
_session.mount("https://", HTTPAdapter(pool_connections=3, pool_maxsize=5))


def web_search(query: str) -> str:
    """Search DuckDuckGo for instant answers and related topics."""
    try:
        r = _session.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
            timeout=4,
        )
        r.raise_for_status()
        data = r.json()
        parts: list[str] = []

        if data.get("Answer"):
            parts.append(data["Answer"])
        if data.get("AbstractText"):
            parts.append(data["AbstractText"])
        if data.get("Infobox", {}).get("content"):
            facts = [f"{c.get('label','')}: {c.get('value','')}" for c in data["Infobox"]["content"][:5]]
            parts.extend(f for f in facts if f.strip(": "))
        if data.get("RelatedTopics"):
            for topic in data["RelatedTopics"][:5]:
                if isinstance(topic, dict) and topic.get("Text"):
                    parts.append(topic["Text"])

        return "\n".join(parts)
    except requests.Timeout:
        logger.warning("Search timeout")
        return ""
    except requests.HTTPError as e:
        logger.error(f"Search HTTP error: {e}")
        return ""
    except Exception as e:
        logger.error(f"Search error: {e}")
        return ""
