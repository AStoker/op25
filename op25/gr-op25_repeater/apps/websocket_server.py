# Copyright 2024 OP25 Contributors
#
# This file is part of OP25
#
# OP25 is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.

"""FastAPI-based server that serves the static frontend and a WebSocket endpoint.

WebSocket message protocol
--------------------------
All messages are JSON objects with two required top-level keys:

    { "type": "<MESSAGE_TYPE>", "payload": { ... } }

Downstream (server → client)
    SYSTEM_STATE   – Overall system health/status snapshot
    SDR_STATUS     – Software-defined radio receiver metrics
    CALL_ACTIVITY  – Currently active / most-recent call details

Upstream (client → server)
    CALL_CONTROL   – Hold, skip, lockout, or whitelist a talk-group
    SYSTEM_CONTROL – Start/stop/restart the decoder, or adjust volume
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import struct
import sys
import traceback
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
import uvicorn

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DIST_DIR = os.path.realpath(
    os.path.join(os.path.dirname(__file__), '..', 'www', 'dist')
)

# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------

_config: dict[str, Any] | None = None


def load_config(path: str) -> dict[str, Any]:
    """Load a JSON config file, mirroring multi_rx.py's utf-8-sig fallback."""
    try:
        with open(path, encoding='utf-8-sig') as f:
            return json.loads(f.read())
    except UnicodeDecodeError:
        with open(path) as f:
            return json.loads(f.read())


def _initial_system_state() -> dict[str, Any]:
    """Build a SYSTEM_STATE payload from the loaded config (status=stopped)."""
    channels      = (_config or {}).get('channels', [])
    trunk_chans   = (_config or {}).get('trunking', {}).get('chans', [])
    site_name     = channels[0].get('name', '')    if channels    else ''
    trunk_id      = trunk_chans[0].get('sysname', '') if trunk_chans else ''
    return {
        'status':       'stopped',
        'uptime':       0,
        'site_name':    site_name,
        'trunk_id':     trunk_id,
        'error_detail': '',
    }

# ---------------------------------------------------------------------------
# Audio streaming
# ---------------------------------------------------------------------------

# These settings match P25 decoder output — 8 kHz / 16-bit signed PCM / mono.
# Keeping bit-rate low (128 kbps) is intentional for Raspberry Pi 5 headroom.
_SAMPLE_RATE   = 8_000   # Hz
_SAMPLE_WIDTH  = 2       # bytes  (16-bit signed PCM)
_CHANNELS      = 1       # mono
_CHUNK_MS      = 100     # chunk duration — 100 ms balances latency vs. overhead
_CHUNK_SAMPLES = _SAMPLE_RATE * _CHUNK_MS // 1_000   # 800 samples
_CHUNK_BYTES   = _CHUNK_SAMPLES * _SAMPLE_WIDTH       # 1 600 bytes


def _wav_stream_header() -> bytes:
    """WAV header for an infinite/unknown-length stream.

    Using 0xFFFFFFFF for both RIFF and data chunk sizes signals an unbounded
    stream — Chrome, Firefox, and Chromium on Pi handle this correctly.
    """
    byte_rate   = _SAMPLE_RATE * _CHANNELS * _SAMPLE_WIDTH
    block_align = _CHANNELS * _SAMPLE_WIDTH
    _UNKNOWN    = 0xFFFF_FFFF
    hdr  = struct.pack('<4sI4s',    b'RIFF', _UNKNOWN, b'WAVE')
    hdr += struct.pack('<4sIHHIIHH', b'fmt ', 16, 1, _CHANNELS,
                       _SAMPLE_RATE, byte_rate, block_align, _SAMPLE_WIDTH * 8)
    hdr += struct.pack('<4sI',      b'data', _UNKNOWN)
    return hdr


def _silence_chunk() -> bytes:
    """One chunk of digital silence (zero-valued PCM)."""
    return b'\x00' * _CHUNK_BYTES


def _sine_chunk(t: float, freq: float = 600.0, amp: float = 0.25) -> bytes:
    """One chunk of a sine wave starting at time *t* (seconds).

    600 Hz at 25 % amplitude is clearly audible without being harsh —
    useful for confirming the stream is live before the decoder connects.
    """
    scale   = amp * 32_767
    samples = [
        max(-32_768, min(32_767, int(scale * math.sin(2 * math.pi * freq * (t + i / _SAMPLE_RATE)))))
        for i in range(_CHUNK_SAMPLES)
    ]
    return struct.pack(f'<{_CHUNK_SAMPLES}h', *samples)


