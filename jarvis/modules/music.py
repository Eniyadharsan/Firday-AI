"""Music module — detects play requests and returns YouTube URLs."""

import os
import re
from urllib.parse import quote

import requests
from loguru import logger


def is_music_request(message: str) -> bool:
    """Check if the message is a music play request."""
    lower = message.lower()

    # Rule 1: "play " followed by at least one non-whitespace character
    if re.match(r"play \S", lower):
        return True

    # Rule 2: "put on" or "queue" followed by non-whitespace content
    if re.search(r"\bput on\s+\S", lower) or re.search(r"\bqueue\s+\S", lower):
        return True

    # Backward compatibility: trigger word + music keyword
    if re.search(r"\b(play|put on|queue)\b", lower) and re.search(r"\b(song|music|track)\b", lower):
        return True

    return False


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

    Returns:
        List of dicts with keys: video_id, title, artist, thumbnail_url
    """
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        logger.warning("YOUTUBE_API_KEY not set in environment — cannot search tracks")
        return []

    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "type": "video",
        "videoCategoryId": "10",  # Music category
        "q": query,
        "maxResults": max_results,
        "key": api_key,
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        logger.warning("YouTube API request timed out for query: {}", query)
        return []
    except requests.exceptions.ConnectionError:
        logger.warning("Network error while searching YouTube for query: {}", query)
        return []
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        if status == 403:
            logger.warning("YouTube API rate limit or quota exceeded for query: {}", query)
        elif status == 400:
            logger.warning("YouTube API bad request for query: {} — {}", query, e)
        else:
            logger.warning("YouTube API HTTP error {} for query: {}", status, query)
        return []
    except requests.exceptions.RequestException as e:
        logger.warning("Unexpected error searching YouTube for query: {} — {}", query, e)
        return []

    data = response.json()
    items = data.get("items", [])
    tracks = []

    for item in items:
        video_id = item.get("id", {}).get("videoId")
        snippet = item.get("snippet", {})
        raw_title = snippet.get("title", "")

        if not video_id:
            continue

        # Get thumbnail — prefer high quality, fall back to default
        thumbnails = snippet.get("thumbnails", {})
        thumbnail_url = (
            thumbnails.get("high", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url")
            or ""
        )

        artist, title = extract_artist_title(raw_title)

        tracks.append({
            "video_id": video_id,
            "title": title,
            "artist": artist,
            "thumbnail_url": thumbnail_url,
        })

    return tracks
