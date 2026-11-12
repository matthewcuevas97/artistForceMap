"""
User ingestion: fetching user's top artists from Spotify/Last.fm.
"""

from typing import Dict, List, Any

import spotipy

from backend.user_data import get_or_create_user, update_user_db, set_user_top_artists


def fetch_top_25_artists_spotify(access_token: str) -> List[Dict[str, Any]]:
    """
    Fetch user's top 25 artists from Spotify.
    Returns list of {name, rank (1-25), spotify_id, images, genres}.
    """
    sp = spotipy.Spotify(auth=access_token)
    results = sp.current_user_top_artists(limit=50, time_range="medium_term")

    top_artists = []
    for rank, artist in enumerate(results["items"][:25], 1):
        top_artists.append({
            "name": artist["name"],
            "rank": rank,
            "spotify_id": artist["id"],
            "genres": artist.get("genres", []),
            "images": artist.get("images", []),
            "popularity": artist.get("popularity", 0),
        })

    return top_artists


def fetch_top_25_artists_lastfm(username: str) -> List[Dict[str, Any]]:
    """
    Fetch user's top 25 artists from Last.fm.
    Returns list of {name, rank (1-25), lastfm_url}.
    """
    from lastfm.fetch import get_top_artists as lastfm_top

    top_artists = lastfm_top(username, limit=50)
    return [
        {
            "name": artist["name"],
            "rank": rank,
            "lastfm_url": f"https://www.last.fm/music/{artist['name']}",
        }
        for rank, artist in enumerate(top_artists[:25], 1)
    ]


def ingest_user(auth_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Complete user ingestion: create user record and fetch top 25 artists.
    """
    user_id = auth_data.get("id", "unknown")

    # Create/get user record
    get_or_create_user(user_id, auth_data)

    # Fetch top artists based on provider
    provider = auth_data.get("provider", "unknown")
    if provider == "spotify":
        top_artists = fetch_top_25_artists_spotify(auth_data["token"])
    elif provider == "lastfm":
        top_artists = fetch_top_25_artists_lastfm(user_id)
    else:
        raise ValueError(f"Unknown provider: {provider}")

    # Save to user database using cache system
    # Convert to format expected by caching system
    formatted_artists = [
        {
            "name": artist["name"],
            "score": 1.0 - (i / max(len(top_artists) - 1, 1))  # Normalize score
        }
        for i, artist in enumerate(top_artists)
    ]

    # Use caching system to store artists
    if provider == "spotify":
        set_user_top_artists(user_id, spotify_artists=formatted_artists)
    else:
        set_user_top_artists(user_id, lastfm_artists=formatted_artists)

    # Also update legacy top_artists field for compatibility
    update_user_db(user_id, {"top_artists": top_artists})

    return {
        "user_id": user_id,
        "provider": provider,
        "top_artists_count": len(top_artists),
        "top_artists": top_artists,
    }
