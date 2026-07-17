"""Music module — detects play requests and returns YouTube URLs."""

import re
from urllib.parse import quote


def is_music_request(message: str) -> bool:
    """Check if the message is a music play request."""
    lower = message.lower()

    # Rule 1: "play " followed by at least one non-whitespace character
    if re.match(r"play \S", lower):
        return True

    # Rule 2: "put on" or "queue" followed by non-whitespace content
    if re.search(r"\bput on\s+\S", lower) or re.search(r"\bqueue\s+\S", lower):
        return True

    # Rule 3: Backward compatibility: trigger word + music keyword
    if re.search(r"\b(play|put on|queue)\b", lower) and re.search(r"\b(song|music|track)\b", lower):
        return True

    # Rule 4: Natural phrasing — "can you play", "please play", "I want to play"
    if re.search(r"\b(can you|could you|please|i want to|i wanna|let's)\s+(play|listen to|hear)\b", lower):
        return True

    # Rule 5: "listen to" or "hear" + something (music intent)
    if re.search(r"\b(listen to|listening to)\s+\S", lower):
        return True

    # Rule 6: Music keywords with intent verbs — "show me a song", "give me a song"
    if re.search(r"\b(give|show|get)\s+me\b", lower) and re.search(r"\b(song|songs|music|track|tracks|playlist|tune|tunes)\b", lower):
        return True

    return False


def detect_playback_control(message: str) -> str | None:
    """Detect playback control commands (pause, resume, stop, next, previous).

    Returns one of: 'pause', 'resume', 'stop', 'next', 'previous', or None.
    These control an already-playing track and must be checked BEFORE
    is_music_request so "play" for resume isn't treated as a new search.
    """
    lower = message.lower().strip()

    # Pause: "pause", "pause music", "pause the song", "hold on"
    if re.search(r"\b(pause|hold)\b", lower) and not re.search(r"\bplay\b", lower):
        return "pause"

    # Stop: "stop", "stop music", "stop playing", "turn off the music", "shut it off"
    if lower in ("stop", "stop it", "stop please", "please stop"):
        return "stop"
    if re.search(r"\bstop\b", lower) and re.search(r"\b(music|song|track|playback|playing|it|tune|this|that)\b", lower):
        return "stop"
    if re.search(r"\b(turn off|shut off|shut down|kill|switch off)\b", lower) and re.search(r"\b(music|song|track|playback|playing|it|tune|this|that)\b", lower):
        return "stop"
    # Split forms: "turn it off", "shut it off", "switch the music off"
    if re.search(r"\b(turn|shut|switch)\b.*\boff\b", lower):
        return "stop"

    # Next: "next", "next song", "skip", "skip this", "play next"
    if re.search(r"\b(next|skip)\b", lower) and not re.search(r"\bplay\s+\w+\s+\w", lower):
        return "next"

    # Previous: "previous", "go back", "last song", "previous track"
    if re.search(r"\b(previous|prev|go back|last song|last track)\b", lower):
        return "previous"

    # Resume: "resume", "resume music", "continue", "unpause", "play" (bare)
    if re.search(r"\b(resume|unpause|continue)\b", lower):
        return "resume"
    if lower in ("play", "play it", "play music", "play the music", "continue playing", "keep playing"):
        return "resume"

    return None


def get_youtube_url(song_query: str) -> str:
    """Generate YouTube search URL for a song."""
    return f"https://www.youtube.com/results?search_query={quote(song_query)}"


def extract_song_from_reply(reply: str) -> str | None:
    """Extract song name from LLM reply containing [PLAY_MUSIC:...]."""
    match = re.search(r"\[PLAY_MUSIC:(.+?)\]", reply)
    return match.group(1).strip() if match else None


def extract_artist_title(youtube_title: str) -> tuple[str, str]:
    """
    Parse a YouTube video title into (artist, title).
    Handles common patterns like "Artist - Song Title",
    "Artist: Song Title", and "Song Title by Artist".

    Returns:
        Tuple of (artist_name, track_title)
    """
    # Clean up common YouTube suffixes before parsing
    cleaned = re.sub(
        r"\s*[\(\[]\s*(?:Official\s+(?:Video|Audio|Music\s+Video|Lyric\s+Video)|"
        r"Lyrics?|Audio|Music\s+Video|MV|HD|HQ|4K|Live|Visualizer|"
        r"Official\s+Visualizer)\s*[\)\]]",
        "",
        youtube_title,
        flags=re.IGNORECASE,
    ).strip()

    # Pattern 1: "Artist - Title"
    if " - " in cleaned:
        parts = cleaned.split(" - ", 1)
        artist = parts[0].strip()
        title = parts[1].strip()
        if artist and title:
            return (artist, title)

    # Pattern 2: "Artist: Title"
    if ": " in cleaned:
        parts = cleaned.split(": ", 1)
        artist = parts[0].strip()
        title = parts[1].strip()
        if artist and title:
            return (artist, title)

    # Pattern 3: "Title by Artist"
    if " by " in cleaned:
        parts = cleaned.rsplit(" by ", 1)
        title = parts[0].strip()
        artist = parts[1].strip()
        if artist and title:
            return (artist, title)

    # Fallback: no recognized pattern
    fallback_title = cleaned if cleaned else youtube_title.strip()
    if not fallback_title:
        fallback_title = youtube_title.strip() if youtube_title.strip() else "Unknown Title"
    return ("Unknown Artist", fallback_title)


def search_tracks(query: str, max_results: int = 10) -> list[dict]:
    """
    Search YouTube for music tracks using YouTube Data API v3.

    This is a backward-compatible wrapper around the YouTubeAdapter.
    Returns:
        List of dicts with keys: video_id, title, artist, thumbnail_url
    """
    from friday.modules.music_youtube_adapter import YouTubeAdapter

    adapter = YouTubeAdapter()
    results = adapter.search(query, max_results=max_results)

    # Convert TrackResult objects to legacy dict format for backward compatibility
    return [
        {
            "video_id": track.id,
            "title": track.title,
            "artist": track.artist,
            "thumbnail_url": track.thumbnail_url,
        }
        for track in results
    ]
