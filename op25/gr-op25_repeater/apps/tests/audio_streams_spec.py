"""
Per-channel audio streams.

A multi-channel config used to be served as one mixed stream, so listening to
a single channel was impossible and the two slots of a DMR channel — which are
independent conversations — were mixed into each other.  These cover the
endpoint discovery, the per-port fan-out, and the /api/stream selectors.

TestClient.stream() hangs on /api/stream (it is an unbounded generator), so the
generator is driven directly under asyncio instead.
"""

import asyncio
import struct
import time
from typing import Any

import pytest

import websocket_server as ws
from ha_bridge import mix_pcm16


def _pcm(nbytes: int, fill: int = 1) -> bytes:
    return bytes([fill]) * nbytes


async def _take_chunks(mgr: ws.AudioStreamManager, count: int, **kw: Any) -> list[bytes]:
    """Pull *count* chunks from a manager's generator, then stop.

    The jitter buffer is disabled here so a test can push one chunk and read it
    back on the next tick.  These cases are about routing and mixing, not
    pacing; priming has its own class below.
    """
    mgr.prime_bytes = 0
    out: list[bytes] = []
    gen = mgr.generate(**kw)
    try:
        for _ in range(count):
            out.append(await gen.__anext__())
    finally:
        await gen.aclose()
    return out


async def _take_chunks_primed(mgr: ws.AudioStreamManager, count: int, **kw: Any) -> list[bytes]:
    """Like :func:`_take_chunks` but leaves the jitter buffer in place."""
    out: list[bytes] = []
    gen = mgr.generate(**kw)
    try:
        for _ in range(count):
            out.append(await gen.__anext__())
    finally:
        await gen.aclose()
    return out


# ---------------------------------------------------------------------------
# Endpoint discovery
# ---------------------------------------------------------------------------


class TestEndpointDiscovery:
    def test_channel_contributes_both_slots(self) -> None:
        eps = ws._discover_audio_endpoints({
            'channels': [{'name': 'voice channel', 'destination': 'udp://127.0.0.1:23456'}],
        })
        assert [(e['port'], e['slot']) for e in eps] == [(23456, 'A'), (23457, 'B')]
        assert all(e['channel'] == 0 for e in eps)
        assert all(e['name'] == 'voice channel' for e in eps)

    def test_multiple_channels_are_attributed(self) -> None:
        eps = ws._discover_audio_endpoints({
            'channels': [
                {'name': 'ch one', 'destination': 'udp://127.0.0.1:23456'},
                {'name': 'ch two', 'destination': 'udp://127.0.0.1:23460'},
            ],
        })
        slot_a = {e['channel']: e for e in eps if e['slot'] == 'A'}
        assert slot_a[0]['port'] == 23456
        assert slot_a[1]['port'] == 23460
        assert slot_a[1]['name'] == 'ch two'

    def test_ws_destinations_are_ignored(self) -> None:
        # ws:// was removed from the C++ audio layer (it fed the legacy browser
        # UI directly).  Old configs on disk may still carry one, and the
        # decoder only warns about it, so discovery must keep parsing such a
        # destination harmlessly and use the udp half.
        eps = ws._discover_audio_endpoints({
            'channels': [{'name': 'c', 'destination': 'udp://127.0.0.1:23456, ws://0.0.0.0:9000'}],
        })
        assert sorted(e['port'] for e in eps) == [23456, 23457]

    def test_audio_ports_override_wins_unattributed(self) -> None:
        eps = ws._discover_audio_endpoints({
            'channels': [{'name': 'c', 'destination': 'udp://127.0.0.1:23456'}],
            'terminal': {'audio_ports': [23458]},
        })
        assert [e['port'] for e in eps] == [23458]
        assert eps[0]['channel'] is None

    def test_local_audio_ports_are_excluded(self) -> None:
        # A unicast UDP port has one consumer; sockaudio wins.
        eps = ws._discover_audio_endpoints({
            'channels': [{'name': 'c', 'destination': 'udp://127.0.0.1:23456, udp://127.0.0.1:23458'}],
            'audio': {'module': 'sockaudio.py', 'instances': [{'udp_port': 23456}]},
        })
        ports = [e['port'] for e in eps]
        assert 23456 not in ports and 23457 not in ports
        assert 23458 in ports

    def test_instances_do_not_claim_ports_when_the_module_is_disabled(self) -> None:
        """An inert audio block must not silence browser audio.

        multi_rx's configure_audio() returns early on an empty "module", so
        nothing binds those ports.  Excluding them anyway would silence any
        config that merely left a stale audio block behind -- which is how the
        Home Assistant add-on runs by default (audio_output: browser sets
        module to "").
        """
        for module in ('', '   ', None):
            eps = ws._discover_audio_endpoints({
                'channels': [{'name': 'c', 'destination': 'udp://127.0.0.1:23456'}],
                'audio': {'module': module, 'instances': [{'udp_port': 23456}]},
            })
            ports = [e['port'] for e in eps]
            assert ports == [23456, 23457], f'module={module!r} gave {ports}'

    def test_default_fallback_when_nothing_configured(self) -> None:
        eps = ws._discover_audio_endpoints({})
        assert [e['port'] for e in eps] == [ws._DEFAULT_AUDIO_PORT,
                                            ws._DEFAULT_AUDIO_PORT + 1]

    def test_ports_wrapper_still_returns_host_port_pairs(self) -> None:
        pairs = ws._discover_audio_ports({
            'channels': [{'name': 'c', 'destination': 'udp://127.0.0.1:23456'}],
        })
        assert pairs == [('127.0.0.1', 23456), ('127.0.0.1', 23457)]


