"""Gaana music source adapter.

Implements the MusicSourceAdapter protocol using Gaana's public search API.
This adapter encapsulates all Gaana-specific search logic and returns
standardized TrackResult objects.

Note: Gaana's public API may not always be accessible without authentication.
This adapter gracefully handles failures by returning an empty result list,
allowing the aggregator to continue with other available sources.
"""

from __future__ import annotations

import requests
from loguru import logger

from friday.modules.music_models import TrackResult


class GaanaAdapter:
    """Music source adapter for Gaana's public search API.

    Searches Gaana's song catalog and returns results as TrackResult
    objects with source="gaana". If the API is unreachable or returns
    errors, the adapter gracefully returns an empty list.
    """

    _API_URL = "https://gaana.com/apiv2/search"
    _SONG_URL_PREFIX = "https://gaana.com/song/"

    @property
    def source_name(self) -> str:
        """Return the identifier for this music source."""
        return "gaana"

    def search(self, query: str, max_results: int = 10) -> list[TrackResult]:
        """Search Gaana for music tracks.

        Args:
            query: The search query string (may contain any Unicode script).
            max_results: Maximum number of results to return.

        Returns:
            A list of TrackResult objects from Gaana, ordered by relevance.
            Returns an empty list on any error (timeout, network, HTTP errors,
            or if the API is not publicly accessible).
        """
        params = {
            "query": query,
            "type": "song",
            "language": "all",
        }

        try:
            response = requests.get(self._API_URL, params=params, timeout=5)
            response.raise_for_status()
        except requests.exceptions.Timeout:
            logger.warning("Gaana API request timed out for query: {}", query)
            return []
        except requests.exceptions.ConnectionError:
            logger.warning("Network error while searching Gaana for query: {}", query)
            return []
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            logger.warning("Gaana API HTTP error {} for query: {}", status, query)
            return []
        except requests.exceptions.RequestException as e:
            logger.warning("Unexpected error searching Gaana for query: {} — {}", query, e)
            return []

        try:
            data = response.json()
        except (ValueError, AttributeError):
            logger.warning("Gaana API returned invalid JSON for query: {}", query)
            return []

        # Gaana API response structure may vary; try common response shapes
        tracks_data = self._extract_tracks(data)
        tracks: list[TrackResult] = []

        for item in tracks_data[:max_results]:
            track = self._parse_track(item)
            if track is not None:
                tracks.append(track)

        return tracks

    def is_available(self) -> bool:
        """Check whether Gaana API is reachable.

        Returns:
            True — Gaana's public API does not require API keys.
            Actual availability is determined at search time.
        """
        return True

    def _extract_tracks(self, data: dict) -> list[dict]:
        """Extract track list from Gaana API response.

        Handles multiple possible response structures from the Gaana API.

        Args:
            data: Parsed JSON response from the API.

        Returns:
            A list of track dictionaries, or empty list if structure is
            unrecognized.
        """
        # Try common Gaana response structures
        # Structure 1: {"gr": [{"gd": [...tracks...]}]}
        if "gr" in data:
            gr = data["gr"]
            if isinstance(gr, list):
                for group in gr:
                    if isinstance(group, dict) and "gd" in group:
                        gd = group["gd"]
                        if isinstance(gd, list):
                            return gd

        # Structure 2: {"tracks": [...]}
        if "tracks" in data:
            tracks = data["tracks"]
            if isinstance(tracks, list):
                return tracks

        # Structure 3: {"results": [...]}
        if "results" in data:
            results = data["results"]
            if isinstance(results, list):
                return results

        # Structure 4: Direct list at top level under "entities"
        if "entities" in data:
            entities = data["entities"]
            if isinstance(entities, list):
                return entities

        return []

    def _parse_track(self, item: dict) -> TrackResult | None:
        """Parse a single track from Gaana API response item.

        Maps Gaana's response fields to a standardized TrackResult.

        Args:
            item: A dictionary representing a single track from the API.

        Returns:
            A TrackResult object, or None if essential fields are missing.
        """
        if not isinstance(item, dict):
            return None

        # Extract track ID — try multiple possible field names
        track_id = str(
            item.get("track_id")
            or item.get("seo")
            or item.get("id")
            or item.get("song_id")
            or ""
        )
        if not track_id:
            return None

        # Extract title
        title = str(
            item.get("title")
            or item.get("track_title")
            or item.get("name")
            or ""
        )
        if not title:
            return None

        # Extract artist — try multiple field patterns
        artist = str(
            item.get("artist")
            or item.get("artists_name")
            or item.get("primary_artists")
            or item.get("singer")
            or "Unknown Artist"
        )

        # Extract thumbnail/artwork URL
        thumbnail_url = str(
            item.get("artwork")
            or item.get("artwork_large")
            or item.get("artwork_web")
            or item.get("atw")
            or item.get("image")
            or ""
        )

        # Build source URL from SEO slug or track ID
        seo = item.get("seo") or item.get("permalink") or track_id
        source_url = f"{self._SONG_URL_PREFIX}{seo}"

        # Extract duration in seconds if available
        duration_seconds = None
        duration_raw = item.get("duration") or item.get("total_duration")
        if duration_raw is not None:
            try:
                duration_seconds = int(duration_raw)
            except (ValueError, TypeError):
                pass

        return TrackResult(
            id=track_id,
            title=title,
            artist=artist,
            thumbnail_url=thumbnail_url,
            source="gaana",
            source_url=source_url,
            duration_seconds=duration_seconds,
            is_devotional=False,
            tradition=None,
            match_score=0.0,
        )
