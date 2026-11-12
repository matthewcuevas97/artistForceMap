/**
 * Universal Artist Map: a D3 force graph of the user's seed artists and their
 * similar artists, grown on demand with the panel's EXPAND button.
 *
 * Data flow
 *   load        GET  /api/map/get          → render the saved map (if any)
 *   generate    POST /api/map/init/stream  → SSE progress, then the new map
 *   details     GET  /api/artist?name=     → tags/bio/tracks for a stub node
 *   expand      POST /api/map/expand       → merge new nodes/edges in place
 *   play        GET  /api/preview?...      → fresh Deezer preview URL
 *
 * Everything that reaches innerHTML goes through escapeHtml()/safeUrl(): artist
 * names, tags, bios and track titles are user-generated content on Last.fm/Deezer.
 */
(function () {
  "use strict";

  // ── Helpers ──────────────────────────────────────────────────────────────────

  const GENRE_HUE = {
    "Electronic": 195, "Indie/Alt": 135, "Hip-Hop": 45, "R&B/Soul": 25, "Pop": 330,
    "Punk/Metal": 0, "Latin/Afro": 275, "Singer-Songwriter/Jazz": 30, "Unknown": 220,
  };

  function genreColor(genre) {
    const hue = GENRE_HUE[genre] ?? GENRE_HUE.Unknown;
    return `hsl(${hue}, 70%, 55%)`;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  /** Only absolute http(s) URLs may be used as src attributes (images come from
   *  Last.fm/Deezer CDNs). Returns the escaped URL, or "" for anything else. */
  function safeUrl(url) {
    if (!/^https?:\/\//i.test(String(url || ""))) return "";
    try {
      return escapeHtml(new URL(url).href);
    } catch (_) {
      return "";
    }
  }

  async function getJson(url, options) {
    const res = await fetch(url, options);
    let body = null;
    try { body = await res.json(); } catch (_) { /* non-JSON error page */ }
    if (!res.ok) throw new Error((body && body.error) || `HTTP ${res.status}`);
    return body;
  }

  // ── State ────────────────────────────────────────────────────────────────────

  const state = {
    authenticated: false,
    nodes: [],            // simulation node objects (keep x/y across merges)
    edges: [],
    nodeByName: new Map(),
    selected: null,
    panelRequest: 0,
    nodeSize: 1,
    charge: -50,
    showLabels: true,
    audio: null,
    audioBtn: null,
  };

  const $ = id => document.getElementById(id);
  const el = {
    controls: $("controls"), menuToggle: $("menuToggle"),
    spotifyBtn: $("spotifyBtn"), spotifyConnected: $("spotifyConnected"),
    spotifyUserLabel: $("spotifyUserLabel"), spotifyDisconnect: $("spotifyDisconnect"),
    lastfmConnected: $("lastfmConnected"), lastfmUserLabel: $("lastfmUserLabel"),
    lastfmDisconnect: $("lastfmDisconnect"), lastfmInput: $("lastfmInput"),
    lastfmUsername: $("lastfmUsername"), lastfmGo: $("lastfmGo"), lastfmError: $("lastfmError"),
    initRow: $("initRow"), initBtn: $("initBtn"), initStatus: $("initStatus"),
    sep1: $("sep1"), sizeRow: $("sizeRow"), nodeSizeSlider: $("nodeSizeSlider"),
    nodeSizeValue: $("nodeSizeValue"), chargeRow: $("chargeRow"), chargeSlider: $("chargeSlider"),
    chargeValue: $("chargeValue"), sep2: $("sep2"), optionsRow: $("optionsRow"),
    labelsCheck: $("labelsCheck"), artistPanel: $("artistPanel"), panelClose: $("panelClose"),
    panelContent: $("panelContent"),
  };

  // ── Auth UI ──────────────────────────────────────────────────────────────────

  function updateAuthUI() {
    if (window.SPOTIFY_DISPLAY_NAME) {
      state.authenticated = true;
      el.spotifyBtn.style.display = "none";
      el.spotifyConnected.style.display = "block";
      el.spotifyUserLabel.textContent = window.SPOTIFY_DISPLAY_NAME;
    } else if (window.LASTFM_USER) {
      state.authenticated = true;
      el.lastfmInput.style.display = "none";
      el.lastfmConnected.style.display = "block";
      el.lastfmUserLabel.textContent = window.LASTFM_USER;
    }
    const show = state.authenticated ? "block" : "none";
    [el.initRow, el.sep1, el.sizeRow, el.chargeRow, el.sep2, el.optionsRow]
      .forEach(e => { e.style.display = show; });
  }

  el.spotifyBtn.addEventListener("click", () => { window.location.href = "/login"; });
  el.spotifyDisconnect.addEventListener("click", async () => {
    await fetch("/api/spotify/logout", { method: "POST" });
    location.reload();
  });
  el.lastfmDisconnect.addEventListener("click", async () => {
    await fetch("/api/lastfm/logout", { method: "POST" });
    location.reload();
  });

  async function lastfmLogin() {
    const username = el.lastfmUsername.value.trim();
    if (!username) return;
    el.lastfmError.style.display = "none";
    try {
      await getJson("/api/lastfm/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username }),
      });
      location.reload();
    } catch (_) {
      el.lastfmError.style.display = "block";
    }
  }
  el.lastfmGo.addEventListener("click", lastfmLogin);
  el.lastfmUsername.addEventListener("keydown", e => { if (e.key === "Enter") lastfmLogin(); });

  // ── Controls ─────────────────────────────────────────────────────────────────

  el.menuToggle.addEventListener("click", () => el.controls.classList.toggle("minimized"));
  el.panelClose.addEventListener("click", () => { select(null); closePanel(); });

  el.nodeSizeSlider.addEventListener("input", e => {
    state.nodeSize = parseFloat(e.target.value);
    el.nodeSizeValue.textContent = state.nodeSize.toFixed(2);
    graph.restyle();
  });
  el.chargeSlider.addEventListener("input", e => {
    state.charge = parseInt(e.target.value, 10);
    el.chargeValue.textContent = state.charge;
    graph.setCharge(state.charge);
  });
  el.labelsCheck.addEventListener("change", e => {
    state.showLabels = e.target.checked;
    graph.restyle();
  });

  // ── Status box ───────────────────────────────────────────────────────────────

  function statusLine(text, kind) {
    const div = document.createElement("div");
    div.className = "status-line" + (kind ? ` status-${kind}` : "");
    div.textContent = text;
    return div;
  }

  function setStatus(text, kind) {
    el.initStatus.style.display = "block";
    el.initStatus.replaceChildren(statusLine(text, kind));
  }

  // ── Map generation (SSE) ─────────────────────────────────────────────────────

  async function generateMap() {
    el.initBtn.disabled = true;
    el.initBtn.classList.add("loading");
    el.initStatus.style.display = "block";
    el.initStatus.replaceChildren();
    try {
      const res = await fetch("/api/map/init/stream", { method: "POST" });
      if (!res.ok || !res.body) {
        let msg = `HTTP ${res.status}`;
        try { msg = (await res.json()).error || msg; } catch (_) { /* keep status */ }
        throw new Error(msg);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const lines = buffer.split("\n");
        buffer = done ? "" : lines.pop();
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;   // ": keepalive" comments, blank lines
          let event;
          try {
            event = JSON.parse(line.slice(6));
          } catch (_) {
            console.warn("Ignoring malformed progress event:", line);
            continue;
          }
          // Handled outside the parse try/catch so the error reaches the user (BUG-14).
          if (event.error) throw new Error(event.error);
          if (event.message) {
            el.initStatus.appendChild(statusLine(event.message));
            el.initStatus.scrollTop = el.initStatus.scrollHeight;
          }
          if (event.complete) {
            graph.replace(event.nodes || [], event.edges || []);
            setStatus(`✓ Map ready! ${state.nodes.length} nodes, ${state.edges.length} connections`, "ok");
            el.initBtn.textContent = "REGENERATE MY MAP";
            setTimeout(() => { el.initStatus.style.display = "none"; }, 3000);
            return;
          }
        }
        if (done) throw new Error("The connection closed before the map was ready.");
      }
    } catch (e) {
      setStatus(`Error: ${e.message}`, "error");
    } finally {
      el.initBtn.disabled = false;
      el.initBtn.classList.remove("loading");
    }
  }
  el.initBtn.addEventListener("click", generateMap);

  async function loadSavedMap() {
    try {
      const data = await getJson("/api/map/get");
      if (data.nodes && data.nodes.length) {
        graph.replace(data.nodes, data.edges || []);
        el.initBtn.textContent = "REGENERATE MY MAP";
      }
    } catch (e) {
      console.warn("Could not load saved map:", e.message);
    }
  }

  // ── Graph ────────────────────────────────────────────────────────────────────

  const graph = (() => {
    const svg = d3.select("#graph");
    const root = svg.append("g");
    const gEdges = root.append("g").attr("class", "edges");
    const gNodes = root.append("g").attr("class", "nodes");
    const gLabels = root.append("g").attr("class", "labels");
    const zoom = d3.zoom().scaleExtent([0.1, 8]).on("zoom", e => root.attr("transform", e.transform));
    svg.call(zoom).on("dblclick.zoom", null);
    svg.on("click", () => { select(null); closePanel(); });

    let edgeSel = gEdges.selectAll("line");
    let nodeSel = gNodes.selectAll("circle");
    let labelSel = gLabels.selectAll("text");
    let radiusScale = () => 4;

    const sim = d3.forceSimulation()
      .force("link", d3.forceLink().id(d => d.name).distance(90).strength(e => 0.2 + 0.5 * (e.weight || 0.5)))
      .force("charge", d3.forceManyBody().strength(state.charge * 4))
      .force("collide", d3.forceCollide().radius(d => radius(d) + 4))
      .force("x", d3.forceX().strength(0.04))
      .force("y", d3.forceY().strength(0.04))
      .on("tick", ticked);
    sim.stop();

    function size() {
      const w = window.innerWidth, h = window.innerHeight;
      svg.attr("width", w).attr("height", h);
      sim.force("x").x(w / 2);
      sim.force("y").y(h / 2);
      return { w, h };
    }
    size();
    let resizeTimer = null;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => { size(); sim.alpha(0.1).restart(); }, 150);
    });

    // Radius from listeners, sqrt-scaled across the map's known range (BUG-15).
    function rescale() {
      const known = state.nodes.map(d => d.listeners || 0).filter(v => v > 0);
      const [lo, hi] = known.length ? d3.extent(known) : [0, 1];
      const s = d3.scaleSqrt().domain([lo, Math.max(hi, lo + 1)]).range([5, 18]).clamp(true);
      radiusScale = d => (d.listeners > 0 ? s(d.listeners) : 4);
    }
    function radius(d) { return radiusScale(d) * state.nodeSize; }

    function ticked() {
      edgeSel.attr("x1", e => e.source.x).attr("y1", e => e.source.y)
             .attr("x2", e => e.target.x).attr("y2", e => e.target.y);
      nodeSel.attr("cx", d => d.x).attr("cy", d => d.y);
      labelSel.attr("x", d => d.x).attr("y", d => d.y + radius(d) + 11);
    }

    function restyle() {
      nodeSel
        .attr("r", radius)
        .attr("fill", d => genreColor(d.genre || "Unknown"))
        .attr("stroke", d => d.name === state.selected ? "rgba(100,200,100,0.95)"
                           : d.seed ? "rgba(255,255,255,0.75)" : "rgba(255,255,255,0.25)")
        .attr("stroke-width", d => d.name === state.selected ? 2.5 : d.seed ? 2 : 1);
      labelSel
        .attr("opacity", state.showLabels ? 1 : 0)
        .attr("font-weight", d => d.seed ? 500 : 400)
        .attr("fill", d => d.seed ? "rgba(255,255,255,0.85)" : "rgba(255,255,255,0.5)");
      sim.force("collide").radius(d => radius(d) + 4);
      ticked();
    }

    function join() {
      edgeSel = gEdges.selectAll("line")
        .data(state.edges, e => `${nameOf(e.source)}→${nameOf(e.target)}`)
        .join("line")
        .attr("stroke", "rgba(255,255,255,0.14)")
        .attr("stroke-width", e => 0.6 + 1.6 * (e.weight || 0.3));
      nodeSel = gNodes.selectAll("circle")
        .data(state.nodes, d => d.name)
        .join(enter => enter.append("circle")
          .attr("class", "node")
          .attr("data-name", d => d.name)
          .style("cursor", "pointer")
          .on("click", (event, d) => { event.stopPropagation(); select(d.name); openPanel(d); })
          .call(d3.drag()
            .on("start", (event, d) => { if (!event.active) sim.alphaTarget(0.2).restart(); d.fx = d.x; d.fy = d.y; })
            .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
            .on("end", (event, d) => { if (!event.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })));
      labelSel = gLabels.selectAll("text")
        .data(state.nodes, d => d.name)
        .join("text")
        .attr("class", "label")
        .attr("font-size", 10)
        .attr("text-anchor", "middle")
        .attr("pointer-events", "none")
        .text(d => d.name);
      rescale();
      restyle();
    }

    function nameOf(n) { return typeof n === "object" ? n.name : n; }

    function setData(nodes, edges) {
      state.nodes = nodes;
      state.nodeByName = new Map(nodes.map(n => [n.name, n]));
      state.edges = edges.filter(e => state.nodeByName.has(nameOf(e.source)) && state.nodeByName.has(nameOf(e.target)))
                         .map(e => ({ ...e, source: nameOf(e.source), target: nameOf(e.target) }));
      sim.nodes(state.nodes);
      sim.force("link").links(state.edges);
      join();
    }

    function fit(duration) {
      if (!state.nodes.length) return;
      const { w, h } = { w: window.innerWidth, h: window.innerHeight };
      const xs = state.nodes.map(d => d.x), ys = state.nodes.map(d => d.y);
      const pad = 60;
      const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad;
      const y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
      const k = Math.min(w / (x1 - x0), h / (y1 - y0), 2);
      const t = d3.zoomIdentity.translate(w / 2 - k * (x0 + x1) / 2, h / 2 - k * (y0 + y1) / 2).scale(k);
      (duration ? svg.transition().duration(duration) : svg).call(zoom.transform, t);
    }

    /** Replace the whole map (initial load / regenerate). */
    function replace(nodes, edges) {
      const { w, h } = size();
      nodes.forEach((n, i) => {   // start on a small circle so the layout unfolds evenly
        const a = (2 * Math.PI * i) / Math.max(nodes.length, 1);
        n.x = w / 2 + 40 * Math.cos(a); n.y = h / 2 + 40 * Math.sin(a);
      });
      setData(nodes, edges);
      sim.alpha(1);
      sim.tick(Math.ceil(Math.log(sim.alphaMin()) / Math.log(1 - sim.alphaDecay())));
      ticked();
      fit(0);
      sim.alpha(0.05).restart();
    }

    /** Merge a server map into the running simulation, keeping existing positions. */
    function merge(nodes, edges, parentName) {
      const parent = state.nodeByName.get(parentName);
      const merged = nodes.map(n => {
        const existing = state.nodeByName.get(n.name);
        if (existing) return Object.assign(existing, n, { x: existing.x, y: existing.y });
        const a = Math.random() * 2 * Math.PI;
        return Object.assign(n, {
          x: (parent ? parent.x : window.innerWidth / 2) + 30 * Math.cos(a),
          y: (parent ? parent.y : window.innerHeight / 2) + 30 * Math.sin(a),
        });
      });
      setData(merged, edges);
      sim.alpha(0.5).restart();
    }

    function setCharge(c) {
      sim.force("charge").strength(c * 4);
      sim.alpha(0.3).restart();
    }

    return { replace, merge, restyle, setCharge, fit };
  })();

  function select(name) {
    state.selected = name;
    graph.restyle();
  }

  // ── Artist panel ─────────────────────────────────────────────────────────────

  function stopAudio() {
    if (state.audio) state.audio.pause();
    if (state.audioBtn) {
      state.audioBtn.classList.remove("playing");
      state.audioBtn.textContent = "▶ PLAY";
    }
    state.audio = null;
    state.audioBtn = null;
  }

  function closePanel() {
    stopAudio();
    state.panelRequest++;
    el.artistPanel.classList.remove("open");
    el.panelContent.innerHTML = "";
  }

  function renderPanel(artist, { loading = false, error = "" } = {}) {
    const img = safeUrl(artist.image_url);
    const tags = (artist.tags || []).slice(0, 5);
    const tracks = (artist.top_tracks || []).slice(0, 10);
    const listeners = artist.listeners > 0 ? `${Number(artist.listeners).toLocaleString()} listeners` : "";
    const meta = [listeners, artist.seed ? "one of your artists" : artist.parent ? `similar to ${artist.parent}` : ""]
      .filter(Boolean).join(" · ");

    let html = img ? `<img class="panel-hero" src="${img}" alt="" />` : "";
    html += `<div class="panel-body">`;
    html += `<div class="panel-name">${escapeHtml(artist.name)}</div>`;
    html += `<div class="panel-meta">${escapeHtml(meta)}</div>`;
    html += artist.expanded
      ? `<button class="panel-expand" id="expandBtn" disabled>EXPANDED</button>`
      : `<button class="panel-expand" id="expandBtn">+ EXPAND: ADD SIMILAR ARTISTS</button>`;
    html += `<div class="panel-error" id="panelError">${escapeHtml(error)}</div>`;
    if (tags.length) {
      html += `<div class="panel-tags">${tags.map(t => `<div class="panel-tag">${escapeHtml(t)}</div>`).join("")}</div>`;
    }
    if (artist.bio) html += `<div class="panel-bio">${escapeHtml(artist.bio)}</div>`;
    if (loading) html += `<div class="panel-loading"><div class="spinner"></div></div>`;
    if (tracks.length) {
      html += `<div class="panel-section-label">TOP TRACKS</div><div class="panel-tracks">`;
      tracks.forEach((t, i) => {
        const art = safeUrl(t.album_art);
        html += `<div class="track-row">` +
          (art ? `<img class="track-art" src="${art}" alt="" />` : `<div class="track-art track-art-empty"></div>`) +
          `<div class="track-name" title="${escapeHtml(t.name)}">${escapeHtml(t.name)}</div>` +
          `<button class="track-play" data-track-idx="${i}">▶ PLAY</button></div>`;
      });
      html += `</div>`;
    }
    html += `</div>`;
    el.panelContent.innerHTML = html;
    el.artistPanel.classList.add("open");

    $("expandBtn").addEventListener("click", e => { e.stopPropagation(); expand(artist); });
    el.panelContent.querySelectorAll(".track-play").forEach(btn => {
      btn.addEventListener("click", e => {
        e.stopPropagation();
        playTrack(btn, artist, tracks[parseInt(btn.dataset.trackIdx, 10)]);
      });
    });
  }

  async function openPanel(artist) {
    stopAudio();
    const myRequest = ++state.panelRequest;
    renderPanel(artist, { loading: !artist.details_loaded });
    if (artist.details_loaded) return;
    try {
      const details = await getJson(`/api/artist?name=${encodeURIComponent(artist.name)}`);
      Object.assign(artist, details);
      graph.restyle();
      if (myRequest === state.panelRequest) renderPanel(artist);
    } catch (e) {
      if (myRequest === state.panelRequest) renderPanel(artist, { error: `Couldn't load details: ${e.message}` });
    }
  }

  async function expand(artist) {
    const btn = $("expandBtn");
    const myRequest = state.panelRequest;
    if (btn) { btn.disabled = true; btn.textContent = "EXPANDING…"; }
    try {
      const data = await getJson("/api/map/expand", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ artist: artist.name }),
      });
      graph.merge(data.nodes || [], data.edges || [], artist.name);
      artist.expanded = true;
      if (myRequest === state.panelRequest) {
        renderPanel(artist);
        const added = (data.added_nodes || []).length;
        $("panelError").textContent = added ? "" : "No new similar artists found.";
      }
    } catch (e) {
      if (myRequest === state.panelRequest) renderPanel(artist, { error: `Expand failed: ${e.message}` });
    }
  }

  async function playTrack(btn, artist, track) {
    if (state.audioBtn === btn) { stopAudio(); return; }
    stopAudio();
    state.audioBtn = btn;
    btn.textContent = "…";
    const params = new URLSearchParams();
    if (track.deezer_id) params.set("deezer_id", track.deezer_id);
    params.set("artist", track.artist || artist.name);
    params.set("title", track.name || "");
    try {
      const { preview_url: url } = await getJson(`/api/preview?${params}`);
      if (state.audioBtn !== btn) return;          // user clicked something else meanwhile
      if (!url) throw new Error("no preview");
      const audio = new Audio(url);
      audio.addEventListener("ended", stopAudio);
      state.audio = audio;
      await audio.play();                          // rejects for dead/blocked media (BUG-38)
      if (state.audioBtn === btn) {
        btn.classList.add("playing");
        btn.textContent = "❚❚ STOP";
      }
    } catch (_) {
      if (state.audioBtn === btn) {
        stopAudio();
        btn.textContent = "N/A";
        btn.disabled = true;
      }
    }
  }

  // ── Boot ─────────────────────────────────────────────────────────────────────

  updateAuthUI();
  if (state.authenticated) loadSavedMap();
})();
