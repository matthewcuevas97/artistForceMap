"""
Flask API routes for the universal map prototype.
Exposes the user ingestion and map initialization pipeline.
"""

from flask import Blueprint, request, jsonify, session, redirect, url_for
import os

from backend.user_ingestion import login_spotify, login_lastfm
from backend.pipeline import run_full_pipeline, run_pipeline_step
from backend.user_data import load_user_db, load_user_map

# Create blueprint
api_bp = Blueprint("api", __name__, url_prefix="/api/proto")

# OAuth configuration
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "your_client_id")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8080/api/proto/auth/spotify/callback")


# ============================================================================
# Authentication Routes
# ============================================================================

@api_bp.route("/auth/spotify", methods=["POST"])
def auth_spotify():
    """
    Initiate Spotify OAuth login.
    Returns auth URL for user to visit.
    """
    try:
        from spotipy.oauth2 import SpotifyOAuth

        oauth = SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=os.getenv("SPOTIFY_CLIENT_SECRET", "your_client_secret"),
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope="user-top-read",
        )
        auth_url = oauth.get_authorize_url()
        session["oauth_state"] = oauth.get_cached_token()

        return jsonify({"auth_url": auth_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@api_bp.route("/auth/spotify/callback", methods=["GET"])
def auth_spotify_callback():
    """
    Handle Spotify OAuth callback.
    """
    try:
        code = request.args.get("code")
        if not code:
            return jsonify({"error": "No auth code"}), 400

        auth_data = login_spotify(code)
        session["user_id"] = auth_data["id"]
        session["auth_data"] = auth_data

        return redirect(f"/proto/pipeline?step=ingestion")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@api_bp.route("/auth/lastfm", methods=["POST"])
def auth_lastfm():
    """
    Initiate Last.fm login (username-based).
    """
    try:
        data = request.get_json()
        username = data.get("username", "").strip()

        if not username:
            return jsonify({"error": "Username required"}), 400

        auth_data = login_lastfm(username)
        session["user_id"] = auth_data["id"]
        session["auth_data"] = auth_data

        return jsonify({
            "status": "authenticated",
            "user_id": auth_data["id"],
            "next": "/proto/pipeline?step=ingestion",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ============================================================================
# Pipeline Routes
# ============================================================================

@api_bp.route("/pipeline/run", methods=["POST"])
def pipeline_run():
    """
    Run the full pipeline for the authenticated user.
    """
    try:
        auth_data = session.get("auth_data")
        if not auth_data:
            return jsonify({"error": "Not authenticated"}), 401

        result = run_full_pipeline(auth_data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/pipeline/step/<step>", methods=["POST"])
def pipeline_step(step: str):
    """
    Run a single pipeline step.
    Useful for re-running or debugging.

    Supported steps: enrichment, seed_selection, graph_init
    """
    try:
        user_id = session.get("user_id")
        if not user_id:
            return jsonify({"error": "Not authenticated"}), 401

        data = request.get_json() or {}
        kwargs = {
            "num_seeds": data.get("num_seeds", 5),
            "lambda_param": data.get("lambda_param", 0.7),
        }

        result = run_pipeline_step(user_id, step, **kwargs)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# Data Retrieval Routes
# ============================================================================

@api_bp.route("/user/<user_id>/db", methods=["GET"])
def get_user_db(user_id: str):
    """
    Get user database (enriched artist data).
    """
    try:
        user_db = load_user_db(user_id)
        return jsonify(user_db)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/user/<user_id>/map", methods=["GET"])
def get_user_map(user_id: str):
    """
    Get user's graph map (for frontend visualization).
    """
    try:
        user_map = load_user_map(user_id)
        return jsonify(user_map)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/user/<user_id>/status", methods=["GET"])
def get_user_status(user_id: str):
    """
    Get user's pipeline status.
    """
    try:
        user_db = load_user_db(user_id)
        user_map = load_user_map(user_id)

        status = {
            "user_id": user_id,
            "ingestion": bool(user_db.get("top_artists")),
            "enrichment": bool(user_db.get("all_artists")),
            "seed_selection": bool(user_db.get("seed_artists")),
            "graph_init": bool(user_map.get("nodes")),
        }

        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# Health Check
# ============================================================================

@api_bp.route("/health", methods=["GET"])
def health():
    """
    Health check endpoint.
    """
    return jsonify({"status": "ok", "service": "universal-map-proto"})
