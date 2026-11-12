# artistForceMap

Interactive force-directed maps of music artists, personalised from your Spotify or Last.fm listening.

| App | Entry point | What it does | Docs |
|---|---|---|---|
| **Coachella 2026 map** | `app.py` | The 142-act lineup as a graph of similar artists. Logged in, the acts you listen to (or that sound like what you listen to) grow and light up. Preview tracks, filter by day, build a playlist. | [docs/COACHELLA.md](docs/COACHELLA.md) |
| **Universal map** | `app_universal.py` | Your own map: 5 diverse seed artists from your top 25, plus their similar artists. Click any artist to load details and **Expand** it with more similar artists. | [docs/UNIVERSAL.md](docs/UNIVERSAL.md) |

Both apps share Spotify OAuth / Last.fm login (`web_auth.py`, `spotify/`) and the Last.fm client (`lastfm/`).

## Setup

```bash
python3.9 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt        # requirements.txt for production only
cp .env.example .env                       # then fill in the values below
```

`.env` (never committed):

```
FLASK_SECRET_KEY=<random string>
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8080/callback
LASTFM_API_KEY=...
# SESSION_COOKIE_SECURE=1   when served over HTTPS
```

Spotify apps in development mode only accept users you add in the Spotify dashboard.

## Run

```bash
python app.py             # Coachella map  → http://127.0.0.1:8080
python app_universal.py   # Universal map  → http://127.0.0.1:8080
```

Production: `gunicorn -w 1 --threads 8 app:app` (or `app_universal:app`). **Use a single worker
process**: the universal map's file locks and the per-user caches are in-process.

## Tests

```bash
pytest -m "not e2e"   # unit + API, ~2 s
pytest                # + Playwright browser tests against your local Chrome, ~6 min
HEADED=1 pytest -m e2e -k mobile          # watch a browser test
PW_CHANNEL=chromium pytest -m e2e         # use Playwright's bundled Chromium instead
```

The suite never touches the network (`responses` blocks it, d3 is vendored) or your real `data/`
files (caches are redirected to temp dirs; a guard fails the run if `data/cache` or `data/users`
change). CI (`.github/workflows/tests.yml`) runs pyflakes, the unit/API tests and the browser tests
on every push.

Bugs are tracked as strict `xfail` tests tagged `BUG-xx` (see [docs/REVIEW_2026-11.md](docs/REVIEW_2026-11.md)).
A fix makes the test XPASS, which fails the run until the marker is removed and the test becomes a
regression test.

## Layout

```
app.py, app_universal.py   Flask apps
web_auth.py                shared session config + auth blueprint
spotify/, lastfm/          API clients
data/                      Coachella graph data + runtime scoring (graph_builder.py)
backend/                   universal-map pipeline, caches, previews
scripts/                   offline data tools for the Coachella graph
static/js/                 Coachella ES modules (main.js) and universal_map.js
templates/                 the two single-page shells
tests/                     unit/, api/, e2e/
docs/                      design docs and the 2026-11 review
```
