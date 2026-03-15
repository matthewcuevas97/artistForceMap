# Design Document: artistForceMap

**Version**: 1.1
**Date**: 2026-03-14
**Status**: Pre-deployment (local development only; BFS similarity expansion in progress)

---

## 1. Purpose

artistForceMap is a web application that visualizes the Coachella 2026 music festival lineup as an interactive force-directed graph. It helps users explore artist relationships, discover new artists, preview music, and build playlists — all within a single-page interface.

---

## 2. System Architecture

### 2.1 High-Level Components

```
┌────────────────────────────────────────────────────────────────────┐
│                        Client (Browser)                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │  index.html   │  │  graph.js    │  │  D3.js v7 (CDN)         │ │
│  │  (HTML+CSS)   │  │  (1560 LOC)  │  │                          │ │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘ │
└─────────────────────────────┬──────────────────────────────────────┘
                              │ HTTP (JSON API)
┌─────────────────────────────▼──────────────────────────────────────┐
│                     Flask Server (app.py)                           │
│  ┌────────────────────────────────────────────────────────────────┐│
│  │  Routes:                                                       ││
│  │    GET  /              → serve SPA shell                       ││
│  │    GET  /login         → Spotify OAuth redirect                ││
│  │    GET  /callback      → Spotify OAuth callback                ││
│  │    POST /api/spotify/logout                                    ││
│  │    POST /api/lastfm/login                                     ││
│  │    POST /api/lastfm/logout                                    ││
│  │    GET  /api/graph?threshold=0.20                              ││
│  │    GET  /api/artist/<name>                                     ││
│  │    GET  /api/artist/<name>/tracks                              ││
│  │    POST /api/spotify/create-playlist                           ││
│  └────────────────────────────────────────────────────────────────┘│
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │ spotify/      │  │ lastfm/      │  │ data/                    │ │
│  │  auth.py      │  │  fetch.py    │  │  graph_builder.py        │ │
│  │  fetch.py     │  │              │  │  lineup.py               │ │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │ Spotify  │   │ Last.fm  │   │ Deezer   │
        │ Web API  │   │ API      │   │ API      │
        └──────────┘   └──────────┘   └──────────┘
```

### 2.2 Offline Data Pipeline

```
coachella_2026.csv
        │
        ▼
scripts/precompute.py
  Pass 1: Last.fm artist info (tags, listeners, genre classification)
  Pass 2: Last.fm similar artists (up to 50 per artist, threshold 0.05)
  Pass 3: Last.fm image+bio, Deezer top tracks
  Pass 4: Deezer fallback images (for Last.fm placeholder images)
        │
        ▼
data/graph_static.json  (~1-2 MB, 142 nodes with full metadata)
        │
        ▼
scripts/build_slim.py
  - Strips fields not needed at runtime (e.g., similar_artists)
  - Precomputes edges at 5 threshold levels
  - Keeps: name, genre, listeners, day, weekend, stage, image_url, bio, tags[:3], top_tracks
        │
        ▼
data/graph_slim.json  (optimized for serving)
```

---

## 3. Data Model

### 3.1 Artist Node (graph_slim.json)

```json
{
  "name": "Charli xcx",
  "genre": "Pop",
  "listeners": 3500000,
  "day": "Saturday",
  "weekend": "Both",
  "stage": "MAIN STAGE",
  "image_url": "https://lastfm.freetls.fastly.net/...",
  "bio": "Charlotte Emma Aitchison, known as Charli xcx...",
  "tags": ["pop", "electropop", "dance-pop"],
  "top_tracks": [
    {
      "name": "360",
      "deezer_url": "https://www.deezer.com/track/...",
      "album_art": "https://cdn-images.dzcdn.net/..."
    }
  ]
}
```

### 3.2 Edge

```json
{
  "source": "Artist A",
  "target": "Artist B",
  "weight": 0.42,
  "type": "similarity"
}
```

- **type**: `"similarity"` (Last.fm-derived) or `"genre"` (same-genre grouping)
- **weight**: 0.0-1.0, derived from `max(direct_lastfm_match, jaccard_similarity_of_similar_artists)`

### 3.3 Edge Thresholds

