"""
Multi-user OAuth isolation.

spotify/auth.get_spotify_oauth() builds SpotifyOAuth without a cache_handler,
so spotipy falls back to CacheFileHandler('.cache') in the CWD. get_access_token(code)
returns any valid cached token *instead of exchanging the code*, so every user
after the first is logged in as the first user.
"""

import itertools
import json
import re

import pytest

from tests.conftest import SPOTIFY_API, SPOTIFY_TOKEN_URL, spotify_token_payload


def _wire_two_users(http):
    seq = itertools.count()
    tokens = ["TOKEN_ALICE", "TOKEN_BOB"]

    def token_cb(request):
        i = next(seq)
        return (200, {}, json.dumps(spotify_token_payload(access=tokens[min(i, 1)])))

    def me_cb(request):
        who = "alice" if "TOKEN_ALICE" in request.headers.get("Authorization", "") else "bob"
        return (200, {}, json.dumps({"id": who, "display_name": who.title()}))

    http.add_callback("POST", SPOTIFY_TOKEN_URL, callback=token_cb)
    http.add_callback("GET", re.compile(r"https://api\.spotify\.com/v1/me/?$"), callback=me_cb)


@pytest.mark.parametrize("app_fixture", ["coachella_app", "universal_app"])
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BUG-01 (CRITICAL): shared spotipy '.cache' file — the "
                   "second user to log in receives the first user's Spotify token")
def test_second_user_gets_their_own_token(request, http, app_fixture):
    mod = request.getfixturevalue(app_fixture)
    _wire_two_users(http)

    alice = mod.app.test_client()
    alice.get("/callback?code=alice-code")
    bob = mod.app.test_client()
    bob.get("/callback?code=bob-code")

    with bob.session_transaction() as s:
        assert s["spotify_token"] == "TOKEN_BOB"


def test_token_exchange_writes_cache_file_to_cwd(coachella_app, http, isolated_storage):
    """Documents the mechanism behind BUG-01: a token file lands in the working directory."""
    _wire_two_users(http)
    coachella_app.app.test_client().get("/callback?code=alice-code")
    cache_file = isolated_storage["root"] / ".cache"
    assert cache_file.exists()
    assert "TOKEN_ALICE" in cache_file.read_text()
