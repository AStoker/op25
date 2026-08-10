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
import math
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
from collections.abc import Iterable, Sequence
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


def _samples(pcm: bytes) -> array.array:
    """*pcm* as a native-order signed-16 array."""
    a = array.array('h')
    a.frombytes(pcm[:len(pcm) - (len(pcm) % SAMPLE_WIDTH)])
    if sys.byteorder != 'little':
        a.byteswap()
    return a


def peak_amplitude(pcm: bytes) -> int:
    """Largest absolute sample value in *pcm* (0 for empty/odd input)."""
    a = _samples(pcm)
    return max(max(a), -min(a)) if a else 0


def mix_pcm16(chunks: Sequence[bytes]) -> bytes:
    """Sum several 16-bit mono LE PCM buffers into one of the longest length.

    This is what makes a multi-channel aggregate stream listenable.  Appending
    the channels instead splices 20 ms fragments of separate conversations into
    one serial stream — and delivers them at N times real time, so the consumer
    falls behind and starts dropping.  Summing keeps one 20 ms slot of wall
    clock carrying one 20 ms slot of audio.

    Samples are summed and then clamped, not averaged: with a single channel
    active — the overwhelmingly common case even on a multi-SDR setup, since
    the decoder only emits while a call is up — the output is bit-identical to
    that channel's own bytes.  Dividing by the channel count would instead make
    ordinary single-channel traffic quieter as SDRs are added.  Clamping can
    distort only while several channels are simultaneously loud.
    """
    real = [c for c in chunks if c]
    if not real:
        return b''
    if len(real) == 1:
        return real[0]

    longest = max(len(c) for c in real)
    acc = [0] * (longest // SAMPLE_WIDTH)
    for c in real:
        for i, v in enumerate(_samples(c)):
            acc[i] += v

    out = array.array('h', [-32768 if v < -32768 else 32767 if v > 32767 else v
                            for v in acc])
    if sys.byteorder != 'little':
        out.byteswap()
    return out.tobytes()


def speech_rms(pcm: bytes, sample_rate: int = 8_000, frame_ms: int = 20) -> float:
    """RMS over the louder half of the clip's frames.

    Plain whole-clip RMS is dragged down by the pauses between phrases, so a
    clip with a lot of dead air would be amplified far more than one without.
    Averaging only the louder half tracks how loud the *speech* is.
    """
    a = _samples(pcm)
    if not a:
        return 0.0
    n = max(1, sample_rate * frame_ms // 1_000)
    frames = [
        math.sqrt(sum(float(v) * v for v in a[i:i + n]) / min(n, len(a) - i))
        for i in range(0, len(a) - n + 1, n)
    ]
    if not frames:
        return math.sqrt(sum(float(v) * v for v in a) / len(a))
    frames.sort()
    loud = frames[len(frames) // 2:]
    return sum(loud) / len(loud)


def normalize_pcm16(
    pcm: bytes,
    sample_rate: int = 8_000,
    target_rms: float = 3_000.0,
    max_gain_db: float = 24.0,
    peak_ceiling: int = 29_000,
) -> tuple[bytes, float]:
    """Bring *pcm* to a consistent loudness.  Returns ``(pcm, gain_db)``.

    Measured across live clips, the decoder's output spans roughly 28 dB of
    RMS between talkgroups — some transmissions arrive pinned at full scale
    while others sit 20 dB down.  Speech models are not scale-invariant in
    practice, so evening this out before transcription is worth more than any
    amount of resampling.

    Gain targets *speech* RMS but is then clamped so the peak cannot exceed
    ``peak_ceiling``; that ordering means a clip with one loud transient is
    attenuated rather than clipped.  ``max_gain_db`` stops a nearly-silent
    clip being amplified into pure noise.
    """
    a = _samples(pcm)
    if not a:
        return pcm, 0.0

    rms = speech_rms(pcm, sample_rate)
    if rms <= 0.0:
        return pcm, 0.0

    gain = target_rms / rms
    gain = min(gain, 10 ** (max_gain_db / 20.0))
    peak = max(max(a), -min(a))
    if peak > 0:
        gain = min(gain, peak_ceiling / float(peak))
    if abs(gain - 1.0) < 0.02:
        return pcm, 0.0

    out = array.array('h', bytes(len(a) * SAMPLE_WIDTH))
    for i, v in enumerate(a):
        s = int(v * gain)
        out[i] = -32_768 if s < -32_768 else (32_767 if s > 32_767 else s)
    if sys.byteorder != 'little':
        out.byteswap()
    return out.tobytes(), 20.0 * math.log10(gain)


def voiced_ratio(pcm: bytes, sample_rate: int = 8_000) -> float:
    """Fraction of frames showing clear pitch periodicity, 0.0–1.0.

    A rough speech-likeness score.  Real voice is strongly periodic in the
    50–400 Hz pitch range; a vocoder fed corrupted parameters produces buzz
    or noise that is not.  The signal is decimated 4:1 first so the
    autocorrelation stays cheap enough to run on a Pi in pure Python.

    This is a heuristic, not a decode-quality measurement — OP25 does not
    surface a bit error rate to Python.  Treat it as advisory.
    """
    a = _samples(pcm)
    if len(a) < sample_rate // 10:
        return 0.0

    dec_rate = sample_rate // 4
    dec = a[::4]
    frame = max(8, dec_rate // 25)                      # 40 ms
    lo_lag = max(2, dec_rate // 400)                    # 400 Hz
    hi_lag = min(frame - 1, dec_rate // 50)             # 50 Hz
    if hi_lag <= lo_lag:
        return 0.0

    voiced = total = 0
    for i in range(0, len(dec) - frame + 1, frame):
        f = dec[i:i + frame]
        energy = sum(float(v) * v for v in f)
        if energy <= 0:
            continue
        total += 1
        best = 0.0
        for lag in range(lo_lag, hi_lag):
            c = sum(float(f[j]) * f[j + lag] for j in range(frame - lag))
            norm = c / energy
            if norm > best:
                best = norm
        if best > 0.35:
            voiced += 1
    return voiced / total if total else 0.0


# ---------------------------------------------------------------------------
# Transcript sanity
# ---------------------------------------------------------------------------

# Whisper's failure mode on unintelligible input is not silence — it emits
# fluent, confident text learned from its training corpus.  These are the
# stock phrases it falls back to, and a keyword alert fired from one of them
# is worse than no alert at all.
_HALLUCINATION_PHRASES = (
    'thank you for watching', 'thanks for watching', 'please subscribe',
    'subscribe to my channel', 'like and subscribe', 'see you next time',
    'thank you very much', "i'll see you next time", 'bye bye',
    'transcription by', 'subtitles by', 'amara.org', 'www.',
)

# Bracketed sound tags: [Music], (upbeat music), ♪ … ♪
_SOUND_TAG_RE = re.compile(r'^\s*[\[\(♪][^\]\)♪]*[\]\)♪]\s*$')
_WORD_RE = re.compile(r"[\w']+")


def is_probable_hallucination(text: str, extra_phrases: tuple[str, ...] = ()) -> bool:
    """True when *text* looks like a speech model's output for noise.

    Three signatures: the stock filler phrases above, a bare sound tag, and
    pathological repetition (Whisper loops on a phrase when the audio carries
    no new information).
    """
    stripped = text.strip()
    if not stripped:
        return False

    lowered = stripped.lower()
    for phrase in _HALLUCINATION_PHRASES + tuple(p.lower() for p in extra_phrases):
        if phrase in lowered:
            return True

    if _SOUND_TAG_RE.match(stripped):
        return True

    words = _WORD_RE.findall(lowered)
    if len(words) >= 6:
        # One token making up most of the output, or a short phrase looped.
        counts: dict[str, int] = {}
        for w in words:
            counts[w] = counts.get(w, 0) + 1
        if max(counts.values()) / len(words) > 0.6:
            return True
        for size in (2, 3, 4):
            if len(words) >= size * 3:
                first = tuple(words[:size])
                reps = sum(1 for i in range(0, len(words) - size + 1, size)
                           if tuple(words[i:i + size]) == first)
                if reps * size / len(words) > 0.8:
                    return True
    return False


# ---------------------------------------------------------------------------
# Call clips
# ---------------------------------------------------------------------------

class CallClip:
    """One captured transmission: audio plus whatever metadata was live."""

    __slots__ = ('id', 'started', 'ended', 'pcm', 'sample_rate', 'metadata',
                 'transcript', 'keywords', 'stt_error', 'discarded_transcript',
                 'transcript_pending', 'media_path')

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
        # Text the model produced that was rejected as a hallucination. Kept
        # visible for tuning, but never matched against keywords.
        self.discarded_transcript: str = ''
        # True between the moment the bridge accepts this clip for
        # transcription and the moment speech-to-text returns (successfully or
        # not). It is what lets the UI say "awaiting transcript" rather than
        # "no transcript" — two states that look identical on the wire
        # otherwise, because both carry an empty ``transcript``.
        self.transcript_pending: bool = False
        # Where Home Assistant is serving this clip once it has been pushed
        # there, e.g. /media/local/scanner/2026-08-05_161735_ffa24f.wav.
        # Empty when media_upload is off or the upload failed.
        self.media_path: str = ''

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
        if self.discarded_transcript:
            d['discarded_transcript'] = self.discarded_transcript
        if self.transcript_pending:
            d['transcript_pending'] = True
        if self.media_path:
            d['media_path'] = self.media_path
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
        normalize: bool = True,
        target_rms: float = 3_000.0,
        max_gain_db: float = 24.0,
        min_voiced_ratio: float = 0.0,
        metadata_fn: Callable[[], dict[str, Any]] | None = None,
        on_complete: Callable[[CallClip], None] | None = None,
    ) -> None:
        self.store          = store
        self.sample_rate    = sample_rate
        self.hang_time      = hang_time_secs
        self.min_call_secs  = min_call_secs
        self.max_call_secs  = max_call_secs
        self.min_peak       = min_peak
        self.normalize      = normalize
        self.target_rms     = target_rms
        self.max_gain_db    = max_gain_db
        self.min_voiced_ratio = min_voiced_ratio
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
        last_push = self._last_push
        self._buf = bytearray()
        self._meta = {}
        self._started = 0.0

        duration = len(pcm) / float(self.sample_rate * SAMPLE_WIDTH)
        if duration < self.min_call_secs:
            self.calls_dropped += 1
            return None

        peak = peak_amplitude(pcm)
        if peak < self.min_peak:
            # All-but-silent: encrypted traffic and squelch tails land here.
            self.calls_dropped += 1
            return None

        # Advisory speech-likeness score. Off by default (0.0) because it is a
        # heuristic, not a decode-quality reading — see voiced_ratio().
        voiced = voiced_ratio(pcm, self.sample_rate) if self.min_voiced_ratio > 0.0 else None
        if voiced is not None and voiced < self.min_voiced_ratio:
            self.calls_dropped += 1
            return None

        rms = speech_rms(pcm, self.sample_rate)
        gain_db = 0.0
        if self.normalize:
            pcm, gain_db = normalize_pcm16(
                pcm, self.sample_rate,
                target_rms=self.target_rms, max_gain_db=self.max_gain_db)

        # How much of the transmission actually decoded.
        #
        # A clip is a *concatenation* of the PCM that arrived -- push() extends a
        # buffer and nothing fills gaps -- so a call that lost half its LDUs
        # produces a clip half as long that still sounds continuous. The live
        # stream cannot do that: it is paced at real time, so the same loss is
        # rendered as silence and heard as chop. That difference is why "the
        # recording sounds fine but the live audio is choppy" is a symptom of
        # lost frames rather than of a streaming fault.
        #
        # continuity makes the loss visible: 1.0 means every frame of the
        # transmission arrived, 0.6 means 40% of it never decoded. It is the
        # per-call decode-completeness figure the decoder otherwise does not
        # expose -- unlike symbol_quality, which measures the eye and says
        # nothing about whether a frame survived FEC.
        # Clamped at 1.0, so a producer ahead of real time -- UDP coalescing, or
        # a burst of LDUs decoded back to back -- reads as "nothing lost" rather
        # than as better-than-perfect reception. Only a single-push call, where
        # there is no span to divide by, gets no reading.
        wall = max(0.0, last_push - started)
        if wall > 0.0:
            meta['continuity'] = round(min(1.0, duration / wall), 3)

        # Levels describe the clip as received, before any normalisation, so
        # they stay meaningful as an RF health indicator.
        meta['peak'] = peak
        meta['rms'] = round(rms, 1)
        meta['gain_db'] = round(gain_db, 1)
        if voiced is not None:
            meta['voiced_ratio'] = round(voiced, 3)

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

#: Config keys that must never leave this process. The loaded config is served
#: verbatim by ``/api/config`` and by the decoder's ``get_full_config``, both
#: of which are unauthenticated — so anything secret has to be stripped there.
SECRET_KEYS = ('token',)

#: What a masked secret reads as. Named because it is not only written here: the
#: config editor has to recognise it on the way *back* in, or a read-modify-write
#: from the browser would persist the mask as the token.
REDACTED = '***redacted***'

#: Accepted values of ``terminal.home_assistant.talkgroup_scope``.
TALKGROUP_SCOPES = ('all', 'focused', 'list')


def _read_token_file(path: str) -> str:
    """Read a long-lived access token from *path*, or '' if unreadable.

    Lets the config file name a **path** rather than carry the secret, which
    keeps the config shareable and keeps the token out of ``/api/config``.
    A missing file is not an error: the environment variable is the next
    fallback, and ``describe()`` already reports whether STT ended up
    configured.
    """
    if not path:
        return ''
    try:
        with open(os.path.expanduser(path), 'r') as fp:
            return fp.read().strip()
    except OSError as exc:
        sys.stderr.write('ha_bridge: cannot read token_file %s: %s\n' % (path, exc))
        return ''


def redact_config(config: Any) -> Any:
    """Deep-copy *config* with every :data:`SECRET_KEYS` value masked.

    Applied wherever the config is handed to a browser. The key is kept (so
    the read-only config view still shows that a token is configured) but the
    value is replaced.
    """
    if isinstance(config, dict):
        return {k: (REDACTED if k in SECRET_KEYS and v else redact_config(v))
                for k, v in config.items()}
    if isinstance(config, list):
        return [redact_config(v) for v in config]
    return config


class HomeAssistantConfig:
    """Parsed ``terminal.home_assistant`` block.

    The access token may be supplied three ways, in precedence order:
    ``token`` in the config, a ``token_file`` path, then ``$OP25_HA_TOKEN``.
    The latter two keep a long-lived credential out of the config file —
    which matters because the config is served to the browser.
    """

    def __init__(self, raw: dict[str, Any] | None) -> None:
        raw = raw or {}
        self.url         = str(raw.get('url', '') or '').rstrip('/')
        self.token_file  = str(raw.get('token_file', '') or '')
        self.token       = (str(raw.get('token', '') or '')
                            or _read_token_file(self.token_file)
                            or os.environ.get('OP25_HA_TOKEN', ''))
        self.webhook_id  = str(raw.get('webhook_id', '') or '')
        self.stt_engine  = str(raw.get('stt_engine', 'stt.faster_whisper') or '')
        self.language    = str(raw.get('language', 'en-US') or 'en-US')
        self.stt_rate    = int(raw.get('stt_sample_rate', 16_000) or 16_000)
        self.stt_audio   = str(raw.get('stt_audio', 'raw') or 'raw').lower()   # 'raw' | 'wav'

        # Push the clip into Home Assistant's media library rather than leaving
        # it in this process for Home Assistant to come back and fetch. Off by
        # default: it writes a file per call on the Home Assistant host.
        self.media_upload = bool(raw.get('media_upload', False))
        self.media_dir    = str(raw.get('media_dir', 'scanner') or 'scanner').strip('/')
        # media_dirs is keyed 'local' on a default install; the media browser
        # shows it as "My media" and serves it at /media/local/...
        self.media_source = str(raw.get('media_source', 'local') or 'local').strip('/')
        # Where the uploaded clip is *reachable*, which is not always where it
        # was *uploaded to*.  /media/<source>/<dir> is served by a view with
        # requires_auth = True, so a bare link to it 401s outside the
        # frontend's authenticated fetches.  Pointing media_dirs at a folder
        # under <config>/www instead makes the same file reachable at
        # /local/..., which Home Assistant registers as an unauthenticated
        # static path.  Set this to '/local/scanner' in that case.
        self.media_url_base = str(raw.get('media_url_base', '') or '').rstrip('/')
        self.public_url  = str(raw.get('public_url', '') or '').rstrip('/')
        self.timeout     = float(raw.get('timeout_secs', 30.0) or 30.0)

        self.keywords_only = bool(raw.get('keywords_only', False))
        self.filter_hallucinations = bool(raw.get('filter_hallucinations', True))
        self.hallucination_phrases = tuple(
            str(p) for p in (raw.get('hallucination_phrases') or []) if str(p).strip())
        self.talkgroups    = [int(t) for t in (raw.get('talkgroups') or [])
                              if str(t).strip().lstrip('-').isdigit()]

        # Which calls are worth a speech-to-text round trip.
        #
        #   all      every captured call
        #   focused  the talkgroups pinned in the UI -- ui_state.focused_talkgroups,
        #            the same selection the talkgroup table sorts and filters by.
        #            Read live through a callback, so pinning takes effect on the
        #            next call rather than at the next restart.
        #   list     the explicit `talkgroups` list above.
        #
        # The default preserves the behaviour that predates this key: a config
        # that set `talkgroups` and nothing else meant "only these", and silently
        # widening that to everything would start billing a cloud STT engine for
        # the whole system.
        scope = str(raw.get('talkgroup_scope', '') or '').strip().lower()
        if scope not in TALKGROUP_SCOPES:
            scope = 'list' if self.talkgroups else 'all'
        self.talkgroup_scope = scope

        self.enabled = bool(raw.get('enabled', bool(self.url)))
        self.keywords = _compile_keywords(raw.get('keywords') or [])

    @property
    def stt_configured(self) -> bool:
        return bool(self.enabled and self.url and self.token and self.stt_engine)

    @property
    def webhook_configured(self) -> bool:
        return bool(self.enabled and self.url and self.webhook_id)

    @property
    def media_configured(self) -> bool:
        # The upload view is @require_admin, so this needs a token belonging to
        # an administrator — not merely a valid one.
        return bool(self.enabled and self.url and self.token and self.media_upload)

    def describe(self) -> str:
        if not self.enabled:
            return 'home assistant: disabled'
        bits = ['url=%s' % (self.url or '(unset)')]
        bits.append('stt=%s' % (self.stt_engine if self.stt_configured else 'off'))
        bits.append('webhook=%s' % (self.webhook_id if self.webhook_configured else 'off'))
        bits.append('keywords=%d' % len(self.keywords))
        bits.append('media=%s' % ('%s/%s' % (self.media_source, self.media_dir)
                                  if self.media_configured else 'off'))
        bits.append('scope=%s' % self.talkgroup_scope)
        if self.talkgroup_scope == 'list':
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
        focused_talkgroups: Callable[[], Iterable[int]] | None = None,
    ) -> None:
        super().__init__(name='ha-bridge', daemon=True)
        self.cfg           = cfg
        self.on_transcript = on_transcript
        # Supplied by websocket_server, reading ui_state. A callable rather than
        # a list because the pinned selection changes while this runs -- and
        # because ha_bridge stays stdlib-only and knows nothing about ui_state.
        self.focused_talkgroups = focused_talkgroups
        self._q: queue.Queue[CallClip | None] = queue.Queue(maxsize=queue_size)
        self.keep_running  = True

        # Filled in by negotiate(); also reported by /api/ha/status.
        self._caps: dict[str, Any] | None = None

        # Diagnostics
        self.media_uploaded = 0
        self.media_errors   = 0
        self.submitted   = 0
        self.filtered    = 0
        self.dropped     = 0
        self.transcribed = 0
        self.stt_errors  = 0
        self.hallucinations = 0
        self.webhooks    = 0
        self.webhook_errors = 0
        self.alerts      = 0

    # ------------------------------------------------------------------

    def accepts(self, clip: CallClip) -> bool:
        """Would :meth:`submit` take this clip?

        Split out from ``submit`` because the caller broadcasts the clip to
        the UI *before* queueing it, and needs to stamp ``transcript_pending``
        on that first message — the UI cannot retroactively learn that a clip
        it already rendered was going to be transcribed after all.
        """
        if not self.cfg.enabled:
            return False
        wanted = self.wanted_talkgroups()
        if wanted:
            tgid = clip.metadata.get('tgid') or 0
            if int(tgid or 0) not in wanted:
                return False
        return True

    def wanted_talkgroups(self) -> set[int]:
        """The talkgroups transcription is restricted to; empty means no filter.

        Empty is deliberately "everything", matching the whitelist convention
        elsewhere in OP25: an empty *list* would otherwise mean silence, and a
        user who turns on "only pinned talkgroups" and then unpins the last one
        would get no transcripts at all with nothing on screen explaining why.
        Widening is visible in the UI and in /api/ha/status; silence is not.
        """
        if self.cfg.talkgroup_scope == 'focused':
            if self.focused_talkgroups is None:
                return set()
            try:
                return {int(t) for t in self.focused_talkgroups()}
            except Exception:
                # This runs on the audio thread for every finished call. A
                # broken state file must not stop calls being transcribed.
                return set()
        if self.cfg.talkgroup_scope == 'list':
            return set(self.cfg.talkgroups)
        return set()

    def will_transcribe(self, clip: CallClip) -> bool:
        """As :meth:`accepts`, but also requires speech-to-text to be usable.

        A clip can be accepted for the webhook alone (no ``token``/``stt_engine``
        configured), in which case there is no transcript to wait for.
        """
        return self.accepts(clip) and self.cfg.stt_configured

    def submit(self, clip: CallClip) -> None:
        """Queue *clip* for processing.  Never blocks the audio thread."""
        if not self.accepts(clip):
            # Counted so "nothing is being transcribed" has an answer in
            # /api/ha/status other than silence: a rising `filtered` next to a
            # flat `submitted` is the talkgroup scope doing its job.
            if self.cfg.enabled:
                self.filtered += 1
            return
        self.submitted += 1
        while True:
            try:
                self._q.put_nowait(clip)
                return
            except queue.Full:
                try:
                    evicted = self._q.get_nowait()
                except queue.Empty:
                    return
                if evicted is None:      # the stop sentinel — put it back
                    self.stop()
                    return
                self.dropped += 1
                # This clip will never be transcribed, so release the UI from
                # "awaiting transcript" rather than leaving the row hanging.
                self._settle(evicted)

    def stop(self) -> None:
        self.keep_running = False
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass

    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Capability negotiation
    # ------------------------------------------------------------------

    def fetch_stt_capabilities(self) -> dict[str, Any] | None:
        """``GET /api/stt/<engine>`` — what the engine will actually accept.

        Home Assistant answers with the provider's supported ``languages``,
        ``formats``, ``codecs``, ``sample_rates``, ``bit_rates`` and
        ``channels``. Returns None if the engine cannot be reached.
        """
        if not self.cfg.stt_configured:
            return None
        url = '%s/api/stt/%s' % (self.cfg.url, self.cfg.stt_engine)
        req = urllib.request.Request(url, method='GET')
        req.add_header('Authorization', 'Bearer %s' % self.cfg.token)
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
                data = json.loads(resp.read().decode('utf-8', 'replace'))
        except Exception as exc:
            sys.stderr.write('ha_bridge: cannot read %s: %s\n' % (url, exc))
            return None
        return data if isinstance(data, dict) else None

    def negotiate(self) -> None:
        """Reconcile our request format against what the engine supports.

        Home Assistant rejects a mismatch with a bare **HTTP 415**, naming
        neither the offending field nor the acceptable values — so ask first.
        The common trap is the language tag: Home Assistant Cloud advertises
        regional codes like ``en-US``, while the Wyoming/Whisper add-on
        advertises bare ISO-639-1 codes like ``en``, and the same config
        pointed at the other engine then fails with nothing to go on.
        """
        caps = self.fetch_stt_capabilities()
        if not caps:
            return
        self._caps = caps

        langs = [str(x) for x in (caps.get('languages') or [])]
        if langs and self.cfg.language not in langs:
            base = self.cfg.language.split('-')[0].lower()
            match = (next((x for x in langs if x.lower() == base), None)
                     or next((x for x in langs if x.lower().split('-')[0] == base), None))
            if match:
                sys.stderr.write(
                    'ha_bridge: %s does not accept language %r; using %r\n'
                    % (self.cfg.stt_engine, self.cfg.language, match))
                self.cfg.language = match
            else:
                sys.stderr.write(
                    'ha_bridge: %s does not accept language %r and has no %r variant '
                    '(it accepts: %s)\n'
                    % (self.cfg.stt_engine, self.cfg.language, base, ', '.join(langs[:20])))

        rates = [int(x) for x in (caps.get('sample_rates') or []) if str(x).isdigit()]
        if rates and self.cfg.stt_rate not in rates:
            # Prefer the lowest rate at or above ours: the source is 8 kHz, so
            # upsampling further buys nothing and only costs bandwidth.
            pick = min((r for r in rates if r >= self.cfg.stt_rate), default=max(rates))
            sys.stderr.write(
                'ha_bridge: %s does not accept sample_rate %d; using %d\n'
                % (self.cfg.stt_engine, self.cfg.stt_rate, pick))
            self.cfg.stt_rate = pick

        fmts = [str(x).lower() for x in (caps.get('formats') or [])]
        if fmts and 'wav' not in fmts:
            sys.stderr.write(
                'ha_bridge: %s does not accept wav (it accepts: %s) — transcription '
                'will fail\n' % (self.cfg.stt_engine, ', '.join(fmts)))

    def run(self) -> None:
        sys.stderr.write('%s\n' % self.cfg.describe())
        self.negotiate()
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
            clip.stt_error = err
            if err:
                self.stt_errors += 1

            # A speech model handed unintelligible audio does not return
            # nothing — it returns confident boilerplate. Drop that before it
            # can match a keyword and page somebody at 3am.
            if (text and self.cfg.filter_hallucinations
                    and is_probable_hallucination(text, self.cfg.hallucination_phrases)):
                clip.discarded_transcript = text
                self.hallucinations += 1
                text = ''

            clip.transcript = text
            if text:
                self.transcribed += 1

        clip.keywords = match_keywords(clip.transcript, self.cfg.keywords)
        if clip.keywords:
            self.alerts += 1

        self._settle(clip)

        if self.cfg.keywords_only and not clip.keywords:
            return

        # Upload before the webhook, so the payload can name the file that is
        # already there. The other order would have the automation racing an
        # upload it has no way to wait for.
        clip.media_path = self._upload_media(clip)

        if self.cfg.webhook_configured:
            self._post_webhook(clip)

    def _settle(self, clip: CallClip) -> None:
        """Mark *clip* as no longer awaiting transcription and notify the UI.

        Called on every terminal outcome — transcribed, failed, filtered as a
        hallucination, or shed from a full queue — so a row can never be left
        showing "awaiting transcript" forever.
        """
        clip.transcript_pending = False
        if self.on_transcript is not None:
            try:
                self.on_transcript(clip)
            except Exception:
                pass

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
            if exc.code == 415:
                # HA returns a bare "Unsupported Media Type" with no indication
                # of which of the six declared fields it disliked, so say what
                # we sent and what the engine advertises.
                return '', ('HTTP 415 from %s — the engine rejected our audio '
                            'declaration. %s' % (url, self._describe_mismatch()))
            return '', 'HTTP %s from %s: %s' % (exc.code, url, detail)
        except Exception as exc:
            return '', '%s: %s' % (type(exc).__name__, exc)

        if str(data.get('result', '')).lower() != 'success':
            return '', 'stt result=%s' % data.get('result')
        return str(data.get('text', '') or '').strip(), ''

    #: ``<date>_<time>_<tgid>_<talkgroup-slug>_<clip id>.wav``
    #:
    #: The filename is the only metadata that travels with the audio. Home
    #: Assistant's media library stores bare files with no sidecar and no
    #: database, so anything a dashboard wants to filter on — which talkgroup,
    #: when — has to be recoverable from the name itself.
    #:
    #: Constraints that shape the format:
    #:   * ``raise_if_invalid_filename`` rejects path separators outright.
    #:   * The name ends up in a URL, so it stays within [A-Za-z0-9._-].
    #:   * The slug is stripped of underscores so ``split('_')`` yields exactly
    #:     five fields regardless of what the talkgroup tag contains.
    #:   * Leading date-time keeps a plain lexicographic sort in newest-last
    #:     order, which is what a directory listing gives you for free.
    MEDIA_NAME_FIELDS = 5

    def _media_filename(self, clip: CallClip) -> str:
        stamp = time.strftime('%Y-%m-%d_%H%M%S', time.localtime(clip.started))
        safe_id = re.sub(r'[^A-Za-z0-9]', '', clip.id) or 'clip'
        tgid = clip.metadata.get('tgid') or 0
        try:
            tgid = int(tgid)
        except (TypeError, ValueError):
            tgid = 0
        tag = str(clip.metadata.get('talkgroup') or '')
        slug = re.sub(r'-{2,}', '-', re.sub(r'[^A-Za-z0-9]+', '-', tag)).strip('-')[:40]
        return '%s_%d_%s_%s.wav' % (stamp, tgid, slug or 'unknown', safe_id)

    def _upload_media(self, clip: CallClip) -> str:
        """Push the clip into Home Assistant's media library.

        Returns the path Home Assistant will serve it at
        (``/media/local/<dir>/<file>.wav``), or '' if the upload did not
        happen.

        This is a *push*: Home Assistant never connects back here, so nothing
        depends on this host being reachable, on ``public_url`` being right, or
        on the clip still being in the in-memory ring by the time somebody
        clicks a link. The bytes land on the Home Assistant host and are its
        problem from then on.

        The endpoint is ``@require_admin``, caps uploads at 20 MB, insists the
        content type be image/video/audio, and creates the target folder
        itself.
        """
        if not self.cfg.media_configured:
            return ''

        filename = self._media_filename(clip)

        # A real RIFF container, not the headerless PCM the STT endpoint takes:
        # this one has to be playable by a browser and a phone.
        audio = wav_bytes(clip.pcm, clip.sample_rate)
        content_id = 'media-source://media_source/%s/%s' % (
            self.cfg.media_source, self.cfg.media_dir)

        boundary = '----op25%s' % os.urandom(16).hex()
        pre = (
            '--%s\r\n'
            'Content-Disposition: form-data; name="media_content_id"\r\n\r\n'
            '%s\r\n'
            '--%s\r\n'
            'Content-Disposition: form-data; name="file"; filename="%s"\r\n'
            'Content-Type: audio/wav\r\n\r\n' % (
                boundary, content_id, boundary, filename)
        ).encode('utf-8')
        post = ('\r\n--%s--\r\n' % boundary).encode('utf-8')

        url = '%s/api/media_source/local_source/upload' % self.cfg.url
        req = urllib.request.Request(url, data=pre + audio + post, method='POST')
        req.add_header('Authorization', 'Bearer %s' % self.cfg.token)
        req.add_header('Content-Type', 'multipart/form-data; boundary=%s' % boundary)

        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', 'replace')[:200] if exc.fp else ''
            hint = ''
            if exc.code in (401, 403):
                hint = (' — the upload endpoint requires an *administrator* '
                        'token, not merely a valid one')
            sys.stderr.write('ha_bridge: media upload failed: HTTP %s%s %s\n'
                             % (exc.code, hint, detail))
            self.media_errors += 1
            return ''
        except Exception as exc:
            sys.stderr.write('ha_bridge: media upload failed: %s: %s\n'
                             % (type(exc).__name__, exc))
            self.media_errors += 1
            return ''

        self.media_uploaded += 1
        base = self.cfg.media_url_base or '/media/%s/%s' % (
            self.cfg.media_source, self.cfg.media_dir)
        return '%s/%s' % (base.rstrip('/'), filename)

    def _describe_mismatch(self) -> str:
        """Name the field an HTTP 415 is most likely complaining about."""
        sent = 'sent language=%s sample_rate=%d bit_rate=%d channel=%d format=wav codec=pcm' % (
            self.cfg.language, self.cfg.stt_rate, SAMPLE_WIDTH * 8, CHANNELS)
        caps = self._caps or self.fetch_stt_capabilities()
        if not caps:
            self._caps = None
            return sent + '; could not read the engine capabilities to compare.'
        self._caps = caps

        bad = []
        langs = [str(x) for x in (caps.get('languages') or [])]
        if langs and self.cfg.language not in langs:
            bad.append('language %r is not in the engine list (try %s)'
                       % (self.cfg.language, ', '.join(langs[:8])))
        rates = [int(x) for x in (caps.get('sample_rates') or []) if str(x).isdigit()]
        if rates and self.cfg.stt_rate not in rates:
            bad.append('sample_rate %d not in %s' % (self.cfg.stt_rate, rates))
        fmts = [str(x).lower() for x in (caps.get('formats') or [])]
        if fmts and 'wav' not in fmts:
            bad.append('format wav not in %s' % fmts)
        codecs = [str(x).lower() for x in (caps.get('codecs') or [])]
        if codecs and 'pcm' not in codecs:
            bad.append('codec pcm not in %s' % codecs)

        return sent + ('; ' + '; '.join(bad) if bad else
                       '; the engine advertises all of those as supported.')

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
            'filtered':       self.filtered,
            'dropped':        self.dropped,
            'transcribed':    self.transcribed,
            'stt_errors':     self.stt_errors,
            'hallucinations': self.hallucinations,
            'webhooks':       self.webhooks,
            'webhook_errors': self.webhook_errors,
            'alerts':         self.alerts,
            'media_uploaded': self.media_uploaded,
            'media_errors':   self.media_errors,
        }
