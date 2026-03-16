# Universal Map Backend - Quick Start Guide

## Installation

```bash
# Install dependencies
pip install flask spotipy requests

# Set environment variables
export LASTFM_API_KEY=your_key
export SPOTIFY_CLIENT_ID=your_id
export SPOTIFY_CLIENT_SECRET=your_secret
```

## Quick Start

### Option 1: Run Full Pipeline (Direct Python)

```python
from backend.pipeline import run_full_pipeline

result = run_full_pipeline({
    "provider": "lastfm",
    "id": "your_username",
    "name": "Your Name",
})

# Outputs:
# data/users/your_username_db.json
# data/users/your_username_map.json
```

### Option 2: Use Flask API

```bash
# Start the app
python app.py

# Login with Spotify
POST http://localhost:8080/api/proto/auth/spotify

# Or login with Last.fm
POST http://localhost:8080/api/proto/auth/lastfm
Body: {"username": "lastfm_username"}

# Run pipeline
POST http://localhost:8080/api/proto/pipeline/run

# Get results
GET http://localhost:8080/api/proto/user/user_id/map
```

### Option 3: Run Individual Steps

```python
from backend.user_ingestion import ingest_user
from backend.tag_enrichment import enrich_top_25_artists
from backend.seed_selection import select_seed_artists
from backend.graph_init import initialize_user_graph

user_id = "my_user"

# Step by step
ingest_user({"provider": "lastfm", "id": user_id})
enrich_top_25_artists(user_id)
select_seed_artists(user_id, num_seeds=5, lambda_param=0.7)
initialize_user_graph(user_id)
```

## Data Output

After running the pipeline, you'll have:

### `data/users/user_id_db.json`
Enriched artist data:
- `top_artists`: User's top 25 artists from streaming
- `all_artists`: Full enrichment with tags, listeners, images
- `seed_artists`: Selected 5 diverse artists
- `all_artists_metadata`: Complete metadata for seed artists

### `data/users/user_id_map.json`
Graph structure for frontend:
- `nodes`: 5 seed artists with full metadata
- `edges`: Connections between seed artists (Gold Standard + RBO)

## Key Parameters

### Seed Selection Trade-off

```python
# lambda_param: 0.0 ← → 1.0
#            [diversity]  [rank]

select_seed_artists(user_id, lambda_param=0.3)   # Very diverse
select_seed_artists(user_id, lambda_param=0.7)   # Balanced (default)
select_seed_artists(user_id, lambda_param=0.95)  # User's favorites
```

### Number of Seeds

```python
select_seed_artists(user_id, num_seeds=3)   # Minimal graph
select_seed_artists(user_id, num_seeds=5)   # Standard (default)
select_seed_artists(user_id, num_seeds=10)  # Larger graph
```

## Debugging

### Re-run a single step:
```python
from backend.pipeline import run_pipeline_step

# Re-enrich with different parameters
run_pipeline_step(user_id, "seed_selection", lambda_param=0.5)

# Re-initialize graph
run_pipeline_step(user_id, "graph_init")
```

### Inspect user data:
```bash
# View enriched artist data
cat data/users/user_id_db.json | jq .all_artists

# View selected seed artists
cat data/users/user_id_db.json | jq .seed_artists

# View graph structure
cat data/users/user_id_map.json | jq .nodes
```

## API Endpoints Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/proto/auth/spotify` | Initiate Spotify login |
| GET | `/api/proto/auth/spotify/callback` | Spotify OAuth callback |
| POST | `/api/proto/auth/lastfm` | Last.fm login (username) |
| POST | `/api/proto/pipeline/run` | Run full pipeline |
| POST | `/api/proto/pipeline/step/<step>` | Run individual step |
| GET | `/api/proto/user/<id>/db` | Get user database |
| GET | `/api/proto/user/<id>/map` | Get user's graph map |
| GET | `/api/proto/user/<id>/status` | Get pipeline status |
| GET | `/api/proto/health` | Health check |

## Next Steps

1. **Test the pipeline** with a sample user
2. **Connect to frontend** by serving `user_map.json` as the initial graph
3. **Add graph expansion** (grow the map from the 5 seed artists)
4. **Implement persistence** (move from JSON to database)
5. **Add user interface** for parameter tuning (lambda, num_seeds, etc.)

## Troubleshooting

### "No enriched artists found"
- Run `enrich_top_25_artists()` before `select_seed_artists()`

### "Could not find X diverse artists"
- Increase `lambda_param` (prioritize rank over diversity)
- Use fewer seed artists

### API rate limits
- Built-in `time.sleep()` delays prevent hitting limits
- Last.fm: 5 requests/sec limit (0.2s delay)
- Deezer: No rate limit

### Missing fields in output
- Non-critical API failures are graceful (empty arrays/None)
- Check logs for specific API errors

## File Structure

```
backend/
├── __init__.py                 # Module exports
├── user_data.py               # JSON persistence
├── user_ingestion.py          # Fetch top 25 artists
├── tag_enrichment.py          # Last.fm enrichment
├── seed_selection.py          # MMR algorithm
├── graph_init.py              # Build initial graph
├── pipeline.py                # Orchestrator
├── api_routes.py              # Flask endpoints
├── example_pipeline.py        # Usage examples
├── README.md                  # Full documentation
└── QUICK_START.md            # This file

data/users/
├── user_id_db.json           # User's enriched data
└── user_id_map.json          # User's graph structure
```
