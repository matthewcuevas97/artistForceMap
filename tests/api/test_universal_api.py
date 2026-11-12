"""HTTP API of the universal map (app_universal.py)."""

import json
import threading
import time

import pytest

from backend import user_data
from backend.progress import report
from tests.conftest import LASTFM_URL, lastfm_top_artists_payload


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
    ("get", "/api/artist?name=A"), ("get", "/api/preview?deezer_id=1"),
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


# ── Expansion (BUG-24: Last.fm similar artists, any provider) ─────────────────

def _similar_payload(pairs):
    return {"similarartists": {"artist": [{"name": n, "match": str(m)} for n, m in pairs]}}


def _expand(client, artist):
    return client.post("/api/map/expand", json={"artist": artist})


@pytest.mark.parametrize("login", ["lastfm", "spotify"])
def test_expand_works_for_both_providers(universal_client, http, login):
    http.add("GET", LASTFM_URL, json=_similar_payload([("B", 0.9), ("C", 0.5)]))
    uid = "bob" if login == "lastfm" else "alice"
    with universal_client.session_transaction() as s:
        if login == "lastfm":
            s["lastfm_user"] = uid
        else:
            s.update(spotify_token="tok", spotify_token_expires_at=time.time() + 3600, spotify_id=uid)
    user_data.save_user_map(uid, {"nodes": [{"name": "A", "genre": "Pop"}], "edges": []})
    data = _expand(universal_client, "A").get_json()
    assert {n["name"] for n in data["nodes"]} == {"A", "B", "C"}
    assert {n["name"] for n in data["added_nodes"]} == {"B", "C"}
    b = next(n for n in data["nodes"] if n["name"] == "B")
    assert b["genre"] == "Pop" and b["details_loaded"] is False and b["parent"] == "A"
    assert {(e["source"], e["target"], e["weight"]) for e in data["edges"]} == {("A", "B", 0.9), ("A", "C", 0.5)}
    assert not [c for c in http.calls if "api.spotify.com" in c.request.url]


def test_expand_is_idempotent_and_persisted(universal_client, http):
    http.add("GET", LASTFM_URL, json=_similar_payload([("B", 0.9)]))
    _login_lastfm(universal_client)
    user_data.save_user_map("bob", {"nodes": [{"name": "A"}], "edges": []})
    _expand(universal_client, "A")
    again = _expand(universal_client, "A").get_json()
    assert again["message"] == "Already expanded" and again["added_nodes"] == []
    assert len(http.calls) == 1, "similar artists are cached"
    saved = user_data.load_user_map("bob")
    assert {n["name"] for n in saved["nodes"]} == {"A", "B"}
    assert next(n for n in saved["nodes"] if n["name"] == "A")["expanded"] is True


def test_expand_links_to_existing_nodes_without_duplicates(universal_client, http):
    http.add("GET", LASTFM_URL, json=_similar_payload([("B", 0.8), ("C", 0.7)]))
    _login_lastfm(universal_client)
    user_data.save_user_map("bob", {"nodes": [{"name": "A"}, {"name": "B"}],
                                    "edges": [{"source": "B", "target": "A"}]})
    data = _expand(universal_client, "A").get_json()
    assert [n["name"] for n in data["added_nodes"]] == ["C"]
    assert len(data["edges"]) == 2  # B–A kept once, A–C added


def test_expand_caps_new_nodes(universal_client, http):
    http.add("GET", LASTFM_URL, json=_similar_payload([(f"S{i}", 0.9 - i / 100) for i in range(15)]))
    _login_lastfm(universal_client)
    user_data.save_user_map("bob", {"nodes": [{"name": "A"}], "edges": []})
    data = _expand(universal_client, "A").get_json()
    assert [n["name"] for n in data["added_nodes"]] == [f"S{i}" for i in range(6)]


def test_expand_unknown_artist_is_404(universal_client):
    _login_lastfm(universal_client)
    user_data.save_user_map("bob", {"nodes": [{"name": "A"}], "edges": []})
    assert _expand(universal_client, "Nope").status_code == 404


def test_expand_lastfm_outage_is_502_and_changes_nothing(universal_client, http):
    http.add("GET", LASTFM_URL, json={"error": 29, "message": "Rate limit exceeded"})
    _login_lastfm(universal_client)
    user_data.save_user_map("bob", {"nodes": [{"name": "A"}], "edges": []})
    assert _expand(universal_client, "A").status_code == 502
    assert user_data.load_user_map("bob")["nodes"] == [{"name": "A"}]


def test_lastfm_login_clears_spotify_session(universal_client, http):
    http.add("GET", LASTFM_URL, json=lastfm_top_artists_payload(["A"]))
    with universal_client.session_transaction() as s:
        s.update(spotify_token="t", spotify_id="alice")
    universal_client.post("/api/lastfm/login", json={"username": "bob"})
    with universal_client.session_transaction() as s:
        assert "spotify_token" not in s and "spotify_id" not in s and s["lastfm_user"] == "bob"


# ── Artist details & previews ─────────────────────────────────────────────────

def test_artist_details_load_and_persist_into_map(universal_client, http, monkeypatch):
    import app_universal
    from tests.unit.test_universal_pipeline import _mock_lastfm
    _mock_lastfm(http, tags=["House", "Electronic"])
    monkeypatch.setattr(app_universal, "get_deezer_info", lambda name: {
        "image_url": "https://img/x.jpg", "top_tracks": [{"name": "Song", "deezer_id": 42}]})
    _login_lastfm(universal_client)
    user_data.save_user_map("bob", {"nodes": [{"name": "B", "details_loaded": False, "genre": "Pop"}], "edges": []})
    d = universal_client.get("/api/artist?name=B").get_json()
    assert d["genre"] == "Electronic" and d["listeners"] == 123 and d["tags"] == ["house", "electronic"]
    assert d["top_tracks"] == [{"name": "Song", "deezer_id": 42}]
    node = user_data.load_user_map("bob")["nodes"][0]
    assert node["details_loaded"] is True and node["genre"] == "Electronic"


def test_artist_details_lastfm_outage_is_502(universal_client, http):
    from tests.unit.test_universal_pipeline import _mock_lastfm
    _mock_lastfm(http, error_on=("artist.getTopTags",))
    _login_lastfm(universal_client)
    assert universal_client.get("/api/artist?name=B").status_code == 502


def test_preview_resolves_fresh_url_by_deezer_id(universal_client, http):
    from backend import previews
    previews.clear()
    http.add("GET", "https://api.deezer.com/track/42", json={"id": 42, "preview": "https://cdn/fresh.mp3"})
    _login_lastfm(universal_client)
    assert universal_client.get("/api/preview?deezer_id=42").get_json() == {"preview_url": "https://cdn/fresh.mp3"}
    universal_client.get("/api/preview?deezer_id=42")
    assert len(http.calls) == 1, "memoised for a few minutes"
