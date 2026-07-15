# Design Document: Music Search Optimization

## Overview

This design describes how the JARVIS AI assistant's music search will be enhanced from a single-source, keyword-only YouTube search into a multi-source, multi-language, intelligent search system with autocomplete, fuzzy matching, and devotional music awareness.

The current architecture is simple: a Python Flask backend exposes `GET /music/search?q=...` which calls `search_tracks()` in `jarvis/modules/music.py`, querying YouTube Data API v3. The frontend has an inline search input (`.mp-search-input`) that fires on Enter and renders results in `.mp-results`. This design adds four new backend components (Autocomplete Service, Fuzzy Matcher, Music Aggregator, Language Processor) and a richer frontend search experience, while keeping the existing YouTube integration intact as one of multiple sources.

### Key Design Decisions

1. **Server-side autocomplete over client-side** — The suggestion corpus lives across multiple APIs so the backend must orchestrate. A lightweight `/music/autocomplete?q=...` endpoint with aggressive caching keeps latency low.
2. **Edit-distance fuzzy matching via RapidFuzz** — The [RapidFuzz](https://github.com/maxbachmann/RapidFuzz) library provides C-optimized Levenshtein distance and partial ratio matching, ideal for typo correction against a local catalog cache.
3. **Adapter pattern for music sources** — Each music source (YouTube, JioSaavn, Gaana) implements a common `MusicSourceAdapter` interface. The aggregator fans out queries concurrently using `asyncio`/`concurrent.futures` and merges results.
4. **No transliteration — pass-through Unicode** — Per requirements, queries in any script are forwarded as-is to all sources. The search engine does not transform scripts, preserving fidelity.
5. **Client-side LRU cache for autocomplete** — A 50-entry, 5-minute TTL cache in the frontend avoids redundant autocomplete API calls for repeated keystrokes.

## Architecture

```mermaid
graph TD
    subgraph Frontend
        SI[Search Input] --> DB[Debounce 250ms]
        DB --> AC_REQ[GET /music/autocomplete]
        SI --> SEARCH_REQ[GET /music/search]
        AC_REQ --> SP[Suggestion Panel]
        SEARCH_REQ --> RL[Results List]
        CB[Correction Banner] --> SEARCH_REQ
    end

    subgraph Backend
        AC_EP[/music/autocomplete endpoint] --> ACS[Autocomplete Service]
        SE_EP[/music/search endpoint] --> SE[Search Engine]
        SE --> LP[Language Processor]
        SE --> FM[Fuzzy Matcher]
        SE --> MA[Music Aggregator]
        ACS --> MA
        MA --> YT[YouTube Adapter]
        MA --> JS[JioSaavn Adapter]
        MA --> GA[Gaana Adapter]
        FM --> CC[Catalog Cache]
    end

    AC_REQ --> AC_EP
    SEARCH_REQ --> SE_EP
```

### Request Flow

1. **Autocomplete**: User types → debounce 250ms → `GET /music/autocomplete?q=ab` → Autocomplete Service checks local cache → fans out to Music Aggregator (lightweight, max 8 results) → returns suggestions.
2. **Full Search**: User presses Enter or selects suggestion → `GET /music/search?q=full+query` → Search Engine processes via Language Processor → Music Aggregator queries all sources concurrently (5s timeout each) → Fuzzy Matcher checks for corrections → merged results + optional correction returned.
3. **Cancellation**: If a new request arrives before the previous completes, the frontend uses `AbortController` to cancel the in-flight fetch. The backend handles this gracefully (no wasted compute beyond what's already in-flight).

## Components and Interfaces

### 1. Autocomplete Service (`jarvis/modules/music_autocomplete.py`)

**Responsibility**: Provide fast, lightweight suggestions from cached data and live API results.

```python
class AutocompleteService:
    def __init__(self, aggregator: MusicAggregator, cache_ttl: int = 300):
        """cache_ttl in seconds (default 5 min server-side)."""
        ...

    def suggest(self, query: str, max_results: int = 8) -> list[Suggestion]:
        """Return up to max_results suggestions for the partial query."""
        ...
```

**Suggestion model**:
```python
@dataclass
class Suggestion:
    title: str        # Truncated to 60 chars
    artist: str       # Truncated to 40 chars
    thumbnail_url: str
    video_id: str     # Or source-specific ID
    source: str       # "youtube", "jiosaavn", "gaana"
```

### 2. Fuzzy Matcher (`jarvis/modules/music_fuzzy.py`)

**Responsibility**: Detect typos, suggest corrections, and provide fuzzy-matched results.

```python
class FuzzyMatcher:
    def __init__(self, catalog_cache: CatalogCache):
        ...

    def find_correction(self, query: str) -> str | None:
        """Return corrected query if edit distance <= 2, else None."""
        ...

    def fuzzy_search(self, query: str, max_results: int = 10) -> list[FuzzyMatch]:
        """Return partial/fuzzy matches ranked by similarity score."""
        ...

    def normalize_romanized(self, query: str) -> str:
        """Normalize common vowel-length and word-boundary variations."""
        ...
```

**Romanization equivalence rules** (configurable):
- `"ee"` ↔ `"i"`, `"oo"` ↔ `"u"`, `"th"` ↔ `"t"`, `"dh"` ↔ `"d"`
- Word boundary collapsing: `"Tum hi"` → `"Tumhi"`

### 3. Music Aggregator (`jarvis/modules/music_aggregator.py`)

**Responsibility**: Query multiple sources concurrently and merge/deduplicate results.

```python
class MusicAggregator:
    def __init__(self, adapters: list[MusicSourceAdapter], timeout: float = 5.0):
        ...

    def search(self, query: str, max_results: int = 20) -> AggregatedResult:
        """Fan out to all adapters, merge, deduplicate, rank."""
        ...

    def quick_search(self, query: str, max_results: int = 8) -> list[TrackResult]:
        """Lightweight search for autocomplete (shorter timeout, fewer results)."""
        ...
```

**MusicSourceAdapter interface**:
```python
class MusicSourceAdapter(Protocol):
    @property
    def source_name(self) -> str: ...

    def search(self, query: str, max_results: int) -> list[TrackResult]: ...

    def is_available(self) -> bool: ...
```

### 4. Language Processor (`jarvis/modules/music_language.py`)

**Responsibility**: Detect script, apply devotional keyword boosting, normalize queries.

```python
class LanguageProcessor:
    DEVOTIONAL_KEYWORDS: set[str]  # {"bhajan", "kirtan", "hymn", ...}
    DEVOTIONAL_TRADITIONS: dict[str, str]  # keyword -> tradition label

    def detect_script(self, text: str) -> str:
        """Detect primary Unicode script block of the text."""
        ...

    def has_devotional_intent(self, query: str) -> tuple[bool, str | None]:
        """Check for devotional keywords; return (is_devotional, tradition_label)."""
        ...

    def build_search_context(self, query: str) -> SearchContext:
        """Produce a SearchContext with script info, devotional flags, normalized query."""
        ...
```

### 5. Catalog Cache (`jarvis/modules/music_catalog.py`)

**Responsibility**: Maintain a local index of recently seen track titles/artists for fuzzy matching.

```python
class CatalogCache:
    def __init__(self, max_entries: int = 10000, ttl: int = 3600):
        ...

    def add_entries(self, tracks: list[TrackResult]) -> None:
        """Index track titles and artists for fuzzy lookup."""
        ...

    def get_candidates(self, prefix: str) -> list[str]:
        """Return candidate strings matching prefix or substring."""
        ...
```

### 6. Frontend Changes (`public/index.html`)

New UI elements:
- **Suggestion Panel** (`.mp-suggestions`): Absolute-positioned dropdown below search input showing autocomplete results.
- **Correction Banner** (`.mp-correction`): "Did you mean...?" banner above results.
- **Loading indicator**: Spinner inside the search input's right padding.
- **Source badge**: Small label on each result item showing the source.

Frontend logic additions:
- Debounce handler (250ms) triggering `/music/autocomplete`
- `AbortController` for request cancellation
- LRU cache (50 entries, 5-min TTL) for autocomplete responses
- Keyboard navigation (arrow keys) in suggestion panel

### 7. New API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/music/autocomplete` | GET | `?q=...` → `{suggestions: Suggestion[]}` |
| `/music/search` | GET | Enhanced: `?q=...` → `{results: TrackResult[], query, correction?: string, devotional_context?: string}` |

The existing `/music/search` endpoint is enhanced (backward-compatible — still returns `results` and `query`).

## Data Models

### TrackResult

```python
@dataclass
class TrackResult:
    id: str                   # Source-specific track ID
    title: str                # Track title in original language
    artist: str               # Artist name in original language
    thumbnail_url: str        # Album art / thumbnail
    source: str               # "youtube" | "jiosaavn" | "gaana"
    source_url: str           # Playback or redirect URL
    duration_seconds: int | None  # Track duration if available
    is_devotional: bool       # Whether categorized as devotional
    tradition: str | None     # e.g., "Hindu Bhajan", "Sikh Shabad"
    match_score: float        # Relevance score (0.0-1.0) for ranking
```

### AggregatedResult

```python
@dataclass
class AggregatedResult:
    results: list[TrackResult]       # Merged, deduplicated, ranked (max 20)
    correction: str | None           # "Did you mean...?" suggestion
    devotional_context: str | None   # Devotional tradition if detected
    sources_queried: list[str]       # Which sources were actually queried
    sources_failed: list[str]        # Which sources timed out or errored
```

### SearchContext

```python
@dataclass
class SearchContext:
    original_query: str
    normalized_query: str        # Romanization-normalized form
    detected_scripts: list[str]  # e.g., ["Latin", "Devanagari"]
    is_devotional: bool
    devotional_tradition: str | None
    devotional_keywords_found: list[str]
```

### Frontend Cache Entry

```typescript
interface CacheEntry {
    query: string;
    suggestions: Suggestion[];
    timestamp: number;  // Date.now() when cached
}
```

### Deduplication Logic

Two tracks are considered duplicates when:
- `title.lower().strip() == other.title.lower().strip()` AND
- `artist.lower().strip() == other.artist.lower().strip()`

When duplicates are found, the track from the higher-priority source is kept (priority: YouTube > JioSaavn > Gaana by default, configurable).



## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Input Length Threshold Controls Suggestion Visibility

*For any* input string, the autocomplete service SHALL return suggestions only when the string length is ≥ 2 characters, and SHALL return an empty list (signaling "hide") for any string with length < 2.

**Validates: Requirements 1.1, 1.5**

### Property 2: Suggestion Output Invariants

*For any* list of raw autocomplete results of arbitrary size, the formatted output SHALL contain at most 8 suggestions, with each suggestion's title truncated to at most 60 characters and each artist name truncated to at most 40 characters.

**Validates: Requirements 1.3**

### Property 3: Query Pass-Through Preservation

*For any* query string composed of characters from any Unicode script (Latin, Devanagari, Tamil, Telugu, Kannada, Malayalam, Bengali, Gujarati, Gurmukhi, or any other script), the Language Processor SHALL output the query unchanged — the string passed to each Music Source adapter must be byte-for-byte identical to the original input.

**Validates: Requirements 2.2, 2.3, 2.6**

### Property 4: Query Length Validation

*For any* string of length ≤ 200 characters in any supported script, the Search Engine SHALL accept the query without error. *For any* string of length > 200 characters, the Search Engine SHALL reject it with a validation error.

**Validates: Requirements 2.1**

### Property 5: Romanization Normalization Equivalence

*For any* pair of romanized Indian-language strings that differ only by common vowel-length variations ("ee"↔"i", "oo"↔"u") or word-boundary variations ("Tum hi"↔"Tumhi"), the `normalize_romanized` function SHALL produce identical canonical output strings.

**Validates: Requirements 2.5, 4.5**

### Property 6: Devotional Ranking Guarantee

*For any* query containing a devotional keyword (in any supported script or romanized form) and a mixed result set containing both devotional and non-devotional tracks (with sufficient devotional tracks available), the ranking function SHALL place devotional results such that at least 70% of the first 10 results have `is_devotional == True`, and every devotional result SHALL have a non-null `tradition` field.

**Validates: Requirements 3.1, 3.3, 3.4**

### Property 7: Fuzzy Correction Within Edit Distance

*For any* catalog entry string and any modified version of that string produced by applying at most 2 single-character edits (insertions, deletions, or substitutions), the `find_correction` function SHALL return the original catalog entry as the suggested correction.

**Validates: Requirements 4.1**

### Property 8: Exact Matches Rank Above Fuzzy Matches

*For any* mixed result set containing both exact-match results (match_score == 1.0) and fuzzy-match results (match_score < 1.0), after sorting, all exact matches SHALL appear before all fuzzy matches in the output list.

**Validates: Requirements 4.3**

### Property 9: Partial Match Constraints

*For any* query and catalog, when the query shares a contiguous substring of ≥ 3 characters with catalog entries, the `fuzzy_search` function SHALL return at most 10 partial matches, and those matches SHALL be sorted in descending order by match length.

**Validates: Requirements 4.4**

### Property 10: Aggregation Deduplication and Bounds

*For any* collection of result lists from multiple music sources (with potential duplicates defined by case-insensitive title + artist equality), the aggregator's merged output SHALL: (a) contain no duplicate entries, (b) contain at most 20 results, and (c) include a non-empty `source` field on every result.

**Validates: Requirements 5.2, 5.4**

### Property 11: Client Cache Invariants

*For any* sequence of cache put operations, the client-side autocomplete cache SHALL never exceed 50 entries, and *for any* entry older than 5 minutes, a cache lookup SHALL return a cache miss (forcing a fresh API call).

**Validates: Requirements 6.4**

## Error Handling

### Backend Errors

| Scenario | Behavior |
|----------|----------|
| Single Music Source timeout (> 5s) | Aggregator returns results from remaining sources; failed source logged with `loguru` warning |
| All Music Sources fail | Return HTTP 503 with `{"error": "All music sources are temporarily unavailable. Please try again."}` |
| YouTube API quota exceeded | Log warning, exclude YouTube from aggregation, continue with other sources |
| Invalid query (> 200 chars) | Return HTTP 400 with `{"error": "Query must be 200 characters or fewer"}` |
| Empty query | Return HTTP 400 with `{"error": "Query parameter 'q' is required"}` (existing behavior preserved) |
| Autocomplete timeout (> 2s) | Return empty suggestions with `{"suggestions": [], "error": "Suggestions temporarily unavailable"}` |
| Fuzzy Matcher catalog empty | Skip correction, return results without "Did you mean" |

### Frontend Errors

| Scenario | Behavior |
|----------|----------|
| Autocomplete API timeout | Hide loading spinner, show subtle "Suggestions unavailable" tooltip |
| Search API timeout | Remove loading indicator, display "Search timed out. Try again." |
| Network offline | Display offline banner, retry 3× at 5s intervals when connectivity returns |
| All retries exhausted | Display persistent "Unable to connect. Please check your network." with manual retry button |
| Request cancelled (new query) | Silently abort previous request via `AbortController`, no error shown |

### Graceful Degradation

The system degrades progressively:
1. **Full functionality**: All sources + fuzzy matching + autocomplete
2. **Partial sources**: 1-2 sources down → results from remaining sources (with a note about reduced coverage)
3. **No fuzzy matching**: Catalog cache empty → standard search without corrections
4. **Autocomplete unavailable**: Backend overloaded → user can still use full search on Enter
5. **Fully offline**: Cached autocomplete suggestions for recent queries still available client-side

## Testing Strategy

### Property-Based Tests (Hypothesis — Python)

The project already uses [Hypothesis](https://hypothesis.readthedocs.io/) (evidenced by `.hypothesis/` directory in the workspace). Each correctness property above will be implemented as a Hypothesis property-based test with a minimum of 100 iterations.

**Library**: `hypothesis` (already installed)
**Configuration**: `@settings(max_examples=100)` minimum per test
**Tag format**: `# Feature: music-search-optimization, Property {N}: {title}`

Properties to implement:
1. Input length threshold (Property 1)
2. Suggestion output invariants (Property 2)
3. Query pass-through preservation (Property 3)
4. Query length validation (Property 4)
5. Romanization normalization equivalence (Property 5)
6. Devotional ranking guarantee (Property 6)
7. Fuzzy correction within edit distance (Property 7)
8. Exact matches rank above fuzzy (Property 8)
9. Partial match constraints (Property 9)
10. Aggregation deduplication and bounds (Property 10)
11. Client cache invariants (Property 11)

### Unit Tests (pytest)

- Autocomplete debounce behavior (mock timers)
- Specific devotional keyword detection (known keywords in multiple scripts)
- "Did you mean" click → new search triggers
- All-sources-fail error response
- Single-source timeout with remaining sources returning results
- Empty query rejection
- Correction banner dismissal on new query

### Integration Tests

- End-to-end `/music/search` with mocked adapters
- End-to-end `/music/autocomplete` with mocked adapters
- YouTube adapter with real API (gated by API key availability)
- Result metadata preserved in original language across adapters
- Performance: aggregated results returned within 3s under normal network

### Frontend Tests

- Debounce fires exactly once per 250ms idle period
- AbortController cancels in-flight requests on new input
- Suggestion panel keyboard navigation (arrow keys, Enter, Escape)
- Correction banner renders and dismisses correctly
- LRU cache eviction at 50 entries
- Cache expiry at 5 minutes
- Offline detection and retry logic
