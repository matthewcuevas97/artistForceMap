// ── Constants ────────────────────────────────────────────────────────────────

const GENRE_HUE = {
  "Electronic":             195,
  "Indie/Alt":              135,
  "Hip-Hop":                 45,
  "R&B/Soul":                25,
  "Pop":                    330,
  "Punk/Metal":               0,
  "Latin/Afro":             275,
  "Singer-Songwriter/Jazz":  30,
  "Unknown":                220,
};

const DAY_MAP = { FRI: "Friday", SAT: "Saturday", SUN: "Sunday" };

// ── Module state ─────────────────────────────────────────────────────────────

let rawNodes = [];   // original data from API (never mutated after fetch)
let rawEdges = [];   // original data from API (never mutated after fetch)
let simNodes = [];   // working copies for simulation (D3 adds x, y, vx, vy)
let simEdges = [];   // working copies for simulation (D3 resolves source/target → objects)

let simulation = null;
let nodeEl, edgeEl, labelEl;  // d3 selections, set in buildGraph()

// Control state — mirrors the HTML controls
let nodeScale      = 1.0;
let edgeThreshold  = 0.2;
let showSimilarity = true;
let showGenre      = true;
let dayFilter      = "ALL";

let thresholdDebounce = null;
let dragMoved = false;

// ── Viewport ─────────────────────────────────────────────────────────────────

const W = window.innerWidth;
const H = window.innerHeight;

// ── SVG scaffold ─────────────────────────────────────────────────────────────

const svg = d3.select("#graph")
  .attr("width",  W)
  .attr("height", H);

// Solid background (also intercepts clicks to clear hover)
svg.append("rect")
  .attr("width",  W)
  .attr("height", H)
  .attr("fill", "#111111")
  .on("click", clearHover);

// One main group that zoom/pan transforms
const gMain   = svg.append("g");
const gEdges  = gMain.append("g").attr("class", "edges");
const gNodes  = gMain.append("g").attr("class", "nodes");
const gLabels = gMain.append("g").attr("class", "labels");

// Zoom + pan
const zoomBehavior = d3.zoom()
  .scaleExtent([0.05, 20])
  .on("zoom", event => gMain.attr("transform", event.transform));

svg.call(zoomBehavior).on("dblclick.zoom", null);

// ── Tooltip ──────────────────────────────────────────────────────────────────

const tooltip = d3.select("body").append("div")
  .style("position",       "fixed")
  .style("background",     "rgba(12, 12, 12, 0.93)")
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

// ── Helper functions ─────────────────────────────────────────────────────────

function nodeRadius(d) {
  return (4 + d.score * 20) * nodeScale;
}

function nodeColor(d) {
  const hue = GENRE_HUE[d.genre] ?? 220;
  const sat = 20 + d.score * 70;
  const lit  = 25 + d.score * 35;
  return `hsl(${hue}, ${sat.toFixed(1)}%, ${lit.toFixed(1)}%)`;
}

function labelOpacity(d) {
  if (d.score < 0.1) return 0;
  return Math.min(1.0, 0.15 + d.score * 0.85);
}

// Base opacity for an edge given current type-filter state
function edgeBaseOpacity(e) {
  if (e.type === "similarity" && !showSimilarity) return 0;
  if (e.type === "genre"      && !showGenre)      return 0;
  return 0.08;
}

// Build a Set of the edges that are in the top-8 by weight for at least one endpoint.
// Operates on raw edges (source/target are still strings).
function buildTopEdgeSet(edges) {
  const byNode = {};
  for (const e of edges) {
    (byNode[e.source] ??= []).push(e);
    (byNode[e.target] ??= []).push(e);
  }
  const topSet = new Set();
  for (const list of Object.values(byNode)) {
    list.sort((a, b) => b.weight - a.weight);
    list.slice(0, 8).forEach(e => topSet.add(e));
  }
  return topSet;
}

// ── Drag behavior ─────────────────────────────────────────────────────────────
// Defined once; references the module-level `simulation` variable at call time.

const drag = d3.drag()
  .on("start", (event, d) => {
    dragMoved = false;
    if (!event.active) simulation.alphaTarget(0.3).restart();
    d.fx = d.x;
    d.fy = d.y;
  })
  .on("drag", (event, d) => {
    dragMoved = true;
    d.fx = event.x;
    d.fy = event.y;
  })
  .on("end", (event, d) => {
    if (!event.active) simulation.alphaTarget(0);
    // Node stays pinned at its dropped position
  });

// ── Tick handler ──────────────────────────────────────────────────────────────

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

