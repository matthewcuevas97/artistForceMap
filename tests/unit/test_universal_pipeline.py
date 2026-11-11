"""Universal-map backend pipeline: ingestion → enrichment → seed selection → graph init."""

import json
import re
import time

import pytest

import backend.cache as cache
from backend import graph_init, seed_selection, tag_enrichment, user_data, user_ingestion
from backend.graph_init import _derive_genre, build_seed_graph, rbo_similarity
from tests.conftest import LASTFM_URL, lastfm_top_artists_payload


# ── Pure helpers ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tags,genre", [
    (["house", "pop"], "Electronic"),          # bucket order wins
    (["indie rock"], "Indie/Alt"),
    (["rap"], "Hip-Hop"),
    (["Folk"], "Singer-Songwriter/Jazz"),      # case-insensitive
    (["polka"], "Unknown"),
    ([], "Unknown"),
])
def test_derive_genre(tags, genre):
    assert _derive_genre(tags) == genre


def test_rbo_identical_lists_is_max_for_depth():
    tags = [f"t{i}" for i in range(10)]
    assert rbo_similarity(tags, tags) == pytest.approx(1 - 0.9 ** 10)


def test_rbo_disjoint_lists_is_zero():
    assert rbo_similarity(["a", "b"], ["c", "d"]) == 0.0


def test_rbo_one_empty_is_zero():
    assert rbo_similarity(["a"], []) == 0.0


def test_rbo_is_symmetric():
    a, b = ["x", "y", "z", "w"], ["y", "q", "x"]
    assert rbo_similarity(a, b) == pytest.approx(rbo_similarity(b, a))


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BUG-18: rbo_similarity([], []) returns 1.0, so two "
                   "tag-less seed artists get a spurious 'tag_similarity' edge")
def test_two_tagless_artists_are_not_connected():
    graph = build_seed_graph("u", ["A", "B"], {"A": {"name": "A", "tags": []}, "B": {"name": "B", "tags": []}})
    assert graph["edges"] == []


TAGS5 = ["pop", "dance", "electropop", "synthpop", "hyperpop"]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BUG-35: RBO is truncated (no extrapolation), so identical "
                   "short tag lists score < 0.21 — e.g. two artists tagged ['pop','dance'] = 0.19")
def test_identical_short_tag_lists_are_connected():
    meta = {n: {"name": n, "tags": ["pop", "dance"]} for n in "AB"}
    assert build_seed_graph("u", ["A", "B"], meta)["edges"]


def test_build_seed_graph_gold_standard_then_rbo():
    meta = {
        "A": {"name": "A", "tags": TAGS5, "similar_artists": [{"name": "B", "match": 0.9}]},
        "B": {"name": "B", "tags": TAGS5, "similar_artists": []},
        "C": {"name": "C", "tags": TAGS5, "similar_artists": []},
        "D": {"name": "D", "tags": ["metal"], "similar_artists": []},
    }
    g = build_seed_graph("u", ["A", "B", "C", "D"], meta)
    by_pair = {tuple(sorted((e["source"], e["target"]))): e for e in g["edges"]}
    assert by_pair[("A", "B")]["pass"] == 1
    assert by_pair[("A", "C")]["pass"] == 2 and by_pair[("B", "C")]["pass"] == 2
    assert not any("D" in k for k in by_pair)
    assert [n["name"] for n in g["nodes"]] == ["A", "B", "C", "D"]


# ── Seed selection (MMR) ──────────────────────────────────────────────────────

def _write_enriched(user_id, artists):
    user_data.save_user_db(user_id, {"all_artists": artists})


def test_seed_selection_picks_rank1_then_diverse():
    artists = {
        "Top":     {"rank": 1, "tags": ["pop"]},
        "PopClone": {"rank": 2, "tags": ["pop"]},
        "Metal":   {"rank": 3, "tags": ["metal"]},
    }
    _write_enriched("u", artists)
    res = seed_selection.select_seed_artists("u", num_seeds=2, lambda_param=0.7)
    # rank_score: PopClone .958*.7 + 0*.3 = .671 ; Metal .917*.7 + 1*.3 = .942
    assert res["seed_artists"] == ["Top", "Metal"]
    assert user_data.load_user_db("u")["seed_artists"] == ["Top", "Metal"]


def test_seed_selection_with_fewer_artists_than_seeds():
    _write_enriched("u", {"Only": {"rank": 1, "tags": []}})
    assert seed_selection.select_seed_artists("u", num_seeds=5)["seed_artists"] == ["Only"]


def test_seed_selection_without_enrichment_raises():
    with pytest.raises(ValueError, match="No enriched artists"):
        seed_selection.select_seed_artists("ghost")


# ── Tag enrichment ────────────────────────────────────────────────────────────

def _mock_lastfm(http, *, info=None, tags=None, error_on=()):
    """Route Last.fm calls by method param."""
    def cb(request):
        method = re.search(r"method=([^&]+)", request.url).group(1)
        if method in error_on:
            return (200, {}, json.dumps({"error": 29, "message": "Rate limit exceeded"}))
        if method == "artist.getInfo":
            return (200, {}, json.dumps(info or {"artist": {"stats": {"listeners": "123"}, "image": [], "bio": {"summary": "Bio <a href='x'>Read more</a>"}}}))
        if method == "artist.getTopTags":
            return (200, {}, json.dumps({"toptags": {"tag": [{"name": t} for t in (tags or ["Pop", "Dance"])]}}))
        return (404, {}, "{}")
    http.add_callback("GET", LASTFM_URL, callback=cb)


