"""Fallback routing using regex-based is_X_request() functions.

This module provides the FallbackRouter class that serves as a backup routing
mechanism when LLM tool selection fails or times out. It preserves the existing
regex-based pattern matching logic from the original app.py implementation.

The priority order matches the existing routing cascade:
1. detect_playback_control() → music_control
2. is_research_request() → research
3. is_video_request() → video
4. is_directions_request() → directions
5. is_map_request() → map_view
6. is_music_request() → music_play
7. is_image_request() → image_generate
8. default → default_chat

**Validates: Requirements 5.1, 5.2, 5.4, 5.5, 4.7**
"""

from __future__ import annotations

from friday.modules.tool_calling.models import FallbackResult

# Import regex detection functions from their respective modules
from friday.modules.music import detect_playback_control, is_music_request
from friday.modules.maps import is_map_request, is_directions_request, extract_place, extract_route
from friday.modules.image import is_image_request
from friday.modules.video import is_video_request
from friday.modules.research import is_research_request


class FallbackRouter:
    """Backup routing using regex-based is_X_request() functions.

    This router is used when LLM tool selection fails due to timeout,
    HTTP errors, or parsing failures. It preserves the original regex-based
    routing logic to ensure the system remains functional.

    The routing priority order matches the existing cascade in app.py to
    maintain backward compatibility (Requirement 4.7).
    """

    def route(self, message: str, trigger_reason: str) -> FallbackResult:
        """Route message using existing regex patterns.

        Checks patterns in priority order matching the original app.py cascade:
        1. detect_playback_control() → music_control
        2. is_research_request() → research
        3. is_video_request() → video
        4. is_directions_request() → directions
        5. is_map_request() → map_view
        6. is_music_request() → music_play
        7. is_image_request() → image_generate
        8. default → default_chat

        Args:
            message: The user message to route.
            trigger_reason: Why fallback was triggered. Expected values:
                - "timeout": Cerebras API exceeded 3 second timeout
                - "http_4xx": Cerebras API returned 4xx status code
                - "http_5xx": Cerebras API returned 5xx status code
                - "parse_error": Failed to parse Cerebras API response
                - "connection_error": Connection failure to Cerebras API

        Returns:
            FallbackResult containing:
                - handler_name: The capability handler to route to
                - parameters: Extracted parameters from regex matching
                - trigger_reason: The reason fallback was triggered
        """
        # Priority 1: Music playback control (pause/resume/stop/next/previous)
        # Must be checked BEFORE is_music_request so "play"/"resume" aren't
        # treated as new music searches
        control_action = detect_playback_control(message)
        if control_action:
            return FallbackResult(
                handler_name="music_control",
                parameters={"action": control_action},
                trigger_reason=trigger_reason,
            )

        # Priority 2: Research mode (deep dive, investigate, comprehensive analysis)
        if is_research_request(message):
            return FallbackResult(
                handler_name="research",
                parameters={"topic": message},
                trigger_reason=trigger_reason,
            )

        # Priority 3: Video generation
        if is_video_request(message):
            return FallbackResult(
                handler_name="video",
                parameters={"prompt": message},
                trigger_reason=trigger_reason,
            )

        # Priority 4: Directions (routing from A to B)
        # Must be checked BEFORE general map requests
        if is_directions_request(message):
            origin, destination = extract_route(message)
            return FallbackResult(
                handler_name="directions",
                parameters={"origin": origin, "destination": destination},
                trigger_reason=trigger_reason,
            )

        # Priority 5: Map view (show map of location)
        if is_map_request(message):
            place = extract_place(message)
            return FallbackResult(
                handler_name="map_view",
                parameters={"place": place},
                trigger_reason=trigger_reason,
            )

        # Priority 6: Music play request
        if is_music_request(message):
            # Extract the song query by removing common prefixes
            song_query = message.lower()
            for prefix in ["play ", "put on ", "queue ", "listen to "]:
                if song_query.startswith(prefix):
                    song_query = message[len(prefix):].strip()
                    break
            else:
                # Use original message if no prefix matched
                song_query = message

            return FallbackResult(
                handler_name="music_play",
                parameters={"song_query": song_query},
                trigger_reason=trigger_reason,
            )

        # Priority 7: Image generation
        if is_image_request(message):
            return FallbackResult(
                handler_name="image_generate",
                parameters={"prompt": message},
                trigger_reason=trigger_reason,
            )

        # Priority 8: Default - route to default chat handler
        return FallbackResult(
            handler_name="default_chat",
            parameters={},
            trigger_reason=trigger_reason,
        )
