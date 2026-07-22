"""
AI Research Mode — Deep multi-source research with synthesis.

Flow:
1. Search the web (multiple queries)
2. Read/extract from multiple sources
3. Remove duplicates
4. Summarize findings
5. Generate citations
6. Return structured report
"""

from __future__ import annotations

import re
import time
import requests
from loguru import logger
from friday.modules import llm, search


def is_research_request(message: str) -> bool:
    """Detect if user wants deep research."""
    lower = message.lower()
    return bool(re.search(r"\b(research|deep dive|investigate|thorough|comprehensive|detailed analysis|report on|write a report)\b", lower))


def multi_search(topic: str) -> list[dict[str, str]]:
    """Search multiple angles of a topic."""
    queries = [
        topic,
        f"{topic} latest developments",
        f"{topic} pros and cons",
        f"{topic} expert opinion",
    ]

    all_results: list[dict[str, str]] = []
    seen_content: set[str] = set()

    for query in queries:
        result = search.web_search(query)
        if result:
            # Split into individual facts
            for line in result.split("\n"):
                line = line.strip()
                if line and len(line) > 20:
                    # Deduplicate
                    key = line[:50].lower()
                    if key not in seen_content:
                        seen_content.add(key)
                        all_results.append({"content": line, "query": query})

    return all_results


def fetch_news_context(topic: str) -> list[str]:
    """Fetch recent news about the topic."""
    try:
        r = requests.get(
            f"https://news.google.com/rss/search?q={requests.utils.quote(topic)}&hl=en",
            timeout=8,
        )
        titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>", r.text)
        items = []
        for match in titles[:6]:
            title = match[0] or match[1]
            if title and "Google News" not in title:
                items.append(title)
        return items
    except Exception:
        return []


def generate_research_report(topic: str) -> dict:
    """
    Generate a comprehensive research report.

    Returns structured report with:
    - Executive summary
    - Key findings
    - Details
    - Sources/citations
    - Conclusion
    """
    logger.info(f"Research mode: {topic}")
    start = time.time()

    # Step 1: Multi-angle web search
    search_results = multi_search(topic)
    logger.info(f"Found {len(search_results)} unique data points")

    # Step 2: Get news context
    news = fetch_news_context(topic)

    # Step 3: Compile context
    context_parts = [r["content"] for r in search_results[:15]]
    if news:
        context_parts.append("Recent news: " + " | ".join(news))
    context = "\n".join(context_parts)

    # Step 4: Generate structured report via LLM
    report_prompt = [
        {"role": "system", "content": """You are a research analyst. Generate a structured research report with these sections:

## Executive Summary
(2-3 sentences overview)

## Key Findings
(5-7 bullet points of the most important discoveries)

## Detailed Analysis
(3-4 paragraphs of in-depth analysis)

## Current Landscape
(What's happening now in this space)

## Recommendations
(3-5 actionable recommendations)

## Sources
(List the sources of information used)

Be factual, cite specific data points, avoid generic statements."""},
        {"role": "user", "content": f"Research topic: {topic}\n\nData gathered:\n{context}"},
    ]

    report_text = llm.generate(report_prompt)
    elapsed = round(time.time() - start, 1)

    return {
        "type": "research_report",
        "topic": topic,
        "report": report_text,
        "sources_count": len(search_results),
        "news_count": len(news),
        "time_taken": f"{elapsed}s",
    }
