"""
Spotify OAuth flow for both apps: per-user token isolation (BUG-01), CSRF `state`
(BUG-02) and graceful handling of bad codes (BUG-03).

Regression context for BUG-01: spotify/auth used to build SpotifyOAuth without a
cache_handler, so spotipy fell back to a shared `.cache` file in the CWD and
get_access_token(code) returned that cached token instead of exchanging the code.
Every user after the first was logged in as the first user.
"""

import itertools
import json
import re
from urllib.parse import parse_qs, urlparse

import pytest

from tests.conftest import SPOTIFY_TOKEN_URL, spotify_token_payload

APPS = pytest.mark.parametrize("app_fixture", ["coachella_app", "universal_app"])
ME_URL = re.compile(r"https://api\.spotify\.com/v1/me/?$")


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
    http.add_callback("GET", ME_URL, callback=me_cb)


def start_login(client):
    """GET /login like a browser would; return the `state` Spotify will echo back."""
    r = client.get("/login")
    assert r.status_code == 302
    url = urlparse(r.location)
    assert url.netloc == "accounts.spotify.com" and url.path == "/authorize"
    return parse_qs(url.query)["state"][0]


def login(client, code):
    state = start_login(client)
    return client.get(f"/callback?code={code}&state={state}")


# ── BUG-01: token isolation ───────────────────────────────────────────────────

@APPS
def test_second_user_gets_their_own_token(request, http, app_fixture):
    mod = request.getfixturevalue(app_fixture)
    _wire_two_users(http)

    alice = mod.app.test_client()
    assert login(alice, "alice-code").status_code == 302
    bob = mod.app.test_client()
    assert login(bob, "bob-code").status_code == 302

    with alice.session_transaction() as s:
        assert s["spotify_token"] == "TOKEN_ALICE"
        assert s["spotify_display_name"] == "Alice"
    with bob.session_transaction() as s:
        assert s["spotify_token"] == "TOKEN_BOB"
        assert s["spotify_display_name"] == "Bob"


@APPS
def test_token_exchange_writes_no_cache_file(request, http, isolated_storage, app_fixture):
    mod = request.getfixturevalue(app_fixture)
    _wire_two_users(http)
    login(mod.app.test_client(), "alice-code")
    assert not list(isolated_storage["root"].glob(".cache*"))


@APPS
def test_stale_cache_file_is_ignored(request, http, isolated_storage, app_fixture):
    """A leftover `.cache` from the old code must not be handed to anyone."""
    mod = request.getfixturevalue(app_fixture)
    (isolated_storage["root"] / ".cache").write_text(json.dumps(
        {**spotify_token_payload(access="LEAKED"), "expires_at": 9_999_999_999}))
    _wire_two_users(http)
    client = mod.app.test_client()
    login(client, "alice-code")
    with client.session_transaction() as s:
        assert s["spotify_token"] == "TOKEN_ALICE"


@APPS
def test_expired_token_refresh_uses_no_shared_cache(request, http, isolated_storage, app_fixture):
    mod = request.getfixturevalue(app_fixture)
    http.add("POST", SPOTIFY_TOKEN_URL, json=spotify_token_payload(access="NEW", refresh="R2"))
    with mod.app.test_request_context():
        from flask import session
        session.update(spotify_token="OLD", spotify_refresh_token="R1", spotify_token_expires_at=0)
        assert mod.get_valid_spotify_token() == "NEW"
        assert session["spotify_refresh_token"] == "R2"
    assert not list(isolated_storage["root"].glob(".cache*"))


# ── BUG-02: CSRF state ────────────────────────────────────────────────────────

@APPS
def test_login_issues_fresh_state_each_time(request, app_fixture):
    client = request.getfixturevalue(app_fixture).app.test_client()
    s1, s2 = start_login(client), start_login(client)
    assert s1 != s2 and len(s1) >= 16


@APPS
@pytest.mark.parametrize("state", [None, "forged"])
def test_callback_rejects_missing_or_forged_state(request, http, app_fixture, state):
    """Login CSRF: an attacker's code must not be accepted without the victim's own state."""
    client = request.getfixturevalue(app_fixture).app.test_client()
    _wire_two_users(http)
    start_login(client)  # victim has a pending login with some other state
    qs = "code=attacker-code" + (f"&state={state}" if state else "")
    assert client.get(f"/callback?{qs}").status_code == 400
    with client.session_transaction() as s:
        assert "spotify_token" not in s
    assert not [c for c in http.calls if c.request.url.startswith(SPOTIFY_TOKEN_URL)]


@APPS
def test_callback_without_login_is_rejected(request, http, app_fixture):
    client = request.getfixturevalue(app_fixture).app.test_client()
    _wire_two_users(http)
    assert client.get("/callback?code=x&state=anything").status_code == 400


@APPS
def test_state_is_single_use(request, http, app_fixture):
    client = request.getfixturevalue(app_fixture).app.test_client()
    _wire_two_users(http)
    state = start_login(client)
    assert client.get(f"/callback?code=a&state={state}").status_code == 302
    assert client.get(f"/callback?code=b&state={state}").status_code == 400


# ── Callback errors (BUG-03) ──────────────────────────────────────────────────

@APPS
def test_callback_error_and_missing_code(request, app_fixture):
    client = request.getfixturevalue(app_fixture).app.test_client()
    state = start_login(client)
    assert client.get(f"/callback?error=access_denied&state={state}").status_code == 400
    state = start_login(client)
    assert client.get(f"/callback?state={state}").status_code == 400


@APPS
def test_callback_with_bad_code_is_handled(request, http, app_fixture):
    client = request.getfixturevalue(app_fixture).app.test_client()
    http.add("POST", SPOTIFY_TOKEN_URL, status=400, json={"error": "invalid_grant"})
    r = login(client, "bad")
    assert r.status_code == 400 and b"try again" in r.data
    with client.session_transaction() as s:
        assert "spotify_token" not in s
