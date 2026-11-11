import os
import secrets

from dotenv import load_dotenv
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError

# Load environment variables from .env at import time
load_dotenv()

# Scopes required to read the user's listening history
SCOPES = "user-top-read user-read-recently-played playlist-modify-private playlist-modify-public"

_STATE_KEY = "spotify_oauth_state"


class OAuthStateError(Exception):
    """The callback's `state` is missing or doesn't match the one issued by /login."""


def get_spotify_oauth(state=None):
    """
    Build a SpotifyOAuth object using credentials from .env.

    Tokens are kept per user in the Flask session by the apps, so spotipy must
    never persist them itself: a MemoryCacheHandler on a fresh object per call
    means nothing is shared between requests or users. (spotipy's default is a
    `.cache` file in the CWD, which handed every user the first user's token.)
    """
    return SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
        scope=SCOPES,
        state=state,
        cache_handler=MemoryCacheHandler(),
        open_browser=False,
    )


def get_authorize_url(session):
    """Issue a fresh CSRF `state`, remember it in the session, and return the authorize URL."""
    state = secrets.token_urlsafe(16)
    session[_STATE_KEY] = state
    return get_spotify_oauth(state=state).get_authorize_url()


def verify_state(session, returned_state):
    """Consume the session's pending state and check it against the callback's. Raises OAuthStateError."""
    expected = session.pop(_STATE_KEY, None)
    if not expected or not returned_state or not secrets.compare_digest(expected, returned_state):
        raise OAuthStateError("OAuth state mismatch")


def get_token(code):
    """
    Exchange an authorization code for a token dict (access_token, refresh_token, expires_at, ...).

    Always performs the exchange (check_cache=False). Raises SpotifyOauthError on an
    invalid or expired code.
    """
    return get_spotify_oauth().get_access_token(code, as_dict=True, check_cache=False)


def refresh_token(refresh_token_value):
    """Exchange a refresh token for a new token dict."""
    return get_spotify_oauth().refresh_access_token(refresh_token_value)


__all__ = [
    "SCOPES", "OAuthStateError", "SpotifyOauthError",
    "get_spotify_oauth", "get_authorize_url", "verify_state", "get_token", "refresh_token",
]
