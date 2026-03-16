/**
 * drawer.js — mobile bottom drawer.
 * Receives `unpinCurrentNode` as a callback to avoid circular dep with main.js.
 */

import { escapeHtml, buildServiceLinks } from './utils.js';
import { PLACEHOLDER_HASH, DRAWER_PLAY_SVG, DRAWER_PAUSE_SVG, DRAWER_PEEK_H } from './constants.js';
import * as S from './state.js';
import { addToPlaylist } from './playlist.js';
import { updateDiscoveryVisuals, updateAmbassadors, triggerDiscovery } from './discovery.js';
import { exitSubgraphHighlight } from './simulation.js';
import { minimizeMenu, expandMenu } from './ui.js';

// Callback registered by main.js to break the circular dep
let _unpinCurrentNode = () => {};
export function registerUnpinCallback(fn) { _unpinCurrentNode = fn; }

// ── Drawer state management ───────────────────────────────────────────────────

export function setDrawerState(state) {
  if (state === 'hidden' && S.pinnedDatum) state = 'peek';

  S.setDrawerState(state);
  const drawer   = document.getElementById("artistDrawer");
  const scrollEl = document.getElementById("drawerScroll");
  const hero     = document.getElementById("drawerHero");
  if (!drawer) return;

  drawer.classList.remove("drawer-hidden", "drawer-collapsed", "drawer-expanded", "drawer-peek");
  drawer.classList.add("drawer-" + state);
  drawer.style.pointerEvents = (state === 'hidden') ? 'none' : 'auto';

  // Toggle carousel arrows visibility on hero
  if (hero) {
    if (state === 'expanded') {
      hero.classList.add("drawer-arrows-visible");
    } else {
      hero.classList.remove("drawer-arrows-visible");
    }
  }

  if (state === 'hidden') {
    drawer.style.transform = 'translateY(100%)';
    drawer.style.height    = DRAWER_PEEK_H + 'px';
    if (scrollEl) scrollEl.style.overflowY = 'hidden';
    if (S.currentAudio) { S.currentAudio.pause(); S.setCurrentAudio(null); }
    if (S.currentPlayBtn) {
      S.currentPlayBtn.innerHTML = DRAWER_PLAY_SVG;
      S.currentPlayBtn.classList.remove("playing");
      S.setCurrentPlayBtn(null);
    }
    collapseDrawerSubmenu();
    exitSubgraphHighlight();
    if (S.discoveryMode && S.lastDiscovered !== null) {
      window._pendingDiscovery = null;
      S.setLastDiscovered(null);
      S.fringe.clear();
      S.subgraph.clear();
      updateAmbassadors();
      updateDiscoveryVisuals();
      if (!S.isMobile) expandMenu();
    }
  } else if (state === 'peek') {
    drawer.style.transform = 'translateY(0)';
    drawer.style.height    = DRAWER_PEEK_H + 'px';
    if (scrollEl) scrollEl.style.overflowY = 'hidden';
    _parallax(DRAWER_PEEK_H);
  } else if (state === 'collapsed') {
    const h = S.drawerCollapsedH();
    drawer.style.transform = 'translateY(0)';
    drawer.style.height    = h + 'px';
    if (scrollEl) { scrollEl.style.overflowY = 'hidden'; scrollEl.scrollTop = 0; }
    _parallax(h);
  } else if (state === 'expanded') {
    const h = S.drawerExpandedH();
    drawer.style.transform = 'translateY(0)';
    drawer.style.height    = h + 'px';
    if (scrollEl) scrollEl.style.overflowY = 'auto';
    _parallax(h);
  }
}

function _parallax(heightPx) {
  const hero = document.getElementById("drawerHero");
  if (!hero) return;
  const ratio = Math.max(0, Math.min(1,
    (heightPx - DRAWER_PEEK_H) / (S.drawerExpandedH() - DRAWER_PEEK_H)
  ));
  hero.style.backgroundPositionY = (33 - ratio * 13) + "%";
}

export function openDrawer(artistName) {
  closeAllPanels('drawer');
  setDrawerState('collapsed');
  // Find the full node datum so hero image / meta is available immediately
  const datum = S.rawNodes.find(n => n.name === artistName) || { name: artistName };
  populateDrawer(datum);
}

