"""Tests for the music search and autocomplete API endpoints in app.py.

Validates:
- GET /music/autocomplete?q=... returns suggestions
- GET /music/search?q=... returns backward-compatible results with new fields
- Proper HTTP error codes (400, 503) for invalid/failed scenarios
- Backward compatibility: response always contains 'results' and 'query'
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from friday.modules.music_models import AggregatedResult, Suggestion, TrackResult


@pytest.fixture
def client():
    """Create a Flask test client with auth bypassed."""
    from app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def bypass_auth(monkeypatch):
    """Bypass the @require_auth decorator by making get_user_from_request return a valid user."""
    from friday.modules import auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_user_from_request", lambda: {"sub": "test-user", "email": "test@friday"})


@pytest.fixture
def mock_engine():
    """Mock the _get_search_engine function to return a controlled engine."""
    engine = MagicMock()
    with patch("app._get_search_engine", return_value=engine):
        yield engine


class TestMusicAutocomplete:
    """Tests for GET /music/autocomplete endpoint."""

    def test_returns_suggestions(self, client, mock_engine):
        mock_engine.autocomplete.return_value = [
            Suggestion(title="Song A", artist="Artist 1", thumbnail_url="http://img.com/1.jpg", video_id="abc123", source="youtube"),
            Suggestion(title="Song B", artist="Artist 2", thumbnail_url="http://img.com/2.jpg", video_id="def456", source="jiosaavn"),
        ]

        resp = client.get("/music/autocomplete?q=so")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "suggestions" in data
        assert len(data["suggestions"]) == 2
        assert data["suggestions"][0]["title"] == "Song A"
        assert data["suggestions"][0]["video_id"] == "abc123"
        assert data["suggestions"][1]["source"] == "jiosaavn"

    def test_empty_query_returns_empty_suggestions(self, client, mock_engine):
        mock_engine.autocomplete.return_value = []

        resp = client.get("/music/autocomplete?q=")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["suggestions"] == []

    def test_suggestion_fields_complete(self, client, mock_engine):
        mock_engine.autocomplete.return_value = [
            Suggestion(title="Test", artist="Art", thumbnail_url="http://t.com/x.jpg", video_id="vid1", source="gaana"),
        ]

        resp = client.get("/music/autocomplete?q=te")
        data = resp.get_json()
        s = data["suggestions"][0]
        assert set(s.keys()) == {"title", "artist", "thumbnail_url", "video_id", "source"}


class TestMusicSearch:
    """Tests for GET /music/search endpoint."""

    def test_empty_query_returns_400(self, client, mock_engine):
        mock_engine.validate_query.return_value = "Query parameter 'q' is required"

        resp = client.get("/music/search?q=")
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data
        assert "required" in data["error"].lower()

    def test_too_long_query_returns_400(self, client, mock_engine):
        mock_engine.validate_query.return_value = "Query must be 200 characters or fewer"

        resp = client.get("/music/search?q=" + "x" * 201)
        assert resp.status_code == 400
        data = resp.get_json()
        assert "200" in data["error"]

    def test_all_sources_failed_returns_503(self, client, mock_engine):
        mock_engine.validate_query.return_value = None
        mock_engine.search.return_value = AggregatedResult(
            results=[],
            sources_queried=["youtube", "jiosaavn", "gaana"],
            sources_failed=["youtube", "jiosaavn", "gaana"],
        )

        resp = client.get("/music/search?q=test")
        assert resp.status_code == 503
        data = resp.get_json()
        assert "unavailable" in data["error"].lower()

    def test_successful_search_returns_results(self, client, mock_engine):
        mock_engine.validate_query.return_value = None
        mock_engine.search.return_value = AggregatedResult(
            results=[
                TrackResult(
                    id="yt123",
                    title="Test Song",
                    artist="Test Artist",
                    thumbnail_url="http://img.com/t.jpg",
                    source="youtube",
                    source_url="http://youtube.com/watch?v=yt123",
                    duration_seconds=240,
                    is_devotional=False,
                    tradition=None,
                    match_score=0.95,
                ),
            ],
            sources_queried=["youtube", "jiosaavn", "gaana"],
            sources_failed=[],
        )

        resp = client.get("/music/search?q=test+song")
        assert resp.status_code == 200
        data = resp.get_json()

        # Backward compatibility: 'results' and 'query' always present
        assert "results" in data
        assert "query" in data
        assert data["query"] == "test song"

        # Result fields
        r = data["results"][0]
        assert r["video_id"] == "yt123"
        assert r["title"] == "Test Song"
        assert r["artist"] == "Test Artist"
        assert r["thumbnail_url"] == "http://img.com/t.jpg"
        assert r["source"] == "youtube"
        assert r["source_url"] == "http://youtube.com/watch?v=yt123"
        assert r["duration_seconds"] == 240
        assert r["is_devotional"] is False
        assert r["tradition"] is None
        assert r["match_score"] == 0.95

    def test_correction_included_when_present(self, client, mock_engine):
        mock_engine.validate_query.return_value = None
        mock_engine.search.return_value = AggregatedResult(
            results=[],
            correction="test song",
            sources_queried=["youtube"],
            sources_failed=[],
        )

        resp = client.get("/music/search?q=tets+song")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["correction"] == "test song"

    def test_correction_not_included_when_none(self, client, mock_engine):
        mock_engine.validate_query.return_value = None
        mock_engine.search.return_value = AggregatedResult(
            results=[],
            correction=None,
            sources_queried=["youtube"],
            sources_failed=[],
        )

        resp = client.get("/music/search?q=test")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "correction" not in data

    def test_devotional_context_included_when_present(self, client, mock_engine):
        mock_engine.validate_query.return_value = None
        mock_engine.search.return_value = AggregatedResult(
            results=[],
            devotional_context="Hindu Bhajan",
            sources_queried=["youtube"],
            sources_failed=[],
        )

        resp = client.get("/music/search?q=bhajan")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["devotional_context"] == "Hindu Bhajan"

    def test_devotional_context_not_included_when_none(self, client, mock_engine):
        mock_engine.validate_query.return_value = None
        mock_engine.search.return_value = AggregatedResult(
            results=[],
            devotional_context=None,
            sources_queried=["youtube"],
            sources_failed=[],
        )

        resp = client.get("/music/search?q=rock")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "devotional_context" not in data

    def test_partial_source_failure_still_returns_200(self, client, mock_engine):
        """When only some sources fail, results from working sources are returned."""
        mock_engine.validate_query.return_value = None
        mock_engine.search.return_value = AggregatedResult(
            results=[
                TrackResult(
                    id="js1",
                    title="Partial Result",
                    artist="Artist",
                    thumbnail_url="http://img.com/1.jpg",
                    source="jiosaavn",
                    source_url="http://jiosaavn.com/1",
                ),
            ],
            sources_queried=["youtube", "jiosaavn", "gaana"],
            sources_failed=["youtube", "gaana"],
        )

        resp = client.get("/music/search?q=partial")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["results"]) == 1

    def test_value_error_returns_400(self, client, mock_engine):
        mock_engine.validate_query.return_value = None
        mock_engine.search.side_effect = ValueError("Something went wrong")

        resp = client.get("/music/search?q=test")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "Something went wrong"
