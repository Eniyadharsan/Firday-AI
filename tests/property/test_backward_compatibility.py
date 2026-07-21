"""Backward compatibility test suite for FallbackRouter.

This test suite verifies that the FallbackRouter (which uses the existing regex
patterns) routes messages correctly to the expected handlers. It serves as the
ground truth for backward compatibility when transitioning to LLM-native routing.

Test messages cover all existing regex patterns:
- is_music_request() patterns
- detect_playback_control() patterns
- is_map_request() patterns
- is_directions_request() patterns
- is_image_request() patterns
- is_video_request() patterns
- is_research_request() patterns

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8**
"""

import pytest
from friday.modules.tool_calling.fallback import FallbackRouter


class TestMusicPlayRouting:
    """Test that music play request patterns route to music_play handler.

    **Validates: Requirements 4.1**
    """

    @pytest.fixture
    def router(self):
        return FallbackRouter()

    @pytest.mark.parametrize(
        "message,expected_handler",
        [
            # "play [query]" pattern
            ("play bohemian rhapsody", "music_play"),
            ("play some jazz music", "music_play"),
            ("play hotel california by eagles", "music_play"),
            ("play the beatles", "music_play"),
            ("PLAY Stairway to Heaven", "music_play"),
            
            # "put on [query]" pattern
            ("put on some classical music", "music_play"),
            ("put on taylor swift", "music_play"),
            ("put on my favorite playlist", "music_play"),
            
            # "queue [query]" pattern
            # Note: "queue this song next" routes to music_control due to "next" keyword
            ("queue thunderstruck", "music_play"),
            ("queue some rock music", "music_play"),
            ("queue up my favorite song", "music_play"),
            
            # "listen to [query]" pattern
            ("listen to pink floyd", "music_play"),
            ("I want to listen to jazz", "music_play"),
            ("let's listen to some music", "music_play"),
            ("listening to podcasts is great but I want to listen to songs", "music_play"),
            
            # Natural phrasing patterns
            ("can you play some music", "music_play"),
            ("could you play despacito", "music_play"),
            ("please play some rock", "music_play"),
            ("i want to play some music", "music_play"),
            ("let's play some hip hop", "music_play"),
            
            # Music keywords with intent verbs
            ("give me a song to listen to", "music_play"),
            ("show me some songs", "music_play"),
            ("get me some music tracks", "music_play"),
        ],
    )
    def test_music_play_patterns(self, router, message, expected_handler):
        """Test music play request patterns route correctly."""
        result = router.route(message, "test_trigger")
        assert result.handler_name == expected_handler, (
            f"Message '{message}' expected handler '{expected_handler}' "
            f"but got '{result.handler_name}'"
        )


class TestPlaybackControlRouting:
    """Test that playback control patterns route to music_control handler.

    **Validates: Requirements 4.6**
    """

    @pytest.fixture
    def router(self):
        return FallbackRouter()

    @pytest.mark.parametrize(
        "message,expected_handler,expected_action",
        [
            # Pause patterns
            ("pause", "music_control", "pause"),
            ("pause the music", "music_control", "pause"),
            ("pause it", "music_control", "pause"),
            ("hold on", "music_control", "pause"),
            
            # Stop patterns
            ("stop", "music_control", "stop"),
            ("stop it", "music_control", "stop"),
            ("stop the music", "music_control", "stop"),
            ("stop playing", "music_control", "stop"),
            ("turn off the music", "music_control", "stop"),
            ("shut off the music", "music_control", "stop"),
            ("turn it off", "music_control", "stop"),
            
            # Next/skip patterns
            ("next", "music_control", "next"),
            ("next song", "music_control", "next"),
            ("skip", "music_control", "next"),
            ("skip this", "music_control", "next"),
            ("skip this song", "music_control", "next"),
            
            # Previous patterns
            ("previous", "music_control", "previous"),
            ("previous song", "music_control", "previous"),
            ("go back", "music_control", "previous"),
            ("last song", "music_control", "previous"),
            
            # Resume patterns
            ("resume", "music_control", "resume"),
            ("resume music", "music_control", "resume"),
            ("continue", "music_control", "resume"),
            ("unpause", "music_control", "resume"),
        ],
    )
    def test_playback_control_patterns(self, router, message, expected_handler, expected_action):
        """Test playback control patterns route correctly with correct action."""
        result = router.route(message, "test_trigger")
        assert result.handler_name == expected_handler, (
            f"Message '{message}' expected handler '{expected_handler}' "
            f"but got '{result.handler_name}'"
        )
        assert result.parameters.get("action") == expected_action, (
            f"Message '{message}' expected action '{expected_action}' "
            f"but got '{result.parameters.get('action')}'"
        )


