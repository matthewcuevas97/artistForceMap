/**
 * simulation.js
 * D3 force simulation, SVG scaffold, rendering, tick, hover,
 * subgraph highlight with temporary edge-strength boost, and zoom.
 * Uses global `d3` (loaded via UMD <script> tag in HTML).
 */

import { nodeRadius, nodeColor, labelOpacity, edgeBaseOpacity, escapeHtml } from './utils.js';
import { DAY_MAP } from './constants.js';
import * as S from './state.js';

// ── SVG scaffold ──────────────────────────────────────────────────────────────

export const svg = d3.select("#graph")
  .attr("width",  S.W)
  .attr("height", S.H);

const bgRect = svg.append("rect")
  .attr("width",  S.W)
  .attr("height", S.H)
  .attr("fill", "#111111");

export const gMain   = svg.append("g");
export const gEdges  = gMain.append("g").attr("class", "edges");
export const gNodes  = gMain.append("g").attr("class", "nodes");
export const gLabels = gMain.append("g").attr("class", "labels");

export const zoomBehavior = d3.zoom()
  .scaleExtent([0.05, 20])
  .on("zoom", event => gMain.attr("transform", event.transform));

svg.call(zoomBehavior).on("dblclick.zoom", null);

// ── Tooltip ───────────────────────────────────────────────────────────────────

const tooltip = d3.select("body").append("div")
  .attr("id", "tooltip")
  .style("position",       "fixed")
  .style("background",     "rgba(12,12,12,0.93)")
  .style("border",         "1px solid rgba(255,255,255,0.12)")
  .style("color",          "#ffffff")
  .style("font-family",    "'IBM Plex Mono', monospace")
  .style("font-size",      "11px")
  .style("line-height",    "1.9")
  .style("padding",        "10px 14px")
  .style("pointer-events", "none")
  .style("display",        "none")
  .style("z-index",        "200")
  .style("letter-spacing", "0.04em")
  .style("max-width",      "240px");

// ── Exported mutable selections (live bindings via re-export pattern) ─────────

export let simulation = null;
export let nodeEl     = null;
export let edgeEl     = null;
export let labelEl    = null;

// Selected node name for edge-boost
let boostNodeName = null;

// ── Subgraph viewport ─────────────────────────────────────────────────────────

export function getSubgraphViewport() {
  if (!S.isMobile) return { top: 0, bottom: S.H, left: 0, right: S.W };
  return {
    top:    S.controlsCollapsedBottom,
    bottom: window.innerHeight - S.drawerCollapsedH(),
    left:   0,
    right:  window.innerWidth,
  };
}

// ── Tick ──────────────────────────────────────────────────────────────────────

function ticked() {
  edgeEl
    .attr("x1", e => e.source.x)
    .attr("y1", e => e.source.y)
    .attr("x2", e => e.target.x)
    .attr("y2", e => e.target.y);

  nodeEl
    .attr("cx", d => d.x)
    .attr("cy", d => d.y);

  labelEl
    .attr("x", d => d.x)
    .attr("y", d => d.y - nodeRadius(d) - 4);
}

// ── Filter helpers ────────────────────────────────────────────────────────────

function nodeName(n) { return typeof n === "object" ? n.name : n; }

export function applyEdgeFilter() {
  if (!edgeEl) return;

  if (S.discoveryMode) {
    edgeEl.attr("opacity", e => {
      const sn = nodeName(e.source), tn = nodeName(e.target);
      if (S.lastDiscovered && (sn === S.lastDiscovered || tn === S.lastDiscovered)) {
        const other = sn === S.lastDiscovered ? tn : sn;
        if (_discoveryVisible(other)) return 0.45;
      }
      if (!S.lastDiscovered && S.discovered.has(sn) && S.discovered.has(tn)) return edgeBaseOpacity(e);
      return 0;
    });
  } else if (S.isSubgraphHighlight && S.highlightNeighborhood) {
    edgeEl.attr("opacity", e => {
      const sn = nodeName(e.source), tn = nodeName(e.target);
      return (S.highlightNeighborhood.has(sn) && S.highlightNeighborhood.has(tn)) ? edgeBaseOpacity(e) : 0;
    });
  } else {
    edgeEl.attr("opacity", e => edgeBaseOpacity(e));
  }
}

export function applyDayFilter() {
  if (!nodeEl) return;
  const target  = S.dayFilter === "ALL" ? null : DAY_MAP[S.dayFilter];
  const visible = d => !target || d.day === target;

  nodeEl.style("display", d => {
    if (!visible(d)) return "none";
    if (S.discoveryMode && !_discoveryVisible(d.name)) return "none";
    return null;
  });
  labelEl.style("display", d => {
    if (!visible(d)) return "none";
    if (S.discoveryMode && !_discoveryVisible(d.name)) return "none";
    return null;
  });
  edgeEl.style("display", e => {
    const src = typeof e.source === "object" ? e.source : {};
    const tgt = typeof e.target === "object" ? e.target : {};
    return visible(src) && visible(tgt) ? null : "none";
  });
}

