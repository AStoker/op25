"""
Contract tests for the websocket_server ↔ browser protocol.

These cover the parts of the bridge that used to claim more than they did:

  - _JSON_TYPE_TO_MSG only routes json_types the decoder actually emits
  - SYSTEM_STATE is live: status/uptime track whether the decoder is feeding us
  - the call_log ring replays history to a late-joining client
  - /api/captures lists what the decoder reported and refuses anything else
  - SYSTEM_CONTROL accepts quit and nothing invented
"""

from typing import Any

import pytest

import websocket_server as ws


def _recv_until(sock: Any, msg_type: str, limit: int = 5) -> dict[str, Any]:
    """Read frames until one of *msg_type* arrives.

    The server sends a health snapshot on connect, and a call_log replay too
    when it has history, so a test waiting for its own reply must not assume a
    fixed frame count.
    """
    for _ in range(limit):
        frame = sock.receive_json()
        if frame['type'] == msg_type:
            return frame
    raise AssertionError(f'no {msg_type} frame within {limit} messages')


# ---------------------------------------------------------------------------
# json_type routing
# ---------------------------------------------------------------------------


class TestJsonTypeRouting:
    """Every key must be a json_type some decoder module really emits."""

    # Sourced by grepping "'json_type'" across apps/*.py.
    REAL_JSON_TYPES = {
        'ok', 'error', 'call_log', 'channel_update', 'trunk_update',
        'meta_update', 'plot', 'terminal_config', 'full_config',
    }

    def test_no_fictional_keys(self) -> None:
        unknown = set(ws._JSON_TYPE_TO_MSG) - self.REAL_JSON_TYPES
        assert unknown == set(), f"routing table names json_types nobody emits: {unknown}"

    def test_every_target_is_a_downstream_type(self) -> None:
        for json_type, msg_type in ws._JSON_TYPE_TO_MSG.items():
            assert msg_type in ws.DOWNSTREAM_TYPES, json_type

    def test_call_log_routes_to_call_activity(self) -> None:
        assert ws._JSON_TYPE_TO_MSG['call_log'] == ws.MSG_CALL_ACTIVITY

    def test_sdr_status_is_gone(self) -> None:
        # It was never emitted; keeping the type advertised a channel that
        # carried nothing.
        assert not hasattr(ws, 'MSG_SDR_STATUS')
        assert all('SDR' not in t for t in ws.DOWNSTREAM_TYPES)


# ---------------------------------------------------------------------------
# SYSTEM_STATE health payload
# ---------------------------------------------------------------------------


class TestSystemStatePayload:
    @pytest.fixture(autouse=True)
    def _reset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ws, '_last_decoder_msg_at', 0.0)
        monkeypatch.setattr(ws, '_server_started_at', ws.time.time() - 42)

    def test_stopped_before_any_decoder_message(self) -> None:
        payload = ws._system_state_payload()
        assert payload['status'] == 'stopped'
        assert payload['error_detail']

    def test_running_while_decoder_is_fresh(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ws, '_last_decoder_msg_at', ws.time.time())
        payload = ws._system_state_payload()
        assert payload['status'] == 'running'
        assert payload['error_detail'] == ''

    def test_error_once_decoder_goes_quiet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stale = ws.time.time() - (ws._DECODER_STALE_SECS + 5)
        monkeypatch.setattr(ws, '_last_decoder_msg_at', stale)
        payload = ws._system_state_payload()
        assert payload['status'] == 'error'
        assert 'no decoder update' in payload['error_detail']

    def test_uptime_counts_up(self) -> None:
        assert ws._system_state_payload()['uptime'] >= 42

    def test_identity_comes_from_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ws, '_config', {
            'channels': [{'name': 'voice channel'}],
            'trunking': {'chans': [{'sysname': 'palmetto'}]},
        })
        payload = ws._system_state_payload()
        assert payload['site_name'] == 'voice channel'
        assert payload['trunk_id'] == 'palmetto'


# ---------------------------------------------------------------------------
# call_log ring (late joiners)
# ---------------------------------------------------------------------------


class TestCallLogRing:
    @pytest.fixture(autouse=True)
    def _clear(self) -> None:
        ws._recent_calls.clear()

    def test_accumulates_draining_feed(self) -> None:
        ws._note_call_log({'json_type': 'call_log', 'log': [{'tgid': 1}, {'tgid': 2}]})
        ws._note_call_log({'json_type': 'call_log', 'log': [{'tgid': 3}]})
        assert [e['tgid'] for e in ws._recent_call_log()] == [1, 2, 3]

    def test_ignores_empty_and_malformed(self) -> None:
        ws._note_call_log({'json_type': 'call_log', 'log': []})
        ws._note_call_log({'json_type': 'call_log'})
        ws._note_call_log({'json_type': 'call_log', 'log': 'nope'})
        assert ws._recent_call_log() == []

    def test_ring_is_bounded(self) -> None:
        ws._note_call_log({'json_type': 'call_log',
                           'log': [{'tgid': i} for i in range(ws._CALL_LOG_HISTORY + 50)]})
        assert len(ws._recent_call_log()) == ws._CALL_LOG_HISTORY

    def test_limit_returns_newest(self) -> None:
        ws._note_call_log({'json_type': 'call_log', 'log': [{'tgid': i} for i in range(10)]})
        assert [e['tgid'] for e in ws._recent_call_log(3)] == [7, 8, 9]


