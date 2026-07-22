"""YouTube music source adapter.

Implements the MusicSourceAdapter protocol using YouTube Data API v3.
This adapter encapsulates all YouTube-specific search logic and returns
standardized TrackResult objects.
"""

from __future__ import annotations

import os

import requests
from loguru import logger

from friday.modules.music import extract_artist_title
from friday.modules.music_models import TrackResult


class YouTubeAdapter:
    """Music source adapter for YouTube Data API v3.

    Searches YouTube's music category and returns results as TrackResult
    objects with source="youtube".
    """

    _API_URL = "https://www.googleapis.com/youtube/v3/search"
    _WATCH_URL = "https://www.youtube.com/watch?v="

    @property
    def source_name(self) -> str:
        """Return the identifier for this music source."""
        return "youtube"

    def search(self, query: str, max_results: int = 10) -> list[TrackResult]:
        """Search YouTube for music tracks.

        Args:
            query: The search query string.
            max_results: Maximum number of results to return.

        Returns:
            A list of TrackResult objects from YouTube, ordered by relevance.
            Returns an empty list on any error (timeout, network, HTTP errors).
        """
        api_key = os.environ.get("YOUTUBE_API_KEY")
        if not api_key:
            logger.warning("YOUTUBE_API_KEY not set in environment — cannot search tracks")
            return []

        params = {
            "part": "snippet",
            "type": "video",
            "videoCategoryId": "10",  # Music category
            "q": query,
            "maxResults": max_results,
            "key": api_key,
        }

        try:
            response = requests.get(self._API_URL, params=params, timeout=10)
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
        tracks: list[TrackResult] = []

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

            tracks.append(TrackResult(
                id=video_id,
                title=title,
                artist=artist,
                thumbnail_url=thumbnail_url,
                source="youtube",
                source_url=f"{self._WATCH_URL}{video_id}",
            ))

        return tracks

    def is_available(self) -> bool:
        """Check whether YouTube API is configured and reachable.

        Returns:
            True if YOUTUBE_API_KEY is set, False otherwise.
        """
        return bool(os.environ.get("YOUTUBE_API_KEY"))
