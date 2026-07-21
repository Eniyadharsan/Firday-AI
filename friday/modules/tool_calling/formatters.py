"""Response formatters for the tool calling routing system.

This module provides formatter functions that convert capability handler results
into standardized API response structures. Each formatter preserves the existing
response format for backward compatibility with the frontend.

**Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6**
"""

from __future__ import annotations

from typing import Any


def format_music_response(
    reply: str,
    session_id: str,
    track: dict[str, Any],
) -> dict[str, Any]:
    """Format a music playback response.

    Creates a response for successful music play requests with the track
    information needed for the frontend to display and play the music.

    Args:
        reply: Human-readable response message (e.g., "Playing 'Song' by Artist...").
        session_id: Current session identifier.
        track: Track information object containing:
            - video_id: YouTube video ID or equivalent identifier.
            - title: Track title.
            - artist: Artist name.
            - thumbnail_url: URL to track artwork/thumbnail.

    Returns:
        Response dictionary with:
            - reply: The reply message.
            - sessionId: The session ID.
            - action: "play_music_embed" to trigger music player.
            - track: Track object with video_id, title, artist, thumbnail_url.

    **Validates: Requirement 8.1**
    """
    return {
        "reply": reply,
        "sessionId": session_id,
        "action": "play_music_embed",
        "track": track,
    }


def format_music_control_response(
    reply: str,
    session_id: str,
    control: str,
) -> dict[str, Any]:
    """Format a music control response.

    Creates a response for playback control commands (pause, resume, stop,
    next, previous) that instructs the frontend to modify playback state.

    Args:
        reply: Human-readable response message (e.g., "Music paused, Sir.").
        session_id: Current session identifier.
        control: The control action to perform. Must be one of:
            "pause", "resume", "stop", "next", "previous".

    Returns:
        Response dictionary with:
            - reply: The reply message.
            - sessionId: The session ID.
            - action: "control_music" to trigger playback control.
            - control: The specific control action.

    **Validates: Requirement 8.1 (music control is part of music capability)**
    """
    return {
        "reply": reply,
        "sessionId": session_id,
        "action": "control_music",
        "control": control,
    }


def format_map_view_response(
    reply: str,
    session_id: str,
    place: str,
) -> dict[str, Any]:
    """Format a map view response.

    Creates a response for map viewing requests that instructs the frontend
    to display an interactive map centered on the specified location.

    Args:
        reply: Human-readable response message (e.g., "Here is the map of Paris, Sir.").
        session_id: Current session identifier.
        place: The location, city, or place to display on the map.

    Returns:
        Response dictionary with:
            - reply: The reply message.
            - sessionId: The session ID.
            - action: "show_map" to trigger map display.
            - mode: "view" for location viewing mode.
            - place: The location string.

    **Validates: Requirement 8.2**
    """
    return {
        "reply": reply,
        "sessionId": session_id,
        "action": "show_map",
        "mode": "view",
        "place": place,
    }


def format_directions_response(
    reply: str,
    session_id: str,
    origin: str,
    destination: str,
) -> dict[str, Any]:
    """Format a directions/navigation response.

    Creates a response for routing/directions requests that instructs the
    frontend to display a map with a route between two locations.

    Args:
        reply: Human-readable response message
            (e.g., "Plotting a route from A to B, Sir.").
        session_id: Current session identifier.
        origin: Starting location. May be empty string if not specified
            (uses current location).
        destination: Destination location.

    Returns:
        Response dictionary with:
            - reply: The reply message.
            - sessionId: The session ID.
            - action: "show_map" to trigger map display.
            - mode: "directions" for routing mode.
            - origin: Starting location (may be empty).
            - destination: Destination location.

    **Validates: Requirement 8.3**
    """
    return {
        "reply": reply,
        "sessionId": session_id,
        "action": "show_map",
        "mode": "directions",
        "origin": origin,
        "destination": destination,
    }


def format_image_response(
    reply: str,
    session_id: str,
    image_url: str,
    image_prompt: str,
) -> dict[str, Any]:
    """Format an image generation response.

    Creates a response for image generation requests that instructs the
    frontend to display the generated image.

    Args:
        reply: Human-readable response message (e.g., "Here's your image, Sir.").
        session_id: Current session identifier.
        image_url: URL to the generated image.
        image_prompt: The original prompt/request used to generate the image.

    Returns:
        Response dictionary with:
            - reply: The reply message.
            - sessionId: The session ID.
            - action: "show_image" to trigger image display.
            - imageUrl: URL to the generated image.
            - imagePrompt: The original generation prompt.

    **Validates: Requirement 8.4**
    """
    return {
        "reply": reply,
        "sessionId": session_id,
        "action": "show_image",
        "imageUrl": image_url,
        "imagePrompt": image_prompt,
    }


