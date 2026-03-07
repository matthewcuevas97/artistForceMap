import os
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

# Load environment variables from .env at import time
load_dotenv()

# Scopes required to read the user's listening history
SCOPES = "user-top-read user-read-recently-played playlist-modify-private playlist-modify-public"


def get_spotify_oauth():
    """
    Build and return a SpotifyOAuth object using credentials from .env.

    The object handles the OAuth 2.0 authorization code flow, including
    generating the authorization URL and exchanging codes for tokens.
    """
    return SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
        scope=SCOPES,
    )


def get_token(code):
    """
    Exchange an authorization code for an access token.

    Args:
        code (str): The authorization code returned by Spotify's callback.

    Returns:
        dict: Token info dict containing access_token, refresh_token, etc.
    """
    sp_oauth = get_spotify_oauth()
    token_dict = sp_oauth.get_access_token(code)
    return token_dict
