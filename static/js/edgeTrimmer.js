/**
 * edgeTrimmer.js
 *
 * Trims the edge set to a manageable size while guaranteeing:
 *   1. No additional disconnected subgraphs are created (max-spanning-tree backbone).
 *   2. High-similarity edges are kept preferentially.
 *
 * Algorithm:
 *   a. Build a maximum spanning tree (Kruskal, sort by weight DESC) — this
 *      preserves exactly the same connected components as the full input graph.
 *   b. For each node, also keep its top-K highest-weight edges that aren't
 *      already in the spanning tree (default K = 6).
 *
 * The result is a Set of edge objects from the original rawEdges array.
 */

class UnionFind {
  constructor(keys) {
    this.parent = new Map(keys.map(k => [k, k]));
    this.rank   = new Map(keys.map(k => [k, 0]));
  }

  find(k) {
    if (this.parent.get(k) !== k) {
      this.parent.set(k, this.find(this.parent.get(k)));
    }
    return this.parent.get(k);
  }

  union(a, b) {
    const ra = this.find(a), rb = this.find(b);
    if (ra === rb) return false;
    if (this.rank.get(ra) < this.rank.get(rb)) {
      this.parent.set(ra, rb);
    } else if (this.rank.get(ra) > this.rank.get(rb)) {
      this.parent.set(rb, ra);
    } else {
      this.parent.set(rb, ra);
      this.rank.set(ra, this.rank.get(ra) + 1);
    }
    return true;
  }
}

/**
 * @param {Array} nodes   - raw node objects (must have .name)
 * @param {Array} edges   - raw edge objects (must have .source, .target, .weight, .type)
 * @param {number} topK   - extra high-weight edges to keep per node beyond the spanning tree
 * @returns {Set}         - Set of edge objects to keep
 */
export function trimEdges(nodes, edges, topK = 6) {
  const nodeNames = nodes.map(n => n.name);
  const uf = new UnionFind(nodeNames);

  // Sort edges by weight descending for maximum spanning tree
  const sorted = [...edges].sort((a, b) => b.weight - a.weight);

  const kept = new Set();

  // Phase 1: max spanning tree — guarantees no extra disconnected components
  for (const e of sorted) {
    const src = typeof e.source === "object" ? e.source.name : e.source;
    const tgt = typeof e.target === "object" ? e.target.name : e.target;
    if (uf.union(src, tgt)) {
      kept.add(e);
    }
  }

  // Phase 2: per-node top-K additional edges (prefer similarity over genre)
  const byNode = new Map();
  for (const e of sorted) {
    const src = typeof e.source === "object" ? e.source.name : e.source;
    const tgt = typeof e.target === "object" ? e.target.name : e.target;
    if (!byNode.has(src)) byNode.set(src, []);
    if (!byNode.has(tgt)) byNode.set(tgt, []);
    byNode.get(src).push(e);
    byNode.get(tgt).push(e);
  }

  for (const list of byNode.values()) {
    // Similarity edges first, then genre, within each group sorted by weight desc
    const simEdges   = list.filter(e => e.type === "similarity");
    const genreEdges = list.filter(e => e.type !== "similarity");
    const ordered    = [...simEdges, ...genreEdges]; // already weight-sorted within type
    let added = 0;
    for (const e of ordered) {
      if (kept.has(e)) { added++; if (added >= topK) break; continue; }
      if (added >= topK) break;
      kept.add(e);
      added++;
    }
  }

  return kept;
}
