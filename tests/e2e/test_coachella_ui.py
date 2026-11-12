"""
Browser tests for the Coachella map (app.py + static/js/*.js).

Each test drives the real frontend against a live server. Behaviour that is
known-broken is captured as strict xfail with a BUG-id (see docs/REVIEW_2026-11.md).
"""

import json
import re

import pytest

pytestmark = pytest.mark.e2e

TOTAL_NODES = 142


def _graph_json(page):
    return page.evaluate("() => fetch('/api/graph').then(r => r.json())")


def _open(c):
    c.goto()
    c.wait_for_graph(TOTAL_NODES)


def _panel_name(page):
    return page.locator("#panelContent div").filter(has_text=re.compile(".+")).nth(0)


# ── Load & render ─────────────────────────────────────────────────────────────

def test_initial_render(coachella):
    _open(coachella)
    p = coachella.page
    data = _graph_json(p)
    assert p.locator("#graph circle").count() == TOTAL_NODES
    assert p.locator("#graph line").count() == len(data["edges_by_level"]["0.30"])
    assert p.locator("#graphStatusOverlay").is_hidden()
    assert coachella.page_errors == []


LONGTASK_OBSERVER = ("window.__lt=[];new PerformanceObserver(l=>l.getEntries().forEach(e=>window.__lt.push(e.duration)))"
                     ".observe({entryTypes:['longtask']});")
# PERF-01: 3000 synchronous pre-ticks used to block ~800 ms on load and on every slider step.
MAIN_THREAD_BUDGET_MS = 300


def test_initial_render_blocks_main_thread_under_budget(coachella):
    coachella.page.add_init_script(LONGTASK_OBSERVER)
    _open(coachella)
    worst = max(coachella.page.evaluate("() => window.__lt") or [0])
    assert worst < MAIN_THREAD_BUDGET_MS, f"main thread blocked for {worst:.0f} ms"


