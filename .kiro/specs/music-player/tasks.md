# Implementation Plan: Music Player

## Overview

This plan implements an embedded music player for the Friday AI Assistant, replacing the current "open YouTube in a new tab" behavior with an in-app player using the YouTube IFrame API. The implementation covers: enhancing the backend music module with YouTube Data API search, adding a `/music/search` endpoint, updating the `/chat` response for music requests, and building a full Now Playing UI with playback controls, search, and queue management in vanilla JavaScript.

## Tasks

- [x] 1. Enhance backend music module with search and parsing
  - [x] 1.1 Add `search_tracks` function to `friday/modules/music.py`
    - Implement YouTube Data API v3 search using the API key from environment
    - Return a list of up to 10 track dicts with keys: `video_id`, `title`, `artist`, `thumbnail_url`
    - Handle API errors gracefully (missing key, rate limits, network failures)
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 1.2 Add `extract_artist_title` function to `friday/modules/music.py`
    - Parse YouTube video titles into (artist, title) tuples
    - Handle common patterns: "Artist - Title", "Title by Artist", "Artist: Title"
    - Fall back to full title as title and "Unknown Artist" when pattern not recognized
    - _Requirements: 1.1, 6.2_

  - [x] 1.3 Update `is_music_request` to broaden detection patterns
    - Ensure messages starting with "play " followed by non-whitespace trigger detection
    - Support "put on" and "queue" patterns as per requirements
    - Keep backward compatibility with existing detection
    - _Requirements: 1.1_

  - [x] 1.4 Write property tests for `extract_artist_title` (Python/Hypothesis)
    - **Property 1: Artist/Title Parsing Round-Trip**
    - **Validates: Requirements 1.1, 6.2**

  - [x] 1.5 Write property tests for `is_music_request` (Python/Hypothesis)
    - **Property 2: Music Request Detection Consistency**
    - **Validates: Requirements 1.1**

  - [x] 1.6 Write property tests for `search_tracks` response structure (Python/Hypothesis)
    - **Property 3: Search Response Structure Invariant**
    - Mock the YouTube Data API to test response structure guarantees
    - **Validates: Requirements 4.2, 6.2, 6.3**

- [x] 2. Add `/music/search` endpoint and update `/chat` music response
  - [x] 2.1 Add `GET /music/search` endpoint to `app.py`
    - Accept `q` query parameter, return 400 if empty
    - Call `music.search_tracks(query, max_results=10)`
    - Return JSON `{"results": [...], "query": "..."}`
    - Require authentication via `@require_auth`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 2.2 Update `/chat` music handling to return embedded track metadata
    - Replace `action: "play_music"` with `action: "play_music_embed"`
    - Call `music.search_tracks` to get a real video ID and metadata
    - Return `{"reply": "...", "sessionId": "...", "action": "play_music_embed", "track": {...}}`
    - Fall back to error message if no results found
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 2.3 Write unit tests for `/music/search` endpoint
    - Test valid query returns 200 with correct structure
    - Test empty query returns 400
    - Test unauthenticated request returns 401
    - _Requirements: 6.1, 6.4, 6.5_

  - [x] 2.4 Write unit tests for updated `/chat` music response
    - Test music request returns `play_music_embed` action with track object
    - Test no results case returns error message in reply
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 3. Checkpoint - Backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Build frontend MusicPlayer class with queue management
  - [x] 4.1 Create `MusicPlayer` class skeleton in `public/index.html`
    - Define class with constructor initializing: queue, currentIndex, ytPlayer, isPlaying, visible
    - Implement `loadTrack(track)`, `loadQueue(tracks, startIndex)`, `play()`, `pause()`, `togglePlayPause()`
    - Implement `next()`, `previous()` with boundary checks
    - Implement `clearQueue()`, `addToQueue(tracks)`, `getCurrentTrack()`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x] 4.2 Integrate YouTube IFrame Player API
    - Dynamically load the YouTube IFrame API script
    - Implement `onYouTubeIframeAPIReady` global callback
    - Create hidden `YT.Player` instance in `#yt-player-container`
    - Handle `onStateChange` for auto-advance on `ENDED` state
    - Handle `onError` for skipping unavailable tracks
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 4.3 Implement progress tracking and time display
    - Poll `ytPlayer.getCurrentTime()` and `ytPlayer.getDuration()` on interval
    - Calculate progress percentage and update progress bar width
    - Format and display current time and total duration
    - _Requirements: 2.2_

