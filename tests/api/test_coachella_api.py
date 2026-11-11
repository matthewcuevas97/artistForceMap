"""HTTP API of the Coachella map (app.py)."""

import re
import time
from urllib.parse import quote

import pytest
import requests
from spotipy.oauth2 import SpotifyOauthError

from tests.conftest import (LASTFM_URL, SPOTIFY_API, SPOTIFY_TOKEN_URL,
                            lastfm_top_artists_payload, spotify_token_payload)

DEEZER = "https://api.deezer.com/search"


# ── /api/graph ────────────────────────────────────────────────────────────────

def test_index_renders(coachella_client):
    r = coachella_client.get("/")
    assert r.status_code == 200
    assert b'id="graph"' in r.data and b"/static/js/main.js" in r.data


def test_graph_anonymous_shape(coachella_client):
    data = coachella_client.get("/api/graph").get_json()
    assert len(data["nodes"]) == 142
    assert data["user_seeds"] == []
    assert set(data["edges_by_level"]) == {"0.30", "0.32", "0.34", "0.36", "0.38", "0.40"}
    for n in data["nodes"]:
        assert 0 <= n["score"] <= 1
        assert "direct_score" not in n and "derived_score" not in n


def test_graph_edge_levels_are_nested_and_monotonic(coachella_client):
    levels = coachella_client.get("/api/graph").get_json()["edges_by_level"]
    keys = sorted(levels)
    counts = [len(levels[k]) for k in keys]
    assert counts == sorted(counts, reverse=True)
    key = lambda e: (e["source"], e["target"])
    for lo, hi in zip(keys, keys[1:]):
        assert {key(e) for e in levels[hi]} <= {key(e) for e in levels[lo]}


def test_graph_does_not_mutate_cached_nodes(coachella_app, coachella_client, http):
    before = dict(coachella_app._nodes[0])
    http.add("GET", LASTFM_URL, json=lastfm_top_artists_payload([before["name"]]))
    with coachella_client.session_transaction() as s:
        s["lastfm_user"] = "bob"
    coachella_client.get("/api/graph")
    assert coachella_app._nodes[0] == before


def test_graph_lastfm_user_personalization(coachella_app, coachella_client, http):
    smallest = min(coachella_app._nodes, key=lambda n: n.get("listeners", 0))["name"]
    http.add("GET", LASTFM_URL, json=lastfm_top_artists_payload([smallest.upper(), "Not On Lineup"]))
    with coachella_client.session_transaction() as s:
        s["lastfm_user"] = "bob"
    data = coachella_client.get("/api/graph").get_json()
    node = next(n for n in data["nodes"] if n["name"] == smallest)
    assert node["score"] == 1.0
    assert data["user_seeds"] == [smallest]


def test_graph_spotify_failure_degrades_to_baseline(coachella_client, http):
    http.add("GET", f"{SPOTIFY_API}/me/top/artists", status=401, json={"error": {"status": 401, "message": "expired"}})
    with coachella_client.session_transaction() as s:
        s["spotify_token"] = "tok"
        s["spotify_token_expires_at"] = time.time() + 3600
    r = coachella_client.get("/api/graph")
    assert r.status_code == 200 and r.get_json()["user_seeds"] == []


# ── /api/artist ───────────────────────────────────────────────────────────────

def test_artist_lookup_and_404(coachella_client):
    assert coachella_client.get("/api/artist/Definitely%20Not%20Playing").status_code == 404
    name = coachella_client.get("/api/graph").get_json()["nodes"][0]["name"]
    r = coachella_client.get("/api/artist/" + quote(name))
    assert r.status_code == 200 and r.get_json()["name"] == name


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BUG-07: artist names containing '/' (e.g. 'Model/Actriz') "
                   "404 because the route uses the default <name> converter; %2F is decoded first")
def test_artist_with_slash_in_name(coachella_client):
    assert coachella_client.get("/api/artist/" + quote("Model/Actriz", safe="")).status_code == 200


def test_tracks_refresh_previews_from_deezer(coachella_app, coachella_client, http):
    node = next(n for n in coachella_app._nodes if n.get("top_tracks"))
    first = node["top_tracks"][0]["name"]
    http.add("GET", DEEZER, json={"data": [{"title": first, "preview": "https://cdn/p.mp3",
                                            "album": {"cover_big": "https://cdn/c.jpg"}}]})
    tracks = coachella_client.get("/api/artist/" + quote(node["name"], safe="") + "/tracks").get_json()["tracks"]
    assert tracks[0]["preview_url"] == "https://cdn/p.mp3"