def test_enrichment_fetches_and_caches(http):
    _mock_lastfm(http)
    user_data.set_user_top_artists("u", spotify_artists=[{"name": "A", "score": 1.0}])
    res = tag_enrichment.enrich_top_25_artists("u")
    assert res["all_artists"]["A"]["tags"] == ["pop", "dance"]
    assert res["all_artists"]["A"]["listeners"] == 123
    assert res["all_artists"]["A"]["bio"] == "Bio"
    assert cache.get_cached_artist("A")["tags"] == ["pop", "dance"]
    n_calls = len(http.calls)
    tag_enrichment.enrich_top_25_artists("u")
    assert len(http.calls) == n_calls, "second run should be served from cache"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BUG-23: a Last.fm error/rate-limit on getTopTags is "
                   "turned into tags=[] and cached for 90 days, permanently degrading that artist")
def test_enrichment_does_not_cache_failed_tag_lookup(http):
    _mock_lastfm(http, error_on=("artist.getTopTags",))
    user_data.set_user_top_artists("u", spotify_artists=[{"name": "A", "score": 1.0}])
    tag_enrichment.enrich_top_25_artists("u")
    assert cache.get_cached_artist("A") is None


# ── Graph init / Deezer ───────────────────────────────────────────────────────

def _expired_preview(minutes_ago=60):
    exp = int(time.time()) - minutes_ago * 60
    return f"https://cdnt-preview.dzcdn.net/api/1/x.mp3?hdnea=exp={exp}~acl=/api/1/x.mp3*~hmac=abc"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BUG-10: Deezer preview URLs are signed with a ~15 min "
                   "expiry (hdnea=exp=...) but cached with top_tracks for 90 days")
def test_seed_metadata_never_serves_expired_preview_urls(monkeypatch):
    cache.set_cached_similar_artists("A", [])
    cache.set_cached_deezer_info("A", {"name": "A", "image_url": None, "fans": 1,
                                       "top_tracks": [{"name": "Song", "preview_url": _expired_preview()}]})
    monkeypatch.setattr(graph_init.time, "sleep", lambda s: None)
    meta = graph_init.fetch_seed_artist_metadata("A", {"tags": []})
    url = meta["top_tracks"][0]["preview_url"]
    exp = int(re.search(r"exp=(\d+)", url).group(1))
    assert exp > time.time()


def test_initialize_user_graph_end_to_end_from_cache(monkeypatch):
    monkeypatch.setattr(graph_init.time, "sleep", lambda s: None)
    _write_enriched("u", {"A": {"rank": 1, "tags": ["pop"], "listeners": 5},
                          "B": {"rank": 2, "tags": ["pop"], "listeners": 3}})
    user_data.save_user_db("u", {"seed_artists": ["A", "B"]})
    for name in "AB":
        cache.set_cached_similar_artists(name, [{"name": "B" if name == "A" else "A", "match": 0.7}])
        cache.set_cached_deezer_info(name, {"name": name, "image_url": f"img-{name}", "fans": 1, "top_tracks": []})
    res = graph_init.initialize_user_graph("u")
    saved = user_data.load_user_map("u")
    assert saved["nodes"] == res["graph"]["nodes"]
    assert {n["name"] for n in saved["nodes"]} == {"A", "B"}
    assert saved["edges"][0]["pass"] == 1
    assert saved["nodes"][0]["genre"] == "Pop"


# ── User data layer ───────────────────────────────────────────────────────────

def test_load_user_map_default_is_empty():
    assert user_data.load_user_map("new") == {"user_id": "new", "nodes": [], "edges": []}


def test_load_user_db_falls_back_to_single_source():
    cache.save_user_cache("u", {"top_artists_lastfm": [{"name": "X", "score": 1}], "top_artists_merged": []})
    assert user_data.load_user_db("u")["top_artists"] == [{"name": "X", "score": 1}]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BUG-22: user ids are interpolated into file paths "
                   "unsanitized (data/users/{user_id}_map.json)")
def test_user_id_cannot_escape_data_dir(isolated_storage):
    import os
    path = os.path.realpath(user_data.get_user_map_path("../../escape"))
    assert path.startswith(os.path.realpath(str(isolated_storage["users"])))


# ── Ingestion ─────────────────────────────────────────────────────────────────

def test_lastfm_ingestion_caches_top_25(http):
    http.add("GET", LASTFM_URL, json=lastfm_top_artists_payload([f"A{i}" for i in range(40)]))
    res = user_ingestion.ingest_user({"provider": "lastfm", "id": "bob"})
    assert res["top_artists_count"] == 25
    top = user_data.load_user_db("bob")["top_artists"]
    assert len(top) == 25 and top[0]["score"] == 1.0 and top[-1]["score"] == 0.0


def test_ingestion_rejects_unknown_provider():
    with pytest.raises(ValueError):
        user_ingestion.ingest_user({"provider": "myspace", "id": "tom"})
