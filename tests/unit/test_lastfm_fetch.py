"""lastfm/fetch.py response parsing and failure handling."""

import pytest
import requests

from lastfm import fetch
from tests.conftest import LASTFM_URL, lastfm_top_artists_payload


def test_top_artists_rank_scores(http):
    http.add("GET", LASTFM_URL, json=lastfm_top_artists_payload(["A", "B", "C"]))
    out = fetch.get_top_artists("user", limit=3)
    assert [a["name"] for a in out] == ["A", "B", "C"]
    assert [a["score"] for a in out] == pytest.approx([1.0, 2 / 3, 1 / 3])


def test_top_artists_unknown_user_returns_empty(http):
    http.add("GET", LASTFM_URL, json={"error": 6, "message": "User not found"})
    assert fetch.get_top_artists("nobody") == []


def test_top_artists_network_error_returns_empty(http):
    http.add("GET", LASTFM_URL, body=requests.ConnectionError("down"))
    assert fetch.get_top_artists("user") == []


def test_top_artists_scored_by_number_returned_not_limit(http):
    """BUG-31 regression: scores were normalized by `limit`, so a short history was squashed near 1.0."""
    http.add("GET", LASTFM_URL, json=lastfm_top_artists_payload(["A", "B"]))
    out = fetch.get_top_artists("user", limit=100)
    assert [a["score"] for a in out] == [1.0, 0.5]


def test_spotify_and_lastfm_rank_scores_agree(http):
    from unittest.mock import Mock
    from spotify.fetch import get_top_artists as spotify_top
    http.add("GET", LASTFM_URL, json=lastfm_top_artists_payload(["A", "B", "C", "D"]))
    sp = Mock()
    sp.current_user_top_artists.return_value = {"items": [{"id": c, "name": c} for c in "ABCD"]}
    assert [a["score"] for a in spotify_top(sp)] == [a["score"] for a in fetch.get_top_artists("u")]
    assert min(a["score"] for a in spotify_top(sp)) > 0


def test_similar_artists_threshold(http):
    http.add("GET", LASTFM_URL, json={"similarartists": {"artist": [
        {"name": "Close", "match": "0.9"}, {"name": "Far", "match": "0.01"}]}})
    assert fetch.get_similar_artists("X", threshold=0.1) == [{"name": "Close", "match": 0.9}]


def test_top_tags_lowercased(http):
    http.add("GET", LASTFM_URL, json={"toptags": {"tag": [{"name": "Hip-Hop"}, {"name": "RAP"}]}})
    assert fetch.get_artist_top_tags("X") == ["hip-hop", "rap"]


def test_image_and_bio_strip_html_and_pick_largest(http):
    http.add("GET", LASTFM_URL, json={"artist": {
        "image": [{"#text": "small.png"}, {"#text": "large.png"}, {"#text": ""}],
        "bio": {"summary": "<b>Great</b> band. <a href=\"https://last.fm\">Read more on Last.fm</a>"}}})
    img, bio = fetch.get_artist_image_and_bio("X")
    assert img == "large.png"
    assert bio == "Great band."


@pytest.mark.xfail(strict=True, raises=(AssertionError, requests.ConnectionError), reason="BUG-32: get_artist_info has no timeout and no exception "
                   "handling, unlike its sibling functions")
def test_artist_info_network_error_is_handled(http):
    http.add("GET", LASTFM_URL, body=requests.ConnectionError("down"))
    assert fetch.get_artist_info("X") is None
