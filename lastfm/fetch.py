import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("LASTFM_API_KEY")
BASE_URL = "https://ws.audioscrobbler.com/2.0/"

# Last.fm error 6 = "artist/user not found": a genuine empty answer, safe to cache.
# Anything else (rate limit 29, service errors, network failures) is transient.
LASTFM_NOT_FOUND = 6


class _Transient(Exception):
    pass


def _artist_call(method, artist_name, **extra):
    """
    GET an artist.* method. Returns the JSON dict, {} for "artist not found",
    or raises _Transient for network/rate-limit/service errors.
    """
    params = {"method": method, "artist": artist_name, "api_key": API_KEY, "format": "json", **extra}
    try:
        data = requests.get(BASE_URL, params=params, timeout=10).json()
    except Exception as exc:
        raise _Transient(str(exc))
    if "error" in data:
        if data.get("error") == LASTFM_NOT_FOUND:
            return {}
        raise _Transient(data.get("message", "Last.fm error"))
    return data


def get_similar_artists(artist_name, limit=50, threshold=0.1):
    """
    [{name, match}] above `threshold`; [] if Last.fm has none.
    None on a transient failure, so callers can avoid caching it.
    """
    try:
        data = _artist_call("artist.getSimilar", artist_name, limit=limit)
    except _Transient:
        return None
    artists = data.get("similarartists", {}).get("artist", [])
    return [
        {"name": a["name"], "match": float(a["match"])}
        for a in artists if float(a["match"]) > threshold
    ]


def get_artist_top_tags(artist_name, limit=100):
    """Lower-cased tag names; [] if none. None on a transient failure (don't cache it)."""
    try:
        data = _artist_call("artist.getTopTags", artist_name, limit=limit)
    except _Transient:
        return None
    tags = data.get("toptags", {}).get("tag", [])
    return [t["name"].lower() for t in tags]


def get_artist_info(artist_name):
    """{name, listeners}, or None if not found or on any failure."""
    try:
        data = _artist_call("artist.getInfo", artist_name)
    except _Transient:
        return None
    if not data:
        return None

    artist = data.get("artist", {})
    listeners = int(artist.get("stats", {}).get("listeners", 0))
    return {
        "name": artist.get("name", artist_name),
        "listeners": listeners,
    }


def get_artist_image_and_bio(artist_name):
    """Returns (image_url, bio) — either may be None (also on any failure)."""
    try:
        data = _artist_call("artist.getInfo", artist_name)
    except _Transient:
        return None, None
    if not data:
        return None, None

    artist = data.get("artist", {})

    # Largest image: Last.fm returns images ordered smallest → largest
    image_url = None
    for img in reversed(artist.get("image", [])):
        url = img.get("#text", "").strip()
        if url:
            image_url = url
            break

    # Bio: strip the trailing <a href=...> read-more link, then all HTML, truncate
    bio = None
    summary = artist.get("bio", {}).get("summary", "").strip()
    if summary:
        cleaned = re.sub(r'\s*<a\s[^>]*>[^<]*</a>', '', summary)
        cleaned = re.sub(r'<[^>]+>', '', cleaned).strip()
        bio = trim_bio(cleaned, BIO_LIMIT) if cleaned else None

    return image_url, bio


BIO_LIMIT = 300
_SENTENCE_END = re.compile(r'[.!?]["\u201d\u2019)]?(?=\s)|\n')


def trim_bio(text, limit=BIO_LIMIT):
    """
    Shorten `text` to at most `limit` characters without cutting mid-sentence or mid-word.

    Prefers the last sentence end (or line break) in the second half of the window; else
    cuts at the last word boundary and appends an ellipsis. Text within the limit is
    returned unchanged (whitespace-trimmed).
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    window = text[:limit + 1]
    ends = [m.end() for m in _SENTENCE_END.finditer(window) if m.end() >= limit // 2]
    if ends:
        return window[:ends[-1]].strip()
    cut = window[:limit - 1].rsplit(None, 1)[0] if " " in window[:limit - 1] else window[:limit - 1]
    return cut.rstrip(" ,;:-\u2013\u2014") + "\u2026"


def get_top_artists(username, limit=100):
    """
    Fetch user's top artists from Last.fm.
    Returns list of {name, score} dicts sorted by rank,
    same format as spotify/fetch.py get_top_artists().
    Score: rank 1 = 1.0, last of n returned = 1/n (never 0), linear.
    """
    params = {
        "method": "user.getTopArtists",
        "user": username,
        "limit": limit,
        "period": "6month",
        "api_key": API_KEY,
        "format": "json",
    }
    try:
        response = requests.get(BASE_URL, params=params, timeout=10)
        data = response.json()
        if "error" in data:
            return []
        artists = data.get("topartists", {}).get("artist", [])
        result = []
        n = len(artists)
        for i, a in enumerate(artists):
            result.append({"name": a["name"], "score": 1 - i / n})
        return result
    except Exception:
        return []


def get_top_tracks(artist_name, limit=10):
    """Returns a list of track name strings (up to `limit`)."""
    params = {
        "method": "artist.getTopTracks",
        "artist": artist_name,
        "limit": limit,
        "api_key": API_KEY,
        "format": "json",
    }
    response = requests.get(BASE_URL, params=params, timeout=10)
    data = response.json()

    if "error" in data:
        return []

    tracks = data.get("toptracks", {}).get("track", [])
    return [t["name"] for t in tracks]


def get_artist_image_from_deezer(artist_name):
    """Fetch artist image from Deezer as fallback for Last.fm."""
    try:
        resp = requests.get(
            "https://api.deezer.com/search/artist",
            params={"q": artist_name, "limit": 1},
            timeout=5
        )
        data = resp.json()
        results = data.get("data", [])

        if results:
            artist = results[0]
            # Use the largest available image
            return artist.get("picture_xl") or artist.get("picture_big") or artist.get("picture_medium")
    except Exception:
        pass
    return None
