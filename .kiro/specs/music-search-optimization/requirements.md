# Requirements Document

## Introduction

This feature optimizes the music search experience in the FRIDAY AI assistant by adding real-time autocomplete suggestions, multi-language support for Indian and international languages, comprehensive religious/devotional music coverage, fuzzy matching with typo correction ("Did you mean...?"), and aggregation of results from multiple music sources beyond the current YouTube-only implementation.

## Glossary

- **Search_Engine**: The backend service responsible for processing music search queries, applying fuzzy matching, and aggregating results from multiple music sources
- **Autocomplete_Service**: The component that provides real-time suggestions as the user types in the search input field
- **Music_Aggregator**: The component that queries multiple music source APIs and merges results into a unified list
- **Fuzzy_Matcher**: The component that detects typos and misspellings in search queries and suggests corrections
- **Search_Input**: The text input field in the music player UI where users type song queries (`.mp-search-input` element)
- **Suggestion_Panel**: The dropdown UI element that displays autocomplete suggestions below the Search_Input
- **Correction_Banner**: The UI element that displays "Did you mean...?" suggestions when a typo is detected
- **Music_Source**: An external API or service that provides music metadata and playback capability (e.g., YouTube Data API, Spotify, JioSaavn, Gaana)
- **Script**: A writing system used for a language (e.g., Devanagari for Hindi, Tamil script for Tamil, Telugu script for Telugu)

## Requirements

### Requirement 1: Real-Time Autocomplete Suggestions

**User Story:** As a user, I want to see live song suggestions as I type in the search box, so that I can quickly find and select the song I want without typing the full name.

#### Acceptance Criteria

1. WHEN the user types at least 2 characters in the Search_Input, THE Autocomplete_Service SHALL display suggestions in the Suggestion_Panel within 300 milliseconds of the last keystroke, and WHEN the input length drops below 2 characters, THE Suggestion_Panel SHALL hide and clear all displayed suggestions
2. THE Autocomplete_Service SHALL debounce keystrokes with a 250-millisecond delay to avoid excessive API calls
3. WHEN suggestions are available, THE Suggestion_Panel SHALL display a maximum of 8 suggestions, each showing the song title (truncated to 60 characters), artist name (truncated to 40 characters), and thumbnail image
4. WHEN the user selects a suggestion from the Suggestion_Panel, THE Search_Engine SHALL begin loading the selected track within 1 second and display a loading indicator until playback starts
5. WHEN the user clears the Search_Input, THE Suggestion_Panel SHALL hide and clear all displayed suggestions
6. WHEN the Autocomplete_Service receives no matching results, THE Suggestion_Panel SHALL display a "No results found" message
7. IF the Autocomplete_Service fails to respond within 2 seconds or returns an error, THEN THE Suggestion_Panel SHALL hide the loading indicator and display a brief error message indicating suggestions are temporarily unavailable

### Requirement 2: Multi-Language Search Support

**User Story:** As a user, I want to search for songs in my regional language (Tamil, Hindi, Telugu, or other Indian languages) as well as international languages, so that I can find music regardless of which language or script I type in.

#### Acceptance Criteria

1. THE Search_Engine SHALL accept queries of up to 200 characters written in English, Tamil, Hindi, Telugu, Kannada, Malayalam, Bengali, Marathi, Gujarati, and Punjabi scripts, and return music results matching the query terms
2. WHEN a query is submitted in a non-Latin script, THE Search_Engine SHALL preserve the original script characters and pass them to all Music_Source APIs without transliteration
3. WHEN a query contains mixed-script text (e.g., English and Tamil), THE Search_Engine SHALL send the full query as a single unsplit search string to all Music_Source APIs without separating by script boundaries
4. THE Search_Engine SHALL return results with metadata (title, artist) in the original language of the content, without forced translation to English
5. WHEN a user searches using a romanized form of a non-English language (e.g., "Nenjukkul Peidhidum" for a Tamil song), THE Search_Engine SHALL match results that contain either the romanized form or the native script equivalent in the title or artist fields
6. IF a query contains only characters from scripts not listed in criterion 1, THEN THE Search_Engine SHALL still forward the query to all Music_Source APIs and return any available results without displaying an error

### Requirement 3: Religious and Devotional Music Coverage

**User Story:** As a user, I want to find religious and devotional songs from all traditions, so that I can listen to bhajans, hymns, naat, shabad, and other devotional music easily.

#### Acceptance Criteria

