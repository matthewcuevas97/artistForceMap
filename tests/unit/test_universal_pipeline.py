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


@pytest.mark.parametrize("n", [1, 2, 5, 10])
def test_rbo_identical_lists_is_one_at_any_length(n):
    tags = [f"t{i}" for i in range(n)]
    assert rbo_similarity(tags, tags) == pytest.approx(1.0)


def test_rbo_matches_hand_computed_extrapolation():
    # First 5 of 10 agree, rest disjoint: (1-p)/p * Σ X_d/d p^d + X_10/10 p^10 = 0.7442
    a = list("abcdefghij")
    b = list("abcde") + list("vwxyz")
    assert rbo_similarity(a, b) == pytest.approx(0.744196, abs=1e-6)


def test_rbo_is_top_weighted():
    base = list("abcdefghij")
    agree_top = list("abc") + list("uvwxyzq")
    agree_bottom = list("uvwxyzq") + list("hij")
    assert rbo_similarity(base, agree_top) > rbo_similarity(base, agree_bottom)


def test_rbo_both_empty_is_zero():
    assert rbo_similarity([], []) == 0.0


def test_rbo_disjoint_lists_is_zero():
    assert rbo_similarity(["a", "b"], ["c", "d"]) == 0.0


def test_rbo_one_empty_is_zero():
    assert rbo_similarity(["a"], []) == 0.0


def test_rbo_is_symmetric():
    a, b = ["x", "y", "z", "w"], ["y", "q", "x"]
    assert rbo_similarity(a, b) == pytest.approx(rbo_similarity(b, a))


def test_two_tagless_artists_are_not_connected():
    """BUG-18 regression: rbo([], []) was 1.0, linking two tag-less artists."""
    graph = build_seed_graph("u", ["A", "B"], {"A": {"name": "A", "tags": []}, "B": {"name": "B", "tags": []}})
    assert graph["edges"] == []


TAGS5 = ["pop", "dance", "electropop", "synthpop", "hyperpop"]


def test_identical_short_tag_lists_are_connected():
    """BUG-35 regression: truncated RBO scored identical 2-tag lists 0.19 (< 0.21)."""
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


def test_enrichment_does_not_cache_failed_tag_lookup(http):
    """BUG-23 regression: a rate-limited tag lookup was cached as tags=[] for 90 days."""
    _mock_lastfm(http, error_on=("artist.getTopTags",))
    user_data.set_user_top_artists("u", spotify_artists=[{"name": "A", "score": 1.0}])
    tag_enrichment.enrich_top_25_artists("u")
    assert cache.get_cached_artist("A") is None


# ── Graph init / Deezer ───────────────────────────────────────────────────────

def _expired_preview(minutes_ago=60):
    exp = int(time.time()) - minutes_ago * 60
    return f"https://cdnt-preview.dzcdn.net/api/1/x.mp3?hdnea=exp={exp}~acl=/api/1/x.mp3*~hmac=abc"


def test_seed_metadata_never_serves_expired_preview_urls(monkeypatch):
    """BUG-10 regression: signed Deezer preview URLs (~15 min) were cached for 90 days.
    Old cache entries are stripped; tracks carry a deezer_id resolved at play time."""
    cache.set_cached_similar_artists("A", [])
    cache.set_cached_deezer_info("A", {"name": "A", "image_url": None, "fans": 1,
                                       "top_tracks": [{"name": "Song", "deezer_id": 7, "preview_url": _expired_preview()}]})
    monkeypatch.setattr(graph_init.time, "sleep", lambda s: None)
    meta = graph_init.fetch_seed_artist_metadata("A", {"tags": []})
    assert meta["top_tracks"] == [{"name": "Song", "deezer_id": 7}]


def test_fetched_deezer_info_caches_ids_not_previews(http):
    http.add("GET", "https://api.deezer.com/search/artist", json={"data": [{"id": 5, "name": "A", "picture_xl": "img"}]})
    http.add("GET", "https://api.deezer.com/artist/5", json={"nb_fan": 10})
    http.add("GET", "https://api.deezer.com/artist/5/top", json={"data": [
        {"id": 99, "title": "Hit", "preview": _expired_preview(-10), "artist": {"name": "A"}, "album": {"cover_big": "c"}}]})
    info = graph_init.get_deezer_info("A")
    assert info["top_tracks"] == [{"name": "Hit", "artist": "A", "deezer_id": 99, "album_art": "c"}]
    assert "preview" not in json.dumps(cache.get_cached_deezer_info("A"))


