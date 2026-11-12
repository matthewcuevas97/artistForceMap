# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

- Python 3.9 (CPython) with a local virtualenv at `venv/`
- Activate: `source venv/bin/activate`
- Install: `pip install -r requirements-dev.txt`
- Secrets come from `.env` (gitignored): `SPOTIFY_CLIENT_ID/SECRET/REDIRECT_URI`, `LASTFM_API_KEY`, `FLASK_SECRET_KEY`

## Project

Two Flask apps sharing `spotify/`, `lastfm/` and `backend/`:

- `app.py` — Coachella 2026 lineup force graph. Serves `templates/index.html` + ES modules in `static/js/` (`main.js` entry). Graph data is precomputed in `data/graph_static.json`. `static/graph.js` is dead legacy code.
- `app_universal.py` — prototype "universal map" built from the user's own top artists via `backend/pipeline.py` (ingestion → tag enrichment → MMR seed selection → graph init), streamed over SSE. Frontend: `templates/index_universal.html` + `static/js/universal_map.js`. Uses file-backed JSON caches in `data/cache/` and `data/users/`.
- `scripts/` — offline data pipeline (`precompute.py` etc.). Rerunning `precompute.py` wipes enrichment fields (BUG-34). To refresh `similar_artists` in `graph_static.json` from the Last.fm cache, run `python scripts/migrate_similar.py`; `python scripts/trim_bios.py` fixes hard-cut bios. Tests fail if either is needed.

Run: `python app.py` or `python app_universal.py` (both on 127.0.0.1:8080).

## Tests

- `pytest -m "not e2e"` — unit + API (~1.5 s). `pytest` — also Playwright browser tests against the local Chrome (~5 min).
- All network is blocked by `responses`; caches/user data are redirected to tmp dirs; a session guard fails the run if real `data/` files change.
- Known bugs are strict `xfail(raises=...)` tests tagged `BUG-xx`, matching `docs/REVIEW_2026-11.md`. When a fix makes one XPASS, remove its marker.