def test_threshold_slider_is_cheap_and_keeps_layout(coachella):
    """PERF-01: a threshold step swaps edges in place: no long task, nodes keep their positions."""
    coachella.page.add_init_script(LONGTASK_OBSERVER)
    _open(coachella)
    p = coachella.page
    p.evaluate("() => { window.__lt = []; }")
    before = p.evaluate("() => Object.fromEntries(Array.from(document.querySelectorAll('#graph circle')).map(c => [c.__data__.name, [c.__data__.x, c.__data__.y]]))")
    for v in ("5", "0", "3"):
        p.locator("#thresholdSlider").fill(v)
        p.wait_for_timeout(150)
    worst = max(p.evaluate("() => window.__lt") or [0])
    assert worst < MAIN_THREAD_BUDGET_MS, f"slider step blocked for {worst:.0f} ms"
    after = p.evaluate("() => Object.fromEntries(Array.from(document.querySelectorAll('#graph circle')).map(c => [c.__data__.name, [c.__data__.x, c.__data__.y]]))")
    moved = sorted(((a[0] - before[n][0]) ** 2 + (a[1] - before[n][1]) ** 2) ** 0.5 for n, a in after.items())
    assert moved[len(moved) // 2] < 60, "median node jumped: layout was rebuilt instead of nudged"
    assert p.locator("#graph circle").count() == TOTAL_NODES


def test_graph_load_failure_shows_error_overlay(coachella):
    coachella.page.route("**/api/graph", lambda r: r.fulfill(status=500, body="boom"))
    coachella.goto()
    overlay = coachella.page.locator("#graphStatusOverlay")
    overlay.wait_for(state="visible")
    assert "Failed to load graph" in overlay.inner_text()


def test_hover_shows_tooltip(coachella):
    _open(coachella)
    name = "The Strokes"
    box = coachella.node(name).bounding_box()
    coachella.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    tip = coachella.page.locator("#tooltip")
    tip.wait_for(state="visible")
    assert name in tip.inner_text() and "Indie/Alt" in tip.inner_text()
    coachella.page.mouse.move(5, 5)
    tip.wait_for(state="hidden")


def test_untrusted_names_are_escaped(coachella):
    """Node names/tags reach innerHTML in tooltip + panel; payload must stay inert."""
    payload = '<img src=x onerror="window.__xss=1">'

    def poison_graph(route):
        resp = route.fetch()
        data = resp.json()
        old = data["nodes"][0]["name"]
        data["nodes"][0].update(name=payload, genre=payload, score=1.0)
        for edges in data["edges_by_level"].values():
            for e in edges:
                e["source"] = payload if e["source"] == old else e["source"]
                e["target"] = payload if e["target"] == old else e["target"]
        route.fulfill(response=resp, body=json.dumps(data))

    def poison_artist(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(
            {"name": payload, "genre": payload, "tags": [payload], "artist_profiles": [{"bio": payload}]}))

    coachella.page.route("**/api/graph", poison_graph)
    coachella.page.route(re.compile(r"/api/artist\?name=%3Cimg"), poison_artist)
    _open(coachella)
    coachella.page.evaluate("() => d3.selectAll('#graph circle').attr('data-name', d => d.name === '%s' ? 'XSS' : d.name)"
                            % payload.replace("'", "\\'"))
    coachella.node("XSS").hover()
    coachella.node("XSS").dispatch_event("click")
    coachella.page.wait_for_timeout(800)
    assert coachella.page.evaluate("() => window.__xss") is None


# ── Selection / panel ─────────────────────────────────────────────────────────

def test_click_node_opens_panel_and_highlights_neighbourhood(coachella):
    _open(coachella)
    p = coachella.page
    coachella.click_node("The Strokes")
    p.locator("#artistPanel.open").wait_for()
    assert "The Strokes" in p.locator("#panelContent").inner_text()
    assert coachella.node("The Strokes").get_attribute("stroke") == "#FFD700"
    p.locator(".track-row").first.wait_for()
    dimmed = p.evaluate("() => Array.from(document.querySelectorAll('#graph circle')).filter(c => c.getAttribute('opacity') === '0.15').length")
    assert 0 < dimmed < TOTAL_NODES - 1
    assert p.locator("#controls").evaluate("e => e.classList.contains('minimized')")


def test_panel_close_restores_graph(coachella):
    """BUG-37 regression: closing with ✕ left the graph dimmed to the old neighbourhood."""
    _open(coachella)
    p = coachella.page
    coachella.click_node("The Strokes")
    p.locator("#artistPanel.open").wait_for()
    p.locator("#panelClose").click()
    p.locator("#artistPanel.open").wait_for(state="detached")
    assert coachella.node("The Strokes").get_attribute("stroke") == "none"
    assert p.evaluate("() => Array.from(document.querySelectorAll('#graph circle')).every(c => c.getAttribute('opacity') === '1')")


def test_background_click_closes_panel(coachella):
    _open(coachella)
    p = coachella.page
    coachella.click_node("The Strokes")
    p.locator("#artistPanel.open").wait_for()
    p.wait_for_timeout(800)  # zoom transition
    p.mouse.click(60, 60)
    p.locator("#artistPanel.open").wait_for(state="detached")


def test_preview_play_pause_toggle(coachella):
    _open(coachella)
    p = coachella.page
    coachella.click_node("The Strokes")
    btn = p.locator(".play-btn").first
    btn.wait_for()
    btn.click()
    p.wait_for_function("() => document.querySelector('.play-btn').textContent === '▐▐'")
    btn.click()
    p.wait_for_function("() => document.querySelector('.play-btn').textContent === '▶'")


def test_tracks_without_preview_are_disabled(coachella):
    _open(coachella)
    coachella.click_node("The Strokes")
    rows = coachella.page.locator(".play-btn")
    rows.first.wait_for()
    assert rows.count() > 3
    assert "pointer-events:none" in (rows.nth(3).get_attribute("style") or "").replace(" ", "")


def test_playlist_add_view_remove(coachella):
    _open(coachella)
    p = coachella.page
    coachella.click_node("The Strokes")
    p.locator(".track-row").first.click()
    p.locator(".add-playlist-btn").click()
    p.locator(".track-submenu", has_text="Added").wait_for()
    p.locator("#menuToggle").click()  # reopen controls (closes the artist panel)
    export = p.locator("#exportBtn")
    export.wait_for()
    assert export.inner_text() == "MY PLAYLIST (1)"
    export.click()
    p.locator("#exportPanel.open").wait_for()
    assert p.locator(".ep-track").count() == 1
    p.locator(".ep-remove").click()
    assert p.locator(".ep-track").count() == 0
    assert p.locator("#exportRow").is_hidden()


def test_playlist_opened_quickly_after_controls_stays_open(coachella):
    """BUG-36 regression: a pending 260 ms hide timer from closing used to hide the reopened panel."""
    _open(coachella)
    p = coachella.page
    coachella.click_node("The Strokes")
    p.locator(".track-row").first.click()
    p.locator(".add-playlist-btn").click()
    p.locator("#menuToggle").click()
    p.locator("#exportBtn").click()
    p.wait_for_timeout(600)
    assert p.locator("#exportPanel").is_visible()


def test_artist_with_slash_opens_panel(coachella):
    """BUG-07 regression: 'Model/Actriz' 404'd because the name was a URL path segment."""
    _open(coachella)
    coachella.click_node("Model/Actriz")
    coachella.page.wait_for_timeout(1500)
    assert coachella.page.locator("#artistPanel.open").count() == 1


def test_artist_load_failure_shows_error(coachella):
    """BUG-08: a failed /api/artist used to leave the panel closed with no feedback."""
    p = coachella.page
    p.route(re.compile(r"/api/artist\?name=The%20Strokes$"), lambda r: r.fulfill(status=500, body="boom"))
    _open(coachella)
    coachella.click_node("The Strokes")
    p.locator("#artistPanel.open .panel-error").wait_for(timeout=3000)
    assert "The Strokes" in p.locator("#panelContent").inner_text()


def test_rapid_clicks_show_last_clicked_artist(coachella):
    """BUG-08 regression: a slow response for an earlier click overwrote the newer artist."""
    p = coachella.page
    p.route(re.compile(r"/api/artist\?name=The%20Strokes$"), lambda r: (p.wait_for_timeout(1200), r.continue_()))
    _open(coachella)
    coachella.click_node("The Strokes")
    p.wait_for_timeout(100)
    coachella.click_node("Interpol")
    p.wait_for_timeout(2500)
    text = p.locator("#panelContent").inner_text()
    assert "Interpol" in text and "The Strokes" not in text
    assert p.locator("#tracksLoading").count() == 0, "spinner left hanging"


# ── Controls ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("day,label", [("FRI", "Friday"), ("SAT", "Saturday"), ("SUN", "Sunday")])
def test_day_filter(coachella, day, label):
    _open(coachella)
    p = coachella.page
    expected = sum(1 for n in _graph_json(p)["nodes"] if n["day"] == label)
    p.locator(f'.day-btn[data-day="{day}"]').click()
    assert len(coachella.visible_node_names()) == expected
    p.locator('.day-btn[data-day="ALL"]').click()
    assert len(coachella.visible_node_names()) == TOTAL_NODES


def test_threshold_slider_filters_edges(coachella):
    _open(coachella)
    p = coachella.page
    levels = _graph_json(p)["edges_by_level"]
    for idx, key in enumerate(["0.30", "0.32", "0.34", "0.36", "0.38", "0.40"]):
        p.locator("#thresholdSlider").fill(str(idx))
        assert p.locator("#thresholdValue").inner_text() == key  # label updates immediately
        # the edge swap itself is debounced
        p.wait_for_function(f"() => document.querySelectorAll('#graph line').length === {len(levels[key])}",
                            timeout=2000)


def test_threshold_change_keeps_selection_consistent(coachella):
    """Rebuilding the graph while a node is pinned must not leave the UI in a half-selected state."""
    _open(coachella)
    p = coachella.page
    coachella.click_node("The Strokes")
    p.locator("#artistPanel.open").wait_for()
    p.locator("#menuToggle").click()  # opening controls closes the artist panel
    p.locator("#thresholdSlider").fill("2")
    coachella.wait_for_graph(TOTAL_NODES)
    opacities = set(p.evaluate("() => Array.from(document.querySelectorAll('#graph circle')).map(c => c.getAttribute('opacity'))"))
    assert opacities <= {None, "1"}, f"stale subgraph dimming after rebuild: {opacities}"


def test_threshold_change_keeps_open_artist_highlighted(coachella):
    """With edges swapped in place, the pinned artist stays selected and its neighbourhood is recomputed."""
    _open(coachella)
    p = coachella.page
    coachella.click_node("The Strokes")
    p.locator("#artistPanel.open").wait_for()
    p.evaluate("() => { const s = document.getElementById('thresholdSlider'); s.value = '4';"
               " s.dispatchEvent(new Event('input')); }")
    p.wait_for_timeout(400)
    assert p.locator("#artistPanel.open").count() == 1
    edges = _graph_json(p)["edges_by_level"]["0.38"]
    expected = {"The Strokes"} | {e["target"] for e in edges if e["source"] == "The Strokes"} \
                               | {e["source"] for e in edges if e["target"] == "The Strokes"}
    lit = set(p.evaluate("() => Array.from(document.querySelectorAll('#graph circle'))"
                         ".filter(c => c.getAttribute('opacity') === '1').map(c => c.__data__.name)"))
    assert lit == expected
    assert coachella.node("The Strokes").get_attribute("stroke") == "#FFD700"


def test_node_size_slider_scales_radius(coachella):
    _open(coachella)
    p = coachella.page
    r0 = float(coachella.node("The Strokes").get_attribute("r"))
    p.locator("#nodeSizeSlider").fill("2")
    r1 = float(coachella.node("The Strokes").get_attribute("r"))
    assert r1 == pytest.approx(r0 * 2, rel=0.01)


def test_similarity_toggle_hides_edges(coachella):
    _open(coachella)
    p = coachella.page
    p.locator("#similarityCheck").uncheck()
    assert p.evaluate("() => Array.from(document.querySelectorAll('#graph line')).every(l => l.getAttribute('opacity') === '0')")
    p.locator("#similarityCheck").check()
    assert p.evaluate("() => Array.from(document.querySelectorAll('#graph line')).every(l => l.getAttribute('opacity') !== '0')")


def test_no_dead_edge_toggles(coachella):
    """BUG-29 regression: the GENRE EDGES toggle did nothing (no edge had type 'genre'), so it was removed.
    Every remaining edge toggle must match at least one edge type the API actually serves."""
    _open(coachella)
    p = coachella.page
    assert p.locator("#genreCheck").count() == 0
    types = {e["type"] for lvl in _graph_json(p)["edges_by_level"].values() for e in lvl}
    assert types == {"similarity"}
    assert coachella.page_errors == []


def test_discovery_mode_reveals_subset_then_restores(coachella):
    _open(coachella)
    p = coachella.page
    p.locator("label:has(#discoveryToggle), #discoveryToggle").first.click(force=True)
    p.wait_for_timeout(700)
    visible = coachella.visible_node_names()
    assert 20 <= len(visible) < TOTAL_NODES
    p.locator("#discoveryToggle").evaluate("e => { e.checked = false; e.dispatchEvent(new Event('change')); }")
    p.wait_for_timeout(700)
    assert len(coachella.visible_node_names()) == TOTAL_NODES


def test_discovery_click_fringe_then_listen_discovers_it(coachella):
    _open(coachella)
    p = coachella.page
    p.locator("#discoveryToggle").evaluate("e => { e.checked = true; e.dispatchEvent(new Event('change')); }")
    p.wait_for_timeout(700)
    # pick an ambassador (visible but undiscovered, hollow) node
    target = p.evaluate("() => Array.from(document.querySelectorAll('#graph circle'))"
                        ".find(c => getComputedStyle(c).display !== 'none' && c.getAttribute('fill') === 'none')?.__data__.name")
    if not target:
        pytest.skip("no ambassador nodes for this seed set")
    coachella.click_node(target)
    p.locator(".play-btn").first.wait_for()
    p.locator(".play-btn").first.click()
    p.wait_for_function(f"() => d3.selectAll('#graph circle').filter(d => d.name === {json.dumps(target)}).attr('fill') !== 'none'", timeout=5000)


# ── Auth ──────────────────────────────────────────────────────────────────────

def test_lastfm_login_personalizes_graph(coachella, monkeypatch):
    import app as coachella_app
    monkeypatch.setattr(coachella_app, "lastfm_top",
                        lambda user, limit=100: [{"name": "Laufey", "score": 1.0}] if user == "bob" else [])
    _open(coachella)
    p = coachella.page
    r_before = float(coachella.node("Laufey").get_attribute("r"))
    p.locator("#lastfmUsername").fill("bob")
    p.locator("#lastfmGo").click()
    p.locator("#lastfmConnected").wait_for()
    assert p.locator("#lastfmUserLabel").inner_text() == "bob"
    assert p.locator("#spotifyCol").is_hidden()
    p.wait_for_timeout(1500)
    coachella.wait_for_graph(TOTAL_NODES)
    assert float(coachella.node("Laufey").get_attribute("r")) > r_before

    p.locator("#lastfmDisconnect").click()
    p.locator("#lastfmInput").wait_for()
    p.reload()
    coachella.wait_for_graph(TOTAL_NODES)
    assert p.locator("#lastfmConnected").is_hidden()


def test_lastfm_unknown_user_shows_error(coachella, monkeypatch):
    import lastfm.fetch
    monkeypatch.setattr(lastfm.fetch, "get_top_artists", lambda user, limit=100: [])
    _open(coachella)
    p = coachella.page
    p.locator("#lastfmUsername").fill("ghost")
    p.locator("#lastfmUsername").press("Enter")
    p.locator("#lastfmError").wait_for()
    p.locator("#lastfmUsername").type("x")
    assert p.locator("#lastfmError").is_hidden()


def test_spotify_connect_navigates_to_login(coachella):
    _open(coachella)
    with coachella.page.expect_request(re.compile(r"accounts\.spotify\.com/authorize")):
        coachella.page.locator("#spotifyBtn").click()


# ── Layout / viewport ─────────────────────────────────────────────────────────

def test_svg_tracks_window_resize(coachella):
    """BUG-09 regression: W/H were captured once at import."""
    _open(coachella)
    coachella.page.set_viewport_size({"width": 900, "height": 700})
    coachella.page.wait_for_timeout(500)
    g = coachella.page.locator("#graph")
    assert (g.get_attribute("width"), g.get_attribute("height")) == ("900", "700")
    assert coachella.page.locator("#graph > rect").get_attribute("width") == "900"


def test_whole_graph_fits_viewport_on_load(coachella):
    """UX-01 regression: part of the graph used to start outside the viewport."""
    _open(coachella)
    vp = coachella.page.viewport_size
    outside = coachella.page.evaluate("([w,h]) => Array.from(document.querySelectorAll('#graph circle')).filter(c => {"
                                      "const b = c.getBoundingClientRect(); return b.right < 0 || b.bottom < 0 || b.left > w || b.top > h; }).length",
                                      [vp["width"], vp["height"]])
    assert outside == 0, f"{outside} nodes start off-screen"


def test_most_labels_visible_for_anonymous_users(coachella):
    """UX-02 regression: linear listener scaling used to hide 58% of labels (score < 0.1)."""
    _open(coachella)
    hidden = coachella.page.evaluate("() => Array.from(document.querySelectorAll('#graph text')).filter(t => t.getAttribute('opacity') === '0').length")
    assert hidden / TOTAL_NODES < 0.15


# ── Mobile ────────────────────────────────────────────────────────────────────

def _tappable_node(c):
    """Name of a large node whose centre is on-screen and not covered by the controls."""
    c.page.touchscreen.tap(5, c.page.viewport_size["height"] - 5)  # tap outside → controls minimise
    c.page.wait_for_timeout(300)
    c.tag_nodes()
    return c.page.evaluate("""() => Array.from(document.querySelectorAll('#graph circle'))
        .map(el => { const b = el.getBoundingClientRect(); return {el, x: b.x + b.width/2, y: b.y + b.height/2, r: b.width}; })
        .filter(o => o.x > 20 && o.x < innerWidth - 20 && o.y > 120 && o.y < innerHeight * 0.5)
        .filter(o => document.elementFromPoint(o.x, o.y) === o.el)
        .sort((a, b) => b.r - a.r)[0]?.el.__data__.name""")


def test_mobile_initial_view_is_usable(coachella_mobile):
    """UX-01 regression: only ~30/142 nodes started on-screen at 390x844, under expanded controls."""
    c = coachella_mobile
    c.goto()
    c.wait_for_graph(TOTAL_NODES)
    on_screen = c.page.evaluate("() => Array.from(document.querySelectorAll('#graph circle')).filter(e => {"
                                "const b = e.getBoundingClientRect(); return b.left >= 0 && b.right <= innerWidth && b.top >= 0 && b.bottom <= innerHeight; }).length")
    assert on_screen / TOTAL_NODES > 0.9
    assert c.page.locator("#controls").evaluate("e => e.classList.contains('minimized')")


def test_mobile_tap_opens_drawer_and_background_dismisses(coachella_mobile):
    c = coachella_mobile
    c.goto()
    c.wait_for_graph(TOTAL_NODES)
    p = c.page
    name = _tappable_node(c)
    box = c.node(name).bounding_box()
    p.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    p.locator("#artistDrawer.drawer-collapsed").wait_for()
    assert p.locator("#drawerHeroName").inner_text() == name
    p.locator(".drawer-track-row").first.wait_for()
    assert p.locator("#artistPanel.open").count() == 0, "desktop panel must not open on mobile"
    p.wait_for_timeout(800)
    p.touchscreen.tap(195, 120)
    p.wait_for_function("() => /drawer-(hidden|peek)/.test(document.getElementById('artistDrawer').className)")


def test_mobile_drawer_expands_on_track_tap(coachella_mobile):
    c = coachella_mobile
    c.goto()
    c.wait_for_graph(TOTAL_NODES)
    name = _tappable_node(c)
    box = c.node(name).bounding_box()
    p = c.page
    p.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    p.locator(".drawer-track-row").first.wait_for()
    p.locator(".drawer-track-row").first.tap()
    p.locator("#artistDrawer.drawer-expanded").wait_for()
    assert p.locator(".drawer-track-submenu.open").count() == 1
