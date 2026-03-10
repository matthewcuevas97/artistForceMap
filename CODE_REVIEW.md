# Code Review: artistForceMap

**Date**: 2026-03-07
**Reviewer**: Claude Opus 4.6
**Commit**: `cdf4bcd` (main)
**Scope**: Full codebase — backend (Python/Flask), frontend (D3.js), data pipeline, configuration

---

## 1. Project Summary

artistForceMap is a single-page web application that visualizes the Coachella 2026 lineup as an interactive force-directed graph. Artists are represented as nodes, connected by similarity edges (derived from Last.fm data) and genre edges. Users can authenticate via Spotify OAuth or Last.fm username to personalize node scores based on their listening history. The app supports audio previews (via Deezer), playlist creation (Spotify), and a "discovery mode" for exploring unfamiliar artists.

**Stack**: Python 3.9 / Flask / Jinja2 / D3.js v7 / Spotipy / Last.fm API / Deezer API

---

## 2. Architecture Overview

```
┌─────────────────┐     ┌────────────────────────┐     ┌──────────────────────┐
│  Browser (D3)   │────▸│  Flask (app.py)         │────▸│  External APIs       │
│  static/graph.js│◂────│  /api/graph             │◂────│  Spotify, Last.fm,   │
│  templates/     │     │  /api/artist/:name       │     │  Deezer              │
│  index.html     │     │  /api/artist/:name/tracks│     └──────────────────────┘
└─────────────────┘     │  /api/spotify/*          │
                        │  /api/lastfm/*           │     ┌──────────────────────┐
                        └────────────────────────┬─┘     │  Pre-built Data      │
                                                 │       │  graph_static.json   │
                                                 └──────▸│  graph_slim.json     │
                                                         └──────────────────────┘
```

**Data pipeline** (offline):
```
coachella_2026.csv → scripts/precompute.py (4 passes) → graph_static.json → scripts/build_slim.py → graph_slim.json
```

**Files by role**:

| File | Lines | Role |
|------|-------|------|
| `app.py` | 265 | Flask server, API routes, auth, Deezer preview refresh |
| `static/graph.js` | 1560 | D3 force graph, all UI logic, discovery mode |
| `templates/index.html` | 656 | HTML shell + all CSS (inline) |
| `data/graph_builder.py` | ~170 | Edge building, scoring, listener normalization |
| `data/lineup.py` | ~35 | CSV reader for Coachella lineup |
| `spotify/auth.py` | ~35 | Spotify OAuth helpers |
| `spotify/fetch.py` | ~30 | Spotify top artists fetcher |
| `lastfm/fetch.py` | ~130 | Last.fm API wrapper (similar artists, info, bio, top tracks, user top artists) |
| `scripts/precompute.py` | 410 | Offline data pipeline (4 passes) |
| `scripts/build_slim.py` | ~75 | Produces optimized graph_slim.json |
| `scripts/sample_tags.py` | ~62 | Tag sampling utility |

---

## 3. Findings

### 3.1 Security Issues

#### CRITICAL: API Secrets Committed to Git

**File**: `.env`
```
SPOTIFY_CLIENT_ID=e36288ab18cf49429e1557dde04554a6
SPOTIFY_CLIENT_SECRET=563acf13011c43cab8d4ce23922d0aa8
LASTFM_API_KEY=4198e5fe296ae874b564b117bdb7b494
```

`.env` is in `.gitignore`, but `.cache` (which appears modified in `git status`) may contain Spotify tokens. The `.gitignore` does not cover `.cache`. These secrets should be rotated if they've ever been pushed to a remote.

**Action**: Add `.cache` to `.gitignore`. Verify no secrets exist in git history. Rotate credentials if exposed.

#### HIGH: Weak Default Flask Secret Key

**File**: `app.py:16`
```python
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
```

The fallback `"dev-secret-change-me"` means sessions are trivially forgeable if the env var is unset. In production, this would allow session hijacking (including Spotify token theft).

**Action**: Remove the fallback or fail hard if the env var is missing in production.

#### MEDIUM: No Spotify Token Refresh

**File**: `app.py:117, 187, 238`