// ── Hover / interaction handlers ──────────────────────────────────────────────

function onNodeEnter(event, d) {
  // Dim all edges; highlight connected ones (respecting type filter)
  edgeEl.attr("opacity", e => {
    if (e.type === "similarity" && !showSimilarity) return 0;
    if (e.type === "genre"      && !showGenre)      return 0;
    return 0.02;
  });
  edgeEl
    .filter(e => e.source === d || e.target === d)
    .attr("opacity", e => edgeBaseOpacity(e));

  // Dim all labels; show hovered node's label
  labelEl.attr("opacity", l => (l === d ? 1.0 : (l.score >= 0.1 ? 0.05 : 0)));

  // Tooltip
  const stage = d.stage ? `${d.stage} · ` : "";
  const wk    = d.weekend !== "Both" ? ` · WK${d.weekend}` : "";
  tooltip
    .style("display", "block")
    .html(
      `<div style="font-weight:500;margin-bottom:3px">${d.name}</div>` +
      `<div style="color:#999">${d.genre}</div>` +
      `<div style="color:#666">${stage}${d.day}${wk}</div>`
    );
  moveTooltip(event);
}

function onNodeMove(event) {
  moveTooltip(event);
}

function onNodeLeave() {
  clearHover();
}

function moveTooltip(event) {
  // Keep tooltip within viewport
  const pad = 16;
  let x = event.clientX + 18;
  let y = event.clientY - 12;
  if (x + 240 > W) x = event.clientX - 240 - 6;
  if (y + 80  > H) y = H - 80 - pad;
  tooltip.style("left", x + "px").style("top", y + "px");
}

function clearHover() {
  applyEdgeFilter();
  if (labelEl) labelEl.attr("opacity", d => labelOpacity(d));
  tooltip.style("display", "none");
}

// ── Filter functions (called on control changes) ──────────────────────────────

function applyDayFilter() {
  if (!nodeEl) return;
  const target = dayFilter === "ALL" ? null : DAY_MAP[dayFilter];
  const visible = d => !target || d.day === target;

  nodeEl .style("display", d => visible(d) ? null : "none");
  labelEl.style("display", d => visible(d) ? null : "none");
  edgeEl .style("display", e => {
    // After 300 ticks, e.source / e.target are node objects
    const src = e.source;
    const tgt = e.target;
    return visible(src) && visible(tgt) ? null : "none";
  });
}

function applyEdgeFilter() {
  if (!edgeEl) return;
  edgeEl.attr("opacity", e => edgeBaseOpacity(e));
}

// ── Graph builder ─────────────────────────────────────────────────────────────

function buildGraph() {
  if (simulation) simulation.stop();

  // Clear existing elements
  gEdges .selectAll("*").remove();
  gNodes .selectAll("*").remove();
  gLabels.selectAll("*").remove();

  // Select top-8 edges per node from the raw set (strings for source/target)
  const topSet = buildTopEdgeSet(rawEdges);

  // Fresh copies: D3 forceLink will mutate source/target in-place → node objects
  simNodes = rawNodes.map(d => ({ ...d }));
  simEdges = rawEdges
    .filter(e => topSet.has(e))
    .map(e => ({ source: e.source, target: e.target, weight: e.weight, type: e.type }));

  // Build simulation (stopped — we pre-tick manually for stable initial layout)
  simulation = d3.forceSimulation(simNodes)
    .force("link",    d3.forceLink(simEdges).id(d => d.name).strength(d => d.weight * 0.3))
    .force("charge",  d3.forceManyBody().strength(-300))
    .force("center",  d3.forceCenter(W / 2, H / 2))
    .force("collide", d3.forceCollide().radius(d => nodeRadius(d) + 2))
    .force("x",       d3.forceX(W / 2).strength(0.05))
    .force("y",       d3.forceY(H / 2).strength(0.05))
    .stop();

  // Pre-compute 300 ticks — graph arrives stable, not animating from chaos
  for (let i = 0; i < 300; ++i) simulation.tick();

  // ── Render edges ──
  edgeEl = gEdges.selectAll("line")
    .data(simEdges)
    .enter()
    .append("line")
    .attr("stroke",       "#ffffff")
    .attr("stroke-width", e => (0.5 + e.weight * 2).toFixed(2))
    .attr("opacity",      e => edgeBaseOpacity(e));

  // ── Render nodes ──
  nodeEl = gNodes.selectAll("circle")
    .data(simNodes)
    .enter()
    .append("circle")
    .attr("r",      d => nodeRadius(d))
    .attr("fill",   d => nodeColor(d))
    .attr("stroke", "none")
    .style("cursor", "pointer")
    .call(drag)
    .on("mouseenter", onNodeEnter)
    .on("mousemove",  onNodeMove)
    .on("mouseleave", onNodeLeave)
    .on("click", (event, d) => {
      event.stopPropagation();
      // D3 drag suppresses click after a real drag; dragMoved guard is belt-and-suspenders
      if (dragMoved) { dragMoved = false; return; }
      if (d.fx !== null && d.fx !== undefined) {
        // Unpin
        d.fx = null;
        d.fy = null;
        d3.select(event.currentTarget)
          .attr("stroke",       "none")
          .attr("stroke-width", 0);
      } else {
        // Pin
        d.fx = d.x;
        d.fy = d.y;
        d3.select(event.currentTarget)
          .attr("stroke",       "rgba(255,255,255,0.45)")
          .attr("stroke-width", 1.5);
      }
      simulation.alpha(0.05).restart();
    });

  // ── Render labels ──
  labelEl = gLabels.selectAll("text")
    .data(simNodes)
    .enter()
    .append("text")
    .attr("font-family",    "'IBM Plex Mono', monospace")
    .attr("font-size",      "11px")
    .attr("fill",           "#ffffff")
    .attr("text-anchor",    "middle")
    .attr("pointer-events", "none")
    .attr("opacity",        d => labelOpacity(d))
    .text(d => d.name);

  // Set initial positions from pre-computed ticks before attaching tick handler
  ticked();

  // Apply current control state
  applyDayFilter();
  applyEdgeFilter();

  // Resume with a gentle alpha so the graph softly continues to settle
  simulation
    .on("tick", ticked)
    .alpha(0.1)
    .restart();
}