def test_similar_lookup_failure_is_not_cached(http):
    http.add("GET", LASTFM_URL, json={"error": 29, "message": "Rate limit exceeded"})
    assert graph_init.get_similar("A") is None
    assert cache.get_cached_similar_artists("A") is None


# ── First ring of similar artists (BUG-17) ────────────────────────────────────

def _seed_meta(name, similar, genre="Pop"):
    return {"name": name, "tags": [], "genre": genre, "seed": True,
            "similar_artists": [{"name": n, "match": m} for n, m in similar]}


def test_seed_graph_adds_top_similar_artists_as_nodes():
    meta = {"A": _seed_meta("A", [("S1", .9), ("S2", .8), ("S3", .7), ("S4", .6), ("S5", .5)]),
            "B": _seed_meta("B", [("S1", .4), ("T1", .9)], genre="Electronic")}
    g = build_seed_graph("u", ["A", "B"], meta)
    names = [n["name"] for n in g["nodes"]]
    assert names[:2] == ["A", "B"]
    assert set(names[2:]) == {"S1", "S2", "S3", "S4", "T1"}  # 4 per seed, S1 shared
    s1 = next(n for n in g["nodes"] if n["name"] == "S1")
    assert s1["seed"] is False and s1["parent"] == "A" and s1["genre"] == "Pop" and s1["details_loaded"] is False
    pairs = {tuple(sorted((e["source"], e["target"]))) for e in g["edges"]}
    assert ("A", "S1") in pairs and ("B", "S1") in pairs, "a shared similar artist links both seeds"
    assert ("A", "S5") not in pairs


def test_seed_graph_uses_users_own_enrichment_for_known_artists():
    meta = {"A": _seed_meta("A", [("Known", .9)])}
    g = build_seed_graph("u", ["A"], meta, user_artists={"Known": {"tags": ["house"], "listeners": 77}})
    known = next(n for n in g["nodes"] if n["name"] == "Known")
    assert known["genre"] == "Electronic" and known["listeners"] == 77


def test_expand_map_skips_existing_and_caps(monkeypatch):
    monkeypatch.setattr(graph_init, "get_similar", lambda n: [{"name": f"X{i}", "match": .5} for i in range(10)] + [{"name": "A", "match": 1}])
    m = {"nodes": [{"name": "P", "genre": "Pop"}, {"name": "X0"}], "edges": []}
    res = graph_init.expand_map(m, "P", limit=3)
    assert [n["name"] for n in res["added_nodes"]] == ["X1", "X2", "X3"]
    assert {e["target"] for e in res["added_edges"]} == {"X0", "X1", "X2", "X3"}
    assert graph_init.expand_map(m, "P")["already_expanded"] is True


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


@pytest.mark.parametrize("uid", ["../../escape", "/etc/passwd", "..", "a/b", "名前", "x" * 200])
def test_user_id_cannot_escape_data_dir(isolated_storage, uid):
    """BUG-22 regression: user ids went into file paths unsanitised."""
    import os
    for path in (user_data.get_user_map_path(uid), user_data.get_user_db_path(uid), cache.get_user_cache_path(uid)):
        real = os.path.realpath(path)
        assert os.path.dirname(real) in {os.path.realpath(str(isolated_storage["users"])),
                                         os.path.realpath(str(isolated_storage["cache"]))}


def test_normal_user_ids_keep_readable_file_names():
    assert user_data.get_user_map_path("yfs6fgzckr3o9tikcj54rsd0f").endswith("yfs6fgzckr3o9tikcj54rsd0f_map.json")
    assert user_data.get_user_map_path("bob_the-dj.1").endswith("bob_the-dj.1_map.json")


def test_user_map_roundtrip_for_unsafe_id():
    user_data.save_user_map("../evil", {"nodes": [{"name": "A"}], "edges": []})
    assert user_data.load_user_map("../evil")["nodes"] == [{"name": "A"}]


def test_concurrent_map_updates_are_not_lost():
    import threading
    user_data.save_user_map("u", {"nodes": [], "edges": []})

    def add(i):
        user_data.update_user_map("u", lambda m: m["nodes"].append({"name": f"N{i}"}))
    threads = [threading.Thread(target=add, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(user_data.load_user_map("u")["nodes"]) == 20


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
