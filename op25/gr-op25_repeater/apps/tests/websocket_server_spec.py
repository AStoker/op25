"""
Contract tests for websocket_server — static file serving.

These tests define the expected behaviour that the GUI front end can rely on:

  - GET /              → 200 text/html  (index.html, SPA entry point)
  - GET /assets/*.js   → 200 text/javascript
  - GET /assets/*.css  → 200 text/css
  - GET /assets/*.svg  → 200 image/svg+xml
  - GET /unknown/route → 200 text/html  (SPA fallback for client-side routing)
  - Path traversal     → does NOT escape dist dir (falls back to index.html)
  - Non-GET methods    → 405
  - CORS headers       → present when the request carries an Origin
  - Unbuilt frontend   → 503 with a helpful message
"""

import pytest
from typing import Any


# ---------------------------------------------------------------------------
# Root / SPA entry point
# ---------------------------------------------------------------------------


class TestRootAndSPAFallback:
    def test_root_returns_200(self, client: Any) -> None:
        resp = client.get("/")
        assert resp.status_code == 200

    def test_root_content_type_is_html(self, client: Any) -> None:
        resp = client.get("/")
        assert resp.headers["content-type"].split(";")[0] == "text/html"

    def test_root_body_is_index_html(self, client: Any) -> None:
        resp = client.get("/")
        assert b"OP25" in resp.content

    def test_unknown_route_falls_back_to_index(self, client: Any) -> None:
        """Client-side routes must get index.html so the React router can handle them."""
        resp = client.get("/talkgroups/42")
        assert resp.status_code == 200
        assert resp.headers["content-type"].split(";")[0] == "text/html"
        assert b"OP25" in resp.content

    def test_deeply_nested_unknown_route_falls_back(self, client: Any) -> None:
        resp = client.get("/a/b/c/d")
        assert resp.status_code == 200
        assert resp.headers["content-type"].split(";")[0] == "text/html"


# ---------------------------------------------------------------------------
# Static asset serving
# ---------------------------------------------------------------------------


class TestStaticAssets:
    def test_js_asset_returns_200(self, client: Any) -> None:
        resp = client.get("/assets/app-abc123.js")
        assert resp.status_code == 200

    def test_js_asset_content_type(self, client: Any) -> None:
        resp = client.get("/assets/app-abc123.js")
        assert resp.headers["content-type"].split(";")[0] == "text/javascript"

    def test_js_asset_body(self, client: Any) -> None:
        resp = client.get("/assets/app-abc123.js")
        assert b'console.log("op25")' in resp.content

    def test_css_asset_content_type(self, client: Any) -> None:
        resp = client.get("/assets/app-abc123.css")
        assert resp.headers["content-type"].split(";")[0] == "text/css"

    def test_svg_asset_content_type(self, client: Any) -> None:
        resp = client.get("/assets/logo-def456.svg")
        assert resp.headers["content-type"].split(";")[0] == "image/svg+xml"

    def test_content_length_header_matches_body(self, client: Any) -> None:
        resp = client.get("/assets/app-abc123.js")
        assert int(resp.headers["Content-Length"]) == len(resp.content)


# ---------------------------------------------------------------------------
# Security: path traversal
# ---------------------------------------------------------------------------