class TestMapViewRouting:
    """Test that map view request patterns route to map_view handler.

    **Validates: Requirements 4.2**
    """

    @pytest.fixture
    def router(self):
        return FallbackRouter()

    @pytest.mark.parametrize(
        "message,expected_handler",
        [
            # "map of [location]" pattern
            ("map of Paris", "map_view"),
            ("show me a map of New York", "map_view"),
            ("display map of Tokyo", "map_view"),
            ("maps of India", "map_view"),
            
            # "where is [location]" pattern
            ("where is the Eiffel Tower", "map_view"),
            ("where is London", "map_view"),
            ("where is Central Park", "map_view"),
            
            # Location patterns
            ("location of the Great Wall", "map_view"),
            ("locate the Statue of Liberty", "map_view"),
            
            # "[location] map" pattern
            ("Paris map", "map_view"),
            ("India map", "map_view"),
        ],
    )
    def test_map_view_patterns(self, router, message, expected_handler):
        """Test map view request patterns route correctly."""
        result = router.route(message, "test_trigger")
        assert result.handler_name == expected_handler, (
            f"Message '{message}' expected handler '{expected_handler}' "
            f"but got '{result.handler_name}'"
        )


class TestDirectionsRouting:
    """Test that directions request patterns route to directions handler.

    **Validates: Requirements 4.2**
    """

    @pytest.fixture
    def router(self):
        return FallbackRouter()

    @pytest.mark.parametrize(
        "message,expected_handler",
        [
            # "directions to [destination]" pattern
            ("directions to the airport", "directions"),
            ("directions to Central Park", "directions"),
            ("give me directions to the mall", "directions"),
            
            # "navigate to [destination]" pattern
            ("navigate to home", "directions"),
            ("navigate me to the office", "directions"),
            ("navigation to downtown", "directions"),
            
            # "from [origin] to [destination]" pattern
            # Note: standalone "from X to Y" needs a movement keyword like get/drive/travel
            ("get from New York to Boston", "directions"),
            ("directions from my house to the station", "directions"),
            ("route from London to Paris", "directions"),
            ("how do I get from here to there", "directions"),
            ("drive from Chicago to Detroit", "directions"),
            ("travel from here to there", "directions"),
            
            # "how to get to [destination]" pattern
            ("how to get to the museum", "directions"),
            ("how do I get to Times Square", "directions"),
            ("how to reach the hospital", "directions"),
            
            # Route patterns
            ("route to the nearest gas station", "directions"),
            ("show me the way to the store", "directions"),
        ],
    )
    def test_directions_patterns(self, router, message, expected_handler):
        """Test directions request patterns route correctly."""
        result = router.route(message, "test_trigger")
        assert result.handler_name == expected_handler, (
            f"Message '{message}' expected handler '{expected_handler}' "
            f"but got '{result.handler_name}'"
        )


