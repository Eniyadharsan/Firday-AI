# Implementation Plan: Music Search Optimization

## Overview

This plan implements the enhanced music search system for the FRIDAY AI assistant. The implementation progresses from core data models and interfaces, through individual components (Language Processor, Fuzzy Matcher, Music Aggregator, Autocomplete Service), to API endpoint wiring and frontend integration. Each step builds incrementally on previous work, ensuring no orphaned code.

## Tasks

- [x] 1. Set up core data models and interfaces
  - [x] 1.1 Create data models and adapter interface
    - Create `friday/modules/music_models.py` with `TrackResult`, `Suggestion`, `FuzzyMatch`, `AggregatedResult`, `SearchContext` dataclasses
    - Define the `MusicSourceAdapter` protocol class with `source_name`, `search()`, and `is_available()` methods
    - Include type hints and docstrings for all models
    - _Requirements: 5.4, 5.2, 3.3_

  - [x] 1.2 Refactor existing YouTube search into adapter pattern
    - Create `friday/modules/music_youtube_adapter.py` implementing `MusicSourceAdapter`
    - Move YouTube Data API v3 search logic from `friday/modules/music.py` into the new adapter
    - Ensure the adapter returns `TrackResult` objects with `source="youtube"`
    - Maintain backward compatibility with the existing `/music/search` endpoint
    - _Requirements: 5.5, 5.3_

- [x] 2. Implement Language Processor
  - [x] 2.1 Create Language Processor module
    - Create `friday/modules/music_language.py` with the `LanguageProcessor` class
    - Implement `detect_script()` using Unicode character block detection
    - Implement `has_devotional_intent()` with keyword matching (bhajan, kirtan, hymn, naat, shabad, stotram, paadal, keerthanai, azan, psalm, gospel) — case-insensitive, whole-word match
    - Implement `build_search_context()` producing a `SearchContext` with script info, devotional flags, and the original query passed through unchanged
    - Add `DEVOTIONAL_KEYWORDS` set and `DEVOTIONAL_TRADITIONS` mapping
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 3.1, 3.4_

  - [x] 2.2 Write property test for query pass-through preservation
    - **Property 3: Query Pass-Through Preservation**
    - Test that for any Unicode string input, `build_search_context().normalized_query` is byte-for-byte identical to the original input (no transliteration)
    - Use Hypothesis `text()` strategy with various Unicode alphabets
    - **Validates: Requirements 2.2, 2.3, 2.6**

  - [x] 2.3 Write property test for query length validation
    - **Property 4: Query Length Validation**
    - Test that queries ≤ 200 characters are accepted and queries > 200 characters are rejected with a validation error
    - Use Hypothesis `text()` strategy with `min_size` and `max_size` controls
    - **Validates: Requirements 2.1**

- [x] 3. Implement Catalog Cache and Fuzzy Matcher
  - [x] 3.1 Create Catalog Cache module
    - Create `friday/modules/music_catalog.py` with `CatalogCache` class
    - Implement LRU-style cache with configurable `max_entries=10000` and `ttl=3600`
    - Implement `add_entries()` to index track titles and artists
    - Implement `get_candidates()` for prefix/substring matching against cached entries
    - _Requirements: 4.1, 4.4_

  - [x] 3.2 Create Fuzzy Matcher module
    - Create `friday/modules/music_fuzzy.py` with `FuzzyMatcher` class
    - Add `rapidfuzz` to `requirements.txt`
    - Implement `find_correction()` using Levenshtein distance ≤ 2 against catalog entries
    - Implement `fuzzy_search()` returning up to 10 partial matches ranked by similarity score
    - Implement `normalize_romanized()` with vowel-length equivalences ("ee"↔"i", "oo"↔"u", "th"↔"t", "dh"↔"d") and word-boundary collapsing
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 3.3 Write property test for fuzzy correction within edit distance
    - **Property 7: Fuzzy Correction Within Edit Distance**
    - Test that for any catalog entry, applying ≤ 2 single-character edits to it always results in `find_correction()` returning the original entry
    - Use Hypothesis to generate random strings and apply random edit operations
    - **Validates: Requirements 4.1**

  - [x] 3.4 Write property test for romanization normalization equivalence
    - **Property 5: Romanization Normalization Equivalence**
    - Test that strings differing only by "ee"↔"i", "oo"↔"u", or word-boundary variations produce identical `normalize_romanized()` output
    - **Validates: Requirements 2.5, 4.5**

  - [x] 3.5 Write property test for exact matches rank above fuzzy matches
    - **Property 8: Exact Matches Rank Above Fuzzy Matches**
    - Test that in any mixed result set, all results with `match_score == 1.0` appear before results with `match_score < 1.0` after sorting
    - **Validates: Requirements 4.3**

  - [x] 3.6 Write property test for partial match constraints
    - **Property 9: Partial Match Constraints**
    - Test that `fuzzy_search()` returns at most 10 partial matches, sorted by descending match length
    - **Validates: Requirements 4.4**

