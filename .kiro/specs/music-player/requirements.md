# Requirements Document

## Introduction

This feature adds a fully functional, embedded music player to the Jarvis AI Assistant. Currently, the music module detects play requests and returns YouTube search URLs that open in a new tab — the song never actually plays within Jarvis. This feature replaces that behavior with an in-app music player featuring an Apple Music-inspired "Now Playing" UI, functional playback controls, search capability, and embedded audio/video playback via the YouTube IFrame API. The player is accessible from the chat interface and operates within the existing Flask + vanilla JS frontend deployed on Vercel.

## Glossary

- **Music_Player**: The embedded frontend component responsible for rendering the Now Playing screen, playback controls, and search interface within the Jarvis UI
- **YouTube_IFrame_Player**: The YouTube IFrame Player API instance that handles actual audio/video playback within the browser
- **Now_Playing_Screen**: The visual panel displaying album art, track title, artist name, and playback progress for the currently playing track
- **Playback_Controls**: The set of interactive buttons providing play/pause, previous track, and next track functionality
- **Search_Interface**: The UI component allowing users to type a query and browse matching song results before selecting one to play
- **Music_Backend**: The Flask backend endpoints responsible for searching songs and returning playable track metadata (video IDs, titles, thumbnails)
- **Track_Queue**: An ordered list of tracks maintained by the Music_Player for sequential playback and previous/next navigation
- **Chat_Interface**: The existing Jarvis chat input and message area where users issue natural language commands

## Requirements

### Requirement 1: Chat-Triggered Music Playback

**User Story:** As a user, I want to ask Jarvis to play a song via the chat interface, so that music starts playing directly within the app without opening external tabs.

#### Acceptance Criteria

1. WHEN a user sends a message matching a music play request pattern, THE Music_Backend SHALL search for the requested song and return a playable video ID, track title, artist name, and thumbnail URL
2. WHEN the Music_Backend returns track metadata, THE Music_Player SHALL load the track into the YouTube_IFrame_Player and begin playback automatically
3. WHEN playback begins from a chat command, THE Now_Playing_Screen SHALL become visible displaying the track title, artist name, and thumbnail
4. IF the Music_Backend cannot find a matching track, THEN THE Chat_Interface SHALL display an error message indicating no results were found

### Requirement 2: Now Playing Screen

**User Story:** As a user, I want to see a beautiful Now Playing screen with album art and track info, so that I have an Apple Music-style visual experience while listening.

#### Acceptance Criteria

1. WHILE a track is playing, THE Now_Playing_Screen SHALL display the track thumbnail as album art, the track title, and the artist name
2. WHILE a track is playing, THE Now_Playing_Screen SHALL display a progress bar indicating current playback position relative to total track duration
3. THE Now_Playing_Screen SHALL use an Apple Music-inspired aesthetic with smooth animations, blurred background derived from album art, rounded corners, and a dark translucent panel consistent with the existing Jarvis HUD theme
4. WHEN no track is loaded, THE Now_Playing_Screen SHALL remain hidden and not occupy screen space

### Requirement 3: Playback Controls

**User Story:** As a user, I want play/pause, previous track, and next track buttons, so that I can control music playback without typing commands.

#### Acceptance Criteria

1. THE Playback_Controls SHALL include a play/pause toggle button, a previous track button, and a next track button
2. WHEN the user clicks the play/pause button while a track is playing, THE YouTube_IFrame_Player SHALL pause playback and the button icon SHALL change to a play icon
3. WHEN the user clicks the play/pause button while playback is paused, THE YouTube_IFrame_Player SHALL resume playback and the button icon SHALL change to a pause icon
4. WHEN the user clicks the next track button and a next track exists in the Track_Queue, THE Music_Player SHALL load and play the next track
5. WHEN the user clicks the previous track button and a previous track exists in the Track_Queue, THE Music_Player SHALL load and play the previous track
6. IF the user clicks the next track button and no next track exists in the Track_Queue, THEN THE next track button SHALL remain inactive and no action SHALL occur
7. IF the user clicks the previous track button and no previous track exists in the Track_Queue, THEN THE previous track button SHALL remain inactive and no action SHALL occur

