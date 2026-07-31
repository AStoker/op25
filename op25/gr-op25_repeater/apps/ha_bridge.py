# Copyright 2026 OP25 Contributors
#
# This file is part of OP25
#
# OP25 is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.

"""Per-call audio capture, speech-to-text, and Home Assistant notification.

The decoder emits PCM over UDP only while a call is actually up, so the
absence of packets is a perfectly good voice-activity detector: a "call"
is a run of UDP audio with no gap longer than ``hang_time_secs``.  That
gives us finite, speech-only clips, which is exactly what a speech-to-text
engine wants — far better than feeding it a continuous stream that is 95 %
digital silence.

Pipeline
--------

    UdpAudioReceiver ──push()──> CallRecorder ──> CallClip ──> ClipStore
                                                     │
                                                     ├─> HomeAssistantBridge
                                                     │      ├─ POST clip to HA's /api/stt/<engine>
                                                     │      ├─ match keywords against the transcript
                                                     │      └─ POST metadata + transcript to a HA webhook
                                                     │
                                                     └─> WebSocket broadcast (UI transcript feed)

Everything here uses only the standard library (``urllib.request`` for
HTTP), so nothing new has to be installed on a Raspberry Pi.

Configuration lives under ``terminal.home_assistant`` in the multi_rx JSON
config; see ``README-home-assistant.md`` for the full reference.
"""

from __future__ import annotations

import array
import json
import os
import queue
import re
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from typing import Any, Callable

# ---------------------------------------------------------------------------
# PCM helpers
# ---------------------------------------------------------------------------

SAMPLE_WIDTH = 2   # bytes — 16-bit signed LE
CHANNELS     = 1   # mono


