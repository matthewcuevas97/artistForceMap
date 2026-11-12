"""
Graph initialization: fetch full metadata for seed artists and build initial graph.
Uses cache for similar artists and artist metadata.
"""

import time
from typing import Dict, List, Any, Tuple

from lastfm.fetch import get_similar_artists, get_top_tracks
from backend.cache import (
    get_cached_artist, set_cached_artist,
    get_cached_similar_artists, set_cached_similar_artists,
    get_cached_deezer_info, set_cached_deezer_info
)
from backend.user_data import load_user_db, load_user_map, save_user_map, update_user_db
from backend.progress import report


def _derive_genre(tags: List[str]) -> str:
    """
    Map Last.fm tags to readable genre names matching GENRE_HUE keys.
    """
    tag_lower = [t.lower() for t in tags]

    # Map common Last.fm tags to genre buckets
    genre_map = {
        "Electronic": ["electronic", "house", "techno", "edm", "synth", "ambient", "synthpop"],
        "Indie/Alt": ["indie", "alternative", "indie rock", "alternative rock", "indie pop"],
        "Hip-Hop": ["hip-hop", "hip hop", "rap", "hip-hop/rap"],
        "R&B/Soul": ["r&b", "r and b", "soul", "rnb"],
        "Pop": ["pop", "poppy"],
        "Punk/Metal": ["metal", "punk", "hard rock", "rock metal"],
        "Latin/Afro": ["latin", "reggaeton", "afrobeats", "spanish", "afro"],
        "Singer-Songwriter/Jazz": ["singer-songwriter", "jazz", "folk", "acoustic"],
    }

    # Check for matches in order of genre buckets
    for genre, keywords in genre_map.items():
        if any(kw in tag_lower for kw in keywords):
            return genre

    # Default if no matches
    return "Unknown"


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
            # Preview URLs are signed and expire in ~15 min, so only the track id is
            # cached; /api/preview resolves a fresh URL at play time (BUG-10).
            "top_tracks": [
                {
                    "name": t.get("title"),
                    "artist": t.get("artist", {}).get("name"),
                    "deezer_id": t.get("id"),
                    "album_art": t.get("album", {}).get("cover_big"),
                }
                for t in tracks_data.get("data", [])[:10]
            ],
        }
    except Exception as e:
        return {"error": str(e)}


