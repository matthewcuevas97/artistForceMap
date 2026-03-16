/**
 * Universal Artist Map - D3 force graph visualization
 * Allows infinite exploration from user's initial seed nodes
 */

// ============================================================================
// Utility Functions
// ============================================================================

const GENRE_HUE = {
  "Electronic": 195,
  "Indie/Alt": 135,
  "Hip-Hop": 45,
  "R&B/Soul": 25,
  "Pop": 330,
  "Punk/Metal": 0,
  "Latin/Afro": 275,
  "Singer-Songwriter/Jazz": 30,
  "Unknown": 220,
};

function getGenreColor(genre) {
  const hue = GENRE_HUE[genre] || GENRE_HUE["Unknown"];
  return `hsl(${hue}, 70%, 55%)`;
}

// ============================================================================
// State Management
// ============================================================================

const state = {
  authenticated: false,
  authProvider: null,
  username: null,
  initialized: false,
  graph: {
    nodes: [],
    edges: []
  },
  nodeMap: {},
  selectedArtist: null,
  simulation: null,
  nodeSize: 1,
  charge: -50,
  showLabels: true,
  currentAudio: null,
  currentTrackEl: null
};

// ============================================================================
// UI Elements
// ============================================================================

const elements = {
  graph: document.getElementById("graph"),
  controls: document.getElementById("controls"),
  menuToggle: document.getElementById("menuToggle"),

  // Auth
  spotifyBtn: document.getElementById("spotifyBtn"),
  spotifyCol: document.getElementById("spotifyCol"),
  spotifyConnected: document.getElementById("spotifyConnected"),
  spotifyUserLabel: document.getElementById("spotifyUserLabel"),
  spotifyDisconnect: document.getElementById("spotifyDisconnect"),

  lastfmCol: document.getElementById("lastfmCol"),
  lastfmConnected: document.getElementById("lastfmConnected"),
  lastfmUserLabel: document.getElementById("lastfmUserLabel"),
  lastfmDisconnect: document.getElementById("lastfmDisconnect"),
  lastfmInput: document.getElementById("lastfmInput"),
  lastfmUsername: document.getElementById("lastfmUsername"),
  lastfmGo: document.getElementById("lastfmGo"),
  lastfmError: document.getElementById("lastfmError"),

  // Map init
  initRow: document.getElementById("initRow"),
  initBtn: document.getElementById("initBtn"),
  initStatus: document.getElementById("initStatus"),

  // Sliders
  sep1: document.getElementById("sep1"),
  sizeRow: document.getElementById("sizeRow"),
  nodeSizeSlider: document.getElementById("nodeSizeSlider"),
  nodeSizeValue: document.getElementById("nodeSizeValue"),
  chargeRow: document.getElementById("chargeRow"),
  chargeSlider: document.getElementById("chargeSlider"),
  chargeValue: document.getElementById("chargeValue"),

  // Options
  sep2: document.getElementById("sep2"),
  optionsRow: document.getElementById("optionsRow"),
  labelsCheck: document.getElementById("labelsCheck"),

  // Panel
  artistPanel: document.getElementById("artistPanel"),
  panelClose: document.getElementById("panelClose"),
  panelContent: document.getElementById("panelContent")
};

// ============================================================================
// Authentication
// ============================================================================

function updateAuthUI() {
  if (window.SPOTIFY_DISPLAY_NAME) {
    state.authenticated = true;
    state.authProvider = "spotify";
    state.username = window.SPOTIFY_DISPLAY_NAME;
    showSpotifyConnected(state.username);
    showMapControls();
  } else if (window.LASTFM_USER) {
    state.authenticated = true;
    state.authProvider = "lastfm";
    state.username = window.LASTFM_USER;
    showLastfmConnected(state.username);
    showMapControls();
  }
}

function showSpotifyConnected(username) {
  elements.spotifyBtn.style.display = "none";
  elements.spotifyConnected.style.display = "block";
  elements.spotifyUserLabel.textContent = username;
}

function showLastfmConnected(username) {
  elements.lastfmInput.style.display = "none";
  elements.lastfmConnected.style.display = "block";
  elements.lastfmUserLabel.textContent = username;
}

function showMapControls() {
  elements.initRow.style.display = "block";
  elements.sep1.style.display = "block";
  elements.sizeRow.style.display = "block";
  elements.chargeRow.style.display = "block";
  elements.sep2.style.display = "block";
  elements.optionsRow.style.display = "block";
}

