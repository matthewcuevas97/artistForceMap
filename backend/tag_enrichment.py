"""
Tag enrichment: fetch Last.fm artist info and tags for all top 25 artists.
"""

import time
from typing import Dict, List, Any

from lastfm.fetch import get_artist_info, get_artist_top_tags, get_artist_image_and_bio

from backend.user_data import load_user_db, update_user_db


def enrich_artist_with_lastfm(artist_name: str) -> Dict[str, Any]:
    """
    Fetch enriched data from Last.fm for a single artist.
    Returns {name, listeners, tags, image_url, bio}.
    """
    # Get basic info
    info = get_artist_info(artist_name)
    listeners = info.get("listeners", 0) if info else 0

    # Get top tags
    tags = get_artist_top_tags(artist_name, limit=10)

    # Get image and bio
    image_url, bio = get_artist_image_and_bio(artist_name)

    return {
        "name": artist_name,
        "listeners": listeners,
        "tags": tags or [],
        "image_url": image_url,
        "bio": bio,
    }


def enrich_top_25_artists(user_id: str) -> Dict[str, Any]:
    """
    Enrich all top 25 artists with Last.fm data.
    Saves to user_db.json under all_artists key.
    """
    db = load_user_db(user_id)
    top_artists = db.get("top_artists", [])

    all_artists = {}

    print(f"Enriching {len(top_artists)} artists with Last.fm data...")

    for i, artist in enumerate(top_artists, 1):
        artist_name = artist.get("name")
        print(f"  [{i}/{len(top_artists)}] {artist_name}...", end=" ", flush=True)

        try:
            enriched = enrich_artist_with_lastfm(artist_name)
            enriched["rank"] = artist.get("rank", i)  # Preserve original rank
            all_artists[artist_name] = enriched
            print("✓")
        except Exception as e:
            print(f"✗ ({str(e)})")
            # Still add minimal data
            all_artists[artist_name] = {
                "name": artist_name,
                "rank": artist.get("rank", i),
                "tags": [],
                "listeners": 0,
            }

        time.sleep(0.2)  # Rate limiting

    # Save enriched data
    db["all_artists"] = all_artists
    update_user_db(user_id, {"all_artists": all_artists})

    return {
        "user_id": user_id,
        "enriched_count": len(all_artists),
        "all_artists": all_artists,
    }
