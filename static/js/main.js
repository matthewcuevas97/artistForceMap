/**
 * main.js — entry point. Orchestrates all modules.
 */

import * as S from './state.js';
import {
  buildGraph, nodeEl, simulation,
  enterSubgraphHighlight, exitSubgraphHighlight,
  clearHover, zoomToSubgraph,
} from './simulation.js';
import {
  discoveryVisible,
  seedDiscovery, recalcFringe,
  updateAmbassadors, updateDiscoveryVisuals,
} from './discovery.js';
import { openPanel, closePanel }                from './panel.js';
import {
  setDrawerState, openDrawer, initDrawerGestures,
  closeAllPanels, registerUnpinCallback,
} from './drawer.js';
import { initControls, updateAuthUI, registerCloseArtistCallback, registerPeekArtistCallback } from './controls.js';
import { updateExportButton, closeExportPanel }  from './playlist.js';
import { minimizeMenu }                         from './ui.js';
import { escapeHtml }                           from './utils.js';

// ── Expose unpinCurrentNode to drawer.js via callback ────────────────────────

function unpinCurrentNode() {
  if (!S.pinnedDatum) return;
  S.pinnedDatum.fx = null;
  S.pinnedDatum.fy = null;
  // nodeEl is a live binding from simulation.js; filter by datum reference
  if (nodeEl) nodeEl.filter(n => n === S.pinnedDatum).attr("stroke", "none").attr("stroke-width", 0);
  S.setPinnedDatum(null);
}

registerUnpinCallback(unpinCurrentNode);

// Register with controls.js: opening the controls hamburger peeks bio (mobile) or no-ops (desktop)
registerPeekArtistCallback(() => {
  if (S.isMobile && S.drawerState !== 'hidden') setDrawerState('peek');
});

// Register with controls.js: opening the playlist closes bio entirely + unpins
registerCloseArtistCallback(() => {
  unpinCurrentNode();
  S.setOpenArtistName(null);
  closePanel();
  if (S.isMobile) setDrawerState('hidden');
});

// ── Helpers ───────────────────────────────────────────────────────────────────

// Close controls + playlist without triggering "reopen controls" back-nav logic.
// Used before opening artist bio (they're mutually exclusive).
function closeSidePanels() {
  minimizeMenu();
  closeExportPanel();
}

// ── Node click ────────────────────────────────────────────────────────────────

function onNodeClick(event, d) {
  if (S.dragMoved) { S.setDragMoved(false); return; }

  // Discovery mode — fringe / ambassador → pending discovery + open detail
  if (S.discoveryMode && (S.fringe.has(d.name) || S.ambassadors.has(d.name)) && !S.discovered.has(d.name)) {
    window._pendingDiscovery = d.name;
    closeSidePanels();
    updateDiscoveryVisuals();
    S.isMobile ? openDrawer(d.name) : openPanel(d.name);
    return;
  }
  // Discovery mode — invisible node → inert
  if (S.discoveryMode && !S.discovered.has(d.name) && !S.fringe.has(d.name) && !S.ambassadors.has(d.name)) {
    return;
  }
  // Discovery mode — clicking a discovered node shifts fringe
  if (S.discoveryMode && S.discovered.has(d.name)) {
    S.setLastDiscovered(d.name);
    recalcFringe();
    updateDiscoveryVisuals();
    zoomToSubgraph();
    minimizeMenu();
  }

  if (S.openArtistName === d.name && d.fx != null) {
    // Re-click same pinned node → unpin, keep panel, exit subgraph
    d.fx = null; d.fy = null;
    S.setPinnedDatum(null);
    if (nodeEl) nodeEl.filter(n => n === d).attr("stroke", "none").attr("stroke-width", 0);
    if (!S.discoveryMode) exitSubgraphHighlight();
  } else {
    // Unpin previous
    if (S.pinnedDatum && S.pinnedDatum !== d) {
      S.pinnedDatum.fx = null; S.pinnedDatum.fy = null;
      if (nodeEl) nodeEl.filter(n => n === S.pinnedDatum).attr("stroke", "none").attr("stroke-width", 0);
    }
    if (!S.discoveryMode) exitSubgraphHighlight();

    // Pin new node
    d.fx = d.x; d.fy = d.y;
    S.setPinnedDatum(d);
    S.setOpenArtistName(d.name);
    if (nodeEl) nodeEl.filter(n => n === d).attr("stroke", "#FFD700").attr("stroke-width", 2.5);

    closeSidePanels();
    S.isMobile ? openDrawer(d.name) : openPanel(d.name);
    if (!S.discoveryMode) enterSubgraphHighlight(d);
  }

  if (simulation) simulation.alpha(0.05).restart();
}