function hideMapControls() {
  elements.initRow.style.display = "none";
  elements.sep1.style.display = "none";
  elements.sizeRow.style.display = "none";
  elements.chargeRow.style.display = "none";
  elements.sep2.style.display = "none";
  elements.optionsRow.style.display = "none";
}

// ============================================================================
// Event Listeners
// ============================================================================

elements.spotifyBtn.addEventListener("click", () => {
  window.location.href = "/login";
});

elements.spotifyDisconnect.addEventListener("click", async () => {
  await fetch("/api/spotify/logout", { method: "POST" });
  location.reload();
});

elements.lastfmGo.addEventListener("click", async () => {
  const username = elements.lastfmUsername.value.trim();
  if (!username) return;

  try {
    const res = await fetch("/api/lastfm/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username })
    });
    if (res.ok) {
      location.reload();
    } else {
      elements.lastfmError.style.display = "block";
    }
  } catch (e) {
    elements.lastfmError.style.display = "block";
  }
});

elements.lastfmDisconnect.addEventListener("click", async () => {
  await fetch("/api/lastfm/logout", { method: "POST" });
  location.reload();
});

elements.initBtn.addEventListener("click", initializeMap);
elements.panelClose.addEventListener("click", closePanel);
elements.menuToggle.addEventListener("click", () => {
  elements.controls.classList.toggle("minimized");
});

elements.nodeSizeSlider.addEventListener("input", (e) => {
  state.nodeSize = parseFloat(e.target.value);
  elements.nodeSizeValue.textContent = state.nodeSize.toFixed(2);
  updateNodeSizes();
});

elements.chargeSlider.addEventListener("input", (e) => {
  state.charge = parseInt(e.target.value);
  elements.chargeValue.textContent = state.charge;
  if (state.simulation) {
    state.simulation.force("charge").strength(state.charge);
    state.simulation.alpha(0.3).restart();
  }
});

elements.labelsCheck.addEventListener("change", (e) => {
  state.showLabels = e.target.checked;
  updateLabels();
});

// ============================================================================
// Map Initialization
// ============================================================================

async function initializeMap() {
  if (!state.authenticated) {
    alert("Please authenticate first");
    return;
  }

  elements.initBtn.disabled = true;
  elements.initBtn.classList.add("loading");

  try {
    // Show status panel
    elements.initStatus.style.display = "block";
    elements.initStatus.innerHTML = '';
    elements.initStatus.classList.add("auth-status");

    let firstMessage = true;

    // Use streaming endpoint for progress updates
    const response = await fetch("/api/map/init/stream", { method: "POST" });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || "Failed to initialize map");
    }

    // Process Server-Sent Events
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');

      // Process complete lines
      for (let i = 0; i < lines.length - 1; i++) {
        const line = lines[i];
        if (line.startsWith("data: ")) {
          try {
            const event = JSON.parse(line.slice(6));

            if (event.error) {
              throw new Error(event.error);
            }

            if (event.message) {
              // Clear initial content on first message
              if (firstMessage) {
                elements.initStatus.innerHTML = '';
                firstMessage = false;
              }

              // Update status with progress message
              const messageDiv = document.createElement("div");
              messageDiv.style.cssText = "font-size: 9px; color: rgba(255,255,255,0.7); margin: 3px 0; font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;";
              messageDiv.textContent = event.message.trim();

              // Append to status, keeping latest messages
              elements.initStatus.appendChild(messageDiv);

              // Scroll to bottom
              elements.initStatus.scrollTop = elements.initStatus.scrollHeight;
            }

            if (event.complete) {
              // Map generation complete
              state.graph = {
                nodes: event.nodes || [],
                edges: event.edges || []
              };

              state.nodeMap = {};
              state.graph.nodes.forEach(node => {
                state.nodeMap[node.name] = node;
              });

              state.initialized = true;

              // Show final success message
              elements.initStatus.innerHTML = `<div style="color: rgba(100, 200, 100, 0.8);">✓ Map ready! ${state.graph.nodes.length} nodes, ${state.graph.edges.length} connections</div>`;
              setTimeout(() => {
                elements.initStatus.style.display = "none";
              }, 3000);

              renderGraph();
              return;
            }
          } catch (e) {
            console.error("Error parsing event:", e);
          }
        }
      }

      // Keep incomplete line in buffer
      buffer = lines[lines.length - 1];
    }
  } catch (e) {
    elements.initStatus.style.display = "block";
    elements.initStatus.innerHTML = `<div style="color: rgba(255, 100, 100, 0.8);">Error: ${e.message}</div>`;
  } finally {
    elements.initBtn.disabled = false;
    elements.initBtn.classList.remove("loading");
  }
}

