"""Browser tests for the universal map prototype (app_universal.py + static/js/universal_map.js)."""

import json
import time

import pytest
from playwright.sync_api import TimeoutError as PWTimeout

from backend import user_data
from backend.progress import report

pytestmark = pytest.mark.e2e

XSS = '<img src=x onerror="window.__xss=1">'


def _node(name, listeners, genre="Pop", tags=("pop",), preview=None):
    return {"name": name, "listeners": listeners, "genre": genre, "tags": list(tags),
            "bio": f"{name} bio", "image_url": None,
            "top_tracks": [{"name": f"{name} Song", "preview_url": preview, "album_art": None}]}


@pytest.fixture
def fake_backend(monkeypatch, universal_server, media_server):
    import app_universal
    nodes = [
        _node("Mega Star", 5_000_000, preview=f"{media_server}/preview.wav"),
        _node("Mid Act", 300_000, genre="Electronic", tags=("house",)),
        _node("Tiny Band", 900, genre="Indie/Alt", tags=("indie",)),
    ]
    state = {"nodes": nodes, "fail": None}

    def fake_pipeline(auth):
        report("STEP 1: User Ingestion")
        report("✓ Fetched 25 top artists")
        time.sleep(0.4)  # let the browser paint progress before completion replaces it
        if state["fail"]:
            raise ValueError(state["fail"])
        user_data.save_user_map(auth["id"], {"nodes": state["nodes"],
                                             "edges": [{"source": "Mega Star", "target": "Mid Act"}]})

    monkeypatch.setattr(app_universal, "run_full_pipeline", fake_pipeline)
    monkeypatch.setattr(app_universal, "lastfm_top",
                        lambda user, limit=100: [{"name": "x", "score": 1}] if user == "bob" else [])
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
    assert universal.page_errors == []


def test_node_click_opens_panel_and_plays_preview(universal, fake_backend):
    _login(universal)
    _generate(universal)
    p = universal.page
    universal.click_node("Mega Star")
    p.locator("#artistPanel.open").wait_for()
    assert "Mega Star" in p.locator(".panel-name").inner_text()
    assert "5,000,000 listeners" in p.locator(".panel-meta").inner_text()
    p.locator(".track-play").click()
    p.wait_for_function("() => document.querySelector('.track-play').classList.contains('playing')")
    p.locator("#panelClose").click()
    assert p.locator("#artistPanel.open").count() == 0


def test_controls_labels_and_size(universal, fake_backend):
    _login(universal)
    _generate(universal)
    p = universal.page
    p.locator("#labelsCheck").uncheck()
    p.wait_for_timeout(400)
    assert p.evaluate("() => Array.from(document.querySelectorAll('#graph text.label')).every(t => t.getAttribute('opacity') === '0')")
    p.locator("#nodeSizeSlider").fill("2")
    p.wait_for_timeout(500)
    assert float(universal.node("Tiny Band").get_attribute("r")) == pytest.approx(10)


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="BUG-15: radius = 3 + log1p(listeners)/1e6 is effectively constant (always 4px)")
def test_node_radius_reflects_listeners(universal, fake_backend):
    _login(universal)
    _generate(universal)
    assert float(universal.node("Mega Star").get_attribute("r")) > float(universal.node("Tiny Band").get_attribute("r"))


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="BUG-14: the SSE loop's inner try/catch swallows `throw new Error(event.error)`, "
                          "so pipeline failures never reach the UI")
def test_pipeline_error_is_shown(universal, fake_backend):
    fake_backend["fail"] = "No enriched artists found"
    _login(universal)
    universal.page.locator("#initBtn").click()
    universal.page.wait_for_timeout(2000)
    assert "No enriched artists found" in universal.page.locator("#initStatus").inner_text()


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="BUG-16: a generated map is saved server-side but never reloaded (/api/map/get "
                          "is unused) — every visit requires re-running the whole pipeline")
def test_map_survives_reload(universal, fake_backend):
    _login(universal)
    _generate(universal)
    universal.page.reload()
    universal.page.wait_for_timeout(2000)
    assert universal.page.locator("#graph circle").count() == 3


@pytest.mark.xfail(strict=True, raises=PWTimeout,
                   reason="BUG-16b: clicking a node never calls /api/map/expand — the 'infinite map' "
                          "cannot actually be explored from the UI")
def test_node_click_expands_map(universal, fake_backend):
    _login(universal)
    _generate(universal)
    with universal.page.expect_request("**/api/map/expand", timeout=3000):
        universal.click_node("Mid Act")


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="BUG-19: universal_map.js builds the panel with unescaped innerHTML "
                          "(name/tags/bio/track names come from Last.fm/Deezer user content)")
def test_panel_escapes_untrusted_content(universal, fake_backend):
    fake_backend["nodes"][1]["tags"] = [XSS]
    fake_backend["nodes"][1]["bio"] = XSS
    _login(universal)
    _generate(universal)
    universal.click_node("Mid Act")
    universal.page.wait_for_timeout(800)
    assert universal.page.evaluate("() => window.__xss") is None


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="BUG-38: audio.play() rejection is never caught — dead previews raise "
                          "'Uncaught (in promise)' and the button still flips to 'playing'")
def test_dead_preview_handled_gracefully(universal, fake_backend):
    fake_backend["nodes"][0]["top_tracks"][0]["preview_url"] = "https://cdnt-preview.dzcdn.net/expired.mp3"
    _login(universal)
    _generate(universal)
    universal.click_node("Mega Star")
    universal.page.locator(".track-play").click()
    universal.page.wait_for_timeout(1500)
    assert not [e for e in universal.console_errors if "Uncaught (in promise)" in e]
    assert not universal.page.locator(".track-play.playing").count()
