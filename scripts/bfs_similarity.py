"""
bfs_similarity.py

Penalized Best-First Search over the Last.fm similarity graph to find
connections between isolated lineup artists and other lineup artists.

Isolated: a lineup artist whose similar_artists list (from graph_static.json)
contains zero other lineup artists after name normalization.

Algorithm:
  Each isolated artist gets a MaxHeap seeded from its L1 similar_artists.
  Heap entries: (priority, candidate_name, path_list, depth)
    priority = cumulative match product * DECAY^depth

  On each pop:
    - If candidate is a different lineup artist → record edge, stop.
    - If candidate already visited this run → push its children from cache
      (free, no API call), continue.
    - If priority < MIN_PRIORITY → stop (heap is sorted, rest is worse).
    - If depth >= MAX_DEPTH → skip.
    - If budget exhausted → stop.
    - Otherwise: cache lookup or API call, mark visited, push children.

Persistent state:
  data/similarity_cache.json  — Last.fm getSimilar results, 90-day TTL.
  data/bfs_frontier.json      — Saved heap state for still-isolated artists,
                                reloaded and merged on next run.
"""

import heapq
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lastfm.fetch import get_similar_artists as _api_fetch

# ── constants ──────────────────────────────────────────────────────────────────
DECAY            = 0.65
MIN_PRIORITY     = 0.03
MAX_DEPTH        = 3
GLOBAL_BUDGET    = 800
PER_ARTIST_BUDGET = 20
RATE_LIMIT_SLEEP = 0.25
CACHE_TTL_DAYS   = 90

# ── paths ──────────────────────────────────────────────────────────────────────
_ROOT          = os.path.join(os.path.dirname(__file__), "..")
GRAPH_PATH     = os.path.join(_ROOT, "data", "graph_static.json")
CACHE_PATH     = os.path.join(_ROOT, "data", "similarity_cache.json")
FRONTIER_PATH  = os.path.join(_ROOT, "data", "bfs_frontier.json")


# ── helpers ────────────────────────────────────────────────────────────────────

def _norm(s):
    return re.sub(r'[^\w]', '', s.lower())


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _expired(entry):
    try:
        fetched = datetime.fromisoformat(entry["fetched_at"])
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - fetched > timedelta(days=CACHE_TTL_DAYS)
    except Exception:
        return True


# ── cache I/O ──────────────────────────────────────────────────────────────────

def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def prepopulate_cache(nodes, cache):
    """Seed cache from graph_static.json similar_artists so lineup artists
    are immediately available as cache hits (no API calls needed for them)."""
    now = _now_iso()
    added = 0
    for node in nodes:
        norm = _norm(node["name"])
        if norm not in cache or _expired(cache[norm]):
            similar = node.get("similar_artists", [])
            if similar:
                cache[norm] = {"fetched_at": now, "similar": similar}
                added += 1
    return added


# ── frontier I/O ───────────────────────────────────────────────────────────────

def load_frontier():
    if os.path.exists(FRONTIER_PATH):
        with open(FRONTIER_PATH) as f:
            return json.load(f)
    return {}


def save_frontier(frontier):
    with open(FRONTIER_PATH, "w") as f:
        json.dump(frontier, f, indent=2, ensure_ascii=False)


# ── graph I/O ──────────────────────────────────────────────────────────────────

def load_graph():
    with open(GRAPH_PATH) as f:
        return json.load(f)