# ---------------------------------------------------------------------------
# Per-port fan-out
# ---------------------------------------------------------------------------


class TestPortManagers:
    @pytest.fixture(autouse=True)
    def _endpoints(self) -> Any:
        ws._init_port_managers([
            {'host': '127.0.0.1', 'port': 23456, 'channel': 0, 'name': 'ch one', 'slot': 'A'},
            {'host': '127.0.0.1', 'port': 23457, 'channel': 0, 'name': 'ch one', 'slot': 'B'},
            {'host': '127.0.0.1', 'port': 23460, 'channel': 1, 'name': 'ch two', 'slot': 'A'},
        ])
        yield
        ws._init_port_managers([])

    def test_one_manager_per_port(self) -> None:
        assert sorted(ws._port_managers) == [23456, 23457, 23460]

    def test_managers_are_distinct(self) -> None:
        ws._port_managers[23456].push_audio(_pcm(320, 1))
        assert ws._port_managers[23456].bytes_pushed == 320
        assert ws._port_managers[23457].bytes_pushed == 0
        assert ws._port_managers[23460].bytes_pushed == 0

    def test_channel_lookup_resolves_slot_a(self) -> None:
        assert ws._manager_for_channel(0) is ws._port_managers[23456]
        assert ws._manager_for_channel(1) is ws._port_managers[23460]

    def test_channel_lookup_misses_are_none(self) -> None:
        assert ws._manager_for_channel(9) is None

    def test_slot_b_is_reachable_only_by_port(self) -> None:
        # The two slots of a DMR channel are separate conversations, so slot B
        # deliberately is not what channel=N gives you.
        assert ws._manager_for_channel(0) is not ws._port_managers[23457]


# ---------------------------------------------------------------------------
# Stream selection
# ---------------------------------------------------------------------------


