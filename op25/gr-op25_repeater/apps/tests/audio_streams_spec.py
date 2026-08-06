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
from typing import Any

import pytest

import websocket_server as ws
from ha_bridge import mix_pcm16


def _pcm(nbytes: int, fill: int = 1) -> bytes:
    return bytes([fill]) * nbytes


async def _take_chunks(mgr: ws.AudioStreamManager, count: int, **kw: Any) -> list[bytes]:
    """Pull *count* chunks from a manager's generator, then stop."""
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
        mgr = self._fresh()
        cap = ws.AudioStreamManager._MAX_BUFFERED_BYTES
        mgr.push_audio(_pcm(cap * 2, 0x44), port=23458)
        mgr.push_audio(_pcm(ws._CHUNK_BYTES, 0x55), port=23462)
        assert mgr.bytes_dropped == cap
        # 23462's chunk survived and is still mixed in.
        assert mgr.buffered_bytes() == cap

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
