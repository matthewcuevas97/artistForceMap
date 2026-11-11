"""lastfm/fetch.py response parsing and failure handling."""

import pytest
import requests

from lastfm import fetch
from tests.conftest import LASTFM_URL, lastfm_top_artists_payload


def test_top_artists_rank_scores(http):
    http.add("GET", LASTFM_URL, json=lastfm_top_artists_payload(["A", "B", "C"]))
    out = fetch.get_top_artists("user", limit=3)
    assert [a["name"] for a in out] == ["A", "B", "C"]
    assert [a["score"] for a in out] == [1.0, 0.5, 0.0]


def test_top_artists_unknown_user_returns_empty(http):
    http.add("GET", LASTFM_URL, json={"error": 6, "message": "User not found"})
    assert fetch.get_top_artists("nobody") == []


def test_top_artists_network_error_returns_empty(http):
    http.add("GET", LASTFM_URL, body=requests.ConnectionError("down"))
    assert fetch.get_top_artists("user") == []


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BUG-31: Last.fm scores are normalized by the requested "
                   "`limit`, not the number returned, unlike spotify/fetch.py")
def test_top_artists_score_spans_full_range_when_fewer_than_limit(http):
    http.add("GET", LASTFM_URL, json=lastfm_top_artists_payload(["A", "B"]))
    out = fetch.get_top_artists("user", limit=100)
    assert out[-1]["score"] == 0.0


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
