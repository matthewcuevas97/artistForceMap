"""
Fast enrichment script to add images, bio, and tracks to graph_static.json.
Fetches from Last.fm and Deezer APIs with caching.
"""

import json
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lastfm.fetch import get_artist_image_and_bio, get_top_tracks, get_artist_image_from_deezer

# Cache setup
CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "lastfm_api_cache.json")

def load_cache():
    default = {"artist_images": {}, "deezer_images": {}, "top_tracks": {}}
    if not os.path.exists(CACHE_PATH):
        return default
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)
        # Merge with defaults to support both old and new cache formats
        return {**existing, **default, **{k: v for k, v in existing.items() if k in default}}
    except (json.JSONDecodeError, FileNotFoundError):
        return default

def save_cache(cache):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def enrich_graph():
    # Load graph and cache
    graph_path = os.path.join(os.path.dirname(__file__), "..", "data", "graph_static.json")
    with open(graph_path) as f:
        graph = json.load(f)

    cache = load_cache()
    nodes = graph["nodes"]
    total = len(nodes)

    # Enrich images and bio — build artist_profiles for all artists
    print("--- Enriching Images and Bio ---")
    for i, node in enumerate(nodes, 1):
        lastfm_artists = node.get("lastfm_artists", [])
        artist_profiles = []

        if lastfm_artists:
            for artist_name in lastfm_artists:
                # Check cache first
                cache_key = artist_name
                if cache_key in cache["artist_images"]:
                    image_url, bio = cache["artist_images"][cache_key]
                else:
                    image_url, bio = get_artist_image_and_bio(artist_name)
                    cache["artist_images"][cache_key] = (image_url, bio)
                    time.sleep(0.2)

                # Fallback to Deezer if Last.fm doesn't have image
                if not image_url or "2a96cbd8b46e442fc41c2b86b821562f" in image_url:
                    if cache_key in cache["deezer_images"]:
                        deezer_image = cache["deezer_images"][cache_key]
                    else:
                        deezer_image = get_artist_image_from_deezer(artist_name)
                        cache["deezer_images"][cache_key] = deezer_image
                        time.sleep(0.1)

                    if deezer_image:
                        image_url = deezer_image

                artist_profiles.append({
                    "name": artist_name,
                    "image_url": image_url,
                    "bio": bio,
                })

            # Set backward-compat top-level fields from first profile
            node["artist_profiles"] = artist_profiles
            node["image_url"] = artist_profiles[0]["image_url"]
            node["bio"] = artist_profiles[0]["bio"]
            print(f"  {i}/{total}: {node['name']} - {len(artist_profiles)} artist(s) - {'✓' if node['image_url'] else '✗'}")
        else:
            node["artist_profiles"] = []
            node["image_url"] = None
            node["bio"] = None
            print(f"  {i}/{total}: {node['name']} - no artists")

    # Enrich tracks — fetch from ALL artists, deduplicate by name
    print("\n--- Enriching Top Tracks ---")
    DEEZER_SEARCH = "https://api.deezer.com/search"

    def norm_simple(s):
        return re.sub(r'[^\w]', '', s.lower())

    for i, node in enumerate(nodes, 1):
        top_tracks_dict = {}  # keyed by track name to deduplicate
        lastfm_artists = node.get("lastfm_artists", [])

        if lastfm_artists:
            # Fetch up to 10 tracks from EACH artist
            all_track_names = []
            for artist_name in lastfm_artists:
                tracks = get_top_tracks(artist_name, limit=10)
                all_track_names.extend(tracks)
                time.sleep(0.1)

            # Deduplicate by track name
            unique_track_names = []
            seen = set()
            for track_name in all_track_names:
                norm_name = norm_simple(track_name)
                if norm_name not in seen:
                    seen.add(norm_name)
                    unique_track_names.append(track_name)

            # For each unique track, try all artists to find it on Deezer
            for track_name in unique_track_names[:10]:  # limit to 10 total
                found = False
                try:
                    for artist_name in lastfm_artists:
                        if found:
                            break
                        q = f'artist:"{artist_name}" track:"{track_name}"'
                        resp = requests.get(
                            DEEZER_SEARCH,
                            params={"q": q, "limit": 3},
                            timeout=5,
                        )
                        if not resp.ok:
                            continue

                        results = resp.json().get("data", [])
                        for r in results:
                            r_title = norm_simple(r.get("title", ""))
                            t_name = norm_simple(track_name)
                            if r_title == t_name or t_name in r_title:
                                preview = r.get("preview", "")
                                album = r.get("album", {})
                                album_art = album.get("cover_big") or album.get("cover_medium") or album.get("cover") or ""
                                top_tracks_dict[track_name] = {
                                    "name": track_name,
                                    "artist": artist_name,
                                    "preview_url": preview,
                                    "album_art": album_art,
                                }
                                found = True
                                break

                        # Fallback to first result
                        if not found and results:
                            preview = results[0].get("preview", "")
                            album = results[0].get("album", {})
                            album_art = album.get("cover_big") or album.get("cover_medium") or album.get("cover") or ""
                            top_tracks_dict[track_name] = {
                                "name": track_name,
                                "artist": artist_name,
                                "preview_url": preview,
                                "album_art": album_art,
                            }
                            found = True
                except Exception:
                    pass

                time.sleep(0.15)

        top_tracks = list(top_tracks_dict.values())[:10]
        node["top_tracks"] = top_tracks
        print(f"  {i}/{total}: {node['name']} - {len(node['top_tracks'])} tracks")

    # Save enriched graph and cache
    with open(graph_path, "w") as f:
        json.dump(graph, f, indent=2)

    save_cache(cache)
    print(f"\n✓ Enrichment complete. Saved to {graph_path}")
    print(f"✓ Cache saved with {len(cache['artist_images'])} artist images and {len(cache['deezer_images'])} Deezer lookups")


if __name__ == "__main__":
    enrich_graph()
