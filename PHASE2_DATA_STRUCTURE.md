# Phase 2: Data Structure Analysis

## What the Frontend (app.py) Needs

The frontend expects a `user_map.json` structure identical to `graph_static.json`:

```json
{
  "nodes": [
    {
      "name": "Artist Name",
      "listeners": 81446,
      "genre": "Electronic",
      "image_url": "https://...",
      "bio": "...",
      "tags": ["dance", "rap", "electronic"],
      "similar_artists": [
        {"name": "Similar Artist", "match": 0.8}
      ],
      "top_tracks": [
        {
          "name": "Track Name",
          "artist": "Artist Name",
          "preview_url": "https://...",
          "album_art": "https://..."
        }
      ],
      "lastfm_artists": ["Artist Name"],
      "artist_profiles": [
        {
          "name": "Artist Name",
          "image_url": "https://...",
          "bio": "..."
        }
      ],
      "stage": "",
      "day": "Sunday",
      "weekend": "Both"
    }
  ],
  "links": [
    {
      "source": "Artist A",
      "target": "Artist B",
      "weight": 0.85,
      "type": "similarity"
    }
  ]
}
```

### Key Fields Used by Frontend:

1. **graph_builder.py** (enrich_with_scores):
   - `nodes[].similar_artists[].name` - to match against user's top artists
   - `nodes[].similar_artists[].match` - similarity score for derived scoring
   - `nodes[].listeners` - baseline scoring

2. **app.py** (api_graph endpoint):
   - `nodes[].name` - artist identity
   - `nodes[].listeners` - score normalization
   - `edges[]` with pass levels - threshold-based rendering

3. **D3 Visualization**:
   - `nodes[].name`
   - `nodes[].image_url`
   - `nodes[].genre`
   - `nodes[].tags`
   - `links[]` (source/target)

---

## What the Ingestion/Enrichment Pipeline Currently Produces

### Step 1: Ingestion (user_ingestion.py)
**Input**: OAuth token or Last.fm username
**Output**: `top_artists` array
```json
{
  "top_artists": [
    {
      "name": "Artist Name",
      "rank": 1,
      "spotify_id": "...",
      "genres": ["electronic", "house"],
      "images": [...],
      "popularity": 85
    }
  ]
}
```

### Step 2: Enrichment (tag_enrichment.py)
**Input**: top_artists list
**Output**: `all_artists` object
```json
{
  "all_artists": {
    "Artist Name": {
      "name": "Artist Name",
      "listeners": 5000000,
      "tags": ["electronic", "house", "techno"],
      "image_url": "https://lastfm...",
      "bio": "..."
    }
  }
}
```
**Missing for Frontend**:
- `similar_artists` (Last.fm API)
- `top_tracks` (Deezer API)
- `lastfm_artists` array
- `artist_profiles`
- `stage`, `day`, `weekend` (Coachella-specific)

### Step 3: Seed Selection (seed_selection.py)
**Input**: all_artists + top_artists
**Output**: seed_artists list
```json
{
  "seed_artists": [
    {"name": "Artist 1", "rank": 1, "score": 0.98},
    {"name": "Artist 2", "rank": 3, "score": 0.89},
    ...
  ]
}
```

### Step 4: Graph Initialization (graph_init.py) - EXPECTED
**Input**: seed_artists from step 3
**Output**: user_map.json structure
```json
{
  "nodes": [...],
  "edges": [...]
}
```

---

## The Gap: What We Need to Build in Phase 2

### Current State:
- ✅ Ingestion: Fetch user's top 25 artists (Spotify/Last.fm)
- ✅ Enrichment: Fetch metadata (listeners, tags, bio from Last.fm)
- ✅ Seed Selection: Pick 5 diverse seed artists
- ❌ Graph Building: Generate full graph structure from seeds

### What Phase 2 Must Deliver:

```
For each of 5 seed artists:
  1. Fetch similar_artists from Last.fm → { name, match_score }
  2. Fetch top_tracks from Deezer → { name, preview_url, album_art }
  3. Merge with enrichment data → build node object
  4. Optionally fetch similar artists' data (2nd order)

Build edges by comparing similar_artists lists (deterministic algorithm)

Output: user_map.json with nodes + edges (same schema as graph_static.json)
```

### Node Building Pipeline:

