"""
Shared pytest fixtures.

Guarantees for every test:
  * Dummy credentials are in the environment BEFORE any app module is imported
    (python-dotenv's load_dotenv() does not override existing env vars, so the
    real .env is never used by the suite).
  * All on-disk caches / user data are redirected to a per-test tmp dir, so the
    suite can never clobber data/cache/*.json or data/users/*.json.
  * The CWD is a tmp dir, so spotipy's default CacheFileHandler (".cache")
    writes there and not into the repo.
  * All outbound HTTP made through `requests` (incl. spotipy) is intercepted by
    `responses`. Any request a test did not explicitly mock raises
    ConnectionError — no test can accidentally hit Spotify/Last.fm/Deezer.
"""

import os
import sys
from pathlib import Path

import pytest
import responses as responses_lib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["FLASK_SECRET_KEY"] = "test-secret-key"
os.environ["SPOTIFY_CLIENT_ID"] = "test-client-id"
os.environ["SPOTIFY_CLIENT_SECRET"] = "test-client-secret"
os.environ["SPOTIFY_REDIRECT_URI"] = "http://127.0.0.1:8080/callback"
os.environ["LASTFM_API_KEY"] = "test-lastfm-key"

LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API = "https://api.spotify.com/v1"


def _snapshot_repo_data():
    out = {}
    for sub in ("data/cache", "data/users"):
        d = ROOT / sub
        for f in d.glob("*") if d.exists() else []:
            out[str(f.relative_to(ROOT))] = f.stat().st_mtime
    return out


@pytest.fixture(scope="session", autouse=True)
def repo_data_guard():
    """Fail the run if any test wrote to the real data/cache or data/users."""
    before = _snapshot_repo_data()
    yield
    after = _snapshot_repo_data()
    changed = sorted(k for k in after if before.get(k) != after[k])
    assert not changed, f"tests modified real repo data: {changed}"


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Redirect every file-backed cache and the CWD into tmp_path."""
    import backend.cache as cache
    import backend.user_data as user_data

    cache_dir = tmp_path / "cache"
    users_dir = tmp_path / "users"
    cache_dir.mkdir()
    users_dir.mkdir()

    monkeypatch.setattr(cache, "CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(cache, "ARTIST_CACHE_FILE", str(cache_dir / "artists.json"))
    monkeypatch.setattr(cache, "SIMILAR_ARTISTS_CACHE_FILE", str(cache_dir / "similar_artists.json"))
    monkeypatch.setattr(cache, "DEEZER_CACHE_FILE", str(cache_dir / "deezer.json"))
    monkeypatch.setattr(user_data, "USER_DATA_DIR", str(users_dir))

    monkeypatch.chdir(tmp_path)
    return {"cache": cache_dir, "users": users_dir, "root": tmp_path}


@pytest.fixture(autouse=True)
def http(request):
    """Block real network; yield a RequestsMock tests can register responses on."""
    with responses_lib.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


# ── Flask apps ────────────────────────────────────────────────────────────────

@pytest.fixture
def coachella_app():
    import app as coachella
    coachella.app.config.update(TESTING=True)
    return coachella


@pytest.fixture
def coachella_client(coachella_app):
    return coachella_app.app.test_client()


@pytest.fixture
def universal_app():
    import app_universal
    app_universal.app.config.update(TESTING=True)
    return app_universal


@pytest.fixture
def universal_client(universal_app):
    return universal_app.app.test_client()


# ── Helpers ───────────────────────────────────────────────────────────────────

def lastfm_top_artists_payload(names):
    return {"topartists": {"artist": [{"name": n} for n in names]}}


def spotify_token_payload(access="ACCESS", refresh="REFRESH", expires_in=3600):
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "refresh_token": refresh,
        "scope": "user-top-read user-read-recently-played playlist-modify-private playlist-modify-public",
    }