// ── Fetch + build ─────────────────────────────────────────────────────────────

async function fetchAndBuild(threshold) {
  try {
    const resp = await fetch(`/api/graph?threshold=${threshold.toFixed(2)}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (data.error) throw new Error(data.error);
    rawNodes = data.nodes;
    rawEdges = data.edges;
    buildGraph();
  } catch (err) {
    console.error("artistForceMap: failed to load graph —", err.message);
  }
}

// ── Wire up controls ──────────────────────────────────────────────────────────

function initControls() {
  // Spotify button
  const spotifyBtn = document.getElementById("spotifyBtn");
  if (window.AUTHENTICATED) {
    spotifyBtn.textContent = "LOGGED IN";
    spotifyBtn.disabled = true;
  }
  spotifyBtn.addEventListener("click", () => {
    window.location.href = "/login";
  });

  // Day filter buttons
  document.querySelectorAll(".day-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".day-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      dayFilter = btn.dataset.day;
      applyDayFilter();
    });
  });

  // Edge threshold slider — re-fetches on change (debounced 500ms)
  const thresholdSlider = document.getElementById("thresholdSlider");
  const thresholdValue  = document.getElementById("thresholdValue");
  thresholdSlider.addEventListener("input", () => {
    edgeThreshold = parseFloat(thresholdSlider.value);
    thresholdValue.textContent = edgeThreshold.toFixed(2);
    clearTimeout(thresholdDebounce);
    thresholdDebounce = setTimeout(() => fetchAndBuild(edgeThreshold), 500);
  });

  // Node size slider — live, no re-fetch
  const nodeSizeSlider = document.getElementById("nodeSizeSlider");
  const nodeSizeValue  = document.getElementById("nodeSizeValue");
  nodeSizeSlider.addEventListener("input", () => {
    nodeScale = parseFloat(nodeSizeSlider.value);
    nodeSizeValue.textContent = nodeScale.toFixed(1);
    if (!nodeEl) return;
    nodeEl .attr("r",  d => nodeRadius(d));
    labelEl.attr("y",  d => d.y - nodeRadius(d) - 4);
    simulation
      .force("collide", d3.forceCollide().radius(d => nodeRadius(d) + 2))
      .alpha(0.15)
      .restart();
  });

  // Similarity edges checkbox — live
  document.getElementById("similarityCheck").addEventListener("change", e => {
    showSimilarity = e.target.checked;
    applyEdgeFilter();
  });

  // Genre edges checkbox — live
  document.getElementById("genreCheck").addEventListener("change", e => {
    showGenre = e.target.checked;
    applyEdgeFilter();
  });
}

// ── Init ──────────────────────────────────────────────────────────────────────

initControls();
fetchAndBuild(edgeThreshold);
