"""Image generation module — uses Pollinations.ai (free, no key)."""

import re
from urllib.parse import quote


def is_image_request(message: str) -> bool:
    """Detect if user wants to generate an image."""
    lower = message.lower()
    action = re.search(r"\b(generate|create|make|draw|design|imagine|show|give|picture|image|photo|illustration)\b", lower)
    subject = re.search(r"\b(image|picture|photo|illustration|art|drawing|poster|wallpaper|logo|portrait|scene|girl|boy|man|woman|car|city|anime|cartoon)\b", lower)
    return bool(action and subject)


def generate_image_url(prompt: str, width: int = 1024, height: int = 1024) -> str:
    """Generate image URL from Pollinations.ai."""
    clean_prompt = re.sub(
        r"\b(generate|create|make|draw|design|imagine|give me|show me|can you|an?|the|of|for|me|image|picture|photo)\b",
        "", prompt, flags=re.IGNORECASE
    ).strip() or prompt
    return f"https://image.pollinations.ai/prompt/{quote(clean_prompt)}?width={width}&height={height}&nologo=true"
