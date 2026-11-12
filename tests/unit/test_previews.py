"""backend/previews.py — preview URLs resolved at play time (BUG-10)."""

import requests

from backend import previews

TRACK = "https://api.deezer.com/track/42"


def test_by_id(http):
    http.add("GET", TRACK, json={"preview": "https://cdn/p.mp3"})
    assert previews.resolve_preview(42) == "https://cdn/p.mp3"


def test_search_fallback_prefers_title_match(http):
    http.add("GET", previews.DEEZER_SEARCH, json={"data": [
        {"title": "Other Song", "preview": "https://cdn/other.mp3"},
        {"title": "Hit (Remastered)", "preview": "https://cdn/hit.mp3"}]})
    assert previews.resolve_preview(None, "Band", "Hit") == "https://cdn/hit.mp3"


def test_memoised_until_ttl(http, monkeypatch):
    http.add("GET", TRACK, json={"preview": "https://cdn/1.mp3"})
    http.add("GET", TRACK, json={"preview": "https://cdn/2.mp3"})
    assert previews.resolve_preview(42) == "https://cdn/1.mp3"
    assert previews.resolve_preview(42) == "https://cdn/1.mp3"
    real = previews.time.time
    monkeypatch.setattr(previews.time, "time", lambda: real() + previews.PREVIEW_TTL + 1)
    assert previews.resolve_preview(42) == "https://cdn/2.mp3"


def test_network_error_returns_none_and_is_not_remembered(http):
    http.add("GET", TRACK, body=requests.ConnectionError("down"))
    http.add("GET", TRACK, json={"preview": "https://cdn/p.mp3"})
    assert previews.resolve_preview(42) is None
    assert previews.resolve_preview(42) == "https://cdn/p.mp3"


def test_nothing_to_resolve():
    assert previews.resolve_preview(None, "", "") is None