1. WHEN a query contains a whole-word, case-insensitive match for any devotional keyword (bhajan, kirtan, hymn, naat, shabad, stotram, paadal, keerthanai, azan, psalm, gospel), THE Search_Engine SHALL rank results from devotional and spiritual music categories such that at least 70% of the first 10 results belong to devotional categories, while still including non-devotional matches in the remaining results
2. THE Music_Aggregator SHALL include at least one Music_Source that specializes in or has a dedicated devotional music catalog
3. WHEN returning devotional music results, THE Search_Engine SHALL include the tradition or genre label (e.g., "Hindu Bhajan", "Sikh Shabad", "Islamic Naat", "Christian Hymn") in the result metadata for each result identified as devotional content
4. THE Search_Engine SHALL support devotional music searches in all scripts and languages defined in Requirement 2, accepting devotional keywords in both native script and romanized form
5. IF a query contains a devotional keyword but no results from devotional music categories are available, THEN THE Search_Engine SHALL return general search results and display a message indicating that no devotional-specific results were found

### Requirement 4: Typo Correction and Fuzzy Matching

**User Story:** As a user, I want the search to suggest correct song names even when I make spelling mistakes, so that I still find the right song without retyping.

#### Acceptance Criteria

1. WHEN a query of at least 3 characters returns zero exact title or artist matches from any Music_Source AND the Fuzzy_Matcher identifies a catalog entry within an edit distance of 2 or fewer characters, THE Search_Engine SHALL display a Correction_Banner with "Did you mean: [corrected query]?"
2. WHEN the user clicks the corrected query in the Correction_Banner, THE Search_Engine SHALL execute a new search using the corrected query and dismiss the Correction_Banner
3. WHEN the Fuzzy_Matcher displays a Correction_Banner, THE Search_Engine SHALL simultaneously return results where at least one query token matches a song title or artist name token within an edit distance of 2 or fewer characters, ranked below exact matches
4. WHEN a query of at least 3 characters shares a matching prefix or contiguous substring of 3 or more characters with a known song title or artist name, THE Fuzzy_Matcher SHALL include up to 10 partial matches in the results ranked by match length
5. WHEN a romanized query for an Indian language song is submitted, THE Fuzzy_Matcher SHALL treat common vowel-length variations (e.g., "i" vs "ee", "u" vs "oo") and word-boundary variations (e.g., "Tumhi" vs "Tum hi") as equivalent matches
6. WHEN the user submits a new query or clears the Search_Input, THE Search_Engine SHALL dismiss any currently displayed Correction_Banner

### Requirement 5: Multi-Source Music Aggregation

**User Story:** As a user, I want search results pulled from multiple music libraries and services, so that I have the widest possible selection of songs available to play.

#### Acceptance Criteria

1. THE Music_Aggregator SHALL query at least 3 distinct Music_Sources for each search request
2. THE Music_Aggregator SHALL merge results from all Music_Sources into a single ranked list of up to 20 results, removing duplicate tracks identified by matching title and artist name with case-insensitive comparison
3. WHEN a Music_Source fails to respond within 5 seconds, THE Music_Aggregator SHALL return results from the remaining available sources without waiting
4. THE Music_Aggregator SHALL include a source label for each result indicating which Music_Source provided the track
5. THE Search_Engine SHALL retain YouTube Data API v3 as one Music_Source and add additional sources such as JioSaavn, Gaana, Spotify, or SoundCloud
6. WHEN all Music_Sources fail to return results, THE Search_Engine SHALL display an error message indicating temporary unavailability and suggest the user retry

### Requirement 6: Search Performance and Responsiveness

**User Story:** As a user, I want the search to feel fast and responsive, so that I do not experience lag or delays while looking for music.

#### Acceptance Criteria

1. THE Search_Engine SHALL return aggregated results from all Music_Sources within 3 seconds of query submission when network round-trip latency is at or below 100 milliseconds and available bandwidth is at least 1 Mbps
2. WHILE the Search_Engine is processing a query, THE Search_Input SHALL display a loading indicator within 200 milliseconds of query submission and remove it when results are rendered or an error is displayed
3. WHEN a new query is submitted before the previous query completes, THE Search_Engine SHALL cancel the previous in-flight request, remove its loading indicator, and process only the latest query
4. THE Autocomplete_Service SHALL cache up to 50 recent query results on the client side for 5 minutes to reduce redundant API calls for repeated queries
5. IF the network connection is lost during a search, THEN THE Search_Engine SHALL display an offline error message and retry automatically up to 3 times at 5-second intervals when connectivity is restored, after which it SHALL display a persistent error message requiring the user to manually retry