export function closeAllPanels(except) {
  if (except !== 'controls' && S.isMobile) minimizeMenu();
  if (except !== 'drawer'   && S.isMobile) setDrawerState('hidden');
  if (except !== 'export') {
    const panel = document.getElementById("exportPanel");
    if (panel) {
      panel.classList.remove("open");
      setTimeout(() => { panel.style.display = "none"; }, 260);
    }
  }
}

// ── Populate ──────────────────────────────────────────────────────────────────

export async function populateDrawer(d) {
  const myId = S.drawerRequestId + 1;
  S.setDrawerRequestId(myId);
  S.setDrawerArtistName(d.name);
  S.setDrawerTracks([]);
  S.setDrawerExpandedIdx(null);

  const artistProfiles = d.artist_profiles || [];
  let activeProfileIdx = 0;

  const hero = document.getElementById("drawerHero");
  const bioEl = document.getElementById("drawerBio");

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
      return artistProfiles[idx].bio;
    }
    return d.bio || "";
  }

  function updateCarouselImage(idx) {
    if (hero) {
      hero.style.backgroundImage = `url('${getProfileImageUrl(idx)}')`;
    }
    if (bioEl) {
      bioEl.textContent = getProfileBio(idx);
      bioEl.style.display = getProfileBio(idx) ? "block" : "none";
    }
  }

  // Set initial hero image
  hero.style.backgroundImage = `url('${getProfileImageUrl(0)}')`;
  document.getElementById("drawerHeroName").textContent = d.name || "";

  const metaStr = [d.genre, d.stage, d.day].filter(Boolean).join(" · ");
  document.getElementById("drawerMetaLine").textContent      = metaStr;
  document.getElementById("drawerHeroPeekMeta").textContent  = metaStr;
  document.getElementById("drawerMetaTags").innerHTML = (d.tags || [])
    .map(t => `<span class="drawer-tag">${escapeHtml(t)}</span>`).join("");

  // Clear old carousel arrows if they exist
  hero.querySelectorAll(".carousel-arrow").forEach(el => el.remove());

  // Add carousel arrows if multi-artist
  if (artistProfiles.length > 1) {
    const leftBtn = document.createElement("button");
    leftBtn.className = "carousel-arrow carousel-arrow-left";
    leftBtn.textContent = "‹";
    leftBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      activeProfileIdx = (activeProfileIdx - 1 + artistProfiles.length) % artistProfiles.length;
      updateCarouselImage(activeProfileIdx);
    });
    hero.appendChild(leftBtn);

    const rightBtn = document.createElement("button");
    rightBtn.className = "carousel-arrow carousel-arrow-right";
    rightBtn.textContent = "›";
    rightBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      activeProfileIdx = (activeProfileIdx + 1) % artistProfiles.length;
      updateCarouselImage(activeProfileIdx);
    });
    hero.appendChild(rightBtn);
  }

  const tracksEl = document.getElementById("drawerTracks");
  tracksEl.innerHTML =
    `<div style="display:flex;justify-content:center;align-items:center;padding:24px 0">` +
    `<div class="spinner"></div></div>`;
  bioEl.style.display = "none";
  bioEl.textContent   = "";

  // Fetch tracks
  try {
    const r = await fetch("/api/artist/" + encodeURIComponent(d.name) + "/tracks");
    if (myId !== S.drawerRequestId) return;
    const data = r.ok ? await r.json() : { tracks: [] };
    if (myId !== S.drawerRequestId) return;

    S.setDrawerTracks(data.tracks || []);

    if (!S.drawerTracks.length) {
      tracksEl.innerHTML =
        `<div style="font-size:9px;color:rgba(255,255,255,0.2);padding:16px;text-align:center;font-family:'IBM Plex Mono',monospace;letter-spacing:0.1em">NO TRACKS AVAILABLE</div>`;
    } else {
      const header =
        `<div style="font-size:9px;letter-spacing:0.12em;color:rgba(255,255,255,0.3);padding:8px 16px 4px;font-family:'IBM Plex Mono',monospace">TOP TRACKS</div>`;
      const rows = S.drawerTracks.map((track, idx) => {
        const art     = track.album_art || "/static/placeholder_artist.jpeg";
        const preview = track.preview_url || "";
        const artistName = track.artist || d.name;
        return (
          `<div class="drawer-track-row" data-drawer-track-index="${idx}">` +
          `<img class="drawer-track-art" src="${escapeHtml(art)}" onerror="this.src='/static/placeholder_artist.jpeg'" />` +
          `<div class="drawer-track-info">` +
          `<div class="drawer-track-name">${escapeHtml(track.name)}</div>` +
          `<div class="drawer-track-artist">${escapeHtml(artistName)}</div>` +
          `</div>` +
          `<button class="drawer-play-btn" data-preview="${escapeHtml(preview)}" style="${preview ? "" : "opacity:0.25;pointer-events:none;"}">${DRAWER_PLAY_SVG}</button>` +
          `</div>` +
          `<div class="drawer-track-submenu" data-drawer-submenu-index="${idx}">` +
          buildServiceLinks(d.name, track.name, "sub-svc-btn", 18) +
          `<button class="add-playlist-btn" data-drawer-add-index="${idx}">` +
          (window.AUTHENTICATED ? `<span class="add-btn-icon"></span><span class="rainbow-text">＋ Queue</span>` : `<span class="rainbow-text">＋ My Playlist</span>`) +
          `</button></div>`
        );
      }).join("");
      tracksEl.innerHTML = header + rows;
      _wireDrawerTracks();
    }
  } catch (_) {
    if (myId !== S.drawerRequestId) return;
    tracksEl.innerHTML =
      `<div style="font-size:9px;color:rgba(255,255,255,0.2);padding:16px;text-align:center;font-family:'IBM Plex Mono',monospace;letter-spacing:0.1em">NO TRACKS AVAILABLE</div>`;
  }

  // Set initial bio
  const initialBio = getProfileBio(0);
  if (initialBio) {
    bioEl.textContent = initialBio;
    bioEl.style.display = "block";
  }
}

