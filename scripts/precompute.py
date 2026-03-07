import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.lineup import load_lineup
from lastfm.fetch import get_similar_artists, get_artist_info, get_artist_image_and_bio

TAG_TO_GENRE = {
    # Electronic
    "electronic": "Electronic",
    "house": "Electronic",
    "techno": "Electronic",
    "deep house": "Electronic",
    "tech house": "Electronic",
    "electro": "Electronic",
    "ambient": "Electronic",
    "trance": "Electronic",
    "dubstep": "Electronic",
    "dance": "Electronic",
    "electronica": "Electronic",
    "minimal": "Electronic",
    "riddim": "Electronic",
    "midtempo bass": "Electronic",
    # Indie/Alt
    "indie": "Indie/Alt",
    "indie rock": "Indie/Alt",
    "alternative": "Indie/Alt",
    "post-punk": "Indie/Alt",
    "indie pop": "Indie/Alt",
    "shoegaze": "Indie/Alt",
    "dream pop": "Indie/Alt",
    "new wave": "Indie/Alt",
    "lo-fi": "Indie/Alt",
    "noise rock": "Indie/Alt",
    "grunge": "Indie/Alt",
    # Hip-Hop
    "hip-hop": "Hip-Hop",
    "rap": "Hip-Hop",
    "trap": "Hip-Hop",
    "hip hop": "Hip-Hop",
    "drill": "Hip-Hop",
    "grime": "Hip-Hop",
    # R&B/Soul
    "rnb": "R&B/Soul",
    "soul": "R&B/Soul",
    "neo-soul": "R&B/Soul",
    "alternative rnb": "R&B/Soul",
    "r&b": "R&B/Soul",
    # Pop
    "pop": "Pop",
    "electropop": "Pop",
    "dance-pop": "Pop",
    "k-pop": "Pop",
    "p-pop": "Pop",
    "hyperpop": "Pop",
    "latin pop": "Pop",
    # Punk/Metal
    "punk": "Punk/Metal",
    "hardcore": "Punk/Metal",
    "hardcore punk": "Punk/Metal",
    "punk rock": "Punk/Metal",
    "crossover": "Punk/Metal",
    "thrash metal": "Punk/Metal",
    "metalcore": "Punk/Metal",
    "emo": "Punk/Metal",
    "pop punk": "Punk/Metal",
    "post-hardcore": "Punk/Metal",
    # Latin/Afro
    "latin": "Latin/Afro",
    "reggaeton": "Latin/Afro",
    "afrobeats": "Latin/Afro",
    "dancehall": "Latin/Afro",
    "reggae": "Latin/Afro",
    # Singer-Songwriter/Jazz
    "singer-songwriter": "Singer-Songwriter/Jazz",
    "jazz": "Singer-Songwriter/Jazz",
    "folk": "Singer-Songwriter/Jazz",
    "indie folk": "Singer-Songwriter/Jazz",
}


DEEZER_SEARCH_URL = "https://api.deezer.com/search"
DEEZER_ARTIST_SEARCH_URL = "https://api.deezer.com/search/artist"
LASTFM_PLACEHOLDER_HASH = "2a96cbd8b46e442fc41c2b86b821562f"

DEEZER_NAME_OVERRIDES = {
    "DJ Snake's Pardon My French": "DJ Snake",
    "Armin van Buuren x Adam Beyer": "Armin van Buuren",
    "Carlita x Josh Baker": "Carlita",
    "Chloé Caillet x Rossi.": "Chloé Caillet",
    "Green Velvet x AYYBO": "Green Velvet",
    "Max Dean x Luke Dean": "Max Dean",
    "Groove Armada (DJ Set)": "Groove Armada",
    "Röyksopp (DJ Set)": "Röyksopp",
    "Worship (Sub Focus, Dimension, Culture Shock, 1991)": "Sub Focus",
    "Sara Landry's Blood Oath": "Sara Landry",
    "¥ØU$UK€ ¥UK1MAT$U": "Yousuke Yukimatsu",
}


def _normalize(s):
    return re.sub(r'[^\w\s]', '', s.lower()).strip()


def _artist_matches(deezer_name, lastfm_name):
    return _normalize(deezer_name) == _normalize(lastfm_name)