The Spotify `access_token` is stored in the session and used directly. There is no token refresh flow. Spotify access tokens expire after 1 hour. While expired-token errors are caught in `api_graph`, they silently degrade (the session is cleared but the user isn't notified). The `create-playlist` and `callback` routes don't handle refresh at all.

**Action**: Implement token refresh using Spotipy's built-in `SpotifyOAuth.refresh_access_token()`.

#### MEDIUM: XSS via Artist Name in Panel HTML

**File**: `static/graph.js:545`
```javascript
`<div style="...">${d.name}</div>`
```

Artist names from the API are interpolated directly into innerHTML without escaping. If an artist name contained `<script>` or similar, it would execute. While the data source is your own JSON, this is fragile if the data pipeline ever ingests user-supplied data.

**Action**: Use `textContent` or a DOM sanitization helper instead of innerHTML for user-visible strings.

#### LOW: Deezer API Has No Rate Limiting / Retry Logic

**File**: `app.py:27-52`

`refresh_track_previews` makes sequential Deezer API calls for every track of every artist. No rate limiting, no retry on failure. On the `/api/artist/<name>/tracks` endpoint, this runs synchronously and blocks the request.

**Action**: Add request-level caching (e.g., in-memory TTL cache) for Deezer preview lookups to avoid redundant API calls.

---

### 3.2 Bugs

#### BUG: `build_edges` Has a Typo — `node_map` Uses Wrong Variable

**File**: `data/graph_builder.py:52`
```python
node_map = {node["name"]: node for nodes in nodes}
```

This should be `for node in nodes`. As written, `nodes in nodes` iterates over the outer list and shadows the parameter, likely causing a runtime error when `build_edges` is called.

**Severity**: This code path runs only during `build_slim.py` (offline), not at runtime. But it will crash if you try to rebuild the slim graph.

#### BUG: Variable Name Shadowing in `api_spotify_create_playlist`

**File**: `app.py:239, 247`
```python
name = f"Coachella 2026 · {datetime.now().strftime('%b %-d')}"
...
for track in tracks:
    ...
    name = track.get("name", "")  # shadows the playlist name variable
```

The loop variable `name` shadows the playlist name. This doesn't cause a functional bug because `name` isn't used after the loop, but it's confusing and fragile.

#### BUG: `strftime('%b %-d')` Is Not Portable

**File**: `app.py:239`

`%-d` (no-padding day) is a GNU extension. It will fail on Windows with `ValueError`. Use `%d` or `%-d` with a platform check.

---

### 3.3 Performance Issues

#### HIGH: `enrich_with_scores` Is O(n * m * k)

**File**: `data/graph_builder.py:117-139`

The derived-score loop iterates over every top artist (`m`), then every node (`n`), then every similar artist per node (`k`). For 50 top artists, 142 nodes, and ~50 similar artists each, this is ~355,000 iterations per request.

This runs on every `/api/graph` request. While not catastrophic at 142 nodes, it's unnecessary work — the inner loop re-checks `_norm()` on every string comparison instead of pre-normalizing.

**Action**: Pre-normalize node names and similar-artist names once, then do O(1) lookups.

#### MEDIUM: `copy.deepcopy(_slim_nodes)` on Every Request

**File**: `app.py:171`

Deep-copying 142 nodes (each with tags, top_tracks, similar_artists) on every request adds ~1-5ms overhead. The mutation is only `score`, `direct_score`, and `derived_score` — consider copying only the score fields or using a scores-only side dict.

#### MEDIUM: Pre-Ticking 300 Iterations on Graph Rebuild

**File**: `static/graph.js:773`
```javascript
for (let i = 0; i < 300; ++i) simulation.tick();
```

This blocks the main thread for ~200-400ms on initial load and every threshold change. Users will experience a brief freeze.

**Action**: Consider running the simulation in a Web Worker, or at minimum reduce to 150 ticks and let it settle live.

#### LOW: Viewport Dimensions Cached Once

**File**: `static/graph.js:65-66`
```javascript
const W = window.innerWidth;
const H = window.innerHeight;
```

`W` and `H` are set once at page load. The graph won't handle window resize or orientation change. Tooltip positioning and zoom calculations will be wrong after resize.

---

### 3.4 Code Quality

#### graph.js Is Too Large and Monolithic

At 1560 lines in a single file, `graph.js` handles:
- D3 graph rendering and simulation
- Discovery mode state machine
- Audio playback
- Playlist management
- Export panel DOM generation
- Auth UI management
- Tooltip management
- Zoom/pan behavior

This makes the code hard to navigate and modify. The state is managed through 20+ module-level `let` variables with complex interdependencies.

**Action**: Consider splitting into modules (e.g., `discovery.js`, `playlist.js`, `panel.js`, `controls.js`).

#### HTML is Generated via String Concatenation

**File**: `static/graph.js` (throughout)

Complex HTML is built via template literal concatenation (e.g., `renderTrackList`, `renderExportPanel`, `openPanel`). This is error-prone, hard to maintain, and creates XSS risk.

#### Inline Styles in HTML Template

**File**: `templates/index.html:1-532`

All CSS is inline in the HTML template (532 lines of `<style>`). No external stylesheet. This prevents caching CSS separately and makes the initial HTML payload large.

#### No Error Display for API Failures

When `/api/graph` fails, the error is logged to console (`console.error` in `fetchAndBuild`), but the user sees nothing — just a blank screen. There's no loading indicator or error state.

#### Inconsistent Import Patterns

**File**: `app.py:134`
```python
from lastfm.fetch import get_top_artists as lastfm_top  # lazy import inside route
```

Last.fm's `get_top_artists` is lazily imported inside two different route handlers. Spotify imports are at the top of the file. This inconsistency suggests the Last.fm integration was added incrementally.

---

### 3.5 Data Pipeline

#### Precompute Script Has No Idempotency Guards

**File**: `scripts/precompute.py`

Running `main()` overwrites `graph_static.json` in-place. If a pass fails midway (e.g., API rate limit), partial data is written and there's no way to resume from where it left off.

**Action**: Write to a temp file and atomically replace on success. Consider checkpointing between passes.

#### build_slim.py References Broken `build_edges`

As noted in the bug section, `data/graph_builder.py:build_edges` has a typo that would crash. This means `build_slim.py` currently cannot be re-run successfully.

#### No CSV File in Repository

`data/coachella_2026.csv` is referenced by `data/lineup.py` but isn't visible in the repo. If it's not committed, the precompute pipeline can't be reproduced from a fresh clone.

---

### 3.6 Testing

**There are no tests.** No unit tests, no integration tests, no test runner configured. Key testable units include:
- `enrich_with_scores` logic
- `build_edges` / `build_genre_edges` graph construction
- `normalize_listeners` normalization
- `_norm_simple` / `_norm` name matching
- OAuth flow (mock-based)
- Discovery mode state transitions (JS)

---

### 3.7 Dependency Management

**File**: `requirements.txt`
```
flask
spotipy
python-dotenv
requests
```

Dependencies are unpinned. This means builds are not reproducible — a future `pip install` could pull breaking changes. The `requests` library is also a transitive dependency of `spotipy`, so listing it explicitly is fine for clarity but the version should be pinned.

**Action**: Generate `requirements.txt` with pinned versions (`pip freeze > requirements.txt` or use `pip-tools`).

---

## 4. Strengths

- **Clean data pipeline separation**: The offline precompute/build_slim pipeline is well-separated from the runtime server. The slim JSON approach is a smart optimization.
- **Thoughtful D3 visualization**: Pre-ticking 300 iterations, top-8 edge filtering per node, subgraph overlay, ambassador nodes — these show careful thought about graph readability.
- **Dual auth strategy**: Supporting both Spotify OAuth (rich but requires app registration) and Last.fm username (zero-friction) is excellent UX.
- **Discovery mode**: A well-designed progressive exploration mechanic that adds genuine value beyond a static graph.
- **Minimal dependencies**: The Python backend is lean (4 deps). No ORM, no complex framework, no unnecessary abstraction layers.
- **Score enrichment design**: The direct-score + derived-score system (using similar-artist match weights) is a clever way to map user affinity onto the festival graph.

---

## 5. Priority Summary

| Priority | Issue | Location |
|----------|-------|----------|
| CRITICAL | API secrets may be in git history | `.env`, `.cache` |
| CRITICAL | `build_edges` typo crashes offline pipeline | `data/graph_builder.py:52` |
| HIGH | No token refresh for Spotify | `app.py` |
| HIGH | Weak default Flask secret key | `app.py:16` |
| HIGH | No tests | project-wide |
| MEDIUM | XSS via innerHTML with artist names | `static/graph.js` |
| MEDIUM | `enrich_with_scores` O(n*m*k) per request | `data/graph_builder.py` |
| MEDIUM | Deep copy overhead per request | `app.py:171` |
| MEDIUM | No error UI for failed graph loads | `static/graph.js` |
| MEDIUM | Unpinned dependencies | `requirements.txt` |
| LOW | No window resize handling | `static/graph.js:65-66` |
| LOW | No rate limiting on Deezer calls | `app.py:27-52` |
| LOW | Monolithic 1560-line JS file | `static/graph.js` |
| LOW | All CSS inline in HTML | `templates/index.html` |
