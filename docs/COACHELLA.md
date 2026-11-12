# Coachella 2026 map (`app.py`)

The 142 acts of the Coachella 2026 lineup as a force-directed graph. Edges connect similar
artists. Anonymous visitors see node size and colour by popularity and genre. When a visitor logs
in with Spotify or Last.fm, the graph is re-scored from their listening.

## Architecture

```
coachella_2026.csv ──▶ scripts/precompute.py ──▶ data/graph_static.json ◀── scripts/migrate_similar.py
                       (offline, Last.fm API)     (nodes + links)           scripts/trim_bios.py
                                                         │                   scripts/enrich_graph.py
                                                         ▼
                Spotify / Last.fm top artists ──▶ app.py  /api/graph  (scored per request)
                                                         │
                                templates/index.html + static/js/*.js (D3 v7, ES modules)
```

The graph is precomputed. At request time, the only external calls are the user's top artists
(cached for 10 minutes per user) and Deezer preview lookups when a panel opens.

## Offline data pipeline (`scripts/`)

| Script | Purpose | Network |
|---|---|---|
| `precompute.py` | Builds nodes from `data/coachella_2026.csv` (`name, day, weekend, stage, lastfm_artists`; `\|`-separated members for B2B acts), then fetches listeners, top tags and similar artists from Last.fm and generates edges. **Warning:** it does not run the enrichment pass, so rerunning it drops images, bios and top tracks (BUG-34). | Last.fm, cached in `data/lastfm_api_cache.json` |
| `enrich_graph.py` | Adds images and bios from Last.fm, plus top tracks and fallback images from Deezer, to `graph_static.json`. | Last.fm, Deezer |
| `migrate_similar.py` | Writes `similar_artists` into `graph_static.json` from the Last.fm cache. B2B nodes take the max `match` across members. | none |
| `trim_bios.py` | Trims bios that were hard-cut at 300 characters back to a sentence or word boundary. | none |
| `bfs_similarity.py` | Experimental best-first search over Last.fm similarity, used to connect isolated acts. It writes `data/bfs_frontier.json` and `data/similarity_cache.json`. The apps don't use it. | Last.fm |

Tests fail if `graph_static.json` needs `migrate_similar.py` or `trim_bios.py`.

### Edge generation (5 passes, degree cap 6)

1. **Gold standard:** Last.fm lists one act as similar to the other.
2. **Base RBO:** the Rank-Biased Overlap of the two acts' top-10 tags is at least 0.21.
3. **Conditional rewiring:** an act left orphaned because its partner was full connects to that partner's neighbour.
4. **Adaptive floor:** each remaining isolated act connects to its best RBO partner, if that score is at least 0.05.
5. **Hail Mary:** each act that is still isolated connects to the most popular act of the same genre.

`/api/graph` serves the edges in `edges_by_level`. The threshold slider maps 0.30 to all passes,
0.32 to passes 1–4, 0.34 to passes 1–3, 0.36 to passes 1–2, and 0.38 or 0.40 to pass 1 only.

## Scoring (`data/graph_builder.py`)

Each node's `score` (0–1) drives its radius, colour saturation and label visibility:

* **Baseline:** `sqrt(listeners / max_listeners)`.
* **Direct match:** the user listens to the act, matching either its display name or any
  `lastfm_artists` member, after name normalisation. The score is the best rank score, where rank
  *i* of *n* top artists scores `1 − i/n`, so it is never 0.
* **Derived match:** for acts with no direct match, a top artist who isn't on the lineup but
  appears in the act's `similar_artists` gives `rank_score × match × 0.6`. The best one wins.
* `user_seeds` lists every act with a direct or derived score. Discovery mode starts from them.

## HTTP API

| Route | Notes |
|---|---|
| `GET /` | Single-page shell |
| `GET /api/graph` | `{nodes, edges_by_level, user_seeds}`, scored for the session's user |
| `GET /api/artist?name=` | One node without internal fields. The name goes in the query string because names can contain `/` (e.g. "Model/Actriz"). |
| `GET /api/artist/tracks?name=` | Top tracks with fresh Deezer preview URLs, resolved at request time |
| `POST /api/spotify/create-playlist` | `{tracks:[{artist,name}]}` → a private playlist in the user's account |
| `/login`, `/callback`, `/api/spotify/logout`, `/api/lastfm/login`, `/api/lastfm/logout` | Shared auth (`web_auth.py`): Spotify OAuth with single-use CSRF `state`, tokens kept in the user's own session |

## Frontend (`static/js/`)

`main.js` wires the modules together.

| Module | What it handles |
|---|---|
| `simulation.js` | D3 scaffold, force layout, hover, neighbourhood highlight, zoom-to-fit, resize |
| `panel.js` | Desktop artist panel (stale-response safe) |
| `drawer.js` | Mobile bottom drawer |
| `controls.js` | Login, day filter, threshold, node size, discovery toggle |
| `discovery.js` | Discovery mode, which reveals the graph outward from your matched acts |
| `playlist.js` | Playlist and export (Spotify playlist, or streaming-service links) |
| `state.js` | Shared state |
| `utils.js` | `escapeHtml`, radius and colour functions |

How it behaves:
* **First load:** the layout pre-settles in about 300 ticks (until alpha drops below alphaMin), so
  the main thread blocks for about 110 ms. Then the view fits all nodes on screen.
* **Threshold slider:** it swaps the link force's edges on the running simulation. Positions, pin
  and highlight are kept.
* **Phones:** the controls start minimised, and the layout stretches to match the screen's
  orientation.
* **Escaping:** all API strings are escaped before they reach `innerHTML`.

## Known limitations

* Rerunning `precompute.py` wipes the enrichment fields (BUG-34). Run `enrich_graph.py`, then
  `migrate_similar.py` and `trim_bios.py`, afterwards.
* Spotify tokens live in the signed (not encrypted) session cookie. Moving them server-side is the
  remaining part of SEC-01.
* Deezer previews come from a public search, so a wrong match is possible for very generic track
  names.
