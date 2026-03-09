// ── Constants ────────────────────────────────────────────────────────────────

const isMobile = window.innerWidth < 768 || ('ontouchstart' in window);

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

// ── Utilities ─────────────────────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

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

let discoveryMode    = false;
let discovered       = new Set(); // fully discovered artist names
let fringe           = new Set(); // undiscovered nodes one degree from lastDiscovered
let subgraph         = new Set(); // lastDiscovered + ALL its direct neighbors (discovered + fringe)
let ambassadors      = new Set(); // highest-score node from each undiscovered, disconnected subgraph
let userSeeds        = new Set(); // artist names matched from Spotify/Last.fm data
let lastDiscovered   = null;      // name of the most recently visited discovered node
let allEdgesForFrontier = []; // populated once from /api/graph?threshold=0.05
let frontierEdgesLoaded = false;

let thresholdDebounce = null;
let dragMoved = false;

let currentAudio   = null;
let currentPlayBtn = null;
let openArtistName = null;
let pinnedDatum    = null;
let panelRequestId = 0;
let drawerState    = 'hidden';

let playlist           = [];   // { artist, name, album_art, deezer_url }
let expandedTrackIndex = null;
let currentTracks      = [];

// ── Viewport ─────────────────────────────────────────────────────────────────

const W = window.innerWidth;
const H = isMobile ? Math.floor(window.innerHeight * 0.55) : window.innerHeight;

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
    if (isMobile) {
      if (drawerState === 'expanded') {
        setDrawerState('collapsed');
        return;
      } else if (drawerState === 'collapsed' || drawerState === 'peek') {
        unpinCurrentNode();
        openArtistName = null;
        setDrawerState('hidden');
        closePanel();
        return;
      }
      return;
    }
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

// ── Service link SVG icons ────────────────────────────────────────────────────

const SPOTIFY_SVG = `<svg viewBox="0 0 24 24" style="width:18px;height:18px"><path fill="currentColor" d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/></svg>`;

const YOUTUBE_SVG = `<svg viewBox="0 0 24 24" style="width:18px;height:18px"><path fill="currentColor" d="M23.495 6.205a3.007 3.007 0 0 0-2.088-2.088c-1.87-.501-9.396-.501-9.396-.501s-7.507-.01-9.396.501A3.007 3.007 0 0 0 .527 6.205a31.247 31.247 0 0 0-.522 5.805 31.247 31.247 0 0 0 .522 5.783 3.007 3.007 0 0 0 2.088 2.088c1.868.502 9.396.502 9.396.502s7.506 0 9.396-.502a3.007 3.007 0 0 0 2.088-2.088 31.247 31.247 0 0 0 .5-5.783 31.247 31.247 0 0 0-.5-5.805zM9.609 15.601V8.408l6.264 3.602z"/></svg>`;

const APPLE_SVG = `<svg viewBox="0 0 24 24" style="width:18px;height:18px"><path fill="currentColor" d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>`;

// ── Artist panel ──────────────────────────────────────────────────────────────

const PLACEHOLDER_HASH = "2a96cbd8b46e442fc41c2b86b821562f";

function closePanel() {
  document.getElementById("artistPanel").classList.remove("open");
  if (currentAudio)   { currentAudio.pause(); currentAudio = null; }
  if (currentPlayBtn) { currentPlayBtn.textContent = "▶"; currentPlayBtn = null; }
  collapseSubmenu();
  // Return to full discovered-node view when the panel is dismissed
  if (discoveryMode && lastDiscovered !== null) {
    window._pendingDiscovery = null;
    lastDiscovered = null;
    fringe.clear();
    subgraph.clear();
    updateAmbassadors();
    updateDiscoveryVisuals();
    expandMenu();
  }
}

function collapseSubmenu() {
  const existing = document.querySelector(".track-submenu");
  if (existing) existing.remove();
  expandedTrackIndex = null;
}

function buildServiceLinks(artist, trackName, btnClass, svgSize) {
  const enc = encodeURIComponent;
  const a   = enc(artist);
  const n   = enc(trackName);
  const sz  = svgSize || 18;
  const spotifySvg = SPOTIFY_SVG.replace('width:18px;height:18px', `width:${sz}px;height:${sz}px`);
  const youtubeSvg = YOUTUBE_SVG.replace('width:18px;height:18px', `width:${sz}px;height:${sz}px`);
  const appleSvg   = APPLE_SVG.replace('width:18px;height:18px',   `width:${sz}px;height:${sz}px`);
  return (
    `<a href="https://open.spotify.com/search/${a}%20${n}" target="_blank" class="${btnClass}">${spotifySvg}</a>` +
    `<a href="https://music.youtube.com/search?q=${a}+${n}" target="_blank" class="${btnClass}">${youtubeSvg}</a>` +
    `<a href="https://music.apple.com/search?term=${a}+${n}" target="_blank" class="${btnClass}">${appleSvg}</a>`
  );
}

function expandSubmenu(idx, rowEl) {
  collapseSubmenu();
  expandedTrackIndex = idx;
  const track  = currentTracks[idx];
  const artist = openArtistName || "";

  const addBtnInner = window.AUTHENTICATED
    ? `<span class="add-btn-icon"></span><span class="rainbow-text">＋ Queue</span>`
    : `<span class="rainbow-text">＋ My Playlist</span>`;

  const sub = document.createElement("div");
  sub.className = "track-submenu";
  sub.innerHTML =
    buildServiceLinks(artist, track.name, "sub-svc-btn", 18) +
    `<button class="add-playlist-btn">${addBtnInner}</button>`;

  rowEl.insertAdjacentElement("afterend", sub);

  requestAnimationFrame(() => {
    sub.style.maxHeight = "60px";
    sub.style.opacity   = "1";
  });

  sub.querySelector(".add-playlist-btn").addEventListener("click", () => {
    addToPlaylist(track, sub);
  });
}

