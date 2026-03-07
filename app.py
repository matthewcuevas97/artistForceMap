import copy
import json
import os
import re
import spotipy
import requests
from flask import Flask, jsonify, render_template, redirect, request, session
from spotipy.exceptions import SpotifyException

from data.graph_builder import enrich_with_scores, normalize_listeners
from spotify.auth import get_spotify_oauth, get_token
from spotify.fetch import get_top_artists

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

THRESHOLDS = [0.05, 0.10, 0.20, 0.30, 0.50]

DEEZER_SEARCH = "https://api.deezer.com/search"


def _norm_simple(s):
    return re.sub(r'[^\w]', '', s.lower())


def refresh_track_previews(tracks, artist_names):
    refreshed = []
    for track in tracks:
        track = dict(track)
        track["preview_url"] = ""
        try:
            for artist_name in artist_names:
                q = f'artist:"{artist_name}" track:"{track["name"]}"'
                resp = requests.get(DEEZER_SEARCH,
                                    params={"q": q, "limit": 5},
                                    timeout=5)
                results = resp.json().get("data", [])
                for r in results:
                    r_title = _norm_simple(r.get("title", ""))
                    t_name  = _norm_simple(track["name"])
                    if r_title == t_name or t_name in r_title or r_title in t_name:
                        track["preview_url"] = r.get("preview", "")
                        break
                if not track["preview_url"] and results:
                    track["preview_url"] = results[0].get("preview", "")
                if track["preview_url"]:
                    break
        except Exception:
            track["preview_url"] = ""
        refreshed.append(track)
    return refreshed


# Load slim graph once at startup
_slim_nodes: list = []
_slim_edges: dict = {}

_slim_nodes_by_name: dict = {}
_static_nodes_by_name: dict = {}

try:
    _slim_path = os.path.join(os.path.dirname(__file__), "data", "graph_slim.json")
    with open(_slim_path) as _f:
        _slim_data = json.load(_f)
    _slim_nodes = _slim_data["nodes"]
    _slim_edges = _slim_data["edges"]
    _slim_nodes_by_name = {n["name"]: n for n in _slim_nodes}
except Exception as e:
    app.logger.error("Failed to load graph_slim.json: %s", e)

try:
    _static_path = os.path.join(os.path.dirname(__file__), "data", "graph_static.json")
    with open(_static_path) as _f:
        _static_data = json.load(_f)
    _static_nodes_by_name = {n["name"]: n for n in _static_data["nodes"]}
except Exception as e:
    app.logger.error("Failed to load graph_static.json: %s", e)


def _get_edges(threshold):
    snapped = min(THRESHOLDS, key=lambda t: abs(t - threshold))
    return _slim_edges.get(f"{snapped:.2f}", []), snapped


# Fields used internally during graph building; not needed by the D3 frontend
_INTERNAL_FIELDS = {"direct_score", "derived_score"}


@app.route("/")
def index():
    """Render the main single-page application shell."""
    return render_template("index.html")


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
    session["token"] = token
    session.pop("lastfm_user", None)
    try:
        sp = spotipy.Spotify(auth=token["access_token"])
        user = sp.current_user()
        session["spotify_display_name"] = user.get("display_name") or user.get("id", "")
    except SpotifyException:
        pass
    return redirect("/")


@app.route("/api/spotify/logout", methods=["POST"])
def spotify_logout():
    session.pop("token", None)
    session.pop("spotify_display_name", None)
    return jsonify({"ok": True})


@app.route("/api/lastfm/login", methods=["POST"])
def lastfm_login():
    from lastfm.fetch import get_top_artists as lastfm_top
    data = request.get_json(force=True)
    username = (data or {}).get("username", "").strip()
    if not username:
        return jsonify({"ok": False, "error": "User not found"}), 400
    top = lastfm_top(username)
    if not top:
        return jsonify({"ok": False, "error": "User not found"}), 400
    session["lastfm_user"] = username
    session.pop("token", None)
    session.pop("spotify_display_name", None)
    return jsonify({"ok": True})


@app.route("/api/lastfm/logout", methods=["POST"])
def lastfm_logout():
    session.pop("lastfm_user", None)
    return jsonify({"ok": True})


@app.route("/api/graph")
def api_graph():
    """
    Return pre-computed graph data enriched with the user's Spotify scores.

    Nodes and edges are computed from data/graph_static.json. Edges are
    cached after the first build. Nodes are deep-copied per request so
    score enrichment doesn't persist across requests.

    Returns JSON:
        nodes: list of artist dicts (name, genre, listeners, score, day, weekend, stage)
        edges: list of connections (source, target, weight, type)
    """
    if not _slim_nodes:
        return jsonify({"error": "Graph data unavailable"}), 503

    threshold = request.args.get("threshold", 0.1, type=float)
    nodes = copy.deepcopy(_slim_nodes)
    edges, snapped = _get_edges(threshold)

    # Use listener count as baseline score for all nodes, then let auth source override
    normalize_listeners(nodes)

    lastfm_user = session.get("lastfm_user")
    spotify_token = session.get("token")

    if lastfm_user:
        from lastfm.fetch import get_top_artists as lastfm_top
        top = lastfm_top(lastfm_user)
        if top:
            enrich_with_scores(nodes, top)
    elif spotify_token:
        try:
            sp = spotipy.Spotify(auth=spotify_token["access_token"])
            top_artists = get_top_artists(sp)
            enrich_with_scores(nodes, top_artists)
        except SpotifyException:
            # Token likely expired; clear session and serve listener-normalized scores
            session.pop("token", None)
            session.pop("spotify_display_name", None)

    for node in nodes:
        for field in _INTERNAL_FIELDS:
            node.pop(field, None)

    return jsonify({"nodes": nodes, "edges": edges, "threshold": snapped})


@app.route("/api/artist/<name>")
def api_artist(name):
    node = _slim_nodes_by_name.get(name)
    if node is None:
        return jsonify({"error": "Not found"}), 404
    result = {k: v for k, v in node.items() if k not in _INTERNAL_FIELDS}
    return jsonify(result)


@app.route("/api/artist/<name>/tracks")
def api_artist_tracks(name):
    node = _slim_nodes_by_name.get(name)
    if node is None:
        return jsonify({"error": "Not found"}), 404
    static_node  = _static_nodes_by_name.get(name, {})
    artist_names = static_node.get("lastfm_artists") or [name]
    tracks = refresh_track_previews(node.get("top_tracks", []), artist_names)
    return jsonify({"tracks": tracks})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=True)