class TestStreamSelection:
    @pytest.fixture(autouse=True)
    def _endpoints(self) -> Any:
        ws._init_port_managers([
            {'host': '127.0.0.1', 'port': 23456, 'channel': 0, 'name': 'ch one', 'slot': 'A'},
            {'host': '127.0.0.1', 'port': 23460, 'channel': 1, 'name': 'ch two', 'slot': 'A'},
        ])
        yield
        ws._init_port_managers([])

    def test_listing_reports_every_stream(self, client: Any) -> None:
        body = client.get('/api/audio/channels').json()
        assert body['aggregate_url'] == '/api/stream'
        by_port = {s['port']: s for s in body['streams']}
        assert by_port[23456]['channel'] == 0
        assert by_port[23460]['name'] == 'ch two'
        assert by_port[23456]['url'] == '/api/stream?port=23456'

    def test_listing_reports_byte_counters(self, client: Any) -> None:
        ws._port_managers[23460].push_audio(_pcm(640))
        by_port = {s['port']: s for s in client.get('/api/audio/channels').json()['streams']}
        assert by_port[23460]['bytes'] == 640
        assert by_port[23456]['bytes'] == 0

    def test_unknown_port_is_404(self, client: Any) -> None:
        resp = client.get('/api/stream?port=9999')
        assert resp.status_code == 404
        assert resp.json()['known'] == [23456, 23460]

    def test_unknown_channel_is_404(self, client: Any) -> None:
        resp = client.get('/api/stream?channel=7')
        assert resp.status_code == 404
        assert resp.json()['known'] == [0, 1]

    def test_bad_rate_still_rejected(self, client: Any) -> None:
        assert client.get('/api/stream?rate=12345').status_code == 400

    def test_per_channel_stream_carries_only_its_own_audio(self) -> None:
        # Push distinct audio to each port, then check the streams do not
        # bleed into one another.
        ws._port_managers[23456].push_audio(_pcm(ws._CHUNK_BYTES, 0x11))
        ws._port_managers[23460].push_audio(_pcm(ws._CHUNK_BYTES, 0x22))

        first = asyncio.run(_take_chunks(ws._port_managers[23456], 1, container='raw'))
        second = asyncio.run(_take_chunks(ws._port_managers[23460], 1, container='raw'))

        assert first[0] == _pcm(ws._CHUNK_BYTES, 0x11)
        assert second[0] == _pcm(ws._CHUNK_BYTES, 0x22)

    def test_aggregate_still_receives_everything(self) -> None:
        # The UDP thread pushes to both the aggregate and the per-port manager,
        # so bare /api/stream behaves as it always did.
        before = ws.audio_manager.bytes_pushed
        ws.audio_manager.push_audio(_pcm(320))
        assert ws.audio_manager.bytes_pushed == before + 320

    def test_stream_emits_wav_header_by_default(self) -> None:
        chunks = asyncio.run(_take_chunks(ws._port_managers[23456], 1))
        assert chunks[0][:4] == b'RIFF'
        assert chunks[0][8:12] == b'WAVE'


# ---------------------------------------------------------------------------
# Aggregate mixing
# ---------------------------------------------------------------------------


def _s16(*vals: int) -> bytes:
    """Little-endian signed-16 PCM from sample values."""
    return struct.pack('<%dh' % len(vals), *vals)


class TestMixPcm16:
    def test_sums_samples(self) -> None:
        assert mix_pcm16([_s16(100, -200), _s16(50, -50)]) == _s16(150, -250)

    def test_single_input_is_passed_through_untouched(self) -> None:
        # The common case even on a multi-SDR setup: only one call is up.  It
        # must not be attenuated, which is why mixing sums rather than averages.
        one = _s16(3000, -3000, 12)
        assert mix_pcm16([one]) == one
        assert mix_pcm16([one, b'']) == one

    def test_clamps_instead_of_wrapping(self) -> None:
        loud = _s16(30000, -30000)
        assert mix_pcm16([loud, loud]) == _s16(32767, -32768)

    def test_result_is_as_long_as_the_longest_input(self) -> None:
        # A short tail must not truncate a channel that still has audio.
        assert mix_pcm16([_s16(1), _s16(2, 7, 9)]) == _s16(3, 7, 9)

    def test_empty(self) -> None:
        assert mix_pcm16([]) == b''
        assert mix_pcm16([b'', b'']) == b''


