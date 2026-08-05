# Server Tests

Tests for `websocket_server.py` using pytest. Tests run entirely in-process — no network, no running server required.

## Setup

From the `apps/` directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Running tests

```sh
# From apps/
.venv/bin/pytest

# Verbose output
.venv/bin/pytest -v

# A specific file
.venv/bin/pytest tests/websocket_server_spec.py

# A specific test class or function
.venv/bin/pytest tests/websocket_server_spec.py::TestCORSHeaders
.venv/bin/pytest tests/websocket_server_spec.py::TestCORSHeaders::test_cors_origin_is_wildcard
```

## Writing tests

### Fixtures

`conftest.py` provides three fixtures:

| Fixture | What it gives you |
|---|---|
| `client` | A FastAPI `TestClient` pointed at a fake `dist/` with `index.html` and a few assets |
| `dist_dir` | The `pathlib.Path` to that fake dist directory (use to add extra files) |
| `empty_dist_dir` | A FastAPI `TestClient` with an empty dist (simulates an unbuilt frontend) |

### Example

```python
def test_my_new_behaviour(client: Any) -> None:
    resp = client.get("/some/path")
    assert resp.status_code == 200
    assert resp.headers["Content-type"] == "text/html"
    assert b"expected content" in resp.body
```

To test with a custom file in dist:

```python
def test_custom_asset(dist_dir, monkeypatch) -> None:
    import websocket_server
    (dist_dir / "custom.js").write_bytes(b"export default 42")
    monkeypatch.setattr(websocket_server, "_DIST_DIR", str(dist_dir))
    client = TestClient(websocket_server.app)

    resp = client.get("/custom.js")
    assert resp.status_code == 200
    assert b"42" in resp.body
```

### Test organisation

Group related tests in a class prefixed with `Test`. Each test function must be prefixed with `test_`. Files must be named `<subject>_spec.py`.

```
tests/
  conftest.py                   # shared fixtures
  websocket_server_spec.py       # static file serving contract
  <next_feature>_spec.py        # add new files as features are added
```

## Adding a new test file

1. Create `tests/<feature>_spec.py`
2. Import fixtures from `conftest.py` via pytest's automatic injection (no explicit import needed)
3. Run `pytest` to confirm everything passes
