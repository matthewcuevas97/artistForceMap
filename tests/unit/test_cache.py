"""backend/cache.py — file-backed caches (ported from the legacy, destructive backend/test_cache.py)."""

import json
import time


import backend.cache as cache


def test_artist_cache_roundtrip_hides_metadata():
    cache.set_cached_artist("the beatles", {"name": "The Beatles", "listeners": 5})
    got = cache.get_cached_artist("the beatles")
    assert got == {"name": "The Beatles", "listeners": 5}


def test_artist_cache_miss_returns_none():
    assert cache.get_cached_artist("nobody") is None


def test_artist_cache_expiry_evicts_entry(monkeypatch):
    cache.set_cached_artist("old", {"name": "Old"})
    future = time.time() + cache.ARTIST_CACHE_TTL + 1
    monkeypatch.setattr(cache.time, "time", lambda: future)
    assert cache.get_cached_artist("old") is None
    assert "old" not in json.load(open(cache.ARTIST_CACHE_FILE))


def test_get_or_set_cached_artist_only_fetches_once():
    calls = []

    def fetch(name):
        calls.append(name)
        return {"name": name}

    assert cache.get_or_set_cached_artist("x", fetch, "X") == {"name": "X"}
    assert cache.get_or_set_cached_artist("x", fetch, "X") == {"name": "X"}
    assert calls == ["X"]


def test_get_or_set_cached_artist_swallows_fetch_errors():
    def boom():
        raise RuntimeError("api down")
    assert cache.get_or_set_cached_artist("x", boom) is None


def test_cache_stats_counts_expired(monkeypatch):
    cache.set_cached_artist("a", {"n": 1})
    cache.set_cached_artist("b", {"n": 2})
    data = json.load(open(cache.ARTIST_CACHE_FILE))
    data["a"]["_created_at"] = 0
    json.dump(data, open(cache.ARTIST_CACHE_FILE, "w"))
    stats = cache.get_cache_stats()
    assert (stats["total_artists"], stats["expired"], stats["valid"]) == (2, 1, 1)


def test_similar_and_deezer_caches_roundtrip():
    cache.set_cached_similar_artists("A", [{"name": "B", "match": 0.5}])
    assert cache.get_cached_similar_artists("A") == [{"name": "B", "match": 0.5}]
    cache.set_cached_deezer_info("A", {"fans": 3})
    assert cache.get_cached_deezer_info("A") == {"fans": 3}


def test_empty_similar_list_is_a_cache_hit_not_a_miss():
    cache.set_cached_similar_artists("Obscure", [])
    assert cache.get_cached_similar_artists("Obscure") == []


def test_merge_top_artists_lastfm_wins_and_keeps_spotify_id():
    sp = [{"name": "Beatles", "spotify_id": "sp1", "score": 1.0}, {"name": "Floyd", "spotify_id": "sp2", "score": 0.8}]
    lf = [{"name": "beatles", "score": 0.95}, {"name": "Bowie", "score": 0.85}]
    merged = cache.merge_top_artists(sp, lf)
    assert [m["name"] for m in merged] == ["beatles", "Bowie", "Floyd"]
    assert merged[0]["source"] == "lastfm" and merged[0]["spotify_id"] == "sp1"
    assert merged[2]["source"] == "spotify"


def test_merge_top_artists_caps_at_50():
    many = [{"name": f"a{i}", "score": 1 - i / 100} for i in range(80)]
    assert len(cache.merge_top_artists(many, [])) == 50


def test_user_cache_never_persists_tokens():
    cache.update_user_top_artists("u1", spotify_artists=[{"name": "A", "score": 1.0}])
    raw = open(cache.get_user_cache_path("u1")).read().lower()
    for secret in ("token", "password", "secret"):
        assert secret not in raw


def test_corrupt_cache_file_reads_as_empty():
    open(cache.ARTIST_CACHE_FILE, "w").write('{"truncated": ')
    assert cache.get_cached_artist("truncated") is None


def test_failed_write_does_not_destroy_existing_cache(monkeypatch):
    """BUG-11 regression: writes go to a temp file and os.replace() it, so a failed write keeps the old cache."""
    cache.set_cached_artist("keep me", {"name": "Keep"})

    real_dump = json.dump

    def exploding_dump(obj, fp, **kw):
        fp.write('{"partial":')
        raise OSError("disk full / process killed")

    monkeypatch.setattr(json, "dump", exploding_dump)
    cache.set_cached_artist("new", {"name": "New"})  # error is swallowed by _save_artist_cache
    monkeypatch.setattr(json, "dump", real_dump)

    assert cache.get_cached_artist("keep me") == {"name": "Keep"}
