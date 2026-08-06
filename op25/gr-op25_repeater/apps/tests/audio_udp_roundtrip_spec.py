"""End-to-end audio path: C++ op25_audio -> UDP -> UdpAudioReceiver -> /api/stream.

Every other spec in this directory runs without GNU Radio installed, because
`websocket_server` guards its `from gnuradio import gr` import.  This one does
not: it drives the real compiled `op25_repeater.analog_udp` block, which is the
only way to exercise `op25_audio::send_audio()` from Python.  It self-skips when
the bindings are absent, exactly like `squelch_upstream_spec.py` does.

Why it exists: `op25_audio` used to support a `ws://` transport alongside
`udp://`, and removing it touched `send_audio`, `send_audio_flag`, the
destination parser and `enabled()`.  A mistake in any of those compiles fine,
decodes fine, and is simply silent -- the failure mode a unit test of the Python
half cannot see.  A tone in one end and non-silent PCM out the other is the
check that actually catches it.
"""

from __future__ import annotations

import array
import asyncio
import math
import threading
import time
from typing import Any

import pytest

pytest.importorskip("gnuradio", reason="needs a built+installed GNU Radio OOT module")

gnuradio_blocks = pytest.importorskip("gnuradio.blocks")
op25_repeater = pytest.importorskip("gnuradio.op25_repeater")

from gnuradio import gr  # noqa: E402

import websocket_server as ws  # noqa: E402

TONE_HZ = 440
TONE_AMPLITUDE = 0.5
SAMPLE_RATE = 8000
EXPECTED_PEAK = int(TONE_AMPLITUDE * 32768)   # analog_udp scales float -> S16


def _tone(seconds: float) -> list[float]:
    n = int(SAMPLE_RATE * seconds)
    return [TONE_AMPLITUDE * math.sin(2 * math.pi * TONE_HZ * i / SAMPLE_RATE)
            for i in range(n)]


def _send_tone(port: int, msgq_id: int, seconds: float = 2.0,
               destination: str | None = None) -> None:
    """Run a one-shot flowgraph that pushes PCM at the given UDP port.

    *msgq_id* must be unique per test.  op25_audio_wrapper is a singleton whose
    map is keyed on msgq_id (op25_audio_wrapper.h:69), so reusing an id returns
    the *cached* audio object bound to the earlier destination and silently
    ignores the new one -- the tests then all publish to the first port.
    """
    dest = destination if destination is not None else 'udp://127.0.0.1:%d' % port
    tb = gr.top_block()
    tb.connect(
        gnuradio_blocks.vector_source_f(_tone(seconds), False),
        op25_repeater.analog_udp(dest, 0, msgq_id, gr.msg_queue(10)),
    )
    tb.run()


def _peak_and_voiced(pcm: bytes) -> tuple[int, float]:
    samples = array.array('h')
    samples.frombytes(pcm[:len(pcm) // 2 * 2])
    if not samples:
        return 0, 0.0
    peak = max(abs(v) for v in samples)
    voiced = sum(1 for v in samples if abs(v) > 200) / len(samples)
    return peak, voiced


class TestUdpAudioRoundTrip:
    def test_send_audio_reaches_the_udp_port(self) -> None:
        """op25_audio::send_audio() puts real PCM on the wire."""
        import socket as _socket

        port = 23990
        rx = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        rx.bind(('127.0.0.1', port))
        rx.settimeout(5.0)
        received: list[bytes] = []

        def reader() -> None:
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    received.append(rx.recvfrom(4096)[0])
                except _socket.timeout:
                    break

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        _send_tone(port, msgq_id=90, seconds=1.0)
        t.join(timeout=6)
        rx.close()

        assert received, "no UDP datagrams -- send_audio() is not transmitting"
        peak, voiced = _peak_and_voiced(b''.join(received))
        assert peak == pytest.approx(EXPECTED_PEAK, rel=0.02)
        assert voiced > 0.9

    def test_unsupported_scheme_does_not_prevent_udp(self) -> None:
        """An old config carrying ws:// still gets audio from its udp:// half."""
        import socket as _socket

        port = 23991
        rx = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        rx.bind(('127.0.0.1', port))
        rx.settimeout(5.0)
        received: list[bytes] = []

        def reader() -> None:
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    received.append(rx.recvfrom(4096)[0])
                except _socket.timeout:
                    break

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        _send_tone(port, msgq_id=91, seconds=1.0,
                   destination='udp://127.0.0.1:%d, ws://0.0.0.0:9000' % port)
        t.join(timeout=6)
        rx.close()

        assert received, "ws:// in the destination list suppressed the udp:// audio"
        peak, _ = _peak_and_voiced(b''.join(received))
        assert peak == pytest.approx(EXPECTED_PEAK, rel=0.02)

    def test_stream_endpoint_serves_the_decoded_audio(
        self, monkeypatch: Any,
    ) -> None:
        """The bytes /api/stream would serve are valid WAV with real content."""
        port = 23992
        mgr = ws.AudioStreamManager(mix=True)
        # UdpAudioReceiver resolves `audio_manager` (the mixed aggregate) and
        # `_port_managers` (per-channel) as module globals at push time.  Point
        # only the aggregate at `mgr`: aiming both at one manager mixes every
        # packet into it twice and doubles the amplitude.
        monkeypatch.setattr(ws, 'audio_manager', mgr)
        monkeypatch.setattr(ws, '_port_managers', {})

        receiver = ws.UdpAudioReceiver([('127.0.0.1', port)])
        receiver.start()
        time.sleep(0.5)          # let the socket bind before the flowgraph runs
        try:
            threading.Thread(target=_send_tone, args=(port, 92, 2.0),
                             daemon=True).start()

            async def pull() -> bytes:
                chunks: list[bytes] = []
                gen = mgr.generate(out_rate=SAMPLE_RATE, container='wav')
                try:
                    async with asyncio.timeout(12):
                        async for chunk in gen:
                            chunks.append(chunk)
                            if sum(len(c) for c in chunks) > 40_000:
                                break
                except (TimeoutError, asyncio.TimeoutError):
                    pass
                finally:
                    await gen.aclose()
                return b''.join(chunks)

            data = asyncio.run(pull())
        finally:
            receiver.stop()

        assert receiver.packets_pcm > 0, "receiver saw no PCM packets"
        assert data[:4] == b'RIFF' and data[8:12] == b'WAVE'
        peak, voiced = _peak_and_voiced(data[44:])
        assert peak == pytest.approx(EXPECTED_PEAK, rel=0.02)
        # Not ~100%: the stream emits silence until the flowgraph starts.
        assert voiced > 0.5
