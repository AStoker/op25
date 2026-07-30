import sys
import os
from typing import Any

import pytest

# Ensure apps/ is importable directly (no package install needed)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


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
def client(dist_dir: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A TestClient wired to websocket_server with a fake dist dir.

    The server these specs were originally written against (http_server_new,
    WSGI) became websocket_server.py on FastAPI, so this drives the ASGI app.
    _DIST_DIR is read at request time, so patching the module global suffices.
    """
    from fastapi.testclient import TestClient
    import websocket_server

    monkeypatch.setattr(websocket_server, "_DIST_DIR", str(dist_dir))
    return TestClient(websocket_server.app)


@pytest.fixture()
def empty_dist_dir(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patches _DIST_DIR to an empty directory (simulates un-built frontend)."""
    from fastapi.testclient import TestClient
    import websocket_server

    d = tmp_path / "dist"
    d.mkdir()
    monkeypatch.setattr(websocket_server, "_DIST_DIR", str(d))
    return TestClient(websocket_server.app)
