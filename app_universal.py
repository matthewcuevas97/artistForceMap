"""
Universal map Flask app: a personal artist map seeded from the user's top artists
(Spotify or Last.fm) and grown on demand with Last.fm similar artists.
Auth routes come from web_auth; map generation lives in backend/.
"""

import json
import queue
import threading

from flask import Flask, Response, jsonify, render_template, request, session

from backend.user_data import load_user_map, update_user_map
from backend.pipeline import run_full_pipeline
from backend.progress import progress_sink
from backend.graph_init import SimilarUnavailable, expand_map, get_deezer_info, _derive_genre
from backend.cache import get_cached_artist, set_cached_artist
from backend.tag_enrichment import EnrichmentUnavailable, enrich_artist_with_lastfm
from backend.previews import resolve_preview
from web_auth import configure_session, create_auth_blueprint, get_valid_spotify_token
from lastfm.fetch import get_top_artists as lastfm_top

app = Flask(__name__)
configure_session(app)
app.register_blueprint(create_auth_blueprint(lambda user: bool(lastfm_top(user))))



# ============================================================================
# Real-time Progress Streaming
# ============================================================================

# Idle seconds between SSE keepalive comments while the pipeline is still running.
# There is no overall deadline: a slow silent step (rate-limited API calls) is fine
# as long as the pipeline thread is alive (BUG-13).
SSE_KEEPALIVE_SECONDS = 15


def _sse(payload):
    return f"data: {json.dumps(payload)}\n\n"


# ============================================================================
# Routes
# ============================================================================

@app.route("/")
def index():
    """Render the main single-page application shell."""
    return render_template("index_universal.html")


# ============================================================================
# Map Initialization & Expansion
# ============================================================================

