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
import select
import socket
import struct
import sys
import threading
import time
import traceback
from collections.abc import AsyncGenerator
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
import uvicorn

try:
    from gnuradio import gr as _gr
except ImportError:
    _gr = None  # type: ignore[assignment]

MOCK = False  # when True, audio stream emits a test tone until real audio arrives

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
_CHUNK_MS      = 20      # chunk duration — 20 ms matches one P25 voice frame (160 samples)
_CHUNK_SAMPLES = _SAMPLE_RATE * _CHUNK_MS // 1_000   # 160 samples
_CHUNK_BYTES   = _CHUNK_SAMPLES * _SAMPLE_WIDTH       # 320 bytes


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
    """Byte-buffered audio stream.

    Real PCM bytes are pushed via :meth:`push_audio` from any thread.  The
    async :meth:`generate` consumer yields fixed-size PCM chunks paced at
    the wall-clock byte-rate so the browser playback stays in sync.  When
    the buffer underruns, silence (or the mock sine) is emitted instead,
    keeping the HTTP stream and the browser's scheduler alive.

    A small set of counters is maintained so the server can log how much
    audio is flowing end-to-end — useful when "no sound" issues need to be
    distinguished from "decoder produced no audio" issues.
    """

    # Hard cap on the buffer — about 4 s at 16 kB/s.  Larger than this and
    # we are unrecoverably behind; drop the oldest to bound latency.
    _MAX_BUFFERED_BYTES = _SAMPLE_RATE * _SAMPLE_WIDTH * 4

    def __init__(self) -> None:
        self._buffer: bytearray = bytearray()
        self._lock: threading.Lock = threading.Lock()
        self.mock: bool = MOCK   # set False once the real decoder feeds audio

        # Diagnostics
        self.bytes_pushed: int = 0
        self.bytes_yielded: int = 0
        self.bytes_dropped: int = 0
        self.underruns: int = 0          # chunks padded with silence
        self.real_chunks: int = 0        # chunks fully sourced from real PCM
        self.last_push_ts: float = 0.0

    # ------------------------------------------------------------------
    # Producer side (called from UDP receiver thread)
    # ------------------------------------------------------------------

    def push_audio(self, pcm_chunk: bytes) -> None:
        """Thread-safe: append raw 8 kHz / 16-bit LE mono PCM bytes."""
        if not pcm_chunk:
            return
        with self._lock:
            self._buffer.extend(pcm_chunk)
            self.bytes_pushed += len(pcm_chunk)
            self.last_push_ts = time.time()
            overflow = len(self._buffer) - self._MAX_BUFFERED_BYTES
            if overflow > 0:
                del self._buffer[:overflow]
                self.bytes_dropped += overflow

    # ------------------------------------------------------------------
    # Consumer side (called from the asyncio event loop)
    # ------------------------------------------------------------------

    def _take_chunk(self) -> tuple[bytes, int]:
        """Pop up to one full chunk from the buffer.

        Returns ``(pcm_bytes, real_byte_count)`` where ``real_byte_count``
        is the number of bytes that came from real pushed audio (the rest
        of the chunk is silence padding when the buffer underran).
        """
        with self._lock:
            if not self._buffer:
                return b'', 0
            take = min(len(self._buffer), _CHUNK_BYTES)
            chunk = bytes(self._buffer[:take])
            del self._buffer[:take]
            return chunk, take

    def buffered_bytes(self) -> int:
        with self._lock:
            return len(self._buffer)

    async def generate(self) -> AsyncGenerator[bytes, None]:
        """Async generator: WAV header then a steady stream of PCM chunks."""
        yield _wav_stream_header()

        interval = _CHUNK_MS / 1_000.0
        t        = 0.0
        loop     = asyncio.get_event_loop()

        while True:
            t0 = loop.time()

            real_bytes, real_len = self._take_chunk()
            if real_len == _CHUNK_BYTES:
                chunk = real_bytes
                self.real_chunks += 1
            elif real_len > 0:
                # Partial buffer — pad the tail with silence so the chunk
                # stays exactly _CHUNK_BYTES.  This is normal at the start
                # and end of a transmission.
                chunk = real_bytes + b'\x00' * (_CHUNK_BYTES - real_len)
                self.underruns += 1
            else:
                chunk = _sine_chunk(t) if self.mock else _silence_chunk()
                self.underruns += 1
                t += interval

            self.bytes_yielded += len(chunk)
            yield chunk
            await asyncio.sleep(max(0.0, interval - (loop.time() - t0)))


