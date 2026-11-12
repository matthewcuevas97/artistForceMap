# Universal map (`app_universal.py`)

A personal artist map. The pipeline picks 5 diverse seed artists from your top 25 and adds their
strongest Last.fm similar artists. You grow it one artist at a time with **Expand**. Spotify and
Last.fm users get the same features.

## Generating a map: `POST /api/map/init/stream` (Server-Sent Events)

`backend/pipeline.run_full_pipeline(auth)` runs in a background thread:

1. **Ingestion** (`user_ingestion.py`) fetches the top 25 artists from Spotify or Last.fm and
   stores them, with rank scores, in the per-user cache.
2. **Tag enrichment** (`tag_enrichment.py`) fetches Last.fm tags, listeners, image and bio for
   each artist, through a global 90-day cache. A transient Last.fm failure (network or rate limit)
   is never cached; that artist just gets minimal data for this run.
3. **Seed selection** (`seed_selection.py`): greedy Maximal Marginal Relevance. The #1 artist is
   always included. Each next pick maximises `0.7 × rank_score + 0.3 × mean tag distance`
   (Jaccard) to the seeds chosen so far.
4. **Graph init** (`graph_init.py`) fetches similar artists and Deezer info for each seed, then
   builds edges:
   * **seed–seed:** pass 1 when one seed lists the other as similar; otherwise pass 2 when the
     *extrapolated* RBO of their tags is at least 0.32 (identical tag lists score 1.0 at any
     length; empty lists score 0).
   * **first ring:** each seed's 4 strongest similar artists become lightweight nodes, linked to
     every seed that lists them. That makes about 25 nodes.

Progress goes through `backend.progress.report()`. The SSE thread installs a context-local sink,
so each stream carries only its own run's messages. Without a sink, `report()` prints.

Events are `data: {"message": ...}` for progress, then either `{"complete": true, nodes, edges}`
or `{"error": ...}`. While the pipeline runs, the stream sends a `: keepalive` comment every 15 s;
there is no overall timeout.

## Nodes

Seed nodes carry full metadata and `seed: true`. First-ring and expanded nodes are **stubs**:
`seed: false, details_loaded: false, parent`, plus a `genre` inherited from the parent. The first
click calls `GET /api/artist?name=`, which loads tags, listeners, bio, image and top tracks from
the caches (or Last.fm + Deezer), returns them, and saves them into the map.

## Other endpoints

| Route | Notes |
|---|---|
| `GET /api/map/get` | The saved map. The frontend renders it on load. |
| `POST /api/map/expand {artist}` | Adds up to 6 new Last.fm similar artists and links already-present ones. Runs under the map's file lock. Returns the full map plus `added_nodes` and `added_edges`. A second call is a no-op ("Already expanded"). A Last.fm outage returns 502 and leaves the map unchanged. |
| `GET /api/artist?name=` | Details for a node (see above) |
| `GET /api/preview?deezer_id=` (or `artist=&title=`) | A fresh Deezer preview URL. Signed preview URLs expire after about 15 minutes, so they are **never cached** with artist data; only track ids are cached, and resolved URLs are kept in memory for 10 minutes. |
| `POST /api/map/init` | Non-streaming version of the generator (legacy) |
| `GET /api/health` | Liveness check |
| auth routes | Shared with the Coachella app (`web_auth.py`) |

All map endpoints require a login (401 otherwise). The user id is the Spotify id or the Last.fm
username.

## Storage (`backend/cache.py`, `backend/user_data.py`, `backend/storage.py`)

| File | Contents | TTL |
|---|---|---|
| `data/cache/artists.json` | Last.fm enrichment per artist | 90 days |
| `data/cache/similar_artists.json` | Last.fm similar artists | 90 days |
| `data/cache/deezer.json` | Deezer image, fans, top tracks (ids, no previews) | 90 days |
| `data/cache/<user>_cache.json` | Top artists (Spotify, Last.fm, merged; Last.fm wins), seeds | — |
| `data/users/<user>_db.json` | Enriched top artists | — |
| `data/users/<user>_map.json` | The map (`nodes`, `edges`) | — |

* User ids outside `[A-Za-z0-9._-]` (or starting with `.`, or longer than 64 characters) are hashed
  into file names.
* Writes go to a temp file followed by `os.replace` (atomic), under one re-entrant lock per file
  held across load → modify → save.
* The locks are in-process, so run **one worker process** (threads are fine). Multiple processes
  would need SQLite or Redis.
* `data/users/` and `data/cache/*_cache.json` hold personal listening data. They are gitignored.

## Frontend (`static/js/universal_map.js`)

* **Loading and generating:** on load, the saved map is fetched and rendered, and the button reads
  REGENERATE MY MAP.
* **Expanding:** new nodes merge into the running simulation near their parent. Existing nodes keep
  their positions.
* **Node style:** radius is `scaleSqrt(listeners)` across the map (5–18 px, scaled by the node-size
  slider). Seeds get a white ring, and colour comes from the genre.
* **Panel:** every string is escaped, and images must be absolute http(s) URLs. PLAY resolves a
  preview first. A missing or dead preview (`audio.play()` rejects) turns the button to N/A.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| "No enriched artists found" | Last.fm returned nothing for every top artist (rate limit or outage). Check `LASTFM_API_KEY` and retry; failures aren't cached. |
| "Couldn't load details" / Expand fails with 502 | A Last.fm outage. Nothing was saved, so retry. |
| Preview shows N/A | Deezer has no preview for that track, or the search couldn't match it. |
| Spotify login loops back with "Login expired" | The OAuth `state` didn't match. Start the login again from the site, in the same browser. |
| Spotify login works only for you | Spotify apps in development mode only accept users you add in the dashboard. |

To start over for one user, delete `data/users/<user>_*.json` and `data/cache/<user>_cache.json`.
The global artist caches can stay.