| Field | Source | Phase | Status |
|-------|--------|-------|--------|
| name | Ingestion | 1 | ✅ |
| listeners | Enrichment | 2 | ✅ |
| tags | Enrichment | 2 | ✅ |
| image_url | Enrichment | 2 | ✅ |
| bio | Enrichment | 2 | ✅ |
| genre | Enrichment or override | 2 | ✅ |
| **similar_artists** | Last.fm API | **3** | ❌ |
| **top_tracks** | Deezer API | **3** | ❌ |
| **lastfm_artists** | Derived | **3** | ❌ |
| **artist_profiles** | Enrichment data | **3** | ❌ |
| stage | Manual/Coachella DB | **N/A** | ❌ |
| day | Manual/Coachella DB | **N/A** | ❌ |
| weekend | Derived from day | **N/A** | ❌ |

---

## Edge Building Algorithm

The `graph_builder.py` uses this logic:

```python
def build_edges(nodes, threshold=0.1):
    for each pair of artists (A, B):
        # 1. Direct similarity: check if A is in B's similar_artists list
        direct = max(
            A.similar_artists.get(B),  # B's match score in A's list
            B.similar_artists.get(A)   # A's match score in B's list
        )

        # 2. Jaccard similarity: overlap in their similar_artists lists
        sa = set(A.similar_artists.keys())
        sb = set(B.similar_artists.keys())
        jaccard = len(sa & sb) / len(sa | sb)

        # 3. Edge weight
        weight = max(direct, jaccard)

        if weight >= threshold:
            create_edge(A, B, weight)
```

**For user-specific graph**: We can use the same algorithm but limit nodes to:
1. 5 seed artists (guaranteed in graph)
2. Similar artists from seeds (fringe, optional)

---

## Comparison: graph_static.json vs User Graph

| Aspect | Static (Coachella) | User-Specific |
|--------|-------------------|---|
| Nodes | ~150 artists | 5-30 artists (seed + fringe) |
| Node Source | Manual curation | User's seed selection algorithm |
| similar_artists | Precomputed from Last.fm | Real-time Last.fm fetch |
| top_tracks | Precomputed from Deezer | Real-time Deezer fetch |
| Edge Algorithm | Same Jaccard + direct | Same Jaccard + direct |
| stage/day/weekend | Coachella schedule | N/A (or user's calendar?) |
| Enrichment | Historic (cached) | User-specific (0.2s rate limit) |

---

## Implementation Path for Phase 2

### Step 1: Build Node for Single Artist
```python
def build_node_for_artist(artist_name: str) -> dict:
    """
    Given an artist name, build complete node object.
    Requires data from all previous pipeline stages.
    """
    # Get base data from enrichment cache
    enriched = all_artists[artist_name]

    # Fetch similar artists (Last.fm)
    similar = fetch_lastfm_similar(artist_name)

    # Fetch top tracks (Deezer)
    tracks = fetch_deezer_tracks(artist_name)

    return {
        "name": artist_name,
        "listeners": enriched["listeners"],
        "tags": enriched["tags"],
        "image_url": enriched["image_url"],
        "bio": enriched["bio"],
        "genre": enriched.get("genre", "Unknown"),
        "similar_artists": similar,  # [{name, match}, ...]
        "top_tracks": tracks,  # [{name, artist, preview_url, album_art}, ...]
        "lastfm_artists": [artist_name],
        "artist_profiles": [{"name": artist_name, ...}],
        "stage": "",
        "day": "",
        "weekend": ""
    }
```

### Step 2: Build Graph from Seeds
```python
def build_user_graph(user_id: str) -> dict:
    """
    1. Load seed artists from user_db
    2. Build nodes for each seed
    3. Optionally expand to fringe
    4. Build edges using same algorithm as static graph
    5. Save to user_map.json
    """
    seed_artists = load_user_db(user_id)["seed_artists"]

    nodes = [build_node_for_artist(artist["name"]) for artist in seed_artists]
    edges = build_edges(nodes, threshold=0.1)

    return {
        "user_id": user_id,
        "nodes": nodes,
        "links": edges,  # Note: app.py expects "links" in response
    }
```

### Step 3: Integration with Existing Pipeline
- graph_init.py should call build_user_graph()
- Save result to user_map.json
- API endpoint /user/<id>/map returns this structure

---

## Key Differences to Track

1. **Field Names**:
   - user_map.json should have "links" (for API) not "edges"
   - graph_builder.py handles this mapping

2. **Schema Validation**:
   - Ensure all required fields exist (with defaults if needed)
   - Missing data (bio=null, tracks=[], etc.) is acceptable

3. **Performance**:
   - Building 5-node graph + fringe: ~15-20 API calls
   - With 0.2s rate limit: ~3-4 seconds
   - Acceptable for on-demand user graph

---

## Success Criteria

✅ user_map.json matches graph_static.json schema
✅ graph_builder.py can score nodes using similar_artists field
✅ Frontend D3 visualization works with user graph
✅ /api/graph endpoint returns properly formatted response
✅ Deterministic: same user → same graph structure
