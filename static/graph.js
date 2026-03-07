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
const THRESHOLD_LEVELS = [0.05, 0.10, 0.20, 0.30, 0.50];

let nodeScale      = 1.0;
let edgeThreshold  = THRESHOLD_LEVELS[2]; // default: 0.20
let showSimilarity = true;
let showGenre      = true;
let dayFilter      = "ALL";

let thresholdDebounce = null;
let dragMoved = false;

let currentAudio   = null;
let currentPlayBtn = null;
let openArtistName = null;
let pinnedDatum    = null;
let panelRequestId = 0;

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
  .on("click", () => {
    clearHover();
    if (pinnedDatum) {
      pinnedDatum.fx = null;
      pinnedDatum.fy = null;
      if (nodeEl) nodeEl.filter(n => n === pinnedDatum).attr("stroke", "none").attr("stroke-width", 0);
      pinnedDatum = null;
    }
    openArtistName = null;
    closePanel();
  });

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

// ── Artist panel ──────────────────────────────────────────────────────────────

const PLACEHOLDER_HASH = "2a96cbd8b46e442fc41c2b86b821562f";

function closePanel() {
  document.getElementById("artistPanel").classList.remove("open");
  if (currentAudio)   { currentAudio.pause(); currentAudio = null; }
  if (currentPlayBtn) { currentPlayBtn.textContent = "▶"; currentPlayBtn = null; }
}

function wirePlayButtons() {
  document.querySelectorAll(".play-btn").forEach(btn => {
    btn.addEventListener("click", function(e) {
      e.stopPropagation();
      const previewUrl = this.dataset.preview;
      if (!previewUrl) return;

      if (currentAudio && currentPlayBtn === this) {
        currentAudio.pause();
        currentAudio   = null;
        currentPlayBtn = null;
        this.textContent = "▶";
        return;
      }
      if (currentAudio) {
        currentAudio.pause();
        if (currentPlayBtn) { currentPlayBtn.textContent = "▶"; }
      }
      const audio = new Audio(previewUrl);
      audio.play();
      currentAudio   = audio;
      currentPlayBtn = this;
      this.textContent = "▐▐";
      audio.addEventListener("ended", () => {
        this.textContent = "▶";
        currentAudio   = null;
        currentPlayBtn = null;
      });
    });
  });
}

function renderTrackList(tracks) {
  if (!tracks || !tracks.length) {
    return `<div style="font-size:9px;color:rgba(255,255,255,0.2);padding:16px;text-align:center">NO TRACKS AVAILABLE</div>`;
  }
  const header = `<div style="font-size:9px;letter-spacing:0.12em;color:rgba(255,255,255,0.3);margin:0 16px 8px">TOP TRACKS</div>`;
  const rows = tracks.map(track => {
    const preview = track.preview_url || "";
    const art     = track.album_art   || "/static/placeholder_artist.jpeg";
    const disabledStyle = preview ? "" : ";opacity:0.25;pointer-events:none";
    return (
      `<div class="track-row" style="display:flex;align-items:center;padding:8px 16px;gap:10px;cursor:pointer"` +
      ` onmouseenter="this.style.background='rgba(255,255,255,0.04)'" onmouseleave="this.style.background=''">` +
      `<img src="${art}" style="width:40px;height:40px;object-fit:cover"` +
      ` onerror="this.src='/static/placeholder_artist.jpeg'" />` +
      `<span style="font-size:10px;flex:1;color:rgba(255,255,255,0.72)">${track.name}</span>` +
      `<button class="play-btn" data-preview="${preview}"` +
      ` style="font-size:12px;color:rgba(255,255,255,0.4);background:none;border:none;cursor:pointer${disabledStyle}">▶</button>` +
      `</div>`
    );
  }).join("");
  return header + rows;
}