class TestAggregateMixes:
    def _fresh(self) -> ws.AudioStreamManager:
        mgr = ws.AudioStreamManager(mix=True)
        mgr.mock = False
        return mgr

    def test_simultaneous_channels_are_summed_not_concatenated(self) -> None:
        # The bug this replaces: two ports pushing one chunk each produced two
        # chunks of serially-spliced audio, so three active channels delivered
        # audio at 3x real time and the listener heard fragments of each.
        mgr = self._fresh()
        mgr.push_audio(_s16(*([100] * ws._CHUNK_SAMPLES)), port=23458)
        mgr.push_audio(_s16(*([ 25] * ws._CHUNK_SAMPLES)), port=23462)

        chunks = asyncio.run(_take_chunks(mgr, 2, container='raw'))
        assert chunks[0] == _s16(*([125] * ws._CHUNK_SAMPLES))
        # One chunk in, one chunk out: the second is silence, not a backlog.
        assert chunks[1] == b'\x00' * ws._CHUNK_BYTES

    def test_one_active_port_is_bit_identical(self) -> None:
        mgr = self._fresh()
        payload = _pcm(ws._CHUNK_BYTES, 0x33)
        mgr.push_audio(payload, port=23458)
        assert asyncio.run(_take_chunks(mgr, 1, container='raw'))[0] == payload

    def test_ports_are_bounded_independently(self) -> None:
        # One channel running away must not evict another channel's audio.
        # A consumer is attached so the bound under test is the full 4 s one --
        # with nobody listening the bound is a short live window instead, see
        # TestIdleBacklogIsNotInherited.
        mgr = self._fresh()
        mgr._attach()
        try:
            cap = ws.AudioStreamManager._MAX_BUFFERED_BYTES
            mgr.push_audio(_pcm(cap * 2, 0x44), port=23458)
            mgr.push_audio(_pcm(ws._CHUNK_BYTES, 0x55), port=23462)
            assert mgr.bytes_dropped == cap
            # 23462's chunk survived and is still mixed in.
            assert mgr.buffered_bytes() == cap
        finally:
            mgr._detach()

    def test_buffered_bytes_is_the_worst_port_not_the_sum(self) -> None:
        mgr = self._fresh()
        mgr.push_audio(_pcm(640), port=23458)
        mgr.push_audio(_pcm(320), port=23462)
        assert mgr.buffered_bytes() == 640

    def test_non_mixing_manager_still_appends(self) -> None:
        # Per-port managers have a single source, so they keep the plain buffer.
        mgr = ws.AudioStreamManager()
        mgr.mock = False
        mgr.push_audio(_pcm(ws._CHUNK_BYTES, 0x66))
        mgr.push_audio(_pcm(ws._CHUNK_BYTES, 0x77))
        chunks = asyncio.run(_take_chunks(mgr, 2, container='raw'))
        assert chunks[0] == _pcm(ws._CHUNK_BYTES, 0x66)
        assert chunks[1] == _pcm(ws._CHUNK_BYTES, 0x77)


# ---------------------------------------------------------------------------
# Jitter buffer
#
# The decoder emits one 20 ms frame every 20 ms and the stream consumes one
# every 20 ms, so without a cushion any late packet finds an empty buffer and
# the only thing to send is a hole in the middle of a word.  These cases pin the
# priming behaviour that keeps that from happening; see _STREAM_PRIME_MS.
# ---------------------------------------------------------------------------


