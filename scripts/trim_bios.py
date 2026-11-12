"""
Trim bios in data/graph_static.json that were hard-cut at 300 characters (UX-03).

lastfm.fetch used to store `summary[:300]`, so most bios end mid-word. The full text
isn't stored, so each cut bio is shortened to its last complete sentence (or last whole
word + "…") with lastfm.fetch.trim_bio. Bios shorter than the old cut are untouched.
No network.

Usage:
    python scripts/trim_bios.py            # write in place
    python scripts/trim_bios.py --check    # exit 1 if any bio still looks hard-cut
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from lastfm.fetch import BIO_LIMIT, trim_bio  # noqa: E402

GRAPH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "graph_static.json")


def _fix(bio):
    # A bio of exactly BIO_LIMIT chars was produced by the old summary[:300] cut.
    if isinstance(bio, str) and len(bio) >= BIO_LIMIT:
        return trim_bio(bio, BIO_LIMIT - 1)
    return bio


def migrate(graph):
    changed = 0
    for node in graph["nodes"]:
        for holder in [node, *(node.get("artist_profiles") or [])]:
            new = _fix(holder.get("bio"))
            if new != holder.get("bio"):
                holder["bio"] = new
                changed += 1
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    with open(GRAPH, encoding="utf-8") as f:
        graph = json.load(f)
    changed = migrate(graph)
    print(f"{changed} bio(s) {'need trimming' if args.check else 'trimmed'}")
    if args.check:
        return 1 if changed else 0
    if changed:
        tmp = GRAPH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(graph, f, indent=2)
        os.replace(tmp, GRAPH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