audio_manager = AudioStreamManager()


# ---------------------------------------------------------------------------
# UDP audio receiver
# ---------------------------------------------------------------------------
#
# The OP25 C++ frame_assembler block decodes IMBE → 8 kHz / 16-bit / mono PCM
# and emits it on a UDP socket whose host/port come from the channel's
# ``destination`` field (e.g. ``udp://127.0.0.1:23456``).  This receiver
# listens on every such port discovered in the loaded config and feeds the
# decoded PCM into :data:`audio_manager` so the browser ``/api/stream`` and
# any other consumer can play it.
#
# Two packet shapes arrive on the wire:
#   * 320 bytes — one P25 voice frame (160 16-bit LE samples = 20 ms of audio)
#   * 2 bytes   — a flag word (drain/drop signal, used by sockaudio.py for
#                 ALSA buffer management).  We ignore these for browser audio.
#
# The companion "+1" port (e.g. 23457) carries the second TDMA slot when
# the decoder is in phase-2 mode; we bind it too so both slots are heard.

_DEFAULT_AUDIO_PORT = 23456
_AUDIO_FRAME_BYTES  = 320
_AUDIO_FLAG_BYTES   = 2


def _discover_audio_ports(config: dict[str, Any] | None) -> list[tuple[str, int]]:
    """Return the list of ``(host, port)`` pairs the decoder will UDP to.

    Each channel with ``destination`` of the form ``udp://host:port``
    contributes two ports — ``port`` (slot A) and ``port + 1`` (slot B,
    used for TDMA phase-2).  If no UDP destinations are configured we
    fall back to the OP25 default of ``127.0.0.1:23456``/``23457`` so the
    browser stream still has a chance of receiving audio when the user
    later adds a destination matching the default.
    """
    ports: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()

    for ch in (config or {}).get('channels', []) or []:
        dest = str(ch.get('destination', '') or '').strip()
        if not dest.startswith('udp://'):
            continue
        try:
            parsed = urlparse(dest)
            host   = parsed.hostname or '127.0.0.1'
            port   = int(parsed.port or 0)
        except (TypeError, ValueError):
            continue
        if port <= 0:
            continue
        for p in (port, port + 1):
            key = (host, p)
            if key not in seen:
                seen.add(key)
                ports.append(key)

    if not ports:
        ports = [('127.0.0.1', _DEFAULT_AUDIO_PORT),
                 ('127.0.0.1', _DEFAULT_AUDIO_PORT + 1)]

    return ports


class UdpAudioReceiver(threading.Thread):
    """Background thread: UDP → :data:`audio_manager`.

    Binds one socket per ``(host, port)`` pair and ``select()``s across
    them in a single thread.  PCM bytes go to ``audio_manager.push_audio``;
    flag packets are counted but discarded.  Periodically logs throughput
    so a user staring at "no audio in browser" can see whether bytes are
    arriving from the decoder at all.
    """

    LOG_INTERVAL = 5.0   # seconds between throughput log lines

    def __init__(self, endpoints: list[tuple[str, int]]) -> None:
        super().__init__(name='ws-audio-udp', daemon=True)
        self._endpoints     = endpoints
        self._socks: list[socket.socket] = []
        self.keep_running   = True

        # Diagnostics
        self.packets_pcm    = 0
        self.packets_flag   = 0
        self.packets_other  = 0
        self.bytes_in       = 0
        self._last_log      = 0.0
        self._last_logged_bytes = 0

    def _open_sockets(self) -> None:
        for host, port in self._endpoints:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
                s.setblocking(False)
                self._socks.append(s)
                sys.stderr.write('ws audio: listening on udp %s:%d\n' % (host, port))
            except OSError as exc:
                sys.stderr.write(
                    'ws audio: failed to bind udp %s:%d (%s) — '
                    'is sockaudio.py or another OP25 audio consumer already '
                    'using this port?\n' % (host, port, exc)
                )

    def _close_sockets(self) -> None:
        for s in self._socks:
            try:
                s.close()
            except OSError:
                pass
        self._socks.clear()

    def stop(self) -> None:
        self.keep_running = False

    def run(self) -> None:
        self._open_sockets()
        if not self._socks:
            sys.stderr.write('ws audio: no UDP sockets bound — browser audio will be silent\n')
            return

        while self.keep_running:
            try:
                readable, _, _ = select.select(self._socks, [], [], 1.0)
            except (OSError, ValueError):
                break

            for s in readable:
                try:
                    data, _addr = s.recvfrom(4096)
                except BlockingIOError:
                    continue
                except OSError:
                    continue

                self.bytes_in += len(data)
                if len(data) == _AUDIO_FLAG_BYTES:
                    self.packets_flag += 1
                elif len(data) >= _AUDIO_FRAME_BYTES and (len(data) % 2 == 0):
                    self.packets_pcm += 1
                    audio_manager.push_audio(data)
                else:
                    # Unknown packet shape — log once-ish via the throttle.
                    self.packets_other += 1

            self._maybe_log()

        self._close_sockets()

    def _maybe_log(self) -> None:
        now = time.time()
        if self._last_log == 0.0:
            self._last_log = now
            return
        if now - self._last_log < self.LOG_INTERVAL:
            return

        delta_bytes = self.bytes_in - self._last_logged_bytes
        rate_kbps   = (delta_bytes * 8) / (now - self._last_log) / 1000.0
        buffered    = audio_manager.buffered_bytes()

        sys.stderr.write(
            'ws audio: rx pcm=%d flag=%d other=%d  in=%d B (+%d, %.1f kbps)  '
            'buf=%d B  pushed=%d  yielded=%d  underruns=%d  dropped=%d\n' % (
                self.packets_pcm, self.packets_flag, self.packets_other,
                self.bytes_in, delta_bytes, rate_kbps,
                buffered,
                audio_manager.bytes_pushed,
                audio_manager.bytes_yielded,
                audio_manager.underruns,
                audio_manager.bytes_dropped,
            )
        )
        self._last_log = now
        self._last_logged_bytes = self.bytes_in


