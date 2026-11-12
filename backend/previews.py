"""
Resolve Deezer 30-second preview URLs at play time (BUG-10).

Deezer preview URLs are signed (`hdnea=exp=...`) and expire after roughly 15
minutes, so they must never be cached alongside 90-day artist data. Tracks keep
their Deezer id; this module fetches a fresh URL when the user presses play and
memoises it briefly.
"""

import re
import threading
import time
from typing import Optional

import requests

DEEZER_TRACK = "https://api.deezer.com/track/{}"
DEEZER_SEARCH = "https://api.deezer.com/search"
PREVIEW_TTL = 10 * 60  # comfortably below Deezer's ~15 min signature lifetime
_MAX_ENTRIES = 2000

_cache = {}
_lock = threading.Lock()


def _norm(s: str) -> str:
    return re.sub(r"[^\w]", "", (s or "").lower())


def _remember(key, url):
    with _lock:
        if len(_cache) >= _MAX_ENTRIES:
            _cache.clear()
        _cache[key] = (time.time() + PREVIEW_TTL, url)


def _recall(key):
    with _lock:
        hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit
    return None


def _by_id(deezer_id) -> Optional[str]:
    data = requests.get(DEEZER_TRACK.format(int(deezer_id)), timeout=5).json()
    return data.get("preview") or None


def _by_search(artist: str, title: str) -> Optional[str]:
    q = f'artist:"{artist}" track:"{title}"'
    results = requests.get(DEEZER_SEARCH, params={"q": q, "limit": 5}, timeout=5).json().get("data", [])
    want = _norm(title)
    for r in results:
        got = _norm(r.get("title", ""))
        if got and (got == want or want in got or got in want) and r.get("preview"):
            return r["preview"]
    return next((r["preview"] for r in results if r.get("preview")), None)


def resolve_preview(deezer_id=None, artist: str = "", title: str = "") -> Optional[str]:
    """A fresh preview URL for a track, or None if Deezer has none / is unreachable."""
    if deezer_id:
        key = ("id", str(deezer_id))
    elif artist and title:
        key = ("q", _norm(artist), _norm(title))
    else:
        return None
    hit = _recall(key)
    if hit:
        return hit[1]
    try:
        url = _by_id(deezer_id) if deezer_id else _by_search(artist, title)
    except (requests.RequestException, ValueError, TypeError):
        return None  # transient: don't remember the miss
    _remember(key, url)
    return url


def clear():
    with _lock:
        _cache.clear()