class TestPathTraversal:
    def test_dotdot_does_not_escape_dist(self, client: Any, tmp_path: pytest.TempPathFactory) -> None:
        """A traversal attempt must never serve a file outside dist/."""
        resp = client.get("/../../../etc/passwd")
        # Must not succeed with the traversal target; fallback to index or 4xx
        assert resp.status_code in (200, 403, 404)
        if resp.status_code == 200:
            assert resp.headers["content-type"].split(";")[0] == "text/html"

    def test_encoded_dotdot_does_not_escape_dist(self, client: Any) -> None:
        resp = client.get("/..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code in (200, 403, 404)
        if resp.status_code == 200:
            assert resp.headers["content-type"].split(";")[0] == "text/html"


# ---------------------------------------------------------------------------
# HTTP method handling
# ---------------------------------------------------------------------------


class TestMethodHandling:
    def test_post_returns_405(self, client: Any) -> None:
        resp = client.post("/")
        assert resp.status_code == 405


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


class TestCORSHeaders:
    ORIGIN = {"Origin": "http://example.test"}

    @pytest.mark.parametrize("path", ["/", "/assets/app-abc123.js", "/nonexistent"])
    def test_cors_origin_header_present(self, client: Any, path: str) -> None:
        resp = client.get(path, headers=self.ORIGIN)
        assert "Access-Control-Allow-Origin" in resp.headers

    def test_cors_origin_is_wildcard(self, client: Any) -> None:
        resp = client.get("/", headers=self.ORIGIN)
        assert resp.headers["Access-Control-Allow-Origin"] == "*"

    def test_no_cors_header_without_origin(self, client: Any) -> None:
        """A same-origin request carries no Origin, so CORS must stay silent."""
        resp = client.get("/")
        assert "Access-Control-Allow-Origin" not in resp.headers


# ---------------------------------------------------------------------------
# Unbuilt frontend
# ---------------------------------------------------------------------------


class TestUnbuiltFrontend:
    def test_missing_dist_returns_503(self, empty_dist_dir: Any) -> None:
        resp = empty_dist_dir.get("/")
        assert resp.status_code == 503

    def test_missing_dist_body_has_hint(self, empty_dist_dir: Any) -> None:
        resp = empty_dist_dir.get("/")
        assert b"yarn build" in resp.content


# ---------------------------------------------------------------------------
# Stale-asset handling and caching
#
# An add-on update changes every content-hashed filename. A browser holding a
# cached index.html then asks for chunks that no longer exist, and the SPA
# fallback used to answer those with index.html -- so the browser reported
# "'text/html' is not a valid JavaScript MIME type for module script" and
# rendered nothing, with no hint that the real problem was a stale document.
# ---------------------------------------------------------------------------


class TestStaleAssetRequests:
    def test_missing_js_returns_404_not_index(self, client: Any) -> None:
        resp = client.get("/op25-vendor-mui-DEADBEEF.js")
        assert resp.status_code == 404
        assert resp.headers["content-type"].split(";")[0] != "text/html"

    def test_missing_css_returns_404(self, client: Any) -> None:
        assert client.get("/op25-react-DEADBEEF.css").status_code == 404

    @pytest.mark.parametrize("path", [
        "/assets/gone.mjs", "/assets/gone.map", "/assets/gone.woff2",
        "/assets/gone.png", "/assets/gone.svg", "/assets/gone.wasm",
    ])
    def test_other_asset_suffixes_also_404(self, client: Any, path: str) -> None:
        assert client.get(path).status_code == 404

    def test_404_body_explains_the_stale_document(self, client: Any) -> None:
        # The whole point is that the failure names its own cause.
        body = client.get("/op25-vendor-mui-DEADBEEF.js").text.lower()
        assert "stale" in body and "reload" in body

    def test_extensionless_routes_still_reach_the_spa(self, client: Any) -> None:
        # The asset rule must not swallow client-side routing.
        for path in ("/talkgroups/42", "/a/b/c", "/settings"):
            resp = client.get(path)
            assert resp.status_code == 200, path
            assert resp.headers["content-type"].split(";")[0] == "text/html"


class TestCacheHeaders:
    def test_index_is_never_cached(self, client: Any) -> None:
        # index.html is the only URL that is stable across builds, so a cached
        # copy is what pairs new chunk files with an old chunk list.
        assert "no-store" in client.get("/").headers["cache-control"]

    def test_spa_route_fallback_is_never_cached(self, client: Any) -> None:
        assert "no-store" in client.get("/talkgroups/42").headers["cache-control"]

    def test_hashed_assets_are_immutable(self, client: Any) -> None:
        cc = client.get("/assets/app-abc123.js").headers["cache-control"]
        assert "immutable" in cc and "max-age=31536000" in cc

    def test_asset_404_is_not_cached(self, client: Any) -> None:
        # Caching this would outlive the reload that fixes it.
        resp = client.get("/op25-vendor-mui-DEADBEEF.js")
        assert "no-store" in resp.headers["cache-control"]
