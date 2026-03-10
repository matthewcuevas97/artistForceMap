/**
 * playlist.js
 * Playlist accumulation, export panel, Spotify playlist creation.
 */

import { escapeHtml, buildServiceLinks } from './utils.js';
import * as S from './state.js';

// Callback called when the user presses the ← back button inside the playlist panel.
// Used by controls.js to re-expand the controls panel (back-navigation pattern).
let _onBackClose = null;
export function setOnBackClose(fn) { _onBackClose = fn; }

export function addToPlaylist(track, subEl, onAdded) {
  S.playlist.push({
    artist:     S.openArtistName || "",
    name:       track.name,
    album_art:  track.album_art || "",
    deezer_url: track.preview_url || "",
  });

  if (onAdded) onAdded();

  updateExportButton();

  const saved = subEl.innerHTML;
  subEl.innerHTML = `<span style="color:rgba(255,255,255,0.6);font-size:10px;font-family:'IBM Plex Mono',monospace;letter-spacing:0.08em">✓ Added</span>`;
  setTimeout(() => {
    subEl.innerHTML = saved;
    subEl.querySelector(".add-playlist-btn")?.addEventListener("click", () => {
      addToPlaylist(track, subEl, onAdded);
    });
  }, 1500);
}

export function updateExportButton() {
  const row = document.getElementById("exportRow");
  const btn = document.getElementById("exportBtn");
  if (!row || !btn) return;
  if (S.playlist.length === 0) {
    row.style.display = "none";
    btn.classList.remove("active");
  } else {
    row.style.display = "block";
    btn.classList.add("active");
    btn.textContent = window.AUTHENTICATED
      ? `SPOTIFY PLAYLIST (${S.playlist.length})`
      : `MY PLAYLIST (${S.playlist.length})`;
  }
  syncHamburgerColor();
}

export function syncHamburgerColor() {
  const btn = document.getElementById("menuToggle");
  if (!btn) return;
  btn.style.color = S.playlist.length > 0 ? "#1db954" : "";
}

export function openExportPanel() {
  renderExportPanel();
  closeExportPanel_internal(false);
  const panel = document.getElementById("exportPanel");
  panel.style.display = "block";
  requestAnimationFrame(() => panel.classList.add("open"));
}

export function closeExportPanel() {
  closeExportPanel_internal(true);
}

function closeExportPanel_internal(animate) {
  const panel = document.getElementById("exportPanel");
  if (!panel) return;
  panel.classList.remove("open");
  if (animate) setTimeout(() => { panel.style.display = "none"; }, 260);
}

export function renderExportPanel() {
  const panel = document.getElementById("exportPanel");
  const title = window.AUTHENTICATED ? "SPOTIFY PLAYLIST" : "MY PLAYLIST";

  const tracksHTML = S.playlist.map((track, i) => {
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
    `<span style="flex:1;text-align:center;font-size:10px;letter-spacing:0.14em;color:rgba(255,255,255,0.7)">${title} (${S.playlist.length})</span>` +
    `<div style="width:24px"></div>` +
    `</div>` +
    `<div id="epTrackList">${tracksHTML}</div>` +
    footerHTML;

  document.getElementById("exportPanelBack").addEventListener("click", () => {
    closeExportPanel();
    _onBackClose?.();
  });

  panel.querySelectorAll(".ep-remove").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      S.playlist.splice(parseInt(btn.dataset.epIndex, 10), 1);
      updateExportButton();
      renderExportPanel();
    });
  });

  if (!window.AUTHENTICATED) {
    let expandedEpIdx = null;
    panel.querySelectorAll(".ep-track").forEach(row => {
      row.addEventListener("click", function() {
        const idx   = parseInt(this.dataset.epIndex, 10);
        const track = S.playlist[idx];
        panel.querySelectorAll(".ep-track").forEach(r => r.style.boxShadow = "");
        panel.querySelectorAll(".ep-service-links").forEach(sl => { sl.style.display = "none"; });
        if (expandedEpIdx === idx) { expandedEpIdx = null; return; }
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
  if (createBtn) createBtn.addEventListener("click", createSpotifyPlaylist);
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
      body:    JSON.stringify({ tracks: S.playlist.map(t => ({ artist: t.artist, name: t.name })) }),
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
      result.style.color = "rgba(255,100,100,0.8)";
      result.textContent = data.error || "Failed to create playlist";
    }
  } catch (_) {
    btn.disabled = false;
    btn.textContent = "CREATE SPOTIFY PLAYLIST";
    result.style.color = "rgba(255,100,100,0.8)";
    result.textContent = "Network error";
  }
}
