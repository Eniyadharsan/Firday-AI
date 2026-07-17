"""Image generation module — uses Pollinations.ai (free, no key)."""

import re
from urllib.parse import quote


# Words that indicate audio/music intent, NOT image
_AUDIO_KEYWORDS = re.compile(
    r"\b(song|songs|music|track|tracks|playlist|album|artist|singer|band|"
    r"listen|listening|audio|podcast|beat|beats|tune|tunes|melody|melodies|"
    r"sing|singing|rap|rapping|concert|lyric|lyrics)\b"
)


def is_image_request(message: str) -> bool:
    """Detect if user wants to generate an image."""
    lower = message.lower()

    # Exclusion: if the message is clearly about music/audio, do NOT treat as image
    if _AUDIO_KEYWORDS.search(lower):
        return False

    # Pattern 1: "give/show/get me [something]" — only if it's about a visual subject
    if re.search(r"\b(give|show|get)\s+me\b", lower):
        # Only match if followed by a visual keyword or "a/an/the" + visual keyword
        if re.search(r"\b(image|picture|photo|map|diagram|chart|illustration|drawing|poster|wallpaper|logo|portrait|scene)\b", lower):
            return True
        # Also match "show me [place/thing]" patterns that imply visuals (e.g., "show me paris")
        # but NOT generic "show me something" without visual context
        if re.search(r"\b(give|show|get)\s+me\s+(a\s+|an\s+|the\s+)?(picture|image|photo|map|drawing|diagram|chart|poster|logo|illustration)\b", lower):
            return True
        # "show me X" where X is not a known non-visual thing — still allow for map/location lookups
        if re.search(r"\bmap\b", lower):
            return True
        return False

    # Pattern 2: "map of [place]" or "[place] map"
    if re.search(r"\bmap\b", lower):
        return True

    # Pattern 3: action + visual subject
    action = re.search(r"\b(generate|create|make|draw|design|imagine|render|picture|image|photo)\b", lower)
    subject = re.search(r"\b(image|picture|photo|illustration|art|drawing|poster|wallpaper|logo|portrait|scene|diagram|chart|map)\b", lower)
    if action and subject:
        return True

    # Pattern 4: "create/generate/draw [anything visual]"
    if re.search(r"\b(generate|create|draw|design)\b.*\b(image|picture|photo|poster|logo|art|map|diagram)\b", lower):
        return True

    return False


def generate_image_url(prompt: str, width: int = 1024, height: int = 1024) -> str:
    """Generate image URL from Pollinations.ai. Keeps the full meaning of the prompt."""
    # Only remove command words, keep everything descriptive
    clean = re.sub(r"^\s*(give me|show me|get me|create|generate|make|draw|can you|please)\s*", "", prompt, flags=re.IGNORECASE).strip()
    # If it's a map request, enhance the prompt
    if "map" in clean.lower():
        clean = f"detailed geographic map of {clean.replace('map of', '').replace('map', '').strip()}, cartographic style, clear labels, high resolution"
    return f"https://image.pollinations.ai/prompt/{quote(clean or prompt)}?width={width}&height={height}&nologo=true"
