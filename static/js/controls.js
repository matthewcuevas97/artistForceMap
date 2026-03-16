/**
 * controls.js — wires all HTML controls.
 */

import { THRESHOLD_LEVELS } from './constants.js';
import * as S from './state.js';
import { applyEdgeFilter, applyDayFilter, rebuildNodeSizes } from './simulation.js';
import { seedDiscovery, updateAmbassadors, updateDiscoveryVisuals } from './discovery.js';
import { updateExportButton, openExportPanel, closeExportPanel, setOnBackClose } from './playlist.js';
import { minimizeMenu, expandMenu } from './ui.js';

export { minimizeMenu, expandMenu };

// Callback registered by main.js — unpin node + close artist bio panel
let _closeArtist = null;
export function registerCloseArtistCallback(fn) { _closeArtist = fn; }

export function updateAuthUI() {
  const spotifyCol       = document.getElementById("spotifyCol");
  const spotifyBtn       = document.getElementById("spotifyBtn");
  const spotifyConnected = document.getElementById("spotifyConnected");
  const spotifyUserLabel = document.getElementById("spotifyUserLabel");
  const lastfmCol        = document.getElementById("lastfmCol");
  const lastfmConnected  = document.getElementById("lastfmConnected");
  const lastfmUserLabel  = document.getElementById("lastfmUserLabel");
  const lastfmInput      = document.getElementById("lastfmInput");

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

export function initControls(fetchAndBuild, onThresholdChange, getUserSeeds, onPanelClose) {
  // When playlist back-button is pressed: close playlist, reopen controls
  setOnBackClose(() => expandMenu());

  // Minimize toggle
  document.getElementById("menuToggle").addEventListener("click", () => {
    const el = document.getElementById("controls");
    if (el.classList.contains("minimized")) {
      // Opening controls: close artist bio (mutually exclusive) + close playlist
      _closeArtist?.();
      closeExportPanel();
      expandMenu();
    } else {
      minimizeMenu();
    }
  });

  // Panel close button
  document.getElementById("panelClose").addEventListener("click", onPanelClose);

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
    fetchAndBuild();
  });

  // Last.fm GO
  const lastfmUsername = document.getElementById("lastfmUsername");
  const lastfmError    = document.getElementById("lastfmError");
  lastfmUsername.addEventListener("input", () => { lastfmError.style.display = "none"; });

  const doLastfmLogin = async () => {
    const username = lastfmUsername.value.trim();
    if (!username) return;
    const resp = await fetch("/api/lastfm/login", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ username }),
    });
    const data = await resp.json();
    if (data.ok) {
      window.LASTFM_USER = username;
      window.AUTHENTICATED = false;
      updateAuthUI();
      fetchAndBuild();
    } else {
      lastfmError.style.display = "block";
    }
  };
  document.getElementById("lastfmGo").addEventListener("click", doLastfmLogin);
  lastfmUsername.addEventListener("keydown", e => { if (e.key === "Enter") doLastfmLogin(); });

  // Last.fm disconnect
  document.getElementById("lastfmDisconnect").addEventListener("click", async () => {
    await fetch("/api/lastfm/logout", { method: "POST" });
    window.LASTFM_USER = null;
    updateAuthUI();
    fetchAndBuild();
  });

  updateAuthUI();
  updateExportButton();

  // Export button: minimize controls first (playlist replaces controls), then open
  document.getElementById("exportBtn").addEventListener("click", () => {
    minimizeMenu();
    openExportPanel();
  });

  // Day filter buttons
  document.querySelectorAll(".day-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".day-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      S.setDayFilter(btn.dataset.day);
      applyDayFilter();
    });
  });

  // Edge threshold slider
  const thresholdSlider = document.getElementById("thresholdSlider");
  const thresholdValue  = document.getElementById("thresholdValue");
  thresholdSlider.addEventListener("input", () => {
    const idx = parseInt(thresholdSlider.value, 10);
    S.setEdgeThreshold(THRESHOLD_LEVELS[idx]);
    thresholdValue.textContent = S.edgeThreshold.toFixed(2);
    onThresholdChange();
  });

  // Node size slider
  const nodeSizeSlider = document.getElementById("nodeSizeSlider");
  const nodeSizeValue  = document.getElementById("nodeSizeValue");
  nodeSizeSlider.addEventListener("input", () => {
    S.setNodeScale(parseFloat(nodeSizeSlider.value));
    nodeSizeValue.textContent = S.nodeScale.toFixed(1);
    rebuildNodeSizes();
  });

  // Similarity edges checkbox
  document.getElementById("similarityCheck").addEventListener("change", e => {
    S.setShowSimilarity(e.target.checked);
    applyEdgeFilter();
  });

  // Genre edges checkbox
  document.getElementById("genreCheck").addEventListener("change", e => {
    S.setShowGenre(e.target.checked);
    applyEdgeFilter();
  });

  // Discovery mode toggle
  document.getElementById("discoveryToggle").addEventListener("change", function() {
    S.setDiscoveryMode(this.checked);
    if (S.discoveryMode) {
      seedDiscovery(getUserSeeds());
    } else {
      S.discovered.clear();
      S.fringe.clear();
      S.subgraph.clear();
      S.ambassadors.clear();
      S.setLastDiscovered(null);
      updateDiscoveryVisuals();
    }
  });

  // On mobile, tap outside controls → minimize
  if (S.isMobile) {
    document.addEventListener("touchstart", e => {
      const controls = document.getElementById("controls");
      if (!controls || controls.classList.contains("minimized")) return;
      if (!controls.contains(e.target)) minimizeMenu();
    }, { passive: true });
  }

  // Measure controls height in minimized state
  if (S.isMobile) {
    const controlsEl = document.getElementById("controls");
    if (controlsEl) {
      const was = controlsEl.classList.contains("minimized");
      if (!was) controlsEl.classList.add("minimized");
      void controlsEl.offsetHeight;
      S.setControlsCollapsedBottom(controlsEl.getBoundingClientRect().bottom);
      if (!was) controlsEl.classList.remove("minimized");
    }
  }
}