// ── Hover ─────────────────────────────────────────────────────────────────────

function onNodeEnter(event, d) {
  edgeEl.attr("opacity", e => {
    if (e.type === "similarity" && !S.showSimilarity) return 0;
    if (e.type === "genre"      && !S.showGenre)      return 0;
    if (e.source === d || e.target === d) return edgeBaseOpacity(e);
    if (S.discoveryMode && S.lastDiscovered) {
      const sn = nodeName(e.source), tn = nodeName(e.target);
      if (sn === S.lastDiscovered || tn === S.lastDiscovered) {
        const other = sn === S.lastDiscovered ? tn : sn;
        if (_discoveryVisible(other)) return 0.45;
      }
    }
    return 0.02;
  });
  labelEl.attr("opacity", l => (l === d ? 1.0 : (l.score >= 0.1 ? 0.05 : 0)));

  const stage = d.stage ? `${d.stage} · ` : "";
  const wk    = d.weekend !== "Both" ? ` · WK${d.weekend}` : "";
  tooltip
    .style("display", "block")
    .html(
      `<div style="font-weight:500;margin-bottom:3px">${escapeHtml(d.name)}</div>` +
      `<div style="color:#999">${escapeHtml(d.genre)}</div>` +
      `<div style="color:#666">${escapeHtml(stage)}${escapeHtml(d.day)}${escapeHtml(wk)}</div>`
    );
  moveTooltip(event);
}

function onNodeMove(event) { moveTooltip(event); }
function onNodeLeave()     { clearHover(); }

function moveTooltip(event) {
  const pad = 16;
  let x = event.clientX + 18, y = event.clientY - 12;
  if (x + 240 > S.W) x = event.clientX - 240 - 6;
  if (y + 80  > S.H) y = S.H - 80 - pad;
  tooltip.style("left", x + "px").style("top", y + "px");
}

export function clearHover() {
  applyEdgeFilter();
  if (labelEl) {
    if (S.discoveryMode) {
      labelEl.attr("opacity", d => _discoveryVisible(d.name) ? 1.0 : 0);
    } else if (S.isSubgraphHighlight && S.highlightNeighborhood) {
      labelEl.attr("opacity", d => S.highlightNeighborhood.has(d.name) ? 1.0 : 0);
    } else {
      labelEl.attr("opacity", d => labelOpacity(d));
    }
  }
  if (nodeEl && S.isSubgraphHighlight && S.highlightNeighborhood) {
    nodeEl.attr("opacity", d => S.highlightNeighborhood.has(d.name) ? 1.0 : 0.15);
  }
  tooltip.style("display", "none");
}

// ── Subgraph highlight with edge-strength boost ───────────────────────────────

export function enterSubgraphHighlight(datum) {
  if (!nodeEl || !edgeEl || !labelEl) return;

  const neighborhood = new Set([datum.name]);
  S.simEdges.forEach(e => {
    const sn = nodeName(e.source), tn = nodeName(e.target);
    if (sn === datum.name) neighborhood.add(tn);
    if (tn === datum.name) neighborhood.add(sn);
  });

  S.setIsSubgraphHighlight(true);
  S.setHighlightNeighborhood(neighborhood);
  boostNodeName = datum.name;

  // Temporarily boost link strength on all edges touching the selected node
  if (simulation) {
    simulation.force("link").strength(e => {
      const sn = nodeName(e.source), tn = nodeName(e.target);
      const base = e.weight * 0.3;
      return (sn === boostNodeName || tn === boostNodeName) ? base * 3.5 : base;
    });
    simulation.alpha(0.08).restart();
  }

  nodeEl .attr("opacity", d => neighborhood.has(d.name) ? 1.0 : 0.15);
  labelEl.attr("opacity", d => neighborhood.has(d.name) ? 1.0 : 0);
  applyEdgeFilter();
  zoomToNodes(S.simNodes.filter(n => neighborhood.has(n.name)));
}

export function exitSubgraphHighlight() {
  if (!S.isSubgraphHighlight) return;
  S.setIsSubgraphHighlight(false);
  S.setHighlightNeighborhood(null);
  boostNodeName = null;

  if (simulation) {
    simulation.force("link").strength(e => e.weight * 0.3);
    simulation.alpha(0.03).restart();
  }

  if (nodeEl)  nodeEl .attr("opacity", 1.0);
  if (labelEl) labelEl.attr("opacity", d => labelOpacity(d));
  applyEdgeFilter();

  svg.transition().duration(500).call(zoomBehavior.scaleBy, 1 / 1.25);
}