Edges are precomputed at 5 thresholds: `0.05, 0.10, 0.20, 0.30, 0.50`. The client requests a threshold; the server returns the precomputed edge set for the nearest threshold.

### 3.4 Genre Taxonomy

8 high-level genres mapped from 50+ Last.fm tags:

| Genre | Color Hue | Example Tags |
|-------|-----------|-------------|
| Electronic | 195 (cyan) | house, techno, dubstep, trance |
| Indie/Alt | 135 (green) | indie rock, shoegaze, post-punk |
| Hip-Hop | 45 (orange) | rap, trap, drill |
| R&B/Soul | 25 (warm orange) | rnb, neo-soul |
| Pop | 330 (pink) | electropop, k-pop, dance-pop |
| Punk/Metal | 0 (red) | punk rock, metalcore, emo |
| Latin/Afro | 275 (purple) | reggaeton, afrobeats, dancehall |
| Singer-Songwriter/Jazz | 30 (amber) | folk, jazz, indie folk |

### 3.5 Scoring System

Nodes receive a `score` (0.0-1.0) that drives visual prominence (radius, color saturation, label opacity):

1. **Baseline**: All nodes normalized by Last.fm listener count (`listeners / max_listeners`)
2. **Direct score**: If user's top artist matches a node name (normalized), `score = rank_position_score` (rank 1 = 1.0, rank 50 = 0.0)
3. **Derived score**: If user's top artist appears in a node's `similar_artists`, `derived = user_score * match_weight * 0.6`
4. Final `score = max(direct_score, derived_score, listener_baseline)`

---

## 4. Authentication

### 4.1 Spotify OAuth 2.0

- **Flow**: Authorization Code flow via Spotipy
- **Scopes**: `user-top-read`, `user-read-recently-played`, `playlist-modify-private`, `playlist-modify-public`
- **Token storage**: Flask session (server-side cookie)
- **Token refresh**: NOT implemented — tokens expire after 1 hour, at which point the session is silently cleared
- **Data used**: Top 50 artists (`current_user_top_artists`)

### 4.2 Last.fm Username

- **Flow**: Client POSTs username to `/api/lastfm/login`; server validates by fetching their top artists
- **Data used**: Top 100 artists over 6-month period
- **No OAuth required**: Last.fm's user top artists API is public given a username

### 4.3 Mutual Exclusion

Only one auth source is active at a time. Connecting Spotify clears Last.fm session, and vice versa.

---

## 5. Frontend Behavior

### 5.1 Graph Rendering

- **Engine**: D3.js v7 force simulation
- **Pre-ticking**: 300 iterations computed synchronously before first render (stable initial layout)
- **Edge filtering**: Only top-8 edges per node are rendered (by weight) to reduce visual clutter
- **Forces**: link, charge (-300), center, collide, x/y centering (0.05 strength)
- **Zoom/Pan**: D3 zoom with scale extent [0.05, 20]

### 5.2 Node Visuals

- **Radius**: `(4 + score * 20) * nodeScale`
- **Color**: HSL with hue from genre, saturation `20 + score * 70`, lightness `25 + score * 35`
- **Label**: IBM Plex Mono 11px, opacity based on score (hidden below 0.1)

### 5.3 Interactions

| Action | Result |
|--------|--------|
| Hover node | Highlight connected edges, show tooltip (name, genre, stage, day, weekend) |
| Click node | Pin node, open artist detail panel, enter subgraph view (1-hop neighborhood) |
| Click background | Unpin, close panel, exit subgraph view |
| Drag node | Reposition node (stays pinned at drop position) |
| Scroll | Zoom in/out |
| Click+drag background | Pan |

### 5.4 Controls Panel (Bottom-Left)

- **Auth**: Spotify connect/disconnect, Last.fm username input
- **My Playlist**: Export button (appears after adding tracks)
- **Day filter**: ALL / FRI / SAT / SUN
- **Edge threshold**: 5-level slider (0.05 to 0.50), triggers data re-fetch with 500ms debounce
- **Node size**: Continuous slider (0.5x to 3.0x), live update
- **Edge type toggles**: Similarity edges on/off, Genre edges on/off
- **Discovery mode**: Toggle + reset button
- **Fullscreen**: Toggle button
- **Collapsible**: Minimize/expand toggle

