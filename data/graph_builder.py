import json
import os
from collections import defaultdict

GENRE_OVERRIDES = {
    "HUGEL": "Electronic",
    "Youna": "Electronic",
    "¥ØU$UK€ ¥UK1MAT$U": "Electronic",
    "Los Hermanos Flores": "Latin/Afro",
}
'''
These artists either had no presence or genre data on lastfm
'''

def load_static_graph():
    path = os.path.join(os.path.dirname(__file__), "graph_static.json")
    with open(path) as f:
        data = json.load(f)
    nodes = data["nodes"]
    for node in nodes:
        if node["name"] in GENRE_OVERRIDES:
            node["genre"] = GENRE_OVERRIDES[node["name"]]
    return nodes


def build_edges(nodes, threshold=0.1):
    # Precompute per-node: direct match lookup and similar-name set
    node_map = {node["name"]: node for node in nodes}

    similar_lookup = {}   # name -> {similar_name: match}
    similar_names = {}    # name -> frozenset of similar artist names
    for node in nodes:
        name = node["name"]
        lookup = {s["name"]: s["match"] for s in node.get("similar_artists", [])}
        similar_lookup[name] = lookup
        similar_names[name] = frozenset(lookup.keys())

    edges = []
    node_list = list(node_map.keys())

    for i, a in enumerate(node_list):
        for b in node_list[i + 1:]:
            # 1. Direct match: max of A->B and B->A
            direct = max(
                similar_lookup[a].get(b, 0.0),
                similar_lookup[b].get(a, 0.0),
            )

            # 2. Jaccard similarity over similar-artist name sets
            sa, sb = similar_names[a], similar_names[b]
            union_size = len(sa | sb)
            jaccard = len(sa & sb) / union_size if union_size else 0.0

            weight = max(direct, jaccard)
            if weight < threshold:
                continue

            edges.append({
                "source": a,
                "target": b,
                "weight": weight,
                "type": "similarity",
            })

    return edges


def build_genre_edges(nodes):
    # Group by genre
    genre_groups = defaultdict(list)
    for node in nodes:
        genre = node.get("genre", "Unknown")
        if genre != "Unknown":
            genre_groups[genre].append(node)

    seen = set()
    edges = []

    for genre, group in genre_groups.items():
        sorted_group = sorted(group, key=lambda n: n.get("listeners", 0), reverse=True)

        # Small genre: fully connect every pair
        if len(sorted_group) <= 3:
            for i, a in enumerate(sorted_group):
                for b in sorted_group[i + 1:]:
                    key = tuple(sorted([a["name"], b["name"]]))
                    if key not in seen:
                        seen.add(key)
                        edges.append({
                            "source": a["name"],
                            "target": b["name"],
                            "weight": 0.15,
                            "type": "genre",
                        })
            continue

        anchor_names = [n["name"] for n in sorted_group[:3]]

        for node in sorted_group:
            if node["name"] in anchor_names:
                continue
            for anchor_name in anchor_names[:2]:
                key = tuple(sorted([node["name"], anchor_name]))
                if key not in seen:
                    seen.add(key)
                    edges.append({
                        "source": node["name"],
                        "target": anchor_name,
                        "weight": 0.15,
                        "type": "genre",
                    })

        # Fully connect the 3 anchors to each other
        for i, a in enumerate(anchor_names):
            for b in anchor_names[i + 1:]:
                key = tuple(sorted([a, b]))
                if key not in seen:
                    seen.add(key)
                    edges.append({
                        "source": a,
                        "target": b,
                        "weight": 0.15,
                        "type": "genre",
                    })

    return edges


def normalize_listeners(nodes):
    max_listeners = max((node.get("listeners", 0) for node in nodes), default=0)
    for node in nodes:
        node["score"] = node.get("listeners", 0) / max_listeners if max_listeners else 0
    return nodes


def enrich_with_spotify(nodes, top_artists):
    top_lookup = {a["name"].lower(): a["score"] for a in top_artists}

    for node in nodes:
        key = node["name"].lower()
        if key in top_lookup:
            node["direct_score"] = top_lookup[key]
            node["score"] = top_lookup[key]
        else:
            node["direct_score"] = 0
            node.setdefault("score", 0)
            node.setdefault("derived_score", 0)

    for artist in top_artists:
        artist_key = artist["name"].lower()
        directly_matched = any(
            node["name"].lower() == artist_key for node in nodes
        )
        if directly_matched:
            continue
        for node in nodes:
            if node["direct_score"] > 0:
                continue
            for similar in node.get("similar_artists", []):
                if similar["name"].lower() == artist_key:
                    derived = artist["score"] * similar["match"] * 0.6
                    node["derived_score"] = max(node.get("derived_score", 0), derived)
                    node["score"] = max(node.get("score", 0), node["derived_score"])
                    break

    return nodes
