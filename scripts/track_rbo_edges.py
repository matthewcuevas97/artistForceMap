"""
Track RBO edges through the entire pipeline:
1. Identifies RBO edges in precompute
2. Shows which pass they're assigned to
3. Shows which thresholds they appear at on frontend
"""

import json
import sys
from collections import Counter, defaultdict
from itertools import combinations

sys.path.insert(0, '.')

# Load current graph files
with open('data/graph_static.json') as f:
    static = json.load(f)

with open('data/graph_slim.json') as f:
    slim = json.load(f)

# Recreate RBO calculation from precompute.py
def rbo(list1, list2, p=0.9):
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

RBO_BASE_THRESHOLD = 0.21

nodes = static['nodes']
links = static['links']

# Calculate which edges would be RBO candidates
print("=== RBO Edge Tracking ===\n")

rbo_scores = {}
for node1, node2 in combinations(nodes, 2):
    score = rbo(node1.get("tags", []), node2.get("tags", []))
    if score >= RBO_BASE_THRESHOLD:
        a, b = sorted((node1["name"], node2["name"]))
        rbo_scores[(a, b)] = score

print(f"RBO candidates (score >= {RBO_BASE_THRESHOLD}): {len(rbo_scores)}")

# Find which RBO edges actually made it into the static graph
rbo_edges_in_graph = defaultdict(list)
pass_distribution = Counter()

for link in links:
    key = (link['source'], link['target'])
    pass_num = link['pass']

    if key in rbo_scores:
        rbo_edges_in_graph[key] = {
            'score': rbo_scores[key],
            'pass': pass_num
        }
        pass_distribution[f"Pass {pass_num}"] += 1

print(f"RBO edges that made it into graph: {len(rbo_edges_in_graph)}")
print(f"Pass distribution of RBO edges:")
for pass_label, count in sorted(pass_distribution.items()):
    print(f"  {pass_label}: {count}")

# Now trace these to the frontend by threshold
# Pass 2 → threshold 0.20
rbo_by_threshold = defaultdict(int)

THRESHOLDS = [0.05, 0.10, 0.20, 0.30, 0.50]

def pass_to_threshold(pass_num):
    if pass_num in (1, 2):
        return 0.20
    elif pass_num == 3:
        return 0.10
    else:
        return 0.05

for edge_pair, edge_info in rbo_edges_in_graph.items():
    threshold = pass_to_threshold(edge_info['pass'])
    # Include at all thresholds >= this threshold
    for t in THRESHOLDS:
        if t >= threshold:
            rbo_by_threshold[f"{t:.2f}"] += 1

print(f"\nRBO edges on frontend by threshold:")
for threshold in [f"{t:.2f}" for t in THRESHOLDS]:
    print(f"  Threshold {threshold}: {rbo_by_threshold[threshold]} RBO edges")

# Sample some high-scoring RBO edges
print(f"\nTop RBO edges (by score):")
sorted_rbo = sorted(rbo_edges_in_graph.items(), key=lambda x: x[1]['score'], reverse=True)
for i, (edge, info) in enumerate(sorted_rbo[:10], 1):
    print(f"  {i}. {edge[0]} ↔ {edge[1]}")
    print(f"     RBO score: {info['score']:.4f}, Pass: {info['pass']}")

# Summary statistics
total_links = len(links)
rbo_count = len(rbo_edges_in_graph)
pass2_edges = sum(1 for link in links if link['pass'] == 2)

print(f"\n=== Summary ===")
print(f"Total edges in graph: {total_links}")
print(f"  Pass 1 (Gold Standard): {sum(1 for link in links if link['pass'] == 1)}")
print(f"  Pass 2 (Base RBO): {pass2_edges}")
print(f"    → RBO-based edges: {rbo_count}")
print(f"    → Non-RBO edges in Pass 2: {pass2_edges - rbo_count}")
print(f"  Pass 3 (Conditional Rewiring): {sum(1 for link in links if link['pass'] == 3)}")
print(f"  Pass 4 (Adaptive Floor): {sum(1 for link in links if link['pass'] == 4)}")
print(f"  Pass 5 (Hail Mary): {sum(1 for link in links if link['pass'] == 5)}")
