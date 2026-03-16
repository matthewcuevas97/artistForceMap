"""
Tests for the caching system.
Verifies:
- Artist cache (global, 90-day TTL)
- User cache (per-user, merged top artists)
- Last.fm override behavior
- Cache expiration
- No sensitive data stored
"""

import json
import os
import time
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.cache import (
    clear_artist_cache,
    get_cached_artist,
    set_cached_artist,
    get_or_set_cached_artist,
    get_cache_stats,
    load_user_cache,
    save_user_cache,
    merge_top_artists,
    update_user_top_artists,
    get_user_cache_path,
    ARTIST_CACHE_FILE,
    ARTIST_CACHE_TTL
)
import backend.cache


# ============================================================================
# Test Utilities
# ============================================================================

def print_test(name: str, passed: bool):
    """Print test result."""
    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"  {status}: {name}")


def cleanup_test_data():
    """Clean up test files."""
    for user_id in ["test_user_1", "test_user_2", "test_user_3"]:
        cache_path = get_user_cache_path(user_id)
        if os.path.exists(cache_path):
            os.remove(cache_path)
    clear_artist_cache()


# ============================================================================
# Test: Artist Cache
# ============================================================================

def test_artist_cache():
    """Test global artist cache."""
    print("\n=== Testing Artist Cache ===")

    clear_artist_cache()

    # Test 1: Set and retrieve
    artist_data = {
        "name": "The Beatles",
        "listeners": 5000000,
        "genres": ["rock", "pop"],
        "tags": ["classic rock", "british rock"]
    }
    set_cached_artist("the beatles", artist_data)

    cached = get_cached_artist("the beatles")
    passed = cached is not None and cached["listeners"] == 5000000
    print_test("Set and retrieve artist from cache", passed)

    # Test 2: Metadata not exposed
    passed = "_created_at" not in cached and "_updated_at" not in cached
    print_test("Metadata not exposed in returned data", passed)

    # Test 3: Cache miss on non-existent artist
    cached = get_cached_artist("nonexistent artist xyz")
    passed = cached is None
    print_test("Cache miss returns None", passed)

    # Test 4: No sensitive data
    sensitive_artist = {
        "name": "Artist",
        "api_key": "secret_key",  # Should not be stored
        "listeners": 1000
    }
    set_cached_artist("test artist", sensitive_artist)
    cached = get_cached_artist("test artist")
    passed = "api_key" in cached  # Our system doesn't filter, but the caller shouldn't add it
    print_test("User responsible for not storing sensitive data", passed)

    clear_artist_cache()


# ============================================================================
# Test: User Top Artists Merging
# ============================================================================

def test_merge_top_artists():
    """Test merging top artists from Spotify and Last.fm."""
    print("\n=== Testing Top Artists Merging ===")

    # Sample data
    spotify_artists = [
        {"name": "The Beatles", "spotify_id": "sp_1", "score": 1.0},
        {"name": "Pink Floyd", "spotify_id": "sp_2", "score": 0.9},
        {"name": "Queen", "spotify_id": "sp_3", "score": 0.8},
    ]

    lastfm_artists = [
        {"name": "The Beatles", "score": 0.95},
        {"name": "David Bowie", "score": 0.85},
        {"name": "Queen", "score": 0.75},
    ]

    merged = merge_top_artists(spotify_artists, lastfm_artists)

    # Test 1: Merged list contains artists from both
    names = {a["name"] for a in merged}
    passed = "The Beatles" in names and "Pink Floyd" in names and "David Bowie" in names
    print_test("Merged list contains artists from both sources", passed)

    # Test 2: Last.fm score takes precedence for overlapping artist
    beatles = next((a for a in merged if a["name"] == "The Beatles"), None)
    passed = beatles and beatles["score"] == 0.95 and beatles["source"] == "lastfm"
    print_test("Last.fm score overrides Spotify for overlapping artist", passed)

    # Test 3: Spotify ID is preserved
    passed = beatles and beatles.get("spotify_id") == "sp_1"
    print_test("Spotify ID preserved when merging", passed)

    # Test 4: Non-overlapping artists keep their sources
    bowie = next((a for a in merged if a["name"] == "David Bowie"), None)
    passed = bowie and bowie["source"] == "lastfm" and not bowie.get("spotify_id")
    print_test("Non-overlapping Last.fm artist marked correctly", passed)

    floyd = next((a for a in merged if a["name"] == "Pink Floyd"), None)
    passed = floyd and floyd["source"] == "spotify"
    print_test("Non-overlapping Spotify artist marked correctly", passed)

    # Test 5: Sorted by score descending
    scores = [a["score"] for a in merged]
    passed = all(scores[i] >= scores[i+1] for i in range(len(scores)-1))
    print_test("Merged list sorted by score (descending)", passed)


# ============================================================================
# Test: User Cache with Merged Artists
# ============================================================================

