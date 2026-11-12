"""
Session setup, Spotify OAuth and Last.fm login shared by both Flask apps.

    from web_auth import configure_session, create_auth_blueprint, get_valid_spotify_token
    configure_session(app)
    app.register_blueprint(create_auth_blueprint(lambda user: bool(lastfm_top(user))))

Routes: GET /login, GET /callback, POST /api/spotify/logout,
        POST /api/lastfm/login, POST /api/lastfm/logout.

Session keys: spotify_token, spotify_refresh_token, spotify_token_expires_at,
spotify_display_name, spotify_id, lastfm_user. Logging in with one provider
logs out of the other.
"""

import os
import time
from typing import Callable, Optional

import spotipy
from flask import Blueprint, jsonify, redirect, request, session
from spotipy.exceptions import SpotifyException

from spotify.auth import (OAuthStateError, SpotifyOauthError, get_authorize_url, get_token,
                          refresh_token as spotify_refresh_token, verify_state)

SPOTIFY_SESSION_KEYS = ("spotify_token", "spotify_refresh_token", "spotify_token_expires_at",
                        "spotify_display_name", "spotify_id")


def configure_session(app) -> None:
    """Require FLASK_SECRET_KEY and harden the session cookie (it carries Spotify tokens)."""
    secret_key = os.getenv("FLASK_SECRET_KEY")
    if not secret_key:
        raise RuntimeError("FLASK_SECRET_KEY environment variable is not set")
    app.secret_key = secret_key
    # Signed, not encrypted: keep it away from JS and cross-site requests. Lax still sends
    # it on the top-level redirect back from Spotify. Set SESSION_COOKIE_SECURE=1 over HTTPS.
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "").lower() in ("1", "true", "yes"),
    )


def _clear_spotify():
    for key in SPOTIFY_SESSION_KEYS:
        session.pop(key, None)


def get_valid_spotify_token() -> Optional[str]:
    """The session's Spotify access token, refreshed if it expires within a minute; else None."""
    token = session.get("spotify_token")
    if not token:
        return None
    if time.time() > session.get("spotify_token_expires_at", 0) - 60:
        refresh = session.get("spotify_refresh_token")
        if not refresh:
            return None
        try:
            new_token = spotify_refresh_token(refresh)
        except Exception:
            return None
        session["spotify_token"] = new_token["access_token"]
        session["spotify_token_expires_at"] = new_token["expires_at"]
        if new_token.get("refresh_token"):
            session["spotify_refresh_token"] = new_token["refresh_token"]
        return new_token["access_token"]
    return token


def create_auth_blueprint(lastfm_user_exists: Callable[[str], bool]) -> Blueprint:
    """
    Auth routes for one app. `lastfm_user_exists(username)` decides whether a Last.fm
    login is accepted; pass a lambda that looks the fetcher up at call time so tests can
    monkeypatch it on the app module.
    """
    bp = Blueprint("auth", __name__)

    @bp.route("/login")
    def login():
        """Redirect to Spotify's authorize page with a fresh single-use CSRF state."""
        return redirect(get_authorize_url(session))

    @bp.route("/callback")
    def callback():
        """Spotify OAuth callback: verify state, exchange the code, store tokens in the session."""
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
            user = spotipy.Spotify(auth=token["access_token"]).current_user()
            session["spotify_display_name"] = user.get("display_name") or user.get("id", "")
            session["spotify_id"] = user.get("id")
        except SpotifyException:
            pass
        return redirect("/")

    @bp.route("/api/spotify/logout", methods=["POST"])
    def spotify_logout():
        _clear_spotify()
        return jsonify({"ok": True})

    @bp.route("/api/lastfm/login", methods=["POST"])
    def lastfm_login():
        username = ((request.get_json(silent=True) or {}).get("username") or "").strip()
        if not username or not lastfm_user_exists(username):
            return jsonify({"ok": False, "error": "User not found"}), 400
        session["lastfm_user"] = username
        _clear_spotify()
        return jsonify({"ok": True})

    @bp.route("/api/lastfm/logout", methods=["POST"])
    def lastfm_logout():
        session.pop("lastfm_user", None)
        return jsonify({"ok": True})

    return bp