function wireTrackInteractions() {
  document.querySelectorAll(".track-row").forEach(row => {
    const idx = parseInt(row.dataset.trackIndex, 10);

    // Row click (not on play button) → toggle submenu
    row.addEventListener("click", function(e) {
      if (e.target.closest(".play-btn")) return;
      if (expandedTrackIndex === idx) {
        collapseSubmenu();
      } else {
        expandSubmenu(idx, this);
      }
    });

    // Play button → play/pause + expand submenu
    const btn = row.querySelector(".play-btn");
    if (btn) {
      btn.addEventListener("click", function(e) {
        e.stopPropagation();

        if (expandedTrackIndex !== idx) {
          expandSubmenu(idx, row);
        }

        const previewUrl = this.dataset.preview;
        if (!previewUrl) return;

        if (currentAudio && currentPlayBtn === this) {
          currentAudio.pause();
          currentAudio     = null;
          currentPlayBtn   = null;
          this.textContent = "▶";
          return;
        }
        if (currentAudio) {
          currentAudio.pause();
          if (currentPlayBtn) { currentPlayBtn.textContent = "▶"; }
        }
        const audio = new Audio(previewUrl);
        audio.play().then(() => {
          if (window._pendingDiscovery) {
            triggerDiscovery(window._pendingDiscovery);
            window._pendingDiscovery = null;
          }
        }).catch(() => {});
        currentAudio     = audio;
        currentPlayBtn   = this;
        this.textContent = "▐▐";
        audio.addEventListener("ended", () => {
          this.textContent = "▶";
          currentAudio   = null;
          currentPlayBtn = null;
        });
      });
    }
  });
}

function addToPlaylist(track, subEl) {
  playlist.push({
    artist:    openArtistName || "",
    name:      track.name,
    album_art: track.album_art || "",
    deezer_url: track.preview_url || "",
  });

  if (window._pendingDiscovery) {
    triggerDiscovery(window._pendingDiscovery);
    window._pendingDiscovery = null;
  }

  const saved = subEl.innerHTML;
  subEl.innerHTML = `<span style="color:rgba(255,255,255,0.6);font-size:10px;font-family:'IBM Plex Mono',monospace;letter-spacing:0.08em">✓ Added</span>`;
  setTimeout(() => {
    subEl.innerHTML = saved;
    subEl.querySelector(".add-playlist-btn").addEventListener("click", () => {
      addToPlaylist(track, subEl);
    });
  }, 1500);

  updateExportButton();
}

function syncHamburgerColor() {
  const btn = document.getElementById("menuToggle");
  if (!btn) return;
  btn.style.color = playlist.length > 0 ? "#1db954" : "";
}

function updateExportButton() {
  const row = document.getElementById("exportRow");
  const btn = document.getElementById("exportBtn");
  if (!row || !btn) return;
  if (playlist.length === 0) {
    row.style.display = "none";
    btn.classList.remove("active");
  } else {
    row.style.display = "block";
    btn.classList.add("active");
    btn.textContent = window.AUTHENTICATED
      ? `SPOTIFY PLAYLIST (${playlist.length})`
      : `MY PLAYLIST (${playlist.length})`;
  }
  syncHamburgerColor();
}

function openExportPanel() {
  renderExportPanel();
  const panel = document.getElementById("exportPanel");
  panel.style.display = "block";
  requestAnimationFrame(() => panel.classList.add("open"));
}

function closeExportPanel() {
  const panel = document.getElementById("exportPanel");
  panel.classList.remove("open");
  setTimeout(() => { panel.style.display = "none"; }, 260);
}

