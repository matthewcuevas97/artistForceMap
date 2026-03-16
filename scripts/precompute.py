import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from itertools import combinations

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.lineup import load_lineup
from lastfm.fetch import get_similar_artists, get_artist_info, get_artist_image_and_bio, get_artist_top_tags

# --- Constants ---
EDGE_CAP = 6
RBO_BASE_THRESHOLD = 0.21
RBO_FLOOR_THRESHOLD = 0.05
CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "lastfm_api_cache.json")

TAG_TO_GENRE = {
    # Electronic
    "electronic": "Electronic", "house": "Electronic", "techno": "Electronic",
    "deep house": "Electronic", "tech house": "Electronic", "electro": "Electronic",
    "ambient": "Electronic", "trance": "Electronic", "dubstep": "Electronic",
    "dance": "Electronic", "electronica": "Electronic", "minimal": "Electronic",
    "riddim": "Electronic", "midtempo bass": "Electronic",
    # Indie/Alt
    "indie": "Indie/Alt", "indie rock": "Indie/Alt", "alternative": "Indie/Alt",
    "post-punk": "Indie/Alt", "indie pop": "Indie/Alt", "shoegaze": "Indie/Alt",
    "dream pop": "Indie/Alt", "new wave": "Indie/Alt", "lo-fi": "Indie/Alt",
    "noise rock": "Indie/Alt", "grunge": "Indie/Alt",
    # Hip-Hop
    "hip-hop": "Hip-Hop", "rap": "Hip-Hop", "trap": "Hip-Hop", "hip hop": "Hip-Hop",
    "drill": "Hip-Hop", "grime": "Hip-Hop",
    # R&B/Soul
    "rnb": "R&B/Soul", "soul": "R&B/Soul", "neo-soul": "R&B/Soul",
    "alternative rnb": "R&B/Soul", "r&b": "R&B/Soul",
    # Pop
    "pop": "Pop", "electropop": "Pop", "dance-pop": "Pop", "k-pop": "Pop",
    "p-pop": "Pop", "hyperpop": "Pop", "latin pop": "Pop",
    # Punk/Metal
    "punk": "Punk/Metal", "hardcore": "Punk/Metal", "hardcore punk": "Punk/Metal",
    "punk rock": "Punk/Metal", "crossover": "Punk/Metal", "thrash metal": "Punk/Metal",
    "metalcore": "Punk/Metal", "emo": "Punk/Metal", "pop punk": "Punk/Metal",
    "post-hardcore": "Punk/Metal",
    # Latin/Afro
    "latin": "Latin/Afro", "reggaeton": "Latin/Afro", "afrobeats": "Latin/Afro",
    "dancehall": "Latin/Afro", "reggae": "Latin/Afro",
    # Singer-Songwriter/Jazz
    "singer-songwriter": "Singer-Songwriter/Jazz", "jazz": "Singer-Songwriter/Jazz",
    "folk": "Singer-Songwriter/Jazz", "indie folk": "Singer-Songwriter/Jazz",
}

# --- Caching Functions ---
def load_cache():
    if not os.path.exists(CACHE_PATH):
        return {"artist_info": {}, "artist_top_tags": {}, "similar_artists": {}}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"artist_info": {}, "artist_top_tags": {}, "similar_artists": {}}

def save_cache(cache):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)

# --- Core Logic ---
def rbo(list1, list2, p=0.9):
    # ... (implementation unchanged)
    if not list1 and not list2: return 1.0
    if not list1 or not list2: return 0.0
    sl, ll = set(), set()
    score = 0.0
    max_d = max(len(list1), len(list2))
    for d in range(1, max_d + 1):
        if d <= len(list1): sl.add(list1[d-1])
        if d <= len(list2): ll.add(list2[d-1])
        agreement = len(sl.intersection(ll)) / d
        score += (1 - p) * (p ** (d - 1)) * agreement
    return score

