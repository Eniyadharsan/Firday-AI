# Requirements Document

## Introduction

Redesign the JARVIS music player from a full-width bottom-fixed panel into a compact, floating "liquid glass" panel. The new player operates as an independent, draggable overlay that does not block chat interaction. It uses glassmorphism (frosted glass, transparency, backdrop blur) to match a modern aesthetic while remaining functional with now-playing info, playback controls, progress tracking, and song search.

## Glossary

- **Music_Panel**: The floating, compact music player UI container rendered as a glassmorphism overlay inside the JARVIS viewport.
- **JARVIS_Chat**: The main conversational interface of the JARVIS assistant where users send and receive messages.
- **Toggle_Button**: A persistent UI element that opens or closes the Music_Panel independently of other UI state.
- **Liquid_Glass_Style**: A visual design combining semi-transparent backgrounds, backdrop blur, subtle borders, and soft shadows to create a frosted-glass appearance.
- **Playback_Controls**: The set of buttons for play/pause, next track, and previous track within the Music_Panel.
- **Progress_Bar**: A visual indicator showing the current playback position relative to the total track duration.
- **Search_Input**: A text field within the Music_Panel that allows the user to search for songs.

## Requirements

### Requirement 1: Floating Panel Positioning

**User Story:** As a user, I want the music player to appear as a floating panel inside the JARVIS UI, so that it does not cover the full width of the screen or block the chat area.

#### Acceptance Criteria

1. THE Music_Panel SHALL render as a fixed-position overlay with a maximum width of 400px and a maximum height of 320px rather than spanning the full viewport width.
2. THE Music_Panel SHALL default to the bottom-right region of the viewport with a minimum margin of 16px from the right and bottom viewport edges.
3. WHILE the Music_Panel is visible, THE JARVIS_Chat SHALL remain fully interactive and scrollable, with no pointer events on the chat area blocked by the panel.
4. THE Music_Panel SHALL render above chat content but below modal dialogs in the stacking order.
5. IF the viewport width is less than 432px, THEN THE Music_Panel SHALL expand to fill the available viewport width minus 16px horizontal margin on each side.

### Requirement 2: Independent Toggle Visibility

**User Story:** As a user, I want to open and close the music player independently, so that I can access it whenever I want without interrupting my conversation with JARVIS.

#### Acceptance Criteria

1. WHILE the Music_Panel is closed, THE Toggle_Button SHALL remain visible at a fixed position in the JARVIS UI without overlapping the Chat_Interface.
2. WHEN the user clicks the Toggle_Button while the Music_Panel is hidden, THE Music_Panel SHALL transition from hidden to visible with a CSS transition completing within 300 milliseconds.
3. WHEN the user clicks the close button on the Music_Panel while the Music_Panel is visible, THE Music_Panel SHALL transition from visible to hidden with a CSS transition completing within 300 milliseconds.
4. WHILE the Music_Panel is hidden and the YouTube_IFrame_Player is actively playing audio, THE Toggle_Button SHALL display an animated visual indicator (such as a pulsing or glowing effect) distinguishable from the idle state to signal that playback is active.
5. IF the user clicks the Toggle_Button while the panel transition animation is in progress, THEN THE System SHALL ignore the click until the current transition completes.
6. THE Toggle_Button SHALL be visible in the JARVIS UI at all times after the Music_Player component has been initialized, regardless of whether a track has been loaded.

### Requirement 3: Liquid Glass Visual Design

**User Story:** As a user, I want the music player to have a frosted-glass aesthetic, so that it feels modern and blends into the JARVIS UI without harsh visual boundaries.

#### Acceptance Criteria

1. THE Music_Panel SHALL use a semi-transparent background with opacity between 0.15 and 0.4 for its base layer.
2. THE Music_Panel SHALL apply a backdrop-filter blur between 16px and 30px to produce the frosted glass effect.
3. THE Music_Panel SHALL have a border of 1px width with a color opacity between 0.1 and 0.3 to define its edges.
4. THE Music_Panel SHALL apply a box-shadow with a blur-radius between 8px and 24px and a shadow color opacity no greater than 0.3 to create depth separation from the background.
5. THE Music_Panel SHALL have rounded corners with a border-radius between 12px and 24px.
6. IF the browser does not support the backdrop-filter property, THEN THE Music_Panel SHALL fall back to a solid semi-transparent background with opacity between 0.7 and 0.85 to maintain panel visibility.
7. THE Music_Panel SHALL ensure all text and icon elements have a minimum contrast ratio of 4.5:1 against the panel background layer.

