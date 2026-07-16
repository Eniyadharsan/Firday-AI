# Implementation Plan: Music Player Redesign

## Overview

Refactor the JARVIS music player from a full-width bottom-fixed bar into a compact floating "liquid glass" overlay panel. The implementation restructures the existing `MusicPlayer` class and DOM layout in `public/index.html`, adds a `PanelManager` for animation state, a `MusicToggleButton` for independent visibility control, and applies glassmorphism CSS. All backend endpoints remain unchanged.

## Tasks

- [x] 1. Create glassmorphism CSS and responsive panel styles
  - [x] 1.1 Add Music Panel glassmorphism CSS styles
    - Replace the existing full-width bottom-fixed `.music-panel` styles with the new floating overlay styles
    - Add `position: fixed`, `bottom: 16px`, `right: 16px`, `max-width: 340px`, `max-height: 50vh`, `overflow-y: auto`
    - Add `background: rgba(10, 22, 40, 0.25)`, `backdrop-filter: blur(20px)`, `-webkit-backdrop-filter: blur(20px)`
    - Add `border: 1px solid rgba(0, 229, 255, 0.15)`, `box-shadow: 0 8px 20px rgba(0, 0, 0, 0.25)`, `border-radius: 16px`
    - Add `z-index: 150` (above chat, below modals)
    - Add `@supports not (backdrop-filter: blur(1px))` fallback with `background: rgba(10, 22, 40, 0.8)`
    - _Requirements: 1.1, 1.2, 1.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 1.2 Add responsive breakpoint styles
    - Add `@media (max-width: 500px)` rule: `max-width: none`, `width: calc(100vw - 32px)`, `left: 16px`, `right: 16px`
    - Ensure panel respects `max-height: 50vh` on all viewports
    - Verify text/icon contrast ratio >= 4.5:1 against glassmorphism background
    - _Requirements: 1.5, 3.7, 6.1, 6.2, 6.3, 6.4_

  - [x] 1.3 Add open/close animation CSS classes
    - Create `.music-panel.hidden` class with `transform: scale(0.95)`, `opacity: 0`, `pointer-events: none`
    - Create `.music-panel.visible` class with `transform: scale(1)`, `opacity: 1`, `pointer-events: auto`
    - Add `transition` property with `ease-out` for showing (300ms) and `ease-in` for hiding (250ms)
    - Ensure `pointer-events: none` is applied when panel is hidden
    - _Requirements: 7.1, 7.2, 7.3_

- [x] 2. Implement Toggle Button component
  - [x] 2.1 Create MusicToggleButton class
    - Create a persistent toggle button element fixed at bottom-right (offset from panel position)
    - Implement `render()` method to inject the button into the DOM
    - Implement `setState(state)` method supporting `'idle'`, `'playing'`, and `'disabled'` visual states
    - Add click handler that delegates to PanelManager's `toggle()` method
    - Ensure the button is always visible after MusicPlayer initialization regardless of track state
    - _Requirements: 2.1, 2.6_

  - [x] 2.2 Add playing indicator animation to toggle button
    - Implement CSS pulsing/glowing animation for the `'playing'` state
    - Animation activates when YouTube IFrame player is playing and panel is hidden
    - Ensure visual indicator is distinguishable from the idle state
    - _Requirements: 2.4_

- [x] 3. Implement PanelManager (Animation Controller)
  - [x] 3.1 Create PanelManager class with state machine
    - Implement state property tracking: `'hidden'` | `'animating_in'` | `'visible'` | `'animating_out'`
    - Implement `show()` method: transition from hidden to visible with scale/opacity animation
    - Implement `hide()` method: transition from visible to hidden with scale/opacity animation
    - Implement `toggle()` method that handles mid-animation reversal
    - Use `transitionend` event listener to detect animation completion and update state
    - _Requirements: 2.2, 2.3, 7.1, 7.2_

  - [x] 3.2 Handle animation edge cases
    - Implement `_reverseAnimation()` to cancel current transition and reverse from intermediate state
    - Ignore toggle clicks while transition is in progress (via state check) per Requirement 2.5
    - Implement fallback for browsers without CSS transitions (immediate show/hide)
    - Apply `pointer-events: none` when panel state is `'hidden'` or `'animating_out'`
    - _Requirements: 2.5, 7.3, 7.4_

  - [x] 3.3 Implement backdrop-filter detection and fallback
    - Use `CSS.supports('backdrop-filter', 'blur(1px)')` to detect support at runtime
    - If unsupported, add a CSS class that applies solid semi-transparent background (opacity 0.7-0.85)
    - _Requirements: 3.6_

- [x] 4. Checkpoint - Ensure panel shell, toggle, and animations work
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Redesign MusicPlayer DOM structure for compact layout
  - [x] 5.1 Restructure panel HTML for compact floating layout
    - Replace the existing full-width music panel DOM structure in `public/index.html`
    - Add album art thumbnail element constrained to 48x48px
    - Add track title and artist elements with single-line truncation (text-overflow: ellipsis, overflow: hidden, white-space: nowrap)
    - Arrange playback controls (prev, play/pause, next) in a compact row
    - Add close button to the panel header
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 5.2 Update progress bar and time display
    - Implement progress bar with filled width proportional to `currentTime / duration`
    - Add current time label (left) and total duration label (right) in `mm:ss` format
    - Update `formatTime()` to return `h:mm:ss` for tracks >= 3600 seconds
    - _Requirements: 4.4, 4.5_

  - [ ]* 5.3 Write property test for time formatting (Property 3)
    - **Property 3: Time Formatting**
    - For any non-negative number of seconds, formatTime returns `m:ss` when s < 3600 or `h:mm:ss` when s >= 3600
    - Use `fast-check` with `fc.nat()` to generate random second values
    - **Validates: Requirements 4.5**

  - [ ]* 5.4 Write property test for progress bar proportionality (Property 2)
    - **Property 2: Progress Bar Proportionality**
    - For any currentTime `t` and duration `d` where d > 0, filled width % equals `(t/d) * 100` ± 1%
    - Use `fast-check` with `fc.float()` to generate random time/duration pairs
    - **Validates: Requirements 4.4**