def resample_pcm16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Linearly resample 16-bit mono LE PCM from *src_rate* to *dst_rate*.

    Linear interpolation is more than good enough here: the source is
    8 kHz vocoded speech whose usable bandwidth tops out around 3.4 kHz,
    so upsampling adds no information either way — it only satisfies
    consumers (Home Assistant's STT API, Whisper) that insist on 16 kHz.
    """
    if src_rate == dst_rate or not pcm:
        return pcm

    src = array.array('h')
    src.frombytes(pcm[:len(pcm) - (len(pcm) % SAMPLE_WIDTH)])
    if sys.byteorder != 'little':
        src.byteswap()

    n_in = len(src)
    if n_in < 2:
        return pcm

    n_out = int(n_in * dst_rate / src_rate)
    ratio = src_rate / dst_rate
    out   = array.array('h', bytes(n_out * SAMPLE_WIDTH))

    for j in range(n_out):
        p = j * ratio
        i = int(p)
        if i >= n_in - 1:
            out[j] = src[n_in - 1]
            continue
        frac = p - i
        out[j] = int(src[i] * (1.0 - frac) + src[i + 1] * frac)

    if sys.byteorder != 'little':
        out.byteswap()
    return out.tobytes()


def wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap *pcm* in a complete (finite, correctly sized) WAV container."""
    byte_rate   = sample_rate * CHANNELS * SAMPLE_WIDTH
    block_align = CHANNELS * SAMPLE_WIDTH
    hdr  = struct.pack('<4sI4s', b'RIFF', 36 + len(pcm), b'WAVE')
    hdr += struct.pack('<4sIHHIIHH', b'fmt ', 16, 1, CHANNELS,
                       sample_rate, byte_rate, block_align, SAMPLE_WIDTH * 8)
    hdr += struct.pack('<4sI', b'data', len(pcm))
    return hdr + pcm


def peak_amplitude(pcm: bytes) -> int:
    """Largest absolute sample value in *pcm* (0 for empty/odd input)."""
    a = array.array('h')
    a.frombytes(pcm[:len(pcm) - (len(pcm) % SAMPLE_WIDTH)])
    if not a:
        return 0
    if sys.byteorder != 'little':
        a.byteswap()
    return max(max(a), -min(a))


# ---------------------------------------------------------------------------
# Call clips
# ---------------------------------------------------------------------------

class CallClip:
    """One captured transmission: audio plus whatever metadata was live."""

    __slots__ = ('id', 'started', 'ended', 'pcm', 'sample_rate', 'metadata',
                 'transcript', 'keywords', 'stt_error')

    def __init__(self, clip_id: str, started: float, ended: float,
                 pcm: bytes, sample_rate: int, metadata: dict[str, Any]) -> None:
        self.id          = clip_id
        self.started     = started
        self.ended       = ended
        self.pcm         = pcm
        self.sample_rate = sample_rate
        self.metadata    = metadata
        self.transcript: str        = ''
        self.keywords:   list[str]  = []
        self.stt_error:  str        = ''

    @property
    def duration(self) -> float:
        return len(self.pcm) / float(self.sample_rate * SAMPLE_WIDTH)

    def to_dict(self, audio_url_base: str = '/api/calls') -> dict[str, Any]:
        """JSON-serialisable summary (no audio) for the REST API / WebSocket."""
        d: dict[str, Any] = {
            'id':         self.id,
            'started':    round(self.started, 3),
            'ended':      round(self.ended, 3),
            'duration':   round(self.duration, 3),
            'transcript': self.transcript,
            'keywords':   list(self.keywords),
            'audio_url':  '%s/%s/audio.wav' % (audio_url_base.rstrip('/'), self.id),
        }
        if self.stt_error:
            d['stt_error'] = self.stt_error
        d.update(self.metadata)
        return d


class ClipStore:
    """Bounded, thread-safe ring of recent :class:`CallClip` objects.

    Bounded by *both* clip count and total audio bytes so a busy system
    cannot grow the process without limit.  At 8 kHz/16-bit the default
    24 MB ceiling is about 25 minutes of captured voice.
    """

    def __init__(self, max_clips: int = 60, max_bytes: int = 24 * 1024 * 1024) -> None:
        self._clips: deque[CallClip] = deque()
        self._by_id: dict[str, CallClip] = {}
        self._lock = threading.Lock()
        self._bytes = 0
        self.max_clips = max_clips
        self.max_bytes = max_bytes

    def add(self, clip: CallClip) -> None:
        with self._lock:
            self._clips.append(clip)
            self._by_id[clip.id] = clip
            self._bytes += len(clip.pcm)
            while self._clips and (len(self._clips) > self.max_clips
                                   or self._bytes > self.max_bytes):
                old = self._clips.popleft()
                self._by_id.pop(old.id, None)
                self._bytes -= len(old.pcm)

    def get(self, clip_id: str) -> CallClip | None:
        with self._lock:
            return self._by_id.get(clip_id)

    def recent(self, limit: int = 50) -> list[CallClip]:
        """Most-recent-first list of up to *limit* clips."""
        with self._lock:
            return list(self._clips)[-limit:][::-1]

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {'clips': len(self._clips), 'bytes': self._bytes}


# ---------------------------------------------------------------------------
# Call recorder (voice-activity segmentation)
# ---------------------------------------------------------------------------

class CallRecorder:
    """Slice the continuous UDP PCM feed into per-call clips.

    :meth:`push` is called from the UDP receiver thread for every PCM
    packet.  :meth:`poll` must be called periodically (the receiver's
    ``select`` loop already wakes at least once a second) so a call can be
    closed out once the audio stops.
    """

    def __init__(
        self,
        store: ClipStore,
        sample_rate: int = 8_000,
        hang_time_secs: float = 1.5,
        min_call_secs: float = 0.8,
        max_call_secs: float = 120.0,
        min_peak: int = 250,
        metadata_fn: Callable[[], dict[str, Any]] | None = None,
        on_complete: Callable[[CallClip], None] | None = None,
    ) -> None:
        self.store          = store
        self.sample_rate    = sample_rate
        self.hang_time      = hang_time_secs
        self.min_call_secs  = min_call_secs
        self.max_call_secs  = max_call_secs
        self.min_peak       = min_peak
        self.metadata_fn    = metadata_fn
        self.on_complete    = on_complete

        self._lock       = threading.Lock()
        self._buf        = bytearray()
        self._started    = 0.0
        self._last_push  = 0.0
        self._meta: dict[str, Any] = {}

        # Diagnostics
        self.calls_captured = 0
        self.calls_dropped  = 0

    # ------------------------------------------------------------------

    def push(self, pcm: bytes) -> None:
        """Append decoder PCM.  Starts a new call if none is in progress."""
        if not pcm:
            return
        now = time.time()
        finished: CallClip | None = None
        with self._lock:
            if not self._buf:
                self._started = now
                self._meta    = self._snapshot_metadata()
            self._buf.extend(pcm)
            self._last_push = now
            # Refresh metadata while the call runs — channel_update arrives at
            # 1 Hz, so a short call may start before its tgid is known.
            self._merge_metadata()
            if self._duration_locked() >= self.max_call_secs:
                finished = self._finalize_locked(now)
        if finished is not None:
            self._emit(finished)

    def poll(self) -> None:
        """Close out the active call once the audio has stopped."""
        now = time.time()
        finished: CallClip | None = None
        with self._lock:
            if self._buf and (now - self._last_push) >= self.hang_time:
                finished = self._finalize_locked(self._last_push)
        if finished is not None:
            self._emit(finished)

    def flush(self) -> None:
        """Force-close any in-progress call (used on shutdown)."""
        finished: CallClip | None = None
        with self._lock:
            if self._buf:
                finished = self._finalize_locked(self._last_push)
        if finished is not None:
            self._emit(finished)

    # ------------------------------------------------------------------
    # Internals (call with self._lock held)
    # ------------------------------------------------------------------

    def _duration_locked(self) -> float:
        return len(self._buf) / float(self.sample_rate * SAMPLE_WIDTH)

    def _snapshot_metadata(self) -> dict[str, Any]:
        if self.metadata_fn is None:
            return {}
        try:
            meta = self.metadata_fn()
        except Exception:
            return {}
        return dict(meta) if isinstance(meta, dict) else {}

    def _merge_metadata(self) -> None:
        """Fill in fields the snapshot at call start did not yet know.

        Never overwrites a value that is already set: the first talkgroup
        seen for a transmission is the correct one, and a late update may
        already describe the *next* call.
        """
        fresh = self._snapshot_metadata()
        for k, v in fresh.items():
            if v in (None, '', 0) :
                continue
            if self._meta.get(k) in (None, '', 0):
                self._meta[k] = v

    def _finalize_locked(self, ended: float) -> CallClip | None:
        pcm  = bytes(self._buf)
        meta = dict(self._meta)
        started = self._started
        self._buf = bytearray()
        self._meta = {}
        self._started = 0.0

        duration = len(pcm) / float(self.sample_rate * SAMPLE_WIDTH)
        if duration < self.min_call_secs:
            self.calls_dropped += 1
            return None
        if peak_amplitude(pcm) < self.min_peak:
            # All-but-silent: encrypted traffic and squelch tails land here.
            self.calls_dropped += 1
            return None

        self.calls_captured += 1
        return CallClip(uuid.uuid4().hex[:12], started, ended, pcm,
                        self.sample_rate, meta)

    def _emit(self, clip: CallClip) -> None:
        self.store.add(clip)
        if self.on_complete is not None:
            try:
                self.on_complete(clip)
            except Exception:
                sys.stderr.write('ha_bridge: on_complete failed for clip %s\n' % clip.id)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class HomeAssistantConfig:
    """Parsed ``terminal.home_assistant`` block.

    The access token may be supplied out-of-band via ``$OP25_HA_TOKEN`` so
    a long-lived credential need not live in the config file.
    """

    def __init__(self, raw: dict[str, Any] | None) -> None:
        raw = raw or {}
        self.url         = str(raw.get('url', '') or '').rstrip('/')
        self.token       = str(raw.get('token', '') or '') or os.environ.get('OP25_HA_TOKEN', '')
        self.webhook_id  = str(raw.get('webhook_id', '') or '')
        self.stt_engine  = str(raw.get('stt_engine', 'stt.faster_whisper') or '')
        self.language    = str(raw.get('language', 'en-US') or 'en-US')
        self.stt_rate    = int(raw.get('stt_sample_rate', 16_000) or 16_000)
        self.stt_audio   = str(raw.get('stt_audio', 'raw') or 'raw').lower()   # 'raw' | 'wav'
        self.public_url  = str(raw.get('public_url', '') or '').rstrip('/')
        self.timeout     = float(raw.get('timeout_secs', 30.0) or 30.0)

        self.keywords_only = bool(raw.get('keywords_only', False))
        self.talkgroups    = [int(t) for t in (raw.get('talkgroups') or [])
                              if str(t).strip().lstrip('-').isdigit()]

        self.enabled = bool(raw.get('enabled', bool(self.url)))
        self.keywords = _compile_keywords(raw.get('keywords') or [])

    @property
    def stt_configured(self) -> bool:
        return bool(self.enabled and self.url and self.token and self.stt_engine)

    @property
    def webhook_configured(self) -> bool:
        return bool(self.enabled and self.url and self.webhook_id)

    def describe(self) -> str:
        if not self.enabled:
            return 'home assistant: disabled'
        bits = ['url=%s' % (self.url or '(unset)')]
        bits.append('stt=%s' % (self.stt_engine if self.stt_configured else 'off'))
        bits.append('webhook=%s' % (self.webhook_id if self.webhook_configured else 'off'))
        bits.append('keywords=%d' % len(self.keywords))
        if self.talkgroups:
            bits.append('talkgroups=%d' % len(self.talkgroups))
        return 'home assistant: ' + ' '.join(bits)


def _compile_keywords(words: Any) -> list[tuple[str, Any]]:
    """Compile keyword strings into ``(original, regex)`` pairs.

    Word-boundary anchored when the term is plain words, so "fire" does
    not fire on "firehouse"; anything containing punctuation or digits
    with symbols falls back to a plain substring match.
    """
    out: list[tuple[str, Any]] = []
    for w in (words if isinstance(words, (list, tuple)) else [words]):
        term = str(w).strip()
        if not term:
            continue
        if re.fullmatch(r"[\w\s'-]+", term):
            pat = re.compile(r'\b' + re.escape(term) + r'\b', re.IGNORECASE)
        else:
            pat = re.compile(re.escape(term), re.IGNORECASE)
        out.append((term, pat))
    return out


def match_keywords(text: str, keywords: list[tuple[str, Any]]) -> list[str]:
    """Return the keyword terms present in *text* (original casing preserved)."""
    if not text:
        return []
    return [term for term, pat in keywords if pat.search(text)]


# ---------------------------------------------------------------------------
# Home Assistant bridge
# ---------------------------------------------------------------------------

class HomeAssistantBridge(threading.Thread):
    """Worker thread: transcribe finished calls and notify Home Assistant.

    Clips are handed over via :meth:`submit` from the UDP receiver thread
    and processed serially here, because both the network round-trips and
    the STT engine itself are slow relative to the call rate.  The queue is
    bounded: when Home Assistant (or Whisper) cannot keep up, the *oldest*
    pending clip is dropped so the newest traffic — the traffic a keyword
    alert is most likely to care about — still gets through.
    """

    def __init__(
        self,
        cfg: HomeAssistantConfig,
        on_transcript: Callable[[CallClip], None] | None = None,
        queue_size: int = 16,
    ) -> None:
        super().__init__(name='ha-bridge', daemon=True)
        self.cfg           = cfg
        self.on_transcript = on_transcript
        self._q: queue.Queue[CallClip | None] = queue.Queue(maxsize=queue_size)
        self.keep_running  = True

        # Diagnostics
        self.submitted   = 0
        self.dropped     = 0
        self.transcribed = 0
        self.stt_errors  = 0
        self.webhooks    = 0
        self.webhook_errors = 0
        self.alerts      = 0

    # ------------------------------------------------------------------

    def submit(self, clip: CallClip) -> None:
        """Queue *clip* for processing.  Never blocks the audio thread."""
        if not self.cfg.enabled:
            return
        if self.cfg.talkgroups:
            tgid = clip.metadata.get('tgid') or 0
            if int(tgid or 0) not in self.cfg.talkgroups:
                return
        self.submitted += 1
        while True:
            try:
                self._q.put_nowait(clip)
                return
            except queue.Full:
                try:
                    self._q.get_nowait()
                    self.dropped += 1
                except queue.Empty:
                    return

    def stop(self) -> None:
        self.keep_running = False
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass

    # ------------------------------------------------------------------

    def run(self) -> None:
        sys.stderr.write('%s\n' % self.cfg.describe())
        while self.keep_running:
            try:
                clip = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            if clip is None:
                break
            try:
                self._process(clip)
            except Exception as exc:
                sys.stderr.write('ha_bridge: processing clip %s failed: %s\n' % (clip.id, exc))

    def _process(self, clip: CallClip) -> None:
        if self.cfg.stt_configured:
            text, err = self._transcribe(clip)
            clip.transcript = text
            clip.stt_error  = err
            if text:
                self.transcribed += 1
            if err:
                self.stt_errors += 1

        clip.keywords = match_keywords(clip.transcript, self.cfg.keywords)
        if clip.keywords:
            self.alerts += 1

        if self.on_transcript is not None:
            try:
                self.on_transcript(clip)
            except Exception:
                pass

        if self.cfg.keywords_only and not clip.keywords:
            return
        if self.cfg.webhook_configured:
            self._post_webhook(clip)

    # ------------------------------------------------------------------
    # Home Assistant HTTP
    # ------------------------------------------------------------------

    def _transcribe(self, clip: CallClip) -> tuple[str, str]:
        """POST the clip to Home Assistant's speech-to-text API.

        Home Assistant's ``/api/stt/<engine>`` endpoint only accepts
        16 kHz / 16-bit / mono, and passes the request body straight
        through to the provider as raw PCM chunks — so the clip is
        upsampled here and sent headerless by default.
        """
        pcm = resample_pcm16(clip.pcm, clip.sample_rate, self.cfg.stt_rate)
        body = wav_bytes(pcm, self.cfg.stt_rate) if self.cfg.stt_audio == 'wav' else pcm

        url = '%s/api/stt/%s' % (self.cfg.url, self.cfg.stt_engine)
        req = urllib.request.Request(url, data=body, method='POST')
        req.add_header('Authorization', 'Bearer %s' % self.cfg.token)
        req.add_header('Content-Type', 'application/octet-stream')
        req.add_header(
            'X-Speech-Content',
            'format=wav; codec=pcm; sample_rate=%d; bit_rate=%d; channel=%d; language=%s'
            % (self.cfg.stt_rate, SAMPLE_WIDTH * 8, CHANNELS, self.cfg.language),
        )

        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
                data = json.loads(resp.read().decode('utf-8', 'replace'))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', 'replace')[:200] if exc.fp else ''
            return '', 'HTTP %s from %s: %s' % (exc.code, url, detail)
        except Exception as exc:
            return '', '%s: %s' % (type(exc).__name__, exc)

        if str(data.get('result', '')).lower() != 'success':
            return '', 'stt result=%s' % data.get('result')
        return str(data.get('text', '') or '').strip(), ''

    def _post_webhook(self, clip: CallClip) -> None:
        base = self.cfg.public_url or ''
        payload = clip.to_dict(audio_url_base=(base + '/api/calls') if base else '/api/calls')
        payload['event'] = 'op25_call'

        url = '%s/api/webhook/%s' % (self.cfg.url, self.cfg.webhook_id)
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode('utf-8'), method='POST')
        req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout):
                self.webhooks += 1
        except Exception as exc:
            self.webhook_errors += 1
            sys.stderr.write('ha_bridge: webhook POST failed (%s): %s\n' % (url, exc))

    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        return {
            'submitted':      self.submitted,
            'dropped':        self.dropped,
            'transcribed':    self.transcribed,
            'stt_errors':     self.stt_errors,
            'webhooks':       self.webhooks,
            'webhook_errors': self.webhook_errors,
            'alerts':         self.alerts,
        }