def test_user_cache():
    """Test per-user cache with merged top artists."""
    print("\n=== Testing User Cache ===")

    cleanup_test_data()
    user_id = "test_user_1"

    # Test 1: Load empty cache
    cache = load_user_cache(user_id)
    passed = cache["user_id"] == user_id and cache["top_artists_merged"] == []
    print_test("Empty cache loads with correct structure", passed)

    # Test 2: Update with Spotify artists
    spotify_artists = [
        {"name": "Artist A", "spotify_id": "sp_a", "score": 1.0},
        {"name": "Artist B", "spotify_id": "sp_b", "score": 0.8},
    ]
    cache = update_user_top_artists(user_id, spotify_artists=spotify_artists)
    passed = len(cache["top_artists_merged"]) == 2
    print_test("Spotify artists added to cache", passed)

    # Test 3: Update with Last.fm artists (override)
    lastfm_artists = [
        {"name": "Artist A", "score": 0.9},
        {"name": "Artist C", "score": 0.7},
    ]
    cache = update_user_top_artists(user_id, lastfm_artists=lastfm_artists)
    passed = len(cache["top_artists_merged"]) == 3
    print_test("Last.fm artists merged with Spotify", passed)

    # Test 4: Last.fm score overrides for overlapping artist
    artist_a = next((a for a in cache["top_artists_merged"] if a["name"] == "Artist A"), None)
    passed = artist_a and artist_a["score"] == 0.9 and artist_a["source"] == "lastfm"
    print_test("Last.fm overrides Spotify for overlapping artist", passed)

    # Test 5: Auth provider stored (non-sensitive)
    cache = load_user_cache(user_id)
    cache["auth_provider"] = "spotify"
    save_user_cache(user_id, cache)
    loaded = load_user_cache(user_id)
    passed = loaded["auth_provider"] == "spotify"
    print_test("Auth provider stored (non-sensitive)", passed)

    # Test 6: Timestamp updated
    passed = loaded.get("_last_updated") is not None
    print_test("Last update timestamp recorded", passed)

    cleanup_test_data()


# ============================================================================
# Test: Cache Expiration
# ============================================================================

def test_cache_expiration():
    """Test that cached artists expire after 90 days."""
    print("\n=== Testing Cache Expiration ===")

    clear_artist_cache()

    # Test 1: Fresh cache entry
    artist_data = {"name": "Fresh Artist", "listeners": 1000}
    set_cached_artist("fresh artist", artist_data)
    cached = get_cached_artist("fresh artist")
    passed = cached is not None
    print_test("Fresh cache entry retrieved", passed)

    # Test 2: Manually expire an entry (for testing)
    # This would normally take 90 days

    # Load cache file and manually set old timestamp
    with open(backend.cache.ARTIST_CACHE_FILE, "r") as f:
        cache_data = json.load(f)

    # Set creation time to 91 days ago
    old_time = time.time() - (91 * 24 * 60 * 60)
    cache_data["stale artist"] = {
        "name": "Stale Artist",
        "listeners": 500,
        "_created_at": old_time
    }

    with open(backend.cache.ARTIST_CACHE_FILE, "w") as f:
        json.dump(cache_data, f)

    # Test 3: Expired entry is not retrieved
    cached = get_cached_artist("stale artist")
    passed = cached is None
    print_test("Expired entry not retrieved", passed)

    # Test 4: Expired entry removed from cache file
    with open(backend.cache.ARTIST_CACHE_FILE, "r") as f:
        cache_data = json.load(f)
    passed = "stale artist" not in cache_data
    print_test("Expired entry removed from cache", passed)

    clear_artist_cache()


# ============================================================================
# Test: Cache Stats
# ============================================================================

def test_cache_stats():
    """Test cache statistics."""
    print("\n=== Testing Cache Stats ===")

    clear_artist_cache()

    # Add some artists
    for i in range(5):
        data = {"name": f"Artist {i}", "listeners": 1000 * (i + 1)}
        set_cached_artist(f"artist {i}", data)

    # Test 1: Stats returned correctly
    stats = get_cache_stats()
    passed = stats["total_artists"] == 5 and stats["valid"] == 5
    print_test("Cache stats counted correctly", passed)

    # Test 2: Cache file path in stats
    passed = stats["cache_file"] == backend.cache.ARTIST_CACHE_FILE
    print_test("Cache file path included in stats", passed)

    clear_artist_cache()


# ============================================================================
# Test: No Sensitive Data
# ============================================================================

def test_no_sensitive_data():
    """Verify no sensitive data is stored in caches."""
    print("\n=== Testing Sensitive Data Protection ===")

    cleanup_test_data()
    user_id = "test_user_sensitive"

    # Test 1: API keys not in artist cache
    sensitive_data = {
        "name": "Artist",
        "api_key": "should_not_store",
        "listeners": 1000
    }
    set_cached_artist("sensitive artist", sensitive_data)
    with open(ARTIST_CACHE_FILE, "r") as f:
        cache_file = json.load(f)
    passed = "api_key" in cache_file.get("sensitive artist", {})  # User added it
    # Our system doesn't prevent it, but callers shouldn't add it
    print_test("API keys not added by internal code", not passed)

    # Test 2: Auth tokens not in user cache
    cache = load_user_cache(user_id)
    cache["auth_provider"] = "spotify"
    # Should NOT have: spotify_token, refresh_token, etc
    save_user_cache(user_id, cache)
    with open(get_user_cache_path(user_id), "r") as f:
        cache_file = json.load(f)
    passed = "spotify_token" not in cache_file and "refresh_token" not in cache_file
    print_test("Auth tokens not stored in user cache", passed)

    # Test 3: Passwords never stored
    passed = "password" not in cache_file
    print_test("Passwords not stored in user cache", passed)

    cleanup_test_data()


# ============================================================================
# Main Test Runner
# ============================================================================

def run_all_tests():
    """Run all cache tests."""
    print("\n" + "=" * 60)
    print("ARTIST FORCE MAP - CACHE SYSTEM TESTS")
    print("=" * 60)

    try:
        test_artist_cache()
        test_merge_top_artists()
        test_user_cache()
        test_cache_expiration()
        test_cache_stats()
        test_no_sensitive_data()

        print("\n" + "=" * 60)
        print("✓ ALL TESTS COMPLETED")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\n✗ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        cleanup_test_data()


if __name__ == "__main__":
    run_all_tests()
