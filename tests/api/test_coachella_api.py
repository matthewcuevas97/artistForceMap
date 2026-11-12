"""HTTP API of the Coachella map (app.py)."""

import time
from urllib.parse import quote

import pytest
import requests

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


def test_graph_derived_personalization_from_similar_artist(coachella_app, coachella_client, http):
    """BUG-04: a user who only listens to an off-lineup artist lights up the lineup acts similar to it."""
    from data.graph_builder import _norm
    lineup = {_norm(m) for n in coachella_app._nodes for m in [n["name"], *(n.get("lastfm_artists") or [])]}
    # Lowest-listener node with a strong off-lineup similar artist, so the derived score beats its baseline.
    target, fave = next(
        (n, s["name"]) for n in sorted(coachella_app._nodes, key=lambda n: n.get("listeners", 0))
        for s in n.get("similar_artists") or []
        if s["match"] >= 0.9 and _norm(s["name"]) not in lineup)
    http.add("GET", LASTFM_URL, json=lastfm_top_artists_payload([fave]))
    with coachella_client.session_transaction() as s:
        s["lastfm_user"] = "bob"
    data = coachella_client.get("/api/graph").get_json()
    node = next(n for n in data["nodes"] if n["name"] == target["name"])
    assert target["name"] in data["user_seeds"]
    assert node["score"] >= 0.9 * 0.6 - 1e-9
    assert "similar_artists" not in node  # server-side only; keeps the payload small


def test_graph_spotify_failure_degrades_to_baseline(coachella_client, http):
    http.add("GET", f"{SPOTIFY_API}/me/top/artists", status=401, json={"error": {"status": 401, "message": "expired"}})
    with coachella_client.session_transaction() as s:
        s["spotify_token"] = "tok"
        s["spotify_token_expires_at"] = time.time() + 3600
    r = coachella_client.get("/api/graph")
    assert r.status_code == 200 and r.get_json()["user_seeds"] == []


# ── /api/artist ───────────────────────────────────────────────────────────────

def test_artist_lookup_and_404(coachella_client):
    assert coachella_client.get("/api/artist?name=Definitely%20Not%20Playing").status_code == 404
    assert coachella_client.get("/api/artist").status_code == 404
    name = coachella_client.get("/api/graph").get_json()["nodes"][0]["name"]
    r = coachella_client.get("/api/artist?name=" + quote(name))
    assert r.status_code == 200 and r.get_json()["name"] == name
    assert "similar_artists" not in r.get_json()


@pytest.mark.parametrize("name", ["Model/Actriz", "¥ØU$UK€ ¥UK1MAT$U", "Cachirula & Loojan", "Chloé Caillet x Rossi."])
def test_artist_with_special_characters_in_name(coachella_app, coachella_client, name):
    """BUG-07 regression: '/' in a name used to 404 because the name was a path segment."""
    if name not in coachella_app._nodes_by_name:
        pytest.skip(f"{name!r} not in lineup")
    r = coachella_client.get("/api/artist?name=" + quote(name, safe=""))
    assert r.status_code == 200 and r.get_json()["name"] == name
    r = coachella_client.get("/api/artist/tracks?name=" + quote(name, safe=""))
    assert r.status_code == 200 and "tracks" in r.get_json()


def test_tracks_refresh_previews_from_deezer(coachella_app, coachella_client, http):
    node = next(n for n in coachella_app._nodes if n.get("top_tracks"))
    first = node["top_tracks"][0]["name"]
    http.add("GET", DEEZER, json={"data": [{"title": first, "preview": "https://cdn/p.mp3",
                                            "album": {"cover_big": "https://cdn/c.jpg"}}]})
    tracks = coachella_client.get("/api/artist/tracks?name=" + quote(node["name"], safe="")).get_json()["tracks"]
    assert tracks[0]["preview_url"] == "https://cdn/p.mp3"


def test_tracks_survive_deezer_outage(coachella_app, coachella_client, http):
    node = next(n for n in coachella_app._nodes if n.get("top_tracks"))
    http.add("GET", DEEZER, body=requests.ConnectionError("down"))
    r = coachella_client.get("/api/artist/tracks?name=" + quote(node["name"], safe=""))
    assert r.status_code == 200
    assert all(t["preview_url"] == "" for t in r.get_json()["tracks"])


# ── Auth ──────────────────────────────────────────────────────────────────────

# Spotify login/callback/state tests for both apps live in test_oauth_isolation.py.


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


# ── PERF-02: per-user top-artist cache ────────────────────────────────────────

def _lastfm_calls(http):
    return [c for c in http.calls if c.request.url.startswith(LASTFM_URL)]


def test_graph_caches_top_artists_per_user(coachella_app, http):
    http.add("GET", LASTFM_URL, json=lastfm_top_artists_payload(["The Strokes"]))
    alice, bob = coachella_app.app.test_client(), coachella_app.app.test_client()
    for client, user in ((alice, "alice"), (bob, "bob")):
        with client.session_transaction() as s:
            s["lastfm_user"] = user
    alice.get("/api/graph")
    alice.get("/api/graph")
    assert len(_lastfm_calls(http)) == 1
    bob.get("/api/graph")
    assert len(_lastfm_calls(http)) == 2, "users must not share cached top artists"


def test_graph_top_artist_cache_expires(coachella_app, coachella_client, http, monkeypatch):
    http.add("GET", LASTFM_URL, json=lastfm_top_artists_payload(["The Strokes"]))
    with coachella_client.session_transaction() as s:
        s["lastfm_user"] = "bob"
    coachella_client.get("/api/graph")
    real_time = time.time
    monkeypatch.setattr(coachella_app.time, "time", lambda: real_time() + coachella_app.TOP_ARTISTS_TTL + 1)
    coachella_client.get("/api/graph")
    assert len(_lastfm_calls(http)) == 2


def test_graph_does_not_cache_failed_top_artist_fetch(coachella_client, http):
    http.add("GET", LASTFM_URL, json={"error": 29, "message": "Rate limit exceeded"})
    http.add("GET", LASTFM_URL, json=lastfm_top_artists_payload(["The Strokes"]))
    with coachella_client.session_transaction() as s:
        s["lastfm_user"] = "bob"
    assert coachella_client.get("/api/graph").get_json()["user_seeds"] == []
    assert coachella_client.get("/api/graph").get_json()["user_seeds"] == ["The Strokes"]