@app.route("/api/map/init/stream", methods=["POST"])
def map_init_stream():
    """
    Initialize user's map with real-time progress updates via Server-Sent Events.
    Streams pipeline progress to frontend as it happens.
    """
    # Get all needed data BEFORE entering generator
    user_id = session.get("spotify_id") or session.get("lastfm_user")
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    spotify_token = get_valid_spotify_token()
    lastfm_user = session.get("lastfm_user")
    spotify_id = session.get("spotify_id")

    auth_data = None
    if spotify_token:
        auth_data = {
            "provider": "spotify",
            "id": spotify_id,
            "token": spotify_token
        }
    elif lastfm_user:
        auth_data = {
            "provider": "lastfm",
            "id": lastfm_user
        }

    if not auth_data:
        return jsonify({"error": "No auth data available"}), 401

    # Create queue for real-time progress messages
    progress_queue = queue.Queue()

    def run_pipeline_thread():
        """Run the pipeline, sending only *this run's* progress to the queue."""
        try:
            with progress_sink(lambda line: progress_queue.put(("message", line))):
                run_full_pipeline(auth_data)
            progress_queue.put(("complete", None))
        except Exception as e:
            app.logger.warning("Pipeline failed for %s: %s", user_id, e)
            progress_queue.put(("error", str(e) or e.__class__.__name__))

    thread = threading.Thread(target=run_pipeline_thread, daemon=True)
    thread.start()

    def generate_progress():
        """Relay queue items as SSE events; keep the connection alive while the run lasts."""
        while True:
            try:
                msg_type, msg_data = progress_queue.get(timeout=SSE_KEEPALIVE_SECONDS)
            except queue.Empty:
                if thread.is_alive():
                    yield ": keepalive\n\n"
                    continue
                # Thread ended without reporting (shouldn't happen, but never hang).
                yield _sse({"error": "Map generation stopped unexpectedly"})
                return

            if msg_type == "message":
                yield _sse({"message": msg_data})
            elif msg_type == "error":
                yield _sse({"error": msg_data})
                return
            elif msg_type == "complete":
                user_map = load_user_map(user_id)
                yield _sse({"complete": True, "nodes": user_map.get("nodes", []),
                            "edges": user_map.get("edges", [])})
                return

    return Response(generate_progress(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/map/init", methods=["POST"])
def map_init():
    """
    Initialize the user's personal map from their top artists.
    Runs the full pipeline to generate seed artists and initial graph.
    (Legacy endpoint - use /api/map/init/stream for progress updates)
    """
    user_id = session.get("spotify_id") or session.get("lastfm_user")
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        # Run full pipeline to generate user's initial graph
        spotify_token = get_valid_spotify_token()
        lastfm_user = session.get("lastfm_user")

        auth_data = None
        if spotify_token:
            auth_data = {
                "provider": "spotify",
                "id": session.get("spotify_id"),
                "token": spotify_token
            }
        elif lastfm_user:
            auth_data = {
                "provider": "lastfm",
                "id": lastfm_user
            }

        if not auth_data:
            return jsonify({"error": "No auth data available"}), 401

        # Run pipeline
        run_full_pipeline(auth_data)

        # Load the generated map
        user_map = load_user_map(user_id)

        return jsonify({
            "ok": True,
            "user_id": user_id,
            "nodes": user_map.get("nodes", []),
            "edges": user_map.get("edges", [])
        })
    except Exception as e:
        app.logger.error(f"Map init failed: {e}")
        return jsonify({"error": str(e)}), 500


def _current_user_id():
    return session.get("spotify_id") or session.get("lastfm_user")


@app.route("/api/map/expand", methods=["POST"])
def map_expand():
    """
    Grow the map from one artist with its Last.fm similar artists. Works for both
    Spotify and Last.fm users (Spotify's recommendations endpoint is unavailable to
    new apps). Returns the full map plus the delta so the client can merge in place.
    """
    user_id = _current_user_id()
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    artist_name = (request.get_json(silent=True) or {}).get("artist")
    if not artist_name:
        return jsonify({"error": "Artist name required"}), 400

    try:
        result = update_user_map(user_id, lambda m: expand_map(m, artist_name))
    except KeyError:
        return jsonify({"error": "Artist is not on your map"}), 404
    except SimilarUnavailable:
        return jsonify({"error": "Last.fm is unavailable right now. Try again shortly."}), 502

    user_map = load_user_map(user_id)
    body = {"ok": True, "nodes": user_map.get("nodes", []), "edges": user_map.get("edges", []),
            "added_nodes": result["added_nodes"], "added_edges": result["added_edges"]}
    if result["already_expanded"]:
        body["message"] = "Already expanded"
    return jsonify(body)


@app.route("/api/map/get", methods=["GET"])
def map_get():
    """Get the current user map."""
    user_id = session.get("spotify_id") or session.get("lastfm_user")
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        user_map = load_user_map(user_id)
        return jsonify({
            "ok": True,
            "user_id": user_id,
            "nodes": user_map.get("nodes", []),
            "edges": user_map.get("edges", [])
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/artist")
def api_artist():
    """
    Full details for an artist on the user's map (tags, listeners, bio, image, top
    tracks without preview URLs), from the shared caches or Last.fm + Deezer.
    The node is updated in the saved map so a reload keeps the details.
    """
    user_id = _current_user_id()
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "Artist name required"}), 400

    info = get_cached_artist(name)
    if info is None:
        try:
            info = enrich_artist_with_lastfm(name)
        except EnrichmentUnavailable:
            return jsonify({"error": "Last.fm is unavailable right now. Try again shortly."}), 502
        set_cached_artist(name, info)
    deezer = get_deezer_info(name)
    details = {
        "name": name,
        "listeners": info.get("listeners", 0),
        "tags": info.get("tags", []),
        "genre": _derive_genre(info.get("tags", [])),
        "bio": info.get("bio"),
        "image_url": deezer.get("image_url") or info.get("image_url"),
        "top_tracks": deezer.get("top_tracks", []),
        "details_loaded": True,
    }

    def merge(user_map):
        for node in user_map.get("nodes", []):
            if node.get("name") == name:
                node.update(details)
    if any(n.get("name") == name for n in load_user_map(user_id).get("nodes", [])):
        update_user_map(user_id, merge)
    return jsonify(details)


@app.route("/api/preview")
def api_preview():
    """A fresh Deezer preview URL for one track (by deezer_id, or artist + title)."""
    if not _current_user_id():
        return jsonify({"error": "Not authenticated"}), 401
    url = resolve_preview(request.args.get("deezer_id"), request.args.get("artist", ""),
                          request.args.get("title", ""))
    return jsonify({"preview_url": url})


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "universal-map"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=False)
