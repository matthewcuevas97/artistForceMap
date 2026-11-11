"""
Browser-level fixtures: live Flask servers + Playwright driving the locally
installed Google Chrome (channel="chrome"), fully offline:

  * d3 is served from tests/e2e/vendor instead of cdnjs
  * Google Fonts and every other third-party host are aborted / stubbed
  * audio previews come from a local static server (silent WAV)
  * backend calls to Deezer / Last.fm are monkeypatched per test
"""

import functools
import http.server
import io
import os
import struct
import threading
import time
import wave
from pathlib import Path

import pytest
from werkzeug.serving import make_server

VENDOR = Path(__file__).parent / "vendor"
D3_JS = (VENDOR / "d3-7.9.0.min.js").read_bytes()

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


def pytest_collection_modifyitems(items):
    for item in items:
        if "/e2e/" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)


# ── Servers ───────────────────────────────────────────────────────────────────

class _LiveServer:
    def __init__(self, wsgi_app):
        self.srv = make_server("127.0.0.1", 0, wsgi_app, threaded=True)
        self.url = f"http://127.0.0.1:{self.srv.server_port}"
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.srv.shutdown()


@pytest.fixture(scope="session")
def coachella_server():
    import app as coachella
    s = _LiveServer(coachella.app)
    yield s
    s.stop()


@pytest.fixture(scope="session")
def universal_server():
    import app_universal
    s = _LiveServer(app_universal.app)
    yield s
    s.stop()


def _silent_wav(seconds=3):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
        w.writeframes(struct.pack("<h", 0) * 8000 * seconds)
    return buf.getvalue()


@pytest.fixture(scope="session")
def media_server(tmp_path_factory):
    root = tmp_path_factory.mktemp("media")
    (root / "preview.wav").write_bytes(_silent_wav())
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


# ── Browser ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def browser():
    if sync_playwright is None:
        pytest.skip("playwright not installed")
    pw = sync_playwright().start()
    try:
        b = pw.chromium.launch(channel="chrome", headless=os.getenv("HEADED") is None,
                               args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"])
    except Exception as exc:  # no local Chrome
        pw.stop()
        pytest.skip(f"cannot launch Chrome: {exc}")
    yield b
    b.close()
    pw.stop()


def _route_offline(context, allowed_origins):
    def handler(route):
        url = route.request.url
        if "cdnjs.cloudflare.com/ajax/libs/d3/" in url:
            return route.fulfill(status=200, body=D3_JS, content_type="application/javascript")
        if any(url.startswith(o) for o in allowed_origins):
            return route.continue_()
        return route.abort()
    context.route("**/*", handler)


class PageHelper:
    """Wraps a Playwright page with graph-aware helpers and error capture."""

    def __init__(self, page, base_url):
        self.page = page
        self.base = base_url
        self.console_errors = []
        self.page_errors = []
        page.on("console", lambda m: m.type == "error" and self.console_errors.append(m.text))
        page.on("pageerror", lambda e: self.page_errors.append(str(e)))

    def goto(self, path="/"):
        self.page.goto(self.base + path)

    # Tag every circle with its datum name so tests can address nodes.
    def tag_nodes(self):
        self.page.evaluate(
            "() => d3.selectAll('#graph circle').attr('data-name', d => d && d.name)")

    def wait_for_graph(self, n=None, timeout=20000):
        self.page.wait_for_function(
            f"() => document.querySelectorAll('#graph circle').length {'>= 1' if n is None else '=== ' + str(n)}",
            timeout=timeout)
        self.wait_settled()
        self.tag_nodes()

    def wait_settled(self, timeout=8.0):
        """Wait until node positions stop moving (simulation cooled)."""
        snap = "() => Array.from(document.querySelectorAll('#graph circle')).slice(0,40).map(c => c.getAttribute('cx')+','+c.getAttribute('cy')).join('|')"
        end = time.time() + timeout
        prev = self.page.evaluate(snap)
        while time.time() < end:
            self.page.wait_for_timeout(250)
            cur = self.page.evaluate(snap)
            if cur == prev:
                return
            prev = cur

    def node(self, name):
        return self.page.locator(f'#graph circle[data-name="{name}"]')

    def click_node(self, name):
        """Real mouse click at the node centre when it is hit-testable, else dispatch."""
        self.tag_nodes()
        loc = self.node(name)
        box = loc.bounding_box()
        assert box, f"node {name!r} not rendered/visible"
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        hit = self.page.evaluate(
            "([x,y,n]) => { const e = document.elementFromPoint(x,y); return !!e && e.getAttribute('data-name') === n; }",
            [cx, cy, name])
        if hit:
            self.page.mouse.click(cx, cy)
        else:
            loc.dispatch_event("click")

    def visible_node_names(self):
        return self.page.evaluate(
            "() => Array.from(document.querySelectorAll('#graph circle'))"
            ".filter(c => getComputedStyle(c).display !== 'none').map(c => c.__data__.name)")


@pytest.fixture
def coachella(browser, coachella_server, coachella_tracks):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    _route_offline(ctx, [coachella_server.url, coachella_tracks])
    helper = PageHelper(ctx.new_page(), coachella_server.url)
    yield helper
    ctx.close()


@pytest.fixture
def coachella_mobile(browser, coachella_server, coachella_tracks):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True,
                              device_scale_factor=3)
    _route_offline(ctx, [coachella_server.url, coachella_tracks])
    helper = PageHelper(ctx.new_page(), coachella_server.url)
    yield helper
    ctx.close()


@pytest.fixture
def universal(browser, universal_server, media_server):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    _route_offline(ctx, [universal_server.url, media_server])
    helper = PageHelper(ctx.new_page(), universal_server.url)
    yield helper
    ctx.close()


@pytest.fixture
def coachella_tracks(monkeypatch, media_server):
    """Replace live Deezer lookups with deterministic tracks that have a playable preview."""
    import app as coachella

    def fake_refresh(tracks, artist_names):
        out = []
        for i, t in enumerate(tracks or [{"name": "Fallback Song"}]):
            t = dict(t)
            t["preview_url"] = f"{media_server}/preview.wav?track={i}" if i < 3 else ""
            t["album_art"] = ""
            out.append(t)
        return out

    monkeypatch.setattr(coachella, "refresh_track_previews", fake_refresh)
    return media_server
