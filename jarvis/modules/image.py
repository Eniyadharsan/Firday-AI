"""Image generation module — uses Pollinations.ai (free, no key)."""

import re
from urllib.parse import quote


def is_image_request(message: str) -> bool:
    """Detect if user wants to generate an image."""
    lower = message.lower()
    # Direct image request patterns
    action = re.search(r"\b(generate|create|make|draw|design|imagine|show|give|picture|image|photo|illustration|render)\b", lower)
    subject = re.search(r"\b(image|picture|photo|illustration|art|drawing|poster|wallpaper|logo|portrait|scene|girl|boy|man|woman|car|city|anime|cartoon|map|diagram|chart)\b", lower)
    # "give me X" pattern
    give_pattern = re.search(r"\b(give me|show me|get me)\b.*\b(map|image|picture|photo|diagram|chart|poster|logo)\b", lower)
    return bool((action and subject) or give_pattern)


def generate_image_url(prompt: str, width: int = 1024, height: int = 1024) -> str:
    """Generate image URL from Pollinations.ai."""
    # Keep meaningful words, only remove filler
    clean_prompt = re.sub(
        r"\b(generate|create|make|draw|design|imagine|give me|show me|get me|can you|please|an?|the)\b",
        "", prompt, flags=re.IGNORECASE
    ).strip() or prompt
    return f"https://image.pollinations.ai/prompt/{quote(clean_prompt)}?width={width}&height={height}&nologo=true"