# ---------------------------------------------------------------------------
# Symbol captures
# ---------------------------------------------------------------------------


class TestCaptures:
    @pytest.fixture(autouse=True)
    def _clear(self) -> None:
        ws._capture_files.clear()
        ws._last_channels.clear()

    def test_channel_update_registers_capture_file(self, tmp_path: Any) -> None:
        path = tmp_path / 'ch0-capture.dat'
        path.write_bytes(b'\x00\x01\x02')
        ws._note_channel_state({
            'json_type': 'channel_update',
            'channels': ['0'],
            '0': {'name': 'ch0', 'capture': True, 'capture_file': str(path)},
        })
        assert ws._capture_files == [str(path)]

    def test_no_duplicate_registrations(self, tmp_path: Any) -> None:
        entry = {
            'json_type': 'channel_update',
            'channels': ['0'],
            '0': {'name': 'ch0', 'capture': True, 'capture_file': str(tmp_path / 'a.dat')},
        }
        ws._note_channel_state(entry)
        ws._note_channel_state(entry)
        assert len(ws._capture_files) == 1

    def test_list_reports_size_and_existence(self, client: Any, tmp_path: Any) -> None:
        real = tmp_path / 'real.dat'
        real.write_bytes(b'x' * 17)
        ws._capture_files.extend([str(real), str(tmp_path / 'gone.dat')])

        body = client.get('/api/captures').json()
        by_name = {c['name']: c for c in body['captures']}
        assert by_name['real.dat']['size'] == 17
        assert by_name['real.dat']['exists'] is True
        assert by_name['gone.dat']['exists'] is False

    def test_download_serves_registered_file(self, client: Any, tmp_path: Any) -> None:
        path = tmp_path / 'ch0-capture.dat'
        path.write_bytes(b'symbols')
        ws._capture_files.append(str(path))

        resp = client.get('/api/captures/ch0-capture.dat')
        assert resp.status_code == 200
        assert resp.content == b'symbols'

    def test_unknown_capture_is_404(self, client: Any) -> None:
        assert client.get('/api/captures/nope.dat').status_code == 404

    def test_traversal_cannot_reach_arbitrary_files(self, client: Any, tmp_path: Any) -> None:
        # Only basenames of registered files are served, so a traversal attempt
        # matches nothing.  An encoded-slash path stops matching this route at
        # all and lands on the SPA fallback (200 index.html) — either way no
        # file content escapes.
        secret = tmp_path / 'secret.txt'
        secret.write_text('classified')
        for attempt in ('..%2f..%2fetc%2fpasswd', '../../etc/passwd', str(secret)):
            resp = client.get(f'/api/captures/{attempt}')
            assert b'root:' not in resp.content
            assert b'classified' not in resp.content

    def test_missing_file_is_404_not_500(self, client: Any, tmp_path: Any) -> None:
        ws._capture_files.append(str(tmp_path / 'vanished.dat'))
        assert client.get('/api/captures/vanished.dat').status_code == 404


# ---------------------------------------------------------------------------
# Upstream control surface
# ---------------------------------------------------------------------------


class TestUpstreamTypes:
    def test_only_two_upstream_types(self) -> None:
        assert ws.UPSTREAM_TYPES == {ws.MSG_CALL_CONTROL, ws.MSG_SYSTEM_CONTROL}

    def test_unknown_type_is_rejected(self, client: Any) -> None:
        with client.websocket_connect('/ws') as sock:
            sock.send_json({'type': 'NOPE', 'payload': {}})
            reply = _recv_until(sock, 'ERROR')
            assert 'unknown type' in reply['payload']['detail']

    def test_invalid_json_is_rejected(self, client: Any) -> None:
        with client.websocket_connect('/ws') as sock:
            sock.send_text('{not json')
            reply = _recv_until(sock, 'ERROR')
            assert 'invalid JSON' in reply['payload']['detail']


class TestConnectSnapshot:
    @pytest.fixture(autouse=True)
    def _clear_history(self) -> Any:
        # The ring is module state shared by every client, so a test that seeds
        # it must not change what the next connection sees.
        ws._recent_calls.clear()
        yield
        ws._recent_calls.clear()

    def test_health_payload_arrives_first(self, client: Any) -> None:
        with client.websocket_connect('/ws') as sock:
            first = sock.receive_json()
            assert first['type'] == ws.MSG_SYSTEM_STATE
            assert 'status' in first['payload']
            assert 'uptime' in first['payload']

    def test_call_history_is_replayed(self, client: Any) -> None:
        ws._note_call_log({'json_type': 'call_log', 'log': [{'tgid': 4242}]})
        with client.websocket_connect('/ws') as sock:
            sock.receive_json()                      # health
            replay = sock.receive_json()
            assert replay['type'] == ws.MSG_CALL_ACTIVITY
            assert replay['payload']['json_type'] == 'call_log'
            assert replay['payload']['replay'] is True
            assert replay['payload']['log'][0]['tgid'] == 4242

    def test_no_replay_frame_when_history_empty(self, client: Any) -> None:
        with client.websocket_connect('/ws') as sock:
            sock.receive_json()                      # health
            # Nothing else should be queued; ask for something and check the
            # very next frame is the error reply, not a replay.
            sock.send_json({'type': 'NOPE', 'payload': {}})
            assert sock.receive_json()['type'] == 'ERROR'