function renderExportPanel() {
  const panel = document.getElementById("exportPanel");
  const title = window.AUTHENTICATED ? "SPOTIFY PLAYLIST" : "MY PLAYLIST";

  const tracksHTML = playlist.map((track, i) => {
    const art = track.album_art || "/static/placeholder_artist.jpeg";
    return (
      `<div class="ep-track" data-ep-index="${i}" style="display:flex;align-items:center;padding:8px 12px;gap:8px;${!window.AUTHENTICATED ? "cursor:pointer;" : ""}">` +
      `<img src="${art}" style="width:36px;height:36px;object-fit:cover;flex-shrink:0" onerror="this.src='/static/placeholder_artist.jpeg'" />` +
      `<div style="flex:1;min-width:0">` +
      `<div style="font-size:10px;font-weight:500;color:rgba(255,255,255,0.8);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(track.name)}</div>` +
      `<div style="font-size:9px;color:rgba(255,255,255,0.4);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(track.artist)}</div>` +
      `</div>` +
      `<button class="ep-remove" data-ep-index="${i}" style="width:20px;height:20px;border-radius:50%;border:1px solid rgba(255,255,255,0.2);background:none;color:rgba(255,255,255,0.5);cursor:pointer;font-size:14px;line-height:1;display:flex;align-items:center;justify-content:center;flex-shrink:0">−</button>` +
      `</div>` +
      (!window.AUTHENTICATED ? `<div class="ep-service-links" data-ep-index="${i}" style="display:none;padding:4px 16px 8px;gap:8px;justify-content:center;align-items:center"></div>` : "")
    );
  }).join("");

  const footerHTML = window.AUTHENTICATED
    ? `<div style="padding:12px 16px;border-top:1px solid rgba(255,255,255,0.06)">` +
      `<button id="createSpotifyBtn" style="width:100%;background:none;border:1px solid #1db954;color:#1db954;font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:0.12em;padding:10px;cursor:pointer;transition:background 0.15s">CREATE SPOTIFY PLAYLIST</button>` +
      `<div id="spotifyCreateResult" style="margin-top:8px;font-size:9px;text-align:center;letter-spacing:0.08em"></div>` +
      `</div>`
    : `<div style="padding:8px 16px 12px;text-align:center;border-top:1px solid rgba(255,255,255,0.06)">` +
      `<span style="font-size:9px;color:rgba(255,255,255,0.3);letter-spacing:0.08em">TAP A TRACK TO OPEN IN YOUR STREAMING SERVICE</span>` +
      `</div>`;

  panel.innerHTML =
    `<div style="display:flex;align-items:center;padding:12px 16px;border-bottom:1px solid rgba(255,255,255,0.06)">` +
    `<button id="exportPanelBack" style="background:none;border:none;color:rgba(255,255,255,0.5);cursor:pointer;font-size:16px;padding:0;font-family:'IBM Plex Mono',monospace;margin-right:8px">←</button>` +
    `<span style="flex:1;text-align:center;font-size:10px;letter-spacing:0.14em;color:rgba(255,255,255,0.7)">${title} (${playlist.length})</span>` +
    `<div style="width:24px"></div>` +
    `</div>` +
    `<div id="epTrackList">${tracksHTML}</div>` +
    footerHTML;

  document.getElementById("exportPanelBack").addEventListener("click", closeExportPanel);

  panel.querySelectorAll(".ep-remove").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      playlist.splice(parseInt(btn.dataset.epIndex, 10), 1);
      updateExportButton();
      renderExportPanel();
    });
  });

  if (!window.AUTHENTICATED) {
    let expandedEpIdx = null;
    panel.querySelectorAll(".ep-track").forEach(row => {
      row.addEventListener("click", function() {
        const idx   = parseInt(this.dataset.epIndex, 10);
        const track = playlist[idx];

        panel.querySelectorAll(".ep-track").forEach(r => r.style.boxShadow = "");
        panel.querySelectorAll(".ep-service-links").forEach(sl => {
          sl.style.display = "none";
        });

        if (expandedEpIdx === idx) {
          expandedEpIdx = null;
          return;
        }
        expandedEpIdx = idx;
        this.style.boxShadow = "0 0 0 1px rgba(255,255,255,0.25)";

        const serviceDiv = panel.querySelector(`.ep-service-links[data-ep-index="${idx}"]`);
        if (serviceDiv) {
          serviceDiv.style.display = "flex";
          serviceDiv.innerHTML = buildServiceLinks(track.artist, track.name, "ep-svc-btn", 14);
        }
      });
    });
  }

  const createBtn = document.getElementById("createSpotifyBtn");
  if (createBtn) {
    createBtn.addEventListener("click", createSpotifyPlaylist);
  }
}

async function createSpotifyPlaylist() {
  const btn    = document.getElementById("createSpotifyBtn");
  const result = document.getElementById("spotifyCreateResult");
  if (!btn || !result) return;

  btn.disabled = true;
  btn.innerHTML = `<span class="spinner" style="display:inline-block;margin:0 auto;width:16px;height:16px;border-width:2px"></span>`;

  try {
    const resp = await fetch("/api/spotify/create-playlist", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ tracks: playlist.map(t => ({ artist: t.artist, name: t.name })) }),
    });
    const data = await resp.json();
    if (data.ok) {
      btn.style.display = "none";
      result.innerHTML  =
        `<span style="color:#1db954">✓ PLAYLIST CREATED</span><br>` +
        `<a href="${escapeHtml(data.playlist_url)}" target="_blank" style="color:rgba(255,255,255,0.5);font-size:9px;letter-spacing:0.08em">OPEN IN SPOTIFY →</a>`;
    } else {
      btn.disabled = false;
      btn.textContent = "CREATE SPOTIFY PLAYLIST";
      result.style.color  = "rgba(255,100,100,0.8)";
      result.textContent  = data.error || "Failed to create playlist";
    }
  } catch (_) {
    btn.disabled = false;
    btn.textContent = "CREATE SPOTIFY PLAYLIST";
    result.style.color = "rgba(255,100,100,0.8)";
    result.textContent = "Network error";
  }
}

function renderTrackList(tracks) {
  currentTracks = tracks || [];
  if (!currentTracks.length) {
    return `<div style="font-size:9px;color:rgba(255,255,255,0.2);padding:16px;text-align:center">NO TRACKS AVAILABLE</div>`;
  }
  const header = `<div style="font-size:9px;letter-spacing:0.12em;color:rgba(255,255,255,0.3);margin:0 16px 8px">TOP TRACKS</div>`;
  const rows = currentTracks.map((track, idx) => {
    const preview = track.preview_url || "";
    const art     = track.album_art   || "/static/placeholder_artist.jpeg";
    const disabledStyle = preview ? "" : ";opacity:0.25;pointer-events:none";
    return (
      `<div class="track-row" data-track-index="${idx}" style="display:flex;align-items:center;padding:8px 16px;gap:10px;cursor:pointer"` +
      ` onmouseenter="this.style.background='rgba(255,255,255,0.04)'" onmouseleave="this.style.background=''">` +
      `<img src="${art}" style="width:40px;height:40px;object-fit:cover"` +
      ` onerror="this.src='/static/placeholder_artist.jpeg'" />` +
      `<span style="font-size:10px;flex:1;color:rgba(255,255,255,0.72)">${escapeHtml(track.name)}</span>` +
      `<button class="play-btn" data-preview="${preview}"` +
      ` style="font-size:12px;color:rgba(255,255,255,0.4);background:none;border:none;cursor:pointer${disabledStyle}">▶</button>` +
      `</div>`
    );
  }).join("");
  return header + rows;
}