### Requirement 4: Song Search Interface

**User Story:** As a user, I want a search box in the music player to find and play songs, so that I can browse for music without using the chat.

#### Acceptance Criteria

1. THE Search_Interface SHALL provide a text input field where the user can type a song query
2. WHEN the user submits a search query, THE Music_Backend SHALL return a list of matching tracks with titles, artist names, thumbnail URLs, and video IDs
3. WHEN search results are returned, THE Search_Interface SHALL display the results as a scrollable list showing thumbnail, title, and artist for each track
4. WHEN the user selects a track from the search results, THE Music_Player SHALL load the selected track into the YouTube_IFrame_Player and begin playback
5. WHEN the user selects a track from search results, THE Music_Player SHALL add remaining search results to the Track_Queue as upcoming tracks
6. IF the search query returns no results, THEN THE Search_Interface SHALL display a message indicating no songs were found

### Requirement 5: Embedded Audio Playback via YouTube

**User Story:** As a user, I want the music to actually play within the Jarvis app, so that I do not need to leave the interface or open new browser tabs.

#### Acceptance Criteria

1. THE Music_Player SHALL embed the YouTube IFrame Player API to handle audio/video playback within the page
2. THE YouTube_IFrame_Player SHALL be rendered as a hidden or minimal visual element so the Now_Playing_Screen provides the primary visual experience
3. WHEN a track finishes playing and a next track exists in the Track_Queue, THE Music_Player SHALL automatically advance to the next track
4. WHEN a track finishes playing and no next track exists in the Track_Queue, THE Music_Player SHALL stop playback and update the Playback_Controls to show the play icon
5. IF the YouTube_IFrame_Player fails to load a video due to restrictions or unavailability, THEN THE Music_Player SHALL skip to the next track in the queue and display a brief notification

### Requirement 6: Music Search Backend Endpoint

**User Story:** As a developer, I want a backend endpoint that searches YouTube for songs and returns structured metadata, so that the frontend can display results and play tracks.

#### Acceptance Criteria

1. THE Music_Backend SHALL expose a GET or POST endpoint at /music/search that accepts a query parameter
2. WHEN the /music/search endpoint receives a valid query, THE Music_Backend SHALL return a JSON array of track objects each containing video_id, title, artist, and thumbnail_url fields
3. THE Music_Backend SHALL return a maximum of 10 results per search query
4. IF the /music/search endpoint receives an empty query, THEN THE Music_Backend SHALL return a 400 status code with an error message
5. THE /music/search endpoint SHALL require authentication consistent with other Jarvis API endpoints

### Requirement 7: Track Queue Management

**User Story:** As a user, I want the player to maintain a queue of tracks, so that I can skip between songs and have continuous playback.

#### Acceptance Criteria

1. WHEN a track is played from a chat command, THE Music_Player SHALL add the track to the Track_Queue and set it as the current track
2. WHEN multiple search results are loaded, THE Music_Player SHALL populate the Track_Queue with all results in order
3. THE Music_Player SHALL maintain a current track index within the Track_Queue to support previous and next navigation
4. WHEN the user plays a new track from search or chat, THE Music_Player SHALL clear the existing queue and start a new queue with the new results

### Requirement 8: Responsive Layout and Integration

**User Story:** As a user, I want the music player to fit within the existing Jarvis UI without breaking the layout, so that I can use chat and music features simultaneously.

#### Acceptance Criteria

1. THE Music_Player SHALL be positioned as a fixed panel at the bottom of the viewport, above the chat input area
2. WHILE the Music_Player is visible, THE Chat_Interface SHALL remain accessible and functional
3. THE Music_Player SHALL adapt to mobile screen widths (below 500px) by reducing padding and using compact layout
4. THE Now_Playing_Screen SHALL include a close/minimize button to hide the player panel when not needed
5. WHEN the user minimizes the Music_Player, THE YouTube_IFrame_Player SHALL continue playback in the background