def save_graph(data):
    with open(GRAPH_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── heap helpers (MaxHeap via negated priority) ────────────────────────────────

def _push(heap, priority, name, path, depth):
    heapq.heappush(heap, (-priority, name, path, depth))


def _pop(heap):
    neg_pri, name, path, depth = heapq.heappop(heap)
    return -neg_pri, name, path, depth


# ── fetch with cache ───────────────────────────────────────────────────────────

def fetch_similar(name, cache, budget):
    """
    Returns (neighbors: list[dict], cache_hit: bool).
    budget is a one-element list used as a mutable int reference.
    Writes cache entry immediately on miss; saves full cache to disk.
    """
    norm = _norm(name)
    if norm in cache and not _expired(cache[norm]):
        return cache[norm]["similar"], True

    if budget[0] <= 0:
        return [], False

    neighbors = _api_fetch(name)
    budget[0] -= 1
    cache[norm] = {"fetched_at": _now_iso(), "similar": neighbors}
    save_cache(cache)          # persist immediately
    time.sleep(RATE_LIMIT_SLEEP)
    return neighbors, False


# ── search ─────────────────────────────────────────────────────────────────────

def search_artist(node, artist_norm, lineup_norm, cache, visited, budget, saved_frontier):
    """
    Run best-first search for one isolated artist.

    Returns:
      found: (path, target_name, weight, depth) or None
      pops:  int
      calls: int   (API calls made during this artist's search)
      remaining_heap: list of [priority, name, path, depth] for frontier save
    """
    budget_before = budget[0]

    # Seed heap from L1 similar_artists
    heap = []
    for s in node.get("similar_artists", []):
        pri = s["match"] * DECAY
        if pri >= MIN_PRIORITY:
            _push(heap, pri, s["name"], [s["name"]], 1)

    # Merge saved frontier (resume from previous run)
    for entry in saved_frontier:
        pri, name, path, depth = entry
        _push(heap, pri, name, path, depth)

    found        = None
    pops         = 0
    artist_misses = 0  # API calls (cache misses) for this artist only

    while heap:
        priority, candidate, path, depth = _pop(heap)
        pops += 1
        cand_norm = _norm(candidate)

        # ── lineup cross-bridge? ───────────────────────────────────────────────
        if cand_norm in lineup_norm and cand_norm != artist_norm:
            target_name = lineup_norm[cand_norm]
            weight = round(priority, 6)
            found = (path, target_name, weight, depth)
            break

        # ── already visited: push children from cache for free ─────────────────
        if cand_norm in visited:
            entry = cache.get(cand_norm)
            if entry and not _expired(entry):
                for nb in entry["similar"]:
                    new_pri = priority * nb["match"] * DECAY
                    if new_pri >= MIN_PRIORITY and depth < MAX_DEPTH:
                        _push(heap, new_pri, nb["name"], path + [nb["name"]], depth + 1)
            continue

        # ── priority floor ─────────────────────────────────────────────────────
        if priority < MIN_PRIORITY:
            # heap is a max-heap; everything remaining is ≤ this priority
            break

        # ── depth cap ─────────────────────────────────────────────────────────
        if depth >= MAX_DEPTH:
            continue

        # ── per-artist budget cap ──────────────────────────────────────────────
        if artist_misses >= PER_ARTIST_BUDGET:
            break

        # ── global budget guard ────────────────────────────────────────────────
        if budget[0] <= 0:
            break

        # ── fetch (cache hit or API call) ──────────────────────────────────────
        neighbors, hit = fetch_similar(candidate, cache, budget)
        if not hit:
            artist_misses += 1
        visited.add(cand_norm)

        for nb in neighbors:
            new_pri = priority * nb["match"] * DECAY
            if new_pri >= MIN_PRIORITY and depth + 1 <= MAX_DEPTH:
                _push(heap, new_pri, nb["name"], path + [nb["name"]], depth + 1)

    calls = budget_before - budget[0]

    # Serialize remaining heap for frontier persistence
    remaining = [[-neg_pri, name, path, depth]
                 for neg_pri, name, path, depth in heap]

    return found, pops, calls, remaining


# ── main ───────────────────────────────────────────────────────────────────────

def run():
    data  = load_graph()
    nodes = data["nodes"]

    # Clear existing bfs_edges (fresh start)
    for node in nodes:
        node.pop("bfs_edges", None)

    # Load + pre-populate cache
    cache = load_cache()
    cache_size_before = len(cache)
    added = prepopulate_cache(nodes, cache)
    if added:
        save_cache(cache)

    # Load frontier
    frontier = load_frontier()

    # Build lineup lookup
    lineup_norm = {_norm(n["name"]): n["name"] for n in nodes}

    # Classify isolated vs connected
    isolated   = []
    n_connected = 0
    for node in nodes:
        l1_norms = [_norm(s["name"]) for s in node.get("similar_artists", [])]
        if any(k in lineup_norm for k in l1_norms):
            n_connected += 1
        else:
            isolated.append(node)

    total_isolated = len(isolated)
    print(f"Total lineup artists      : {len(nodes)}")
    print(f"Non-isolated (L1 hit)     : {n_connected}")
    print(f"Isolated entering search  : {total_isolated}")
    print(f"Cache size at start       : {cache_size_before} (+{added} pre-populated from graph)")
    print()

    # Global state
    visited = set()
    budget  = [GLOBAL_BUDGET]

    # Result buckets
    connected_free = []   # found with 0 API calls (pure cache)
    connected_paid = []   # found with ≥1 API calls
    still_isolated = []

    for idx, node in enumerate(isolated, 1):
        artist_name = node["name"]
        artist_norm = _norm(artist_name)
        saved = frontier.get(artist_norm, [])

        found, pops, calls, remaining = search_artist(
            node, artist_norm, lineup_norm, cache, visited, budget, saved
        )

        if found:
            path, target_name, weight, depth = found
            # via = all path elements except the final lineup artist
            via_str = " → ".join(path[:-1]) if len(path) > 1 else path[0]

            node["bfs_edges"] = [{
                "target": target_name,
                "weight": weight,
                "via":    via_str,
                "depth":  depth,
            }]

            # Remove from frontier if it was there
            frontier.pop(artist_norm, None)

            if calls == 0:
                connected_free.append((artist_name, path, target_name, weight, depth, 0))
            else:
                connected_paid.append((artist_name, path, target_name, weight, depth, calls))

            sys.stdout.write(
                f"[{idx}/{total_isolated}] {artist_name} — "
                f"popped {pops} nodes, {calls} API call{'s' if calls != 1 else ''} → "
                f"found: via {via_str} → {target_name} (w={weight})\n"
            )
        else:
            still_isolated.append(artist_name)
            frontier[artist_norm] = remaining   # save for next run

            sys.stdout.write(
                f"[{idx}/{total_isolated}] {artist_name} — "
                f"popped {pops} nodes, {calls} API call{'s' if calls != 1 else ''} → "
                f"still isolated (budget remaining: {budget[0]})\n"
            )

        sys.stdout.flush()

    # Persist everything
    save_graph(data)
    save_cache(cache)
    save_frontier(frontier)

    cache_size_after  = len(cache)
    total_api_calls   = GLOBAL_BUDGET - budget[0]
    all_connected     = connected_free + connected_paid

    # ── summary ───────────────────────────────────────────────────────────────
    print()
    print("─" * 75)
    print("RESULTS:")
    print(f"  Isolated entering search       : {total_isolated}")
    print(f"  Connected (cache / free)       : {len(connected_free)}")
    print(f"  Connected (new API calls)      : {len(connected_paid)}")
    print(f"  Still isolated                 : {len(still_isolated)}")
    print(f"  Total API calls (cache misses) : {total_api_calls}")
    print(f"  Cache size before / after      : {cache_size_before} → {cache_size_after}")
    print(f"  Budget remaining               : {budget[0]}")
    print()

    # ── connection table ──────────────────────────────────────────────────────
    if all_connected:
        col_a = 44
        col_v = 46
        col_t = 28
        header = (f"  {'Isolated artist':<{col_a}}  {'Via path':<{col_v}}"
                  f"  {'Target':<{col_t}}  {'Weight':>7}  {'Depth':>5}  {'API calls':>9}")
        print(header)
        print("  " + "─" * (col_a + col_v + col_t + 30))
        for artist, path, target, weight, depth, calls in all_connected:
            via = " → ".join(path[:-1]) if len(path) > 1 else "(L1 direct)"
            print(f"  {artist:<{col_a}}  {via:<{col_v}}  {target:<{col_t}}"
                  f"  {weight:>7.4f}  {depth:>5}  {calls:>9}")

    if still_isolated:
        print()
        print("── Still isolated ──")
        for name in still_isolated:
            print(f"  {name!r}")


if __name__ == "__main__":
    run()