class TestImageGenerationRouting:
    """Test that image generation request patterns route to image_generate handler.

    **Validates: Requirements 4.3**
    """

    @pytest.fixture
    def router(self):
        return FallbackRouter()

    @pytest.mark.parametrize(
        "message,expected_handler",
        [
            # "generate/create/make [image type]" pattern
            ("generate an image of a sunset", "image_generate"),
            ("create a picture of a mountain", "image_generate"),
            ("make an illustration of a cat", "image_generate"),
            ("draw a portrait of Einstein", "image_generate"),
            ("design a logo for my company", "image_generate"),
            
            # "show me [visual subject]" with visual keywords
            ("show me a picture of the ocean", "image_generate"),
            ("show me an image of a forest", "image_generate"),
            ("give me a photo of a sunset", "image_generate"),
            
            # Image/picture/photo keywords with action verbs
            ("create a poster for my event", "image_generate"),
            ("make a wallpaper with mountains", "image_generate"),
            ("generate a chart showing sales data", "image_generate"),
            ("render an image of a futuristic city", "image_generate"),
        ],
    )
    def test_image_generation_patterns(self, router, message, expected_handler):
        """Test image generation request patterns route correctly."""
        result = router.route(message, "test_trigger")
        assert result.handler_name == expected_handler, (
            f"Message '{message}' expected handler '{expected_handler}' "
            f"but got '{result.handler_name}'"
        )


class TestVideoGenerationRouting:
    """Test that video generation request patterns route to video handler.

    **Validates: Requirements 4.4**
    """

    @pytest.fixture
    def router(self):
        return FallbackRouter()

    @pytest.mark.parametrize(
        "message,expected_handler",
        [
            # "generate/create/make [video/clip/animation]" pattern
            ("generate a video of a sunset", "video"),
            ("create a video clip of waves", "video"),
            ("make an animation of a logo", "video"),
            ("produce a short video intro", "video"),
            ("render a video animation", "video"),
            
            # Video-related keywords
            ("create a movie trailer", "video"),
            ("make a film clip", "video"),
            ("generate a short reel", "video"),
        ],
    )
    def test_video_generation_patterns(self, router, message, expected_handler):
        """Test video generation request patterns route correctly."""
        result = router.route(message, "test_trigger")
        assert result.handler_name == expected_handler, (
            f"Message '{message}' expected handler '{expected_handler}' "
            f"but got '{result.handler_name}'"
        )


class TestResearchRouting:
    """Test that research request patterns route to research handler.

    **Validates: Requirements 4.5**
    """

    @pytest.fixture
    def router(self):
        return FallbackRouter()

    @pytest.mark.parametrize(
        "message,expected_handler",
        [
            # Research keywords
            ("research the history of AI", "research"),
            ("do a deep dive on quantum computing", "research"),
            ("investigate the causes of climate change", "research"),
            ("give me a comprehensive analysis of the market", "research"),
            ("thorough review of renewable energy", "research"),
            ("detailed analysis of blockchain technology", "research"),
            ("write a report on machine learning", "research"),
            ("report on the state of electric vehicles", "research"),
        ],
    )
    def test_research_patterns(self, router, message, expected_handler):
        """Test research request patterns route correctly."""
        result = router.route(message, "test_trigger")
        assert result.handler_name == expected_handler, (
            f"Message '{message}' expected handler '{expected_handler}' "
            f"but got '{result.handler_name}'"
        )


class TestDefaultChatRouting:
    """Test that messages not matching any pattern route to default_chat handler.

    **Validates: Requirements 4.8**
    """

    @pytest.fixture
    def router(self):
        return FallbackRouter()

    @pytest.mark.parametrize(
        "message,expected_handler",
        [
            # General conversation
            ("Hello, how are you?", "default_chat"),
            ("What's your name?", "default_chat"),
            ("Tell me a joke", "default_chat"),
            ("What is 2 + 2?", "default_chat"),
            ("Explain quantum physics", "default_chat"),
            ("What's the meaning of life?", "default_chat"),
            
            # Questions about previous content (not new requests)
            ("what did you show me?", "default_chat"),
            ("which image was that?", "default_chat"),
            
            # Commands that don't match any patterns
            ("thank you", "default_chat"),
            ("goodbye", "default_chat"),
            ("help me with coding", "default_chat"),
        ],
    )
    def test_default_chat_patterns(self, router, message, expected_handler):
        """Test default chat routing for non-matching patterns."""
        result = router.route(message, "test_trigger")
        assert result.handler_name == expected_handler, (
            f"Message '{message}' expected handler '{expected_handler}' "
            f"but got '{result.handler_name}'"
        )