- [x] 6. Implement search UI within compact panel
  - [x] 6.1 Restructure search input and results within panel
    - Move search input inside the Music Panel DOM structure
    - Add `maxlength="200"` attribute and JS validation for 200-char limit
    - Implement debounced autocomplete (250ms delay) triggering after >= 2 characters
    - Clear suggestions when input drops below 2 characters
    - _Requirements: 5.1, 5.2, 5.7_

  - [x] 6.2 Implement search results display and selection
    - Display up to 8 autocomplete suggestions in a dropdown within panel boundaries
    - Display up to 20 search results in a scrollable list within panel boundaries
    - On result selection, initiate playback with a loading indicator until playback starts
    - _Requirements: 5.2, 5.3, 5.4_

  - [x] 6.3 Add search error handling
    - Display "Search temporarily unavailable" on 5-second timeout or network error
    - Display "No results found" when search returns zero results
    - Ensure error messages render within the search area inside the panel
    - _Requirements: 5.5, 5.6_

  - [ ]* 6.4 Write property test for search input validation (Property 4)
    - **Property 4: Search Input Validation**
    - For any string input, if length > 200 it is rejected/truncated; if length < 2 suggestions are cleared
    - Use `fast-check` with `fc.string()` to generate random input strings
    - **Validates: Requirements 5.1, 5.7**

  - [ ]* 6.5 Write property test for autocomplete suggestions cap (Property 5)
    - **Property 5: Autocomplete Suggestions Cap**
    - For any autocomplete response with N > 8 items, at most 8 are displayed
    - Use `fast-check` with `fc.array()` to generate variable-length suggestion arrays
    - **Validates: Requirements 5.2**

  - [ ]* 6.6 Write property test for search results cap (Property 6)
    - **Property 6: Search Results Cap**
    - For any search response with N > 20 items, at most 20 are rendered
    - Use `fast-check` with `fc.array()` to generate variable-length result arrays
    - **Validates: Requirements 5.4**

- [x] 7. Checkpoint - Ensure search and layout function correctly
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Wire all components together and integrate
  - [x] 8.1 Initialize components and wire toggle/panel/player
    - Instantiate `MusicToggleButton` and `PanelManager` after DOM load
    - Wire toggle button click to `PanelManager.toggle()`
    - Wire panel close button to `PanelManager.hide()`
    - Connect `MusicPlayer` playback state changes to toggle button `setState()` (show playing indicator when audio plays and panel is hidden)
    - Ensure `MusicPlayer.initControls()` and `MusicPlayer.initSearch()` work with new DOM structure
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6_

  - [x] 8.2 Ensure chat remains interactive with panel open
    - Verify the panel does not intercept pointer events on the chat area
    - Verify chat scrolling works while panel is visible
    - Verify panel z-index is above chat but below modal dialogs
    - _Requirements: 1.3, 1.4, 4.6_

  - [ ]* 8.3 Write property test for responsive panel sizing (Property 1)
    - **Property 1: Responsive Panel Sizing**
    - For any viewport (width, height): if width <= 500 then panel width === width - 32; if width > 500 then panel width <= 340; panel height <= min(320, height * 0.5)
    - Use `fast-check` with `fc.integer()` to generate random viewport dimensions
    - **Validates: Requirements 1.1, 1.2, 1.5, 6.1, 6.2, 6.3**

  - [ ]* 8.4 Write property test for text truncation (Property 7)
    - **Property 7: Text Truncation**
    - For any track title/artist string exceeding container width, rendered element applies ellipsis and does not exceed parent width
    - Use `fast-check` with `fc.string()` to generate random-length title/artist strings
    - **Validates: Requirements 4.2**

  - [ ]* 8.5 Write unit tests for toggle and animation behavior
    - Test toggle button visibility after initialization
    - Test animation timing within 250-350ms (show) and 200-300ms (hide)
    - Test pointer-events disabled when hidden
    - Test click debounce during animation
    - Test mid-animation reversal
    - _Requirements: 2.2, 2.3, 2.5, 7.1, 7.2, 7.3, 7.4_

- [x] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The backend `/music/search` and `/music/autocomplete` endpoints remain unchanged
- All implementation is within `public/index.html` (inline JS/CSS) matching the existing project structure
- `fast-check` should be loaded via CDN or npm depending on project test runner setup

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1", "2.2", "3.1"] },
    { "id": 2, "tasks": ["3.2", "3.3"] },
    { "id": 3, "tasks": ["5.1", "5.2"] },
    { "id": 4, "tasks": ["5.3", "5.4", "6.1"] },
    { "id": 5, "tasks": ["6.2", "6.3"] },
    { "id": 6, "tasks": ["6.4", "6.5", "6.6"] },
    { "id": 7, "tasks": ["8.1", "8.2"] },
    { "id": 8, "tasks": ["8.3", "8.4", "8.5"] }
  ]
}
```