export function collapseDrawerSubmenu() {
  document.querySelector(".drawer-track-submenu.open")?.classList.remove("open");
  S.setDrawerExpandedIdx(null);
}

function _wireDrawerTracks() {
  const tracksEl = document.getElementById("drawerTracks");
  tracksEl.querySelectorAll(".drawer-track-row").forEach(row => {
    const idx     = parseInt(row.dataset.drawerTrackIndex, 10);
    const submenu = tracksEl.querySelector(`.drawer-track-submenu[data-drawer-submenu-index="${idx}"]`);

    row.addEventListener("click", function(e) {
      if (e.target.closest(".drawer-play-btn")) return;
      if (S.drawerState === 'collapsed') { closeAllPanels('drawer'); setDrawerState('expanded'); }
      if (S.drawerExpandedIdx === idx) {
        collapseDrawerSubmenu();
      } else {
        collapseDrawerSubmenu();
        S.setDrawerExpandedIdx(idx);
        if (submenu) submenu.classList.add("open");
      }
    });

    if (submenu) {
      submenu.querySelector(".add-playlist-btn").addEventListener("click", e => {
        e.stopPropagation();
        addToPlaylist(S.drawerTracks[idx], submenu, () => {
          if (window._pendingDiscovery) {
            triggerDiscovery(window._pendingDiscovery);
            window._pendingDiscovery = null;
          }
        });
      });
    }

    const playBtn = row.querySelector(".drawer-play-btn");
    if (!playBtn) return;
    playBtn.addEventListener("click", function(e) {
      e.stopPropagation();
      if (S.drawerState === 'collapsed' || S.drawerState === 'peek') {
        closeAllPanels('drawer'); setDrawerState('expanded');
      }
      if (S.drawerExpandedIdx !== idx) {
        collapseDrawerSubmenu();
        S.setDrawerExpandedIdx(idx);
        if (submenu) submenu.classList.add("open");
      }

      const previewUrl = this.dataset.preview;
      if (!previewUrl) return;

      if (S.currentAudio && S.currentPlayBtn === this) {
        S.currentAudio.pause();
        S.setCurrentAudio(null); S.setCurrentPlayBtn(null);
        this.innerHTML = DRAWER_PLAY_SVG;
        this.classList.remove("playing");
        return;
      }
      if (S.currentAudio) {
        S.currentAudio.pause();
        if (S.currentPlayBtn) { S.currentPlayBtn.innerHTML = DRAWER_PLAY_SVG; S.currentPlayBtn.classList.remove("playing"); }
      }
      const audio = new Audio(previewUrl);
      audio.play().catch(() => {});
      S.setCurrentAudio(audio); S.setCurrentPlayBtn(this);
      this.innerHTML = DRAWER_PAUSE_SVG;
      this.classList.add("playing");
      audio.addEventListener("ended", () => {
        this.innerHTML = DRAWER_PLAY_SVG; this.classList.remove("playing");
        S.setCurrentAudio(null); S.setCurrentPlayBtn(null);
      });
    });
  });
}

