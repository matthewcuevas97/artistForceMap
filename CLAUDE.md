# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

- Python 3.9 (CPython) with a local virtualenv at `venv/`
- Activate: `source venv/bin/activate`
- Install: `pip install -r requirements-dev.txt`
- Secrets come from `.env` (gitignored): `SPOTIFY_CLIENT_ID/SECRET/REDIRECT_URI`, `LASTFM_API_KEY`, `FLASK_SECRET_KEY`

## Project

Two Flask apps sharing `spotify/`, `lastfm/` and `backend/`:

- `app.py` — Coachella 2026 lineup force graph. Serves `templates/index.html` + ES modules in `static/js/` (`main.js` entry). Graph data is precomputed in `data/graph_static.json`.
- `app_universal.py` — "universal map" built from the user's own top artists via `backend/pipeline.py` (ingestion → tag enrichment → MMR seed selection → graph init: 5 seeds + their top similar artists), streamed over SSE. Pipeline code reports progress with `backend.progress.report()`, not `print()`. Expansion uses Last.fm similar artists (`POST /api/map/expand`) for both providers; stub nodes load details from `GET /api/artist?name=`; previews are resolved at play time (`GET /api/preview`) because Deezer preview URLs expire after ~15 min, so never cache them. Frontend: `templates/index_universal.html` + `static/js/universal_map.js` (escape everything that reaches innerHTML).
- Storage: file-backed JSON caches in `data/cache/` and `data/users/`, written atomically under per-file locks (`backend/storage.py`); user ids are mapped to safe file names. In-process locks only, so run one worker process.
- `scripts/` — offline data pipeline (`precompute.py` etc.). Rerunning `precompute.py` wipes enrichment fields (BUG-34). To refresh `similar_artists` in `graph_static.json` from the Last.fm cache, run `python scripts/migrate_similar.py`; `python scripts/trim_bios.py` fixes hard-cut bios. Tests fail if either is needed.

Run: `python app.py` or `python app_universal.py` (both on 127.0.0.1:8080).

## Tests

- `pytest -m "not e2e"` — unit + API (~1.5 s). `pytest` — also Playwright browser tests against the local Chrome (~5 min).
- All network is blocked by `responses`; caches/user data are redirected to tmp dirs; a session guard fails the run if real `data/` files change.
- Known bugs are strict `xfail(raises=...)` tests tagged `BUG-xx`, matching `docs/REVIEW_2026-11.md`. When a fix makes one XPASS, remove its marker. (As of Phase 3 there are none left; new bugs should follow the same convention.)
