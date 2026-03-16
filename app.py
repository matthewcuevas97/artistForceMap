import json
import os
import re
import time
import spotipy
import requests
from datetime import datetime
from flask import Flask, jsonify, render_template, redirect, request, session
from spotipy.exceptions import SpotifyException

from data.graph_builder import enrich_with_scores, normalize_listeners
from spotify.auth import get_spotify_oauth, get_token
from spotify.fetch import get_top_artists

app = Flask(__name__)
secret_key = os.getenv("FLASK_SECRET_KEY")
if not secret_key:
    raise RuntimeError("FLASK_SECRET_KEY environment variable is not set")
app.secret_key = secret_key

sp_oauth = get_spotify_oauth()

THRESHOLDS = [0.30, 0.32, 0.34, 0.36, 0.38, 0.40]

DEEZER_SEARCH = "https://api.deezer.com/search"


def _norm_simple(s):
    return re.sub(r'[^\w]', '', s.lower())


def get_valid_spotify_token():
    """Return a valid Spotify access token from the session, refreshing if needed.

    Returns the access token string, or None if the session has no token or
    the refresh attempt fails.
    """
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


def refresh_track_previews(tracks, artist_names):
    refreshed = []
    for track in tracks:
        track = dict(track)
        track["preview_url"] = ""
        if not track.get("album_art"):
            track["album_art"] = ""
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
                        if not track["album_art"]:
                            album = r.get("album", {})
                            track["album_art"] = album.get("cover_big") or album.get("cover_medium") or album.get("cover") or ""
                        break
                if not track["preview_url"] and results:
                    track["preview_url"] = results[0].get("preview", "")
                    if not track["album_art"]:
                        album = results[0].get("album", {})
                        track["album_art"] = album.get("cover_big") or album.get("cover_medium") or album.get("cover") or ""
                if track["preview_url"]:
                    break
        except Exception:
            track["preview_url"] = ""
        refreshed.append(track)
    return refreshed


# Load graph once at startup
_nodes: list = []
_links: list = []
_nodes_by_name: dict = {}

try:
    _static_path = os.path.join(os.path.dirname(__file__), "data", "graph_static.json")
    with open(_static_path) as _f:
        _data = json.load(_f)
    _nodes = _data.get("nodes", [])
    _links = _data.get("links", [])
    _nodes_by_name = {n["name"]: n for n in _nodes}