_audio_receiver: UdpAudioReceiver | None = None


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

# Captured on startup so non-async decoder threads can schedule broadcasts.
_server_loop: asyncio.AbstractEventLoop | None = None


@app.on_event("startup")
async def _on_startup() -> None:
    global _server_loop
    _server_loop = asyncio.get_event_loop()


def _broadcast_from_thread(msg_type: str, payload: dict[str, Any]) -> None:
    """Schedule a broadcast from any thread into the uvicorn event loop."""
    if _server_loop is None or _server_loop.is_closed():
        return
    asyncio.run_coroutine_threadsafe(
        manager.broadcast({"type": msg_type, "payload": payload}),
        _server_loop,
    )


# Maps the decoder's json_type field to the appropriate downstream WS message.
_JSON_TYPE_TO_MSG: dict[str, str] = {
    "chan_status":         MSG_SDR_STATUS,
    "call_log":           MSG_CALL_ACTIVITY,
    "trunked_site_status": MSG_CALL_ACTIVITY,
    "sys_info":           MSG_CALL_ACTIVITY,
    "terminal_config":    MSG_SYSTEM_STATE,
    "full_config":        MSG_SYSTEM_STATE,
    "ws_instances":       MSG_SYSTEM_STATE,
}


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
# OP25 terminal adapter  (multi_rx.py integration)
# ---------------------------------------------------------------------------

