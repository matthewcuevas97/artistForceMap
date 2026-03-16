/**
 * panel.js — desktop right-panel artist detail.
 */

import { escapeHtml, buildServiceLinks } from './utils.js';
import { PLACEHOLDER_HASH } from './constants.js';
import * as S from './state.js';
import { addToPlaylist } from './playlist.js';
import { updateAmbassadors, updateDiscoveryVisuals, triggerDiscovery } from './discovery.js';
import { expandMenu } from './ui.js';

export function closePanel() {
  document.getElementById("artistPanel").classList.remove("open");
  if (S.currentAudio)   { S.currentAudio.pause(); S.setCurrentAudio(null); }
  if (S.currentPlayBtn) { S.currentPlayBtn.textContent = "▶"; S.setCurrentPlayBtn(null); }
  collapseSubmenu();
  if (S.discoveryMode && S.lastDiscovered !== null) {
    window._pendingDiscovery = null;
    S.setLastDiscovered(null);
    S.fringe.clear();
    S.subgraph.clear();
    updateAmbassadors();
    updateDiscoveryVisuals();
    if (!S.isMobile) expandMenu();
  }
}

export function collapseSubmenu() {
  document.querySelector(".track-submenu")?.remove();
  S.setExpandedTrackIndex(null);
}

function expandSubmenu(idx, rowEl) {
  collapseSubmenu();
  S.setExpandedTrackIndex(idx);
  const track  = S.currentTracks[idx];
  const artist = S.openArtistName || "";
  const addBtnInner = window.AUTHENTICATED
    ? `<span class="add-btn-icon"></span><span class="rainbow-text">＋ Queue</span>`
    : `<span class="rainbow-text">＋ My Playlist</span>`;

  const sub = document.createElement("div");
  sub.className = "track-submenu";
  sub.innerHTML = buildServiceLinks(artist, track.name, "sub-svc-btn", 18) +
    `<button class="add-playlist-btn">${addBtnInner}</button>`;
  rowEl.insertAdjacentElement("afterend", sub);
  requestAnimationFrame(() => { sub.style.maxHeight = "60px"; sub.style.opacity = "1"; });

  sub.querySelector(".add-playlist-btn").addEventListener("click", () => {
    addToPlaylist(track, sub, () => {
      if (window._pendingDiscovery) {
        triggerDiscovery(window._pendingDiscovery);
        window._pendingDiscovery = null;
      }
    });
  });
}

export function wireTrackInteractions() {
  document.querySelectorAll(".track-row").forEach(row => {
    const idx = parseInt(row.dataset.trackIndex, 10);

    row.addEventListener("click", function(e) {
      if (e.target.closest(".play-btn")) return;
      S.expandedTrackIndex === idx ? collapseSubmenu() : expandSubmenu(idx, this);
    });

    const btn = row.querySelector(".play-btn");
    if (!btn) return;
    btn.addEventListener("click", function(e) {
      e.stopPropagation();
      if (S.expandedTrackIndex !== idx) expandSubmenu(idx, row);

      const previewUrl = this.dataset.preview;
      if (!previewUrl) return;

      if (S.currentAudio && S.currentPlayBtn === this) {
        S.currentAudio.pause();
        S.setCurrentAudio(null); S.setCurrentPlayBtn(null);
        this.textContent = "▶";
        return;
      }
      if (S.currentAudio) {
        S.currentAudio.pause();
        if (S.currentPlayBtn) S.currentPlayBtn.textContent = "▶";
      }
      const audio = new Audio(previewUrl);
      audio.play().then(() => {
        if (window._pendingDiscovery) {
          triggerDiscovery(window._pendingDiscovery);
          window._pendingDiscovery = null;
        }
      }).catch(() => {});
      S.setCurrentAudio(audio); S.setCurrentPlayBtn(this);
      this.textContent = "▐▐";
      audio.addEventListener("ended", () => {
        this.textContent = "▶";
        S.setCurrentAudio(null); S.setCurrentPlayBtn(null);
      });
    });
  });
}

export function renderTrackList(tracks) {
  S.setCurrentTracks(tracks || []);
  if (!S.currentTracks.length) {
    return `<div style="font-size:9px;color:rgba(255,255,255,0.2);padding:16px;text-align:center">NO TRACKS AVAILABLE</div>`;
  }
  const header = `<div style="font-size:9px;letter-spacing:0.12em;color:rgba(255,255,255,0.3);margin:0 16px 8px">TOP TRACKS</div>`;
  return header + S.currentTracks.map((track, idx) => {
    const preview      = track.preview_url || "";
    const art          = track.album_art   || "/static/placeholder_artist.jpeg";
    const disabledStyle = preview ? "" : ";opacity:0.25;pointer-events:none";
    return (
      `<div class="track-row" data-track-index="${idx}" style="display:flex;align-items:center;padding:8px 16px;gap:10px;cursor:pointer"` +
      ` onmouseenter="this.style.background='rgba(255,255,255,0.04)'" onmouseleave="this.style.background=''">` +
      `<img src="${art}" style="width:40px;height:40px;object-fit:cover" onerror="this.src='/static/placeholder_artist.jpeg'" />` +
      `<span style="font-size:10px;flex:1;color:rgba(255,255,255,0.72)">${escapeHtml(track.name)}</span>` +
      `<button class="play-btn" data-preview="${preview}" style="font-size:12px;color:rgba(255,255,255,0.4);background:none;border:none;cursor:pointer${disabledStyle}">▶</button>` +
      `</div>`
    );
  }).join("");
}

