import copy
import os

import spotipy
from flask import Flask, jsonify, render_template, redirect, request, session
from spotipy.exceptions import SpotifyException

from data.graph_builder import build_edges, build_genre_edges, enrich_with_spotify, load_static_graph, normalize_listeners
from spotify.auth import get_spotify_oauth, get_token
from spotify.fetch import get_top_artists

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

# Load static graph once at startup; deep-copied per request so mutations don't bleed over
try:
    _static_nodes = load_static_graph()
except Exception as e:
    _static_nodes = []
    app.logger.error("Failed to load graph_static.json: %s", e)

# Edge cache keyed by threshold — edges are deterministic and never mutated
_edge_cache: dict = {}


def _get_edges(nodes, threshold):
    if threshold not in _edge_cache:
        raw = build_edges(nodes, threshold) + build_genre_edges(nodes)
        seen = set()
        deduped = []
        for e in raw:
            key = (min(e["source"], e["target"]), max(e["source"], e["target"]))
            if key not in seen:
                seen.add(key)
                deduped.append(e)
        _edge_cache[threshold] = deduped
    return _edge_cache[threshold]


# Fields used internally during graph building; not needed by the D3 frontend
_INTERNAL_FIELDS = {"similar_artists", "tags", "lastfm_artists", "direct_score", "derived_score"}


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
    return redirect("/")


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
    if not _static_nodes:
        return jsonify({"error": "Graph data unavailable"}), 503

    threshold = request.args.get("threshold", 0.1, type=float)
    nodes = copy.deepcopy(_static_nodes)
    edges = _get_edges(_static_nodes, threshold)

    # Use listener count as baseline score for all nodes, then let Spotify override
    normalize_listeners(nodes)

    if "token" in session:
        try:
            sp = spotipy.Spotify(auth=session["token"]["access_token"])
            top_artists = get_top_artists(sp)
            enrich_with_spotify(nodes, top_artists)
        except SpotifyException:
            # Token likely expired; clear session and serve listener-normalized scores
            session.pop("token", None)

    for node in nodes:
        for field in _INTERNAL_FIELDS:
            node.pop(field, None)

    return jsonify({"nodes": nodes, "edges": edges})


# Warm the default-threshold edge cache at startup
if _static_nodes:
    _get_edges(_static_nodes, 0.1)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=True)