// ── Touch gestures ────────────────────────────────────────────────────────────

export function initDrawerGestures() {
  if (!S.isMobile) return;
  const drawer   = document.getElementById("artistDrawer");
  const scrollEl = document.getElementById("drawerScroll");

  let startY = 0, startHeight = 0, isDragging = false, committed = null;
  const samples = [];

  function applyDrag(currentY) {
    const deltaY = startY - currentY;
    const minH   = S.pinnedDatum ? DRAWER_PEEK_H : 0;
    const maxH   = S.drawerExpandedH();
    let   newH   = Math.max(minH, Math.min(maxH, startHeight + deltaY));
    if (!S.pinnedDatum && startHeight + deltaY < DRAWER_PEEK_H) {
      const excess = DRAWER_PEEK_H - (startHeight + deltaY);
      drawer.style.transform = `translateY(${Math.max(0, excess)}px)`;
      drawer.style.height    = DRAWER_PEEK_H + 'px';
    } else {
      drawer.style.transform = 'translateY(0)';
      drawer.style.height    = newH + 'px';
    }
    _parallax(newH);
  }

  function snapFromDrag() {
    let velocity = 0;
    if (samples.length >= 2) {
      const dt = samples[samples.length-1].t - samples[0].t;
      if (dt > 0) velocity = (samples[0].y - samples[samples.length-1].y) / dt;
    }
    const currentH = drawer.offsetHeight;
    const collH    = S.drawerCollapsedH();
    const expH     = S.drawerExpandedH();
    drawer.style.transition = '';

    let target;
    if (Math.abs(velocity) >= 0.4) {
      if (velocity > 0) {
        target = currentH < collH - 30 ? 'collapsed' : 'expanded';
      } else {
        if      (currentH > collH + 30)         target = 'collapsed';
        else if (currentH > DRAWER_PEEK_H + 30) target = 'peek';
        else                                     target = 'hidden';
      }
    } else {
      const dPeek = Math.abs(currentH - DRAWER_PEEK_H);
      const dColl = Math.abs(currentH - collH);
      const dExp  = Math.abs(currentH - expH);
      if (dPeek <= dColl && dPeek <= dExp) target = 'peek';
      else target = dColl <= dExp ? 'collapsed' : 'expanded';
    }

    if ((target === 'hidden' || target === 'peek') && !S.pinnedDatum) {
      _unpinCurrentNode();
      S.setOpenArtistName(null);
    } else if (target === 'collapsed' || target === 'expanded') {
      closeAllPanels('drawer');
    }
    setDrawerState(target);
  }

  drawer.addEventListener("touchstart", e => {
    startY = e.touches[0].clientY;
    startHeight = drawer.offsetHeight;
    isDragging = false; committed = null;
    samples.length = 0;
    samples.push({ y: startY, t: Date.now() });
  }, { passive: true });

  drawer.addEventListener("touchmove", e => {
    const fingerY    = e.touches[0].clientY;
    const fingerDown = fingerY - startY;
    const inScroll   = scrollEl && e.target.closest("#drawerScroll");

    if (committed === null) {
      if (inScroll && S.drawerState === 'expanded') {
        committed = (scrollEl.scrollTop > 4 || fingerDown < 0) ? 'scroll' : 'drawer';
      } else {
        committed = 'drawer';
      }
    }
    if (committed === 'scroll') return;

    e.preventDefault();
    isDragging = true;
    drawer.style.transition = 'none';
    samples.push({ y: fingerY, t: Date.now() });
    if (samples.length > 10) samples.shift();
    applyDrag(fingerY);
  }, { passive: false });

  drawer.addEventListener("touchend", e => {
    if (!isDragging) return;
    isDragging = false; committed = null;
    snapFromDrag();
  }, { passive: true });

  drawer.addEventListener("touchcancel", () => {
    if (!isDragging) return;
    isDragging = false; committed = null;
    drawer.style.transition = '';
    setDrawerState(S.drawerState);
  }, { passive: true });
}
