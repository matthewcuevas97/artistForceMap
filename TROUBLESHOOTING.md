# Troubleshooting Guide

## Error: "No enriched artists found for user X. Run tag_enrichment first."

### Cause
The ingestion step didn't properly cache the user's top artists.

### Solution

#### Step 1: Check Cache Files
```bash
# List cache files
ls -la data/cache/

# Check user's cache
cat data/cache/{user_id}_cache.json | python -m json.tool | head -30
```

#### Step 2: Verify User Cache Has Artists
```bash
# Look for top_artists_spotify or top_artists_lastfm
# Should see: "top_artists_spotify": [...] or "top_artists_lastfm": [...]
```

#### Step 3: Clear and Retry
```bash
# Clear the user's cache (fresh start)
rm data/cache/{user_id}_cache.json

# Restart the app and try again
python app_universal.py
```

#### Step 4: Check Application Logs
```bash
# Look for error messages during:
# - Spotify/Last.fm authentication
# - Artist fetching
# - Cache saving
```

---

## Error: "Spotify authentication failed"

### Check Spotify Configuration
```bash
# Verify FLASK_SECRET_KEY is set
echo $FLASK_SECRET_KEY

# Verify Spotify credentials in .env
cat .env | grep SPOTIFY
```

### Reset Spotify OAuth State
```python
# In Python shell
import os
os.environ.pop("oauth_state", None)
```

---

## Error: "Last.fm user not found"

### Check Last.fm Username
```bash
# Verify the username is correct
# Visit: https://www.last.fm/user/{username}

# If user exists but error persists, Last.fm API might be down
# Check: https://www.last.fm/api/
```

---

## Cache Not Persisting

### Verify Cache Directory Exists
```bash
# Create if missing
mkdir -p data/cache/
chmod 755 data/cache/
```

### Check Permissions
```bash
# Ensure write permissions
ls -la data/cache/
# Should show: drwxr-xr-x

# If not, fix:
chmod 755 data/cache/
```

### Check Disk Space
```bash
# Verify free space
df -h data/
```

---

## Pipeline Fails During Enrichment

### Check Last.fm API
```bash
# Test Last.fm API directly
curl "https://ws.audioscrobbler.com/2.0/?method=artist.getInfo&artist=The+Beatles&api_key={KEY}&format=json"
```

### Verify LASTFM_API_KEY
```bash
# Check environment variable
echo $LASTFM_API_KEY
```

### Check Rate Limiting
Enrichment uses 0.2s delay between requests. If Last.fm is rate limiting:
- Wait a few minutes
- Try again with fewer artists (modify pipeline)

---

## Cache Growing Too Large

### Check Cache Size
```bash
# Get total cache size
du -sh data/cache/

# See size of artist cache
ls -lh data/cache/artists.json
```

### Clear Old User Caches
```bash
# Remove cache for inactive users (older than 90 days)
find data/cache/ -name "*_cache.json" -mtime +90 -delete

# Or clear all caches
rm data/cache/*.json
```

### Monitor Cache Stats
```python
from backend.cache import get_cache_stats

stats = get_cache_stats()
print(f"Total artists: {stats['total_artists']}")
print(f"Expired: {stats['expired']}")
print(f"Valid: {stats['valid']}")
```

---

## Tests Failing

### Run Integration Test
```bash
python backend/test_pipeline_integration.py
```

### Run Cache Tests
```bash
python backend/test_cache.py
```

### Run with Verbose Output
```bash
python -u backend/test_cache.py 2>&1 | head -100
```

---

## Clearing Everything for Fresh Start

### Complete Reset
```bash
# Remove all user data
rm -rf data/users/*
rm -rf data/cache/*

# Restart app
python app_universal.py
```

### Keep Artist Cache, Clear User Data
```bash
# Keep global artist cache, clear per-user caches
rm data/cache/*_cache.json

# Keep user maps for reference, clear caches only
rm data/cache/*_cache.json
```

---

## Debugging with Logs

### Enable Verbose Logging
```python
# In app_universal.py, add:
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Monitor Cache Hits/Misses
```python
# In your route
from backend.cache import get_cache_stats

stats = get_cache_stats()
print(f"Cache hit rate: {stats['valid'] / stats['total_artists']}")
```

### Check Artist Cache Contents
```bash
# View cached artists
cat data/cache/artists.json | python -m json.tool | head -50
```

---

## Performance Issues

### Slow Enrichment
- Last.fm API can be slow
- Check network latency: `ping ws.audioscrobbler.com`
- Consider caching Last.fm responses

### Slow Graph Rendering
- Check browser console for errors
- Verify D3 is loaded correctly
- Limit nodes (reduce artists from 50 to 25)

---

## Still Having Issues?

### Collect Diagnostic Info
```bash
# Create debug report
echo "=== Environment ===" > debug.txt
echo $FLASK_SECRET_KEY >> debug.txt
echo $SPOTIFY_CLIENT_ID >> debug.txt
echo $LASTFM_API_KEY >> debug.txt

echo "=== Cache Status ===" >> debug.txt
du -sh data/cache/ >> debug.txt
ls data/cache/ >> debug.txt

echo "=== Test Results ===" >> debug.txt
python backend/test_cache.py >> debug.txt 2>&1

cat debug.txt
```

### Check Recent Changes
```bash
# View recent git commits
git log --oneline -10

# See what changed
git diff HEAD~5
```

---

## Contact & Support

- Check logs in console
- Review `CACHE_PIPELINE_FIX.md` for recent changes
- Review `CACHE.md` for architecture details
- Review test files for expected behavior

The system is designed to be resilient - most issues can be fixed by clearing caches and retrying.
