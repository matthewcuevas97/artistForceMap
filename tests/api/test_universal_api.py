"""HTTP API of the universal map (app_universal.py)."""

import json
import threading
import time

import pytest

from backend import user_data
from backend.progress import report
from tests.conftest import LASTFM_URL, SPOTIFY_API, lastfm_top_artists_payload


def _sse_events(resp):
    body = resp.get_data(as_text=True)
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


def _login_lastfm(client, user="bob"):
    with client.session_transaction() as s:
        s["lastfm_user"] = user


def test_health_and_index(universal_client):
    assert universal_client.get("/api/health").get_json()["status"] == "ok"
    assert b"universal_map.js" in universal_client.get("/").data


@pytest.mark.parametrize("method,path", [
    ("post", "/api/map/init/stream"), ("post", "/api/map/init"),
    ("post", "/api/map/expand"), ("get", "/api/map/get"),
])
def test_map_endpoints_require_auth(universal_client, method, path):
    r = getattr(universal_client, method)(path, json={})
    assert r.status_code == 401


def test_map_get_returns_saved_map(universal_client):
    user_data.save_user_map("bob", {"user_id": "bob", "nodes": [{"name": "A"}], "edges": []})
    _login_lastfm(universal_client)
    assert universal_client.get("/api/map/get").get_json()["nodes"] == [{"name": "A"}]


def test_stream_emits_progress_then_complete(universal_app, universal_client, monkeypatch):
    def fake_pipeline(auth):
        report("STEP 1: User Ingestion")
        report("")  # blank lines are dropped
        report("✓ Fetched 25 top artists")
        user_data.save_user_map(auth["id"], {"nodes": [{"name": "A"}, {"name": "B"}],
                                             "edges": [{"source": "A", "target": "B"}]})
    monkeypatch.setattr(universal_app, "run_full_pipeline", fake_pipeline)
    _login_lastfm(universal_client)
    events = _sse_events(universal_client.post("/api/map/init/stream"))
    assert [e["message"] for e in events if "message" in e] == ["STEP 1: User Ingestion", "✓ Fetched 25 top artists"]
    assert events[-1]["complete"] is True and len(events[-1]["nodes"]) == 2


def test_stream_reports_pipeline_errors(universal_app, universal_client, monkeypatch):
    def failing(auth):
        report("STEP 1")
        raise ValueError("No enriched artists found")
    monkeypatch.setattr(universal_app, "run_full_pipeline", failing)
    _login_lastfm(universal_client)
    events = _sse_events(universal_client.post("/api/map/init/stream"))
    assert events[-1] == {"error": "No enriched artists found"}


def test_stream_does_not_capture_other_threads_output(universal_app, universal_client, monkeypatch):
    """BUG-12 regression: the stream swapped the global sys.stdout and relayed other requests' output."""
    started, release = threading.Event(), threading.Event()

    def slow_pipeline(auth):
        started.set()
        release.wait(5)
        user_data.save_user_map(auth["id"], {"nodes": [], "edges": []})

    monkeypatch.setattr(universal_app, "run_full_pipeline", slow_pipeline)
    _login_lastfm(universal_client)

    def other_request():
        started.wait(5)
        print("OTHER USER'S PRIVATE OUTPUT")
        report("OTHER USER'S PIPELINE PROGRESS")  # no sink in this thread -> stdout, not the stream
        release.set()
    t = threading.Thread(target=other_request)
    t.start()
    events = _sse_events(universal_client.post("/api/map/init/stream"))
    t.join()
    assert not any("OTHER USER" in e.get("message", "") for e in events)


