import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.lineup import load_lineup
from lastfm.fetch import get_similar_artists, get_artist_info

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


def main():
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


if __name__ == "__main__":
    main()
