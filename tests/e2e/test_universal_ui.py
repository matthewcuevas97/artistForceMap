"""Browser tests for the universal map (app_universal.py + static/js/universal_map.js)."""

import time

import pytest

from backend import graph_init, user_data
from backend.progress import report

pytestmark = pytest.mark.e2e

XSS = '<img src=x onerror="window.__xss=1">'


def _node(name, listeners, genre="Pop", tags=("pop",), seed=True, **extra):
    return {"name": name, "listeners": listeners, "genre": genre, "tags": list(tags), "seed": seed,
            "details_loaded": True, "expanded": False, "bio": f"{name} bio", "image_url": None,
            "top_tracks": [{"name": f"{name} Song", "deezer_id": len(name), "album_art": None}],
            **extra}


@pytest.fixture
def fake_backend(monkeypatch, universal_server, media_server):
    """Deterministic pipeline, Last.fm similar artists, artist details and preview resolution."""
    import app_universal
    nodes = [
        _node("Mega Star", 5_000_000),
        _node("Mid Act", 300_000, genre="Electronic", tags=("house",)),
        _node("Tiny Band", 900, genre="Indie/Alt", tags=("indie",)),
    ]
    state = {
        "nodes": nodes, "fail": None,
        "previews": {"Mega Star Song": f"{media_server}/preview.wav"},
        "similar": {"Mid Act": [{"name": "New Friend", "match": 0.8}, {"name": "Mega Star", "match": 0.6}]},
        "details": {},
    }

    def fake_pipeline(auth):
        report("STEP 1: User Ingestion")
        report("✓ Fetched 25 top artists")
        time.sleep(0.4)  # let the browser paint progress before completion replaces it
        if state["fail"]:
            raise ValueError(state["fail"])
        user_data.save_user_map(auth["id"], {"nodes": state["nodes"],
                                             "edges": [{"source": "Mega Star", "target": "Mid Act", "weight": 0.7}]})

    def fake_enrich(name):
        if name not in state["details"]:
            from backend.tag_enrichment import EnrichmentUnavailable
            raise EnrichmentUnavailable(name)
        return state["details"][name]

    monkeypatch.setattr(app_universal, "run_full_pipeline", fake_pipeline)
    monkeypatch.setattr(app_universal, "lastfm_top",
                        lambda user, limit=100: [{"name": "x", "score": 1}] if user == "bob" else [])
    monkeypatch.setattr(app_universal, "resolve_preview",
                        lambda deezer_id=None, artist="", title="": state["previews"].get(title))
    monkeypatch.setattr(app_universal, "enrich_artist_with_lastfm", fake_enrich)
    monkeypatch.setattr(app_universal, "get_deezer_info", lambda name: {})
    monkeypatch.setattr(graph_init, "get_similar", lambda name: state["similar"].get(name, []))
    return state


def _login(u):
    p = u.page
    u.goto()
    p.locator("#lastfmUsername").fill("bob")
    p.locator("#lastfmGo").click()
    p.locator("#lastfmConnected").wait_for()


def _generate(u):
    u.page.locator("#initBtn").click()
    u.page.locator("#initStatus", has_text="Map ready").wait_for(timeout=15000)
    u.wait_for_graph()


def _open_panel(u, name):
    u.click_node(name)
    u.page.locator("#artistPanel.open .panel-name", has_text=name).wait_for()


def _positions(page):
    return page.evaluate("() => Object.fromEntries(Array.from(document.querySelectorAll('#graph circle'))"
                         ".map(c => [c.__data__.name, [c.__data__.x, c.__data__.y]]))")


# ── Auth / generation ─────────────────────────────────────────────────────────

def test_anonymous_sees_only_auth_controls(universal, fake_backend):
    universal.goto()
    p = universal.page
    assert p.locator("#spotifyBtn").is_visible() and p.locator("#lastfmUsername").is_visible()
    for hidden in ("#initRow", "#sizeRow", "#chargeRow", "#optionsRow"):
        assert p.locator(hidden).is_hidden()


def test_lastfm_unknown_user(universal, fake_backend):
    universal.goto()
    p = universal.page
    p.locator("#lastfmUsername").fill("ghost")
    p.locator("#lastfmGo").click()
    p.locator("#lastfmError").wait_for()


