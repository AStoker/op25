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
from typing import Any

import pytest

import websocket_server as ws


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
        # ws:// is the legacy stack's C++ sink; only udp carries PCM here.
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
            'audio': {'instances': [{'udp_port': 23456}]},
        })
        ports = [e['port'] for e in eps]
        assert 23456 not in ports and 23457 not in ports
        assert 23458 in ports

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