// ============================================================================
// Graph Rendering (D3)
// ============================================================================

function renderGraph() {
  // Clear previous
  d3.select("#graph").selectAll("*").remove();

  if (!state.graph.nodes.length) {
    return;
  }

  const width = window.innerWidth;
  const height = window.innerHeight;

  const svg = d3.select("#graph")
    .attr("width", width)
    .attr("height", height);

  // Create container group
  const g = svg.append("g");

  // Add zoom/pan behavior
  const zoom = d3.zoom()
    .on("zoom", (event) => {
      g.attr("transform", event.transform);
    });
  svg.call(zoom);

  // Create simulation
  state.simulation = d3.forceSimulation(state.graph.nodes)
    .force("link", d3.forceLink(state.graph.edges)
      .id(d => d.name)
      .distance(100)
      .strength(0.5))
    .force("charge", d3.forceManyBody().strength(state.charge))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collide", d3.forceCollide().radius(20));

  // Render edges
  const edges = g.selectAll(".link")
    .data(state.graph.edges)
    .enter()
    .append("line")
    .attr("class", "link")
    .attr("stroke", "rgba(255, 255, 255, 0.1)")
    .attr("stroke-width", 1);

  // Render nodes
  const nodes = g.selectAll(".node")
    .data(state.graph.nodes, d => d.name)
    .enter()
    .append("circle")
    .attr("class", "node")
    .attr("r", d => {
      // Size by listener count (log-normalized)
      const listeners = d.listeners || 0;
      const logListeners = Math.log1p(listeners);
      return Math.max(4, Math.min(12, 3 + logListeners / 1000000)) * state.nodeSize;
    })
    .attr("fill", d => {
      const genre = d.genre || "Unknown";
      return getGenreColor(genre);
    })
    .attr("stroke", "rgba(255, 255, 255, 0.3)")
    .attr("stroke-width", 1.5)
    .attr("cursor", "pointer")
    .on("click", (event, d) => {
      event.stopPropagation();
      selectArtist(d.name);
      showPanel(d);
    })
    .on("mouseover", function(event, d) {
      const genre = d.genre || "Unknown";
      const baseColor = getGenreColor(genre);
      d3.select(this)
        .attr("fill", baseColor)
        .attr("opacity", 0.7)
        .attr("r", d => {
          const listeners = d.listeners || 0;
          const logListeners = Math.log1p(listeners);
          return Math.max(4, Math.min(12, 3 + logListeners / 1000000)) * state.nodeSize * 1.3;
        });
    })
    .on("mouseout", function() {
      d3.select(this)
        .attr("opacity", 1)
        .attr("r", d => {
          const listeners = d.listeners || 0;
          const logListeners = Math.log1p(listeners);
          return Math.max(4, Math.min(12, 3 + logListeners / 1000000)) * state.nodeSize;
        });
    });

  // Render labels
  const labels = g.selectAll(".label")
    .data(state.graph.nodes, d => d.name)
    .enter()
    .append("text")
    .attr("class", "label")
    .attr("font-size", 10)
    .attr("fill", "rgba(255, 255, 255, 0.5)")
    .attr("text-anchor", "middle")
    .attr("pointer-events", "none")
    .attr("opacity", state.showLabels ? 1 : 0)
    .text(d => d.name);

  // Update positions on simulation tick
  state.simulation.on("tick", () => {
    edges
      .attr("x1", d => d.source.x)
      .attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x)
      .attr("y2", d => d.target.y);

    nodes
      .attr("cx", d => d.x)
      .attr("cy", d => d.y);

    labels
      .attr("x", d => d.x)
      .attr("y", d => d.y + 15);
  });

  // Click on background to deselect
  svg.on("click", () => {
    selectArtist(null);
    closePanel();
  });
}

function updateNodeSizes() {
  d3.selectAll(".node")
    .transition()
    .duration(300)
    .attr("r", d => 5 * state.nodeSize);

  d3.selectAll(".label")
    .transition()
    .duration(300)
    .attr("y", d => d.y + (15 * state.nodeSize));
}

