# Design Document: artistForceMap

**Version**: 1.2
**Date**: 2026-03-15
**Status**: New edge generation pipeline implemented.

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
│  │    GET  /api/graph                                             ││
│  │    GET  /api/artist/<name>                                     ││
│  │    GET  /api/artist/<name>/tracks                              ││
│  │    POST /api/spotify/create-playlist                           ││
│  └────────────────────────────────────────────────────────────────┘│
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │ spotify/      │  │ lastfm/      │  │ data/                    │ │
│  │  auth.py      │  │  fetch.py    │  │  (No longer used)        │ │
│  │  fetch.py     │  │              │  │                          │ │
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

The data pipeline is now a single, powerful script that generates a deterministic graph structure.

```
coachella_2026.csv
        │
        ▼
scripts/precompute.py
  Node Generation:
    - Reads artists from CSV to create base nodes.
    - Pass 1: Fetches artist listeners and a comprehensive list of up to 10 tags from Last.fm's `artist.getTopTags` endpoint.
    - Pass 2: Fetches similar artists from Last.fm, which are used as candidates for "gold standard" edges.
  
  Edge Generation (5-Pass Deterministic Pipeline with Degree Cap of 6):
    - Pass 1: Gold Standard Edges - Adds edges from Last.fm's similar artists if both nodes are under the degree cap.
    - Pass 2: Base RBO Edges - Calculates Rank-Biased Overlap (RBO) on artist tags and adds edges for pairs with a score >= 0.21.
    - Pass 3: Conditional Rewiring - Attempts to connect "orphan" nodes (those that failed to connect in Pass 2 because their partner was full) to a neighbor of the full node.
    - Pass 4: Adaptive Floor - Connects any remaining zero-degree nodes to their highest-scoring RBO partner, provided the score is >= 0.05.
    - Pass 5: Hail Mary - As a final step, connects any still-isolated nodes to the most popular artist of the same genre.

  Enrichment (Optional, can be run standalone):
    - Pass 3: Fetches artist images and bios from Last.fm and top tracks from Deezer.
    - Pass 4: Fetches fallback images from Deezer for any artists missing a valid image.
        │
        ▼
data/graph_static.json
  - A single file containing two main keys: `nodes` and `links`.
  - `nodes`: An array of all artist objects with their full metadata.
  - `links`: An array of all generated edges, each with a `source`, `target`, and the `pass` number it was generated in.
```

---

## 3. Data Model

