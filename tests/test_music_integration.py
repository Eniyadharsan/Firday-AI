"""Integration tests for end-to-end chat → playback flow.

Tests the complete flow from sending a music request via /chat through to
receiving structured playback metadata, and validates auth enforcement on
music endpoints.

Validates: Requirements 1.1, 1.2, 4.4, 6.5
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def client():
    """Create a Flask test client with auth bypassed for authenticated flow tests."""
    from app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def unauthenticated_client():
    """Create a Flask test client WITHOUT auth bypass for 401 tests."""
    from app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def bypass_auth(monkeypatch):
    """Bypass the @require_auth decorator for authenticated tests."""
    from friday.modules import auth as auth_mod

    monkeypatch.setattr(
        auth_mod, "get_user_from_request",
        lambda: {"sub": "test-user", "email": "test@friday"}
    )


@pytest.fixture(autouse=True)
def mock_memory(monkeypatch):
    """Mock memory module to avoid database calls during tests."""
    from friday.modules import memory as mem_mod

    monkeypatch.setattr(mem_mod, "save_message", lambda *args, **kwargs: None)


# =============================================================================
# Integration Test 1: End-to-end chat → playback (Requirements 1.1, 1.2)
# =============================================================================


class TestChatToPlaybackFlow:
    """Send 'play bohemian rhapsody' via POST /chat, verify response structure."""

    @patch("friday.modules.music.search_tracks")
    @patch("friday.modules.llm.generate")
    def test_play_bohemian_rhapsody_returns_play_music_embed(self, mock_llm, mock_search, client):
        """Full flow: chat message → music detection → search → structured response."""
        mock_llm.return_value = "Playing Bohemian Rhapsody by Queen for you!"
        mock_search.return_value = [
            {
                "video_id": "fJ9rUzIMcZQ",
                "title": "Bohemian Rhapsody",
                "artist": "Queen",
                "thumbnail_url": "https://i.ytimg.com/vi/fJ9rUzIMcZQ/hqdefault.jpg",
            }
        ]

        resp = client.post("/chat", json={
            "message": "play bohemian rhapsody",
            "sessionId": "integration-test-1"
        })

        assert resp.status_code == 200
        data = resp.get_json()

        # Verify action type
        assert data["action"] == "play_music_embed"

        # Verify track object structure
        assert "track" in data
        track = data["track"]
        assert "video_id" in track
        assert "title" in track
        assert "artist" in track
        assert "thumbnail_url" in track

        # Verify track field values
        assert track["video_id"] == "fJ9rUzIMcZQ"
        assert track["title"] == "Bohemian Rhapsody"
        assert track["artist"] == "Queen"
        assert track["thumbnail_url"].startswith("https://")

    @patch("friday.modules.music.search_tracks")
    @patch("friday.modules.llm.generate")
    def test_play_request_returns_reply_with_song_info(self, mock_llm, mock_search, client):
        """Response reply should contain the track title and artist."""
        mock_llm.return_value = "Sure thing!"
        mock_search.return_value = [
            {
                "video_id": "fJ9rUzIMcZQ",
                "title": "Bohemian Rhapsody",
                "artist": "Queen",
                "thumbnail_url": "https://i.ytimg.com/vi/fJ9rUzIMcZQ/hqdefault.jpg",
            }
        ]

        resp = client.post("/chat", json={
            "message": "play bohemian rhapsody",
            "sessionId": "integration-test-2"
        })
        data = resp.get_json()

        assert "reply" in data
        assert "Bohemian Rhapsody" in data["reply"]
        assert "Queen" in data["reply"]

    @patch("friday.modules.music.search_tracks")
    @patch("friday.modules.llm.generate")
    def test_play_request_includes_session_id(self, mock_llm, mock_search, client):
        """Response should echo back the sessionId."""
        mock_llm.return_value = "Here we go!"
        mock_search.return_value = [
            {
                "video_id": "dQw4w9WgXcQ",
                "title": "Never Gonna Give You Up",
                "artist": "Rick Astley",
                "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
            }
        ]

        resp = client.post("/chat", json={
            "message": "play never gonna give you up",
            "sessionId": "my-session-42"
        })
        data = resp.get_json()

        assert data["sessionId"] == "my-session-42"

    @patch("friday.modules.music.search_tracks")
    @patch("friday.modules.llm.generate")
    def test_play_request_track_has_valid_video_id(self, mock_llm, mock_search, client):
        """Track video_id should be a non-empty string (YouTube video ID format)."""
        mock_llm.return_value = "Playing!"
        mock_search.return_value = [
            {
                "video_id": "fJ9rUzIMcZQ",
                "title": "Bohemian Rhapsody",
                "artist": "Queen",
                "thumbnail_url": "https://i.ytimg.com/vi/fJ9rUzIMcZQ/hqdefault.jpg",
            }
        ]

        resp = client.post("/chat", json={
            "message": "play bohemian rhapsody",
            "sessionId": "s-vid-check"
        })
        data = resp.get_json()

        video_id = data["track"]["video_id"]
        assert isinstance(video_id, str)
        assert len(video_id) > 0

    @patch("friday.modules.music.search_tracks")
    @patch("friday.modules.llm.generate")
    def test_play_request_track_thumbnail_is_url(self, mock_llm, mock_search, client):
        """Track thumbnail_url should be a valid HTTPS URL."""
        mock_llm.return_value = "Enjoy!"
        mock_search.return_value = [
            {
                "video_id": "fJ9rUzIMcZQ",
                "title": "Bohemian Rhapsody",
                "artist": "Queen",
                "thumbnail_url": "https://i.ytimg.com/vi/fJ9rUzIMcZQ/hqdefault.jpg",
            }
        ]

        resp = client.post("/chat", json={
            "message": "play bohemian rhapsody",
            "sessionId": "s-thumb"
        })
        data = resp.get_json()

        assert data["track"]["thumbnail_url"].startswith("https://")


# =============================================================================
# Integration Test 2: Search → Select → Play flow (Requirement 4.4)
# =============================================================================


class TestSearchSelectPlayFlow:
    """Test the search → select flow by calling GET /music/search and verifying results."""

    @patch("app._get_search_engine")
    def test_search_returns_results_with_correct_structure(self, mock_engine_factory, client):
        """GET /music/search should return results with video_id, title, artist, thumbnail_url."""
        mock_engine = MagicMock()
        mock_engine.validate_query.return_value = None

        mock_track_1 = MagicMock()
        mock_track_1.id = "fJ9rUzIMcZQ"
        mock_track_1.title = "Bohemian Rhapsody"
        mock_track_1.artist = "Queen"
        mock_track_1.thumbnail_url = "https://i.ytimg.com/vi/fJ9rUzIMcZQ/hqdefault.jpg"
        mock_track_1.source = "youtube"
        mock_track_1.source_url = "https://youtube.com/watch?v=fJ9rUzIMcZQ"
        mock_track_1.duration_seconds = 354
        mock_track_1.is_devotional = False
        mock_track_1.tradition = None
        mock_track_1.match_score = 0.98

        mock_track_2 = MagicMock()
        mock_track_2.id = "abc456def"
        mock_track_2.title = "Bohemian Rhapsody (Remastered)"
        mock_track_2.artist = "Queen"
        mock_track_2.thumbnail_url = "https://i.ytimg.com/vi/abc456def/hqdefault.jpg"
        mock_track_2.source = "youtube"
        mock_track_2.source_url = "https://youtube.com/watch?v=abc456def"
        mock_track_2.duration_seconds = 360
        mock_track_2.is_devotional = False
        mock_track_2.tradition = None
        mock_track_2.match_score = 0.90

        mock_result = MagicMock()
        mock_result.results = [mock_track_1, mock_track_2]
        mock_result.sources_failed = []
        mock_result.sources_queried = ["youtube"]
        mock_result.correction = None
        mock_result.devotional_context = None
        mock_engine.search.return_value = mock_result
        mock_engine_factory.return_value = mock_engine

        resp = client.get("/music/search?q=bohemian+rhapsody")

        assert resp.status_code == 200
        data = resp.get_json()

        # Verify response structure
        assert "results" in data
        assert "query" in data
        assert data["query"] == "bohemian rhapsody"
        assert len(data["results"]) == 2

        # Verify each result has the required fields for playback
        for track in data["results"]:
            assert "video_id" in track
            assert "title" in track
            assert "artist" in track
            assert "thumbnail_url" in track
            assert isinstance(track["video_id"], str)
            assert len(track["video_id"]) > 0
            assert isinstance(track["title"], str)
            assert len(track["title"]) > 0

    @patch("app._get_search_engine")
    def test_search_results_can_be_used_for_playback(self, mock_engine_factory, client):
        """Verify that search results contain all fields needed to load into the player."""
        mock_engine = MagicMock()
        mock_engine.validate_query.return_value = None

        mock_track = MagicMock()
        mock_track.id = "fJ9rUzIMcZQ"
        mock_track.title = "Bohemian Rhapsody"
        mock_track.artist = "Queen"
        mock_track.thumbnail_url = "https://i.ytimg.com/vi/fJ9rUzIMcZQ/hqdefault.jpg"
        mock_track.source = "youtube"
        mock_track.source_url = "https://youtube.com/watch?v=fJ9rUzIMcZQ"
        mock_track.duration_seconds = 354
        mock_track.is_devotional = False
        mock_track.tradition = None
        mock_track.match_score = 0.98

        mock_result = MagicMock()
        mock_result.results = [mock_track]
        mock_result.sources_failed = []
        mock_result.sources_queried = ["youtube"]
        mock_result.correction = None
        mock_result.devotional_context = None
        mock_engine.search.return_value = mock_result
        mock_engine_factory.return_value = mock_engine

        resp = client.get("/music/search?q=bohemian+rhapsody")
        data = resp.get_json()

        # Simulate selecting the first result for playback
        selected_track = data["results"][0]

        # The selected track should have all fields required by the Track interface
        assert selected_track["video_id"] == "fJ9rUzIMcZQ"
        assert selected_track["title"] == "Bohemian Rhapsody"
        assert selected_track["artist"] == "Queen"
        assert selected_track["thumbnail_url"].startswith("https://")

    @patch("app._get_search_engine")
    def test_search_empty_results_returns_empty_list(self, mock_engine_factory, client):
        """When no songs match, results should be an empty list (not an error)."""
        mock_engine = MagicMock()
        mock_engine.validate_query.return_value = None

        mock_result = MagicMock()
        mock_result.results = []
        mock_result.sources_failed = []
        mock_result.sources_queried = ["youtube"]
        mock_result.correction = None
        mock_result.devotional_context = None
        mock_engine.search.return_value = mock_result
        mock_engine_factory.return_value = mock_engine

        resp = client.get("/music/search?q=xyznonexistent99999")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["results"] == []
        assert data["query"] == "xyznonexistent99999"


# =============================================================================
# Integration Test 3: Auth enforcement on music endpoints (Requirement 6.5)
# =============================================================================


class TestAuthEnforcement:
    """Test that all music endpoints reject unauthenticated requests with 401."""

    def test_chat_endpoint_rejects_unauthenticated(self, unauthenticated_client, monkeypatch):
        """POST /chat should return 401 without valid authentication."""
        from friday.modules import auth as auth_mod

        monkeypatch.setattr(auth_mod, "get_user_from_request", lambda: None)

        resp = unauthenticated_client.post("/chat", json={
            "message": "play bohemian rhapsody",
            "sessionId": "unauth-test"
        })

        assert resp.status_code == 401
        data = resp.get_json()
        assert "error" in data

    def test_music_search_rejects_unauthenticated(self, unauthenticated_client, monkeypatch):
        """GET /music/search should return 401 without valid authentication."""
        from friday.modules import auth as auth_mod

        monkeypatch.setattr(auth_mod, "get_user_from_request", lambda: None)

        resp = unauthenticated_client.get("/music/search?q=bohemian+rhapsody")

        assert resp.status_code == 401
        data = resp.get_json()
        assert "error" in data

    def test_chat_401_contains_auth_error_message(self, unauthenticated_client, monkeypatch):
        """401 response should contain an authentication-related error message."""
        from friday.modules import auth as auth_mod

        monkeypatch.setattr(auth_mod, "get_user_from_request", lambda: None)

        resp = unauthenticated_client.post("/chat", json={
            "message": "play something",
            "sessionId": "unauth-msg"
        })

        data = resp.get_json()
        assert "auth" in data["error"].lower()

    def test_music_search_401_contains_auth_error_message(self, unauthenticated_client, monkeypatch):
        """401 response from /music/search should contain auth error message."""
        from friday.modules import auth as auth_mod

        monkeypatch.setattr(auth_mod, "get_user_from_request", lambda: None)

        resp = unauthenticated_client.get("/music/search?q=test")

        data = resp.get_json()
        assert "auth" in data["error"].lower()
