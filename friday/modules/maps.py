"""Maps module — detects map/location requests and extracts the target place.

Real interactive maps are rendered on the frontend (Leaflet + OpenStreetMap /
satellite tiles). This module only decides whether a message is a map request
and extracts the place/location string to center the map on.
"""

import re

# Interrogatives / references that are questions, NOT map requests
_QUESTION = re.compile(
    r"^(what|which|why|how|who|whom|whose|is|are|was|were|does|did|explain|tell me|describe)\b"
)
_REFERENCE = re.compile(
    r"\b(shown|showed|you (gave|generated|created|made|showed))\b"
)

# Phrases that indicate a map / navigation intent
_MAP_INTENT = re.compile(
    r"\b(map|maps|directions?|navigate|navigation|route|where is|locate|location of|"
    r"how (do i|to) (get|reach)|show me the way)\b"
)


def is_map_request(message: str) -> bool:
    """Return True if the message is asking to see a real map / location."""
    lower = message.lower().strip()

    # Questions about an existing map are not new map requests
    if _QUESTION.match(lower) or _REFERENCE.search(lower):
        return False

    return bool(_MAP_INTENT.search(lower))


def extract_place(message: str) -> str:
    """Extract the location/place from a map request. Returns '' if none found."""
    text = message.strip()

    # Try to capture what follows common map/navigation phrases
    patterns = [
        r"\bmap\s+of\s+(.+)",
        r"\bdirections?\s+(?:to|for|from)\s+(.+)",
        r"\bnavigate\s+(?:to|me to)?\s*(.+)",
        r"\broute\s+(?:to|from)\s+(.+)",
        r"\bwhere\s+is\s+(.+)",
        r"\blocation\s+of\s+(.+)",
        r"\blocate\s+(.+)",
        r"\bshow\s+me\s+(?:a\s+|the\s+)?map\s+of\s+(.+)",
        r"\bshow\s+me\s+(.+?)\s+(?:on\s+(?:the\s+)?map|map)\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            place = m.group(1).strip()
            place = _clean_place(place)
            if place:
                return place

    # "<place> map" e.g. "India map", "Paris map"
    m = re.search(r"^(.+?)\s+maps?\b", text, re.IGNORECASE)
    if m:
        place = _clean_place(m.group(1).strip())
        # Avoid returning command words as the place
        if place and place.lower() not in ("show me a", "show me", "give me a", "give me", "a", "the"):
            return place

    return ""


def _clean_place(place: str) -> str:
    """Strip trailing punctuation, filler words, and command remnants."""
    place = re.sub(r"[?!.,]+$", "", place).strip()
    # Remove leading filler/command words
    place = re.sub(r"^(a|an|the|please|for me|me)\s+", "", place, flags=re.IGNORECASE).strip()
    # Remove trailing polite filler
    place = re.sub(r"\s+(please|now|for me|sir)$", "", place, flags=re.IGNORECASE).strip()
    return place