// ── Background click ──────────────────────────────────────────────────────────

function onBgClick() {
  clearHover();
  if (S.isMobile) {
    if (S.drawerState === 'expanded') {
      setDrawerState('collapsed');
    } else if (S.drawerState === 'collapsed' || S.drawerState === 'peek') {
      unpinCurrentNode();
      S.setOpenArtistName(null);
      setDrawerState('hidden');
      closePanel();
    } else {
      closeSidePanels();
    }
    return;
  }
  closeSidePanels();
  exitSubgraphHighlight();
  unpinCurrentNode();
  S.setOpenArtistName(null);
  closePanel();
}

// ── Panel close button ────────────────────────────────────────────────────────

function onPanelClose() {
  unpinCurrentNode();
  S.setOpenArtistName(null);
  closePanel();
}

// ── Graph loading ─────────────────────────────────────────────────────────────

function _statusEl() {
  let el = document.getElementById("graphStatusOverlay");
  if (!el) {
    el = document.createElement("div");
    el.id = "graphStatusOverlay";
    Object.assign(el.style, {
      position: "fixed", inset: "0",
      display: "flex", alignItems: "center", justifyContent: "center",
      pointerEvents: "none", zIndex: "5",
    });
    document.body.appendChild(el);
  }
  return el;
}

function showLoading() {
  const el = _statusEl();
  el.style.display = "flex";
  el.innerHTML =
    `<div style="display:flex;flex-direction:column;align-items:center;gap:6px">` +
    `<span style="font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:0.12em;color:rgba(255,255,255,0.3)">LOADING…</span>` +
    `<span style="font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:0.08em;color:rgba(255,255,255,0.3);opacity:0.4">first load may take ~30s</span>` +
    `</div>`;
}

function showError(msg) {
  const el = _statusEl();
  el.style.display = "flex";
  el.innerHTML = `<span style="font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:0.1em;color:rgba(255,100,100,0.6)">${escapeHtml(msg)}</span>`;
}

function hideStatus() {
  const el = document.getElementById("graphStatusOverlay");
  if (el) el.style.display = "none";
}

async function fetchAndBuild(threshold) {
  showLoading();
  try {
    if (!S.frontierEdgesLoaded) {
      S.setFrontierEdgesLoaded(true);
      fetch("/api/graph?threshold=0.05")
        .then(r => r.ok ? r.json() : null)
        .then(data => { if (data?.edges) S.setAllEdgesForFrontier(data.edges); })
        .catch(() => {});
    }
    const resp = await fetch(`/api/graph?threshold=${threshold.toFixed(2)}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (data.error) throw new Error(data.error);

    S.setRawNodes(data.nodes);
    S.setRawEdges(data.edges);
    S.setUserSeeds(new Set(data.user_seeds || []));

    buildGraph(onNodeClick, onBgClick);

    if (S.discoveryMode) seedDiscovery(S.userSeeds);

    hideStatus();
  } catch (err) {
    console.error("artistForceMap:", err.message);
    showError("Failed to load graph. Please refresh the page.");
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────

initControls(fetchAndBuild, () => S.userSeeds, onPanelClose);
initDrawerGestures();
fetchAndBuild(S.edgeThreshold);