def _is_close_match(query, result_name):
    q = _normalize(query)
    r = _normalize(result_name)
    return q == r or q in r or r in q


def fetch_deezer_artist_image(artist_name):
    """Search Deezer for an artist image. Returns picture_medium URL or None."""
    query = DEEZER_NAME_OVERRIDES.get(artist_name, artist_name)
    try:
        resp = requests.get(
            DEEZER_ARTIST_SEARCH_URL,
            params={"q": query, "limit": 5},
            timeout=10,
        )
        results = resp.json().get("data", [])
        for result in results:
            if _is_close_match(query, result.get("name", "")):
                return result.get("picture_medium")
    except Exception as e:
        print(f"  Deezer image error for '{artist_name}': {e}")
    return None


def run_pass4():
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "graph_static.json")
    with open(out_path, "r", encoding="utf-8") as f:
        graph = json.load(f)

    nodes = graph["nodes"]
    total = len(nodes)
    updated = 0
    not_found = []

    for i, node in enumerate(nodes, 1):
        name = node["name"]
        image_url = node.get("image_url") or ""
        if LASTFM_PLACEHOLDER_HASH not in image_url:
            print(f"Pass 4: {i}/{total} — {name} (skipped, already has image)")
            continue

        print(f"Pass 4: {i}/{total} — {name} (fetching from Deezer...)")
        new_url = fetch_deezer_artist_image(name)
        time.sleep(0.3)

        if new_url:
            node["image_url"] = new_url
            updated += 1
            print(f"  → Updated image")
        else:
            not_found.append(name)
            print(f"  → Not found")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)

    print("\nPass 4 complete.")
    print(f"  Total nodes processed : {total}")
    print(f"  Images updated        : {updated}")
    print(f"  Images not found      : {len(not_found)}")
    if not_found:
        print("  Not-found artists:")
        for n in not_found:
            print(f"    - {n}")


def fetch_deezer_top_tracks(artist_name, lastfm_names=None):
    """Fetch top 5 tracks for an artist from Deezer. Returns list of track dicts."""
    names_to_try = [DEEZER_NAME_OVERRIDES.get(artist_name, artist_name)]
    if lastfm_names:
        for n in lastfm_names:
            if n not in names_to_try:
                names_to_try.append(n)

    for query in names_to_try:
        try:
            resp = requests.get(
                DEEZER_ARTIST_SEARCH_URL,
                params={"q": query, "limit": 1},
                timeout=10,
            )
            results = resp.json().get("data", [])
            if not results:
                continue
            artist_id = results[0]["id"]

            resp2 = requests.get(
                f"https://api.deezer.com/artist/{artist_id}/top",
                params={"limit": 5},
                timeout=10,
            )
            tracks = resp2.json().get("data", [])
            if tracks:
                return [
                    {
                        "name": t["title"],
                        "deezer_url": t.get("link") or "",
                        "album_art": t.get("album", {}).get("cover_small") or "",
                    }
                    for t in tracks
                ]
        except Exception as e:
            print(f"  Deezer top-tracks error for '{query}': {e}")

    return []


def run_tracks_only():
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "graph_static.json")
    with open(out_path, "r", encoding="utf-8") as f:
        graph = json.load(f)

    nodes = graph["nodes"]
    total = len(nodes)

    for i, node in enumerate(nodes, 1):
        name = node["name"]
        tracks = fetch_deezer_top_tracks(name, lastfm_names=node.get("lastfm_artists"))
        node["top_tracks"] = tracks
        print(f"Tracks: {i}/{total} — {name} — {len(tracks)} tracks found")
        time.sleep(0.5)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)
    print("Saved to data/graph_static.json")

    build_slim_path = os.path.join(os.path.dirname(__file__), "build_slim.py")
    os.system(f"{sys.executable} {build_slim_path}")