- [x] 5. Build Now Playing UI and search interface
  - [x] 5.1 Render Now Playing panel DOM structure
    - Create fixed bottom panel with album art, title, artist, progress bar, controls
    - Apply Apple Music-inspired dark translucent theme with blurred background
    - Add close/minimize button
    - Ensure panel is hidden when no track loaded
    - _Requirements: 2.1, 2.3, 2.4, 8.1, 8.4_

  - [x] 5.2 Implement `updateNowPlaying(track)` method
    - Set album art image src to track thumbnail_url
    - Set title and artist text content
    - Update blurred background from thumbnail
    - Show the panel when track is loaded
    - _Requirements: 1.3, 2.1_

  - [x] 5.3 Build search interface within the player
    - Add search input field with placeholder text
    - On submit, call `fetch('/music/search?q=...')` with auth headers
    - Display results as scrollable list with thumbnail, title, artist
    - On track selection, call `loadQueue(results, selectedIndex)`
    - Show "no songs found" message when results are empty
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 5.4 Wire playback control buttons
    - Connect play/pause button to `togglePlayPause()`
    - Connect next button to `next()`
    - Connect previous button to `previous()`
    - Update button icons based on play state
    - Disable next/prev when at queue boundaries
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x] 5.5 Write property tests for queue navigation (JavaScript/fast-check)
    - **Property 7: Queue Navigation Correctness**
    - **Validates: Requirements 3.4, 3.5, 3.6, 3.7, 5.3**

  - [x] 5.6 Write property tests for queue replacement (JavaScript/fast-check)
    - **Property 8: Queue Replacement on New Load**
    - **Validates: Requirements 7.1, 7.2, 7.4**

  - [x] 5.7 Write property test for queue index invariant (JavaScript/fast-check)
    - **Property 9: Queue Index Invariant**
    - **Validates: Requirements 7.3**

  - [x] 5.8 Write property test for togglePlayPause involution (JavaScript/fast-check)
    - **Property 6: Play/Pause Toggle is Its Own Inverse**
    - **Validates: Requirements 3.2, 3.3**

  - [x] 5.9 Write property test for progress bar calculation (JavaScript/fast-check)
    - **Property 5: Progress Bar Calculation**
    - **Validates: Requirements 2.2**

  - [x] 5.10 Write property test for search selection populating queue (JavaScript/fast-check)
    - **Property 10: Search Selection Populates Queue**
    - **Validates: Requirements 4.5**

- [x] 6. Checkpoint - Frontend player functional
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Responsive layout, chat integration, and error handling
  - [x] 7.1 Implement responsive layout for mobile screens
    - Add CSS media queries for screens below 500px
    - Reduce padding, use compact layout for controls
    - Ensure chat interface remains accessible when player is visible
    - _Requirements: 8.2, 8.3_

  - [x] 7.2 Wire chat-triggered playback to the music player
    - Update frontend chat response handler to detect `action: "play_music_embed"`
    - Extract track from response and call `musicPlayer.loadTrack(track)`
    - Show Now Playing panel automatically on chat-triggered playback
    - _Requirements: 1.2, 1.3_

  - [x] 7.3 Implement minimize/background playback behavior
    - Close button hides the panel without pausing playback
    - Add a minimal indicator or re-open trigger when player is minimized
    - _Requirements: 8.4, 8.5_

  - [x] 7.4 Implement error handling and graceful degradation
    - If YouTube IFrame API fails to load, fall back to opening YouTube URL in new tab
    - Show toast notifications for skipped/unavailable tracks
    - Display "Player unavailable" when API cannot load
    - Show "Search failed" message on network errors during search
    - _Requirements: 5.5, 1.4_

  - [x] 7.5 Write integration tests for end-to-end chat → playback flow
    - Send "play bohemian rhapsody" via `/chat`, verify response structure
    - Test search → select → play flow
    - Test auth enforcement on music endpoints
    - _Requirements: 1.1, 1.2, 4.4, 6.5_

  - [x] 7.6 Write property test for Now Playing rendering (JavaScript/fast-check)
    - **Property 4: Now Playing Renders All Track Fields**
    - **Validates: Requirements 1.3, 2.1**

- [x] 8. Final checkpoint - All features integrated
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The backend uses Python (Flask + Hypothesis for PBT), frontend uses vanilla JavaScript (fast-check + vitest for PBT)
- YouTube Data API v3 key must be added to environment variables before backend tasks can run

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["1.4", "1.5", "1.6", "2.1", "2.2"] },
    { "id": 2, "tasks": ["2.3", "2.4"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "5.1"] },
    { "id": 5, "tasks": ["5.2", "5.3", "5.4"] },
    { "id": 6, "tasks": ["5.5", "5.6", "5.7", "5.8", "5.9", "5.10"] },
    { "id": 7, "tasks": ["7.1", "7.2", "7.3", "7.4"] },
    { "id": 8, "tasks": ["7.5", "7.6"] }
  ]
}
```
