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
    SYSTEM_STATE   – Health snapshot (status/uptime), plus every decoder
                     json_type without a more specific home: trunk_update,
                     channel_update, plot, terminal_config, full_config
    CALL_ACTIVITY  – call_log entries (a draining delta feed; the server keeps
                     a ring of recent ones so late joiners are not left blank)
    CALL_AUDIO     – A captured call clip, and later its transcript

Upstream (client → server)
    CALL_CONTROL   – Any decoder UI command: hold, skip, lockout, whitelist,
                     reload, adj_tune, set_debug, capture, dump_tgids,
                     dump_buffer, toggle_plot, close_plots, get_full_config, …
                     Normally sent as the bare command name with its argument in
                     arg1; a payload carrying anything beyond command/arg1/arg2
                     goes as JSON instead, which is how the batch scan-list
                     commands (set_whitelist / set_blacklist) pass a list that
                     would not fit in a gr.message's two floats.
    SYSTEM_CONTROL – quit.  Muting is a browser-side concern (the page simply
                     stops pulling /api/stream), so there is no mute command.
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
from collections import deque
from collections.abc import AsyncGenerator
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
import uvicorn

import config_schema
import config_store
from ha_bridge import (
    CallClip,
    CallRecorder,
    ClipStore,
    HomeAssistantBridge,
    HomeAssistantConfig,
    mix_pcm16,
    redact_config,
    resample_pcm16,
    wav_bytes,
)
from tg_metadata import TalkgroupStore, db_path as _metadata_db_path

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

# The editable-config layer. None until a config is installed; None also means
# "editing unavailable", which is what a standalone run with no overlay path or a
# deliberately read-only deployment looks like.
_config_store: config_store.ConfigStore | None = None

# The decoder's command queue, published here so the REST handlers can send it a
# command. ws_terminal owns it; the WebSocket path reaches it through a closure,
# but a REST handler is a module-level function with no such context.
_output_q: Any = None


def _send_upstream(payload: dict[str, Any]) -> bool:
    """Send a decoder UI command. Returns False if there is nothing to send to.

    Uses the JSON form unconditionally: every caller here has an argument that
    does not fit a gr.message's two floats (a gain string, a device name), and
    multi_rx.process_qmsg has always tried json.loads() before the bare-string
    form.
    """
    if _gr is None or _output_q is None:
        return False
    try:
        arg1 = float(payload.get('arg1', 0.0))
        arg2 = float(payload.get('arg2', 0.0))
        msg = _gr.message().make_from_string(json.dumps(payload), -2, arg1, arg2)
        if _output_q.full_p():
            return False
        _output_q.insert_tail(msg)
        return True
    except Exception:
        sys.stderr.write('_send_upstream failed:\n%s\n' % traceback.format_exc())
        return False


def load_config(path: str) -> dict[str, Any]:
    """Load a JSON config file, mirroring multi_rx.py's utf-8-sig fallback."""
    try:
        with open(path, encoding='utf-8-sig') as f:
            return json.loads(f.read())
    except UnicodeDecodeError:
        with open(path) as f:
            return json.loads(f.read())


# Server start, and the last time the decoder sent us anything.  Together these
# are what makes SYSTEM_STATE a live health signal rather than the frozen
# 'stopped' / uptime 0 placeholder it used to be.
_server_started_at: float = time.time()
_last_decoder_msg_at: float = 0.0

# How long without decoder traffic before we call the decoder stopped.  The
# ws_terminal heartbeat asks for an update every second, so a few missed
# replies is a real stall, not jitter.
_DECODER_STALE_SECS = 5.0