def run_pass3():
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "graph_static.json")
    with open(out_path, "r", encoding="utf-8") as f:
        graph = json.load(f)

    nodes = graph["nodes"]
    total = len(nodes)

    for i, node in enumerate(nodes, 1):
        name = node["name"]
        print(f"Pass 3: {i}/{total} — {name}")

        lastfm_names = node.get("lastfm_artists", [])
        lookup_name = lastfm_names[0] if lastfm_names else None

        if not lookup_name:
            node["image_url"] = None
            node["bio"] = None
            node["top_tracks"] = []
            continue

        try:
            image_url, bio = get_artist_image_and_bio(lookup_name)
            node["image_url"] = image_url
            node["bio"] = bio
            time.sleep(0.3)

            tracks = fetch_deezer_top_tracks(name)
            time.sleep(0.5)
            node["top_tracks"] = tracks

        except Exception as e:
            print(f"  Error processing '{name}': {e}")
            node["image_url"] = None
            node["bio"] = None
            node["top_tracks"] = []

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)
    print("Pass 3 complete. Saved to data/graph_static.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pass3-only", action="store_true", help="Skip passes 1 and 2, only run pass 3")
    parser.add_argument("--pass4-only", action="store_true", help="Skip passes 1-3, only run pass 4")
    parser.add_argument("--tracks-only", action="store_true", help="Re-fetch only top_tracks from Deezer and rebuild slim graph")
    args = parser.parse_args()

    if args.tracks_only:
        run_tracks_only()
        return

    if args.pass4_only:
        run_pass4()
        return

    if args.pass3_only:
        run_pass3()
        return

    lineup = load_lineup()
    total = len(lineup)

    nodes = [
        {
            "name": a["name"],
            "day": a["day"],
            "weekend": a["weekend"],
            "stage": a["stage"],
            "lastfm_artists": a.get("lastfm_artists", []),
        }
        for a in lineup
    ]
    node_map = {n["name"]: n for n in nodes}

    # Pass 1: fetch artist info (tags, listeners, genre)
    print("Pass 1: fetching artist info...")
    for i, artist in enumerate(lineup, 1):
        print(f"Processing {i}/{total}: {artist['name']}")
        node = node_map[artist["name"]]
        lastfm_names = artist.get("lastfm_artists", [])

        if not lastfm_names:
            node["tags"] = []
            node["listeners"] = 0
            node["genre"] = "Unknown"
            continue

        all_tags: list = []
        seen_tags: set = set()
        max_listeners = 0

        for lastfm_name in lastfm_names:
            info = get_artist_info(lastfm_name)
            if info:
                if info["listeners"] > max_listeners:
                    max_listeners = info["listeners"]
                for tag in info["tags"]:
                    if tag not in seen_tags:
                        seen_tags.add(tag)
                        all_tags.append(tag)
            time.sleep(0.25)

        node["tags"] = all_tags
        node["listeners"] = max_listeners

        genre = "Unknown"
        for tag in all_tags:
            if tag in TAG_TO_GENRE:
                genre = TAG_TO_GENRE[tag]
                break
        node["genre"] = genre

    # Pass 2: fetch similar artists (unfiltered — all of them)
    print("\nPass 2: fetching similar artists...")
    all_similar_names: set = set()

    for i, artist in enumerate(lineup, 1):
        print(f"Processing {i}/{total}: {artist['name']}")
        node = node_map[artist["name"]]
        lastfm_names = artist.get("lastfm_artists", [])

        if not lastfm_names:
            node["similar_artists"] = []
            continue

        combined: dict = {}
        for lastfm_name in lastfm_names:
            for s in get_similar_artists(lastfm_name, limit=50, threshold=0.05):
                if s["name"] not in combined or s["match"] > combined[s["name"]]:
                    combined[s["name"]] = s["match"]
            time.sleep(0.25)

        node["similar_artists"] = [
            {"name": name, "match": match} for name, match in combined.items()
        ]
        all_similar_names.update(combined.keys())

    # Genre summary
    genre_counts: dict = defaultdict(int)
    for node in nodes:
        genre_counts[node["genre"]] += 1
    print("\nGenre summary:")
    for genre, count in sorted(genre_counts.items()):
        print(f"  {genre}: {count}")

    print(f"\nUnique similar artists stored: {len(all_similar_names)}")

    graph = {"nodes": nodes}

    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "graph_static.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)

    print("Saved to data/graph_static.json")

    run_pass3()
    run_pass4()


if __name__ == "__main__":
    main()
