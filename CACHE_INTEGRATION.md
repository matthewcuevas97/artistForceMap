# Cache Integration Guide

## Quick Start

### 1. Update User Top Artists After Authentication

```python
from backend.user_data import set_user_top_artists
from spotify.fetch import get_top_artists
import spotipy

# In your auth callback
@app.route("/callback")
def callback():
    # ... auth setup ...

    sp = spotipy.Spotify(auth=token)
    artists = get_top_artists(sp)  # Top 50 with scores

    # Cache the artists for this user
    set_user_top_artists(
        user_id=user_id,
        spotify_artists=artists
    )
```

### 2. Get User's Top Artists (With Last.fm Override)

```python
from backend.user_data import get_user_top_artists

# In your API route
@app.route("/api/user/artists")
def get_artists():
    user_id = session.get("user_id")

    # Returns merged top 50 (Last.fm overrides Spotify if both present)
    artists = get_user_top_artists(user_id, limit=25)

    return jsonify({"artists": artists})
```

### 3. Handle Last.fm Login

```python
from backend.user_data import set_user_top_artists
from lastfm.fetch import get_top_artists as lastfm_top

@app.route("/api/lastfm/login", methods=["POST"])
def lastfm_login():
    username = request.json.get("username")

    # Fetch and cache Last.fm artists
    artists = lastfm_top(username, limit=100)
    set_user_top_artists(
        user_id=username,
        lastfm_artists=artists
    )

    return jsonify({"ok": True})
```

### 4. Cache Artist Metadata

```python
from backend.cache import get_or_set_cached_artist
from lastfm.fetch import get_artist_info

@app.route("/api/artist/<name>")
def get_artist(name):
    # First check cache, then fetch if not found
    artist = get_or_set_cached_artist(
        artist_name=name.lower(),
        fetch_fn=get_artist_info,
        artist_name=name
    )

    if not artist:
        return jsonify({"error": "Not found"}), 404

    return jsonify(artist)
```

## Integration with Universal Map App

In `app_universal.py`, after map initialization:

```python
from backend.user_data import set_user_top_artists
from spotify.fetch import get_top_artists
from lastfm.fetch import get_top_artists as lastfm_top

@app.route("/api/map/init", methods=["POST"])
def map_init():
    user_id = session.get("spotify_id") or session.get("lastfm_user")

    spotify_token = get_valid_spotify_token()
    lastfm_user = session.get("lastfm_user")

    # Fetch from sources
    spotify_artists = None
    lastfm_artists = None

    if spotify_token:
        sp = spotipy.Spotify(auth=spotify_token)
        spotify_artists = get_top_artists(sp)

    if lastfm_user:
        lastfm_artists = lastfm_top(lastfm_user)

    # Cache both (Last.fm takes precedence if both present)
    set_user_top_artists(
        user_id=user_id,
        spotify_artists=spotify_artists,
        lastfm_artists=lastfm_artists
    )

    # Use merged artists for graph generation
    user_db = load_user_db(user_id)  # Includes merged top artists
    # ... generate graph from user_db["top_artists"] ...
```

## Cache Checking

Check if user has cached data:

```python
from backend.user_data import load_user_db

def has_cached_user_data(user_id):
    db = load_user_db(user_id)
    return len(db.get("top_artists", [])) > 0

# In your app
if has_cached_user_data(user_id):
    # Use cached data
    artists = get_user_top_artists(user_id)
else:
    # Need to fetch from source
    # Trigger authentication/fetching
```

## Viewing Cache Stats

```python
from backend.cache import get_cache_stats

@app.route("/api/debug/cache-stats")
def cache_stats():
    if not is_admin():  # Add your admin check
        return jsonify({"error": "Unauthorized"}), 403

    stats = get_cache_stats()
    return jsonify(stats)
```

Output:
```json
{
  "total_artists": 1500,
  "expired": 10,
  "valid": 1490,
  "cache_file": "/path/to/data/cache/artists.json"
}
```

## Common Patterns

### Pattern 1: Fetch with Cache Fallback
```python
# Good: Uses cache, falls back to API if needed
from backend.cache import get_or_set_cached_artist

artist = get_or_set_cached_artist(
    artist_name="the beatles",
    fetch_fn=lastfm.get_artist_info,
    artist_name="The Beatles"
)
```

### Pattern 2: Update User After Source Change
```python
# User switches from Spotify to Last.fm
def switch_auth_source(user_id, new_source):
    if new_source == "lastfm":
        artists = lastfm_top(session.get("lastfm_user"))
        set_user_top_artists(user_id, lastfm_artists=artists)
    else:
        artists = get_top_artists(sp)
        set_user_top_artists(user_id, spotify_artists=artists)
```

### Pattern 3: Display Source for Each Artist
```python
# Frontend can show which source the artist came from
artists = get_user_top_artists(user_id)
for artist in artists:
    print(f"{artist['name']} (from {artist['source']})")
```

### Pattern 4: Switch Between Sources
```python
# If user has both sources, Last.fm takes precedence
db = load_user_db(user_id)
has_spotify = len(db.get("top_artists_spotify", [])) > 0
has_lastfm = len(db.get("top_artists_lastfm", [])) > 0

if has_lastfm:
    # Use Last.fm merged results
    top = db["top_artists"]  # Already merged with Last.fm override
else:
    # Use Spotify only
    top = db["top_artists"]  # Still merged, just no Last.fm
```

## Debugging

### Clear Cache (Development Only)
```python
from backend.cache import clear_artist_cache

# Only in development/testing!
if app.debug:
    @app.route("/api/debug/clear-cache")
    def clear_cache():
        clear_artist_cache()
        return jsonify({"ok": True})
```

### View Raw Cache Files
```bash
# Artist cache
cat data/cache/artists.json | python -m json.tool | head -50

# User cache
cat data/cache/{user_id}_cache.json | python -m json.tool
```

### Run Tests
```bash
python backend/test_cache.py
```

## Error Handling

```python
from backend.cache import get_cached_artist

try:
    artist = get_cached_artist("the beatles")
    if not artist:
        print("Not in cache, fetch from API")
        # Fetch logic here
except Exception as e:
    print(f"Cache error: {e}")
    # Gracefully fall back to API
```

## Migration from Old User DB

If migrating from old format, run once:

```python
from backend.user_data import load_user_db, save_user_db, set_user_top_artists

# For each user, copy old data to new cache format
old_db = load_old_user_db(user_id)

if old_db.get("top_artists"):
    set_user_top_artists(
        user_id=user_id,
        spotify_artists=old_db["top_artists"]
    )
```

## Next Steps

- Implement Redis backend for distributed caching
- Add cache warming on app startup
- Monitor cache hit rates in logs
- Implement automatic cleanup of expired entries