// ── Zoom helpers ──────────────────────────────────────────────────────────────

export function zoomToSubgraph() {
  zoomToNodes(S.simNodes.filter(n => S.subgraph.has(n.name)));
}

function zoomToNodes(nodes) {
  if (!nodes.length) return;
  const vp     = getSubgraphViewport();
  const availW = vp.right - vp.left;
  const availH = vp.bottom - vp.top;
  if (availW <= 0 || availH <= 0) return;

  const pad  = 80;
  const xs   = nodes.map(n => n.x);
  const ys   = nodes.map(n => n.y);
  const minX = Math.min(...xs) - pad, maxX = Math.max(...xs) + pad;
  const minY = Math.min(...ys) - pad, maxY = Math.max(...ys) + pad;

  const scale = Math.min(availW / (maxX - minX), availH / (maxY - minY), 5);
  const tx    = (vp.left + availW / 2) - scale * ((minX + maxX) / 2);
  const ty    = (vp.top  + availH / 2) - scale * ((minY + maxY) / 2);

  svg.transition().duration(700)
    .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
}

// ── Drag ──────────────────────────────────────────────────────────────────────

export const drag = d3.drag()
  .on("start", (event, d) => {
    S.setDragMoved(false);
    if (!event.active) simulation.alphaTarget(0.3).restart();
    d.fx = d.x; d.fy = d.y;
  })
  .on("drag", (event, d) => {
    S.setDragMoved(true);
    d.fx = event.x; d.fy = event.y;
  })
  .on("end", (event) => {
    if (!event.active) simulation.alphaTarget(0);
  });

// ── Build graph ───────────────────────────────────────────────────────────────

export function buildGraph(onNodeClick, onBgClick) {
  if (simulation) simulation.stop();

  gEdges.selectAll("*").remove();
  gNodes.selectAll("*").remove();
  gLabels.selectAll("*").remove();

  const newNodes = S.rawNodes.map(d => ({ ...d }));
  const newEdges = S.rawEdges.map(e => ({ source: e.source, target: e.target, weight: e.weight, type: e.type }));

  S.setSimNodes(newNodes);
  S.setSimEdges(newEdges);

  simulation = d3.forceSimulation(newNodes)
    .force("link",    d3.forceLink(newEdges).id(d => d.name).strength(e => e.weight * 0.7))
    .force("charge",  d3.forceManyBody().strength(-800))
    .force("center",  d3.forceCenter(S.W / 2, S.H / 2))
    .force("collide", d3.forceCollide().radius(d => nodeRadius(d) + 2))
    .force("x",       d3.forceX(S.W / 2).strength(0.15))
    .force("y",       d3.forceY(S.H / 2).strength(0.3))
    .stop();

  for (let i = 0; i < 3000; ++i) simulation.tick();

  edgeEl = gEdges.selectAll("line")
    .data(newEdges).enter().append("line")
    .attr("stroke",       "#ffffff")
    .attr("stroke-width", e => (2 + e.weight * 2).toFixed(2))
    .attr("opacity",      e => edgeBaseOpacity(e));

  nodeEl = gNodes.selectAll("circle")
    .data(newNodes).enter().append("circle")
    .attr("r",      d => nodeRadius(d))
    .attr("fill",   d => nodeColor(d))
    .attr("stroke", "none")
    .style("cursor", "pointer")
    .call(drag)
    .on("mouseenter", S.isMobile ? null : onNodeEnter)
    .on("mousemove",  S.isMobile ? null : onNodeMove)
    .on("mouseleave", S.isMobile ? null : onNodeLeave)
    .on("click", (event, d) => { event.stopPropagation(); onNodeClick(event, d); });

  labelEl = gLabels.selectAll("text")
    .data(newNodes).enter().append("text")
    .attr("font-family",    "'IBM Plex Mono', monospace")
    .attr("font-size",      "11px")
    .attr("fill",           "#ffffff")
    .attr("text-anchor",    "middle")
    .attr("pointer-events", "none")
    .attr("opacity",        d => labelOpacity(d))
    .text(d => d.name);

  bgRect.on("click", () => onBgClick());

  ticked();
  applyDayFilter();
  applyEdgeFilter();

  simulation.on("tick", ticked).alpha(0.1).restart();
}

export function rebuildNodeSizes() {
  if (!nodeEl || !labelEl || !simulation) return;
  nodeEl .attr("r",  d => nodeRadius(d));
  labelEl.attr("y",  d => d.y - nodeRadius(d) - 4);
  simulation
    .force("collide", d3.forceCollide().radius(d => nodeRadius(d) + 2))
    .alpha(0.15).restart();
}

// ── Discovery visibility (set from discovery.js to avoid circular dep) ────────

let _discoveryVisible = () => false;
export function registerDiscoveryVisible(fn) { _discoveryVisible = fn; }