class ws_terminal(threading.Thread):
    """Bridge the multi_rx.py UI queues to the FastAPI WebSocket server.

    multi_rx.py calls ``op25_terminal(input_q, output_q, terminal_type)``
    which returns one of these.  The thread does two things:

    1. Sends a periodic ``update`` heartbeat to *output_q* so the decoder
       pushes fresh channel-status and call-log data into *input_q*.
    2. Drains *input_q*, maps each JSON message to the appropriate
       WebSocket message type, and broadcasts it to all connected clients.

    Upstream WebSocket messages (CALL_CONTROL / SYSTEM_CONTROL) are
    forwarded to *output_q* as GNURadio messages.
    """

    UPDATE_INTERVAL: float = 1.0  # seconds between heartbeat 'update' commands

    def __init__(
        self,
        input_q: Any,
        output_q: Any,
        endpoint: str,
        **kwds: Any,
    ) -> None:
        threading.Thread.__init__(self, **kwds)
        self.daemon = True
        self.input_q  = input_q
        self.output_q = output_q
        self.keep_running = True

        # Parse "host:port" — the "ws:" prefix is stripped by op25_terminal().
        host, port_str = endpoint.split(':', 1)
        self._host = host
        self._port = int(port_str)

        # Start uvicorn in its own daemon thread so multi_rx's main thread
        # is free to run the GNURadio flowgraph.
        server_t = threading.Thread(
            target=lambda: uvicorn.run(app, host=self._host, port=self._port, log_level="warning"),
            name='ws-server',
            daemon=True,
        )
        server_t.start()
        sys.stderr.write('WebSocket terminal server starting on %s:%d\n' % (self._host, self._port))

        # Start the UDP audio receiver that feeds /api/stream.  Ports are
        # discovered from the channels' "destination" fields so the user
        # doesn't have to configure audio separately for the browser.
        global _audio_receiver
        if _audio_receiver is None:
            _audio_receiver = UdpAudioReceiver(_discover_audio_ports(_config))
            _audio_receiver.start()

        # Register upstream WebSocket handlers that forward client commands
        # to the decoder via output_q.
        self._register_upstream_handlers()

        self.start()  # start the queue-watcher / heartbeat thread

    # ------------------------------------------------------------------
    # Terminal interface expected by multi_rx.py
    # ------------------------------------------------------------------

    def get_terminal_type(self) -> str:
        return "ws"

    def end_terminal(self) -> None:
        self.keep_running = False
        global _audio_receiver
        if _audio_receiver is not None:
            _audio_receiver.stop()
            _audio_receiver = None

    # ------------------------------------------------------------------
    # Thread body
    # ------------------------------------------------------------------

    def run(self) -> None:
        last_update = 0.0
        while self.keep_running:
            now = time.time()
            if now - last_update >= self.UPDATE_INTERVAL:
                self._send_cmd('update')
                last_update = now
            if not self.input_q.empty_p():
                msg = self.input_q.delete_head_nowait()
                if msg is not None:
                    self._dispatch(msg)
            else:
                time.sleep(0.01)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _send_cmd(self, cmd: str, arg1: float = 0.0, arg2: float = 0.0) -> None:
        """Put a command message onto the decoder's output queue."""
        if _gr is None:
            return
        msg = _gr.message().make_from_string(cmd, -2, arg1, arg2)
        if not self.output_q.full_p():
            self.output_q.insert_tail(msg)

    def _dispatch(self, msg: Any) -> None:
        """Broadcast a decoder message to all WebSocket clients."""
        if msg.type() != -4:
            return
        try:
            data: dict[str, Any] = json.loads(msg.to_string())
        except Exception:
            return
        data.pop('uuid', None)  # internal request-correlation tag; not part of the client protocol
        json_type = data.get('json_type', '')
        ws_type = _JSON_TYPE_TO_MSG.get(json_type, MSG_SYSTEM_STATE)
        _broadcast_from_thread(ws_type, data)

    def _register_upstream_handlers(self) -> None:
        """Wire upstream WebSocket messages to decoder commands."""
        output_q = self.output_q  # capture for closures

        async def handle_call_control(websocket: WebSocket, payload: dict[str, Any]) -> None:
            try:
                if _gr is None:
                    return
                command = str(payload.get('command', ''))
                arg1    = float(payload.get('arg1', 0.0))
                arg2    = float(payload.get('arg2', 0.0))
                if command:
                    m = _gr.message().make_from_string(command, -2, arg1, arg2)
                    if not output_q.full_p():
                        output_q.insert_tail(m)
            except Exception:
                sys.stderr.write('ws_terminal: handle_call_control error:\n%s\n' % traceback.format_exc())

        async def handle_system_control(websocket: WebSocket, payload: dict[str, Any]) -> None:
            try:
                if _gr is None:
                    return
                action = str(payload.get('action', ''))
                if action == 'quit':
                    m = _gr.message().make_from_string('quit', -2, 0.0, 0.0)
                    if not output_q.full_p():
                        output_q.insert_tail(m)
            except Exception:
                sys.stderr.write('ws_terminal: handle_system_control error:\n%s\n' % traceback.format_exc())

        register_upstream_handler(MSG_CALL_CONTROL, handle_call_control)
        register_upstream_handler(MSG_SYSTEM_CONTROL, handle_system_control)


def op25_terminal(input_q: Any, output_q: Any, terminal_type: str) -> ws_terminal:
    """Factory matching the terminal.py ``op25_terminal`` interface.

    ``terminal_type`` should be ``"ws:<host>:<port>"``, e.g.
    ``"ws:0.0.0.0:8080"``.  The ``"ws:"`` prefix is stripped before the
    endpoint is passed to :class:`ws_terminal`.
    """
    if terminal_type.startswith('ws:'):
        endpoint = terminal_type[3:]
    else:
        endpoint = terminal_type
    return ws_terminal(input_q, output_q, endpoint)


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
