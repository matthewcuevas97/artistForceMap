"""
Global caching layer for API requests.
- Artist info DB: global, 90-day cache
- User DB: per-user, contains non-sensitive data (top artists, seed artists, map reference)
- NO sensitive data stored: auth tokens, passwords, refresh tokens
"""

import json
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, List

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

ARTIST_CACHE_FILE = os.path.join(CACHE_DIR, "artists.json")
SIMILAR_ARTISTS_CACHE_FILE = os.path.join(CACHE_DIR, "similar_artists.json")
DEEZER_CACHE_FILE = os.path.join(CACHE_DIR, "deezer.json")
ARTIST_CACHE_TTL = 90 * 24 * 60 * 60  # 90 days in seconds
SIMILAR_ARTISTS_CACHE_TTL = 90 * 24 * 60 * 60  # 90 days in seconds
DEEZER_CACHE_TTL = 90 * 24 * 60 * 60  # 90 days in seconds


# ============================================================================
# Artist Info Cache (Global)
# ============================================================================

def _load_artist_cache() -> Dict[str, Any]:
    """Load the global artist cache from disk."""
    if not os.path.exists(ARTIST_CACHE_FILE):
        return {}
    try:
        with open(ARTIST_CACHE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_artist_cache(cache: Dict[str, Any]) -> None:
    """Save the global artist cache to disk."""
    try:
        with open(ARTIST_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Failed to save artist cache: {e}")


def get_cached_artist(artist_name: str) -> Optional[Dict[str, Any]]:
    """
    Get artist info from cache, if it exists and hasn't expired.

    Args:
        artist_name: Normalized artist name (lowercase)

    Returns:
        Artist dict with info, or None if not cached or expired
    """
    cache = _load_artist_cache()
    entry = cache.get(artist_name)

    if not entry:
        return None

    # Check expiry
    created_at = entry.get("_created_at", 0)
    if time.time() - created_at > ARTIST_CACHE_TTL:
        # Expired, remove it
        del cache[artist_name]
        _save_artist_cache(cache)
        return None

    # Return data (without metadata)
    return {k: v for k, v in entry.items() if not k.startswith("_")}


def set_cached_artist(artist_name: str, data: Dict[str, Any]) -> None:
    """
    Cache artist info globally.

    Args:
        artist_name: Normalized artist name (lowercase)
        data: Artist info dict (no sensitive data)
    """
    cache = _load_artist_cache()
    cache[artist_name] = {
        **data,
        "_created_at": time.time(),
        "_updated_at": datetime.now().isoformat()
    }
    _save_artist_cache(cache)


def get_or_set_cached_artist(
    artist_name: str,
    fetch_fn,
    *args,
    **kwargs
) -> Optional[Dict[str, Any]]:
    """
    Get artist from cache, or fetch and cache if not found.

    Args:
        artist_name: Normalized artist name
        fetch_fn: Async/sync function to fetch artist data
        *args, **kwargs: Arguments to pass to fetch_fn

    Returns:
        Artist data
    """
    # Try cache first
    cached = get_cached_artist(artist_name)
    if cached:
        return cached

    # Fetch and cache
    try:
        data = fetch_fn(*args, **kwargs)
        if data:
            set_cached_artist(artist_name, data)
        return data
    except Exception as e:
        print(f"Failed to fetch artist {artist_name}: {e}")
        return None


def clear_artist_cache() -> None:
    """Clear the entire artist cache (useful for testing)."""
    try:
        if os.path.exists(ARTIST_CACHE_FILE):
            os.remove(ARTIST_CACHE_FILE)
    except Exception as e:
        print(f"Failed to clear cache: {e}")


def get_cache_stats() -> Dict[str, Any]:
    """Get statistics about the artist cache."""
    cache = _load_artist_cache()
    now = time.time()

    total = len(cache)
    expired = 0
    for entry in cache.values():
        created_at = entry.get("_created_at", 0)
        if now - created_at > ARTIST_CACHE_TTL:
            expired += 1

    return {
        "total_artists": total,
        "expired": expired,
        "valid": total - expired,
        "cache_file": ARTIST_CACHE_FILE
    }


# ============================================================================
# Similar Artists Cache (Global, 90-day TTL)
# ============================================================================

def _load_similar_artists_cache() -> Dict[str, Any]:
    """Load the similar artists cache from disk."""
    if not os.path.exists(SIMILAR_ARTISTS_CACHE_FILE):
        return {}
    try:
        with open(SIMILAR_ARTISTS_CACHE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_similar_artists_cache(cache: Dict[str, Any]) -> None:
    """Save the similar artists cache to disk."""
    try:
        with open(SIMILAR_ARTISTS_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Failed to save similar artists cache: {e}")


def get_cached_similar_artists(artist_name: str) -> Optional[List[Dict[str, Any]]]:
    """
    Get similar artists for an artist from cache, if it exists and hasn't expired.

    Args:
        artist_name: Artist name

    Returns:
        List of similar artist dicts, or None if not cached or expired
    """
    cache = _load_similar_artists_cache()
    entry = cache.get(artist_name)

    if not entry:
        return None

    # Check expiry
    created_at = entry.get("_created_at", 0)
    if time.time() - created_at > SIMILAR_ARTISTS_CACHE_TTL:
        # Expired, remove it
        del cache[artist_name]
        _save_similar_artists_cache(cache)
        return None

    # Return data (without metadata)
    return entry.get("similar_artists", [])


def set_cached_similar_artists(artist_name: str, similar_artists: List[Dict[str, Any]]) -> None:
    """
    Cache similar artists for an artist globally.

    Args:
        artist_name: Artist name
        similar_artists: List of similar artist dicts
    """
    cache = _load_similar_artists_cache()
    cache[artist_name] = {
        "similar_artists": similar_artists,
        "_created_at": time.time(),
        "_updated_at": datetime.now().isoformat()
    }
    _save_similar_artists_cache(cache)


# ============================================================================
# Deezer Cache (Global, 90-day TTL)
# ============================================================================

def _load_deezer_cache() -> Dict[str, Any]:
    """Load the Deezer cache from disk."""
    if not os.path.exists(DEEZER_CACHE_FILE):
        return {}
    try:
        with open(DEEZER_CACHE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_deezer_cache(cache: Dict[str, Any]) -> None:
    """Save the Deezer cache to disk."""
    try:
        with open(DEEZER_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Failed to save Deezer cache: {e}")


def get_cached_deezer_info(artist_name: str) -> Optional[Dict[str, Any]]:
    """
    Get Deezer artist info from cache, if it exists and hasn't expired.

    Args:
        artist_name: Artist name

    Returns:
        Deezer info dict, or None if not cached or expired
    """
    cache = _load_deezer_cache()
    entry = cache.get(artist_name)

    if not entry:
        return None

    # Check expiry
    created_at = entry.get("_created_at", 0)
    if time.time() - created_at > DEEZER_CACHE_TTL:
        # Expired, remove it
        del cache[artist_name]
        _save_deezer_cache(cache)
        return None

    # Return data (without metadata)
    return {k: v for k, v in entry.items() if not k.startswith("_")}


def set_cached_deezer_info(artist_name: str, data: Dict[str, Any]) -> None:
    """
    Cache Deezer artist info globally.

    Args:
        artist_name: Artist name
        data: Deezer info dict (image_url, top_tracks, fans, etc)
    """
    cache = _load_deezer_cache()
    cache[artist_name] = {
        **data,
        "_created_at": time.time(),
        "_updated_at": datetime.now().isoformat()
    }
    _save_deezer_cache(cache)


# ============================================================================
# User DB Cache (Per-User)
# ============================================================================

def get_user_cache_path(user_id: str) -> str:
    """Get path to user's cache file."""
    return os.path.join(CACHE_DIR, f"{user_id}_cache.json")


def load_user_cache(user_id: str) -> Dict[str, Any]:
    """Load user's cache data."""
    path = get_user_cache_path(user_id)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass

    return {
        "user_id": user_id,
        "auth_provider": None,  # "spotify" or "lastfm" (non-sensitive)
        "top_artists_spotify": [],  # [{"name", "spotify_id", "score"}]
        "top_artists_lastfm": [],   # [{"name", "score"}]
        "top_artists_merged": [],   # [{"name", "spotify_id", "score", "source"}] (top 50)
        "seed_artists": [],         # Selected diverse subset
        "map_id": None,             # Reference to user's map
        "_last_updated": None
    }


def save_user_cache(user_id: str, data: Dict[str, Any]) -> None:
    """Save user's cache data."""
    data["_last_updated"] = datetime.now().isoformat()
    path = get_user_cache_path(user_id)
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Failed to save user cache: {e}")


# ============================================================================
# User Top Artists Merging Logic
# ============================================================================

def merge_top_artists(
    spotify_artists: List[Dict[str, Any]],
    lastfm_artists: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Merge top artists from both sources with Last.fm taking precedence.

    Returns top 50 artists with data from both sources when available.

    Args:
        spotify_artists: [{"name", "spotify_id", "score"}]
        lastfm_artists: [{"name", "score"}]

    Returns:
        Top 50 merged artists: [{"name", "spotify_id" (if available), "score", "source"}]
    """
    # Build maps for quick lookup
    spotify_map = {artist["name"].lower(): artist for artist in spotify_artists}
    lastfm_map = {artist["name"].lower(): artist for artist in lastfm_artists}

    merged = {}

    # Add Last.fm artists first (they take precedence)
    for artist in lastfm_artists:
        name = artist["name"]
        name_lower = name.lower()
        merged[name_lower] = {
            "name": name,
            "score": artist["score"],
            "source": "lastfm",
            "spotify_id": spotify_map.get(name_lower, {}).get("spotify_id")
        }

    # Add Spotify artists not in Last.fm
    for artist in spotify_artists:
        name_lower = artist["name"].lower()
        if name_lower not in merged:
            merged[name_lower] = {
                "name": artist["name"],
                "score": artist["score"],
                "source": "spotify",
                "spotify_id": artist.get("spotify_id")
            }

    # Sort by score (descending) and take top 50
    sorted_artists = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
    return sorted_artists[:50]


def update_user_top_artists(
    user_id: str,
    spotify_artists: Optional[List[Dict[str, Any]]] = None,
    lastfm_artists: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Update user's top artists in cache.
    Merges sources and maintains parity.

    Args:
        user_id: User ID
        spotify_artists: Top artists from Spotify (if available)
        lastfm_artists: Top artists from Last.fm (if available)

    Returns:
        Updated user cache
    """
    cache = load_user_cache(user_id)

    if spotify_artists:
        cache["top_artists_spotify"] = spotify_artists
    if lastfm_artists:
        cache["top_artists_lastfm"] = lastfm_artists

    # Merge with Last.fm taking precedence
    cache["top_artists_merged"] = merge_top_artists(
        cache.get("top_artists_spotify", []),
        cache.get("top_artists_lastfm", [])
    )

    save_user_cache(user_id, cache)
    return cache
