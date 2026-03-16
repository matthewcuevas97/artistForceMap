"""
Universal map Flask app - infinite/expandable map based on user's initial nodes.
Mirrors the Coachella force map but dynamically generates nodes as the user explores.
"""

import json
import os
import time
import spotipy
import requests
from datetime import datetime
from flask import Flask, jsonify, render_template, redirect, request, session, Response
import sys
import io
import queue
import threading
from contextlib import redirect_stdout
from spotipy.exceptions import SpotifyException

from backend.user_data import load_user_db, load_user_map, save_user_map
from backend.pipeline import run_full_pipeline
from spotify.auth import get_spotify_oauth, get_token
from spotify.fetch import get_top_artists
from lastfm.fetch import get_top_artists as lastfm_top

app = Flask(__name__)
secret_key = os.getenv("FLASK_SECRET_KEY")
if not secret_key:
    raise RuntimeError("FLASK_SECRET_KEY environment variable is not set")
app.secret_key = secret_key

sp_oauth = get_spotify_oauth()

DEEZER_SEARCH = "https://api.deezer.com/search"
LASTFM_API = "http://ws.audioscrobbler.com/2.0"


# ============================================================================
# Real-time Progress Streaming
# ============================================================================

class StreamingStringIO(io.StringIO):
    """StringIO that queues lines as they're written for real-time streaming."""
    def __init__(self, queue_obj=None):
        super().__init__()
        self.queue = queue_obj
        self.line_buffer = ""

    def write(self, s):
        super().write(s)
        if self.queue:
            self.line_buffer += s
            # Process complete lines
            while '\n' in self.line_buffer:
                line, self.line_buffer = self.line_buffer.split('\n', 1)
                if line.strip():
                    self.queue.put(('message', line.strip()))
        return len(s)


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
            new_token = sp_oauth.refresh_access_token(refresh_token)
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
    oauth = get_spotify_oauth()
    auth_url = oauth.get_authorize_url()
    return redirect(auth_url)


@app.route("/callback")
def callback():
    """Handle the OAuth callback from Spotify."""
    error = request.args.get("error")
    if error:
        return f"Authorization failed: {error}", 400
    code = request.args.get("code")
    if not code:
        return "Missing authorization code", 400
    token = get_token(code)
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
        """Run the pipeline in a thread, sending progress to queue."""
        try:
            streaming_output = StreamingStringIO(queue_obj=progress_queue)
            with redirect_stdout(streaming_output):
                run_full_pipeline(auth_data)
            progress_queue.put(('complete', None))
        except Exception as e:
            progress_queue.put(('error', str(e)))

    # Start pipeline in background thread
    thread = threading.Thread(target=run_pipeline_thread)
    thread.daemon = True
    thread.start()

    def generate_progress():
        """Generate SSE events from the progress queue."""
        try:
            while True:
                try:
                    msg_type, msg_data = progress_queue.get(timeout=30)
                except queue.Empty:
                    yield f"data: {json.dumps({'error': 'Pipeline timeout'})}\n\n"
                    break

                if msg_type == 'message':
                    yield f"data: {json.dumps({'message': msg_data})}\n\n"
                elif msg_type == 'error':
                    yield f"data: {json.dumps({'error': msg_data})}\n\n"
                    break
                elif msg_type == 'complete':
                    # Load the generated map
                    user_map = load_user_map(user_id)
                    yield f"data: {json.dumps({'complete': True, 'nodes': user_map.get('nodes', []), 'edges': user_map.get('edges', [])})}\n\n"
                    break
        except Exception as e:
            print(f"SSE error: {e}", file=sys.stderr)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(generate_progress(), mimetype="text/event-stream")


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


@app.route("/api/map/expand", methods=["POST"])
def map_expand():
    """
    Expand the map from a given artist node.
    Fetches similar artists and adds them to the graph.
    """
    user_id = session.get("spotify_id") or session.get("lastfm_user")
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json()
    artist_name = data.get("artist")
    if not artist_name:
        return jsonify({"error": "Artist name required"}), 400

    try:
        user_map = load_user_map(user_id)
        nodes = {node["name"]: node for node in user_map.get("nodes", [])}
        edges = user_map.get("edges", [])

        # Skip if already expanded
        if nodes.get(artist_name, {}).get("expanded"):
            return jsonify({
                "ok": True,
                "nodes": list(nodes.values()),
                "edges": edges,
                "message": "Already expanded"
            })

        spotify_token = get_valid_spotify_token()
        if spotify_token:
            sp = spotipy.Spotify(auth=spotify_token)
            try:
                # Search for artist and get recommendations
                results = sp.search(q=artist_name, type="artist", limit=5)
                artists = results.get("artists", {}).get("items", [])
                if not artists:
                    return jsonify({"error": "Artist not found"}), 404

                target_artist = artists[0]
                artist_id = target_artist["id"]

                # Get similar artists via recommendations
                recs = sp.recommendations(seed_artists=[artist_id], limit=20)
                rec_tracks = recs.get("tracks", [])

                # Add new artists and edges
                for track in rec_tracks[:10]:  # Limit to top 10 recommendations
                    for artist in track.get("artists", []):
                        new_artist_name = artist["name"]
                        if new_artist_name not in nodes:
                            nodes[new_artist_name] = {
                                "name": new_artist_name,
                                "popularity": artist.get("popularity", 50),
                                "id": artist["id"],
                                "genres": artist.get("genres", []),
                                "expanded": False
                            }
                        # Add edge
                        edge = {
                            "source": artist_name,
                            "target": new_artist_name,
                            "type": "similarity",
                            "weight": 0.8
                        }
                        # Avoid duplicate edges
                        if not any(e["source"] == edge["source"] and e["target"] == edge["target"]
                                  for e in edges):
                            edges.append(edge)

                # Mark as expanded
                if artist_name in nodes:
                    nodes[artist_name]["expanded"] = True

                # Save updated map
                user_map["nodes"] = list(nodes.values())
                user_map["edges"] = edges
                save_user_map(user_id, user_map)

                return jsonify({
                    "ok": True,
                    "nodes": list(nodes.values()),
                    "edges": edges
                })
            except SpotifyException as e:
                return jsonify({"error": f"Spotify error: {str(e)}"}), 400
        else:
            return jsonify({"error": "Spotify auth required"}), 401

    except Exception as e:
        app.logger.error(f"Map expand failed: {e}")
        return jsonify({"error": str(e)}), 500


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


@app.route("/api/artist/<name>")
def api_artist(name):
    """Get metadata for an artist."""
    spotify_token = get_valid_spotify_token()
    if not spotify_token:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        sp = spotipy.Spotify(auth=spotify_token)
        results = sp.search(q=name, type="artist", limit=1)
        artists = results.get("artists", {}).get("items", [])
        if not artists:
            return jsonify({"error": "Not found"}), 404

        artist = artists[0]
        return jsonify({
            "name": artist["name"],
            "id": artist["id"],
            "popularity": artist.get("popularity", 0),
            "genres": artist.get("genres", []),
            "followers": artist.get("followers", {}).get("total", 0),
            "images": artist.get("images", []),
            "external_urls": artist.get("external_urls", {})
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "universal-map"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=False)