def test_tracks_survive_deezer_outage(coachella_app, coachella_client, http):
    node = next(n for n in coachella_app._nodes if n.get("top_tracks"))
    http.add("GET", DEEZER, body=requests.ConnectionError("down"))
    r = coachella_client.get("/api/artist/" + quote(node["name"], safe="") + "/tracks")
    assert r.status_code == 200
    assert all(t["preview_url"] == "" for t in r.get_json()["tracks"])


# ── Auth ──────────────────────────────────────────────────────────────────────

def test_login_redirects_to_spotify(coachella_client):
    r = coachella_client.get("/login")
    assert r.status_code == 302 and r.location.startswith("https://accounts.spotify.com/authorize")


def test_callback_error_and_missing_code(coachella_client):
    assert coachella_client.get("/callback?error=access_denied").status_code == 400
    assert coachella_client.get("/callback").status_code == 400


@pytest.mark.xfail(strict=True, raises=(AssertionError, SpotifyOauthError), reason="BUG-03: an invalid/expired ?code= makes get_token raise "
                   "SpotifyOauthError → unhandled 500")
def test_callback_with_bad_code_is_handled(coachella_client, http):
    http.add("POST", SPOTIFY_TOKEN_URL, status=400, json={"error": "invalid_grant"})
    assert coachella_client.get("/callback?code=bad").status_code < 500


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BUG-02: OAuth `state` is never generated or verified, so "
                   "/callback accepts any code (login CSRF)")
def test_callback_requires_matching_state(coachella_client, http):
    http.add("POST", SPOTIFY_TOKEN_URL, json=spotify_token_payload())
    http.add("GET", re.compile(r"https://api\.spotify\.com/v1/me/?$"), json={"id": "attacker", "display_name": "attacker"})
    coachella_client.get("/callback?code=attacker-code")
    with coachella_client.session_transaction() as s:
        assert "spotify_token" not in s


def test_lastfm_login_and_logout(coachella_client, http):
    http.add("GET", LASTFM_URL, json=lastfm_top_artists_payload(["A"]))
    r = coachella_client.post("/api/lastfm/login", json={"username": "  bob  "})
    assert r.get_json() == {"ok": True}
    with coachella_client.session_transaction() as s:
        assert s["lastfm_user"] == "bob"
    coachella_client.post("/api/lastfm/logout")
    with coachella_client.session_transaction() as s:
        assert "lastfm_user" not in s


@pytest.mark.parametrize("payload", [{"username": ""}, {}, None])
def test_lastfm_login_rejects_blank(coachella_client, payload):
    r = coachella_client.post("/api/lastfm/login", json=payload)
    assert r.status_code == 400


def test_lastfm_login_unknown_user(coachella_client, http):
    http.add("GET", LASTFM_URL, json={"error": 6, "message": "User not found"})
    assert coachella_client.post("/api/lastfm/login", json={"username": "ghost"}).status_code == 400


def test_expired_token_is_refreshed(coachella_app, coachella_client, http):
    http.add("POST", SPOTIFY_TOKEN_URL, json=spotify_token_payload(access="NEW", refresh="R2"))
    with coachella_app.app.test_request_context():
        from flask import session
        session["spotify_token"] = "OLD"
        session["spotify_refresh_token"] = "R1"
        session["spotify_token_expires_at"] = time.time() - 10
        assert coachella_app.get_valid_spotify_token() == "NEW"
        assert session["spotify_refresh_token"] == "R2"


def test_refresh_failure_returns_none(coachella_app, http):
    http.add("POST", SPOTIFY_TOKEN_URL, status=400, json={"error": "invalid_grant"})
    with coachella_app.app.test_request_context():
        from flask import session
        session.update(spotify_token="OLD", spotify_refresh_token="R1", spotify_token_expires_at=0)
        assert coachella_app.get_valid_spotify_token() is None


# ── Playlist ──────────────────────────────────────────────────────────────────

def test_create_playlist_requires_auth(coachella_client):
    assert coachella_client.post("/api/spotify/create-playlist", json={"tracks": []}).status_code == 401


def test_create_playlist_searches_and_adds(coachella_client, http):
    http.add("POST", f"{SPOTIFY_API}/me/playlists", json={"id": "PL1"})
    http.add("GET", f"{SPOTIFY_API}/search", json={"tracks": {"items": [{"uri": "spotify:track:T1"}]}})
    http.add("POST", f"{SPOTIFY_API}/playlists/PL1/items", json={"snapshot_id": "s"})
    with coachella_client.session_transaction() as s:
        s["spotify_token"] = "tok"
        s["spotify_token_expires_at"] = time.time() + 3600
    r = coachella_client.post("/api/spotify/create-playlist",
                              json={"tracks": [{"artist": "A", "name": "Song"}]})
    assert r.get_json() == {"ok": True, "playlist_url": "https://open.spotify.com/playlist/PL1"}
