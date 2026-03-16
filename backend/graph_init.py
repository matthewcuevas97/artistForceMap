"""
Graph initialization: fetch full metadata for seed artists and build initial graph.
"""

import time
from typing import Dict, List, Any, Tuple

from lastfm.fetch import get_similar_artists, get_top_tracks
from backend.user_data import load_user_db, load_user_map, save_user_map, update_user_db


def fetch_deezer_artist_info(artist_name: str) -> Dict[str, Any]:
    """
    Fetch artist info from Deezer: bio, images, top tracks.
    """
    import requests

    try:
        # Search for artist on Deezer
        resp = requests.get(
            "https://api.deezer.com/search/artist",
            params={"q": artist_name, "limit": 1},
            timeout=5
        )
        data = resp.json()
        results = data.get("data", [])

        if not results:
            return {"error": "not_found"}

        artist = results[0]
        artist_id = artist.get("id")

        # Get full artist info including top tracks
        artist_resp = requests.get(
            f"https://api.deezer.com/artist/{artist_id}",
            timeout=5
        )
        artist_full = artist_resp.json()

        # Get top tracks
        tracks_resp = requests.get(
            f"https://api.deezer.com/artist/{artist_id}/top",
            params={"limit": 10},
            timeout=5
        )
        tracks_data = tracks_resp.json()

        return {
            "name": artist.get("name", artist_name),
            "image_url": artist.get("picture_xl") or artist.get("picture_big"),
            "fans": artist_full.get("nb_fan", 0),
            "top_tracks": [
                {
                    "name": t.get("title"),
                    "artist": t.get("artist", {}).get("name"),
                    "preview_url": t.get("preview"),
                    "album_art": t.get("album", {}).get("cover_big"),
                }
                for t in tracks_data.get("data", [])[:10]
            ],
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_seed_artist_metadata(artist_name: str, lastfm_data: Dict) -> Dict[str, Any]:
    """
    Fetch complete metadata for a seed artist.
    Combines Last.fm and Deezer data.
    """
    print(f"  Fetching metadata for {artist_name}...", end=" ", flush=True)

    # Get similar artists from Last.fm
    similar = get_similar_artists(artist_name, limit=20, threshold=0.05)
    time.sleep(0.15)

    # Get Deezer data
    deezer_info = fetch_deezer_artist_info(artist_name)
    time.sleep(0.1)

    # Combine all data
    metadata = {
        "name": artist_name,
        "rank": lastfm_data.get("rank"),
        "listeners": lastfm_data.get("listeners", 0),
        "tags": lastfm_data.get("tags", []),
        "image_url": lastfm_data.get("image_url") or deezer_info.get("image_url"),
        "bio": lastfm_data.get("bio"),
        "similar_artists": similar,
        "top_tracks": deezer_info.get("top_tracks", []),
        "deezer_fans": deezer_info.get("fans", 0),
    }

    print("✓")
    return metadata


def rbo_similarity(list1: List[str], list2: List[str], p: float = 0.9) -> float:
    """
    Rank-Biased Overlap similarity between two ranked lists.
    """
    if not list1 and not list2:
        return 1.0
    if not list1 or not list2:
        return 0.0

    set1, set2 = set(), set()
    score = 0.0
    max_d = max(len(list1), len(list2))

    for d in range(1, max_d + 1):
        if d <= len(list1):
            set1.add(list1[d - 1])
        if d <= len(list2):
            set2.add(list2[d - 1])
        agreement = len(set1 & set2) / d
        score += (1 - p) * (p ** (d - 1)) * agreement

    return score


def build_seed_graph(
    user_id: str,
    seed_artists: List[str],
    all_artists_metadata: Dict[str, Dict],
) -> Dict[str, Any]:
    """
    Build initial graph with seed artists as nodes and edges between them.
    Uses Gold Standard (similar artists overlap) + RBO logic.
    """
    print(f"Building graph with {len(seed_artists)} seed artists...")

    nodes = []
    node_map = {name: metadata for name, metadata in all_artists_metadata.items()}

    # Add seed artists as nodes
    for artist_name in seed_artists:
        if artist_name in node_map:
            nodes.append(node_map[artist_name])

    # Build edges using Gold Standard + RBO
    edges = []
    added_edges = set()

    print("  Building edges...")

    # Gold Standard: similar artists that are both in seed set
    for i, artist1 in enumerate(seed_artists):
        metadata1 = node_map.get(artist1, {})
        similar1 = [s["name"] for s in metadata1.get("similar_artists", [])]

        for artist2 in seed_artists[i + 1 :]:
            if artist2 in similar1:
                # Found a direct similarity
                edge_key = tuple(sorted([artist1, artist2]))
                if edge_key not in added_edges:
                    edges.append({
                        "source": artist1,
                        "target": artist2,
                        "type": "similar",
                        "pass": 1,  # Gold Standard
                        "weight": 1.0,
                    })
                    added_edges.add(edge_key)

    # RBO: tag-based similarity for remaining pairs
    for i, artist1 in enumerate(seed_artists):
        metadata1 = node_map.get(artist1, {})
        tags1 = metadata1.get("tags", [])

        for artist2 in seed_artists[i + 1 :]:
            edge_key = tuple(sorted([artist1, artist2]))
            if edge_key in added_edges:
                continue  # Already has an edge

            metadata2 = node_map.get(artist2, {})
            tags2 = metadata2.get("tags", [])

            # RBO similarity of tags
            rbo_score = rbo_similarity(tags1, tags2, p=0.9)
            if rbo_score >= 0.21:  # RBO_BASE_THRESHOLD
                edges.append({
                    "source": artist1,
                    "target": artist2,
                    "type": "tag_similarity",
                    "pass": 2,  # Base RBO
                    "weight": rbo_score,
                })
                added_edges.add(edge_key)

    print(f"  {len(nodes)} nodes, {len(edges)} edges")

    return {
        "nodes": nodes,
        "edges": edges,
    }


def initialize_user_graph(user_id: str) -> Dict[str, Any]:
    """
    Complete graph initialization:
    1. Fetch full metadata for each seed artist.
    2. Build initial graph with edges.
    3. Save to user_map.json.
    """
    db = load_user_db(user_id)
    seed_artists = db.get("seed_artists", [])
    all_artists = db.get("all_artists", {})

    if not seed_artists:
        raise ValueError(f"No seed artists found for user {user_id}")

    print(f"Initializing graph for {len(seed_artists)} seed artists...")

    # Fetch metadata for each seed artist
    all_artists_metadata = {}
    for artist_name in seed_artists:
        lastfm_data = all_artists.get(artist_name, {})
        metadata = fetch_seed_artist_metadata(artist_name, lastfm_data)
        all_artists_metadata[artist_name] = metadata
        time.sleep(0.1)

    # Build graph
    graph = build_seed_graph(user_id, seed_artists, all_artists_metadata)

    # Save to user_map.json
    user_map = {
        "user_id": user_id,
        "nodes": graph["nodes"],
        "edges": graph["edges"],
    }
    save_user_map(user_id, user_map)

    # Update database with metadata
    db["all_artists_metadata"] = all_artists_metadata
    update_user_db(user_id, {"all_artists_metadata": all_artists_metadata})

    return {
        "user_id": user_id,
        "graph": graph,
        "status": "initialized",
    }
