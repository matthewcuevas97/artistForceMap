import json
import os
import re
from collections import defaultdict


def _norm(s):
    return re.sub(r'[^\w]', '', s.lower())

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


def normalize_listeners(nodes, scores):
    max_listeners = max((node.get("listeners", 0) for node in nodes), default=0)
    for node in nodes:
        scores[node["name"]]["score"] = node.get("listeners", 0) / max_listeners if max_listeners else 0
    return scores


def enrich_with_scores(nodes, top_artists, scores):
    top_lookup = {_norm(a["name"]): a["score"] for a in top_artists}

    node_norm = {node["name"]: _norm(node["name"]) for node in nodes}
    similar_lookup = {
        node["name"]: {_norm(s["name"]): s["match"] for s in node.get("similar_artists", [])}
        for node in nodes
    }
    normed_node_names = set(node_norm.values())

    for node in nodes:
        name = node["name"]
        if node_norm[name] in top_lookup:
            scores[name]["direct_score"] = top_lookup[node_norm[name]]
            scores[name]["score"] = top_lookup[node_norm[name]]
        else:
            scores[name]["direct_score"] = 0

    for artist in top_artists:
        artist_key = _norm(artist["name"])
        if artist_key in normed_node_names:
            continue
        for node in nodes:
            name = node["name"]
            if scores[name]["direct_score"] > 0:
                continue
            match = similar_lookup[name].get(artist_key)
            if match is not None:
                derived = artist["score"] * match * 0.6
                scores[name]["derived_score"] = max(scores[name]["derived_score"], derived)
                scores[name]["score"] = max(scores[name]["score"], scores[name]["derived_score"])

    return scores