export async function openPanel(artistName) {
  collapseSubmenu();
  const myId = S.panelRequestId + 1;
  S.setPanelRequestId(myId);
  S.setOpenArtistName(artistName);

  const resp = await fetch("/api/artist/" + encodeURIComponent(artistName));
  if (!resp.ok) return;
  const d = await resp.json();

  const artistProfiles = d.artist_profiles || [];
  let activeProfileIdx = 0;

  const metaParts = [d.genre, d.stage, d.day].filter(Boolean);
  const tagsHtml  = (d.tags || []).map(tag =>
    `<span style="display:inline-block;background:rgba(255,255,255,0.07);border-radius:3px;padding:2px 6px;font-size:9px;color:rgba(255,255,255,0.4);margin:0 4px 4px 0">${escapeHtml(tag)}</span>`
  ).join("");

  function getProfileImageUrl(idx) {
    if (artistProfiles[idx]) {
      const url = artistProfiles[idx].image_url || "";
      return (!url || url.includes(PLACEHOLDER_HASH)) ? "/static/placeholder_artist.jpeg" : url;
    }
    const imgUrl = d.image_url || "";
    return (!imgUrl || imgUrl.includes(PLACEHOLDER_HASH)) ? "/static/placeholder_artist.jpeg" : imgUrl;
  }

  function getProfileBio(idx) {
    if (artistProfiles[idx] && artistProfiles[idx].bio) {
      return `<div style="font-size:10px;line-height:1.6;color:rgba(255,255,255,0.55);margin:0 16px 16px;border-top:1px solid rgba(255,255,255,0.06);padding-top:12px">${escapeHtml(artistProfiles[idx].bio)}</div>`;
    }
    return "";
  }

  function updateCarouselImage(idx) {
    const img = document.getElementById("panelHeroImg");
    if (img) {
      img.src = getProfileImageUrl(idx);
    }
    const bioEl = document.getElementById("panelBio");
    if (bioEl) {
      bioEl.innerHTML = getProfileBio(idx);
    }
  }

  const imgUrl = artistProfiles[0]?.image_url || d.image_url || "";
  const imgSrc = getProfileImageUrl(0);
  const bioHtml = getProfileBio(0);

  // Build carousel HTML if multiple profiles
  const carouselHtml = artistProfiles.length > 1
    ? `<div class="hero-carousel" id="panelCarousel">` +
      `<img id="panelHeroImg" src="${imgSrc}" style="width:100%;object-fit:cover;max-height:280px;display:block" onerror="this.src='/static/placeholder_artist.jpeg'" />` +
      `<button class="carousel-arrow carousel-arrow-left" id="panelArrowLeft">‹</button>` +
      `<button class="carousel-arrow carousel-arrow-right" id="panelArrowRight">›</button>` +
      `</div>`
    : `<img id="panelHeroImg" src="${imgSrc}" style="width:100%;object-fit:cover;max-height:280px;display:block" onerror="this.src='/static/placeholder_artist.jpeg'" />`;

  document.getElementById("panelContent").innerHTML =
    carouselHtml +
    `<div style="font-size:15px;font-weight:bold;color:white;margin:12px 16px 4px">${escapeHtml(d.name)}</div>` +
    `<div style="font-size:10px;color:rgba(255,255,255,0.45);margin:0 16px 8px">${metaParts.map(escapeHtml).join(" · ")}</div>` +
    `<div style="margin:0 16px 12px">${tagsHtml}</div>` +
    `<div id="panelBio">${bioHtml}</div>` +
    `<div id="tracksLoading" style="display:flex;justify-content:center;align-items:center;padding:24px 0"><div class="spinner"></div></div>`;

  // Wire carousel arrows if multi-artist
  if (artistProfiles.length > 1) {
    const leftBtn = document.getElementById("panelArrowLeft");
    const rightBtn = document.getElementById("panelArrowRight");
    if (leftBtn) {
      leftBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        activeProfileIdx = (activeProfileIdx - 1 + artistProfiles.length) % artistProfiles.length;
        updateCarouselImage(activeProfileIdx);
      });
    }
    if (rightBtn) {
      rightBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        activeProfileIdx = (activeProfileIdx + 1) % artistProfiles.length;
        updateCarouselImage(activeProfileIdx);
      });
    }
  }

  document.getElementById("artistPanel").classList.add("open");

  try {
    const tr = await fetch("/api/artist/" + encodeURIComponent(artistName) + "/tracks");
    if (myId !== S.panelRequestId) return;
    const td = tr.ok ? await tr.json() : { tracks: [] };
    if (myId !== S.panelRequestId) return;
    const el = document.getElementById("tracksLoading");
    if (el) { el.outerHTML = renderTrackList(td.tracks || []); }
    wireTrackInteractions();
  } catch (_) {
    if (myId !== S.panelRequestId) return;
    const el = document.getElementById("tracksLoading");
    if (el) el.outerHTML = `<div style="font-size:9px;color:rgba(255,255,255,0.2);padding:16px;text-align:center">NO TRACKS AVAILABLE</div>`;
  }
}
