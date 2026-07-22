"""News module — fetches live news from Google News RSS with session reuse."""

from __future__ import annotations

import re
import time
import requests
from requests.adapters import HTTPAdapter
from loguru import logger
from friday.config import NEWS_REFRESH_INTERVAL

# Persistent session for news fetches
_session = requests.Session()
_session.mount("https://", HTTPAdapter(pool_connections=2, pool_maxsize=5))

# --- Cache ---
_cache: dict[str, str] = {"world": "", "tech": "", "business": ""}
_last_update: float = 0


def fetch_news(topic: str) -> str:
    """Fetch news headlines for a topic from Google News RSS."""
    try:
        r = _session.get(
            f"https://news.google.com/rss/search?q={requests.utils.quote(topic)}&hl=en",
            timeout=5,
        )
        r.raise_for_status()
        titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>", r.text)
        items: list[str] = []
        for match in titles[:8]:
            title = match[0] or match[1]
            if title and "Google News" not in title:
                items.append(title)
        return "\n".join(f"{i+1}. {t}" for i, t in enumerate(items))
    except requests.Timeout:
        logger.warning("News fetch timeout")
        return ""
    except Exception as e:
        logger.error(f"News error: {e}")
        return ""


def refresh_cache() -> None:
    """Refresh the news cache if stale."""
    global _last_update
    if time.time() - _last_update < NEWS_REFRESH_INTERVAL:
        return
    _cache["world"] = fetch_news("world news today")
    _cache["tech"] = fetch_news("technology AI")
    _cache["business"] = fetch_news("business markets")
    _last_update = time.time()


def get_cached_news(category: str = "world") -> str:
    """Get cached news for a category."""
    refresh_cache()
    return _cache.get(category, "")