function unpinCurrentNode() {
  if (!pinnedDatum) return;
  pinnedDatum.fx = null;
  pinnedDatum.fy = null;
  if (nodeEl) nodeEl.filter(n => n === pinnedDatum).attr("stroke", "none").attr("stroke-width", 0);
  pinnedDatum = null;
}

function setDrawerState(state) {
  drawerState = state;
  const drawer = document.getElementById("artistDrawer");
  if (!drawer) return;
  drawer.classList.remove("drawer-hidden", "drawer-collapsed", "drawer-expanded", "drawer-peek");
  drawer.classList.add("drawer-" + state);
  // When hiding, stop any playing audio and exit discovery subgraph
  if (state === 'hidden') {
    if (currentAudio) { currentAudio.pause(); currentAudio = null; }
    if (currentPlayBtn) {
      currentPlayBtn.textContent = "▶";
      currentPlayBtn.classList.remove("playing");
      currentPlayBtn = null;
    }
    collapseDrawerSubmenu();
    if (discoveryMode && lastDiscovered !== null) {
      window._pendingDiscovery = null;
      lastDiscovered = null;
      fringe.clear();
      subgraph.clear();
      updateAmbassadors();
      updateDiscoveryVisuals();
      expandMenu();
    }
  }
}

function openDrawer(artistName) {
  if (isMobile) {
    const datum = rawNodes.find(n => n.name === artistName) || { name: artistName };
    setDrawerState('collapsed');
    populateDrawer(datum);
  } else {
    openPanel(artistName);
  }
}

let drawerRequestId = 0;
let drawerArtistName = null;
let drawerTracks = [];
let drawerExpandedIdx = null;

function collapseDrawerSubmenu() {
  const existing = document.querySelector(".drawer-track-submenu.open");
  if (existing) existing.classList.remove("open");
  drawerExpandedIdx = null;
}

async function populateDrawer(d) {
  const myId = ++drawerRequestId;
  drawerArtistName = d.name;
  drawerTracks = [];
  drawerExpandedIdx = null;

  // ── Hero ──
  const imgUrl = d.image_url || "";
  const isPlaceholder = !imgUrl || imgUrl.includes(PLACEHOLDER_HASH);
  const imgSrc = isPlaceholder ? "/static/placeholder_artist.jpeg" : imgUrl;
  const hero = document.getElementById("drawerHero");
  hero.style.backgroundImage = `url('${imgSrc}')`;
  document.getElementById("drawerHeroName").textContent = d.name || "";

  // ── Meta ──
  const metaParts = [d.genre, d.stage, d.day].filter(Boolean);
  document.getElementById("drawerMetaLine").textContent = metaParts.join(" · ");
  document.getElementById("drawerMetaTags").innerHTML = (d.tags || [])
    .map(tag => `<span class="drawer-tag">${escapeHtml(tag)}</span>`)
    .join("");

  // ── Tracks: loading state ──
  const tracksEl = document.getElementById("drawerTracks");
  tracksEl.innerHTML =
    `<div style="display:flex;justify-content:center;align-items:center;padding:24px 0">` +
    `<div class="spinner"></div></div>`;

  const bioEl = document.getElementById("drawerBio");
  bioEl.style.display = "none";
  bioEl.textContent = "";

  // ── Fetch tracks ──
  try {
    const tracksResp = await fetch("/api/artist/" + encodeURIComponent(d.name) + "/tracks");
    if (myId !== drawerRequestId) return;
    const tracksData = tracksResp.ok ? await tracksResp.json() : { tracks: [] };
    if (myId !== drawerRequestId) return;

    drawerTracks = tracksData.tracks || [];

    if (!drawerTracks.length) {
      tracksEl.innerHTML =
        `<div style="font-size:9px;color:rgba(255,255,255,0.2);padding:16px;text-align:center;` +
        `font-family:'IBM Plex Mono',monospace;letter-spacing:0.1em">NO TRACKS AVAILABLE</div>`;
    } else {
      const header =
        `<div style="font-size:9px;letter-spacing:0.12em;color:rgba(255,255,255,0.3);` +
        `padding:8px 16px 4px;font-family:'IBM Plex Mono',monospace">TOP TRACKS</div>`;

      const rows = drawerTracks.map((track, idx) => {
        const art     = track.album_art || "/static/placeholder_artist.jpeg";
        const preview = track.preview_url || "";
        const disabledStyle = preview ? "" : "opacity:0.25;pointer-events:none;";
        return (
          `<div class="drawer-track-row" data-drawer-track-index="${idx}">` +
          `<img class="drawer-track-art" src="${escapeHtml(art)}"` +
          ` onerror="this.src='/static/placeholder_artist.jpeg'" />` +
          `<div class="drawer-track-info">` +
          `<div class="drawer-track-name">${escapeHtml(track.name)}</div>` +
          `<div class="drawer-track-artist">${escapeHtml(d.name)}</div>` +
          `</div>` +
          `<button class="drawer-play-btn" data-preview="${escapeHtml(preview)}"` +
          ` style="${disabledStyle}">▶</button>` +
          `</div>` +
          `<div class="drawer-track-submenu" data-drawer-submenu-index="${idx}">` +
          buildServiceLinks(d.name, track.name, "sub-svc-btn", 18) +
          `<button class="add-playlist-btn" data-drawer-add-index="${idx}">` +
          (window.AUTHENTICATED
            ? `<span class="add-btn-icon"></span><span class="rainbow-text">＋ Queue</span>`
            : `<span class="rainbow-text">＋ My Playlist</span>`) +
          `</button>` +
          `</div>`
        );
      }).join("");

      tracksEl.innerHTML = header + rows;
      wireDrawerTrackInteractions();
    }
  } catch (_) {
    if (myId !== drawerRequestId) return;
    tracksEl.innerHTML =
      `<div style="font-size:9px;color:rgba(255,255,255,0.2);padding:16px;text-align:center;` +
      `font-family:'IBM Plex Mono',monospace;letter-spacing:0.1em">NO TRACKS AVAILABLE</div>`;
  }

  // ── Fetch bio (may already be on datum, else fetch artist endpoint) ──
  try {
    const bio = d.bio || await (async () => {
      const r = await fetch("/api/artist/" + encodeURIComponent(d.name));
      if (!r.ok) return null;
      const data = await r.json();
      return data.bio || null;
    })();
    if (myId !== drawerRequestId) return;
    if (bio) {
      bioEl.textContent = bio;
      bioEl.style.display = "block";
    }
  } catch (_) { /* bio is optional */ }
}

