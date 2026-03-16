"""
User data persistence layer with caching.
- User cache: top artists (merged from Spotify/Last.fm), seed artists, map reference
- Artist cache: global 90-day cache for artist info
- NO sensitive data: auth tokens, passwords, refresh tokens
"""

import json
import os
from typing import Any, Dict, List, Optional
from .cache import (
    load_user_cache,
    save_user_cache,
    update_user_top_artists,
    merge_top_artists
)

USER_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "users")
os.makedirs(USER_DATA_DIR, exist_ok=True)


def get_user_db_path(user_id: str) -> str:
    """Get the path to a user's database file (legacy, for backwards compat)."""
    return os.path.join(USER_DATA_DIR, f"{user_id}_db.json")


def get_user_map_path(user_id: str) -> str:
    """Get the path to a user's map file."""
    return os.path.join(USER_DATA_DIR, f"{user_id}_map.json")


# ============================================================================
# User Cache (Primary Data Source)
# ============================================================================

def load_user_db(user_id: str) -> Dict[str, Any]:
    """
    Load user database from cache layer + legacy format.
    Contains: top artists (merged), seed artists, map reference, auth provider.
    Also loads enriched data from legacy format (all_artists).
    NO sensitive data (tokens, passwords, etc).
    """
    cache = load_user_cache(user_id)

    # Get top artists: prefer merged, fall back to individual sources if only one is set
    top_artists = cache.get("top_artists_merged", [])
    if not top_artists:
        # If merged is empty, use whichever source is available
        if cache.get("top_artists_spotify"):
            top_artists = cache["top_artists_spotify"]
        elif cache.get("top_artists_lastfm"):
            top_artists = cache["top_artists_lastfm"]

    # Try to load enriched data from legacy format
    all_artists = {}
    try:
        legacy_path = get_user_db_path(user_id)
        if os.path.exists(legacy_path):
            with open(legacy_path, "r") as f:
                legacy_data = json.load(f)
                all_artists = legacy_data.get("all_artists", {})
    except Exception:
        pass

    return {
        "user_id": user_id,
        "auth_provider": cache.get("auth_provider"),
        "top_artists": top_artists,  # Top 50 merged from both sources
        "top_artists_spotify": cache.get("top_artists_spotify", []),  # For reference
        "top_artists_lastfm": cache.get("top_artists_lastfm", []),     # For reference
        "seed_artists": cache.get("seed_artists", []),
        "all_artists": all_artists,  # Enriched data from legacy format
        "map_id": cache.get("map_id"),
        "_last_updated": cache.get("_last_updated")
    }


def save_user_db(user_id: str, data: Dict[str, Any]) -> None:
    """
    Save user database to cache layer.
    Extracts relevant fields and updates cache.
    Also persists all_artists to legacy format for backward compat.
    """
    cache = load_user_cache(user_id)

    # Update non-sensitive fields only
    if "auth_provider" in data:
        cache["auth_provider"] = data["auth_provider"]
    if "seed_artists" in data:
        cache["seed_artists"] = data["seed_artists"]
    if "map_id" in data:
        cache["map_id"] = data["map_id"]

    save_user_cache(user_id, cache)

    # Persist all_artists to legacy format if present
    if "all_artists" in data:
        legacy_path = get_user_db_path(user_id)
        try:
            legacy = {}
            if os.path.exists(legacy_path):
                with open(legacy_path) as f:
                    legacy = json.load(f)
            legacy["all_artists"] = data["all_artists"]
            with open(legacy_path, "w") as f:
                json.dump(legacy, f, indent=2)
        except Exception:
            pass


def load_user_map(user_id: str) -> Dict[str, Any]:
    """Load user's graph map (nodes and edges for frontend)."""
    path = get_user_map_path(user_id)
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {
        "user_id": user_id,
        "nodes": [],  # Seed artists with full metadata
        "edges": [],  # Connections between seed artists
    }


def save_user_map(user_id: str, data: Dict[str, Any]) -> None:
    """Save user's graph map."""
    path = get_user_map_path(user_id)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    # Also update cache to point to this map
    cache = load_user_cache(user_id)
    cache["map_id"] = user_id  # or derive actual map ID if different
    save_user_cache(user_id, cache)


def get_or_create_user(user_id: str, auth_data: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Get or create a user record."""
    cache = load_user_cache(user_id)
    if not cache.get("auth_provider"):
        cache["auth_provider"] = auth_data.get("provider") if auth_data else "unknown"
        save_user_cache(user_id, cache)
    return load_user_db(user_id)


def update_user_db(user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update specific fields in user database."""
    db = load_user_db(user_id)
    db.update(updates)
    save_user_db(user_id, db)
    return db


# ============================================================================
# Top Artists Management
# ============================================================================

def set_user_top_artists(
    user_id: str,
    spotify_artists: Optional[List[Dict[str, Any]]] = None,
    lastfm_artists: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Set user's top artists from one or both sources.
    Last.fm takes precedence when both are provided.

    Args:
        user_id: User ID
        spotify_artists: [{"name", "spotify_id", "score"}]
        lastfm_artists: [{"name", "score"}]

    Returns:
        Updated user database
    """
    update_user_top_artists(user_id, spotify_artists, lastfm_artists)
    return load_user_db(user_id)


def get_user_top_artists(
    user_id: str,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Get user's merged top artists.

    Args:
        user_id: User ID
        limit: Limit results to top N (default 50)

    Returns:
        List of top artists with score, source, and spotify_id if available
    """
    db = load_user_db(user_id)
    artists = db.get("top_artists", [])
    if limit:
        artists = artists[:limit]
    return artists
