/**
 * discovery.js — Discovery mode: seeding, fringe, ambassadors, visuals.
 */

import { nodeRadius, nodeColor, labelOpacity } from './utils.js';
import * as S from './state.js';
import {
  nodeEl, edgeEl, labelEl,
  applyEdgeFilter, zoomToSubgraph,
  registerDiscoveryVisible,
} from './simulation.js';
import { minimizeMenu } from './ui.js';

// ── Register our visibility check with simulation.js ─────────────────────────

export function discoveryVisible(name) {
  if (S.lastDiscovered) return S.subgraph.has(name);
  return S.discovered.has(name) || S.ambassadors.has(name);
}

registerDiscoveryVisible(discoveryVisible);

// ── Seed / recalc ─────────────────────────────────────────────────────────────

export function seedDiscovery(userSeeds) {
  S.discovered.clear();
  S.fringe.clear();
  S.subgraph.clear();
  S.ambassadors.clear();
  S.setLastDiscovered(null);

  let seeds;
  if (userSeeds.size > 0) {
    const userNodes = S.simNodes
      .filter(n => userSeeds.has(n.name))
      .sort((a, b) => b.score - a.score);

    seeds = userNodes.length >= 20
      ? userNodes.slice(0, 20)
      : [...userNodes, ...S.simNodes.filter(n => !userSeeds.has(n.name)).sort((a,b) => b.score-a.score)].slice(0, 20);
  } else {
    seeds = [...S.simNodes].sort((a, b) => b.score - a.score).slice(0, 20);
  }

  seeds.forEach(n => S.discovered.add(n.name));
  S.setLastDiscovered(null);
  updateAmbassadors();
  updateDiscoveryVisuals();
}

export function recalcFringe() {
  S.fringe.clear();
  S.subgraph.clear();

  if (!S.lastDiscovered) return;
  S.subgraph.add(S.lastDiscovered);

  for (const e of S.rawEdges) {
    const src = typeof e.source === "object" ? e.source.name : e.source;
    const tgt = typeof e.target === "object" ? e.target.name : e.target;
    if (src === S.lastDiscovered) {
      S.subgraph.add(tgt);
      if (!S.discovered.has(tgt)) S.fringe.add(tgt);
    }
    if (tgt === S.lastDiscovered) {
      S.subgraph.add(src);
      if (!S.discovered.has(src)) S.fringe.add(src);
    }
  }
}

export function updateAmbassadors() {
  S.ambassadors.clear();

  const undiscovered = new Set(S.simNodes.filter(n => !S.discovered.has(n.name)).map(n => n.name));
  if (!undiscovered.size) return;

  const reachable = new Set();
  for (const e of S.rawEdges) {
    const src = typeof e.source === "object" ? e.source.name : e.source;
    const tgt = typeof e.target === "object" ? e.target.name : e.target;
    if (S.discovered.has(src) && undiscovered.has(tgt)) reachable.add(tgt);
    if (S.discovered.has(tgt) && undiscovered.has(src)) reachable.add(src);
  }

  const unreachable = new Set([...undiscovered].filter(n => !reachable.has(n)));
  if (!unreachable.size) return;

  const adj = new Map([...unreachable].map(n => [n, []]));
  for (const e of S.rawEdges) {
    const src = typeof e.source === "object" ? e.source.name : e.source;
    const tgt = typeof e.target === "object" ? e.target.name : e.target;
    if (unreachable.has(src) && unreachable.has(tgt)) {
      adj.get(src).push(tgt);
      adj.get(tgt).push(src);
    }
  }

  const visited    = new Set();
  const nodeByName = new Map(S.simNodes.map(n => [n.name, n]));
  for (const start of unreachable) {
    if (visited.has(start)) continue;
    const component = [];
    const queue     = [start];
    visited.add(start);
    while (queue.length) {
      const name = queue.shift();
      component.push(name);
      for (const nb of (adj.get(name) || [])) {
        if (!visited.has(nb)) { visited.add(nb); queue.push(nb); }
      }
    }
    const best = component.map(name => nodeByName.get(name)).filter(Boolean).sort((a,b) => b.score-a.score)[0];
    if (best) S.ambassadors.add(best.name);
  }
}

export function updateDiscoveryVisuals() {
  if (!nodeEl || !labelEl || !edgeEl) return;

  if (!S.discoveryMode) {
    nodeEl.style("display", null).transition().duration(600)
      .attr("r", d => nodeRadius(d)).attr("fill", d => nodeColor(d))
      .attr("fill-opacity", 1).attr("stroke", "none").attr("stroke-width", 0)
      .style("pointer-events", "all");
    labelEl.style("display", null).transition().duration(600)
      .attr("opacity", d => labelOpacity(d)).attr("font-size", "11px");
    applyEdgeFilter();
    return;
  }

  nodeEl .style("display", d => discoveryVisible(d.name) ? null : "none");
  labelEl.style("display", d => discoveryVisible(d.name) ? null : "none");

  nodeEl.filter(d => discoveryVisible(d.name)).transition().duration(600)
    .attr("r",    d => nodeRadius(d))
    .attr("fill", d => S.discovered.has(d.name) ? nodeColor(d) : "none")
    .attr("fill-opacity", 1)
    .attr("stroke", d => {
      if (d.name === S.lastDiscovered)           return "rgba(255,255,255,0.95)";
      if (d.name === window._pendingDiscovery)   return "rgba(255,200,50,0.9)";
      if (S.fringe.has(d.name) || S.ambassadors.has(d.name)) return "rgba(255,255,255,0.45)";
      return "none";
    })
    .attr("stroke-width", d => {
      if (d.name === S.lastDiscovered)           return 3;
      if (d.name === window._pendingDiscovery)   return 2;
      if (S.fringe.has(d.name) || S.ambassadors.has(d.name)) return 1.5;
      return 0;
    })
    .style("pointer-events", "all");

  labelEl.filter(d => discoveryVisible(d.name)).transition().duration(300)
    .attr("opacity",   1.0)
    .attr("font-size", d => d.name === window._pendingDiscovery ? "13px" : "11px");

  applyEdgeFilter();
}

export function triggerDiscovery(artistName) {
  if (!S.discoveryMode || S.discovered.has(artistName)) return;
  window._pendingDiscovery = null;
  S.fringe.delete(artistName);
  S.ambassadors.delete(artistName);
  S.discovered.add(artistName);
  S.setLastDiscovered(artistName);
  updateAmbassadors();
  recalcFringe();
  updateDiscoveryVisuals();
  zoomToSubgraph();
  minimizeMenu();
}