- [x] 4. Checkpoint - Core components verification
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement Music Source Adapters and Aggregator
  - [x] 5.1 Create JioSaavn adapter
    - Create `friday/modules/music_jiosaavn_adapter.py` implementing `MusicSourceAdapter`
    - Implement search using JioSaavn's public API
    - Return `TrackResult` objects with `source="jiosaavn"` and proper metadata mapping
    - _Requirements: 5.1, 5.5, 3.2_

  - [x] 5.2 Create Gaana adapter
    - Create `friday/modules/music_gaana_adapter.py` implementing `MusicSourceAdapter`
    - Implement search using Gaana's API
    - Return `TrackResult` objects with `source="gaana"` and proper metadata mapping
    - _Requirements: 5.1, 5.5, 3.2_

  - [x] 5.3 Create Music Aggregator module
    - Create `friday/modules/music_aggregator.py` with `MusicAggregator` class
    - Implement `search()` with concurrent fan-out to all adapters using `concurrent.futures.ThreadPoolExecutor` with 5s timeout per source
    - Implement deduplication logic (case-insensitive title + artist matching)
    - Implement result merging and ranking with `match_score`-based ordering (exact matches first)
    - Apply devotional ranking boost when `SearchContext.is_devotional` is True (≥70% devotional results in top 10)
    - Implement `quick_search()` for autocomplete (shorter timeout, max 8 results)
    - Handle partial failures gracefully — return results from available sources
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6, 3.1, 3.3, 6.1_

  - [x] 5.4 Write property test for aggregation deduplication and bounds
    - **Property 10: Aggregation Deduplication and Bounds**
    - Test that merged output has no duplicates (case-insensitive title+artist), at most 20 results, and every result has a non-empty `source` field
    - Use Hypothesis to generate lists of `TrackResult` with potential duplicates
    - **Validates: Requirements 5.2, 5.4**

  - [x] 5.5 Write property test for devotional ranking guarantee
    - **Property 6: Devotional Ranking Guarantee**
    - Test that when a devotional query has sufficient devotional tracks, ≥70% of the first 10 results have `is_devotional == True` and all devotional results have non-null `tradition`
    - **Validates: Requirements 3.1, 3.3, 3.4**

- [x] 6. Implement Autocomplete Service
  - [x] 6.1 Create Autocomplete Service module
    - Create `friday/modules/music_autocomplete.py` with `AutocompleteService` class
    - Implement `suggest()` with server-side caching (TTL 300s)
    - Enforce minimum query length of 2 characters (return empty list for shorter)
    - Limit output to max 8 suggestions with title truncated to 60 chars and artist to 40 chars
    - Wire to `MusicAggregator.quick_search()` for live results
    - _Requirements: 1.1, 1.2, 1.3, 1.6, 1.7_

  - [x] 6.2 Write property test for input length threshold
    - **Property 1: Input Length Threshold Controls Suggestion Visibility**
    - Test that queries with length < 2 always return empty list, and queries with length ≥ 2 proceed to return suggestions
    - **Validates: Requirements 1.1, 1.5**

  - [x] 6.3 Write property test for suggestion output invariants
    - **Property 2: Suggestion Output Invariants**
    - Test that output never exceeds 8 suggestions, titles are ≤ 60 chars, and artist names are ≤ 40 chars
    - Use Hypothesis to generate arbitrary-length suggestion lists with long strings
    - **Validates: Requirements 1.3**