async function openPanel(artistName) {
  const myId = ++panelRequestId;

  // Phase 1: fetch static data, render immediately
  const resp = await fetch("/api/artist/" + encodeURIComponent(artistName));
  if (!resp.ok) return;
  const d = await resp.json();

  const imgUrl = d.image_url || "";
  const isPlaceholder = !imgUrl || imgUrl.includes(PLACEHOLDER_HASH);
  const imgSrc = isPlaceholder ? "/static/placeholder_artist.jpeg" : imgUrl;

  const metaParts = [d.genre, d.stage, d.day].filter(Boolean);

  const tagsHtml = (d.tags || []).map(tag =>
    `<span style="display:inline-block;background:rgba(255,255,255,0.07);border-radius:3px;` +
    `padding:2px 6px;font-size:9px;color:rgba(255,255,255,0.4);margin:0 4px 4px 0">${tag}</span>`
  ).join("");

  const bioHtml = d.bio
    ? `<div style="font-size:10px;line-height:1.6;color:rgba(255,255,255,0.55);` +
      `margin:0 16px 16px;border-top:1px solid rgba(255,255,255,0.06);padding-top:12px">${d.bio}</div>`
    : "";

  document.getElementById("panelContent").innerHTML =
    `<img src="${imgSrc}" style="width:100%;object-fit:cover;max-height:280px;display:block"` +
    ` onerror="this.src='/static/placeholder_artist.jpeg'" />` +
    `<div style="font-size:15px;font-weight:bold;color:white;margin:12px 16px 4px">${d.name}</div>` +
    `<div style="font-size:10px;color:rgba(255,255,255,0.45);margin:0 16px 8px">${metaParts.join(" · ")}</div>` +
    `<div style="margin:0 16px 12px">${tagsHtml}</div>` +
    bioHtml +
    `<div id="tracksLoading" style="display:flex;justify-content:center;align-items:center;padding:24px 0">` +
    `<div class="spinner"></div></div>`;

  document.getElementById("artistPanel").classList.add("open");

  // Phase 2: fetch fresh preview URLs asynchronously
  try {
    const tracksResp = await fetch("/api/artist/" + encodeURIComponent(artistName) + "/tracks");
    if (myId !== panelRequestId) return; // user navigated to a different node
    const tracksData = tracksResp.ok ? await tracksResp.json() : { tracks: [] };
    if (myId !== panelRequestId) return;

    const tracksEl = document.getElementById("tracksLoading");
    if (tracksEl) {
      tracksEl.outerHTML = renderTrackList(tracksData.tracks || []);
    }
    wirePlayButtons();
  } catch (_) {
    if (myId !== panelRequestId) return;
    const tracksEl = document.getElementById("tracksLoading");
    if (tracksEl) {
      tracksEl.outerHTML = `<div style="font-size:9px;color:rgba(255,255,255,0.2);padding:16px;text-align:center">NO TRACKS AVAILABLE</div>`;
    }
  }
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

      if (openArtistName === d.name && d.fx !== null && d.fx !== undefined) {
        // Same pinned node → unpin, keep panel open
        d.fx = null;
        d.fy = null;
        pinnedDatum = null;
        d3.select(event.currentTarget).attr("stroke", "none").attr("stroke-width", 0);
      } else {
        // Unpin previous node if different
        if (pinnedDatum && pinnedDatum !== d) {
          pinnedDatum.fx = null;
          pinnedDatum.fy = null;
          nodeEl.filter(n => n === pinnedDatum).attr("stroke", "none").attr("stroke-width", 0);
        }
        // Pin this node and open panel
        d.fx = d.x;
        d.fy = d.y;
        pinnedDatum    = d;
        openArtistName = d.name;
        d3.select(event.currentTarget)
          .attr("stroke",       "rgba(255,255,255,0.45)")
          .attr("stroke-width", 1.5);
        openPanel(d.name);
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

function updateAuthUI() {
  const spotifyCol      = document.getElementById("spotifyCol");
  const spotifyBtn      = document.getElementById("spotifyBtn");
  const spotifyConnected = document.getElementById("spotifyConnected");
  const spotifyUserLabel = document.getElementById("spotifyUserLabel");
  const lastfmCol       = document.getElementById("lastfmCol");
  const lastfmConnected = document.getElementById("lastfmConnected");
  const lastfmUserLabel = document.getElementById("lastfmUserLabel");
  const lastfmInput     = document.getElementById("lastfmInput");

  if (window.AUTHENTICATED) {
    spotifyBtn.style.display       = "none";
    spotifyConnected.style.display = "block";
    spotifyUserLabel.textContent   = "Connected as " + (window.SPOTIFY_DISPLAY_NAME || "user");
    lastfmCol.style.display        = "none";
  } else if (window.LASTFM_USER) {
    spotifyBtn.style.display       = "none";
    spotifyCol.style.display       = "none";
    lastfmInput.style.display      = "none";
    lastfmConnected.style.display  = "block";
    lastfmUserLabel.textContent    = window.LASTFM_USER;
  } else {
    spotifyCol.style.display       = "block";
    spotifyBtn.style.display       = "block";
    spotifyConnected.style.display = "none";
    lastfmCol.style.display        = "block";
    lastfmInput.style.display      = "block";
    lastfmConnected.style.display  = "none";
  }
}

function initControls() {
  // Artist panel close button
  document.getElementById("panelClose").addEventListener("click", () => {
    if (pinnedDatum) {
      pinnedDatum.fx = null;
      pinnedDatum.fy = null;
      if (nodeEl) nodeEl.filter(n => n === pinnedDatum).attr("stroke", "none").attr("stroke-width", 0);
      pinnedDatum = null;
    }
    openArtistName = null;
    closePanel();
  });

  // Spotify connect
  document.getElementById("spotifyBtn").addEventListener("click", () => {
    window.location.href = "/login";
  });

  // Spotify disconnect
  document.getElementById("spotifyDisconnect").addEventListener("click", async () => {
    await fetch("/api/spotify/logout", { method: "POST" });
    window.AUTHENTICATED = false;
    window.SPOTIFY_DISPLAY_NAME = null;
    updateAuthUI();
    fetchAndBuild(edgeThreshold);
  });

  // Last.fm GO
  const lastfmUsername = document.getElementById("lastfmUsername");
  const lastfmError    = document.getElementById("lastfmError");
  lastfmUsername.addEventListener("input", () => {
    lastfmError.style.display = "none";
  });
  document.getElementById("lastfmGo").addEventListener("click", async () => {
    const username = lastfmUsername.value.trim();
    if (!username) return;
    const resp = await fetch("/api/lastfm/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username }),
    });
    const data = await resp.json();
    if (data.ok) {
      window.LASTFM_USER = username;
      window.AUTHENTICATED = false;
      updateAuthUI();
      fetchAndBuild(edgeThreshold);
    } else {
      lastfmError.style.display = "block";
    }
  });
  lastfmUsername.addEventListener("keydown", e => {
    if (e.key === "Enter") document.getElementById("lastfmGo").click();
  });

  // Last.fm disconnect
  document.getElementById("lastfmDisconnect").addEventListener("click", async () => {
    await fetch("/api/lastfm/logout", { method: "POST" });
    window.LASTFM_USER = null;
    updateAuthUI();
    fetchAndBuild(edgeThreshold);
  });

  updateAuthUI();

  // Day filter buttons
  document.querySelectorAll(".day-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".day-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      dayFilter = btn.dataset.day;
      applyDayFilter();
    });
  });

  // Edge threshold slider — 5 discrete levels, re-fetches on change (debounced 500ms)
  const thresholdSlider = document.getElementById("thresholdSlider");
  const thresholdValue  = document.getElementById("thresholdValue");
  thresholdSlider.addEventListener("input", () => {
    const idx = parseInt(thresholdSlider.value, 10);
    edgeThreshold = THRESHOLD_LEVELS[idx];
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
