"""
Build data/graph_slim.json from data/graph_static.json.

Slim nodes strip fields not needed by the frontend.
Edges are precomputed at 5 thresholds so app.py can serve them with
a simple dict lookup instead of building them per request.
"""

import json
import os
import sys

# Allow imports from project root when run as a script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.graph_builder import build_edges, load_static_graph

THRESHOLDS = [0.05, 0.10, 0.20, 0.30, 0.50]

KEEP_FIELDS = {"name", "genre", "listeners", "day", "weekend", "stage", "image_url", "bio", "top_tracks"}


def slim_node(node):
    out = {k: node[k] for k in KEEP_FIELDS if k in node}
    out["tags"] = (node.get("tags") or [])[:3]
    out["top_tracks"] = [
        {k: v for k, v in t.items() if k != "preview_url"}
        for t in node.get("top_tracks", [])
    ]
    return out


def build_deduped_edges(full_nodes, threshold):
    raw = build_edges(full_nodes, threshold)
    seen = set()
    deduped = []
    for e in raw:
        key = (min(e["source"], e["target"]), max(e["source"], e["target"]))
        if key not in seen:
            seen.add(key)
            deduped.append(e)
    return deduped


def main():
    full_nodes = load_static_graph()

    slim_nodes = [slim_node(n) for n in full_nodes]

    edges = {}
    for t in THRESHOLDS:
        key = f"{t:.2f}"
        edge_list = build_deduped_edges(full_nodes, t)
        edges[key] = edge_list
        print(f"Building edges at threshold {key} — {len(edge_list)} edges")

    slim = {"nodes": slim_nodes, "edges": edges}

    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "graph_slim.json")
    out_path = os.path.normpath(out_path)
    with open(out_path, "w") as f:
        json.dump(slim, f, separators=(",", ":"))

    static_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "data", "graph_static.json")
    )
    static_size = os.path.getsize(static_path)
    slim_size   = os.path.getsize(out_path)

    print(f"\ngraph_static.json : {static_size:,} bytes")
    print(f"graph_slim.json   : {slim_size:,} bytes")
    print(f"Reduction         : {100 * (1 - slim_size / static_size):.1f}%")


if __name__ == "__main__":
    main()