### 3.1 Artist Node (in `graph_static.json`)

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
  "tags": ["pop", "electropop", "dance-pop", "hyperpop", "bubblegum pop"],
  "top_tracks": [
    {
      "name": "360",
      "deezer_url": "https://www.deezer.com/track/...",
      "album_art": "https://cdn-images.dzcdn.net/..."
    }
  ]
}
```

### 3.2 Edge (in `graph_static.json`)

```json
{
  "source": "Artist A",
  "target": "Artist B",
  "pass": 2
}
```

- **source/target**: The names of the connected artists.
- **pass**: An integer (1-5) indicating which pass in the deterministic pipeline generated this edge. This replaces the previous `weight` and `type` fields, as the connection logic is now more nuanced.

### 3.3 Edge Thresholds

The concept of pre-computing edges at multiple thresholds is now **obsolete**. The graph has a single, deterministically generated set of edges with a fixed degree cap of 6 per node. The frontend slider for changing the threshold has been removed.

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

The scoring system remains the same, based on user listening data and baseline listener counts.

---

## 4. Authentication

Authentication logic remains unchanged (Spotify OAuth 2.0 and Last.fm username).

---

## 5. Frontend Behavior

### 5.1 Graph Rendering

- **Engine**: D3.js v7 force simulation.
- **Data Source**: The frontend now receives a single graph structure with a fixed set of nodes and links.
- **Edge Filtering**: The client-side filtering of edges by weight or threshold is no longer necessary. All provided edges are rendered.

### 5.2 Controls Panel (Bottom-Left)

- **Edge Threshold Slider**: This control has been **removed** as it is no longer applicable.
- Other controls (Auth, Day filter, Node size, etc.) remain the same.

---

## 6. API Reference

### `GET /api/graph`

Returns the full graph data, enriched with the current user's scores. The `threshold` parameter is no longer used.

**Response**:
```json
{
  "nodes": [{ "name": "...", "genre": "...", "score": 0.75, ... }],
  "links": [{ "source": "A", "target": "B", "pass": 1 }],
  "user_seeds": ["Artist A", "Artist B"]
}
```

- `links`: The new key for the edge list, replacing `edges`.

Other API endpoints remain the same.

---

## 7. External Dependencies

Dependencies remain largely the same. The `data/graph_builder.py` and `scripts/build_slim.py` files are now obsolete and have been removed.

---

## 8. Deployment Considerations

Deployment considerations are unchanged. The new `graph_static.json` file is still loaded into memory at startup.

---

## 9. Recent Changes (2026-03-15)

### 9.1 Deterministic Edge Generation Pipeline

**Branch**: `main`
**Commits**:
- `[commit hash]` feat: Implement deterministic edge generation pipeline

**Changes**:
1. **Overhauled Edge Generation** (`scripts/precompute.py`):
   - Replaced the old, simple edge builder with a 5-pass deterministic pipeline to create a more consistent and high-quality graph.
   - Implemented Rank-Biased Overlap (RBO) to score similarity between artists based on their tag lists.
   - Enforces a strict degree cap of 6 connections per artist, preventing "supernodes" and improving graph readability.

2. **Updated Data Fetching** (`lastfm/fetch.py`):
   - Switched from `artist.getInfo` to `artist.getTopTags` to fetch a more comprehensive list of up to 10 tags per artist, improving the accuracy of RBO calculations.

3. **Simplified Graph Structure**:
   - The final graph data (`graph_static.json`) now contains a `nodes` array and a `links` array. The `links` array replaces the old `edges` array and contains simpler objects.
   - Removed the need for `graph_slim.json` and the `scripts/build_slim.py` script.

**Impact**: The graph structure is now much more stable and predictable. The removal of the edge threshold slider simplifies the user interface. The use of more comprehensive tags and a sophisticated algorithm results in higher-quality connections between artists.

---

## 10. Known Limitations

1. **No token refresh**: Spotify sessions expire after 1 hour.
2. **No offline/PWA support**.
3. **No mobile optimization**.
4. **Fixed viewport**: No resize handling.
5. **Single festival**: Hardcoded to Coachella 2026.
6. **No user accounts**.
7. **Deezer preview expiry**.
8. **Standalone passes need update**: The `--pass1-only`, `--pass3-only`, etc. flags in `precompute.py` are not fully compatible with the new integrated pipeline and may need to be updated if standalone execution is required.

---

## 11. File Inventory

```
artistForceMap/
├── app.py                          # Flask server
├── requirements.txt                # Python deps
├── .env                            # API keys (gitignored)
├── .gitignore
├── DESIGN.md                       # This document
├── data/
│   ├── __init__.py
│   ├── coachella_2026.csv          # Source lineup data
│   └── graph_static.json           # Full precomputed graph with nodes and links
├── spotify/
│   ├── __init__.py
│   ├── auth.py                     # OAuth helpers
│   └── fetch.py                    # Top artists fetcher
├── lastfm/
│   ├── __init__.py
│   └── fetch.py                    # Last.fm API wrapper
├── scripts/
│   ├── __init__.py
│   └── precompute.py               # 5-pass data and edge generation pipeline
├── static/
│   ├── graph.js                    # Frontend app
│   ├── placeholder_artist.jpeg     # Fallback artist image
│   └── music-player-add-playlist-queue-square-black-icon.svg
└── templates/
    └── index.html                  # SPA shell + CSS
```
