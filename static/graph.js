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

let discoveryMode    = false;
let discovered       = new Set(); // fully discovered artist names
let revealed         = new Set(); // hollow/clickable but not yet discovered
// locked = all nodes not in discovered or revealed (tiny dots, inert)
let allEdgesForFrontier = []; // populated once from /api/graph?threshold=0.05
let frontierEdgesLoaded = false;

let thresholdDebounce = null;
let dragMoved = false;

let currentAudio   = null;
let currentPlayBtn = null;
let openArtistName = null;
let pinnedDatum    = null;
let panelRequestId = 0;

let playlist           = [];   // { artist, name, album_art, deezer_url }
let expandedTrackIndex = null;
let currentTracks      = [];

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
      `<div style="font-size:10px;font-weight:500;color:rgba(255,255,255,0.8);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${track.name}</div>` +
      `<div style="font-size:9px;color:rgba(255,255,255,0.4);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${track.artist}</div>` +
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
        `<a href="${data.playlist_url}" target="_blank" style="color:rgba(255,255,255,0.5);font-size:9px;letter-spacing:0.08em">OPEN IN SPOTIFY →</a>`;
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
      `<span style="font-size:10px;flex:1;color:rgba(255,255,255,0.72)">${track.name}</span>` +
      `<button class="play-btn" data-preview="${preview}"` +
      ` style="font-size:12px;color:rgba(255,255,255,0.4);background:none;border:none;cursor:pointer${disabledStyle}">▶</button>` +
      `</div>`
    );
  }).join("");
  return header + rows;
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
  if (labelEl) {
    if (discoveryMode) {
      labelEl.attr("opacity", d => {
        if (discovered.has(d.name)) return labelOpacity(d);
        if (revealed.has(d.name))   return 0.4;
        return 0;
      });
    } else {
      labelEl.attr("opacity", d => labelOpacity(d));
    }
  }
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
  if (discoveryMode) {
    edgeEl.attr("opacity", e => {
      const srcName = typeof e.source === "object" ? e.source.name : e.source;
      const tgtName = typeof e.target === "object" ? e.target.name : e.target;
      if (!discovered.has(srcName) || !discovered.has(tgtName)) return 0;
      return edgeBaseOpacity(e);
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

      // Discovery mode: revealed node → open panel, set pending discovery
      if (discoveryMode && revealed.has(d.name) && !discovered.has(d.name)) {
        openPanel(d.name);
        window._pendingDiscovery = d.name;
        return;
      }
      // Discovery mode: locked node → inert (pointer-events:none should already block this)
      if (discoveryMode && !discovered.has(d.name) && !revealed.has(d.name)) {
        return;
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

  // If discovery mode is on, re-seed after graph rebuild
  if (discoveryMode) seedDiscovery();

  // Resume with a gentle alpha so the graph softly continues to settle
  simulation
    .on("tick", ticked)
    .alpha(0.1)
    .restart();
}

// ── Fetch + build ─────────────────────────────────────────────────────────────

async function fetchAndBuild(threshold) {
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
    rawNodes = data.nodes;
    rawEdges = data.edges;
    buildGraph();
  } catch (err) {
    console.error("artistForceMap: failed to load graph —", err.message);
  }
}

// ── Discovery mode ────────────────────────────────────────────────────────────

function seedDiscovery() {
  discovered.clear();
  revealed.clear();
  // Top 20 nodes by score
  const top20 = [...simNodes]
    .sort((a, b) => b.score - a.score)
    .slice(0, 20);
  top20.forEach(n => discovered.add(n.name));
  expandFrontier();
  updateDiscoveryVisuals();
}

function expandFrontier() {
  for (const name of discovered) {
    for (const e of allEdgesForFrontier) {
      const src = typeof e.source === "object" ? e.source.name : e.source;
      const tgt = typeof e.target === "object" ? e.target.name : e.target;
      if (src === name && !discovered.has(tgt)) revealed.add(tgt);
      if (tgt === name && !discovered.has(src)) revealed.add(src);
    }
  }
  // If revealed is empty and locked nodes remain, guarantee reachability
  const locked = simNodes.filter(n => !discovered.has(n.name) && !revealed.has(n.name));
  if (revealed.size === 0 && locked.length > 0) {
    bridgeUnlock();
  }
}

function bridgeUnlock() {
  const locked = simNodes.filter(n => !discovered.has(n.name) && !revealed.has(n.name));
  if (locked.length === 0) return;

  const lockedNames = new Set(locked.map(n => n.name));
  let bestNode   = null;
  let bestWeight = -1;

  for (const e of allEdgesForFrontier) {
    const src = typeof e.source === "object" ? e.source.name : e.source;
    const tgt = typeof e.target === "object" ? e.target.name : e.target;
    if (lockedNames.has(src) && discovered.has(tgt) && e.weight > bestWeight) {
      bestWeight = e.weight;
      bestNode   = src;
    }
    if (lockedNames.has(tgt) && discovered.has(src) && e.weight > bestWeight) {
      bestWeight = e.weight;
      bestNode   = tgt;
    }
  }

  // Fallback: highest-score locked node if no edges connect to discovered
  if (bestNode === null) {
    bestNode = locked.sort((a, b) => b.score - a.score)[0].name;
  }

  revealed.add(bestNode);
}

function updateDiscoveryVisuals() {
  if (!nodeEl || !labelEl || !edgeEl) return;

  if (!discoveryMode) {
    // Restore all nodes to normal score-based appearance
    nodeEl.transition().duration(600)
      .attr("r",            d => nodeRadius(d))
      .attr("fill",         d => nodeColor(d))
      .attr("fill-opacity", 1)
      .attr("stroke",       "none")
      .attr("stroke-width", 0)
      .style("pointer-events", "all");
    labelEl.transition().duration(600)
      .attr("opacity",   d => labelOpacity(d))
      .attr("font-size", "11px");
    applyEdgeFilter();
    return;
  }

  // Discovery mode visual states
  nodeEl.transition().duration(600)
    .attr("r", d => {
      if (discovered.has(d.name)) return nodeRadius(d);
      if (revealed.has(d.name))   return 5;
      return 2;
    })
    .attr("fill", d => {
      if (discovered.has(d.name)) return nodeColor(d);
      if (revealed.has(d.name))   return "none";
      return "rgba(255,255,255,0.08)";
    })
    .attr("fill-opacity", d => {
      if (revealed.has(d.name) && !discovered.has(d.name)) return 0;
      return 1;
    })
    .attr("stroke", d => {
      if (revealed.has(d.name) && !discovered.has(d.name)) return "rgba(255,255,255,0.35)";
      return "none";
    })
    .attr("stroke-width", d => {
      if (revealed.has(d.name) && !discovered.has(d.name)) return 1.5;
      return 0;
    })
    .style("pointer-events", d => {
      if (!discovered.has(d.name) && !revealed.has(d.name)) return "none";
      return "all";
    });

  labelEl.transition().duration(600)
    .attr("opacity", d => {
      if (discovered.has(d.name)) return labelOpacity(d);
      if (revealed.has(d.name))   return 0.4;
      return 0;
    })
    .attr("font-size", d => {
      if (revealed.has(d.name) && !discovered.has(d.name)) return "8px";
      return "11px";
    });

  // Only draw edges where both endpoints are in discovered
  applyEdgeFilter();
}

function triggerDiscovery(artistName) {
  if (!discoveryMode) return;
  if (discovered.has(artistName)) return;
  revealed.delete(artistName);
  discovered.add(artistName);
  expandFrontier();
  updateDiscoveryVisuals();
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
        revealed.clear();
        updateDiscoveryVisuals();
      }
    });
}

// ── Init ──────────────────────────────────────────────────────────────────────

initControls();
fetchAndBuild(edgeThreshold);
