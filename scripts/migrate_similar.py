"""
Merge `similar_artists` into data/graph_static.json from the Last.fm API cache.

Why: precompute.py's slim_node() used to drop `similar_artists`, so the derived
("you'd like this because you listen to X") scoring in data/graph_builder.py never
fired in production (BUG-04). Rerunning precompute.py would wipe images, bios and
top tracks (BUG-34), so this patches the existing file in place instead.

Uses only data/lastfm_api_cache.json — no network. Multi-artist nodes (B2Bs,
"A x B") take the max `match` per similar artist across their members, matching
precompute.py's Pass 2. Lineup members with no cached entry are reported and get
an empty list.

Usage:
    python scripts/migrate_similar.py            # write in place
    python scripts/migrate_similar.py --check    # report only, exit 1 if changes are needed
"""

import argparse
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
GRAPH = os.path.join(ROOT, "data", "graph_static.json")
API_CACHE = os.path.join(ROOT, "data", "lastfm_api_cache.json")


def combined_similar(members, similar_cache):
    combined = {}
    for member in members:
        for s in similar_cache.get(member) or []:
            if s["name"] not in combined or s["match"] > combined[s["name"]]:
                combined[s["name"]] = s["match"]
    return [{"name": n, "match": m} for n, m in sorted(combined.items(), key=lambda kv: -kv[1])]


def migrate(graph, similar_cache):
    """Set node["similar_artists"] on every node. Returns (changed_count, missing_members)."""
    changed, missing = 0, []
    for node in graph["nodes"]:
        members = node.get("lastfm_artists") or [node["name"]]
        missing += [m for m in members if m not in similar_cache]
        new = combined_similar(members, similar_cache)
        if node.get("similar_artists") != new:
            node["similar_artists"] = new
            changed += 1
    return changed, missing


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="don't write; exit 1 if the graph is out of date")
    args = ap.parse_args(argv)

    with open(GRAPH, encoding="utf-8") as f:
        graph = json.load(f)
    with open(API_CACHE, encoding="utf-8") as f:
        similar_cache = json.load(f)["similar_artists"]

    changed, missing = migrate(graph, similar_cache)
    with_similar = sum(1 for n in graph["nodes"] if n["similar_artists"])
    print(f"{changed} node(s) updated; {with_similar}/{len(graph['nodes'])} have similar artists")
    if missing:
        print(f"no cached similar artists for: {', '.join(sorted(set(missing)))}")

    if args.check:
        return 1 if changed else 0
    if changed:
        tmp = GRAPH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(graph, f, indent=2)  # same format as precompute.py writes
        os.replace(tmp, GRAPH)
        print(f"wrote {os.path.relpath(GRAPH, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
