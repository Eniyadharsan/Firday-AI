"""Unit tests for /music/search endpoint and updated /chat music response.

Validates:
- /music/search: Valid query returns 200 with correct structure (Requirements 6.1, 6.4)
- /music/search: Empty query returns 400 (Requirement 6.4)
- /music/search: Unauthenticated request returns 401 (Requirement 6.5)
- Music request returns `play_music_embed` action with track object (Requirements 1.1, 1.2, 1.3, 1.4)
- No results case returns error message in reply (Requirement 1.4)
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def client():
    """Create a Flask test client with auth bypassed."""
    from app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def unauthenticated_client():
    """Create a Flask test client WITHOUT auth bypass (for testing 401)."""
    from app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def bypass_auth(monkeypatch):
    """Bypass the @require_auth decorator by making get_user_from_request return a valid user."""
    from friday.modules import auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_user_from_request", lambda: {"sub": "test-user", "email": "test@friday"})


@pytest.fixture(autouse=True)
def mock_memory(monkeypatch):
    """Mock memory module to avoid database calls during tests."""
    from friday.modules import memory as mem_mod

    monkeypatch.setattr(mem_mod, "save_message", lambda *args, **kwargs: None)


# =============================================================================
# Tests for GET /music/search endpoint (Requirements 6.1, 6.4, 6.5)
# =============================================================================


class TestMusicSearchEndpointValidQuery:
    """Tests for /music/search with a valid query returning 200 with correct structure."""

    @patch("app._get_search_engine")
    def test_valid_query_returns_200(self, mock_engine_factory, client):
        """A valid query should return HTTP 200."""
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

        resp = client.get("/music/search?q=bohemian+rhapsody")
        assert resp.status_code == 200

    @patch("app._get_search_engine")
    def test_valid_query_returns_results_and_query_fields(self, mock_engine_factory, client):
        """Response JSON should contain 'results' array and 'query' string."""
        mock_engine = MagicMock()
        mock_engine.validate_query.return_value = None

        mock_track = MagicMock()
        mock_track.id = "dQw4w9WgXcQ"
        mock_track.title = "Never Gonna Give You Up"
        mock_track.artist = "Rick Astley"
        mock_track.thumbnail_url = "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
        mock_track.source = "youtube"
        mock_track.source_url = "https://youtube.com/watch?v=dQw4w9WgXcQ"
        mock_track.duration_seconds = 213
        mock_track.is_devotional = False
        mock_track.tradition = None
        mock_track.match_score = 0.95

        mock_result = MagicMock()
        mock_result.results = [mock_track]
        mock_result.sources_failed = []
        mock_result.sources_queried = ["youtube"]
        mock_result.correction = None
        mock_result.devotional_context = None
        mock_engine.search.return_value = mock_result
        mock_engine_factory.return_value = mock_engine

        resp = client.get("/music/search?q=never+gonna+give+you+up")
        data = resp.get_json()

        assert "results" in data
        assert "query" in data
        assert isinstance(data["results"], list)
        assert data["query"] == "never gonna give you up"

    @patch("app._get_search_engine")
    def test_valid_query_results_contain_track_fields(self, mock_engine_factory, client):
        """Each result should contain video_id, title, artist, and thumbnail_url."""
        mock_engine = MagicMock()
        mock_engine.validate_query.return_value = None

        mock_track = MagicMock()
        mock_track.id = "abc123"
        mock_track.title = "Test Song"
        mock_track.artist = "Test Artist"
        mock_track.thumbnail_url = "https://example.com/thumb.jpg"
        mock_track.source = "youtube"
        mock_track.source_url = "https://youtube.com/watch?v=abc123"
        mock_track.duration_seconds = 180
        mock_track.is_devotional = False
        mock_track.tradition = None
        mock_track.match_score = 0.9

        mock_result = MagicMock()
        mock_result.results = [mock_track]
        mock_result.sources_failed = []
        mock_result.sources_queried = ["youtube"]
        mock_result.correction = None
        mock_result.devotional_context = None
        mock_engine.search.return_value = mock_result
        mock_engine_factory.return_value = mock_engine

        resp = client.get("/music/search?q=test+song")
        data = resp.get_json()

        assert len(data["results"]) == 1
        track = data["results"][0]
        assert track["video_id"] == "abc123"
        assert track["title"] == "Test Song"
        assert track["artist"] == "Test Artist"
        assert track["thumbnail_url"] == "https://example.com/thumb.jpg"


class TestMusicSearchEndpointEmptyQuery:
    """Tests for /music/search with empty query returning 400."""

    @patch("app._get_search_engine")
    def test_empty_query_returns_400(self, mock_engine_factory, client):
        """An empty query parameter should return HTTP 400."""
        mock_engine = MagicMock()
        mock_engine.validate_query.return_value = "Query parameter 'q' is required"
        mock_engine_factory.return_value = mock_engine

        resp = client.get("/music/search?q=")
        assert resp.status_code == 400

    @patch("app._get_search_engine")
    def test_missing_query_param_returns_400(self, mock_engine_factory, client):
        """A missing q parameter should return HTTP 400."""
        mock_engine = MagicMock()
        mock_engine.validate_query.return_value = "Query parameter 'q' is required"
        mock_engine_factory.return_value = mock_engine

        resp = client.get("/music/search")
        assert resp.status_code == 400

    @patch("app._get_search_engine")
    def test_empty_query_returns_error_message(self, mock_engine_factory, client):
        """Response body should contain an error message about the missing query."""
        mock_engine = MagicMock()
        mock_engine.validate_query.return_value = "Query parameter 'q' is required"
        mock_engine_factory.return_value = mock_engine

        resp = client.get("/music/search?q=")
        data = resp.get_json()

        assert "error" in data
        assert "q" in data["error"].lower() or "query" in data["error"].lower()

    @patch("app._get_search_engine")
    def test_whitespace_only_query_returns_400(self, mock_engine_factory, client):
        """A whitespace-only query should return HTTP 400."""
        mock_engine = MagicMock()
        mock_engine.validate_query.return_value = "Query parameter 'q' is required"
        mock_engine_factory.return_value = mock_engine

        resp = client.get("/music/search?q=   ")
        assert resp.status_code == 400


class TestMusicSearchEndpointUnauthenticated:
    """Tests for /music/search returning 401 when unauthenticated."""

    def test_no_auth_header_returns_401(self, unauthenticated_client, monkeypatch):
        """A request without an Authorization header should return 401."""
        from friday.modules import auth as auth_mod

        # Override the autouse bypass_auth to simulate no auth
        monkeypatch.setattr(auth_mod, "get_user_from_request", lambda: None)

        resp = unauthenticated_client.get("/music/search?q=test")
        assert resp.status_code == 401

    def test_unauthenticated_returns_error_message(self, unauthenticated_client, monkeypatch):
        """Unauthenticated response should contain an authentication error message."""
        from friday.modules import auth as auth_mod

        monkeypatch.setattr(auth_mod, "get_user_from_request", lambda: None)

        resp = unauthenticated_client.get("/music/search?q=test")
        data = resp.get_json()

        assert "error" in data
        assert "auth" in data["error"].lower()


class TestChatMusicResponseWithResults:
    """Tests for /chat music request returning play_music_embed action with track object."""

    @patch("friday.modules.music.search_tracks")
    @patch("friday.modules.llm.generate")
    def test_music_request_returns_play_music_embed_action(self, mock_llm, mock_search, client):
        """When a music request is detected and tracks are found, action should be play_music_embed."""
        mock_llm.return_value = "Sure, playing that for you!"
        mock_search.return_value = [
            {
                "video_id": "dQw4w9WgXcQ",
                "title": "Never Gonna Give You Up",
                "artist": "Rick Astley",
                "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
            }
        ]

        resp = client.post("/chat", json={"message": "play never gonna give you up", "sessionId": "test-session"})
        assert resp.status_code == 200
        data = resp.get_json()

        assert data["action"] == "play_music_embed"

    @patch("friday.modules.music.search_tracks")
    @patch("friday.modules.llm.generate")
    def test_music_request_returns_track_object(self, mock_llm, mock_search, client):
        """Response should contain a track object with video_id, title, artist, thumbnail_url."""
        mock_llm.return_value = "Playing some music!"
        mock_search.return_value = [
            {
                "video_id": "abc123xyz",
                "title": "Bohemian Rhapsody",
                "artist": "Queen",
                "thumbnail_url": "https://i.ytimg.com/vi/abc123xyz/hqdefault.jpg",
            }
        ]

        resp = client.post("/chat", json={"message": "play bohemian rhapsody", "sessionId": "test-session"})
        data = resp.get_json()

        assert "track" in data
        track = data["track"]
        assert track["video_id"] == "abc123xyz"
        assert track["title"] == "Bohemian Rhapsody"
        assert track["artist"] == "Queen"
        assert track["thumbnail_url"] == "https://i.ytimg.com/vi/abc123xyz/hqdefault.jpg"

    @patch("friday.modules.music.search_tracks")
    @patch("friday.modules.llm.generate")
    def test_music_request_includes_session_id(self, mock_llm, mock_search, client):
        """Response should include the sessionId."""
        mock_llm.return_value = "Here you go!"
        mock_search.return_value = [
            {
                "video_id": "vid1",
                "title": "Test Song",
                "artist": "Test Artist",
                "thumbnail_url": "https://example.com/thumb.jpg",
            }
        ]

        resp = client.post("/chat", json={"message": "play test song", "sessionId": "my-session-123"})
        data = resp.get_json()

        assert data["sessionId"] == "my-session-123"

    @patch("friday.modules.music.search_tracks")
    @patch("friday.modules.llm.generate")
    def test_music_request_includes_reply_with_track_info(self, mock_llm, mock_search, client):
        """Response reply should mention the track title and artist."""
        mock_llm.return_value = "Playing now!"
        mock_search.return_value = [
            {
                "video_id": "xyz789",
                "title": "Shape of You",
                "artist": "Ed Sheeran",
                "thumbnail_url": "https://i.ytimg.com/vi/xyz789/hqdefault.jpg",
            }
        ]

        resp = client.post("/chat", json={"message": "play shape of you", "sessionId": "s1"})
        data = resp.get_json()

        assert "reply" in data
        assert "Shape of You" in data["reply"]
        assert "Ed Sheeran" in data["reply"]

    @patch("friday.modules.music.search_tracks")
    @patch("friday.modules.llm.generate")
    def test_music_request_uses_first_search_result(self, mock_llm, mock_search, client):
        """When multiple results are returned, the first result should be used as the track."""
        mock_llm.return_value = "Playing!"
        mock_search.return_value = [
            {
                "video_id": "first_id",
                "title": "First Song",
                "artist": "First Artist",
                "thumbnail_url": "https://example.com/first.jpg",
            },
            {
                "video_id": "second_id",
                "title": "Second Song",
                "artist": "Second Artist",
                "thumbnail_url": "https://example.com/second.jpg",
            },
        ]

        resp = client.post("/chat", json={"message": "play something", "sessionId": "s1"})
        data = resp.get_json()

        assert data["track"]["video_id"] == "first_id"
        assert data["track"]["title"] == "First Song"


class TestChatMusicResponseNoResults:
    """Tests for /chat music request when no results are found."""

    @patch("friday.modules.music.search_tracks")
    @patch("friday.modules.llm.generate")
    def test_no_results_returns_error_in_reply(self, mock_llm, mock_search, client):
        """When search returns no results, reply should contain an error message."""
        mock_llm.return_value = "Let me find that for you."
        mock_search.return_value = []

        resp = client.post("/chat", json={"message": "play xyznonexistent12345", "sessionId": "s1"})
        assert resp.status_code == 200
        data = resp.get_json()

        assert "reply" in data
        assert "couldn't find" in data["reply"].lower() or "sorry" in data["reply"].lower()

    @patch("friday.modules.music.search_tracks")
    @patch("friday.modules.llm.generate")
    def test_no_results_does_not_return_action(self, mock_llm, mock_search, client):
        """When no results found, response should NOT contain a play_music_embed action."""
        mock_llm.return_value = "Searching..."
        mock_search.return_value = []

        resp = client.post("/chat", json={"message": "play obscure unknown track", "sessionId": "s1"})
        data = resp.get_json()

        assert data.get("action") != "play_music_embed"
        assert "track" not in data

    @patch("friday.modules.music.search_tracks")
    @patch("friday.modules.llm.generate")
    def test_no_results_still_includes_session_id(self, mock_llm, mock_search, client):
        """Even on no results, the sessionId should be returned."""
        mock_llm.return_value = "Hmm..."
        mock_search.return_value = []

        resp = client.post("/chat", json={"message": "play nothing here", "sessionId": "sess-abc"})
        data = resp.get_json()

        assert data["sessionId"] == "sess-abc"
