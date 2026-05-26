"""
Contract tests for http_server_new — static file serving.

These tests define the expected behaviour that the GUI front end can rely on:

  - GET /              → 200 text/html  (index.html, SPA entry point)
  - GET /assets/*.js   → 200 application/javascript
  - GET /assets/*.css  → 200 text/css
  - GET /assets/*.svg  → 200 image/svg+xml
  - GET /unknown/route → 200 text/html  (SPA fallback for client-side routing)
  - Path traversal     → does NOT escape dist dir (falls back to index.html)
  - Non-GET methods    → 405
  - CORS headers       → present on every response
  - Unbuilt frontend   → 503 with a helpful message
"""

import pytest
from tests.conftest import WSGITestClient


# ---------------------------------------------------------------------------
# Root / SPA entry point
# ---------------------------------------------------------------------------


class TestRootAndSPAFallback:
    def test_root_returns_200(self, client: WSGITestClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200

    def test_root_content_type_is_html(self, client: WSGITestClient) -> None:
        resp = client.get("/")
        assert resp.headers["Content-type"] == "text/html"

    def test_root_body_is_index_html(self, client: WSGITestClient) -> None:
        resp = client.get("/")
        assert b"OP25" in resp.body

    def test_unknown_route_falls_back_to_index(self, client: WSGITestClient) -> None:
        """Client-side routes must get index.html so the React router can handle them."""
        resp = client.get("/talkgroups/42")
        assert resp.status_code == 200
        assert resp.headers["Content-type"] == "text/html"
        assert b"OP25" in resp.body

    def test_deeply_nested_unknown_route_falls_back(self, client: WSGITestClient) -> None:
        resp = client.get("/a/b/c/d")
        assert resp.status_code == 200
        assert resp.headers["Content-type"] == "text/html"


# ---------------------------------------------------------------------------
# Static asset serving
# ---------------------------------------------------------------------------


class TestStaticAssets:
    def test_js_asset_returns_200(self, client: WSGITestClient) -> None:
        resp = client.get("/assets/app-abc123.js")
        assert resp.status_code == 200

    def test_js_asset_content_type(self, client: WSGITestClient) -> None:
        resp = client.get("/assets/app-abc123.js")
        assert resp.headers["Content-type"] == "application/javascript"

    def test_js_asset_body(self, client: WSGITestClient) -> None:
        resp = client.get("/assets/app-abc123.js")
        assert b'console.log("op25")' in resp.body

    def test_css_asset_content_type(self, client: WSGITestClient) -> None:
        resp = client.get("/assets/app-abc123.css")
        assert resp.headers["Content-type"] == "text/css"

    def test_svg_asset_content_type(self, client: WSGITestClient) -> None:
        resp = client.get("/assets/logo-def456.svg")
        assert resp.headers["Content-type"] == "image/svg+xml"

    def test_content_length_header_matches_body(self, client: WSGITestClient) -> None:
        resp = client.get("/assets/app-abc123.js")
        assert int(resp.headers["Content-Length"]) == len(resp.body)


# ---------------------------------------------------------------------------
# Security: path traversal
# ---------------------------------------------------------------------------


class TestPathTraversal:
    def test_dotdot_does_not_escape_dist(self, client: WSGITestClient, tmp_path: pytest.TempPathFactory) -> None:
        """A traversal attempt must never serve a file outside dist/."""
        resp = client.get("/../../../etc/passwd")
        # Must not succeed with the traversal target; fallback to index or 4xx
        assert resp.status_code in (200, 403, 404)
        if resp.status_code == 200:
            assert resp.headers["Content-type"] == "text/html"

    def test_encoded_dotdot_does_not_escape_dist(self, client: WSGITestClient) -> None:
        resp = client.get("/..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code in (200, 403, 404)
        if resp.status_code == 200:
            assert resp.headers["Content-type"] == "text/html"


# ---------------------------------------------------------------------------
# HTTP method handling
# ---------------------------------------------------------------------------


class TestMethodHandling:
    def test_post_returns_405(self, client: WSGITestClient) -> None:
        resp = client.post("/")
        assert resp.status_code == 405


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


class TestCORSHeaders:
    @pytest.mark.parametrize("path", ["/", "/assets/app-abc123.js", "/nonexistent"])
    def test_cors_origin_header_present(self, client: WSGITestClient, path: str) -> None:
        resp = client.get(path)
        assert "Access-Control-Allow-Origin" in resp.headers

    def test_cors_origin_is_wildcard(self, client: WSGITestClient) -> None:
        resp = client.get("/")
        assert resp.headers["Access-Control-Allow-Origin"] == "*"


# ---------------------------------------------------------------------------
# Unbuilt frontend
# ---------------------------------------------------------------------------


class TestUnbuiltFrontend:
    def test_missing_dist_returns_503(self, empty_dist_dir: WSGITestClient) -> None:
        resp = empty_dist_dir.get("/")
        assert resp.status_code == 503

    def test_missing_dist_body_has_hint(self, empty_dist_dir: WSGITestClient) -> None:
        resp = empty_dist_dir.get("/")
        assert b"yarn build" in resp.body
