"""Runtime scoring for the Coachella map (data/graph_builder.py) + static data contract."""

import json
from pathlib import Path

import pytest

from data.graph_builder import _norm, enrich_with_scores, normalize_listeners

ROOT = Path(__file__).resolve().parents[2]


def _scores(nodes):
    return {n["name"]: {"score": 0, "direct_score": 0, "derived_score": 0} for n in nodes}


def test_norm_strips_punctuation_and_case():
    assert _norm("Charli XCX!") == "charlixcx"
    assert _norm("Rossi.") == "rossi"
    assert _norm("¥ØU$UK€") == _norm("¥øu$uk€")  # unicode-aware lowercasing


def test_normalize_listeners_scales_to_max():
    nodes = [{"name": "a", "listeners": 100}, {"name": "b", "listeners": 25}, {"name": "c"}]
    s = normalize_listeners(nodes, _scores(nodes))
    assert s["a"]["score"] == 1.0
    assert s["b"]["score"] == 0.25
    assert s["c"]["score"] == 0


def test_normalize_listeners_all_zero_does_not_divide_by_zero():
    nodes = [{"name": "a", "listeners": 0}]
    assert normalize_listeners(nodes, _scores(nodes))["a"]["score"] == 0


def test_direct_match_overrides_baseline_and_is_name_normalized():
    nodes = [{"name": "Charli xcx", "listeners": 10}]
    scores = _scores(nodes)
    enrich_with_scores(nodes, [{"name": "CHARLI XCX", "score": 0.8}], scores)
    assert scores["Charli xcx"]["direct_score"] == 0.8
    assert scores["Charli xcx"]["score"] == 0.8


def test_derived_score_from_similar_artists():
    nodes = [{"name": "Lineup Act", "similar_artists": [{"name": "User Fave", "match": 0.5}]}]
    scores = _scores(nodes)
    enrich_with_scores(nodes, [{"name": "User Fave", "score": 1.0}], scores)
    assert scores["Lineup Act"]["derived_score"] == pytest.approx(0.3)  # 1.0 * 0.5 * 0.6
    assert scores["Lineup Act"]["score"] == pytest.approx(0.3)


def test_derived_score_takes_max_over_contributors():
    nodes = [{"name": "X", "similar_artists": [{"name": "A", "match": 0.9}, {"name": "B", "match": 0.2}]}]
    scores = _scores(nodes)
    enrich_with_scores(nodes, [{"name": "A", "score": 0.5}, {"name": "B", "score": 1.0}], scores)
    assert scores["X"]["derived_score"] == pytest.approx(max(0.5 * 0.9, 1.0 * 0.2) * 0.6)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BUG-05: a top artist with score 0.0 (last rank) is "
                   "indistinguishable from 'not a match' and gets its baseline wiped to 0")
def test_last_ranked_top_artist_still_counts_as_direct_match():
    nodes = [{"name": "Deep Cut", "listeners": 50}, {"name": "Big", "listeners": 100}]
    scores = _scores(nodes)
    normalize_listeners(nodes, scores)
    # spotify/fetch.get_top_artists gives the last of N artists score == 0.0
    enrich_with_scores(nodes, [{"name": "Big", "score": 1.0}, {"name": "Deep Cut", "score": 0.0}], scores)
    assert scores["Deep Cut"]["direct_score"] > 0 or scores["Deep Cut"]["score"] >= 0.5


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BUG-06: multi-artist lineup nodes (B2Bs, aliases) only "
                   "match on the display name, not their lastfm_artists members")
def test_multi_artist_node_matches_member_artist():
    nodes = [{"name": "Nine Inch Noize", "lastfm_artists": ["Nine Inch Nails", "Boys Noize"]}]
    scores = _scores(nodes)
    enrich_with_scores(nodes, [{"name": "Nine Inch Nails", "score": 1.0}], scores)
    assert scores["Nine Inch Noize"]["direct_score"] > 0


# ── Static data contract ──────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def static_graph():
    with open(ROOT / "data" / "graph_static.json") as f:
        return json.load(f)


def test_static_graph_links_reference_existing_nodes(static_graph):
    names = {n["name"] for n in static_graph["nodes"]}
    assert len(names) == len(static_graph["nodes"]), "duplicate node names"
    for link in static_graph["links"]:
        assert link["source"] in names and link["target"] in names
        assert 1 <= link["pass"] <= 5


def test_static_graph_degree_cap(static_graph):
    from collections import Counter
    deg = Counter()
    for l in static_graph["links"]:
        deg.update([l["source"], l["target"]])
    assert max(deg.values()) <= 6


def test_static_graph_nodes_have_frontend_fields(static_graph):
    required = {"name", "genre", "listeners", "day", "weekend", "tags", "top_tracks"}
    for n in static_graph["nodes"]:
        assert required <= n.keys(), n["name"]
        assert n["day"] in {"Friday", "Saturday", "Sunday"}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BUG-04: scripts/precompute.py slim_node() drops "
                   "similar_artists, so enrich_with_scores' derived scoring never fires in prod")
def test_static_graph_carries_similar_artists_for_derived_scoring(static_graph):
    assert any(n.get("similar_artists") for n in static_graph["nodes"])