class TestJitterBuffer:
    def _fresh(self) -> ws.AudioStreamManager:
        mgr = ws.AudioStreamManager()
        mgr.mock = False
        return mgr

    def test_prime_is_enabled_by_default(self) -> None:
        mgr = self._fresh()
        assert mgr.prime_bytes >= ws._CHUNK_BYTES, \
            "a zero prime is the chopping bug this exists to prevent"

    def test_playback_waits_for_the_cushion(self) -> None:
        # One chunk buffered is not enough to start: emitting it immediately is
        # what stops the cushion from ever building.
        mgr = self._fresh()
        mgr.push_audio(_pcm(ws._CHUNK_BYTES, 0x11))
        chunks = asyncio.run(_take_chunks_primed(mgr, 1, container='raw'))
        assert chunks[0] == b'\x00' * ws._CHUNK_BYTES
        assert mgr.silent_chunks == 1
        assert mgr.real_chunks == 0
        # The audio was held, not discarded.
        assert mgr.buffered_bytes() == ws._CHUNK_BYTES

    def test_audio_flows_once_primed(self) -> None:
        mgr = self._fresh()
        mgr.push_audio(_pcm(mgr.prime_bytes, 0x22))
        n = mgr.prime_bytes // ws._CHUNK_BYTES
        chunks = asyncio.run(_take_chunks_primed(mgr, n, container='raw'))
        assert chunks == [_pcm(ws._CHUNK_BYTES, 0x22)] * n
        assert mgr.real_chunks == n
        assert mgr.underruns == 0

    def test_dropout_re_primes_instead_of_chopping(self) -> None:
        # Drain the cushion, then push a single chunk.  The stream must rebuild
        # the cushion rather than hand out the lone chunk and be empty again.
        mgr = self._fresh()
        mgr.push_audio(_pcm(mgr.prime_bytes, 0x33))
        n = mgr.prime_bytes // ws._CHUNK_BYTES
        asyncio.run(_take_chunks_primed(mgr, n, container='raw'))
        assert mgr.buffered_bytes() == 0

        mgr.push_audio(_pcm(ws._CHUNK_BYTES, 0x44))
        chunks = asyncio.run(_take_chunks_primed(mgr, 1, container='raw'))
        assert chunks[0] == b'\x00' * ws._CHUNK_BYTES
        assert mgr.buffered_bytes() == ws._CHUNK_BYTES

    def test_idle_silence_is_not_counted_as_a_dropout(self) -> None:
        # 'underruns' has to mean "lost audio that was in flight" for it to be
        # usable as a diagnostic; idle silence must not inflate it.
        mgr = self._fresh()
        asyncio.run(_take_chunks_primed(mgr, 3, container='raw'))
        assert mgr.underruns == 0
        assert mgr.silent_chunks == 3


