# Caching System Architecture

## Overview

The caching system consists of two tiers:

1. **Global Artist Cache** - Shared across all users, 90-day TTL
2. **User Cache** - Per-user, contains merged top artists and metadata

No sensitive data (auth tokens, passwords, API keys) is stored.

## Global Artist Cache

**Location**: `data/cache/artists.json`

**TTL**: 90 days (7,776,000 seconds)

**Data Stored**:
```json
{
  "artist_name_lowercase": {
    "name": "Artist Name",
    "genres": ["rock", "pop"],
    "listeners": 1000000,
    "tags": ["alternative", "indie"],
    "_created_at": 1234567890,
    "_updated_at": "2025-03-16T12:00:00"
  }
}
```

**Key Features**:
- Automatic expiration: entries older than 90 days are removed on access
- Metadata (`_created_at`, `_updated_at`) not exposed to callers
- Normalized by lowercase artist name

**Usage**:
```python
from backend.cache import get_cached_artist, set_cached_artist

# Retrieve from cache
artist = get_cached_artist("the beatles")

# Store in cache
set_cached_artist("the beatles", {
    "name": "The Beatles",
    "listeners": 5000000,
    "genres": ["rock", "pop"]
})

# Get with fallback to fetch function
artist = get_or_set_cached_artist(
    "the beatles",
    fetch_fn=lastfm.get_artist_info,
    artist_name="The Beatles"
)
```

## User Cache

**Location**: `data/cache/{user_id}_cache.json`

**Data Stored**:
```json
{
  "user_id": "user123",
  "auth_provider": "spotify",
  "top_artists_spotify": [
    {"name": "Artist A", "spotify_id": "sp_123", "score": 1.0}
  ],
  "top_artists_lastfm": [
    {"name": "Artist B", "score": 0.95}
  ],
  "top_artists_merged": [
    {
      "name": "Artist A",
      "score": 1.0,
      "source": "lastfm",
      "spotify_id": "sp_123"
    }
  ],
  "seed_artists": ["Artist A", "Artist B"],
  "map_id": "user123_map",
  "_last_updated": "2025-03-16T12:00:00"
}
```

**Key Fields**:
- `top_artists_spotify`: Unmodified Spotify top 50
- `top_artists_lastfm`: Unmodified Last.fm top 50
- `top_artists_merged`: Merged top 50 with Last.fm override
- `auth_provider`: Non-sensitive identifier ("spotify" or "lastfm")
- No tokens, passwords, or sensitive credentials

**Usage**:
```python
from backend.cache import load_user_cache, update_user_top_artists
from backend.user_data import set_user_top_artists, get_user_top_artists

# Update top artists
set_user_top_artists(
    user_id="user123",
    spotify_artists=[...],
    lastfm_artists=[...]
)

# Retrieve merged top artists
artists = get_user_top_artists("user123", limit=50)
```

## Top Artists Merging Logic

When a user has data from both Spotify and Last.fm:

1. **Both sources available**: Last.fm score takes precedence, but Spotify ID is preserved
2. **Overlapping artists**: Ranked by Last.fm score if available, else Spotify
3. **Non-overlapping artists**: Included from both sources
4. **Source tracking**: Each artist records whether it came from "spotify" or "lastfm"
5. **Top 50**: Final list limited to top 50 by score

**Example**:
```python
from backend.cache import merge_top_artists

spotify = [
    {"name": "Beatles", "spotify_id": "sp_1", "score": 1.0},
    {"name": "Floyd", "spotify_id": "sp_2", "score": 0.8}
]

lastfm = [
    {"name": "Beatles", "score": 0.95},
    {"name": "Bowie", "score": 0.85}
]

merged = merge_top_artists(spotify, lastfm)
# Result:
# [
#   {"name": "Beatles", "score": 0.95, "source": "lastfm", "spotify_id": "sp_1"},
#   {"name": "Bowie", "score": 0.85, "source": "lastfm"},
#   {"name": "Floyd", "score": 0.8, "source": "spotify", "spotify_id": "sp_2"}
# ]
```

## API Integration

### Spotify
```python
from spotify.fetch import get_top_artists
from backend.user_data import set_user_top_artists

sp = spotipy.Spotify(auth=token)
artists = get_top_artists(sp)  # Returns top 50 with scores

set_user_top_artists("user123", spotify_artists=artists)
```

### Last.fm
```python
from lastfm.fetch import get_top_artists as lastfm_top
from backend.user_data import set_user_top_artists

artists = lastfm_top("username", limit=100)  # Returns top 100

set_user_top_artists("user123", lastfm_artists=artists)
```

## Data Parity

Both APIs return top artists with normalized scores:
- **Spotify**: Score = rank position (1st = 1.0, last = 0.0)
- **Last.fm**: Score = rank position with period "6month"

This enables direct comparison and override logic.

## Testing

Run comprehensive cache tests:
```bash
python backend/test_cache.py
```

Tests verify:
- ✓ Artist cache creation and retrieval
- ✓ Metadata isolation (not exposed to callers)
- ✓ Automatic expiration after 90 days
- ✓ Top artists merging logic
- ✓ Last.fm override behavior
- ✓ User cache creation and updates
- ✓ No sensitive data storage
- ✓ Cache statistics

## Cache Maintenance

### View Cache Stats
```python
from backend.cache import get_cache_stats

stats = get_cache_stats()
# {
#   "total_artists": 1500,
#   "expired": 10,
#   "valid": 1490,
#   "cache_file": "/path/to/artists.json"
# }
```

### Clear Cache (Development)
```python
from backend.cache import clear_artist_cache

clear_artist_cache()  # Deletes artists.json
```

## Performance Characteristics

| Operation | Time | Notes |
|-----------|------|-------|
| Cache hit (artist) | O(1) | File I/O, typically <5ms |
| Cache miss | API call | ~100-500ms depending on source |
| Merge top artists | O(n) | n ≈ 100, typically <5ms |
| User cache save | O(1) | Single file write, typically <10ms |

## Security

**What's NOT stored**:
- Spotify access tokens
- Spotify refresh tokens
- Last.fm API keys
- User passwords
- Rate limit tokens
- Session cookies

**What IS stored**:
- Artist names (public data)
- Popularity scores (public data)
- User ID (non-sensitive identifier)
- Auth provider type (non-sensitive)
- Listener counts (public data)

All sensitive data remains in application memory or HTTP session.

## Future Enhancements

- [ ] Redis backend for distributed caching
- [ ] Automatic cache expiration cleanup job
- [ ] Per-artist popularity trend tracking
- [ ] Cache warming on startup
- [ ] LRU eviction if cache grows too large