def format_video_response(
    reply: str,
    session_id: str,
    video_url: str,
    video_prompt: str,
) -> dict[str, Any]:
    """Format a video generation response.

    Creates a response for video generation requests that instructs the
    frontend to display the generated video.

    Args:
        reply: Human-readable response message (e.g., "Generating your video, Sir.").
        session_id: Current session identifier.
        video_url: URL to the generated video.
        video_prompt: The original prompt/request used to generate the video.

    Returns:
        Response dictionary with:
            - reply: The reply message.
            - sessionId: The session ID.
            - action: "show_video" to trigger video display.
            - videoUrl: URL to the generated video.
            - videoPrompt: The original generation prompt.

    **Validates: Requirement 8.5**
    """
    return {
        "reply": reply,
        "sessionId": session_id,
        "action": "show_video",
        "videoUrl": video_url,
        "videoPrompt": video_prompt,
    }


def format_research_response(
    reply: str,
    session_id: str,
    report: str,
    topic: str,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """Format a research report response.

    Creates a response for research requests that instructs the frontend
    to display the full research report with metadata.

    Args:
        reply: Human-readable summary (e.g., "Research complete. 5 sources in 12s.").
        session_id: Current session identifier.
        report: The full research report text.
        topic: The research topic.
        meta: Metadata about the research containing:
            - sources: Number of sources consulted.
            - news: Number of news articles included.
            - time: Time taken for research (e.g., "12s").

    Returns:
        Response dictionary with:
            - reply: The reply message.
            - sessionId: The session ID.
            - action: "show_report" to trigger report display.
            - report: The full report text.
            - topic: The research topic.
            - meta: Object with sources, news, and time fields.

    **Validates: Requirement 8.6**
    """
    return {
        "reply": reply,
        "sessionId": session_id,
        "action": "show_report",
        "report": report,
        "topic": topic,
        "meta": meta,
    }


def format_multi_result_response(
    reply: str,
    session_id: str,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Format a multi-tool execution response.

    Creates a response for requests that triggered multiple tool calls,
    combining all results into a single response.

    Args:
        reply: Human-readable summary of all actions performed.
        session_id: Current session identifier.
        results: List of individual tool results, each containing:
            - tool: Name of the tool that was executed.
            - success: Boolean indicating if execution succeeded.
            - result: The tool's output (if success=True), or None.
            - error: Error message (if success=False), or None.

    Returns:
        Response dictionary with:
            - reply: The summary message.
            - sessionId: The session ID.
            - action: "multi_result" to indicate multiple results.
            - results: Array of individual tool results.

    **Validates: Requirements 6.3, 6.4 (multi-intent handling)**
    """
    return {
        "reply": reply,
        "sessionId": session_id,
        "action": "multi_result",
        "results": results,
    }


def format_error_response(
    reply: str,
    session_id: str,
    error: str,
) -> dict[str, Any]:
    """Format an error response.

    Creates a response for routing or execution failures that informs
    the user of the error in a friendly manner.

    Args:
        reply: Human-readable error message for the user
            (e.g., "I encountered an issue with your request.").
        session_id: Current session identifier.
        error: Technical error description for debugging/logging.

    Returns:
        Response dictionary with:
            - reply: The user-friendly error message.
            - sessionId: The session ID.
            - action: "error" to indicate an error occurred.
            - error: Technical error details.

    **Validates: Requirements 3.6, 3.7 (error handling)**
    """
    return {
        "reply": reply,
        "sessionId": session_id,
        "action": "error",
        "error": error,
    }


def format_conversational_response(
    reply: str,
    session_id: str,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Format a general conversational response.

    Creates a response for messages that don't require any special action,
    just a text reply from the assistant.

    Args:
        reply: The assistant's text response.
        session_id: Current session identifier.
        timestamp: Optional ISO timestamp for the response.

    Returns:
        Response dictionary with:
            - reply: The assistant's message.
            - sessionId: The session ID.
            - timestamp: ISO timestamp (if provided).

    **Validates: Requirements 2.3, 3.5 (no tool call returns content)**
    """
    response: dict[str, Any] = {
        "reply": reply,
        "sessionId": session_id,
    }
    if timestamp is not None:
        response["timestamp"] = timestamp
    return response
