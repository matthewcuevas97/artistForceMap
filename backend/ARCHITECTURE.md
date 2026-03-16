# Universal Map Backend - Architecture

## High-Level Overview

This backend implements a **user-specific, on-demand graph generation pipeline**. Instead of serving a precomputed static graph to all users, we build personalized maps dynamically based on each user's listening history.

```
┌─────────────────────────────────────────────────────────────────┐
│                    UNIVERSAL MAP PIPELINE                        │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────────┐
│   User Ingestion     │  ← OAuth (Spotify) / Username (Last.fm)
│  (Fetch Top 25)      │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Tag Enrichment      │  ← Last.fm: artist.getInfo, artist.getTopTags
│  (Last.fm API)       │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Seed Selection      │  ← Greedy MMR: rank × (1 - tag_overlap)
│  (5 Diverse Artists) │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Graph Initialization │  ← Last.fm: similar_artists, Deezer: tracks
│ (Build Graph)        │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│   user_db.json       │  ← All enriched artist data
│   user_map.json      │  ← Graph structure for frontend
└──────────────────────┘
```

## Component Details

### 1. User Ingestion Layer

**Files**: `user_ingestion.py`, `api_routes.py`

**Responsibility**: Authenticate user and fetch their top artists.

**Providers**:
- **Spotify**: OAuth 2.0 flow
  - Scopes: `user-top-read`
  - Returns: 25 top artists with genres, popularity, images
- **Last.fm**: Username-based (no OAuth)
  - Returns: 25 top artists with URLs

**Key Functions**:
- `login_spotify(auth_code)` → auth_data
- `login_lastfm(username)` → auth_data
- `fetch_top_25_artists_spotify(token)` → List[artist]
- `fetch_top_25_artists_lastfm(username)` → List[artist]
- `ingest_user(auth_data)` → ingestion_result

**Output**: `top_artists` array in `user_db.json`

---

### 2. Tag Enrichment Layer

**Files**: `tag_enrichment.py`

**Responsibility**: Fetch detailed artist data from Last.fm for all 25 artists.

**Data Fetched**:
- `artist.getInfo`: listeners count, images, bio
- `artist.getTopTags`: genre/style tags (up to 10 per artist)

**Key Functions**:
- `enrich_artist_with_lastfm(artist_name)` → enriched_data
- `enrich_top_25_artists(user_id)` → result

**Output**: `all_artists` object in `user_db.json`

```json
{
  "all_artists": {
    "Artist Name": {
      "name": "Artist Name",
      "listeners": 5000000,
      "tags": ["electronic", "house", "techno"],
      "image_url": "https://...",
      "bio": "..."
    }
  }
}
```

---

### 3. Seed Selection Layer

**Files**: `seed_selection.py`

**Responsibility**: Select exactly 5 seed artists that maximize user affinity while ensuring genre diversity.

**Algorithm**: Maximal Marginal Relevance (MMR)

```
Step 1: Auto-select artist with rank=1

Step 2-5: For each remaining slot:
  For each candidate artist not yet selected:
    score = λ * rank_score - (1-λ) * avg_tag_similarity
    where:
      rank_score = (26 - rank) / 25      [0 to 1, higher is user's favorite]
      tag_similarity = avg Jaccard(candidate.tags, selected.tags)
      λ = 0.7 [default: 70% rank, 30% diversity]

  Pick the candidate with highest score
```

**Key Functions**:
- `jaccard_similarity(tags_a, tags_b)` → float
- `tag_distance(tags_a, tags_b)` → float [1 - similarity]
- `calculate_diversity_score(...)` → float
- `select_seed_artists(user_id, num_seeds=5, lambda_param=0.7)` → result

**Output**: `seed_artists` list in `user_db.json`

**Parameters**:
- `lambda_param`: 0.0 (maximize diversity) to 1.0 (maximize rank)
- `num_seeds`: 3-10 artists (default 5)

---

### 4. Graph Initialization Layer

**Files**: `graph_init.py`

**Responsibility**: Fetch complete metadata for seed artists and build the initial graph structure.

**Data Fetched**:
- **Last.fm**: `artist.getSimilar` → list of similar artists
- **Deezer**: Artist search → image, top tracks (10 per artist)

**Edge Construction**:
1. **Gold Standard** (pass=1): Direct similarity overlap
   - Artist A's similar artists includes Artist B (and vice versa)
   - Weight: 1.0

2. **RBO-based** (pass=2): Tag similarity
   - RBO(A.tags, B.tags) ≥ 0.21 (RBO_BASE_THRESHOLD)
   - Weight: RBO score

**Key Functions**:
- `fetch_deezer_artist_info(artist_name)` → dict
- `fetch_seed_artist_metadata(artist_name, lastfm_data)` → dict
- `rbo_similarity(list1, list2, p=0.9)` → float
- `build_seed_graph(...)` → graph
- `initialize_user_graph(user_id)` → result

**Output**: `user_map.json` with nodes and edges

```json
{
  "nodes": [
    {
      "name": "Artist",
      "rank": 1,
      "listeners": 5000000,
      "tags": [...],
      "image_url": "...",
      "bio": "...",
      "similar_artists": [...],
      "top_tracks": [...]
    }
  ],
  "edges": [
    {
      "source": "Artist A",
      "target": "Artist B",
      "type": "similar",
      "pass": 1,
      "weight": 1.0
    }
  ]
}
```

---

### 5. Data Persistence Layer

**Files**: `user_data.py`

**Responsibility**: Simple JSON-based storage for user data.

**Files on Disk**:
- `data/users/{user_id}_db.json` - Enriched artist data
- `data/users/{user_id}_map.json` - Graph structure