def test_stream_keeps_alive_through_slow_silent_step(universal_app, universal_client, monkeypatch):
    """BUG-13 regression: a step silent for >30 s used to end the stream with 'Pipeline timeout'."""
    monkeypatch.setattr(universal_app, "SSE_KEEPALIVE_SECONDS", 0.1)
    done = threading.Event()

    def slow(auth):
        try:
            time.sleep(0.5)  # silent for 5 keepalive periods
            user_data.save_user_map(auth["id"], {"nodes": [{"name": "A"}], "edges": []})
        finally:
            done.set()
    monkeypatch.setattr(universal_app, "run_full_pipeline", slow)
    _login_lastfm(universal_client)
    body = universal_client.post("/api/map/init/stream").get_data(as_text=True)
    done.wait(5)
    assert ": keepalive" in body
    events = [json.loads(l[6:]) for l in body.splitlines() if l.startswith("data: ")]
    assert events[-1]["complete"] is True and events[-1]["nodes"] == [{"name": "A"}]


def test_stream_sets_no_cache_headers(universal_app, universal_client, monkeypatch):
    monkeypatch.setattr(universal_app, "run_full_pipeline",
                        lambda auth: user_data.save_user_map(auth["id"], {"nodes": [], "edges": []}))
    _login_lastfm(universal_client)
    r = universal_client.post("/api/map/init/stream")
    assert r.mimetype == "text/event-stream" and r.headers["Cache-Control"] == "no-cache"


def test_expand_requires_spotify_for_lastfm_users(universal_client):
    """Limitation (BUG-24): Last.fm users can never expand their map."""
    user_data.save_user_map("bob", {"nodes": [{"name": "A", "expanded": False}], "edges": []})
    _login_lastfm(universal_client)
    r = universal_client.post("/api/map/expand", json={"artist": "A"})
    assert r.status_code == 401 and "Spotify" in r.get_json()["error"]


def test_expand_fails_when_recommendations_endpoint_is_gone(universal_client, http):
    """BUG-24: GET /recommendations 404s for apps without pre-Nov-2024 extended access."""
    http.add("GET", f"{SPOTIFY_API}/search", json={"artists": {"items": [{"id": "ar1", "name": "A"}]}})
    http.add("GET", f"{SPOTIFY_API}/recommendations", status=404, json={"error": {"status": 404, "message": "Not Found"}})
    with universal_client.session_transaction() as s:
        s.update(spotify_token="tok", spotify_token_expires_at=time.time() + 3600, spotify_id="alice")
    user_data.save_user_map("alice", {"nodes": [{"name": "A"}], "edges": []})
    r = universal_client.post("/api/map/expand", json={"artist": "A"})
    assert r.status_code == 400 and "Spotify error" in r.get_json()["error"]


def test_expand_adds_nodes_and_is_idempotent(universal_client, http):
    http.add("GET", f"{SPOTIFY_API}/search", json={"artists": {"items": [{"id": "ar1", "name": "A"}]}})
    http.add("GET", f"{SPOTIFY_API}/recommendations", json={"tracks": [
        {"artists": [{"id": "b", "name": "B"}]}, {"artists": [{"id": "c", "name": "C"}, {"id": "b", "name": "B"}]}]})
    with universal_client.session_transaction() as s:
        s.update(spotify_token="tok", spotify_token_expires_at=time.time() + 3600, spotify_id="alice")
    user_data.save_user_map("alice", {"nodes": [{"name": "A"}], "edges": []})
    data = universal_client.post("/api/map/expand", json={"artist": "A"}).get_json()
    assert {n["name"] for n in data["nodes"]} == {"A", "B", "C"}
    assert len(data["edges"]) == 2
    again = universal_client.post("/api/map/expand", json={"artist": "A"}).get_json()
    assert again["message"] == "Already expanded"


def test_lastfm_login_clears_spotify_session(universal_client, http):
    http.add("GET", LASTFM_URL, json=lastfm_top_artists_payload(["A"]))
    with universal_client.session_transaction() as s:
        s.update(spotify_token="t", spotify_id="alice")
    universal_client.post("/api/lastfm/login", json={"username": "bob"})
    with universal_client.session_transaction() as s:
        assert "spotify_token" not in s and "spotify_id" not in s and s["lastfm_user"] == "bob"


def test_artist_metadata_requires_spotify(universal_client):
    assert universal_client.get("/api/artist/A").status_code == 401
