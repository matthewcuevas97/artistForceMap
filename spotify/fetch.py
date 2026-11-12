def get_top_artists(sp):
    """
    Fetch the current user's top artists from Spotify.

    Args:
        sp: An authenticated Spotipy client instance.

    Returns:
        list[dict]: Each dict has keys:
            name        - artist display name (str)
            spotify_id  - Spotify artist ID (str)
            score       - rank-based affinity score in (0, 1]:
                          1st = 1.0, last of n = 1/n (never 0)
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
            "score": 1 - i / num_artists
        })
    return to_return