def build_graph_edges(nodes):
    # ... (implementation unchanged)
    print("\n--- Building Graph Edges ---")
    node_map = {n["name"]: n for n in nodes}
    degrees = defaultdict(int)
    accepted_edges = set()
    links = []

    def add_edge(n1_name, n2_name, source_pass):
        a, b = sorted((n1_name, n2_name))
        if a == b or (a, b) in accepted_edges: return False
        if degrees[a] < EDGE_CAP and degrees[b] < EDGE_CAP:
            accepted_edges.add((a, b))
            degrees[a] += 1
            degrees[b] += 1
            links.append({"source": a, "target": b, "pass": source_pass})
            return True
        return False

    # Pass 1: Gold Standard
    print("Edge Pass 1: Gold Standard")
    gold_standard_candidates = []
    for node in nodes:
        for similar in node.get("similar_artists", []):
            if similar["name"] in node_map:
                a, b = sorted((node["name"], similar["name"]))
                gold_standard_candidates.append((a, b))
    gold_standard_candidates.sort()
    for a, b in gold_standard_candidates: add_edge(a, b, 1)
    print(f"  > Edges after pass: {len(links)}")

    # Pass 2: Base RBO
    print("Edge Pass 2: Base RBO")
    rbo_candidates, rejected_rbo_edges = [], []
    for node1, node2 in combinations(nodes, 2):
        score = rbo(node1.get("tags", []), node2.get("tags", []))
        if score >= RBO_BASE_THRESHOLD:
            a, b = sorted((node1["name"], node2["name"]))
            rbo_candidates.append({"a": a, "b": b, "score": score})
    rbo_candidates.sort(key=lambda x: (-x["score"], x["a"], x["b"]))
    for edge in rbo_candidates:
        if not add_edge(edge["a"], edge["b"], 2): rejected_rbo_edges.append(edge)
    print(f"  > Edges after pass: {len(links)}")

    # Pass 3: Conditional Rewiring
    print("Edge Pass 3: Conditional Rewiring")
    rewired_orphans = set()
    for rejected in rejected_rbo_edges:
        n1, n2 = rejected["a"], rejected["b"]
        if n1 in rewired_orphans or n2 in rewired_orphans: continue
        n1_under_cap, n2_under_cap = degrees[n1] < EDGE_CAP, degrees[n2] < EDGE_CAP
        if n1_under_cap and not n2_under_cap: orphan, capped = n1, n2
        elif not n1_under_cap and n2_under_cap: orphan, capped = n2, n1
        else: continue
        capped_neighbors = [target if source == capped else source for source, target in accepted_edges if source == capped or target == capped]
        neighbor_scores = []
        for neighbor_name in capped_neighbors:
            if neighbor_name == orphan: continue
            neighbor_node, orphan_node = node_map[neighbor_name], node_map[orphan]
            score = rbo(orphan_node.get("tags", []), neighbor_node.get("tags", []))
            if score > 0: neighbor_scores.append({"name": neighbor_name, "score": score})
        neighbor_scores.sort(key=lambda x: (-x["score"], x["name"]))
        for best_neighbor in neighbor_scores:
            if add_edge(orphan, best_neighbor["name"], 3):
                rewired_orphans.add(orphan)
                break
    print(f"  > Edges after pass: {len(links)}")

    # Pass 4: Adaptive Floor
    print("Edge Pass 4: Adaptive Floor")
    zero_degree_nodes = [n for n in nodes if degrees[n["name"]] == 0]
    for node in zero_degree_nodes:
        best_candidate, highest_score = None, -1
        for other_node in nodes:
            if node["name"] == other_node["name"] or degrees[other_node["name"]] >= EDGE_CAP: continue
            score = rbo(node.get("tags", []), other_node.get("tags", []))
            if score > highest_score:
                highest_score, best_candidate = score, other_node["name"]
        if highest_score >= RBO_FLOOR_THRESHOLD: add_edge(node["name"], best_candidate, 4)
    print(f"  > Edges after pass: {len(links)}")

    # Pass 5: Hail Mary
    print("Edge Pass 5: Hail Mary")
    nodes_by_listeners = sorted(nodes, key=lambda x: x.get("listeners", 0), reverse=True)
    still_zero_degree_nodes = [n for n in nodes if degrees[n["name"]] == 0]
    for node in still_zero_degree_nodes:
        if not node.get("genre") or node["genre"] == "Unknown": continue
        for candidate in nodes_by_listeners:
            if node["name"] == candidate["name"]: continue
            if candidate.get("genre") == node["genre"] and add_edge(node["name"], candidate["name"], 5):
                break
    print(f"  > Edges after pass: {len(links)}")
    return links