class TestRoutingPriorityOrder:
    """Test that routing priority is maintained correctly.

    The priority order should be:
    1. detect_playback_control() -> music_control
    2. is_research_request() -> research
    3. is_video_request() -> video
    4. is_directions_request() -> directions
    5. is_map_request() -> map_view
    6. is_music_request() -> music_play
    7. is_image_request() -> image_generate
    8. default -> default_chat

    **Validates: Requirements 4.7**
    """

    @pytest.fixture
    def router(self):
        return FallbackRouter()

    def test_playback_control_before_music_play(self, router):
        """Playback control should take precedence over music play."""
        # "resume" by itself should be resume control, not music play
        result = router.route("resume", "test_trigger")
        assert result.handler_name == "music_control"
        assert result.parameters.get("action") == "resume"

    def test_directions_before_map_view(self, router):
        """Directions should take precedence over general map view."""
        # "navigate to X" should be directions, not just map
        result = router.route("navigate to the airport", "test_trigger")
        assert result.handler_name == "directions"

    def test_research_before_other_handlers(self, router):
        """Research requests should be recognized even with other keywords."""
        result = router.route("research the latest music trends", "test_trigger")
        assert result.handler_name == "research"

    def test_video_before_image(self, router):
        """Video generation should take precedence when video keywords present."""
        result = router.route("create a video animation", "test_trigger")
        assert result.handler_name == "video"


class TestTriggerReasonPassthrough:
    """Test that trigger_reason is correctly passed through to FallbackResult."""

    @pytest.fixture
    def router(self):
        return FallbackRouter()

    @pytest.mark.parametrize(
        "trigger_reason",
        [
            "timeout",
            "http_4xx",
            "http_5xx",
            "parse_error",
            "connection_error",
        ],
    )
    def test_trigger_reason_preserved(self, router, trigger_reason):
        """Test that trigger_reason is preserved in the FallbackResult."""
        result = router.route("play some music", trigger_reason)
        assert result.trigger_reason == trigger_reason


class TestParameterExtraction:
    """Test that parameters are correctly extracted for each handler type."""

    @pytest.fixture
    def router(self):
        return FallbackRouter()

    def test_music_play_extracts_song_query(self, router):
        """Test that music_play extracts the song query correctly."""
        result = router.route("play bohemian rhapsody", "test_trigger")
        assert result.handler_name == "music_play"
        assert "song_query" in result.parameters
        assert result.parameters["song_query"] == "bohemian rhapsody"

    def test_music_control_extracts_action(self, router):
        """Test that music_control extracts the action correctly."""
        result = router.route("pause the music", "test_trigger")
        assert result.handler_name == "music_control"
        assert result.parameters.get("action") == "pause"

    def test_directions_extracts_origin_destination(self, router):
        """Test that directions extracts origin and destination correctly."""
        result = router.route("directions from New York to Boston", "test_trigger")
        assert result.handler_name == "directions"
        assert "destination" in result.parameters
        assert "origin" in result.parameters
        # Note: exact values depend on extract_route implementation

    def test_map_view_extracts_place(self, router):
        """Test that map_view extracts place correctly."""
        result = router.route("map of Paris", "test_trigger")
        assert result.handler_name == "map_view"
        assert "place" in result.parameters

    def test_video_extracts_prompt(self, router):
        """Test that video extracts prompt correctly."""
        result = router.route("generate a video of sunset", "test_trigger")
        assert result.handler_name == "video"
        assert "prompt" in result.parameters
        assert result.parameters["prompt"] == "generate a video of sunset"

    def test_research_extracts_topic(self, router):
        """Test that research extracts topic correctly."""
        result = router.route("research quantum computing", "test_trigger")
        assert result.handler_name == "research"
        assert "topic" in result.parameters
        assert result.parameters["topic"] == "research quantum computing"

    def test_image_extracts_prompt(self, router):
        """Test that image_generate extracts prompt correctly."""
        result = router.route("generate an image of a mountain", "test_trigger")
        assert result.handler_name == "image_generate"
        assert "prompt" in result.parameters
        assert result.parameters["prompt"] == "generate an image of a mountain"