def test_login_generate_and_render(universal, fake_backend):
    _login(universal)
    p = universal.page
    assert p.locator("#initBtn").is_visible()
    p.evaluate("""() => { window.__progress = [];
        new MutationObserver(() => window.__progress.push(document.getElementById('initStatus').innerText))
          .observe(document.getElementById('initStatus'), {childList: true, subtree: true}); }""")
    p.locator("#initBtn").click()
    p.locator("#initStatus", has_text="Map ready! 3 nodes, 1 connections").wait_for()
    assert any("Fetched 25 top artists" in t for t in p.evaluate("() => window.__progress"))
    universal.wait_for_graph(3)
    assert p.locator("#graph line").count() == 1
    assert p.locator("#graph text.label").count() == 3
    assert p.locator("#initBtn").inner_text() == "REGENERATE MY MAP"
    assert universal.page_errors == []


def test_pipeline_error_is_shown(universal, fake_backend):
    """BUG-14 regression: the SSE loop swallowed event.error, so failures never reached the UI."""
    fake_backend["fail"] = "No enriched artists found"
    _login(universal)
    universal.page.locator("#initBtn").click()
    universal.page.locator("#initStatus .status-error", has_text="No enriched artists found").wait_for(timeout=5000)
    assert universal.page.locator("#initBtn").is_enabled()


def test_map_survives_reload(universal, fake_backend):
    """BUG-16 regression: the saved map was never reloaded (/api/map/get was unused)."""
    _login(universal)
    _generate(universal)
    universal.page.reload()
    universal.wait_for_graph(3)
    assert universal.page.locator("#initBtn").inner_text() == "REGENERATE MY MAP"


def test_whole_map_fits_viewport(universal, fake_backend):
    _login(universal)
    _generate(universal)
    vp = universal.page.viewport_size
    outside = universal.page.evaluate(
        "([w,h]) => Array.from(document.querySelectorAll('#graph circle')).filter(c => {"
        "const b = c.getBoundingClientRect(); return b.right < 0 || b.bottom < 0 || b.left > w || b.top > h; }).length",
        [vp["width"], vp["height"]])
    assert outside == 0


# ── Graph controls ────────────────────────────────────────────────────────────

def test_controls_labels_and_size(universal, fake_backend):
    _login(universal)
    _generate(universal)
    p = universal.page
    p.locator("#labelsCheck").uncheck()
    assert p.evaluate("() => Array.from(document.querySelectorAll('#graph text.label'))"
                      ".every(t => t.getAttribute('opacity') === '0')")
    r1 = float(universal.node("Tiny Band").get_attribute("r"))
    p.locator("#nodeSizeSlider").fill("2")
    assert float(universal.node("Tiny Band").get_attribute("r")) == pytest.approx(r1 * 2)


def test_node_radius_reflects_listeners(universal, fake_backend):
    """BUG-15 regression: radius was 3 + log1p(listeners)/1e6, i.e. always 4 px."""
    _login(universal)
    _generate(universal)
    r = {n: float(universal.node(n).get_attribute("r")) for n in ("Mega Star", "Mid Act", "Tiny Band")}
    assert r["Mega Star"] > r["Mid Act"] > r["Tiny Band"]


# ── Panel ─────────────────────────────────────────────────────────────────────

def test_node_click_opens_panel_and_plays_preview(universal, fake_backend):
    _login(universal)
    _generate(universal)
    p = universal.page
    _open_panel(universal, "Mega Star")
    assert "5,000,000 listeners" in p.locator(".panel-meta").inner_text()
    with p.expect_request("**/api/preview?*"):
        p.locator(".track-play").click()
    p.wait_for_function("() => document.querySelector('.track-play').classList.contains('playing')")
    p.locator(".track-play").click()  # toggle off
    assert p.locator(".track-play.playing").count() == 0
    p.locator("#panelClose").click()
    assert p.locator("#artistPanel.open").count() == 0


def test_dead_preview_handled_gracefully(universal, fake_backend):
    """BUG-38 regression: an audio.play() rejection was uncaught and the button still showed 'playing'."""
    fake_backend["previews"]["Mega Star Song"] = "https://cdnt-preview.dzcdn.net/expired.mp3"  # aborted offline
    _login(universal)
    _generate(universal)
    _open_panel(universal, "Mega Star")
    universal.page.locator(".track-play").click()
    universal.page.wait_for_function("() => document.querySelector('.track-play').textContent === 'N/A'")
    assert not [e for e in universal.console_errors + universal.page_errors if "Uncaught" in e]
    assert universal.page.locator(".track-play.playing").count() == 0