def slim_node(node):
    # ... (implementation unchanged)
    keep_fields = {"name", "genre", "listeners", "day", "weekend", "stage", "image_url", "bio", "lastfm_artists", "artist_profiles"}
    slimmed_node = {k: node.get(k) for k in keep_fields}
    slimmed_node["tags"] = (node.get("tags") or [])[:3]
    slimmed_node["top_tracks"] = [
        {k: v for k, v in t.items() if k != "preview_url"}
        for t in node.get("top_tracks", [])
    ]
    return slimmed_node

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-cache", action="store_true", help="Bypass the API cache and fetch fresh data.")
    args = parser.parse_args()

    use_cache = not args.no_cache
    cache = load_cache() if use_cache else {"artist_info": {}, "artist_top_tags": {}, "similar_artists": {}}

    lineup = load_lineup()
    total = len(lineup)
    nodes = [{"name": a["name"], "day": a["day"], "weekend": a["weekend"], "stage": a["stage"], "lastfm_artists": a.get("lastfm_artists", [])} for a in lineup]
    node_map = {n["name"]: n for n in nodes}

    # Pass 1: Fetch artist info
    print("--- Pass 1: Fetching Artist Info ---")
    for i, artist in enumerate(lineup, 1):
        print(f"Processing {i}/{total}: {artist['name']}")
        node = node_map[artist["name"]]
        lastfm_names = artist.get("lastfm_artists", [])
        if not lastfm_names:
            node.update({"tags": [], "listeners": 0, "genre": "Unknown", "similar_artists": []})
            continue

        max_listeners = 0
        all_tags, seen_tags = [], set()
        for lastfm_name in lastfm_names:
            # Get artist info (listeners)
            info = cache["artist_info"].get(lastfm_name)
            if not info:
                print(f"  > Fetching info for '{lastfm_name}'...")
                info = get_artist_info(lastfm_name)
                cache["artist_info"][lastfm_name] = info
                time.sleep(0.25)
            if info and info.get("listeners", 0) > max_listeners:
                max_listeners = info["listeners"]

            # Get artist top tags
            tags = cache["artist_top_tags"].get(lastfm_name)
            if not tags:
                print(f"  > Fetching tags for '{lastfm_name}'...")
                tags = get_artist_top_tags(lastfm_name, limit=10)
                cache["artist_top_tags"][lastfm_name] = tags
                time.sleep(0.25)
            
            for tag in (tags or []):
                if tag not in seen_tags:
                    seen_tags.add(tag)
                    all_tags.append(tag)

        node["tags"] = all_tags
        node["listeners"] = max_listeners
        node["genre"] = next((TAG_TO_GENRE[t] for t in all_tags if t in TAG_TO_GENRE), "Unknown")

    # Pass 2: Fetch similar artists
    print("\n--- Pass 2: Fetching Similar Artists ---")
    for i, artist in enumerate(lineup, 1):
        print(f"Processing {i}/{total}: {artist['name']}")
        node = node_map[artist["name"]]
        lastfm_names = artist.get("lastfm_artists", [])
        if not lastfm_names:
            node["similar_artists"] = []
            continue

        combined = {}
        for lastfm_name in lastfm_names:
            similar = cache["similar_artists"].get(lastfm_name)
            if not similar:
                print(f"  > Fetching similar for '{lastfm_name}'...")
                similar = get_similar_artists(lastfm_name, limit=50, threshold=0.05)
                cache["similar_artists"][lastfm_name] = similar
                time.sleep(0.25)

            for s in (similar or []):
                if s["name"] not in combined or s["match"] > combined[s["name"]]:
                    combined[s["name"]] = s["match"]
        node["similar_artists"] = [{"name": name, "match": match} for name, match in combined.items()]

    if use_cache:
        print("\nSaving API data to cache...")
        save_cache(cache)

    links = build_graph_edges(nodes)

    for node in nodes:
        if "image_url" not in node: node["image_url"] = None
        if "bio" not in node: node["bio"] = None
        if "top_tracks" not in node: node["top_tracks"] = []

    slimmed_nodes = [slim_node(n) for n in nodes]
    graph = {"nodes": slimmed_nodes, "links": links}
    
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "graph_static.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)

    print(f"\nSaved to data/graph_static.json. Total nodes: {len(slimmed_nodes)}, Total links: {len(links)}")

if __name__ == "__main__":
    main()
