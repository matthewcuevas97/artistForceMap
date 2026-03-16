"""
Build data/graph_slim.json from data/graph_static.json.

Slim nodes strip fields not needed by the frontend.
Edges are read from the new edges_by_level structure and transformed to slim format.
"""

import json
import os
import sys

# Allow imports from project root when run as a script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

THRESHOLD_LEVELS = [0.30, 0.32, 0.34, 0.36, 0.38, 0.40]

KEEP_FIELDS = {"name", "genre", "listeners", "day", "weekend", "stage", "image_url", "bio", "top_tracks"}


def slim_node(node):
    out = {k: node[k] for k in KEEP_FIELDS if k in node}
    out["tags"] = (node.get("tags") or [])[:3]
    out["top_tracks"] = [
        {k: v for k, v in t.items() if k != "preview_url"}
        for t in node.get("top_tracks", [])
    ]
    return out


def load_static_graph():
    """Load graph_static.json with edges_by_level structure."""
    path = os.path.join(os.path.dirname(__file__), "..", "data", "graph_static.json")
    with open(path) as f:
        data = json.load(f)
    return data["nodes"], data.get("edges_by_level", {})


def main():
    print("Loading graph_static.json with edges_by_level structure...")
    full_nodes, edges_by_level_raw = load_static_graph()

    slim_nodes = [slim_node(n) for n in full_nodes]

    # Transform edges_by_level to slim format
    print(f"Transforming edges to slim format...")
    edges_by_level = {}
    for level_key, raw_edges in edges_by_level_raw.items():
        edges_by_level[level_key] = [
            {"source": e["source"], "target": e["target"], "weight": 1.0, "type": "similarity"}
            for e in raw_edges
        ]

    for level_key, edges in edges_by_level.items():
        print(f"  Level {level_key}: {len(edges)} edges")

    slim = {"nodes": slim_nodes, "edges_by_level": edges_by_level}

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
