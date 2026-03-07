import spotipy

def get_top_artists(sp):
    """
    Fetch the current user's top artists from Spotify.

    Args:
        sp: An authenticated Spotipy client instance.

    Returns:
        list[dict]: Each dict has keys:
            name        - artist display name (str)
            spotify_id  - Spotify artist ID (str)
            score       - normalized affinity score, 0.0-1.0 (float)
                          based on rank position (1st = 1.0, last = 0.0)
    """
    top_artists = sp.current_user_top_artists(limit=50)
    to_return = []
    num_artists = len(top_artists["items"])
    for i, artist in enumerate(top_artists["items"]):
        spotify_id = artist["id"]
        artist_name = artist["name"]
        to_return.append({
            "name": artist_name,
            "spotify_id": spotify_id,
            "score": 1.0 if num_artists == 1 else 1 - i / (num_artists - 1)
        })
    return to_return