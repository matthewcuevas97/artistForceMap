# Universal Map Prototype - Backend Pipeline

This backend pipeline creates user-specific artist maps by orchestrating a series of data ingestion, enrichment, and selection steps.

## Data Flow

```
User Login (Spotify/Last.fm)
    ↓
Ingest Top 25 Artists
    ↓
Tag Enrichment (Last.fm API)
    ↓
Seed Artist Selection (MMR Algorithm)
    ↓
Graph Initialization (Deezer + Last.fm)
    ↓
user_db.json + user_map.json
```

## Architecture

### Modular Components

- **`user_data.py`**: Local JSON persistence layer
  - Load/save `user_db.json` (enriched artist data)
  - Load/save `user_map.json` (graph structure)

- **`user_ingestion.py`**: Fetch user's top artists
  - Spotify OAuth stub
  - Last.fm username login
  - Fetch top 25 artists

- **`tag_enrichment.py`**: Enrich artists with Last.fm data
  - `artist.getInfo` → listeners, image, bio
  - `artist.getTopTags` → genre/style tags
  - Save to `all_artists` in user_db

- **`seed_selection.py`**: Select 5 diverse seed artists
  - **Algorithm**: Maximal Marginal Relevance (MMR)
  - Auto-select #1 ranked artist
  - Greedy selection: maximize rank × minimize tag overlap
  - Jaccard similarity for tag-based diversity

- **`graph_init.py`**: Build initial graph with seed artists
  - Fetch `similar_artists` from Last.fm
  - Fetch top tracks from Deezer
  - Gold Standard edges (direct similar artist overlap)
  - RBO edges (tag similarity ≥ 0.21)
  - Save to `user_map.json`

- **`pipeline.py`**: Orchestrator
  - `run_full_pipeline()`: Execute all steps sequentially
  - `run_pipeline_step()`: Run individual step (for debugging)

- **`api_routes.py`**: Flask endpoints
  - Auth: `/api/proto/auth/spotify`, `/api/proto/auth/lastfm`
  - Pipeline: `/api/proto/pipeline/run`, `/api/proto/pipeline/step/<step>`
  - Data: `/api/proto/user/<user_id>/db`, `/api/proto/user/<user_id>/map`

## Configuration

### Environment Variables

```bash
# Spotify OAuth
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REDIRECT_URI=http://localhost:8080/api/proto/auth/spotify/callback

# Last.fm API
LASTFM_API_KEY=your_api_key
```

## Usage

### Running the Full Pipeline (Python)

```python
from backend.pipeline import run_full_pipeline

auth_data = {
    "provider": "spotify",
    "id": "user_123",
    "name": "John Doe",
    "token": "spotify_access_token",
}

result = run_full_pipeline(auth_data)
# Outputs:
# - data/users/user_123_db.json (enriched artists)
# - data/users/user_123_map.json (graph structure)
```

### Via Flask API

```bash
# 1. Initiate Spotify login
curl -X POST http://localhost:8080/api/proto/auth/spotify

# 2. User visits returned auth_url, gets redirected to callback
# (automatically starts ingestion)

# 3. Check status
curl http://localhost:8080/api/proto/user/user_123/status

# 4. Get the graph map
curl http://localhost:8080/api/proto/user/user_123/map
```

## Data Structures

### user_db.json
```json
{
  "user_id": "user_123",
  "auth_provider": "spotify",
  "top_artists": [
    {
      "name": "Artist Name",
      "rank": 1,
      "spotify_id": "...",
      "genres": ["electronic", "house"],
      "popularity": 85
    }
  ],
  "all_artists": {
    "Artist Name": {
      "name": "Artist Name",
      "rank": 1,
      "listeners": 5000000,
      "tags": ["electronic", "house", "techno"],
      "image_url": "https://...",
      "bio": "...",
      "all_artists_metadata": {
        "Artist Name": {
          "name": "Artist Name",
          "similar_artists": [
            {"name": "Similar Artist", "match": 0.85}
          ],
          "top_tracks": [
            {
              "name": "Track Name",
              "preview_url": "https://...",
              "album_art": "https://..."
            }
          ]
        }
      }
    }
  },
  "seed_artists": ["Artist 1", "Artist 2", "Artist 3", "Artist 4", "Artist 5"],
  "seed_selection_log": [
    {
      "artist": "Artist 1",
      "reason": "auto-selected (rank #1)",
      "score": 1.0
    }
  ]
}
```

### user_map.json
```json
{
  "user_id": "user_123",
  "nodes": [
    {
      "name": "Artist Name",
      "rank": 1,
      "listeners": 5000000,
      "tags": ["electronic", "house"],
      "image_url": "https://...",
      "bio": "...",
      "similar_artists": [...],
      "top_tracks": [...]
    }
  ],
  "edges": [
    {
      "source": "Artist 1",
      "target": "Artist 2",
      "type": "similar",
      "pass": 1,
      "weight": 1.0
    }
  ]
}
```

## Customization

### Changing the Number of Seed Artists

```python
select_seed_artists(user_id, num_seeds=7, lambda_param=0.7)
```

### Adjusting Rank vs. Diversity Trade-off

```python
# lambda_param: 0.0-1.0
# Higher = prioritize user's top artists (rank affinity)
# Lower = prioritize genre diversity

select_seed_artists(user_id, num_seeds=5, lambda_param=0.5)  # More diverse
select_seed_artists(user_id, num_seeds=5, lambda_param=0.9)  # More top-heavy
```

### Swapping APIs

Each step uses pluggable functions:

```python
# In tag_enrichment.py:
def enrich_artist_with_lastfm(artist_name):
    # Replace this with your own API call
    pass

# In graph_init.py:
def fetch_deezer_artist_info(artist_name):
    # Replace this with your own API call
    pass
```

## Error Handling

Each step gracefully handles API failures:
- Missing data → filled with defaults (empty arrays, None, 0)
- API timeouts → logged, but pipeline continues
- Rate limits → built-in `time.sleep()` delays

## Next Steps

- [ ] Implement graph expansion (fringe artists)
- [ ] Add discovery mode mechanics
- [ ] Build frontend visualization
- [ ] Add playlist creation
- [ ] Implement real database (PostgreSQL/MongoDB)
