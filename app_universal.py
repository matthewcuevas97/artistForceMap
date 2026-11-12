"""
Universal map Flask app - infinite/expandable map based on user's initial nodes.
Mirrors the Coachella force map but dynamically generates nodes as the user explores.
"""

import json
import os
import time
import spotipy
from flask import Flask, jsonify, render_template, redirect, request, session, Response
import queue
import threading
from spotipy.exceptions import SpotifyException

from backend.user_data import load_user_map, update_user_map
from backend.pipeline import run_full_pipeline
from backend.progress import progress_sink
from backend.graph_init import SimilarUnavailable, expand_map, get_deezer_info, _derive_genre
from backend.cache import get_cached_artist, set_cached_artist
from backend.tag_enrichment import EnrichmentUnavailable, enrich_artist_with_lastfm
from backend.previews import resolve_preview
from spotify.auth import (OAuthStateError, SpotifyOauthError, get_authorize_url, get_token,
                          refresh_token as spotify_refresh_token, verify_state)
from lastfm.fetch import get_top_artists as lastfm_top

app = Flask(__name__)
secret_key = os.getenv("FLASK_SECRET_KEY")
if not secret_key:
    raise RuntimeError("FLASK_SECRET_KEY environment variable is not set")
app.secret_key = secret_key
# Session cookie carries Spotify tokens (signed, not encrypted): keep it away from JS and
# cross-site requests. Lax still sends it on the top-level redirect back from Spotify.
# Set SESSION_COOKIE_SECURE=1 when serving over HTTPS.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "").lower() in ("1", "true", "yes"),
)


DEEZER_SEARCH = "https://api.deezer.com/search"
LASTFM_API = "http://ws.audioscrobbler.com/2.0"


# ============================================================================
# Real-time Progress Streaming
# ============================================================================

# Idle seconds between SSE keepalive comments while the pipeline is still running.
# There is no overall deadline: a slow silent step (rate-limited API calls) is fine
# as long as the pipeline thread is alive (BUG-13).
SSE_KEEPALIVE_SECONDS = 15


def _sse(payload):
    return f"data: {json.dumps(payload)}\n\n"


def get_valid_spotify_token():
    """Return a valid Spotify access token, refreshing if needed."""
    token = session.get("spotify_token")
    if not token:
        return None
    expires_at = session.get("spotify_token_expires_at", 0)
    if time.time() > expires_at - 60:
        refresh_token = session.get("spotify_refresh_token")
        if not refresh_token:
            return None
        try:
            new_token = spotify_refresh_token(refresh_token)
            session["spotify_token"] = new_token["access_token"]
            session["spotify_token_expires_at"] = new_token["expires_at"]
            if new_token.get("refresh_token"):
                session["spotify_refresh_token"] = new_token["refresh_token"]
            return new_token["access_token"]
        except Exception:
            return None
    return token


# ============================================================================
# Routes
# ============================================================================

@app.route("/")
def index():
    """Render the main single-page application shell."""
    return render_template("index_universal.html")


# ============================================================================
# Authentication Routes
# ============================================================================

@app.route("/login")
def login():
    """Redirect the user to Spotify's OAuth authorization page."""
    return redirect(get_authorize_url(session))


@app.route("/callback")
def callback():
    """Handle the OAuth callback from Spotify."""
    try:
        verify_state(session, request.args.get("state"))
    except OAuthStateError:
        return "Login expired or was not started from this site. Please try again.", 400
    error = request.args.get("error")
    if error:
        return f"Authorization failed: {error}", 400
    code = request.args.get("code")
    if not code:
        return "Missing authorization code", 400
    try:
        token = get_token(code)
    except SpotifyOauthError:
        return "Spotify login failed (the code was invalid or expired). Please try again.", 400
    session["spotify_token"] = token["access_token"]
    session["spotify_refresh_token"] = token.get("refresh_token")
    session["spotify_token_expires_at"] = token["expires_at"]
    session.pop("lastfm_user", None)
    try:
        sp = spotipy.Spotify(auth=token["access_token"])
        user = sp.current_user()
        session["spotify_display_name"] = user.get("display_name") or user.get("id", "")
        session["spotify_id"] = user.get("id")
    except SpotifyException:
        pass
    return redirect("/")


@app.route("/api/spotify/logout", methods=["POST"])
def spotify_logout():
    """Logout from Spotify."""
    session.pop("spotify_token", None)
    session.pop("spotify_refresh_token", None)
    session.pop("spotify_token_expires_at", None)
    session.pop("spotify_display_name", None)
    session.pop("spotify_id", None)
    return jsonify({"ok": True})


@app.route("/api/lastfm/login", methods=["POST"])
def lastfm_login():
    """Login with Last.fm username."""
    data = request.get_json(force=True)
    username = (data or {}).get("username", "").strip()
    if not username:
        return jsonify({"ok": False, "error": "User not found"}), 400
    top = lastfm_top(username)
    if not top:
        return jsonify({"ok": False, "error": "User not found"}), 400
    session["lastfm_user"] = username
    session.pop("spotify_token", None)
    session.pop("spotify_refresh_token", None)
    session.pop("spotify_token_expires_at", None)
    session.pop("spotify_display_name", None)
    session.pop("spotify_id", None)
    return jsonify({"ok": True})


@app.route("/api/lastfm/logout", methods=["POST"])
def lastfm_logout():
    """Logout from Last.fm."""
    session.pop("lastfm_user", None)
    return jsonify({"ok": True})


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