### 5.5 Artist Detail Panel (Right Sidebar, 320px)

Opens on node click. Shows:
1. Artist image (full-width)
2. Name, genre, stage, day
3. Tags (up to 3)
4. Bio (up to 300 chars, from Last.fm)
5. Top tracks (up to 5, from Deezer) with:
   - Album art thumbnail
   - Track name
   - Play/pause button (Deezer 30-second preview)
   - Expandable submenu with: Spotify/YouTube Music/Apple Music search links, "Add to playlist" button

### 5.6 Discovery Mode

A progressive exploration mechanic:

1. **Seed**: Top 20 nodes by score (prioritizes user-matched artists if authenticated)
2. **State**: `discovered` (explored), `fringe` (1-hop undiscovered neighbors), `ambassadors` (highest-score node from each disconnected undiscovered cluster)
3. **Interaction**: Click a fringe/ambassador node → opens panel. Playing a preview or adding to playlist triggers "discovery" (node joins discovered set)
4. **Visual**: Discovered nodes are filled; fringe/ambassadors are stroke-only outlines. Non-visible nodes are hidden.
5. **Persistence**: Discovery state saved to `localStorage`
6. **Counter**: Shows `discovered/total` in the controls header

### 5.7 Subgraph View (Non-Discovery)

Clicking any node in normal mode enters a 1-hop subgraph view:
- Focus node and its direct neighbors are highlighted
- All other nodes dim to 9% opacity
- A separate edge overlay shows connections within the subgraph
- Camera zooms/pans to frame the subgraph

### 5.8 Playlist / Export

- Users can queue tracks from the artist panel
- Export panel shows queued tracks with remove buttons
- **Authenticated (Spotify)**: "CREATE SPOTIFY PLAYLIST" button calls `/api/spotify/create-playlist`, which creates a private playlist named "Coachella 2026 · {date}" and searches Spotify for each track by artist+title
- **Unauthenticated**: Tap a track to see Spotify/YouTube Music/Apple Music search links

---

## 6. API Reference

### `GET /api/graph?threshold=0.20`

Returns the full graph data, enriched with the current user's scores.

**Response**:
```json
{
  "nodes": [{ "name": "...", "genre": "...", "score": 0.75, ... }],
  "edges": [{ "source": "A", "target": "B", "weight": 0.42, "type": "similarity" }],
  "threshold": 0.20,
  "user_seeds": ["Artist A", "Artist B"]
}
```

- `user_seeds`: Names of nodes that matched the user's listening data (direct or derived score > 0). Used to seed discovery mode.
- `threshold`: The actual threshold used (snapped to nearest precomputed level).

### `GET /api/artist/<name>`

Returns a single artist node (without internal scoring fields).

### `GET /api/artist/<name>/tracks`

Returns top tracks with fresh Deezer preview URLs. The preview URLs are fetched live because Deezer preview URLs expire.

**Response**:
```json
{
  "tracks": [
    { "name": "Track", "album_art": "https://...", "preview_url": "https://..." }
  ]
}
```

### `POST /api/spotify/create-playlist`

Creates a Spotify playlist from queued tracks. Requires active Spotify session.

**Request**:
```json
{
  "tracks": [{ "artist": "Artist Name", "name": "Track Name" }]
}
```

**Response**:
```json
{
  "ok": true,
  "playlist_url": "https://open.spotify.com/playlist/..."
}
```

---

## 7. External Dependencies

### 7.1 Runtime APIs

| API | Usage | Auth | Rate Limits |
|-----|-------|------|-------------|
| Spotify Web API | User top artists, playlist creation, track search | OAuth 2.0 (user token) | ~180 req/min per user |
| Last.fm API | User top artists (by username) | API key (query param) | 5 req/sec |
| Deezer API | Track preview URLs (live refresh) | None (public) | Undocumented, ~50 req/sec |

### 7.2 Offline APIs (Data Pipeline Only)

