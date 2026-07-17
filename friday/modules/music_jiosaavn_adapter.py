"""JioSaavn music source adapter.

Implements the MusicSourceAdapter protocol using the saavn.dev public API.
This adapter encapsulates all JioSaavn-specific search logic and returns
standardized TrackResult objects.
"""

import requests
from loguru import logger

from friday.modules.music_models import TrackResult


class JioSaavnAdapter:
    """Music source adapter for JioSaavn via the saavn.dev public API.

    Searches JioSaavn's music catalog and returns results as TrackResult
    objects with source="jiosaavn". No API key is required.
    """

    _API_URL = "https://saavn.dev/api/search/songs"

    @property
    def source_name(self) -> str:
        """Return the identifier for this music source."""
        return "jiosaavn"

    def search(self, query: str, max_results: int = 10) -> list[TrackResult]:
        """Search JioSaavn for music tracks.

        Args:
            query: The search query string (may contain any Unicode script).
            max_results: Maximum number of results to return.

        Returns:
            A list of TrackResult objects from JioSaavn, ordered by relevance.
            Returns an empty list on any error (timeout, network, HTTP errors).
        """
        params = {
            "query": query,
            "limit": max_results,
        }

        try:
            response = requests.get(self._API_URL, params=params, timeout=5)
            response.raise_for_status()
        except requests.exceptions.Timeout:
            logger.warning("JioSaavn API request timed out for query: {}", query)
            return []
        except requests.exceptions.ConnectionError:
            logger.warning("Network error while searching JioSaavn for query: {}", query)
            return []
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            logger.warning("JioSaavn API HTTP error {} for query: {}", status, query)
            return []
        except requests.exceptions.RequestException as e:
            logger.warning("Unexpected error searching JioSaavn for query: {} — {}", query, e)
            return []

        try:
            data = response.json()
        except (ValueError, AttributeError):
            logger.warning("JioSaavn API returned invalid JSON for query: {}", query)
            return []

        # The saavn.dev API returns data in {"success": true, "data": {"results": [...]}}
        results_data = data.get("data", {}).get("results", [])
        tracks: list[TrackResult] = []

        for item in results_data:
            track = self._parse_track(item)
            if track:
                tracks.append(track)
            if len(tracks) >= max_results:
                break

        return tracks

    def _parse_track(self, item: dict) -> TrackResult | None:
        """Parse a single track item from the JioSaavn API response.

        Args:
            item: A dictionary representing a single song from the API response.

        Returns:
            A TrackResult object, or None if required fields are missing.
        """
        track_id = item.get("id", "")
        title = item.get("name", "")

        if not track_id or not title:
            return None

        # Extract primary artist name
        artists = item.get("artists", {})
        if isinstance(artists, dict):
            primary_artists = artists.get("primary", [])
            if primary_artists and isinstance(primary_artists, list):
                artist = primary_artists[0].get("name", "Unknown Artist")
            else:
                artist = item.get("primaryArtists", "Unknown Artist")
        else:
            artist = item.get("primaryArtists", "Unknown Artist")

        # Extract thumbnail URL — prefer higher quality images
        image_list = item.get("image", [])
        thumbnail_url = ""
        if isinstance(image_list, list) and image_list:
            # Images are typically ordered by quality; pick the last (highest quality)
            thumbnail_url = image_list[-1].get("url", "") if isinstance(image_list[-1], dict) else ""
        elif isinstance(image_list, str):
            thumbnail_url = image_list

        # Extract source URL
        source_url = item.get("url", "")

        # Extract duration in seconds
        duration_seconds = None
        duration_value = item.get("duration")
        if duration_value is not None:
            try:
                duration_seconds = int(duration_value)
            except (ValueError, TypeError):
                duration_seconds = None

        return TrackResult(
            id=track_id,
            title=title,
            artist=artist,
            thumbnail_url=thumbnail_url,
            source="jiosaavn",
            source_url=source_url,
            duration_seconds=duration_seconds,
            is_devotional=False,
            tradition=None,
            match_score=0.0,
        )

    def is_available(self) -> bool:
        """Check whether JioSaavn API is reachable.

        The saavn.dev API is public and requires no API key,
        so this always returns True.

        Returns:
            True — JioSaavn's public API requires no authentication.
        """
        return True