class AudioStreamManager:
    """Queue-backed audio stream.

    Real PCM chunks are pushed via :meth:`push_audio`; when the queue is
    empty the generator emits the mock sine wave (while ``mock`` is ``True``)
    or silence, maintaining a steady byte-rate so browser buffers stay happy
    and no syllables are clipped when real audio resumes.

    Swap ``mock = False`` and call :meth:`push_audio` from the OP25 decoder
    thread to switch from the test tone to live radio audio.
    """

    def __init__(self) -> None:
        # maxsize = 50 chunks × 100 ms = 5 s of buffering before we drop
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=50)
        self.mock: bool = True   # set False once the real decoder feeds audio

    def push_audio(self, pcm_chunk: bytes) -> None:
        """Thread-safe: push a raw PCM chunk.  Drops the oldest on overflow."""
        try:
            self._queue.put_nowait(pcm_chunk)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()          # discard oldest
                self._queue.put_nowait(pcm_chunk) # enqueue new
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    async def generate(self) -> AsyncGenerator[bytes, None]:
        """Async generator: WAV header then a steady stream of PCM chunks."""
        yield _wav_stream_header()

        interval = _CHUNK_MS / 1_000.0
        t        = 0.0
        loop     = asyncio.get_event_loop()

        while True:
            t0 = loop.time()

            try:
                chunk = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                chunk = _sine_chunk(t) if self.mock else _silence_chunk()
                t += interval

            yield chunk
            await asyncio.sleep(max(0.0, interval - (loop.time() - t0)))


audio_manager = AudioStreamManager()

# ---------------------------------------------------------------------------
# Message-type constants (mirrors the TypeScript definitions)
# ---------------------------------------------------------------------------

# Downstream
MSG_SYSTEM_STATE  = "SYSTEM_STATE"
MSG_SDR_STATUS    = "SDR_STATUS"
MSG_CALL_ACTIVITY = "CALL_ACTIVITY"

# Upstream
MSG_CALL_CONTROL   = "CALL_CONTROL"
MSG_SYSTEM_CONTROL = "SYSTEM_CONTROL"

DOWNSTREAM_TYPES = {MSG_SYSTEM_STATE, MSG_SDR_STATUS, MSG_CALL_ACTIVITY}
UPSTREAM_TYPES   = {MSG_CALL_CONTROL, MSG_SYSTEM_CONTROL}

# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Thread-safe registry of active WebSocket connections."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        try:
            self._connections.remove(websocket)
        except ValueError:
            pass

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send *message* to every connected client, dropping stale connections."""
        dead: list[WebSocket] = []
        payload = json.dumps(message)
        for ws in list(self._connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def send(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        """Send *message* to a single connection."""
        await websocket.send_text(json.dumps(message))


manager = ConnectionManager()

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(title="OP25 WebSocket Server", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


# ------------------------------------------------------------------
# WebSocket endpoint
# ------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    # Send an initial system state derived from the loaded config so the
    # frontend can show system identity even before the decoder starts.
    await manager.send(websocket, {
        "type": MSG_SYSTEM_STATE,
        "payload": _initial_system_state(),
    })
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send(websocket, {"type": "ERROR", "payload": {"detail": "invalid JSON"}})
                continue

            msg_type = msg.get("type", "")
            if msg_type not in UPSTREAM_TYPES:
                await manager.send(websocket, {"type": "ERROR", "payload": {"detail": f"unknown type: {msg_type}"}})
                continue

            # Hand off to the appropriate handler
            await _handle_upstream(websocket, msg_type, msg.get("payload", {}))

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        sys.stderr.write("websocket_endpoint error:\n%s\n" % traceback.format_exc())
        manager.disconnect(websocket)


async def _handle_upstream(
    websocket: WebSocket,
    msg_type: str,
    payload: dict[str, Any],
) -> None:
    """Dispatch an upstream message to the registered handler, if any."""
    handler = _upstream_handlers.get(msg_type)
    if handler is not None:
        await handler(websocket, payload)


# Registry for external code to hook into upstream messages.
# Key: message type string, Value: async callable(websocket, payload) -> None
_upstream_handlers: dict[str, Any] = {}


def register_upstream_handler(msg_type: str, handler: Any) -> None:
    """Register *handler* to be called when an upstream *msg_type* arrives.

    The handler signature must be:  async def handler(websocket, payload) -> None
    """
    if msg_type not in UPSTREAM_TYPES:
        raise ValueError(f"'{msg_type}' is not a valid upstream message type")
    _upstream_handlers[msg_type] = handler


# ---------------------------------------------------------------------------
# Config endpoint
# ---------------------------------------------------------------------------

@app.get("/api/config")
async def get_config() -> Response:
    """Return the loaded config JSON, or 404 when no config file was supplied."""
    if _config is None:
        return Response(
            content='{"error": "No config loaded. Start the server with --config-file."}',
            status_code=404,
            media_type="application/json",
        )
    return Response(content=json.dumps(_config), media_type="application/json")


# ---------------------------------------------------------------------------
# Audio stream endpoint
# ---------------------------------------------------------------------------

@app.get("/api/stream")
async def audio_stream() -> StreamingResponse:
    """Continuous WAV audio stream for the browser <audio> element.

    Streams 8 kHz / 16-bit / mono PCM wrapped in a WAV header with an
    unknown-length marker.  When the OP25 decoder is not yet connected the
    generator emits a 600 Hz sine-wave test tone so the browser keeps the
    HTTP connection alive and does not drop buffered audio on reconnect.
    """
    return StreamingResponse(
        audio_manager.generate(),
        media_type="audio/wav",
        headers={
            "Cache-Control":          "no-store",
            "Accept-Ranges":          "none",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ------------------------------------------------------------------
# Static file serving (SPA with client-side routing fallback)
# ------------------------------------------------------------------

def _resolve_dist_path(url_path: str) -> str | None:
    rel = url_path.lstrip('/')
    candidate = os.path.realpath(os.path.join(_DIST_DIR, rel))
    if not candidate.startswith(_DIST_DIR + os.sep) and candidate != _DIST_DIR:
        return None
    return candidate


@app.get("/{full_path:path}")
async def serve_spa(full_path: str) -> Response:
    if full_path and full_path != "/":
        resolved = _resolve_dist_path(full_path)
        if resolved and os.path.isfile(resolved):
            return FileResponse(resolved)

    index_path = os.path.join(_DIST_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path, media_type="text/html")

    return Response(
        content="Frontend not built. Run 'yarn build' inside www/app.",
        status_code=503,
        media_type="text/plain",
    )


# ---------------------------------------------------------------------------
# Public broadcast helpers (for use by OP25 decoder threads)
# ---------------------------------------------------------------------------

async def broadcast_system_state(payload: dict[str, Any]) -> None:
    """Broadcast a SYSTEM_STATE message to all connected clients."""
    await manager.broadcast({"type": MSG_SYSTEM_STATE, "payload": payload})


async def broadcast_sdr_status(payload: dict[str, Any]) -> None:
    """Broadcast an SDR_STATUS message to all connected clients."""
    await manager.broadcast({"type": MSG_SDR_STATUS, "payload": payload})


async def broadcast_call_activity(payload: dict[str, Any]) -> None:
    """Broadcast a CALL_ACTIVITY message to all connected clients."""
    await manager.broadcast({"type": MSG_CALL_ACTIVITY, "payload": payload})


# ---------------------------------------------------------------------------
# Server wrapper (mirrors http_server interface for easy integration)
# ---------------------------------------------------------------------------

class websocket_server:
    """Thin wrapper around uvicorn that mirrors the http_server start-up API."""

    def __init__(self, endpoint: str, config_file: str | None = None, **kwds: Any) -> None:
        global _config
        host, port_str = endpoint.split(':')
        self._host = host
        self._port = int(port_str)
        if config_file is not None:
            _config = load_config(config_file)
            sys.stderr.write('Loaded config from %s\n' % config_file)

    def run(self) -> None:
        uvicorn.run(app, host=self._host, port=self._port, log_level="warning")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='OP25 FastAPI WebSocket server')
    parser.add_argument('--endpoint', default='127.0.0.1:8080',
                        help='host:port to listen on (default: 127.0.0.1:8080)')
    parser.add_argument('--config-file', '-c', default=None,
                        help='path to JSON config file (e.g. richland.json)')
    args = parser.parse_args()

    sys.stderr.write('Serving %s on http://%s\n' % (_DIST_DIR, args.endpoint))
    websocket_server(args.endpoint, config_file=args.config_file).run()
