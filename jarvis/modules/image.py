"""Image generation module — uses Pollinations.ai (free, no key)."""

import re
from urllib.parse import quote


def is_image_request(message: str) -> bool:
    """Detect if user wants to generate an image."""
    lower = message.lower()

    # Pattern 1: "give/show/get me [something]"
    if re.search(r"\b(give|show|get)\s+me\b", lower):
        return True

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