function updateLabels() {
  d3.selectAll(".label")
    .transition()
    .duration(200)
    .attr("opacity", state.showLabels ? 1 : 0);
}

function selectArtist(name) {
  state.selectedArtist = name;
  d3.selectAll(".node")
    .attr("stroke", d => d.name === name ? "rgba(100, 200, 100, 0.9)" : "rgba(255, 255, 255, 0.3)")
    .attr("stroke-width", d => d.name === name ? 2.5 : 1.5);
}

// ============================================================================
// Artist Panel
// ============================================================================

function showPanel(artist) {
  // Stop any currently playing audio
  if (state.currentAudio) {
    state.currentAudio.pause();
    state.currentAudio = null;
    if (state.currentTrackEl) {
      state.currentTrackEl.classList.remove("playing");
    }
  }

  const imageUrl = artist.image_url || "";
  const bio = artist.bio || "";
  const tags = artist.tags || [];
  const listeners = artist.listeners || 0;
  const topTracks = artist.top_tracks || [];

  let html = `<div class="panel-body">`;

  // Hero image
  if (imageUrl) {
    html += `<img class="panel-hero" src="${imageUrl}" alt="${artist.name}" />`;
  }

  // Name and listeners
  html += `
    <div class="panel-name">${artist.name}</div>
    <div class="panel-meta">${listeners.toLocaleString()} listeners</div>
  `;

  // Tags
  if (tags.length > 0) {
    html += `<div class="panel-tags">`;
    tags.slice(0, 5).forEach(tag => {
      html += `<div class="panel-tag">${tag}</div>`;
    });
    html += `</div>`;
  }

  // Bio
  if (bio) {
    html += `<div class="panel-bio">${bio.substring(0, 300)}${bio.length > 300 ? "..." : ""}</div>`;
  }

  // Top tracks
  if (topTracks.length > 0) {
    html += `<div class="panel-section-label">TOP TRACKS</div>`;
    html += `<div style="margin-bottom: 12px;">`;
    topTracks.slice(0, 10).forEach((track, idx) => {
      const trackName = track.name || "";
      const albumArt = track.album_art || "";
      const previewUrl = track.preview_url || "";
      html += `
        <div class="track-row" data-preview="${previewUrl}" data-track-idx="${idx}">
          ${albumArt ? `<img class="track-art" src="${albumArt}" alt="${trackName}" />` : `<div class="track-art" style="background: rgba(255,255,255,0.1);"></div>`}
          <div class="track-name" title="${trackName}">${trackName}</div>
          ${previewUrl ? `<button class="track-play" data-track-idx="${idx}">▶ PLAY</button>` : `<span style="font-size: 8px; color: rgba(255,255,255,0.25);">N/A</span>`}
        </div>
      `;
    });
    html += `</div>`;
  }

  html += `</div>`;

  elements.panelContent.innerHTML = html;
  elements.artistPanel.classList.add("open");

  // Wire up play button listeners
  document.querySelectorAll(".track-play").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const trackIdx = parseInt(btn.dataset.trackIdx);
      const track = topTracks[trackIdx];
      const previewUrl = track.preview_url;

      if (!previewUrl) return;

      // Toggle playback
      if (state.currentAudio && state.currentTrackEl === btn) {
        state.currentAudio.pause();
        state.currentAudio = null;
        btn.classList.remove("playing");
        state.currentTrackEl = null;
      } else {
        // Stop other audio
        if (state.currentAudio) {
          state.currentAudio.pause();
        }
        if (state.currentTrackEl) {
          state.currentTrackEl.classList.remove("playing");
        }

        // Play new audio
        const audio = new Audio(previewUrl);
        audio.addEventListener("ended", () => {
          btn.classList.remove("playing");
          state.currentAudio = null;
          state.currentTrackEl = null;
        });
        audio.play();
        state.currentAudio = audio;
        state.currentTrackEl = btn;
        btn.classList.add("playing");
      }
    });
  });
}

function closePanel() {
  // Stop any playing audio
  if (state.currentAudio) {
    state.currentAudio.pause();
    state.currentAudio = null;
  }
  if (state.currentTrackEl) {
    state.currentTrackEl.classList.remove("playing");
    state.currentTrackEl = null;
  }

  elements.artistPanel.classList.remove("open");
  elements.panelContent.innerHTML = "";
}

// ============================================================================
// Initialization
// ============================================================================

updateAuthUI();
