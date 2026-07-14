"""Video generation module — uses free AI video APIs."""

import re
from urllib.parse import quote


def is_video_request(message: str) -> bool:
    """Detect if user wants to generate a video."""
    lower = message.lower()
    return bool(
        re.search(r"\b(generate|create|make|produce|render)\b", lower) and
        re.search(r"\b(video|clip|animation|movie|film|reel|short)\b", lower)
    )


def generate_video_url(prompt: str) -> str:
    """Generate video using Pollinations.ai video endpoint."""
    clean = re.sub(
        r"\b(generate|create|make|produce|render|a|an|the|video|clip|of|for|me)\b",
        "", prompt, flags=re.IGNORECASE
    ).strip() or prompt
    # Pollinations video endpoint
    return f"https://video.pollinations.ai/prompt/{quote(clean)}?duration=5"


def get_video_response(prompt: str) -> dict:
    """Get complete video generation response."""
    url = generate_video_url(prompt)
    return {
        "reply": "Generating your video, Sir. This may take a moment.",
        "action": "show_video",
        "videoUrl": url,
        "videoPrompt": prompt,
    }