except Exception as e:
    app.logger.error("Failed to load graph_static.json: %s", e)


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
    session["spotify_token"] = token["access_token"]
    session["spotify_refresh_token"] = token.get("refresh_token")
    session["spotify_token_expires_at"] = token["expires_at"]
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
    session.pop("spotify_token", None)
    session.pop("spotify_refresh_token", None)
    session.pop("spotify_token_expires_at", None)
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
    session.pop("spotify_token", None)
    session.pop("spotify_refresh_token", None)
    session.pop("spotify_token_expires_at", None)
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

    Nodes and links are served from immutable module-level caches. Per-request
    scores are tracked in a separate dict and merged into each node at
    serialization time, leaving the cached node objects untouched.

    Returns JSON:
        nodes: list of artist dicts (name, genre, listeners, score, day, weekend, stage)
        edges_by_level: dict with arrays of edges at different threshold levels
    """
    if not _nodes:
        return jsonify({"error": "Graph data unavailable"}), 503

    scores = {node["name"]: {"score": 0, "direct_score": 0, "derived_score": 0} for node in _nodes}

    # Use listener count as baseline score for all nodes, then let auth source override
    normalize_listeners(_nodes, scores)

    lastfm_user = session.get("lastfm_user")
    spotify_token = get_valid_spotify_token()

    if lastfm_user:
        from lastfm.fetch import get_top_artists as lastfm_top
        top = lastfm_top(lastfm_user)
        if top:
            enrich_with_scores(_nodes, top, scores)
    elif spotify_token:
        try:
            sp = spotipy.Spotify(auth=spotify_token)
            top_artists = get_top_artists(sp)
            enrich_with_scores(_nodes, top_artists, scores)
        except SpotifyException:
            pass

    user_seeds = [
        name for name, s in scores.items()
        if s["direct_score"] > 0 or s["derived_score"] > 0
    ]

    nodes_out = [
        {k: v for k, v in {**node, **scores.get(node["name"], {})}.items()
         if k not in _INTERNAL_FIELDS}
        for node in _nodes
    ]

    # Convert links to include weight (inverse of pass) and organize by threshold
    # Higher pass number = lower weight (earlier passes are stronger connections)
    # Threshold filters by pass: lower threshold shows more edges (including weaker passes)
    processed_links = []
    for link in _links:
        processed_link = {
            "source": link["source"],
            "target": link["target"],
            "pass": link.get("pass", 1),
            "weight": 1.0 / link.get("pass", 1),  # Inverse of pass: pass 1 -> weight 1.0, pass 5 -> weight 0.2
            "type": "similarity"  # Default edge type
        }
        processed_links.append(processed_link)

    # Organize edges by threshold: lower threshold (more lenient) shows more edges
    # Threshold maps to maximum pass to include:
    # 0.30: all (pass 1-5)  0.32: pass 1-4  0.34: pass 1-3  0.36: pass 1-2  0.38+: pass 1 only
    pass_cutoffs = {
        "0.30": 5,  # All edges
        "0.32": 4,  # Exclude hail-mary (pass 5)
        "0.34": 3,  # Exclude adaptive floor + hail-mary
        "0.36": 2,  # Only gold standard + base RBO
        "0.38": 1,  # Only gold standard
        "0.40": 1,  # Same as 0.38
    }

    edges_by_level = {}
    for threshold, max_pass in pass_cutoffs.items():
        edges_by_level[threshold] = [
            edge for edge in processed_links if edge["pass"] <= max_pass
        ]

    return jsonify({"nodes": nodes_out, "edges_by_level": edges_by_level, "user_seeds": user_seeds})


@app.route("/api/artist/<name>")
def api_artist(name):
    node = _nodes_by_name.get(name)
    if node is None:
        return jsonify({"error": "Not found"}), 404
    result = {k: v for k, v in node.items() if k not in _INTERNAL_FIELDS}
    return jsonify(result)


@app.route("/api/artist/<name>/tracks")
def api_artist_tracks(name):
    node = _nodes_by_name.get(name)
    if node is None:
        return jsonify({"error": "Not found"}), 404
    artist_names = node.get("lastfm_artists") or [name]
    tracks = refresh_track_previews(node.get("top_tracks", []), artist_names)
    return jsonify({"tracks": tracks})


@app.route("/api/spotify/create-playlist", methods=["POST"])
def api_spotify_create_playlist():
    token = get_valid_spotify_token()
    if not token:
        return jsonify({"error": "spotify_auth_required"}), 401

    data = request.get_json(force=True) or {}
    tracks = data.get("tracks", [])

    try:
        sp = spotipy.Spotify(auth=token)
        name = f"Coachella 2026 · {datetime.now().strftime('%b %-d')}"
        pl = sp.current_user_playlist_create(name, public=False)
        playlist_id = pl["id"]

        uris = []
        for track in tracks:
            artist = track.get("artist", "")
            name = track.get("name", "")
            results = sp.search(q=f"artist:{artist} track:{name}", type="track", limit=1)
            items = results.get("tracks", {}).get("items", [])
            if items:
                uris.append(items[0]["uri"])

        for i in range(0, len(uris), 100):
            sp.playlist_add_items(playlist_id, uris[i:i + 100])

        return jsonify({
            "ok": True,
            "playlist_url": f"https://open.spotify.com/playlist/{playlist_id}"
        })
    except SpotifyException as e:
        return jsonify({"ok": False, "error": str(e)}), 400


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=False)