class TestRePrimeOnlyForTransportJitter:
    """A dropout gets a rebuilt cushion only if the *producer* is still producing.

    Re-priming is right for transport jitter — without a cushion every late packet
    punches another hole.  It is wrong for lost voice frames: an LDU whose frame
    sync failed yields no audio for as long as the RF is bad, no cushion can help,
    and the extra _STREAM_PRIME_MS of silence is charged on top of the real gap
    every single time.  The discriminator is producer_idle_ms(), latched as a
    running maximum because the packet that ends the gap destroys the evidence.
    """

    def _fresh(self) -> ws.AudioStreamManager:
        mgr = ws.AudioStreamManager()
        mgr.mock = False
        return mgr

    def test_producer_idle_is_infinite_before_the_first_push(self) -> None:
        assert self._fresh().producer_idle_ms() == float('inf')

    def test_producer_idle_tracks_the_last_push(self) -> None:
        mgr = self._fresh()
        mgr.push_audio(_pcm(ws._CHUNK_BYTES))
        assert mgr.producer_idle_ms() < 100.0

    def test_a_new_listener_always_primes(self) -> None:
        # dry_idle starts at infinity, so a client that has just attached gets a
        # full cushion whatever the producer was doing beforehand.  The no-prime
        # shortcut is only ever an in-flight decision about one dry spell.
        mgr = self._fresh()
        mgr.push_audio(_pcm(ws._CHUNK_BYTES, 0x55))
        chunks = asyncio.run(_take_chunks_primed(mgr, 1, container='raw'))
        assert chunks[0] == b'\x00' * ws._CHUNK_BYTES
        assert mgr.buffered_bytes() == ws._CHUNK_BYTES, "audio held, not dropped"

    async def _gap(
        self, mgr: ws.AudioStreamManager, idle_ms: float, fill: int = 0x22,
    ) -> bytes:
        """Prime, drain, open a gap of *idle_ms*, then resume with one chunk.

        The whole sequence has to run inside a single generator: the verdict is
        per-dry-spell state, and a freshly attached client is always primed
        properly regardless of what the producer was doing before it arrived.
        Returns the chunk yielded on the tick after the producer comes back.
        """
        mgr.push_audio(_pcm(mgr.prime_bytes, 0x11))
        n = mgr.prime_bytes // ws._CHUNK_BYTES
        gen = mgr.generate(container='raw')
        try:
            for _ in range(n):                  # drain the cushion
                await gen.__anext__()
            assert mgr.buffered_bytes() == 0

            mgr.last_push_ts = time.time() - idle_ms / 1_000.0
            await gen.__anext__()               # the dry tick: latches the verdict
            # The decoder comes back, which refreshes last_push_ts.
            mgr.push_audio(_pcm(ws._CHUNK_BYTES, fill))
            return await gen.__anext__()
        finally:
            await gen.aclose()

    def test_mid_call_decoder_gap_resumes_immediately(self) -> None:
        # Producer quiet for longer than a couple of packet intervals but well
        # inside a transmission: these are lost voice frames.  Play the moment
        # audio returns rather than adding a second prime's worth of hole.
        #
        # This also guards the latch: read fresh, producer_idle_ms() shows the
        # producer alive again on the very tick it resumes, so the gap would
        # re-prime anyway — and a two-threshold latch oscillated between the two
        # verdicts on alternate ticks.
        mgr = self._fresh()
        chunk = asyncio.run(self._gap(mgr, ws._JITTER_IDLE_MS + 100, fill=0x66))
        assert chunk == _pcm(ws._CHUNK_BYTES, 0x66), \
            "resumption must not be delayed by a prime it cannot benefit from"
        assert mgr.buffered_bytes() == 0

    def test_gap_past_the_dropout_ceiling_primes_again(self) -> None:
        # Past _DROPOUT_END_MS the transmission is over, so the next one is a fresh
        # start and deserves a real cushion.  Without this the no-reprime verdict
        # would stick and every subsequent call would chop on its first word.
        mgr = self._fresh()
        chunk = asyncio.run(self._gap(mgr, ws._DROPOUT_END_MS + 100, fill=0x77))
        assert chunk == b'\x00' * ws._CHUNK_BYTES
        assert mgr.buffered_bytes() == ws._CHUNK_BYTES

    def test_brief_gap_with_a_live_producer_still_primes(self) -> None:
        # The jitter case, driven the same way: the producer never went quiet, so
        # the cushion is worth rebuilding and the lone chunk is held back.
        mgr = self._fresh()
        chunk = asyncio.run(self._gap(mgr, 0.0, fill=0x88))
        assert chunk == b'\x00' * ws._CHUNK_BYTES
        assert mgr.buffered_bytes() == ws._CHUNK_BYTES