function wireDrawerTrackInteractions() {
  const tracksEl = document.getElementById("drawerTracks");

  tracksEl.querySelectorAll(".drawer-track-row").forEach(row => {
    const idx = parseInt(row.dataset.drawerTrackIndex, 10);
    const submenu = tracksEl.querySelector(`.drawer-track-submenu[data-drawer-submenu-index="${idx}"]`);

    // Row tap (not on play btn) → expand drawer if collapsed, then toggle submenu
    row.addEventListener("click", function(e) {
      if (e.target.closest(".drawer-play-btn")) return;
      if (drawerState === 'collapsed') setDrawerState('expanded');
      if (drawerExpandedIdx === idx) {
        collapseDrawerSubmenu();
      } else {
        collapseDrawerSubmenu();
        drawerExpandedIdx = idx;
        if (submenu) submenu.classList.add("open");
      }
    });

    // Add-to-playlist button
    if (submenu) {
      submenu.querySelector(".add-playlist-btn").addEventListener("click", e => {
        e.stopPropagation();
        const track = drawerTracks[idx];
        addToPlaylist(track, submenu);
      });
    }

    // Play button
    const playBtn = row.querySelector(".drawer-play-btn");
    if (playBtn) {
      playBtn.addEventListener("click", function(e) {
        e.stopPropagation();

        // Also open submenu
        if (drawerExpandedIdx !== idx) {
          collapseDrawerSubmenu();
          drawerExpandedIdx = idx;
          if (submenu) submenu.classList.add("open");
        }

        const previewUrl = this.dataset.preview;
        if (!previewUrl) return;

        if (currentAudio && currentPlayBtn === this) {
          currentAudio.pause();
          currentAudio = null;
          currentPlayBtn = null;
          this.textContent = "▶";
          this.classList.remove("playing");
          return;
        }
        if (currentAudio) {
          currentAudio.pause();
          if (currentPlayBtn) {
            currentPlayBtn.textContent = "▶";
            currentPlayBtn.classList.remove("playing");
          }
        }
        const audio = new Audio(previewUrl);
        audio.play().catch(() => {});
        currentAudio = audio;
        currentPlayBtn = this;
        this.textContent = "▐▐";
        this.classList.add("playing");
        audio.addEventListener("ended", () => {
          this.textContent = "▶";
          this.classList.remove("playing");
          currentAudio = null;
          currentPlayBtn = null;
        });
      });
    }
  });
}

async function openPanel(artistName) {
  collapseSubmenu();
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
    `padding:2px 6px;font-size:9px;color:rgba(255,255,255,0.4);margin:0 4px 4px 0">${escapeHtml(tag)}</span>`
  ).join("");

  const bioHtml = d.bio
    ? `<div style="font-size:10px;line-height:1.6;color:rgba(255,255,255,0.55);` +
      `margin:0 16px 16px;border-top:1px solid rgba(255,255,255,0.06);padding-top:12px">${escapeHtml(d.bio)}</div>`
    : "";

  document.getElementById("panelContent").innerHTML =
    `<img src="${imgSrc}" style="width:100%;object-fit:cover;max-height:280px;display:block"` +
    ` onerror="this.src='/static/placeholder_artist.jpeg'" />` +
    `<div style="font-size:15px;font-weight:bold;color:white;margin:12px 16px 4px">${escapeHtml(d.name)}</div>` +
    `<div style="font-size:10px;color:rgba(255,255,255,0.45);margin:0 16px 8px">${metaParts.map(escapeHtml).join(" · ")}</div>` +
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
    wireTrackInteractions();
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
  // Dim all edges; highlight hovered + lastDiscovered 1-degree edges
  edgeEl.attr("opacity", e => {
    if (e.type === "similarity" && !showSimilarity) return 0;
    if (e.type === "genre"      && !showGenre)      return 0;
    if (e.source === d || e.target === d) return edgeBaseOpacity(e);
    // Preserve lastDiscovered 1-degree highlights in discovery mode
    if (discoveryMode && lastDiscovered) {
      const srcName = typeof e.source === "object" ? e.source.name : e.source;
      const tgtName = typeof e.target === "object" ? e.target.name : e.target;
      if (srcName === lastDiscovered || tgtName === lastDiscovered) {
        const other = srcName === lastDiscovered ? tgtName : srcName;
        if (discoveryVisible(other)) return 0.45;
      }
    }
    return 0.02;
  });

  // Dim all labels; show hovered node's label
  labelEl.attr("opacity", l => (l === d ? 1.0 : (l.score >= 0.1 ? 0.05 : 0)));

  // Tooltip
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
  if (labelEl) {
    if (discoveryMode) {
      labelEl.attr("opacity", d => {
        if (discoveryVisible(d.name)) return labelOpacity(d);
        return 0;
      });
    } else {
      labelEl.attr("opacity", d => labelOpacity(d));
    }
  }
  tooltip.style("display", "none");
}

