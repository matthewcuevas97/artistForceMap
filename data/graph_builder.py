import json
import math
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
    return []


def normalize_listeners(nodes, scores):
    """
    Baseline score from Last.fm listeners, square-root scaled to [0, 1].

    Listener counts span 4 orders of magnitude, so a linear scale left 83/142 lineup
    nodes below 0.1 (labels hidden, tiny grey dots). sqrt leaves ~15 there while
    keeping headliners clearly bigger; log would flatten everything to 0.7-1.0 (UX-02).
    """
    max_listeners = max((node.get("listeners", 0) for node in nodes), default=0)
    for node in nodes:
        scores[node["name"]]["score"] = math.sqrt(node.get("listeners", 0) / max_listeners) if max_listeners else 0
    return scores


def _member_keys(node):
    """Normalised names a lineup node answers to: its display name plus its Last.fm members."""
    return {_norm(n) for n in [node["name"], *(node.get("lastfm_artists") or [])]}


def enrich_with_scores(nodes, top_artists, scores):
    """
    Overlay a user's top artists onto the per-node scores.

    Direct match: the user listens to the node's artist (by display name or any
    `lastfm_artists` member, e.g. one half of a B2B). The node's score becomes the
    best rank score among matching top artists.

    Derived match: for nodes with no direct match, a top artist that isn't on the
    lineup but appears in the node's `similar_artists` gives
    rank score * similarity * 0.6; the best one wins.

    Matching is by membership, never by `score > 0`.
    """
    top_lookup = {}
    for a in top_artists:
        key = _norm(a["name"])
        top_lookup[key] = max(top_lookup.get(key, 0), a["score"])

    node_keys = {node["name"]: _member_keys(node) for node in nodes}
    lineup_keys = set().union(*node_keys.values()) if node_keys else set()

    direct = set()
    for node in nodes:
        name = node["name"]
        hits = [top_lookup[k] for k in node_keys[name] if k in top_lookup]
        if hits:
            direct.add(name)
            scores[name]["direct_score"] = max(hits)
            scores[name]["score"] = max(hits)
        else:
            scores[name]["direct_score"] = 0

    off_lineup = [(k, sc) for k, sc in top_lookup.items() if k not in lineup_keys]
    if not off_lineup:
        return scores

    for node in nodes:
        name = node["name"]
        if name in direct:
            continue
        similar = {_norm(s["name"]): s["match"] for s in node.get("similar_artists") or []}
        derived = max((sc * similar[k] * 0.6 for k, sc in off_lineup if k in similar), default=0)
        if derived > 0:
            scores[name]["derived_score"] = max(scores[name]["derived_score"], derived)
            scores[name]["score"] = max(scores[name]["score"], derived)

    return scores