def strip_previews(tracks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop (possibly expired) preview URLs, e.g. from Deezer entries cached before BUG-10."""
    return [{k: v for k, v in t.items() if k != "preview_url"} for t in tracks or []]


def get_similar(artist_name: str):
    """
    Similar artists for `artist_name`, from the 90-day cache or Last.fm.
    Returns [] if Last.fm has none, None on a transient failure (not cached).
    """
    similar = get_cached_similar_artists(artist_name)
    if similar is not None:
        return similar
    similar = get_similar_artists(artist_name, limit=20, threshold=0.05)
    if similar is not None:
        set_cached_similar_artists(artist_name, similar)
    return similar


def get_deezer_info(artist_name: str) -> Dict[str, Any]:
    """Deezer image/fans/top tracks from the cache or the API; {} on failure."""
    info = get_cached_deezer_info(artist_name)
    if info is None:
        info = fetch_deezer_artist_info(artist_name)
        if info and "error" not in info:
            set_cached_deezer_info(artist_name, info)
    if not info or "error" in info:
        return {}
    return {**info, "top_tracks": strip_previews(info.get("top_tracks"))}


def fetch_seed_artist_metadata(artist_name: str, lastfm_data: Dict, idx: int = 0, total: int = 0) -> Dict[str, Any]:
    """
    Fetch complete metadata for a seed artist.
    Combines Last.fm and Deezer data. Normalizes node schema with all required fields.
    Uses cache for similar artists to avoid redundant API calls.
    """
    # Get similar artists from Last.fm with progress message
    frames = ["-", "\\", "|", "/"]
    frame_idx = idx % len(frames)
    frame = frames[frame_idx]

    # Check if similar artists are cached (90-day TTL)
    similar = get_cached_similar_artists(artist_name)
    was_cached_similar = similar is not None

    if similar is None:
        # Not in cache, fetch from API
        if idx > 0 and total > 0:
            report(f"[{idx}/{total}] Gathering {artist_name} -{frame}*-{frame}* LOADING")
        similar = get_similar_artists(artist_name, limit=20, threshold=0.05)
        # Cache it for 90 days, but never cache a transient failure (None)
        if similar is not None:
            set_cached_similar_artists(artist_name, similar)
        similar = similar or []
    else:
        # Found in cache
        if idx > 0 and total > 0:
            report(f"[{idx}/{total}] Gathering {artist_name} - Cache ✓")

    # Rate limiting only for API calls (cached data doesn't need rate limiting)
    if not was_cached_similar:
        time.sleep(0.15)

    # Get Deezer data (cached, 90-day TTL)
    deezer_info = get_cached_deezer_info(artist_name)
    was_cached_deezer = deezer_info is not None

    if deezer_info is None:
        # Not in cache, fetch from API
        deezer_info = fetch_deezer_artist_info(artist_name)
        # Cache it for 90 days
        if deezer_info and "error" not in deezer_info:
            set_cached_deezer_info(artist_name, deezer_info)

    if not was_cached_deezer:
        time.sleep(0.1)

    # Derive genre from tags
    tags = lastfm_data.get("tags", [])
    genre = _derive_genre(tags)

    # Combine all data (prefer Deezer images over Last.fm)
    image_url = deezer_info.get("image_url") or lastfm_data.get("image_url")
    metadata = {
        "name": artist_name,
        "rank": lastfm_data.get("rank"),
        "listeners": lastfm_data.get("listeners", 0),
        "tags": tags,
        "image_url": image_url,
        "bio": lastfm_data.get("bio"),
        "similar_artists": similar,
        "top_tracks": strip_previews(deezer_info.get("top_tracks", [])),
        "deezer_fans": deezer_info.get("fans", 0),
        # Normalized fields for frontend
        "genre": genre,
        "lastfm_artists": [artist_name],
        "artist_profiles": [{
            "name": artist_name,
            "image_url": image_url,
            "bio": lastfm_data.get("bio")
        }],
        "stage": "",
        "day": "",
        "weekend": "",
        "seed": True,
        "expanded": False,
        "details_loaded": True,
    }

    return metadata


# Extrapolated RBO is 1.0 for identical lists of any length. The old truncated
# score topped out at 1 - p^10 = 0.65 for full 10-tag lists with a 0.21 cutoff;
# 0.21 / 0.65 ≈ 0.32 keeps the same bar for 10-tag artists while letting short
# identical lists (e.g. ['pop', 'dance']) connect (BUG-35).
RBO_EDGE_THRESHOLD = 0.32


def rbo_similarity(list1: List[str], list2: List[str], p: float = 0.9) -> float:
    """
    Extrapolated Rank-Biased Overlap (Webber, Moffat & Zobel 2010, eq. 32) between
    two ranked lists, possibly of different lengths. 1.0 for identical lists, 0.0 for
    disjoint ones, and 0.0 if either list is empty (no evidence of similarity, BUG-18).
    """
    if not list1 or not list2:
        return 0.0
    S, L = (list1, list2) if len(list1) <= len(list2) else (list2, list1)
    s, l = len(S), len(L)
    seen_s, seen_l = set(), set()
    overlap = 0       # X_d: |S[:d] ∩ L[:d]|, with S frozen once exhausted
    x_s = 0           # X_s: overlap at depth s
    total = 0.0
    for d in range(1, l + 1):
        l_item = L[d - 1]
        if d <= s:
            s_item = S[d - 1]
            if s_item == l_item:
                overlap += 1
            else:
                overlap += (s_item in seen_l) + (l_item in seen_s)
            seen_s.add(s_item)
            seen_l.add(l_item)
            if d == s:
                x_s = overlap
        else:
            overlap += l_item in seen_s
            seen_l.add(l_item)
            total += x_s * (d - s) / (s * d) * p ** d
        total += overlap / d * p ** d
    return (1 - p) / p * total + ((overlap - x_s) / l + x_s / s) * p ** l


SIMILAR_PER_SEED = 4
EXPAND_LIMIT = 6


def stub_node(name: str, parent: Dict[str, Any], match: float, known: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    A lightweight node for a similar artist. Full details (tags, bio, tracks) are
    loaded on demand by /api/artist. Genre is inherited from the parent until then;
    `known` is the user's own enrichment for that artist, if they listen to it.
    """
    known = known or {}
    tags = known.get("tags") or []
    return {
        "name": name,
        "seed": False,
        "expanded": False,
        "details_loaded": False,
        "parent": parent["name"],
        "match": match,
        "listeners": known.get("listeners", 0),
        "tags": tags,
        "genre": _derive_genre(tags) if tags else parent.get("genre", "Unknown"),
        "image_url": known.get("image_url"),
        "bio": known.get("bio"),
        "top_tracks": [],
    }


def _add_edge(edges, seen, a, b, **attrs):
    key = tuple(sorted((a, b)))
    if a == b or key in seen:
        return False
    seen.add(key)
    edges.append({"source": a, "target": b, **attrs})
    return True


def build_seed_graph(
    user_id: str,
    seed_artists: List[str],
    all_artists_metadata: Dict[str, Dict],
    similar_per_seed: int = SIMILAR_PER_SEED,
    user_artists: Dict[str, Dict] = None,
) -> Dict[str, Any]:
    """
    Build the initial graph: seed artists, edges between them (Gold Standard
    similar-artist overlap, then tag RBO), plus each seed's `similar_per_seed`
    strongest similar artists as lightweight nodes linked to every seed that
    lists them (BUG-17: the map used to be just the 5 isolated seeds).
    """
    report(f"Building graph with {len(seed_artists)} seed artists...")

    nodes = []
    node_map = {name: metadata for name, metadata in all_artists_metadata.items()}

    # Add seed artists as nodes
    for artist_name in seed_artists:
        if artist_name in node_map:
            nodes.append(node_map[artist_name])

    # Build edges using Gold Standard + RBO
    edges = []
    added_edges = set()

    report("  Building edges...")

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
            if rbo_score >= RBO_EDGE_THRESHOLD:
                edges.append({
                    "source": artist1,
                    "target": artist2,
                    "type": "tag_similarity",
                    "pass": 2,  # Base RBO
                    "weight": rbo_score,
                })
                added_edges.add(edge_key)

    # Similar artists as first-ring nodes
    present = {n["name"] for n in nodes}
    for seed in seed_artists:
        meta = node_map.get(seed)
        if not meta:
            continue
        added = 0
        for s in meta.get("similar_artists") or []:
            if added >= similar_per_seed:
                break
            if s["name"] in present:
                continue
            nodes.append(stub_node(s["name"], meta, s["match"], (user_artists or {}).get(s["name"])))
            present.add(s["name"])
            added += 1
    # Link every seed to each first-ring artist it lists as similar
    for seed in seed_artists:
        for s in node_map.get(seed, {}).get("similar_artists") or []:
            if s["name"] in present and s["name"] not in seed_artists:
                _add_edge(edges, added_edges, seed, s["name"], type="similar", weight=s["match"], **{"pass": 1})

    report(f"  {len(nodes)} nodes, {len(edges)} edges")

    return {
        "nodes": nodes,
        "edges": edges,
    }


class SimilarUnavailable(Exception):
    """Last.fm could not be reached; nothing was changed."""


def expand_map(user_map: Dict[str, Any], artist_name: str, limit: int = EXPAND_LIMIT) -> Dict[str, Any]:
    """
    Grow `user_map` in place from `artist_name` using Last.fm similar artists
    (works for Spotify and Last.fm users alike; replaces Spotify's retired
    recommendations endpoint, BUG-24). Adds up to `limit` new artists and links
    the parent to any listed artist already on the map.

    Returns {"added_nodes": [...], "added_edges": [...], "already_expanded": bool}.
    Raises KeyError if the artist isn't on the map, SimilarUnavailable on failure.
    """
    nodes = {n["name"]: n for n in user_map.setdefault("nodes", [])}
    edges = user_map.setdefault("edges", [])
    parent = nodes[artist_name]
    if parent.get("expanded"):
        return {"added_nodes": [], "added_edges": [], "already_expanded": True}

    similar = get_similar(artist_name)
    if similar is None:
        raise SimilarUnavailable(artist_name)

    seen = {tuple(sorted((e["source"], e["target"]))) for e in edges}
    added_nodes, added_edges = [], []
    for s in similar:
        name = s["name"]
        if name not in nodes:
            if len(added_nodes) >= limit:
                continue
            node = stub_node(name, parent, s["match"])
            nodes[name] = node
            user_map["nodes"].append(node)
            added_nodes.append(node)
        if _add_edge(edges, seen, artist_name, name, type="similar", weight=s["match"], **{"pass": 1}):
            added_edges.append(edges[-1])
    parent["expanded"] = True
    return {"added_nodes": added_nodes, "added_edges": added_edges, "already_expanded": False}


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

    report(f"Gathering related artists")

    # Fetch metadata for each seed artist
    all_artists_metadata = {}
    for idx, artist_name in enumerate(seed_artists, 1):
        lastfm_data = all_artists.get(artist_name, {})
        metadata = fetch_seed_artist_metadata(artist_name, lastfm_data, idx=idx, total=len(seed_artists))
        all_artists_metadata[artist_name] = metadata
        time.sleep(0.1)

    # Build graph
    graph = build_seed_graph(user_id, seed_artists, all_artists_metadata, user_artists=all_artists)

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