// ── Filter functions (called on control changes) ──────────────────────────────

// Returns true if the named node should be visible in the current discovery state.
// When a node is selected: the full 1-degree subgraph (lastDiscovered + all direct
// neighbors, both discovered and undiscovered fringe) is shown.
// When no node is selected: all discovered nodes are shown.
function discoveryVisible(name) {
  if (lastDiscovered) return subgraph.has(name);
  return discovered.has(name) || ambassadors.has(name);
}

function applyDayFilter() {
  if (!nodeEl) return;
  const target = dayFilter === "ALL" ? null : DAY_MAP[dayFilter];
  const visible = d => !target || d.day === target;

  nodeEl.style("display", d => {
    if (!visible(d)) return "none";
    if (discoveryMode && !discoveryVisible(d.name)) return "none";
    return null;
  });
  labelEl.style("display", d => {
    if (!visible(d)) return "none";
    if (discoveryMode && !discoveryVisible(d.name)) return "none";
    return null;
  });
  edgeEl .style("display", e => {
    // After 300 ticks, e.source / e.target are node objects
    const src = e.source;
    const tgt = e.target;
    return visible(src) && visible(tgt) ? null : "none";
  });
}

function applyEdgeFilter() {
  if (!edgeEl) return;
  if (discoveryMode) {
    edgeEl.attr("opacity", e => {
      const srcName = typeof e.source === "object" ? e.source.name : e.source;
      const tgtName = typeof e.target === "object" ? e.target.name : e.target;
      // 1-degree subgraph of lastDiscovered: show edges to discovered AND fringe
      if (lastDiscovered && (srcName === lastDiscovered || tgtName === lastDiscovered)) {
        const other = srcName === lastDiscovered ? tgtName : srcName;
        if (discoveryVisible(other)) return 0.45;
      }
      // No node selected: show discovered↔discovered edges normally
      if (!lastDiscovered && discovered.has(srcName) && discovered.has(tgtName)) return edgeBaseOpacity(e);
      return 0;
    });
  } else {
    edgeEl.attr("opacity", e => edgeBaseOpacity(e));
  }
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

      // Discovery mode: fringe or ambassador node → open panel, set pending discovery
      if (discoveryMode && (fringe.has(d.name) || ambassadors.has(d.name)) && !discovered.has(d.name)) {
        window._pendingDiscovery = d.name;
        updateDiscoveryVisuals();
        openDrawer(d.name);
        return;
      }
      // Discovery mode: non-visible undiscovered node → inert
      if (discoveryMode && !discovered.has(d.name) && !fringe.has(d.name) && !ambassadors.has(d.name)) {
        return;
      }
      // Discovery mode: clicking a discovered node shifts the fringe to its neighbors
      if (discoveryMode && discovered.has(d.name)) {
        lastDiscovered = d.name;
        recalcFringe();
        updateDiscoveryVisuals();
        zoomToSubgraph();
        minimizeMenu();
      }

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
          .attr("stroke",       "#FFD700")
          .attr("stroke-width", 2.5);
        openDrawer(d.name);
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

  // If discovery mode is on, re-seed after graph rebuild
  if (discoveryMode) seedDiscovery();

  // Resume with a gentle alpha so the graph softly continues to settle
  simulation
    .on("tick", ticked)
    .alpha(0.1)
    .restart();
}

// ── Fetch + build ─────────────────────────────────────────────────────────────

function _graphStatusEl() {
  let el = document.getElementById("graphStatusOverlay");
  if (!el) {
    el = document.createElement("div");
    el.id = "graphStatusOverlay";
    Object.assign(el.style, {
      position:   "fixed",
      inset:      "0",
      display:    "flex",
      alignItems: "center",
      justifyContent: "center",
      pointerEvents:  "none",
      zIndex:     "5",
    });
    document.body.appendChild(el);
  }
  return el;
}

function _showGraphLoading() {
  const el = _graphStatusEl();
  el.style.display = "flex";
  el.innerHTML =
    `<div style="display:flex;flex-direction:column;align-items:center;gap:6px">` +
    `<span style="font-family:'IBM Plex Mono',monospace;font-size:11px;` +
    `letter-spacing:0.12em;color:rgba(255,255,255,0.3)">LOADING…</span>` +
    `<span style="font-family:'IBM Plex Mono',monospace;font-size:10px;` +
    `letter-spacing:0.08em;color:rgba(255,255,255,0.3);opacity:0.4">first load may take ~30s</span>` +
    `</div>`;
}

function _showGraphError(msg) {
  const el = _graphStatusEl();
  el.style.display = "flex";
  el.innerHTML =
    `<span style="font-family:'IBM Plex Mono',monospace;font-size:11px;` +
    `letter-spacing:0.1em;color:rgba(255,100,100,0.6)">${escapeHtml(msg)}</span>`;
}

function _hideGraphStatus() {
  const el = document.getElementById("graphStatusOverlay");
  if (el) el.style.display = "none";
}