def _system_state_payload() -> dict[str, Any]:
    """Build the SYSTEM_STATE health payload.

    ``status`` reflects whether the decoder is actually feeding us: 'running'
    once messages are arriving, 'stopped' before the first one or after
    _DECODER_STALE_SECS of silence.  ``uptime`` is this server's, in seconds.
    """
    channels      = (_config or {}).get('channels', [])
    trunk_chans   = (_config or {}).get('trunking', {}).get('chans', [])
    site_name     = channels[0].get('name', '')    if channels    else ''
    trunk_id      = trunk_chans[0].get('sysname', '') if trunk_chans else ''

    now = time.time()
    if _last_decoder_msg_at and (now - _last_decoder_msg_at) < _DECODER_STALE_SECS:
        status, detail = 'running', ''
    elif _last_decoder_msg_at:
        status = 'error'
        detail = 'no decoder update for %.0fs' % (now - _last_decoder_msg_at)
    else:
        status, detail = 'stopped', 'waiting for the decoder'

    return {
        'status':       status,
        'uptime':       int(now - _server_started_at),
        'site_name':    site_name,
        'trunk_id':     trunk_id,
        'error_detail': detail,
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

# Jitter buffer depth, in ms of audio, held back before playback starts.
#
# The decoder produces exactly one 20 ms frame every 20 ms and we consume one
# every 20 ms, so the steady-state cushion is zero: any packet that arrives even
# slightly late finds the buffer empty, and without a cushion the only thing to
# emit is silence.  That splices a 20 ms hole into the middle of a word and the
# buffer never gets a chance to build up, so at 50 packets/s a few percent of
# scheduling jitter is heard as continuous chopping — which is indistinguishable
# by ear from a bad RF decode.  Holding a short prime absorbs the jitter instead.
#
# This is the same reasoning (and the same default) as sockaudio.py's
# PORTAUDIO_PRIME_MS, for the same reason.  Do not "simplify" it away: 120 ms of
# added latency is imperceptible on scanner audio, the chopping is not.
_STREAM_PRIME_MS = int(os.environ.get('OP25_STREAM_PRIME_MS', '120'))

# Audio buffered while nobody is listening is not buffered audio, it is history.
#
# The UDP thread pushes whether or not a client is attached, so an idle server
# used to fill to _MAX_BUFFERED_BYTES (4 s) and then shed the oldest bytes to
# stay there -- observed live as `buf=64000 pushed=181440 yielded=0
# dropped=117440`. A listener attaching then inherited that 4 s backlog and,
# being drained at real time and refilled at real time, stayed 4 s behind for as
# long as it listened. Live scanner audio 4 s late is worse than useless: you
# hear the reply before the call.
#
# So with no consumer the buffer keeps only a rolling prime's worth, and a
# listener starts live. Note this is decided by *who is attached*, not by how
# deep the buffer is: a producer that bursts ahead of real time is normal (UDP
# coalescing does it, and so does a non-real-time source), and its audio is the
# start of a transmission, not staleness. Discarding it clips the first word.
_IDLE_KEEP_MS = int(os.environ.get('OP25_STREAM_IDLE_KEEP_MS', '120'))


def _wav_stream_header(sample_rate: int = _SAMPLE_RATE) -> bytes:
    """WAV header for an infinite/unknown-length stream.

    Using 0xFFFFFFFF for both RIFF and data chunk sizes signals an unbounded
    stream — Chrome, Firefox, and Chromium on Pi handle this correctly, as
    does ffmpeg (which is what Home Assistant's stream integrations use).
    """
    byte_rate   = sample_rate * _CHANNELS * _SAMPLE_WIDTH
    block_align = _CHANNELS * _SAMPLE_WIDTH
    _UNKNOWN    = 0xFFFF_FFFF
    hdr  = struct.pack('<4sI4s',    b'RIFF', _UNKNOWN, b'WAVE')
    hdr += struct.pack('<4sIHHIIHH', b'fmt ', 16, 1, _CHANNELS,
                       sample_rate, byte_rate, block_align, _SAMPLE_WIDTH * 8)
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

    def __init__(self, mix: bool = False) -> None:
        self._buffer: bytearray = bytearray()
        self._lock: threading.Lock = threading.Lock()
        self.mock: bool = MOCK   # set False once the real decoder feeds audio

        # Mixing mode, used only by the aggregate stream.  Each source port
        # gets its own queue and :meth:`_take_chunk` sums one chunk across all
        # of them.  A single shared buffer cannot work here: appending would
        # interleave fragments of separate conversations and would also accept
        # audio N times faster than the consumer drains it.
        self._mix: bool = mix
        self._mix_buffers: dict[int, bytearray] = {}

        # How much audio to accumulate before playback starts, and again after
        # the buffer runs dry.  Per-instance so a test can set it to 0 and get
        # the old push-one-chunk/take-one-chunk behaviour.
        self.prime_bytes: int = (
            int(_SAMPLE_RATE * _STREAM_PRIME_MS / 1_000.0) * _SAMPLE_WIDTH
        )
        # What to retain while no consumer is attached -- see _IDLE_KEEP_MS.
        self.idle_keep_bytes: int = (
            int(_SAMPLE_RATE * _IDLE_KEEP_MS / 1_000.0) * _SAMPLE_WIDTH
        )
        # Number of live generate() consumers. Guarded by _lock.
        self._consumers: int = 0

        # Diagnostics
        self.bytes_pushed: int = 0
        self.bytes_yielded: int = 0
        self.bytes_dropped: int = 0
        self.underruns: int = 0          # dropouts: ran dry with a call in progress
        self.silent_chunks: int = 0      # idle silence, incl. waiting on the prime
        self.real_chunks: int = 0        # chunks fully sourced from real PCM
        self.last_push_ts: float = 0.0

    # ------------------------------------------------------------------
    # Producer side (called from UDP receiver thread)
    # ------------------------------------------------------------------

    def push_audio(self, pcm_chunk: bytes, port: int = 0) -> None:
        """Thread-safe: append raw 8 kHz / 16-bit LE mono PCM bytes.

        *port* is only consulted in mixing mode, where it selects which source
        queue the bytes join.
        """
        if not pcm_chunk:
            return
        with self._lock:
            buf = self._mix_buffers.setdefault(port, bytearray()) if self._mix \
                else self._buffer
            buf.extend(pcm_chunk)
            self.bytes_pushed += len(pcm_chunk)
            self.last_push_ts = time.time()
            # Bound each source independently, so one channel falling behind
            # cannot evict another channel's audio.  With nobody listening the
            # bound is a rolling live window instead of the full 4 s, so a client
            # that attaches starts live rather than inheriting history --
            # see _IDLE_KEEP_MS.
            cap = self._MAX_BUFFERED_BYTES if self._consumers \
                else max(self.idle_keep_bytes, _CHUNK_BYTES)
            overflow = len(buf) - cap
            if overflow > 0:
                del buf[:overflow]
                self.bytes_dropped += overflow

    # ------------------------------------------------------------------
    # Consumer side (called from the asyncio event loop)
    # ------------------------------------------------------------------

    def drop_stale(self, keep_bytes: int) -> int:
        """Discard all but the newest *keep_bytes* from each source. Returns bytes dropped.

        The UDP thread pushes whether or not anyone is listening, so with no
        client attached the buffer sits at ``_MAX_BUFFERED_BYTES`` (4 s) and
        sheds the oldest audio to stay there.  A listener attaching then finds a
        full backlog, primes off it instantly, and -- because it is drained at
        real time and refilled at real time -- stays 4 s behind for as long as it
        listens.  Live scanner audio 4 s late is worse than useless: you hear the
        reply before the call.

        So priming trims to the cushion it actually wants rather than adopting
        whatever happens to be queued.  Call recording is unaffected: clips come
        from ``CallCapture``, which the UDP thread feeds separately.
        """
        dropped = 0
        with self._lock:
            bufs = list(self._mix_buffers.values()) if self._mix else [self._buffer]
            for buf in bufs:
                excess = len(buf) - keep_bytes
                if excess > 0:
                    del buf[:excess]          # keep the tail: newest audio
                    dropped += excess
            self.bytes_dropped += dropped
        return dropped

    def _take_chunk(self) -> tuple[bytes, int]:
        """Pop up to one full chunk from the buffer.

        Returns ``(pcm_bytes, real_byte_count)`` where ``real_byte_count``
        is the number of bytes that came from real pushed audio (the rest
        of the chunk is silence padding when the buffer underran).
        """
        with self._lock:
            if self._mix:
                parts: list[bytes] = []
                for buf in self._mix_buffers.values():
                    if not buf:
                        continue
                    take = min(len(buf), _CHUNK_BYTES)
                    parts.append(bytes(buf[:take]))
                    del buf[:take]
                if not parts:
                    return b'', 0
                chunk = mix_pcm16(parts)
                return chunk, len(chunk)
            if not self._buffer:
                return b'', 0
            take = min(len(self._buffer), _CHUNK_BYTES)
            chunk = bytes(self._buffer[:take])
            del self._buffer[:take]
            return chunk, take

    def buffered_bytes(self) -> int:
        with self._lock:
            if self._mix:
                # The backlog is however far the *most* backed-up source is,
                # not the sum: the sources are drained in parallel.
                return max((len(b) for b in self._mix_buffers.values()), default=0)
            return len(self._buffer)

    def _attach(self) -> None:
        with self._lock:
            self._consumers += 1

    def _detach(self) -> None:
        with self._lock:
            self._consumers = max(0, self._consumers - 1)

    @property
    def consumers(self) -> int:
        return self._consumers

    async def generate(
        self,
        out_rate: int = _SAMPLE_RATE,
        container: str = 'wav',
    ) -> AsyncGenerator[bytes, None]:
        """Async generator: optional WAV header, then a steady stream of PCM.

        *out_rate* resamples on the way out — Home Assistant's speech
        pipeline and Whisper both want 16 kHz, and doing the conversion
        here saves every consumer from having to.  *container* may be
        ``'wav'`` (default) or ``'raw'`` for headerless PCM.
        """
        # Registering as a consumer switches push_audio from "keep a rolling live
        # window" to "buffer properly", so audio queued before anyone was
        # listening is never inherited as latency. See _IDLE_KEEP_MS.
        self._attach()
        try:
            async for chunk in self._generate(out_rate, container):
                yield chunk
        finally:
            self._detach()

    async def _generate(
        self,
        out_rate: int,
        container: str,
    ) -> AsyncGenerator[bytes, None]:
        if container != 'raw':
            yield _wav_stream_header(out_rate)

        interval = _CHUNK_MS / 1_000.0
        t        = 0.0
        loop     = asyncio.get_event_loop()
        # False until self.prime_bytes of audio has accumulated.  Reset whenever
        # the buffer runs dry, which is both the end of a transmission and the
        # recovery path from a jitter dropout — see _STREAM_PRIME_MS.
        primed   = False
        # Absolute send schedule.  Sleeping for "interval minus work done" looks
        # right but silently runs slow: asyncio.sleep overshoots by a millisecond
        # or two every iteration and that error accumulates, so the stream
        # delivers a few percent less than real time.  The client's buffer then
        # drains until it starves, which sounds like a periodic dropout no
        # matter how much it buffers.  Pacing against an absolute deadline
        # absorbs the overshoot instead of compounding it.
        next_send = loop.time()

        while True:
            # Hold playback until the cushion is there.  Taking a chunk the
            # moment one exists consumes it as fast as it arrives, so the
            # cushion never builds and every late packet is a hole.
            if not primed and self.buffered_bytes() >= max(self.prime_bytes, _CHUNK_BYTES):
                primed = True

            if not primed:
                chunk = _sine_chunk(t) if self.mock else _silence_chunk()
                self.silent_chunks += 1
                t += interval
            else:
                real_bytes, real_len = self._take_chunk()
                if real_len == _CHUNK_BYTES:
                    chunk = real_bytes
                    self.real_chunks += 1
                elif real_len > 0:
                    # Partial buffer — pad the tail with silence so the chunk
                    # stays exactly _CHUNK_BYTES.  Normal at the end of a
                    # transmission, where the last frame does not land on a
                    # chunk boundary.
                    chunk = real_bytes + b'\x00' * (_CHUNK_BYTES - real_len)
                    self.underruns += 1
                    primed = False
                else:
                    chunk = _sine_chunk(t) if self.mock else _silence_chunk()
                    self.underruns += 1
                    t += interval
                    primed = False

            self.bytes_yielded += len(chunk)
            yield resample_pcm16(chunk, _SAMPLE_RATE, out_rate) if out_rate != _SAMPLE_RATE else chunk

            next_send += interval
            delay = next_send - loop.time()
            if delay < -interval:
                # Fell badly behind (scheduler stall).  Resync rather than
                # bursting a backlog of chunks at the client all at once.
                next_send = loop.time()
                delay = 0.0
            await asyncio.sleep(max(0.0, delay))


# The aggregate stream: every UDP port mixed together.  This is what bare
# /api/stream serves, so a single-channel setup — and Home Assistant, and any
# existing consumer — behaves exactly as before.
audio_manager = AudioStreamManager(mix=True)

# One manager per UDP port, so a multi-channel setup can be listened to one
# channel (or one DMR slot) at a time instead of hearing everything at once.
# Created up front from the discovered endpoints; the UDP thread only ever
# looks ports up, so no locking is needed on the hot path.
_port_managers: dict[int, AudioStreamManager] = {}

# Which endpoint each port belongs to, for /api/audio/channels.
_audio_endpoints: list[dict[str, Any]] = []


def _init_port_managers(endpoints: list[dict[str, Any]]) -> None:
    """Give every discovered port its own stream manager."""
    _audio_endpoints.clear()
    _audio_endpoints.extend(endpoints)
    _port_managers.clear()
    for ep in endpoints:
        _port_managers[ep['port']] = AudioStreamManager()


def _manager_for_channel(channel: int) -> AudioStreamManager | None:
    """The stream for a channel's slot-A port, or None if there isn't one."""
    for ep in _audio_endpoints:
        if ep['channel'] == channel and ep['slot'] == 'A':
            return _port_managers.get(ep['port'])
    return None


# ---------------------------------------------------------------------------
# Call capture and Home Assistant bridge
# ---------------------------------------------------------------------------
#
# The same PCM that feeds the browser stream is also sliced into per-call
# clips (see ha_bridge.CallRecorder).  Those clips are what a speech-to-text
# engine actually wants: short, finite, and speech-only.  They back both the
# /api/calls REST endpoints and — when configured — the push of transcripts
# and keyword alerts into Home Assistant.

class CallCapture:
    """One :class:`CallRecorder` per UDP audio port.

    P25 sends a channel's audio to a single port — ``p25_frame_assembler``
    holds one ``p25p2_tdma`` and calls plain ``send_audio()`` — so in the
    common case this is a set of one.  DMR in stereo mode is the exception:
    ``rx_sync::output()`` routes timeslot B to ``port + 1``, and those two
    slots carry *independent conversations*.  Feeding both into a single
    recorder would interleave two people into one clip, so each port gets
    its own segmentation state.
    """

    def __init__(self, factory: Any) -> None:
        self._factory = factory
        self._recorders: dict[int, CallRecorder] = {}
        self._lock = threading.Lock()

    def _recorder(self, port: int) -> CallRecorder:
        with self._lock:
            rec = self._recorders.get(port)
            if rec is None:
                rec = self._factory(port)
                self._recorders[port] = rec
            return rec

    def push(self, port: int, pcm: bytes) -> None:
        self._recorder(port).push(pcm)

    def poll(self) -> None:
        with self._lock:
            recorders = list(self._recorders.values())
        for rec in recorders:
            rec.poll()

    def flush(self) -> None:
        with self._lock:
            recorders = list(self._recorders.values())
        for rec in recorders:
            rec.flush()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            recorders = dict(self._recorders)
        return {
            'ports':          sorted(recorders),
            'calls_captured': sum(r.calls_captured for r in recorders.values()),
            'calls_dropped':  sum(r.calls_dropped for r in recorders.values()),
        }


clip_store: ClipStore = ClipStore()
_call_capture: CallCapture | None = None
_ha_bridge: HomeAssistantBridge | None = None

# Durable talkgroup metadata (last heard, last frequency, lifetime call count).
# Created when the terminal starts, because that is when the config -- and so the
# database path -- is known.  None means nothing has been wired up yet, which is
# the state every test that does not ask for it runs in.
talkgroup_store: TalkgroupStore | None = None

# Latest channel_update snapshot from the decoder, used to tag captured clips
# with talkgroup / source / frequency.  Written by the ws_terminal thread and
# read by the UDP audio thread, hence the lock.
_last_channels: dict[str, Any] = {}
_last_channels_lock = threading.Lock()

# Symbol-capture files the decoder has told us it is writing, newest last.
# Kept even after a capture stops so the finished file stays downloadable.
_capture_files: list[str] = []

# call_log is a *draining* delta feed: tk_p25.get_call_log() clears its buffer
# on every read and ws_terminal polls once a second whether or not a browser is
# attached.  Without this ring a client that connects late permanently misses
# every call that happened before it arrived.
_CALL_LOG_HISTORY = 200
_recent_calls: deque[dict[str, Any]] = deque(maxlen=_CALL_LOG_HISTORY)
_recent_calls_lock = threading.Lock()


def _note_channel_state(entry: dict[str, Any]) -> None:
    """Remember the newest channel_update so clips can be tagged with it."""
    ids = entry.get('channels')
    if not isinstance(ids, list):
        return
    snapshot = {cid: entry[cid] for cid in ids
                if isinstance(entry.get(cid), dict)}
    with _last_channels_lock:
        _last_channels.clear()
        _last_channels.update(snapshot)

    for chan in snapshot.values():
        path = chan.get('capture_file')
        if path and path not in _capture_files:
            _capture_files.append(path)


def _note_trunk_update(entry: dict[str, Any]) -> None:
    """Fold each system's talkgroup activity into the durable store, then merge
    the durable values back into the payload the browser is about to receive.

    trunk_update is keyed by integer-as-string system index (tk_p25.p25_rx_ctl
    numbers them 0, 1, ... in to_json) with the system name inside each entry, so
    the systems are found by shape rather than by a fixed key list.
    """
    if talkgroup_store is None:
        return
    for value in entry.values():
        if not isinstance(value, dict):
            continue
        tgid_tags = value.get('tgid_tags')
        if not isinstance(tgid_tags, dict):
            continue
        system = str(value.get('system') or '')
        talkgroup_store.observe(system, tgid_tags)
        talkgroup_store.merge_into(system, tgid_tags)


def _note_call_log(entry: dict[str, Any]) -> None:
    """Accumulate the draining call_log feed so late joiners see history."""
    log = entry.get('log')
    if not isinstance(log, list) or not log:
        return
    with _recent_calls_lock:
        _recent_calls.extend(e for e in log if isinstance(e, dict))


def _recent_call_log(limit: int = _CALL_LOG_HISTORY) -> list[dict[str, Any]]:
    with _recent_calls_lock:
        entries = list(_recent_calls)
    return entries[-limit:]


def _current_call_metadata() -> dict[str, Any]:
    """Metadata describing the call currently on the air.

    All configured channels share one audio capture, so when several are
    active at once the tag is best-effort: the first channel reporting a
    talkgroup wins.  Single-channel setups — the common case — are exact.
    """
    with _last_channels_lock:
        channels = list(_last_channels.values())

    for ch in channels:
        if not ch.get('tgid'):
            continue
        return {
            'system':     ch.get('system') or '',
            'channel':    ch.get('name') or '',
            'tgid':       int(ch.get('tgid') or 0),
            'talkgroup':  ch.get('tag') or '',
            'source':     int(ch.get('srcaddr') or 0),
            'source_tag': ch.get('srctag') or '',
            'frequency':  int(ch.get('freq') or 0),
            'encrypted':  bool(ch.get('encrypted')),
            'emergency':  bool(ch.get('emergency')),
        }
    return {}


def _on_clip_complete(clip: CallClip) -> None:
    """A call finished recording: tell the UI, then queue it for Home Assistant.

    The pending flag is stamped *before* the broadcast, not by ``submit()``:
    the clip goes out to the UI first (so a row appears the instant the
    transmission ends), and the worker thread could otherwise transcribe and
    re-broadcast it before this first message was even serialised.
    """
    if _ha_bridge is not None:
        clip.transcript_pending = _ha_bridge.will_transcribe(clip)
    _broadcast_from_thread(MSG_CALL_AUDIO, dict(clip.to_dict(), json_type='call_clip'))
    if _ha_bridge is not None:
        _ha_bridge.submit(clip)


def _on_transcript(clip: CallClip) -> None:
    """Speech-to-text finished for a clip: push the text to the UI."""
    _broadcast_from_thread(MSG_CALL_AUDIO, dict(clip.to_dict(), json_type='call_transcript'))


def _call_capture_settings(config: dict[str, Any] | None) -> dict[str, Any]:
    """Recorder tuning from ``terminal.home_assistant``, with defaults."""
    ha = (config or {}).get('terminal', {}).get('home_assistant', {}) or {}
    return {
        'hang_time_secs':   float(ha.get('hang_time_secs', 1.5) or 1.5),
        'min_call_secs':    float(ha.get('min_call_secs', 0.8) or 0.8),
        'max_call_secs':    float(ha.get('max_call_secs', 120.0) or 120.0),
        'min_peak':         int(ha.get('min_peak', 250) or 250),
        'normalize':        ha.get('normalize', True) is not False,
        'target_rms':       float(ha.get('normalize_target_rms', 3_000.0) or 3_000.0),
        'max_gain_db':      float(ha.get('normalize_max_gain_db', 24.0) or 24.0),
        'min_voiced_ratio': float(ha.get('min_voiced_ratio', 0.0) or 0.0),
    }


def _routable_address_for(target_url: str) -> str:
    """Our own IP on the interface that reaches *target_url*, or ''.

    ``localhost`` is the wrong answer to "where can Home Assistant fetch this
    clip from" — it points HA back at itself — and so is any address picked by
    ``gethostname()``, which on a multi-homed box may be a VPN or Docker
    interface.  Connecting a UDP socket sends no packets; it only asks the
    kernel to pick a source address for that destination, which is exactly the
    address Home Assistant will see our webhook arrive from.
    """
    if not target_url:
        return ''
    try:
        parsed = urlparse(target_url)
        host = parsed.hostname
        if not host:
            return ''
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(1.0)
            s.connect((host, parsed.port or 8123))
            addr = s.getsockname()[0]
        return '' if addr.startswith('127.') else addr
    except Exception:
        return ''


def start_call_capture(config: dict[str, Any] | None,
                       endpoint: str | None = None) -> None:
    """Start the call recorder, plus the Home Assistant bridge when configured.

    Recording is on by default — it costs a bounded slice of memory and is
    what makes /api/calls useful — but can be turned off entirely with
    ``"terminal": { "call_recording": false }``.

    *endpoint* is the ``host:port`` this server is bound to.  It supplies a
    fallback for ``home_assistant.public_url`` so webhook payloads carry an
    absolute audio URL that Home Assistant can actually fetch.
    """
    global _call_capture, _ha_bridge

    terminal = (config or {}).get('terminal', {}) or {}
    if terminal.get('call_recording', True) is False:
        sys.stderr.write('call capture: disabled by terminal.call_recording\n')
        return

    ha_cfg = HomeAssistantConfig(terminal.get('home_assistant'))
    if not ha_cfg.public_url and endpoint:
        host, _, port = endpoint.partition(':')
        port = port or '8080'
        if host not in ('', '0.0.0.0', '::'):
            ha_cfg.public_url = 'http://%s:%s' % (host, port)
        else:
            # 0.0.0.0 is a bind address, not a reachable one.  Ask the routing
            # table which of our addresses reaches Home Assistant and publish
            # that, because the whole point of the URL is for Home Assistant
            # to fetch from it.
            addr = _routable_address_for(ha_cfg.url)
            if addr:
                ha_cfg.public_url = 'http://%s:%s' % (addr, port)
    if ha_cfg.enabled and _ha_bridge is None:
        _ha_bridge = HomeAssistantBridge(ha_cfg, on_transcript=_on_transcript)
        _ha_bridge.start()

    if _call_capture is None:
        settings = _call_capture_settings(config)
        _call_capture = CallCapture(lambda _port: CallRecorder(
            clip_store,
            sample_rate=_SAMPLE_RATE,
            metadata_fn=_current_call_metadata,
            on_complete=_on_clip_complete,
            **settings,
        ))


def stop_call_capture() -> None:
    global _call_capture, _ha_bridge
    if _call_capture is not None:
        _call_capture.flush()
        _call_capture = None
    if _ha_bridge is not None:
        _ha_bridge.stop()
        _ha_bridge = None


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

    Thin wrapper over :func:`_discover_audio_endpoints` for the UDP receiver,
    which only needs somewhere to bind.
    """
    return [(ep['host'], ep['port']) for ep in _discover_audio_endpoints(config)]


def _discover_audio_endpoints(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Describe every UDP audio stream the decoder will produce.

    Each entry is ``{host, port, channel, name, slot}`` where *channel* is the
    index into the config's ``channels`` list (None when it cannot be
    attributed) and *slot* is ``'A'`` or ``'B'``.

    Each channel with a ``destination`` of the form ``udp://host:port``
    contributes two ports — ``port`` (slot A) and ``port + 1`` (slot B, used
    for TDMA phase-2 and DMR).  The two slots of one channel are *independent
    conversations*, which is why they stay separate streams rather than being
    mixed together.  If no UDP destinations are configured we fall back to the
    OP25 default of ``127.0.0.1:23456``/``23457`` so the browser stream still
    has a chance of receiving audio when the user later adds a destination
    matching the default.
    """
    endpoints: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    def add(host: str, port: int, channel: int | None, name: str, slot: str) -> None:
        key = (host, port)
        if key in seen:
            return
        seen.add(key)
        endpoints.append({'host': host, 'port': port,
                          'channel': channel, 'name': name, 'slot': slot})

    # An explicit "audio_ports" in the terminal config wins outright.  It is the
    # escape hatch for running local speaker output and browser audio at once:
    # point the channel at two udp destinations and name the spare one here.
    # Which channel such a port belongs to is not knowable from the config, so
    # these are reported unattributed.
    override = (config or {}).get('terminal', {}).get('audio_ports')
    if override:
        for entry in (override if isinstance(override, list) else [override]):
            try:
                add('127.0.0.1', int(entry), None, 'audio_ports override', 'A')
            except (TypeError, ValueError):
                sys.stderr.write('ws audio: ignoring invalid audio_ports entry %r\n' % (entry,))
        if endpoints:
            return endpoints

    for idx, ch in enumerate((config or {}).get('channels', []) or []):
        ch_name = str(ch.get('name') or f'channel {idx}')
        # 'destination' is a comma-separated list of destinations — op25_audio.cc
        # tokenizes on ',' — so a channel may feed udp and ws sinks at once,
        # e.g. "udp://0.0.0.0:23456, ws://0.0.0.0:9000".  Only the udp ones
        # carry the PCM this server re-streams to the browser.
        for dest in str(ch.get('destination', '') or '').split(','):
            dest = dest.strip()
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
            add(host, port,     idx, ch_name, 'A')
            add(host, port + 1, idx, ch_name, 'B')

    # Ports sockaudio.py will bind for local speaker output.  A unicast UDP port
    # has exactly one consumer, so binding these as well would only make
    # whichever thread loses the race go silent.  Compare on port number alone —
    # a destination of 0.0.0.0 and sockaudio's 127.0.0.1 carry the same traffic.
    #
    # Only when the audio module is actually loaded, though.  multi_rx's
    # configure_audio() returns early on an empty "module", so the instances
    # list is inert and nothing binds those ports — yielding them to the browser
    # is then correct, and excluding them would silence a config whose only
    # crime is leaving a stale audio block in place.  The Home Assistant add-on
    # runs exactly that way by default.
    audio_cfg = (config or {}).get('audio', {}) or {}
    local: set[int] = set()
    instances = audio_cfg.get('instances', []) or []
    if not str(audio_cfg.get('module', '') or '').strip():
        instances = []
    for inst in instances:
        try:
            port = int(inst.get('udp_port', _DEFAULT_AUDIO_PORT))
        except (TypeError, ValueError):
            continue
        local.update((port, port + 1))       # sockaudio binds both TDMA slots

    if local:
        kept = [ep for ep in endpoints if ep['port'] not in local]
        if endpoints and not kept:
            sys.stderr.write(
                'ws audio: every UDP audio port is claimed by the local audio module, '
                'so browser audio is disabled.  To run both, give the channel a second '
                'destination on a free port and point this server at it, e.g.\n'
                '    "destination": "udp://127.0.0.1:23456, udp://127.0.0.1:23458"\n'
                '    "terminal": { ..., "audio_ports": [23458] }\n')
        endpoints = kept

    if not endpoints and not local:
        add('127.0.0.1', _DEFAULT_AUDIO_PORT,     None, 'default', 'A')
        add('127.0.0.1', _DEFAULT_AUDIO_PORT + 1, None, 'default', 'B')

    return endpoints


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
        # Which port each socket is bound to. Needed because each port gets
        # its own call recorder — see CallCapture.
        self._port_by_fd: dict[int, int] = {}
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
                self._port_by_fd[s.fileno()] = port
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
        self._port_by_fd.clear()

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
                    port = self._port_by_fd.get(s.fileno(), 0)
                    audio_manager.push_audio(data, port)    # aggregate stream (mixed)
                    per_port = _port_managers.get(port)     # per-channel stream
                    if per_port is not None:
                        per_port.push_audio(data)
                    if _call_capture is not None:
                        _call_capture.push(port, data)
                else:
                    # Unknown packet shape — log once-ish via the throttle.
                    self.packets_other += 1

            # select() returns at least once a second, which is frequent
            # enough to close out a call after its hang time expires.
            if _call_capture is not None:
                _call_capture.poll()

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

        # 'underruns' counts only dropouts with audio in flight — idle silence is
        # 'silent'. A rising underrun count against a steady 'voice' count is a
        # jitter problem in this process, not a bad RF decode; see
        # _STREAM_PRIME_MS.
        sys.stderr.write(
            'ws audio: rx pcm=%d flag=%d other=%d  in=%d B (+%d, %.1f kbps)  '
            'buf=%d B  pushed=%d  yielded=%d  voice=%d  silent=%d  underruns=%d  '
            'dropped=%d\n' % (
                self.packets_pcm, self.packets_flag, self.packets_other,
                self.bytes_in, delta_bytes, rate_kbps,
                buffered,
                audio_manager.bytes_pushed,
                audio_manager.bytes_yielded,
                audio_manager.real_chunks,
                audio_manager.silent_chunks,
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
MSG_CALL_ACTIVITY = "CALL_ACTIVITY"
MSG_CALL_AUDIO    = "CALL_AUDIO"

# Upstream
MSG_CALL_CONTROL   = "CALL_CONTROL"
MSG_SYSTEM_CONTROL = "SYSTEM_CONTROL"

DOWNSTREAM_TYPES = {MSG_SYSTEM_STATE, MSG_CALL_ACTIVITY, MSG_CALL_AUDIO}
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

    def client_count(self) -> int:
        """Number of attached clients.

        Polled by ws_terminal to decide whether anything is still watching the
        signal plots, which are the one thing the decoder computes purely for
        the browser's benefit.
        """
        return len(self._connections)

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
#
# Every key here is a json_type some decoder module actually emits — grep for
# "'json_type'" under apps/ for the authoritative list.  An earlier version of
# this table keyed on chan_status / trunked_site_status / sys_info, none of
# which exist, which made the documented protocol wider than the wire.
# Anything not listed falls through to SYSTEM_STATE (see _dispatch), which is
# where trunk_update, channel_update and plot land.
_JSON_TYPE_TO_MSG: dict[str, str] = {
    "call_log":        MSG_CALL_ACTIVITY,
    "terminal_config": MSG_SYSTEM_STATE,
    "full_config":     MSG_SYSTEM_STATE,
    "meta_update":     MSG_SYSTEM_STATE,
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
        "payload": _system_state_payload(),
    })
    # Replay the call history this client missed.  call_log is a draining feed,
    # so without this a page opened mid-shift starts blank and stays blank
    # until the next transmission.
    history = _recent_call_log()
    if history:
        await manager.send(websocket, {
            "type": MSG_CALL_ACTIVITY,
            "payload": {"json_type": "call_log", "log": history, "replay": True},
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

# ---------------------------------------------------------------------------
# Editable configuration
# ---------------------------------------------------------------------------

def _init_config_store() -> None:
    """(Re)build the config store from the installed config."""
    global _config_store
    if _config_store is not None:
        _config_store.close()
        _config_store = None
    if _config is None:
        return
    base_id = str(((_config.get('terminal') or {}).get('config_base_id')
                   or os.environ.get('OP25_CONFIG_BASE_ID') or 'config'))
    _config_store = config_store.ConfigStore(
        _config,
        overlay_file=config_store.overlay_path(_config),
        history_file=config_store.history_db_path(_config),
        base_id=base_id,
    )


def _write_policy() -> str:
    """``'ingress'``, ``'open'`` or ``'off'`` -- who may change the config.

    Writing the config from an unauthenticated port is a real escalation, not a
    theoretical one: port 8099 has ``allow_origins=["*"]`` and no token, so
    anyone on the LAN could re-point the receiver or change the Home Assistant
    webhook. Ingress is the authenticated path, so in the add-on that is the only
    one permitted.

    The default is therefore ``ingress`` when running as an add-on and ``open``
    otherwise. ``$SUPERVISOR_TOKEN`` is what distinguishes the two -- bashio
    exports it in the container and nothing else sets it -- because a standalone
    install has no ingress to require, and defaulting to ``ingress`` there would
    make the editor permanently unreachable rather than secure.
    """
    env = os.environ.get('OP25_CONFIG_WRITE')
    if env:
        return env.strip().lower()
    terminal = (_config or {}).get('terminal', {}) or {}
    configured = terminal.get('config_write')
    if configured:
        return str(configured).strip().lower()
    return 'ingress' if os.environ.get('SUPERVISOR_TOKEN') else 'open'


def _write_denied(request: Any) -> Response | None:
    """None if this request may write, else the Response to return."""
    policy = _write_policy()
    if policy == 'open':
        return None
    if policy == 'ingress':
        # Supervisor's ingress proxy sets this on every request it forwards, and
        # it cannot be reached from the published port.
        if request is not None and request.headers.get('x-ingress-path') is not None:
            return None
        return Response(
            content=json.dumps({
                'error': 'config writes require the Home Assistant ingress path',
                'detail': 'Open OP25 from the Home Assistant sidebar rather than '
                          'via port 8099, which is unauthenticated. Set the '
                          'config_write option to "open" to allow it anyway.',
                'policy': policy,
            }),
            status_code=403, media_type='application/json',
            headers={'Cache-Control': 'no-store'})
    return Response(
        content=json.dumps({'error': 'config editing is disabled', 'policy': policy}),
        status_code=403, media_type='application/json',
        headers={'Cache-Control': 'no-store'})


def _json(payload: Any, status_code: int = 200) -> Response:
    return Response(content=json.dumps(payload), status_code=status_code,
                    media_type='application/json',
                    headers={'Cache-Control': 'no-store'})


def _no_store() -> Response:
    return _json({'error': 'config editing is unavailable',
                  'detail': 'No config is loaded, or no overlay path is configured.'},
                 status_code=503)


@app.get("/api/config/schema")
async def get_config_schema(
    protocol: str | None = Query(None, description="Filter to one trunking module"),
) -> Response:
    """Field metadata the editor renders itself from.

    Filtering by protocol is what keeps this from being a P25 form: a field that
    means nothing for SmartNet is not shown for SmartNet.
    """
    if protocol is None and _config is not None:
        protocol = ((_config.get('trunking') or {}).get('module')) or None
    return _json(config_schema.schema(protocol))


@app.get("/api/config/state")
async def get_config_state() -> Response:
    """Everything the editor needs to render: effective config, overlay, drift."""
    if _config_store is None:
        return _no_store()
    return _json({
        # stats() is spread FIRST so the computed keys below win. It carries its
        # own 'editable' -- meaning only "an overlay path exists" -- and spreading
        # it last silently replaced the write-policy-aware value with that one.
        # Same trap as tg_metadata.stats() vs /api/talkgroups.
        **_config_store.stats(),
        'editable': _config_store.editable and _write_policy() != 'off',
        'write_policy': _write_policy(),
        'effective': redact_config(_config_store.effective()),
        'base': redact_config(_config_store.base),
        'overlay': redact_config(_config_store.overlay()),
        'preset_drift': _config_store.preset_drift(),
    })


@app.get("/api/config/history")
async def get_config_history(
    limit: int = Query(50, ge=1, le=config_store.MAX_VERSIONS),
) -> Response:
    if _config_store is None:
        return _no_store()
    return _json({'versions': [
        {**v, 'overlay': redact_config(v['overlay'])}
        for v in _config_store.history(limit)
    ]})


def _apply_and_classify(changes: list[dict[str, Any]]) -> dict[str, Any]:
    """Dispatch the live half of a diff to the decoder; report the rest.

    Returning ``needs_restart`` honestly is the point. Reporting a
    restart-required change as applied would leave the user trusting a value the
    decoder is not running -- and gain, the field most worth changing, is one of
    the few that *is* live, so the distinction is visible immediately.
    """
    verdict = config_schema.classify(changes)
    applied: list[str] = []
    for change in verdict['live']:
        path, new = change['path'], change.get('new')
        device = None
        if path.startswith('devices[') and '].' in path:
            device = path[len('devices['):path.index('].')]
        if device is None:
            continue
        if path.endswith('.gains'):
            _send_upstream({'command': 'set_device_gains', 'device': device,
                            'gains': new})
            applied.append(path)
        elif path.endswith('.ppm'):
            _send_upstream({'command': 'set_device_ppm', 'device': device,
                            'ppm': new})
            applied.append(path)
    verdict['applied'] = applied
    return verdict


@app.put("/api/config")
async def put_config(request: Request) -> Response:
    """Save a full effective config as overrides of the preset.

    The body is what the caller wants to be running, not a patch -- that is what
    a form or a JSON editor naturally produces, and the delta is computed here so
    a field set back to the preset value stops being an override.
    """
    denied = _write_denied(request)
    if denied is not None:
        return denied
    if _config_store is None or not _config_store.editable:
        return _no_store()
    try:
        body = await request.json()
    except (ValueError, TypeError):
        return _json({'error': 'body is not valid JSON'}, status_code=400)
    if not isinstance(body, dict):
        return _json({'error': 'body must be a JSON object'}, status_code=400)
    proposed = body.get('config', body)
    if not isinstance(proposed, dict):
        return _json({'error': '"config" must be a JSON object'}, status_code=400)
    problems = _validate_config(proposed)
    if problems:
        return _json({'error': 'config is not valid', 'problems': problems},
                     status_code=422)
    try:
        version = _config_store.save(proposed, source=str(body.get('source', 'gui')),
                                     summary=str(body.get('summary', '')))
    except (OSError, RuntimeError) as e:
        return _json({'error': 'could not write the overlay', 'detail': str(e)},
                     status_code=500)
    return _json({'ok': True,
                  'version': {**version, 'overlay': redact_config(version['overlay'])},
                  **_apply_and_classify(version['diff'])})


@app.post("/api/config/rollback/{version_id}")
async def post_config_rollback(version_id: int, request: Request) -> Response:
    denied = _write_denied(request)
    if denied is not None:
        return denied
    if _config_store is None or not _config_store.editable:
        return _no_store()
    try:
        version = _config_store.rollback(version_id)
    except KeyError:
        return _json({'error': 'no such config version', 'id': version_id},
                     status_code=404)
    except (OSError, RuntimeError) as e:
        return _json({'error': 'could not write the overlay', 'detail': str(e)},
                     status_code=500)
    return _json({'ok': True,
                  'version': {**version, 'overlay': redact_config(version['overlay'])},
                  **_apply_and_classify(version['diff'])})


@app.post("/api/config/reset")
async def post_config_reset(request: Request) -> Response:
    """Discard every override and run the preset as shipped."""
    denied = _write_denied(request)
    if denied is not None:
        return denied
    if _config_store is None or not _config_store.editable:
        return _no_store()
    try:
        version = _config_store.reset_to_preset()
    except (OSError, RuntimeError) as e:
        return _json({'error': 'could not write the overlay', 'detail': str(e)},
                     status_code=500)
    return _json({'ok': True, 'version': version, **_apply_and_classify(version['diff'])})


@app.post("/api/config/export")
async def post_config_export(request: Request) -> Response:
    """Write the effective config out as a standalone, fully-owned file.

    The result stops tracking the preset, which is the trade being made: this is
    for graduating to ``preset: custom``.
    """
    denied = _write_denied(request)
    if denied is not None:
        return denied
    if _config_store is None:
        return _no_store()
    try:
        body = await request.json()
    except (ValueError, TypeError):
        body = {}
    path = str((body or {}).get('path') or 'op25.exported.json')
    allowed = _export_denied(path)
    if allowed is not None:
        return allowed
    try:
        written = _config_store.export(path)
    except OSError as e:
        return _json({'error': 'could not write the export', 'detail': str(e)},
                     status_code=500)
    return _json({'ok': True, 'path': written,
                  'note': 'This file no longer tracks the preset. Point the '
                          'config_file option at it and set preset: custom to use it.'})


def _export_roots() -> list[str]:
    """Directories an export may be written to.

    The working directory is included because that *is* the data directory: it is
    where multi_rx resolves tag files, where tg_metadata puts its database, and on
    a standalone install it is the only writable location that exists. Restricting
    to /share, /config and /data alone would refuse every legitimate path outside
    the add-on. ``$OP25_EXPORT_ROOTS`` overrides for an unusual layout.
    """
    env = os.environ.get('OP25_EXPORT_ROOTS')
    if env:
        return [p for p in (part.strip() for part in env.split(':')) if p]
    roots = [os.getcwd()]
    roots.extend(d for d in ('/share', '/config', '/data') if os.path.isdir(d))
    return roots


def _export_denied(path: str) -> Response | None:
    """None if *path* is inside an allowed root, else the Response to return.

    Defence in depth -- writes are already gated to ingress. This is here so a
    path traversal in an export request cannot drop a file anywhere on the
    filesystem, which matters because the config it writes is attacker-chosen.
    """
    roots = [os.path.realpath(r) for r in _export_roots()]
    target = os.path.realpath(os.path.join(os.getcwd(), path))
    if any(target == r or target.startswith(r + os.sep) for r in roots):
        return None
    return _json({'error': 'refusing to write outside the allowed directories',
                  'path': path, 'allowed': roots}, status_code=400)


def _validate_config(cfg: dict[str, Any]) -> list[str]:
    """Cheap structural validation. Not a schema check -- a footgun check.

    Only rules whose violation would stop the decoder starting, or would start it
    in a state with no way back through the UI. Everything subtler is left to the
    decoder, which reports it in the log.
    """
    problems: list[str] = []
    devices = cfg.get('devices')
    channels = cfg.get('channels')
    if not isinstance(devices, list) or not devices:
        problems.append('devices must be a non-empty list')
        devices = []
    if not isinstance(channels, list) or not channels:
        problems.append('channels must be a non-empty list')
        channels = []

    names = set()
    for i, dev in enumerate(devices):
        if not isinstance(dev, dict):
            problems.append('devices[%d] is not an object' % i)
            continue
        name = dev.get('name')
        if not name:
            problems.append('devices[%d] has no name' % i)
        elif name in names:
            problems.append('duplicate device name %r' % name)
        else:
            names.add(name)
        rate, if_rate = dev.get('rate'), None
        for ch in channels if isinstance(channels, list) else []:
            if isinstance(ch, dict) and ch.get('device') == name:
                if_rate = ch.get('if_rate')
                break
        if isinstance(rate, (int, float)) and isinstance(if_rate, (int, float)) \
                and if_rate and rate % if_rate:
            # Not fatal -- an arbitrary resampler covers it -- so this is a
            # warning in problems' clothing only if it were fatal. Keep it out.
            pass
        if 'gains' in dev and dev['gains']:
            try:
                for tup in str(dev['gains']).split(','):
                    if tup.strip():
                        stage, value = tup.split(':', 1)
                        if not stage.strip():
                            raise ValueError
                        float(value)
            except ValueError:
                problems.append('devices[%s].gains is not STAGE:value' % (name or i))

    for i, ch in enumerate(channels):
        if not isinstance(ch, dict):
            problems.append('channels[%d] is not an object' % i)
            continue
        if ch.get('device') and names and ch['device'] not in names:
            problems.append('channels[%d].device %r matches no device'
                            % (i, ch['device']))
        if not ch.get('if_rate'):
            problems.append('channels[%d] has no if_rate' % i)

    terminal = cfg.get('terminal')
    if terminal is not None and not isinstance(terminal, dict):
        problems.append('terminal must be an object')
    return problems


@app.get("/api/config")
async def get_config() -> Response:
    """Return the loaded config JSON, or 404 when no config file was supplied.

    Secrets are stripped: this endpoint is unauthenticated, so a Home
    Assistant token sitting in ``terminal.home_assistant.token`` would
    otherwise be readable by anyone who can reach the port.
    """
    if _config is None:
        return Response(
            content='{"error": "No config loaded. Start the server with --config-file."}',
            status_code=404,
            media_type="application/json",
        )
    return Response(content=json.dumps(redact_config(_config)),
                    media_type="application/json")


# ---------------------------------------------------------------------------
# Audio stream endpoint
# ---------------------------------------------------------------------------

_ALLOWED_STREAM_RATES = (8_000, 16_000, 22_050, 24_000, 44_100, 48_000)


@app.get("/api/audio/channels")
async def list_audio_channels() -> Response:
    """The audio streams this server can serve, one per decoder UDP port.

    A channel's two slots are listed separately because on DMR they carry two
    unrelated conversations; ``bytes`` lets a client hide the ones that have
    never carried anything (slot B on a P25 system, for instance).
    """
    streams = []
    for ep in _audio_endpoints:
        mgr = _port_managers.get(ep['port'])
        streams.append({
            'channel': ep['channel'],
            'name':    ep['name'],
            'slot':    ep['slot'],
            'port':    ep['port'],
            'bytes':   mgr.bytes_pushed if mgr else 0,
            'url':     '/api/stream?port=%d' % ep['port'],
        })
    body = {'streams': streams, 'aggregate_url': '/api/stream'}
    return Response(content=json.dumps(body), media_type="application/json",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/stream")
async def audio_stream(
    rate: int = Query(_SAMPLE_RATE, description="Output sample rate in Hz"),
    format: str = Query("wav", pattern="^(wav|raw)$",
                        description="'wav' for a WAV-wrapped stream, 'raw' for headerless PCM"),
    channel: int | None = Query(None, description="Config channel index; streams that channel's slot A"),
    port: int | None = Query(None, description="Exact decoder UDP port to stream (see /api/audio/channels)"),
) -> StreamingResponse:
    """Continuous audio stream — the browser player and external consumers.

    Streams 16-bit / mono PCM.  Defaults (8 kHz, WAV-wrapped, every channel
    mixed together) are exactly what the decoder produces and what the React
    player expects; nothing changes unless a query parameter is supplied.

    ``channel=N`` streams just that config channel, and ``port=N`` just that
    UDP port (which is how to reach a DMR slot B) — without either, the mix of
    all ports is served as it always has been.

    ``rate=16000`` resamples on the way out, which is what Home Assistant's
    voice pipeline and Whisper require.  ``format=raw`` drops the WAV header
    for consumers that would rather be handed bare PCM.

    When the OP25 decoder is not yet connected the generator emits silence
    (or a 600 Hz test tone in mock mode) so the HTTP connection stays alive
    and buffered audio is not dropped on reconnect.
    """
    if rate not in _ALLOWED_STREAM_RATES:
        return Response(
            content=json.dumps({
                "error": "unsupported rate",
                "supported": list(_ALLOWED_STREAM_RATES),
            }),
            status_code=400,
            media_type="application/json",
        )

    manager = audio_manager
    if port is not None:
        manager = _port_managers.get(port)
        if manager is None:
            return Response(
                content=json.dumps({
                    "error": "unknown port",
                    "known": sorted(_port_managers),
                }),
                status_code=404,
                media_type="application/json",
            )
    elif channel is not None:
        manager = _manager_for_channel(channel)
        if manager is None:
            return Response(
                content=json.dumps({
                    "error": "unknown channel",
                    "known": sorted({ep['channel'] for ep in _audio_endpoints
                                     if ep['channel'] is not None}),
                }),
                status_code=404,
                media_type="application/json",
            )

    return StreamingResponse(
        manager.generate(out_rate=rate, container=format),
        media_type="audio/wav" if format == "wav" else "audio/L16",
        headers={
            "Cache-Control":          "no-store",
            "Accept-Ranges":          "none",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---------------------------------------------------------------------------
# Talkgroup metadata
# ---------------------------------------------------------------------------

@app.get("/api/talkgroups")
async def list_talkgroups(
    system: str | None = Query(None, description="Restrict to one trunking system"),
    heard: bool = Query(False, description="Only talkgroups heard at least once"),
) -> Response:
    """Every talkgroup on record, newest activity first.

    This is the durable view -- it includes talkgroups last heard in a *previous*
    run of the decoder, which the live trunk_update payload cannot describe.  The
    Talkgroup Browser uses it to offer a complete pick-list rather than only what
    has been seen since start-up.
    """
    if talkgroup_store is None:
        return Response(
            content=json.dumps({"talkgroups": [], "count": 0, "persistent": False}),
            media_type="application/json", headers={"Cache-Control": "no-store"})
    rows = talkgroup_store.talkgroups(system)
    if heard:
        rows = [r for r in rows if r['last_seen'] > 0]
    body = {"talkgroups": rows, "count": len(rows)}
    body.update(talkgroup_store.stats())
    return Response(content=json.dumps(body), media_type="application/json",
                    headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# Captured call clips  (speech-to-text / Home Assistant integration)
# ---------------------------------------------------------------------------

@app.get("/api/calls")
async def list_calls(limit: int = Query(50, ge=1, le=500)) -> Response:
    """Recent captured calls, newest first, with transcripts when available."""
    calls = [c.to_dict() for c in clip_store.recent(limit)]
    body  = {"calls": calls, "count": len(calls)}
    body.update(clip_store.stats())
    return Response(content=json.dumps(body), media_type="application/json",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/calls/{call_id}/audio.wav")
async def call_audio(
    call_id: str,
    rate: int = Query(_SAMPLE_RATE, description="Output sample rate in Hz"),
) -> Response:
    """A single captured call as a finite WAV file.

    Finite (real RIFF/data sizes) rather than the unbounded header used by
    /api/stream, so it can be downloaded, seeked, handed to an STT engine,
    or played by a Home Assistant media player.
    """
    clip = clip_store.get(call_id)
    if clip is None:
        return Response(content='{"error": "unknown call id"}', status_code=404,
                        media_type="application/json")
    if rate not in _ALLOWED_STREAM_RATES:
        return Response(content='{"error": "unsupported rate"}', status_code=400,
                        media_type="application/json")

    pcm = resample_pcm16(clip.pcm, clip.sample_rate, rate)
    return Response(
        content=wav_bytes(pcm, rate),
        media_type="audio/wav",
        headers={
            "Cache-Control":        "no-store",
            "Content-Disposition":  'inline; filename="op25-%s.wav"' % call_id,
        },
    )


# ---------------------------------------------------------------------------
# Symbol captures  (the 'capture' command's output)
# ---------------------------------------------------------------------------

def _capture_entry(path: str) -> dict[str, Any]:
    """Describe one capture file, whether or not it still exists on disk."""
    try:
        stat = os.stat(path)
        return {
            'name':     os.path.basename(path),
            'path':     path,
            'size':     stat.st_size,
            'modified': int(stat.st_mtime),
            'exists':   True,
        }
    except OSError:
        return {'name': os.path.basename(path), 'path': path,
                'size': 0, 'modified': 0, 'exists': False}


@app.get("/api/captures")
async def list_captures() -> Response:
    """Raw symbol-capture files this decoder run has written.

    The decoder names them from the channel's ``raw_output`` config key, or
    ``ch<N>-<default>``, relative to the directory multi_rx was started in —
    which is why the list comes from what channel_update reported rather than
    from scanning a directory.
    """
    body = {"captures": [_capture_entry(p) for p in _capture_files]}
    return Response(content=json.dumps(body), media_type="application/json",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/captures/{name}")
async def get_capture(name: str) -> Response:
    """Download one capture file by basename.

    Only files the decoder actually reported are served — the name is matched
    against that list rather than joined onto a directory, so there is no path
    for a request to reach an arbitrary file.
    """
    for path in _capture_files:
        if os.path.basename(path) == name:
            if not os.path.isfile(path):
                return Response(content='{"error": "capture file is gone"}',
                                status_code=404, media_type="application/json")
            return FileResponse(
                path,
                media_type="application/octet-stream",
                filename=name,
            )
    return Response(content='{"error": "unknown capture"}', status_code=404,
                    media_type="application/json")


@app.get("/api/ha/status")
async def ha_status() -> Response:
    """Diagnostics for the call-capture and Home Assistant pipeline.

    The first thing to check when transcripts are not appearing: it shows
    whether calls are being captured at all, and separately whether the
    speech-to-text and webhook round-trips are succeeding.
    """
    body: dict[str, Any] = {
        "call_recording": _call_capture is not None,
        "store":          clip_store.stats(),
    }
    if _call_capture is not None:
        body["recorder"] = _call_capture.stats()
    if _ha_bridge is None:
        body["home_assistant"] = {"enabled": False}
    else:
        body["home_assistant"] = dict(
            _ha_bridge.stats(),
            enabled=True,
            url=_ha_bridge.cfg.url,
            stt_engine=_ha_bridge.cfg.stt_engine if _ha_bridge.cfg.stt_configured else None,
            webhook_id=_ha_bridge.cfg.webhook_id if _ha_bridge.cfg.webhook_configured else None,
            keywords=[term for term, _ in _ha_bridge.cfg.keywords],
        )
    return Response(content=json.dumps(body), media_type="application/json",
                    headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------
# Static file serving (SPA with client-side routing fallback)
# ------------------------------------------------------------------

def _resolve_dist_path(url_path: str) -> str | None:
    rel = url_path.lstrip('/')
    candidate = os.path.realpath(os.path.join(_DIST_DIR, rel))
    if not candidate.startswith(_DIST_DIR + os.sep) and candidate != _DIST_DIR:
        return None
    return candidate


# Extensions that are files on disk, never client-side routes.  A request for
# one of these that does not exist has to 404: handing back index.html instead
# makes the browser report
#
#   'text/html' is not a valid JavaScript MIME type for module script
#
# and renders a blank page, which says nothing about the real problem (the
# client asked for a build artifact this server does not have).  SPA routes are
# always extensionless, so this cannot swallow one.
_ASSET_SUFFIXES = frozenset((
    '.js', '.mjs', '.css', '.map', '.json', '.wasm',
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.avif', '.ico',
    '.woff', '.woff2', '.ttf', '.otf', '.eot',
))


@app.get("/{full_path:path}")
async def serve_spa(full_path: str) -> Response:
    if full_path and full_path != "/":
        resolved = _resolve_dist_path(full_path)
        if resolved and os.path.isfile(resolved):
            # Vendor chunks and assets carry a content hash, so the URL changes
            # whenever the bytes do and they can be cached hard.  The entry
            # chunk is hashed too (vite.config.ts) precisely so this is safe.
            return FileResponse(resolved, headers={
                'Cache-Control': 'public, max-age=31536000, immutable',
            })

        suffix = os.path.splitext(full_path)[1].lower()
        if suffix in _ASSET_SUFFIXES:
            return Response(
                content='Not found: %s\n\nThis is a build artifact, not a route. '
                        'If the browser asked for it, it is running a stale '
                        'index.html — reload.\n' % full_path,
                status_code=404,
                media_type='text/plain',
                headers={'Cache-Control': 'no-store'},
            )

    index_path = os.path.join(_DIST_DIR, "index.html")
    if os.path.isfile(index_path):
        # Never cache the entry document.  It is the only file whose URL is
        # stable across builds, so a cached copy pairs a new deployment's
        # chunk list with the old one's filenames and the app fails to boot --
        # which is exactly what an add-on update used to do to an open tab.
        return FileResponse(index_path, media_type="text/html",
                            headers={'Cache-Control': 'no-store'})

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

    # How long after the last client disconnects before the decoder is told to
    # shut its signal plots down.  Long enough that a page reload does not cost
    # the user their enabled plots (op25Service re-adopts whatever modes it sees
    # data for, so a torn-down plot comes back dark), short enough that a closed
    # tab is not left burning DSP cycles on traces nobody will ever see.
    PLOT_IDLE_GRACE: float = 5.0

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
        global _output_q
        _output_q = output_q
        # None == clients attached; a timestamp == idle since then; -1 == idle
        # and the decoder has already been told to close its plots.
        self._idle_since: float | None = None

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
        # Slice that same audio into per-call clips for /api/calls and, when
        # configured, for Home Assistant speech-to-text.  Must be started
        # before the receiver so no call is missed.
        start_call_capture(_config, endpoint='%s:%d' % (self._host, self._port))

        # Durable talkgroup metadata.  Opened here rather than at import time
        # because the path comes from the config, and a plain `import
        # websocket_server` (every test, and the CLI entry point) must not create
        # a database as a side effect.
        global talkgroup_store
        if talkgroup_store is None:
            talkgroup_store = TalkgroupStore(_metadata_db_path(_config))

        global _audio_receiver
        if _audio_receiver is None:
            endpoints = _discover_audio_endpoints(_config)
            _init_port_managers(endpoints)   # per-channel streams for /api/stream?channel=
            _audio_receiver = UdpAudioReceiver(
                [(ep['host'], ep['port']) for ep in endpoints])
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
        stop_call_capture()
        # Last chance to persist: up to FLUSH_INTERVAL of last-heard history is
        # still only in memory at this point.
        global talkgroup_store
        if talkgroup_store is not None:
            talkgroup_store.close()
            talkgroup_store = None

    # ------------------------------------------------------------------
    # Thread body
    # ------------------------------------------------------------------

    def run(self) -> None:
        last_update = 0.0
        while self.keep_running:
            now = time.time()
            if now - last_update >= self.UPDATE_INTERVAL:
                self._send_cmd('update')
                # Ride the same 1 Hz tick for the health payload so `status`
                # goes stale on its own when the decoder stops answering.
                _broadcast_from_thread(MSG_SYSTEM_STATE, _system_state_payload())
                self._reap_idle_plots(now)
                if talkgroup_store is not None:
                    talkgroup_store.flush()   # no-op until FLUSH_INTERVAL elapses
                last_update = now
            if not self.input_q.empty_p():
                msg = self.input_q.delete_head_nowait()
                if msg is not None:
                    # Never let one malformed message kill the bridge — the
                    # heartbeat above is the only thing driving decoder updates.
                    try:
                        self._dispatch(msg)
                    except Exception:
                        sys.stderr.write('ws_terminal: dispatch error:\n%s\n' % traceback.format_exc())
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

    def _reap_idle_plots(self, now: float) -> None:
        """Turn the decoder's signal plots off while no client is attached.

        Plots are the only thing the decoder computes solely for the browser, and
        the decoder owns their on/off state so it survives a page reload — which
        also means an enabled plot outlives the tab that enabled it.  multi_rx's
        own 'watchdog' cannot catch this: it keys off 'update' going quiet, and
        the heartbeat above keeps sending those forever so the call-log ring
        keeps filling for the next client.
        """
        if manager.client_count() > 0:
            self._idle_since = None
            return
        if self._idle_since is None:
            self._idle_since = now
        elif self._idle_since >= 0 and now - self._idle_since >= self.PLOT_IDLE_GRACE:
            self._idle_since = -1.0     # sent; don't repeat until a client returns
            self._send_cmd('close_plots', 0.0, -1.0)   # arg2 < 0 == every channel

    def _dispatch(self, msg: Any) -> None:
        """Broadcast decoder message(s) to all WebSocket clients.

        multi_rx.py enqueues a JSON *list* of dicts — a single 'update'
        command yields trunk_update, channel_update and call_log entries in
        one message — so normalize to a list and route each entry on its own
        json_type.
        """
        if msg.type() != -4:
            return
        try:
            data: Any = json.loads(msg.to_string())
        except Exception:
            return

        global _last_decoder_msg_at
        _last_decoder_msg_at = time.time()   # drives SYSTEM_STATE.status

        for entry in (data if isinstance(data, list) else [data]):
            if not isinstance(entry, dict):
                continue
            entry.pop('uuid', None)  # internal request-correlation tag; not part of the client protocol
            if not entry:
                continue  # e.g. ui_calllog_update() returns {} when there is nothing new
            json_type = entry.get('json_type', '')
            if json_type == 'channel_update':
                # Keep the newest talkgroup/source per channel so captured
                # call clips can be tagged with what was on the air.
                _note_channel_state(entry)
            elif json_type == 'trunk_update':
                # Merges last_seen/last_freq/count from previous runs into the
                # payload before it is broadcast, so the UI's last-heard column
                # survives a decoder restart.
                _note_trunk_update(entry)
            elif json_type == 'call_log':
                _note_call_log(entry)
            elif json_type == 'full_config':
                # get_full_config hands the decoder's whole config file to the
                # browser. Same exposure as /api/config, same treatment.
                entry = redact_config(entry)
            ws_type = _JSON_TYPE_TO_MSG.get(json_type, MSG_SYSTEM_STATE)
            _broadcast_from_thread(ws_type, entry)

    def _register_upstream_handlers(self) -> None:
        """Wire upstream WebSocket messages to decoder commands."""
        output_q = self.output_q  # capture for closures

        async def handle_call_control(websocket: WebSocket, payload: dict[str, Any]) -> None:
            """Forward a decoder UI command.

            A gr.message carries a string plus two floats, so most commands go as
            the bare command name with their argument in arg1.  Commands whose
            argument does not fit in a float -- a batch scan list, say -- are sent
            as the whole JSON payload instead; multi_rx.process_qmsg tries
            json.loads() first and falls back to the bare-string form, so both
            shapes have always been accepted.
            """
            try:
                if _gr is None:
                    return
                command = str(payload.get('command', ''))
                if not command:
                    return
                arg1 = float(payload.get('arg1', 0.0))
                arg2 = float(payload.get('arg2', 0.0))
                extra = set(payload) - {'command', 'arg1', 'arg2'}
                body = json.dumps(payload) if extra else command
                m = _gr.message().make_from_string(body, -2, arg1, arg2)
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


def op25_terminal(
    input_q: Any,
    output_q: Any,
    terminal_type: str,
    config: dict[str, Any] | None = None,
) -> ws_terminal:
    """Factory matching the terminal.py ``op25_terminal`` interface.

    ``terminal_type`` should be ``"ws:<host>:<port>"``, e.g.
    ``"ws:0.0.0.0:8080"``.  The ``"ws:"`` prefix is stripped before the
    endpoint is passed to :class:`ws_terminal`.

    ``config`` is the fully parsed config dict from multi_rx.py.  It must be
    installed before :class:`ws_terminal` is constructed, because that is what
    binds the UDP audio ports derived from it.
    """
    global _config
    if config is not None:
        _config = config
        _init_config_store()
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
            _init_config_store()
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
