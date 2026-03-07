import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("LASTFM_API_KEY")
BASE_URL = "https://ws.audioscrobbler.com/2.0/"


def get_similar_artists(artist_name, limit=50, threshold=0.1):
    params = {
        "method": "artist.getSimilar",
        "artist": artist_name,
        "limit": limit,
        "api_key": API_KEY,
        "format": "json",
    }
    response = requests.get(BASE_URL, params=params)
    data = response.json()

    if "error" in data:
        return []

    artists = data.get("similarartists", {}).get("artist", [])
    return [
        {"name": a["name"], "match": float(a["match"])}
        for a in artists if float(a["match"]) > threshold
    ]


def get_artist_info(artist_name):
    params = {
        "method": "artist.getInfo",
        "artist": artist_name,
        "api_key": API_KEY,
        "format": "json",
    }
    response = requests.get(BASE_URL, params=params)
    data = response.json()

    if "error" in data:
        return None

    artist = data.get("artist", {})
    listeners = int(artist.get("stats", {}).get("listeners", 0))
    tags = [t["name"].lower() for t in artist.get("tags", {}).get("tag", [])[:5]]
    return {
        "name": artist.get("name", artist_name),
        "listeners": listeners,
        "tags": tags,
    }