class TestIdleBacklogIsNotInherited:
    """A listener must start live, not behind whatever queued while it was away.

    The UDP thread pushes whether or not anyone is listening, so an idle server
    filled to _MAX_BUFFERED_BYTES and a client attaching inherited a 4 s lag for
    as long as it listened. Observed live: buf=64000 pushed=181440 yielded=0
    dropped=117440.

    The discriminator is *who is attached*, not how deep the buffer is -- a
    producer bursting ahead of real time is normal, and its audio is the start of
    a transmission rather than staleness.
    """

    def _fresh(self, mix: bool = False) -> ws.AudioStreamManager:
        mgr = ws.AudioStreamManager(mix=mix)
        mgr.mock = False
        return mgr

    def test_idle_buffer_is_bounded_to_a_live_window(self) -> None:
        mgr = self._fresh()
        assert mgr.consumers == 0
        mgr.push_audio(_pcm(ws.AudioStreamManager._MAX_BUFFERED_BYTES, 0x11))
        assert mgr.buffered_bytes() <= max(mgr.idle_keep_bytes, ws._CHUNK_BYTES)

    def test_idle_window_keeps_the_newest_audio(self) -> None:
        mgr = self._fresh()
        mgr.idle_keep_bytes = ws._CHUNK_BYTES
        mgr.push_audio(_pcm(ws._CHUNK_BYTES, 0xAA))
        mgr.push_audio(_pcm(ws._CHUNK_BYTES, 0xBB))
        assert bytes(mgr._buffer) == _pcm(ws._CHUNK_BYTES, 0xBB)

    def test_a_listener_starts_from_the_live_edge(self) -> None:
        mgr = self._fresh()
        mgr.idle_keep_bytes = ws._CHUNK_BYTES
        mgr.prime_bytes = ws._CHUNK_BYTES
        mgr.push_audio(_pcm(ws.AudioStreamManager._MAX_BUFFERED_BYTES, 0x11))  # history
        mgr.push_audio(_pcm(ws._CHUNK_BYTES, 0x22))                            # live edge
        first = asyncio.run(_take_chunks_primed(mgr, 1, container='raw'))[0]
        assert first == _pcm(ws._CHUNK_BYTES, 0x22)

    def test_an_attached_consumer_gets_the_full_buffer(self) -> None:
        # Once someone is listening, nothing may be discarded early: a burst is
        # the start of a transmission, and trimming it clips the first word.
        mgr = self._fresh()
        mgr._attach()
        try:
            mgr.push_audio(_pcm(mgr.idle_keep_bytes * 4, 0x33))
            assert mgr.buffered_bytes() == mgr.idle_keep_bytes * 4
            assert mgr.bytes_dropped == 0
        finally:
            mgr._detach()

    def test_generate_registers_and_deregisters_as_a_consumer(self) -> None:
        mgr = self._fresh()
        seen = []

        async def drive() -> None:
            gen = mgr.generate(container='raw')
            try:
                await gen.__anext__()
                seen.append(mgr.consumers)
            finally:
                await gen.aclose()

        asyncio.run(drive())
        assert seen == [1], 'generate() did not register as a consumer'
        assert mgr.consumers == 0, 'consumer count leaked after aclose()'

    def test_detach_never_goes_negative(self) -> None:
        mgr = self._fresh()
        mgr._detach()
        assert mgr.consumers == 0

    def test_drop_stale_keeps_the_tail(self) -> None:
        mgr = self._fresh()
        mgr._attach()
        try:
            mgr.push_audio(_pcm(320, 0xAA) + _pcm(320, 0xBB))
            assert mgr.drop_stale(320) == 320
            assert bytes(mgr._buffer) == _pcm(320, 0xBB)
        finally:
            mgr._detach()

    def test_drop_stale_is_a_noop_below_the_threshold(self) -> None:
        mgr = self._fresh()
        mgr.push_audio(_pcm(320, 0xCC))
        assert mgr.drop_stale(640) == 0
        assert mgr.buffered_bytes() == 320

    def test_mix_mode_bounds_each_source_independently(self) -> None:
        # Bounding the sum would let one backed-up channel evict another's audio.
        mgr = self._fresh(mix=True)
        mgr.idle_keep_bytes = ws._CHUNK_BYTES
        mgr.push_audio(_pcm(ws._CHUNK_BYTES * 4, 0x44), port=23458)
        mgr.push_audio(_pcm(ws._CHUNK_BYTES, 0x55), port=23462)
        assert all(len(b) == ws._CHUNK_BYTES for b in mgr._mix_buffers.values())