async function fetchAndBuild(threshold) {
  _showGraphLoading();
  try {
    // Fetch frontier edges once (0.05 threshold) for discovery mode connectivity
    if (!frontierEdgesLoaded) {
      frontierEdgesLoaded = true;
      fetch("/api/graph?threshold=0.05")
        .then(r => r.ok ? r.json() : null)
        .then(data => { if (data && data.edges) allEdgesForFrontier = data.edges; })
        .catch(() => {});
    }
    const resp = await fetch(`/api/graph?threshold=${threshold.toFixed(2)}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (data.error) throw new Error(data.error);
    rawNodes  = data.nodes;
    rawEdges  = data.edges;
    userSeeds = new Set(data.user_seeds || []);
    buildGraph();
    _hideGraphStatus();
  } catch (err) {
    console.error("artistForceMap: failed to load graph —", err.message);
    _showGraphError("Failed to load graph. Please refresh the page.");
  }
}

// ── Discovery mode ────────────────────────────────────────────────────────────

function seedDiscovery() {
  discovered.clear();
  fringe.clear();
  subgraph.clear();
  ambassadors.clear();
  lastDiscovered = null;

  let seeds;
  if (userSeeds.size > 0) {
    // User has Spotify/Last.fm data: prioritize those artists
    const userNodes = simNodes
      .filter(n => userSeeds.has(n.name))
      .sort((a, b) => b.score - a.score);

    if (userNodes.length >= 20) {
      seeds = userNodes.slice(0, 20);
    } else {
      // Fill remaining slots from the rest of the graph sorted by score
      const userNameSet = new Set(userNodes.map(n => n.name));
      const rest = simNodes
        .filter(n => !userNameSet.has(n.name))
        .sort((a, b) => b.score - a.score);
      seeds = [...userNodes, ...rest].slice(0, 20);
    }
  } else {
    // No user data: top 20 by score
    seeds = [...simNodes]
      .sort((a, b) => b.score - a.score)
      .slice(0, 20);
  }

  seeds.forEach(n => discovered.add(n.name));
  // Fringe starts empty; it's computed when the user first clicks a discovered node
  lastDiscovered = null;
  updateAmbassadors();
  updateDiscoveryVisuals();
}

function recalcFringe() {
  fringe.clear();
  subgraph.clear();

  if (lastDiscovered) {
    subgraph.add(lastDiscovered);
    // Use rawEdges (current display threshold) so every fringe node has a visible edge
    for (const e of rawEdges) {
      const src = typeof e.source === "object" ? e.source.name : e.source;
      const tgt = typeof e.target === "object" ? e.target.name : e.target;
      if (src === lastDiscovered) {
        subgraph.add(tgt);
        if (!discovered.has(tgt)) fringe.add(tgt);
      }
      if (tgt === lastDiscovered) {
        subgraph.add(src);
        if (!discovered.has(src)) fringe.add(src);
      }
    }
  }

}

function updateAmbassadors() {
  ambassadors.clear();

  // All undiscovered node names
  const undiscovered = new Set(
    simNodes.filter(n => !discovered.has(n.name)).map(n => n.name)
  );
  if (undiscovered.size === 0) return;

  // Find undiscovered nodes that have at least one edge to a discovered node
  const reachable = new Set();
  for (const e of rawEdges) {
    const src = typeof e.source === "object" ? e.source.name : e.source;
    const tgt = typeof e.target === "object" ? e.target.name : e.target;
    if (discovered.has(src) && undiscovered.has(tgt)) reachable.add(tgt);
    if (discovered.has(tgt) && undiscovered.has(src)) reachable.add(src);
  }

  // Unreachable = undiscovered nodes with no edge to any discovered node
  const unreachable = new Set([...undiscovered].filter(n => !reachable.has(n)));
  if (unreachable.size === 0) return;

  // Build adjacency among unreachable nodes only
  const adj = new Map([...unreachable].map(n => [n, []]));
  for (const e of rawEdges) {
    const src = typeof e.source === "object" ? e.source.name : e.source;
    const tgt = typeof e.target === "object" ? e.target.name : e.target;
    if (unreachable.has(src) && unreachable.has(tgt)) {
      adj.get(src).push(tgt);
      adj.get(tgt).push(src);
    }
  }

  // BFS: find connected components, elect highest-score node as ambassador
  const visited = new Set();
  const nodeByName = new Map(simNodes.map(n => [n.name, n]));
  for (const start of unreachable) {
    if (visited.has(start)) continue;
    const component = [];
    const queue = [start];
    visited.add(start);
    while (queue.length > 0) {
      const name = queue.shift();
      component.push(name);
      for (const neighbor of (adj.get(name) || [])) {
        if (!visited.has(neighbor)) { visited.add(neighbor); queue.push(neighbor); }
      }
    }
    const best = component
      .map(name => nodeByName.get(name))
      .filter(Boolean)
      .sort((a, b) => b.score - a.score)[0];
    if (best) ambassadors.add(best.name);
  }
}

function updateDiscoveryVisuals() {
  if (!nodeEl || !labelEl || !edgeEl) return;

  if (!discoveryMode) {
    // Restore all nodes to normal score-based appearance
    nodeEl
      .style("display", null)
      .transition().duration(600)
      .attr("r",            d => nodeRadius(d))
      .attr("fill",         d => nodeColor(d))
      .attr("fill-opacity", 1)
      .attr("stroke",       "none")
      .attr("stroke-width", 0)
      .style("pointer-events", "all");
    labelEl
      .style("display", null)
      .transition().duration(600)
      .attr("opacity",   d => labelOpacity(d))
      .attr("font-size", "11px");
    applyEdgeFilter();
    return;
  }

  // Hide nodes outside the current subgraph
  nodeEl.style("display",  d => discoveryVisible(d.name) ? null : "none");
  labelEl.style("display", d => discoveryVisible(d.name) ? null : "none");

  // Visual states — transition only visible nodes to avoid D3 touching hidden elements
  nodeEl.filter(d => discoveryVisible(d.name))
    .transition().duration(600)
    .attr("r",    d => nodeRadius(d))
    .attr("fill", d => discovered.has(d.name) ? nodeColor(d) : "none")
    .attr("fill-opacity", 1)
    .attr("stroke", d => {
      if (d.name === lastDiscovered)              return "rgba(255,255,255,0.95)";
      if (d.name === window._pendingDiscovery)    return "rgba(255,200,50,0.9)";
      if (fringe.has(d.name) || ambassadors.has(d.name)) return "rgba(255,255,255,0.45)";
      return "none";
    })
    .attr("stroke-width", d => {
      if (d.name === lastDiscovered)              return 3;
      if (d.name === window._pendingDiscovery)    return 2;
      if (fringe.has(d.name) || ambassadors.has(d.name)) return 1.5;
      return 0;
    })
    .style("pointer-events", "all");

  // Discovered nodes keep labels forever; fringe labels show only while in fringe
  // Pending discovery node gets full-brightness label
  labelEl.filter(d => discoveryVisible(d.name))
    .transition().duration(300)
    .attr("opacity",   d => d.name === window._pendingDiscovery ? 1.0 : labelOpacity(d))
    .attr("font-size", d => d.name === window._pendingDiscovery ? "13px" : "11px");

  // Only draw edges where both endpoints are discovered
  applyEdgeFilter();
}

function triggerDiscovery(artistName) {
  if (!discoveryMode) return;
  if (discovered.has(artistName)) return;
  window._pendingDiscovery = null;
  fringe.delete(artistName);
  ambassadors.delete(artistName);
  discovered.add(artistName);
  lastDiscovered = artistName;
  updateAmbassadors();
  recalcFringe();
  updateDiscoveryVisuals();
  zoomToSubgraph();
  minimizeMenu();
}

function zoomToSubgraph() {
  if (!lastDiscovered) return;
  const subNodes = simNodes.filter(n => subgraph.has(n.name));
  if (subNodes.length === 0) return;

  // Shrink the available viewport to avoid the open artist panel (320 px, right side)
  const panelOpen  = document.getElementById("artistPanel").classList.contains("open");
  const panelW     = panelOpen ? 320 : 0;
  const availW     = W - panelW;
  const availCentX = availW / 2; // centre of the usable area

  const pad = 80;
  const xs  = subNodes.map(n => n.x);
  const ys  = subNodes.map(n => n.y);
  const minX = Math.min(...xs) - pad;
  const maxX = Math.max(...xs) + pad;
  const minY = Math.min(...ys) - pad;
  const maxY = Math.max(...ys) + pad;

  const bw    = maxX - minX;
  const bh    = maxY - minY;
  const scale = Math.min(availW / bw, H / bh, 5);
  const tx    = availCentX - scale * ((minX + maxX) / 2);
  const ty    = H / 2      - scale * ((minY + maxY) / 2);

  svg.transition().duration(700)
    .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
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

function minimizeMenu() {
  const el = document.getElementById("controls");
  if (el) {
    el.classList.add("minimized");
    const btn = document.getElementById("menuToggle");
    if (btn) btn.textContent = "+";
  }
}

function expandMenu() {
  const el = document.getElementById("controls");
  if (el) {
    el.classList.remove("minimized");
    const btn = document.getElementById("menuToggle");
    if (btn) btn.textContent = "−";
  }
}

function initControls() {
  // Main menu minimize toggle
  document.getElementById("menuToggle").addEventListener("click", () => {
    const el = document.getElementById("controls");
    if (el.classList.contains("minimized")) expandMenu();
    else minimizeMenu();
  });

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
  updateExportButton();

  // Export panel button
  document.getElementById("exportBtn").addEventListener("click", openExportPanel);

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

  // Discovery mode toggle
  document.getElementById("discoveryToggle")
    .addEventListener("change", function() {
      discoveryMode = this.checked;
      if (discoveryMode) {
        seedDiscovery();
      } else {
        discovered.clear();
        fringe.clear();
        subgraph.clear();
        ambassadors.clear();
        lastDiscovered = null;
        updateDiscoveryVisuals();
      }
    });
}

// ── Drawer gestures (mobile only) ─────────────────────────────────────────────

function initDrawerGestures() {
  if (!isMobile) return;

  const drawer = document.getElementById("artistDrawer");
  let touchStartY        = 0;
  let scrollAtTouchStart = 0;

  drawer.addEventListener("touchstart", e => {
    touchStartY        = e.touches[0].clientY;
    scrollAtTouchStart = drawer.scrollTop;
  }, { passive: true });

  drawer.addEventListener("touchend", e => {
    const deltaY = e.changedTouches[0].clientY - touchStartY;
    const atTop  = scrollAtTouchStart <= 2;

    if (drawerState === 'collapsed') {
      if (deltaY < -40) {
        // Swipe up → expand
        setDrawerState('expanded');
      } else if (atTop && deltaY > 40) {
        // Fast swipe down at top → hidden
        unpinCurrentNode();
        openArtistName = null;
        setDrawerState('hidden');
      } else if (atTop && deltaY > 10) {
        // Gentle push down at top → peek
        setDrawerState('peek');
      }
    } else if (drawerState === 'expanded') {
      if (atTop && deltaY > 40) {
        // Swipe down from top → collapse
        setDrawerState('collapsed');
        drawer.scrollTop = 0;
      }
    } else if (drawerState === 'peek') {
      if (deltaY < -20) {
        // Swipe up from peek → collapsed
        setDrawerState('collapsed');
      } else if (deltaY > 10) {
        // Any downward touch on peek → hidden
        unpinCurrentNode();
        openArtistName = null;
        setDrawerState('hidden');
      }
    }
  }, { passive: true });

  // Scroll past top in collapsed state → peek
  drawer.addEventListener("scroll", () => {
    if (drawerState === 'collapsed' && drawer.scrollTop === 0) {
      setDrawerState('peek');
    }
  }, { passive: true });
}

// ── Init ──────────────────────────────────────────────────────────────────────

initControls();
initDrawerGestures();
fetchAndBuild(edgeThreshold);