def test_track_without_preview_shows_na(universal, fake_backend):
    _login(universal)
    _generate(universal)
    _open_panel(universal, "Tiny Band")  # no entry in fake previews → resolver returns None
    universal.page.locator(".track-play").click()
    universal.page.wait_for_function("() => document.querySelector('.track-play').textContent === 'N/A'")


def test_panel_escapes_untrusted_content(universal, fake_backend):
    """BUG-19 regression: the panel was built from unescaped Last.fm/Deezer strings."""
    mid = fake_backend["nodes"][1]
    mid["tags"] = [XSS]
    mid["bio"] = XSS
    mid["top_tracks"] = [{"name": XSS, "deezer_id": 1, "album_art": "javascript:window.__xss=2"}]
    mid["image_url"] = '" onerror="window.__xss=3'
    _login(universal)
    _generate(universal)
    _open_panel(universal, "Mid Act")
    universal.page.wait_for_timeout(500)
    assert universal.page.evaluate("() => window.__xss") is None
    assert XSS in universal.page.locator(".panel-bio").inner_text()  # shown as text
    assert universal.page.locator(".panel-hero").count() == 0, "non-http image URLs are dropped"


def test_missing_album_art_renders_placeholder(universal, fake_backend):
    _login(universal)
    _generate(universal)
    _open_panel(universal, "Mega Star")  # album_art is None
    assert universal.page.locator(".track-row img").count() == 0
    assert universal.page.locator(".track-row .track-art-empty").count() == 1


def test_stub_node_loads_details_on_click(universal, fake_backend):
    fake_backend["nodes"].append({"name": "Stubby", "seed": False, "details_loaded": False, "parent": "Mid Act",
                                  "genre": "Electronic", "listeners": 0, "tags": [], "top_tracks": []})
    fake_backend["details"]["Stubby"] = {"name": "Stubby", "listeners": 4242, "tags": ["jazz"],
                                         "bio": "A jazz trio.", "image_url": None}
    _login(universal)
    _generate(universal)
    p = universal.page
    _open_panel(universal, "Stubby")
    p.locator(".panel-bio", has_text="A jazz trio.").wait_for()
    assert "4,242 listeners" in p.locator(".panel-meta").inner_text()
    assert universal.node("Stubby").get_attribute("fill").startswith("hsl(30,"), \
        "genre re-derived from the loaded tags (jazz → Singer-Songwriter/Jazz)"


def test_details_failure_is_shown(universal, fake_backend):
    fake_backend["nodes"].append({"name": "Flaky", "seed": False, "details_loaded": False, "genre": "Pop",
                                  "listeners": 0, "tags": [], "top_tracks": []})
    _login(universal)
    _generate(universal)
    _open_panel(universal, "Flaky")
    universal.page.locator("#panelError", has_text="Couldn't load details").wait_for()


# ── Expansion ─────────────────────────────────────────────────────────────────

def test_expand_adds_similar_artists_in_place(universal, fake_backend):
    """BUG-16b/24 regression: the map could not be explored from the UI (and expansion needed Spotify)."""
    _login(universal)
    _generate(universal)
    p = universal.page
    before = _positions(p)
    _open_panel(universal, "Mid Act")
    with p.expect_request("**/api/map/expand"):
        p.locator("#expandBtn").click()
    p.wait_for_function("() => document.querySelectorAll('#graph circle').length === 4")
    p.locator("#expandBtn", has_text="EXPANDED").wait_for()
    universal.tag_nodes()
    assert universal.node("New Friend").count() == 1
    assert p.locator("#graph line").count() == 2  # Mega Star–Mid Act (existing) + Mid Act–New Friend
    after = _positions(p)
    jump = max(((after[n][0] - x) ** 2 + (after[n][1] - y) ** 2) ** 0.5 for n, (x, y) in before.items())
    assert jump < 150, "existing nodes keep their positions when the map grows"
    p.reload()  # persisted
    universal.wait_for_graph(4)


def test_expand_with_no_new_artists_says_so(universal, fake_backend):
    _login(universal)
    _generate(universal)
    _open_panel(universal, "Tiny Band")
    universal.page.locator("#expandBtn").click()
    universal.page.locator("#panelError", has_text="No new similar artists").wait_for()