- [x] 7. Checkpoint - Backend components complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Wire API endpoints and integrate Search Engine
  - [x] 8.1 Create Search Engine orchestrator
    - Create `friday/modules/music_search_engine.py` with `SearchEngine` class
    - Wire together `LanguageProcessor`, `FuzzyMatcher`, `MusicAggregator`, and `AutocompleteService`
    - Implement query validation (reject > 200 chars, reject empty)
    - Implement search flow: validate → build context → aggregate → apply fuzzy correction → return `AggregatedResult`
    - _Requirements: 2.1, 4.1, 4.3, 6.1_

  - [x] 8.2 Add API endpoints to Flask app
    - Add `GET /music/autocomplete?q=...` endpoint in `app.py` or a new route module
    - Enhance existing `GET /music/search?q=...` endpoint to use the new `SearchEngine`
    - Return JSON with `results`, `query`, `correction`, and `devotional_context` fields
    - Implement proper HTTP error codes (400 for invalid input, 503 for all sources failed)
    - Ensure backward compatibility with existing response format
    - _Requirements: 1.1, 1.7, 5.6, 6.1, 6.3_

  - [x] 8.3 Write unit tests for API endpoints
    - Test `/music/autocomplete` with mocked aggregator
    - Test `/music/search` with mocked adapters for success, partial failure, and all-failure cases
    - Test query validation (empty, too long, valid)
    - Test backward compatibility of response format
    - _Requirements: 1.7, 2.1, 5.3, 5.6_

- [x] 9. Implement frontend enhancements
  - [x] 9.1 Add autocomplete UI with debounce and suggestion panel
    - Add Suggestion Panel HTML (`.mp-suggestions` dropdown below search input) in `public/index.html`
    - Implement 250ms debounce handler on the search input
    - Implement `AbortController` for request cancellation on new keystrokes
    - Render suggestions with song title, artist, and thumbnail
    - Implement keyboard navigation (arrow keys, Enter to select, Escape to dismiss)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 6.2, 6.3_

  - [x] 9.2 Add correction banner and source badges
    - Add Correction Banner HTML (`.mp-correction`) above results
    - Implement "Did you mean: [corrected query]?" click handler to trigger new search
    - Dismiss correction banner on new query or input clear
    - Add source badge labels to each result item showing the Music_Source
    - _Requirements: 4.2, 4.6, 5.4_

  - [x] 9.3 Implement client-side LRU cache and offline handling
    - Implement LRU cache (50 entries, 5-min TTL) for autocomplete responses
    - Implement network offline detection with retry logic (3 retries at 5s intervals)
    - Display persistent error message with manual retry button after retries exhausted
    - Add loading indicator inside search input (spinner in right padding)
    - _Requirements: 6.4, 6.5, 6.2_

  - [x] 9.4 Write property test for client cache invariants
    - **Property 11: Client Cache Invariants**
    - Test that cache never exceeds 50 entries and entries older than 5 minutes return cache misses
    - Implement cache logic in Python for testing (mirrors frontend JS logic)
    - **Validates: Requirements 6.4**

- [x] 10. Final checkpoint - Full integration verification
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The project uses Python (Flask) for the backend and vanilla JS in `public/index.html` for the frontend
- `hypothesis` is already installed (`.hypothesis/` directory exists)
- `rapidfuzz` must be added to `requirements.txt` in task 3.2
- The existing `friday/modules/music.py` contains the current YouTube-only search implementation

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1", "3.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.2"] },
    { "id": 3, "tasks": ["3.3", "3.4", "3.5", "3.6", "5.1", "5.2"] },
    { "id": 4, "tasks": ["5.3"] },
    { "id": 5, "tasks": ["5.4", "5.5", "6.1"] },
    { "id": 6, "tasks": ["6.2", "6.3"] },
    { "id": 7, "tasks": ["8.1"] },
    { "id": 8, "tasks": ["8.2"] },
    { "id": 9, "tasks": ["8.3", "9.1"] },
    { "id": 10, "tasks": ["9.2", "9.3"] },
    { "id": 11, "tasks": ["9.4"] }
  ]
}
```
