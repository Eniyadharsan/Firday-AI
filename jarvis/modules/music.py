"""Music module — detects play requests and returns YouTube URLs."""

import re
from urllib.parse import quote


def is_music_request(message: str) -> bool:
    """Check if the message is a music play request."""
    lower = message.lower()
    return bool(
        re.search(r"\b(play|put on|queue)\b", lower) and
        (re.search(r"\b(song|music|track)\b", lower) or lower.startswith("play "))
    )


def get_youtube_url(song_query: str) -> str:
    """Generate YouTube search URL for a song."""
    return f"https://www.youtube.com/results?search_query={quote(song_query)}"


def extract_song_from_reply(reply: str) -> str | None:
    """Extract song name from LLM reply containing [PLAY_MUSIC:...]."""
    match = re.search(r"\[PLAY_MUSIC:(.+?)\]", reply)
    return match.group(1).strip() if match else None
