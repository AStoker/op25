import io
import sys
import os
from typing import Any

import pytest

# Ensure apps/ is importable directly (no package install needed)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class WSGITestResponse:
    """Captures the result of a single WSGI call."""

    def __init__(self, status: str, headers: list[tuple[str, str]], body: bytes) -> None:
        self.status = status
        self.status_code = int(status.split(" ", 1)[0])
        self.headers: dict[str, str] = dict(headers)
        self.body = body
        self.text = body.decode()


class WSGITestClient:
    """Minimal in-process WSGI test client — no network required."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def get(self, path: str) -> WSGITestResponse:
        return self._request("GET", path)

    def post(self, path: str, body: bytes = b"") -> WSGITestResponse:
        return self._request("POST", path, body)

    def _request(self, method: str, path: str, body: bytes = b"") -> WSGITestResponse:
        environ: dict[str, Any] = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "SERVER_NAME": "localhost",
            "SERVER_PORT": "8000",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": io.BytesIO(body),
            "wsgi.errors": sys.stderr,
            "wsgi.url_scheme": "http",
            "wsgi.multithread": False,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
            "CONTENT_LENGTH": str(len(body)),
            "CONTENT_TYPE": "application/octet-stream",
        }

        status_holder: list[str] = []
        headers_holder: list[list[tuple[str, str]]] = []

        def start_response(
            status: str,
            headers: list[tuple[str, str]],
            exc_info: Any = None,
        ) -> None:
            status_holder.append(status)
            headers_holder.append(headers)

        chunks = self.app(environ, start_response)
        return WSGITestResponse(
            status=status_holder[0],
            headers=headers_holder[0],
            body=b"".join(chunks),
        )


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def dist_dir(tmp_path: Any) -> Any:
    """A minimal fake Vite dist directory."""
    d = tmp_path / "dist"
    d.mkdir()
    (d / "index.html").write_bytes(b"<html><body>OP25</body></html>")

    assets = d / "assets"
    assets.mkdir()
    (assets / "app-abc123.js").write_bytes(b'console.log("op25")')
    (assets / "app-abc123.css").write_bytes(b"body { margin: 0 }")
    (assets / "logo-def456.svg").write_bytes(b"<svg></svg>")

    return d


@pytest.fixture()
def client(dist_dir: Any, monkeypatch: pytest.MonkeyPatch) -> WSGITestClient:
    """A WSGITestClient wired to http_server_new with a fake dist dir."""
    import http_server_new

    monkeypatch.setattr(http_server_new, "_DIST_DIR", str(dist_dir))
    return WSGITestClient(http_server_new.application)


@pytest.fixture()
def empty_dist_dir(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patches _DIST_DIR to an empty directory (simulates un-built frontend)."""
    import http_server_new

    d = tmp_path / "dist"
    d.mkdir()
    monkeypatch.setattr(http_server_new, "_DIST_DIR", str(d))
    return WSGITestClient(http_server_new.application)
