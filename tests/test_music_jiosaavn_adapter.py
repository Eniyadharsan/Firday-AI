"""Unit tests for the JioSaavn music source adapter."""

from unittest.mock import patch, MagicMock

import pytest
import requests

from jarvis.modules.music_jiosaavn_adapter import JioSaavnAdapter
from jarvis.modules.music_models import TrackResult


@pytest.fixture
def adapter():
    """Create a JioSaavnAdapter instance."""
    return JioSaavnAdapter()


def _mock_api_response(results: list[dict], success: bool = True) -> dict:
    """Build a mock JioSaavn API response."""
    return {
        "success": success,
        "data": {
            "results": results,
        },
    }


def _sample_track_data(
    track_id: str = "abc123",
    name: str = "Tum Hi Ho",
    primary_artist: str = "Arijit Singh",
    duration: int = 240,
    url: str = "https://www.jiosaavn.com/song/tum-hi-ho/abc123",
) -> dict:
    """Build a sample track dict matching saavn.dev API response format."""
    return {
        "id": track_id,
        "name": name,
        "duration": duration,
        "url": url,
        "artists": {
            "primary": [{"name": primary_artist}],
        },
        "image": [
            {"url": "https://c.saavncdn.com/img_50x50.jpg"},
            {"url": "https://c.saavncdn.com/img_150x150.jpg"},
            {"url": "https://c.saavncdn.com/img_500x500.jpg"},
        ],
    }


class TestSourceName:
    def test_source_name_is_jiosaavn(self, adapter):
        assert adapter.source_name == "jiosaavn"


class TestIsAvailable:
    def test_always_returns_true(self, adapter):
        assert adapter.is_available() is True


class TestSearch:
    @patch("jarvis.modules.music_jiosaavn_adapter.requests.get")
    def test_successful_search(self, mock_get, adapter):
        mock_response = MagicMock()
        mock_response.json.return_value = _mock_api_response([
            _sample_track_data(),
        ])
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        results = adapter.search("Tum Hi Ho", max_results=5)

        assert len(results) == 1
        track = results[0]
        assert isinstance(track, TrackResult)
        assert track.id == "abc123"
        assert track.title == "Tum Hi Ho"
        assert track.artist == "Arijit Singh"
        assert track.source == "jiosaavn"
        assert track.source_url == "https://www.jiosaavn.com/song/tum-hi-ho/abc123"
        assert track.duration_seconds == 240
        assert track.is_devotional is False
        assert track.tradition is None
        assert track.match_score == 0.0
        assert "500x500" in track.thumbnail_url

    @patch("jarvis.modules.music_jiosaavn_adapter.requests.get")
    def test_uses_correct_api_params(self, mock_get, adapter):
        mock_response = MagicMock()
        mock_response.json.return_value = _mock_api_response([])
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        adapter.search("test query", max_results=7)

        mock_get.assert_called_once_with(
            "https://saavn.dev/api/search/songs",
            params={"query": "test query", "limit": 7},
            timeout=5,
        )

    @patch("jarvis.modules.music_jiosaavn_adapter.requests.get")
    def test_timeout_returns_empty_list(self, mock_get, adapter):
        mock_get.side_effect = requests.exceptions.Timeout()

        results = adapter.search("any query")
        assert results == []

    @patch("jarvis.modules.music_jiosaavn_adapter.requests.get")
    def test_connection_error_returns_empty_list(self, mock_get, adapter):
        mock_get.side_effect = requests.exceptions.ConnectionError()

        results = adapter.search("any query")
        assert results == []

    @patch("jarvis.modules.music_jiosaavn_adapter.requests.get")
    def test_http_error_returns_empty_list(self, mock_get, adapter):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=MagicMock(status_code=500)
        )
        mock_get.return_value = mock_response

        results = adapter.search("any query")
        assert results == []

    @patch("jarvis.modules.music_jiosaavn_adapter.requests.get")
    def test_invalid_json_returns_empty_list(self, mock_get, adapter):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.side_effect = ValueError("No JSON")
        mock_get.return_value = mock_response

        results = adapter.search("any query")
        assert results == []

    @patch("jarvis.modules.music_jiosaavn_adapter.requests.get")
    def test_missing_id_skips_track(self, mock_get, adapter):
        mock_response = MagicMock()
        mock_response.json.return_value = _mock_api_response([
            {"name": "No ID Song", "artists": {"primary": [{"name": "Artist"}]}},
        ])
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        results = adapter.search("test")
        assert results == []

    @patch("jarvis.modules.music_jiosaavn_adapter.requests.get")
    def test_missing_name_skips_track(self, mock_get, adapter):
        mock_response = MagicMock()
        mock_response.json.return_value = _mock_api_response([
            {"id": "xyz", "artists": {"primary": [{"name": "Artist"}]}},
        ])
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        results = adapter.search("test")
        assert results == []

    @patch("jarvis.modules.music_jiosaavn_adapter.requests.get")
    def test_respects_max_results(self, mock_get, adapter):
        tracks = [_sample_track_data(track_id=f"id_{i}", name=f"Song {i}") for i in range(10)]
        mock_response = MagicMock()
        mock_response.json.return_value = _mock_api_response(tracks)
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        results = adapter.search("songs", max_results=3)
        assert len(results) == 3

    @patch("jarvis.modules.music_jiosaavn_adapter.requests.get")
    def test_fallback_artist_from_primaryArtists_field(self, mock_get, adapter):
        """Test fallback when artists.primary is empty but primaryArtists exists."""
        mock_response = MagicMock()
        mock_response.json.return_value = _mock_api_response([
            {
                "id": "track1",
                "name": "Song Title",
                "duration": 180,
                "url": "https://www.jiosaavn.com/song/x/track1",
                "artists": {"primary": []},
                "primaryArtists": "Fallback Artist",
                "image": [{"url": "https://img.com/thumb.jpg"}],
            },
        ])
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        results = adapter.search("test")
        assert len(results) == 1
        assert results[0].artist == "Fallback Artist"

    @patch("jarvis.modules.music_jiosaavn_adapter.requests.get")
    def test_handles_image_as_string(self, mock_get, adapter):
        """Test handling when image field is a plain string URL."""
        mock_response = MagicMock()
        mock_response.json.return_value = _mock_api_response([
            {
                "id": "track1",
                "name": "Song",
                "duration": 100,
                "url": "https://jiosaavn.com/song/x/track1",
                "artists": {"primary": [{"name": "Artist"}]},
                "image": "https://img.com/direct.jpg",
            },
        ])
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        results = adapter.search("test")
        assert len(results) == 1
        assert results[0].thumbnail_url == "https://img.com/direct.jpg"

    @patch("jarvis.modules.music_jiosaavn_adapter.requests.get")
    def test_duration_none_when_missing(self, mock_get, adapter):
        mock_response = MagicMock()
        mock_response.json.return_value = _mock_api_response([
            {
                "id": "track1",
                "name": "Song",
                "url": "https://jiosaavn.com/song/x/track1",
                "artists": {"primary": [{"name": "Artist"}]},
                "image": [],
            },
        ])
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        results = adapter.search("test")
        assert len(results) == 1
        assert results[0].duration_seconds is None

    @patch("jarvis.modules.music_jiosaavn_adapter.requests.get")
    def test_request_exception_returns_empty_list(self, mock_get, adapter):
        mock_get.side_effect = requests.exceptions.RequestException("generic error")

        results = adapter.search("any query")
        assert results == []
