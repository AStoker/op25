# Copyright 2017, 2018 Max H. Parke KA1RBI
#
# This file is part of OP25
#
# OP25 is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.
#
# OP25 is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public
# License for more details.
#
# You should have received a copy of the GNU General Public License
# along with OP25; see the file COPYING. If not, write to the Free
# Software Foundation, Inc., 51 Franklin Street, Boston, MA
# 02110-1301, USA.

from __future__ import annotations

import sys
import os
import traceback
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wsgiref.types import StartResponse, WSGIEnvironment

from waitress.server import create_server  # type: ignore[import-untyped]

# Directory containing built frontend assets (Vite output)
_DIST_DIR = os.path.realpath(
    os.path.join(os.path.dirname(__file__), '..', 'www', 'dist')
)

CONTENT_TYPES = {
    'html': 'text/html',
    'css':  'text/css',
    'js':   'application/javascript',
    'mjs':  'application/javascript',
    'json': 'application/json',
    'png':  'image/png',
    'jpg':  'image/jpeg',
    'jpeg': 'image/jpeg',
    'gif':  'image/gif',
    'svg':  'image/svg+xml',
    'ico':  'image/x-icon',
    'woff':  'font/woff',
    'woff2': 'font/woff2',
    'ttf':   'font/ttf',
    'eot':   'application/vnd.ms-fontobject',
    'map':  'application/json',
    'txt':  'text/plain',
}


def _resolve_dist_path(url_path: str) -> str | None:
    """Resolve *url_path* to a real filesystem path inside _DIST_DIR.

    Returns the resolved path string on success, or None if the path would
    escape the dist directory (path-traversal guard).
    """
    # Strip leading slash and normalise (handles %xx, duplicate slashes, etc.)
    rel = url_path.lstrip('/')
    candidate = os.path.realpath(os.path.join(_DIST_DIR, rel))
    # Guard: resolved path must stay inside the dist directory
    if not candidate.startswith(_DIST_DIR + os.sep) and candidate != _DIST_DIR:
        return None
    return candidate


def static_file(environ: WSGIEnvironment) -> tuple[str, str, bytes]:
    """Serve a static file from _DIST_DIR.

    For the root path (or any path that does not resolve to a regular file),
    serve index.html so that the React SPA can handle client-side routing.
    """
    url_path = environ.get('PATH_INFO', '/')

    # Attempt to serve the exact requested file first.
    if url_path != '/':
        resolved = _resolve_dist_path(url_path)
        if resolved and os.path.isfile(resolved):
            ext = resolved.rsplit('.', 1)[-1].lower() if '.' in resolved else ''
            content_type = CONTENT_TYPES.get(ext, 'application/octet-stream')
            try:
                with open(resolved, 'rb') as f:
                    output = f.read()
                return '200 OK', content_type, output
            except OSError:
                pass  # fall through to index.html

    # Fall back to index.html for SPA client-side routing.
    index_path = os.path.join(_DIST_DIR, 'index.html')
    if os.path.isfile(index_path):
        with open(index_path, 'rb') as f:
            output = f.read()
        return '200 OK', 'text/html', output

    # dist not built yet
    return '503 Service Unavailable', 'text/plain', b'Frontend not built. Run "yarn build" inside www/app.'


CORS_HEADERS = [
    ('Access-Control-Allow-Origin',  '*'),
    ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
    ('Access-Control-Allow-Headers', 'Content-Type'),
]


def http_request(environ: WSGIEnvironment, start_response: StartResponse) -> list[bytes]:
    method: str = environ.get('REQUEST_METHOD', 'GET')

    if method == 'GET':
        status, content_type, raw_output = static_file(environ)
        output: bytes = raw_output
    else:
        status, content_type = '405 Method Not Allowed', 'text/plain'
        output = b'Method Not Allowed'

    response_headers: list[tuple[str, str]] = [
        ('Content-type', content_type),
        ('Content-Length', str(len(output))),
        *CORS_HEADERS,
    ]
    start_response(status, response_headers)
    return [output]


def application(environ: WSGIEnvironment, start_response: StartResponse) -> list[bytes]:
    try:
        return http_request(environ, start_response)
    except Exception:
        sys.stderr.write('application: request failed:\n%s\n' % traceback.format_exc())
        sys.exit(1)


class http_server(object):
    def __init__(self, endpoint: str, **kwds: Any) -> None:
        host, port = endpoint.split(':')
        try:
            self.server = create_server(application, host=host, port=int(port), threads=6)
        except (OSError, ValueError):
            sys.stderr.write('Failed to create http server\n%s\n' % traceback.format_exc())
            sys.exit(1)

    def run(self):
        self.server.run()