| API | Usage |
|-----|-------|
| Last.fm `artist.getInfo` | Tags, listener count |
| Last.fm `artist.getSimilar` | Similar artists + match scores |
| Last.fm `artist.getInfo` (bio) | Image URL, biography |
| Deezer artist search | Fallback artist images |
| Deezer artist top tracks | Track names, album art, links |

### 7.3 Python Dependencies

| Package | Purpose |
|---------|---------|
| flask | Web server + routing |
| spotipy | Spotify OAuth + API client |
| python-dotenv | Load `.env` file |
| requests | HTTP client for Last.fm, Deezer |

### 7.4 Frontend Dependencies

| Library | Source | Purpose |
|---------|--------|---------|
| D3.js v7.9.0 | CDN (cdnjs) | Force graph, SVG rendering, zoom/pan |
| IBM Plex Mono | Google Fonts CDN | UI font |

---

## 8. Deployment Considerations

### 8.1 Current State

- **Runs locally only**: `python app.py` on `127.0.0.1:8080`
- **No WSGI server**: Uses Flask's built-in development server
- **No Dockerfile or deployment config**
- **No CI/CD pipeline**
- **No production logging**

### 8.2 Deployment Requirements

1. **WSGI server**: Gunicorn or uWSGI (Flask's dev server is single-threaded and not production-safe)
2. **Reverse proxy**: Nginx or similar for TLS termination, static file serving, and connection handling
3. **Environment variables**: `FLASK_SECRET_KEY`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI`, `LASTFM_API_KEY` must be set securely
4. **Session backend**: Flask's default cookie-based sessions work but are limited to 4KB. For multiple concurrent users, consider server-side sessions (Redis/filesystem)
5. **Static files**: `graph_slim.json` (~500KB-1MB) and `graph_static.json` (~1-2MB) are loaded into memory at startup. Ensure the deployment has sufficient RAM.
6. **HTTPS**: Required for Spotify OAuth callback in production (Spotify enforces HTTPS redirect URIs for non-localhost)
7. **CORS**: Not currently configured. If the frontend is served from a different domain, Flask-CORS would be needed.

### 8.3 Scaling Characteristics

- **Stateless compute**: The Flask app itself is stateless (all user state is in session cookies). It can be horizontally scaled behind a load balancer.
- **In-memory data**: `_slim_nodes`, `_slim_edges`, `_slim_nodes_by_name`, `_static_nodes_by_name` are loaded into memory at startup and shared across requests (read-only). Each worker process duplicates this data (~2-5MB per worker).
- **Blocking I/O**: Deezer preview URL refresh (`/api/artist/<name>/tracks`) and Spotify API calls block the worker. With a synchronous WSGI server, concurrent requests are limited by worker count.
- **No database**: All data is file-based JSON. No migrations, no connection pooling, no query optimization needed.
- **No caching layer**: Every `/api/graph` request deep-copies nodes and re-enriches scores. Adding a cache (Redis or in-process TTL) keyed on `(user_id, threshold)` would eliminate redundant work.

### 8.4 Monitoring Needs

- **Error tracking**: Unhandled exceptions in routes (especially Spotify/Deezer API failures)
- **Latency**: `/api/graph` (score enrichment), `/api/artist/<name>/tracks` (Deezer calls)
- **API quota**: Deezer and Last.fm call volume
- **Session health**: Expired Spotify tokens (currently silent failures)

### 8.5 Data Pipeline Operations

The data pipeline (`scripts/precompute.py` + `scripts/build_slim.py`) is designed to run manually on a developer machine. For production:

- **Cadence**: Run once before each festival season (or when the lineup changes)
- **Duration**: ~15-30 minutes (142 artists × 4 passes with API rate limiting)
- **Output**: `graph_static.json` and `graph_slim.json` should be committed or deployed as artifacts
- **Idempotency**: Passes can be re-run individually (`--pass3-only`, `--pass4-only`, `--tracks-only`)

---

## 9. Recent Changes (2026-03-14)

### 9.1 BFS Similarity Graph Expansion with Caching

**Branch**: `feature/bfs-similarity`
**Commits**:
- `743308a` feat: add BFS similarity graph expansion with caching
- `bc0a063` checkpoint: clean frontend before bfs experiment
- `d27bf41` feat: mutual exclusivity between controls, playlist, and artist bio panels
- `6d889f9` feat: modular frontend rewrite with edge trimming and selection boost

**Changes**:
1. **Edge filtering optimization** (`static/graph.js`, `static/js/simulation.js`):
   - Reduced top-N edges per node from 8 to 3 (reduces visual clutter, improves performance)
   - Updated edge stroke width calculation for better visual clarity
   - Changes affect graph layout significantly — fewer connections force nodes to spread

2. **Force simulation tuning** (`static/js/simulation.js`):
   - Link force strength: 0.3 → 0.7 (stronger attraction to connected neighbors)
   - Charge force: -300 → -800 (stronger repulsion, prevents node overlap)
   - X/Y centering forces: 0.05 → 0.15/0.3 (stronger gravitation toward viewport center)
   - Pre-ticking iterations: 300 → 3000 (more stable initial layout, higher UI freeze time)

3. **UI improvements**:
   - Mutual exclusivity between controls, playlist, and artist bio panels (improved mobile UX)
   - Modular frontend structure (preparation for BFS expansion)
   - Selection boost for highlighted nodes

**Impact**: The graph now renders fewer edges but with stronger repulsion and attraction forces. Initial layout takes longer to compute (3000 ticks ~500-1000ms vs 300 ticks ~50-100ms) but is more stable. The reduced edge count may impact discovery of weak connections between artists.

### 9.2 Remaining BFS Features (Not Yet Implemented)

- **BFS neighbor expansion**: When clicking a node, fetch similar artists from the backend and add them to the graph dynamically
- **Caching layer**: Backend cache for expanded neighborhoods (avoid redundant API calls)
- **Progressive UI**: Loading spinner during BFS expansion

---

## 10. Known Limitations

1. **No token refresh**: Spotify sessions expire after 1 hour with no auto-refresh
2. **No offline/PWA support**: Requires network for all API calls and CDN assets
3. **No mobile optimization**: The graph is mouse-oriented (hover, drag); touch support is basic D3 defaults
4. **Fixed viewport**: Window dimensions are cached at page load; no resize handling
5. **Single festival**: Hardcoded to Coachella 2026 (lineup data, playlist naming, etc.)
6. **No user accounts**: All state is session/localStorage; clearing cookies/storage loses everything
7. **Deezer preview expiry**: Preview URLs from Deezer expire, which is why they're fetched live on panel open rather than cached
8. **142-node limit**: The graph is designed for a festival-sized dataset (~100-200 artists). Performance characteristics would change significantly at 1000+ nodes
9. **`build_edges` bug**: The offline edge builder has a typo (`for nodes in nodes`) that prevents re-running the data pipeline
10. **UI freeze on initial load**: 3000 pre-ticking iterations block the main thread for 500-1000ms on graph rebuild

---

## 11. File Inventory

```
artistForceMap/
├── app.py                          # Flask server (265 lines)
├── requirements.txt                # Python deps (unpinned)
├── .env                            # API keys (gitignored)
├── .gitignore
├── CLAUDE.md                       # Dev instructions
├── data/
│   ├── __init__.py
│   ├── coachella_2026.csv          # Source lineup data
│   ├── graph_static.json           # Full precomputed graph (~1-2 MB)
│   ├── graph_slim.json             # Optimized runtime graph
│   ├── graph_builder.py            # Edge construction + scoring
│   └── lineup.py                   # CSV reader
├── spotify/
│   ├── __init__.py
│   ├── auth.py                     # OAuth helpers
│   └── fetch.py                    # Top artists fetcher
├── lastfm/
│   ├── __init__.py
│   └── fetch.py                    # Last.fm API wrapper
├── scripts/
│   ├── __init__.py
│   ├── precompute.py               # 4-pass data pipeline
│   ├── build_slim.py               # Slim graph builder
│   └── sample_tags.py              # Tag sampling utility
├── static/
│   ├── graph.js                    # Frontend app (1560 lines)
│   ├── placeholder_artist.jpeg     # Fallback artist image
│   └── music-player-add-playlist-queue-square-black-icon.svg
└── templates/
    └── index.html                  # SPA shell + CSS (656 lines)
```