### Requirement 4: Compact Layout with Full Functionality

**User Story:** As a user, I want the compact player to still show album art, track info, playback controls, and a progress bar, so that I can control music without needing a full-screen panel.

#### Acceptance Criteria

1. THE Music_Panel SHALL display album art as a thumbnail no larger than 48x48 pixels.
2. THE Music_Panel SHALL display the current track title and artist name each as a single line of text, truncated with an ellipsis when the text exceeds the available container width.
3. THE Music_Panel SHALL contain Playback_Controls for previous, play/pause, and next track.
4. THE Music_Panel SHALL contain a Progress_Bar whose filled width is proportional to the ratio of current playback position to total track duration.
5. THE Music_Panel SHALL display current time and total duration labels in mm:ss format (or h:mm:ss for tracks 60 minutes or longer) positioned on the left and right sides of the Progress_Bar respectively.
6. WHILE a track is loaded, THE Music_Panel SHALL remain visible and not obscure the JARVIS_Chat content area.

### Requirement 5: Integrated Song Search

**User Story:** As a user, I want to search for songs directly within the compact player, so that I can find and play music without switching context.

#### Acceptance Criteria

1. THE Music_Panel SHALL contain a Search_Input field that accepts song queries of up to 200 characters.
2. WHEN the user types at least 2 characters in the Search_Input, THE Music_Panel SHALL display up to 8 search suggestions below the input within 300 milliseconds of the last keystroke, debouncing keystrokes with a 250-millisecond delay.
3. WHEN the user selects a search result, THE Music_Panel SHALL begin playback of the selected track within 3 seconds and display a loading indicator until playback starts.
4. THE search results list SHALL be scrollable, display a maximum of 20 results, and remain contained within the Music_Panel boundaries.
5. IF the search request fails to respond within 5 seconds or returns a network error, THEN THE Music_Panel SHALL display an error message within the search area indicating that the search is temporarily unavailable.
6. WHEN the search request returns zero matching results, THE Music_Panel SHALL display a "No results found" message within the search area.
7. WHEN the user clears the Search_Input or the input length drops below 2 characters, THE Music_Panel SHALL hide and clear all displayed suggestions.

### Requirement 6: Responsive Sizing

**User Story:** As a user on a mobile device, I want the music player panel to adapt its size appropriately, so that it remains usable without overwhelming the smaller screen.

#### Acceptance Criteria

1. WHILE the viewport width is 500px or less, THE Music_Panel SHALL expand to occupy the full viewport width minus 16px of horizontal margin on each side.
2. WHILE the viewport width is greater than 500px, THE Music_Panel SHALL maintain a maximum width of 340px.
3. THE Music_Panel SHALL have a maximum height of 50% of the viewport height.
4. WHILE the Music_Panel content exceeds its maximum height, THE Music_Panel SHALL allow vertical scrolling within its container to access all content.

### Requirement 7: Smooth Open/Close Animations

**User Story:** As a user, I want the panel to open and close smoothly, so that the transitions feel polished and intentional.

#### Acceptance Criteria

1. WHEN the Music_Panel transitions to visible, THE Music_Panel SHALL animate from scale 0.95 and opacity 0 to scale 1.0 and opacity 1 using an ease-out timing function over 250-350ms.
2. WHEN the Music_Panel transitions to hidden, THE Music_Panel SHALL animate from scale 1.0 and opacity 1 to scale 0.95 and opacity 0 using an ease-in timing function over 200-300ms.
3. WHILE the Music_Panel is hidden, THE Music_Panel SHALL have pointer-events disabled to avoid blocking underlying UI.
4. IF a toggle action occurs while an open or close animation is in progress, THEN THE Music_Panel SHALL cancel the current animation and immediately begin the reverse animation from the current intermediate state.