**Key Functions**:
- `load_user_db(user_id)` → dict
- `save_user_db(user_id, data)` → None
- `load_user_map(user_id)` → dict
- `save_user_map(user_id, data)` → None
- `get_or_create_user(user_id, auth_data)` → dict
- `update_user_db(user_id, updates)` → dict

---

### 6. Pipeline Orchestrator

**Files**: `pipeline.py`

**Responsibility**: Chain all components together and provide easy entry points.

**Key Functions**:
- `run_full_pipeline(auth_data)` - Execute all steps sequentially
- `run_pipeline_step(user_id, step, **kwargs)` - Run a single step

**Output**: Comprehensive result object with all outputs

```python
{
  "user_id": "...",
  "provider": "spotify" or "lastfm",
  "ingestion": {...},
  "enrichment": {...},
  "seed_selection": {...},
  "graph_init": {...}
}
```

---

## API Layer

**Files**: `api_routes.py`

**Framework**: Flask Blueprint (`/api/proto`)

**Endpoints**:

| Route | Method | Purpose |
|-------|--------|---------|
| `/auth/spotify` | POST | Start OAuth flow |
| `/auth/spotify/callback` | GET | OAuth callback |
| `/auth/lastfm` | POST | Last.fm login |
| `/pipeline/run` | POST | Execute full pipeline |
| `/pipeline/step/<step>` | POST | Run single step |
| `/user/<id>/db` | GET | Get user database |
| `/user/<id>/map` | GET | Get user's graph |
| `/user/<id>/status` | GET | Check pipeline progress |
| `/health` | GET | Health check |

---

## Design Decisions

### 1. Modular Architecture
Each step is independent and can be:
- Run in isolation
- Re-run with different parameters
- Swapped with alternative implementations
- Tested independently

### 2. Greedy Selection Algorithm
Why MMR instead of exhaustive search?
- ✅ Deterministic (no randomness)
- ✅ Fast (O(n²) per step, n=25)
- ✅ Interpretable (see selection log)
- ✅ Tunable (lambda_param controls trade-off)

### 3. JSON Persistence
Why not a real database yet?
- ✅ No setup required
- ✅ Easy to inspect/debug
- ✅ Works for prototyping
- ⚠️ Not suitable for millions of users

Migration plan: Wrapper functions in `user_data.py` make it trivial to swap in SQLAlchemy/MongoDB later.

### 4. Graceful API Failures
Missing data doesn't break the pipeline:
- `enrichment`: Failed tags → empty array
- `graph_init`: Missing Deezer data → use Last.fm fallback
- Minimal rate limiting (0.2s delays) prevents hitting API limits

### 5. Tag-Based Diversity
Why not just shuffle genres?
- Jaccard similarity captures nuance
- Tags can combine (e.g., "deep house" + "techno")
- RBO edge logic already uses tags
- Consistent with graph-building phase

---

## Data Flow Example

User: "spotify_user_123"

**Ingestion** (5 sec):
```
Spotify API → {top 25 artists with rank, genre, popularity}
             → user_db.json: top_artists
```

**Enrichment** (30 sec):
```
For each of 25 artists:
  Last.fm API → {listeners, image, bio, top 10 tags}
               → user_db.json: all_artists
```

**Seed Selection** (immediate):
```
Algorithm runs on local data (no API calls):
  1. Auto-select #1
  2. Greedy: pick highest MMR score 4 more times
           → user_db.json: seed_artists + selection_log
```

**Graph Init** (45 sec):
```
For each of 5 seed artists:
  Last.fm API → similar_artists (20 per artist)
  Deezer API → top tracks (10 per artist), images
             → user_db.json: all_artists_metadata
             → user_map.json: nodes + edges
```

**Total Time**: ~2 minutes (including API rate limits)

---

## Extensibility

### Adding a New Streaming Provider

```python
# In user_ingestion.py:
def fetch_top_25_artists_new_provider(token):
    # Implement API call
    return [{"name": "...", "rank": 1, ...}, ...]

# In pipeline.py:
if provider == "new_provider":
    top_artists = fetch_top_25_artists_new_provider(token)
```

### Swapping Out Last.fm

```python
# In tag_enrichment.py:
def enrich_artist_with_new_api(artist_name):
    return {
        "name": artist_name,
        "listeners": ...,
        "tags": [...],
        "image_url": "...",
        "bio": "..."
    }
```

### Changing Edge Logic

```python
# In graph_init.py:
def build_seed_graph(...):
    # Replace RBO logic with your own similarity metric
    # Same node/edge structure on output
```

---

## Performance Characteristics

| Phase | Time | API Calls | Notes |
|-------|------|-----------|-------|
| Ingestion | 1-3 sec | 1 | Single auth endpoint |
| Enrichment | 25-30 sec | 50 | 2 per artist (info + tags) |
| Seed Selection | <1 sec | 0 | Local computation |
| Graph Init | 30-45 sec | 75+ | 3-4 per seed artist |
| **Total** | **2-3 min** | **126+** | With 0.2s rate limiting |

---

## Future Enhancements

### Phase 2: Graph Expansion
- Fetch "fringe" artists from seed artists' similar lists
- Implement edge trimming (spanning tree + top K)
- Add graph traversal for discovery

### Phase 3: Real Database
- Migrate from JSON to PostgreSQL/MongoDB
- Add user authentication (real OAuth)
- Implement caching layer (Redis)

### Phase 4: Advanced Features
- User preference tuning (adjust lambda, num_seeds)
- Collaborative filtering (artists liked by similar users)
- Playlist generation
- Real-time graph updates
