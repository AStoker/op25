"""
Config editing over REST: the write gate, the endpoints, and the honesty of
what they report back.

The write gate is the part worth being careful about. Port 8099 is
unauthenticated -- `allow_origins=["*"]`, no token -- so config *writes* have to
be confined to the Home Assistant ingress path, which is authenticated. Getting
that wrong hands anyone on the LAN the ability to re-point the receiver or change
the Home Assistant webhook.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import config_store as cs
import websocket_server as ws


BASE: dict[str, Any] = {
    'devices': [{'name': 'sdr0', 'args': 'rtl', 'gains': 'LNA:40',
                 'rate': 2400000, 'ppm': 0.0, 'frequency': 859262500}],
    'channels': [{'name': 'Palmetto 800', 'device': 'sdr0', 'if_rate': 24000,
                  'symbol_rate': 4800}],
    'trunking': {'module': 'tk_p25.py',
                 'chans': [{'sysname': 'P800', 'nac': '0x1D1'}]},
    'terminal': {'http_plot_interval': 1.0,
                 'home_assistant': {'enabled': False, 'token': 'a-real-secret'}},
}

INGRESS = {'X-Ingress-Path': '/api/hassio_ingress/abc123'}


@pytest.fixture()
def client(tmp_path: Any, monkeypatch: Any) -> Any:
    """A TestClient with an editable config store and writes open by default."""
    monkeypatch.setattr(ws, '_config', copy.deepcopy(BASE))
    monkeypatch.setenv('OP25_CONFIG_OVERLAY', str(tmp_path / 'overlay.json'))
    monkeypatch.setenv('OP25_CONFIG_HISTORY_DB', str(tmp_path / 'history.sqlite'))
    monkeypatch.setenv('OP25_CONFIG_WRITE', 'open')
    monkeypatch.delenv('SUPERVISOR_TOKEN', raising=False)
    ws._init_config_store()
    # Nothing to send commands to; _send_upstream returns False rather than raising.
    monkeypatch.setattr(ws, '_output_q', None)
    yield TestClient(ws.app)
    if ws._config_store is not None:
        ws._config_store.close()
    monkeypatch.setattr(ws, '_config_store', None)


def _put(client: Any, mutate: Any, **kw: Any) -> Any:
    cfg = client.get('/api/config/state').json()['effective']
    mutate(cfg)
    return client.put('/api/config', json={'config': cfg}, **kw)


# ---------------------------------------------------------------------------
# Write gate
# ---------------------------------------------------------------------------


class TestWritePolicy:
    def test_defaults_to_ingress_only_as_an_addon(self, monkeypatch: Any) -> None:
        # SUPERVISOR_TOKEN is what distinguishes the add-on: bashio exports it in
        # the container and nothing else sets it.
        monkeypatch.delenv('OP25_CONFIG_WRITE', raising=False)
        monkeypatch.setattr(ws, '_config', {})
        monkeypatch.setenv('SUPERVISOR_TOKEN', 'x')
        assert ws._write_policy() == 'ingress'

    def test_defaults_to_open_standalone(self, monkeypatch: Any) -> None:
        # A standalone install has no ingress to require, so defaulting to
        # 'ingress' there would make the editor permanently unreachable rather
        # than secure.
        monkeypatch.delenv('OP25_CONFIG_WRITE', raising=False)
        monkeypatch.delenv('SUPERVISOR_TOKEN', raising=False)
        monkeypatch.setattr(ws, '_config', {})
        assert ws._write_policy() == 'open'

    def test_env_overrides_everything(self, monkeypatch: Any) -> None:
        monkeypatch.setenv('OP25_CONFIG_WRITE', 'off')
        monkeypatch.setattr(ws, '_config', {'terminal': {'config_write': 'open'}})
        assert ws._write_policy() == 'off'

    def test_config_key_beats_the_default(self, monkeypatch: Any) -> None:
        monkeypatch.delenv('OP25_CONFIG_WRITE', raising=False)
        monkeypatch.setattr(ws, '_config', {'terminal': {'config_write': 'off'}})
        assert ws._write_policy() == 'off'


class TestIngressGate:
    @pytest.fixture(autouse=True)
    def _ingress_policy(self, client: Any, monkeypatch: Any) -> None:
        monkeypatch.setenv('OP25_CONFIG_WRITE', 'ingress')

    def test_write_without_the_ingress_header_is_403(self, client: Any) -> None:
        resp = _put(client, lambda c: c['devices'][0].update(gains='LNA:42'))
        assert resp.status_code == 403
        assert 'ingress' in resp.json()['error']

    def test_write_with_the_ingress_header_succeeds(self, client: Any) -> None:
        resp = _put(client, lambda c: c['devices'][0].update(gains='LNA:42'),
                    headers=INGRESS)
        assert resp.status_code == 200, resp.text

    def test_reads_stay_open(self, client: Any) -> None:
        # So `yarn dev` against the published port still works for UI work;
        # only writes need the authenticated path.
        assert client.get('/api/config/state').status_code == 200
        assert client.get('/api/config/schema').status_code == 200
        assert client.get('/api/config/history').status_code == 200

    def test_rollback_and_reset_are_gated_too(self, client: Any) -> None:
        assert client.post('/api/config/reset').status_code == 403
        assert client.post('/api/config/rollback/1').status_code == 403
        assert client.post('/api/config/export', json={}).status_code == 403

    def test_the_403_explains_how_to_proceed(self, client: Any) -> None:
        body = client.post('/api/config/reset').json()
        assert 'sidebar' in body['detail']
        assert body['policy'] == 'ingress'


class TestWritesDisabled:
    def test_off_refuses_even_via_ingress(self, client: Any, monkeypatch: Any) -> None:
        monkeypatch.setenv('OP25_CONFIG_WRITE', 'off')
        resp = _put(client, lambda c: c['devices'][0].update(gains='LNA:42'),
                    headers=INGRESS)
        assert resp.status_code == 403
        assert resp.json()['policy'] == 'off'

    def test_state_reports_not_editable(self, client: Any, monkeypatch: Any) -> None:
        monkeypatch.setenv('OP25_CONFIG_WRITE', 'off')
        assert client.get('/api/config/state').json()['editable'] is False


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


class TestConfigState:
    def test_reports_effective_base_and_overlay(self, client: Any) -> None:
        body = client.get('/api/config/state').json()
        assert body['effective']['devices'][0]['gains'] == 'LNA:40'
        assert body['base']['devices'][0]['gains'] == 'LNA:40'
        assert body['overlay'] == {}
        assert body['editable'] is True

    def test_secrets_are_redacted_everywhere(self, client: Any) -> None:
        # This endpoint is unauthenticated on the published port.
        body = client.get('/api/config/state').text
        assert 'a-real-secret' not in body
        assert cs.REDACTED in body

    def test_no_store_cache_header(self, client: Any) -> None:
        assert 'no-store' in client.get('/api/config/state').headers['cache-control']

    def test_503_when_no_config_is_loaded(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(ws, '_config', None)
        monkeypatch.setattr(ws, '_config_store', None)
        assert TestClient(ws.app).get('/api/config/state').status_code == 503


class TestConfigSchemaEndpoint:
    def test_defaults_to_the_loaded_protocol(self, client: Any) -> None:
        body = client.get('/api/config/schema').json()
        assert body['protocol'] == 'tk_p25.py'
        paths = {f['path'] for s in body['sections'] for f in s['fields']}
        assert 'trunking.chans[*].nac' in paths          # P25-only, and we are P25
        assert 'trunking.chans[*].bandplan' not in paths  # SmartNet-only

    def test_explicit_protocol_filter(self, client: Any) -> None:
        body = client.get('/api/config/schema?protocol=tk_smartnet.py').json()
        paths = {f['path'] for s in body['sections'] for f in s['fields']}
        assert 'trunking.chans[*].bandplan' in paths
        assert 'trunking.chans[*].nac' not in paths

    def test_live_paths_are_advertised(self, client: Any) -> None:
        body = client.get('/api/config/schema').json()
        assert 'devices[*].gains' in body['live_paths']


class TestTranscriptionSection:
    """Transcription is a section of its own, and a tab of its own."""

    @staticmethod
    def _section(client: Any, key: str) -> dict:
        body = client.get('/api/config/schema').json()
        return next(s for s in body['sections'] if s['key'] == key)

    def test_the_server_decides_which_sections_get_their_own_tab(
        self, client: Any
    ) -> None:
        # The React file does not name config fields, and it does not name tabs
        # either: a client that has not heard of this one still renders the
        # fields under Settings.
        body = client.get('/api/config/schema').json()
        assert body['standalone_sections'] == ['transcription']

    def test_the_scope_flag_is_offered(self, client: Any) -> None:
        field = next(f for f in self._section(client, 'transcription')['fields']
                     if f['path'] == 'terminal.home_assistant.talkgroup_scope')
        assert field['choices'] == ['all', 'focused', 'list']
        assert field['default'] == 'all'
        assert set(field['choice_labels']) == {'all', 'focused', 'list'}

    def test_transcription_fields_left_the_terminal_section(self, client: Any) -> None:
        # Otherwise they render twice: once under Settings, once under the tab.
        paths = {f['path'] for f in self._section(client, 'terminal')['fields']}
        assert not any(p.startswith('terminal.home_assistant.') for p in paths)

    def test_fields_that_default_to_on_say_so(self, client: Any) -> None:
        # A switch showing "off" for something that is on invites the user to
        # store an override that changes nothing.
        fields = {f['path']: f for f in self._section(client, 'transcription')['fields']}
        assert fields['terminal.call_recording']['default'] is True
        assert fields['terminal.home_assistant.filter_hallucinations']['default'] is True
        assert fields['terminal.home_assistant.enabled']['default'] is False

    def test_nothing_here_claims_to_be_live(self, client: Any) -> None:
        # HomeAssistantConfig is built once in start_call_capture. The live half
        # of this is the pinned talkgroup list, which is not config.
        fields = self._section(client, 'transcription')['fields']
        assert not [f['path'] for f in fields if f['live']]

    def test_the_scope_survives_a_round_trip_through_the_editor(
        self, client: Any
    ) -> None:
        resp = _put(client, lambda c: c.setdefault('terminal', {})
                    .setdefault('home_assistant', {})
                    .update(talkgroup_scope='focused'))
        assert resp.json()['ok'] is True
        assert resp.json()['needs_restart'] is True
        state = client.get('/api/config/state').json()
        assert (state['effective']['terminal']['home_assistant']['talkgroup_scope']
                == 'focused')


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


class TestPutConfig:
    def test_a_live_change_reports_applied_and_no_restart(self, client: Any) -> None:
        resp = _put(client, lambda c: c['devices'][0].update(gains='LNA:42'))
        body = resp.json()
        assert body['ok'] is True
        assert body['needs_restart'] is False
        assert body['applied'] == ['devices[sdr0].gains']

    def test_a_restart_required_change_says_so(self, client: Any) -> None:
        # Reporting this as applied is the failure that matters: the user would
        # trust a value the decoder is not running.
        resp = _put(client, lambda c: c['devices'][0].update(rate=1920000))
        body = resp.json()
        assert body['needs_restart'] is True
        assert [c['path'] for c in body['restart_required']] == ['devices[sdr0].rate']
        assert body['applied'] == []

    def test_a_mixed_change_reports_both_halves(self, client: Any) -> None:
        def mutate(c: dict) -> None:
            c['devices'][0].update(gains='LNA:42', rate=1920000)
        body = _put(client, mutate).json()
        assert body['applied'] == ['devices[sdr0].gains']
        assert body['needs_restart'] is True

    def test_only_the_delta_is_stored(self, client: Any) -> None:
        _put(client, lambda c: c['devices'][0].update(gains='LNA:42'))
        overlay = client.get('/api/config/state').json()['overlay']
        assert overlay == {'devices': [{'name': 'sdr0', 'gains': 'LNA:42'}]}

    def test_a_redacted_token_is_not_persisted(self, client: Any) -> None:
        # The client reads a redacted config, edits one field, and writes it back.
        _put(client, lambda c: c['terminal'].update(http_plot_interval=2.0))
        assert ws._config_store is not None
        assert cs.REDACTED not in json.dumps(ws._config_store.overlay())
        eff = ws._config_store.effective()
        assert eff['terminal']['home_assistant']['token'] == 'a-real-secret'

    def test_a_bare_config_body_is_accepted(self, client: Any) -> None:
        cfg = client.get('/api/config/state').json()['effective']
        cfg['devices'][0]['gains'] = 'LNA:42'
        assert client.put('/api/config', json=cfg).status_code == 200

    def test_invalid_json_is_400(self, client: Any) -> None:
        resp = client.put('/api/config', content=b'{not json',
                          headers={'Content-Type': 'application/json'})
        assert resp.status_code == 400

    def test_a_non_object_body_is_400(self, client: Any) -> None:
        assert client.put('/api/config', json=[1, 2]).status_code == 400

    def test_summary_and_source_are_recorded(self, client: Any) -> None:
        cfg = client.get('/api/config/state').json()['effective']
        cfg['devices'][0]['gains'] = 'LNA:42'
        client.put('/api/config', json={'config': cfg, 'summary': 'gain sweep step 3',
                                        'source': 'advanced-editor'})
        latest = client.get('/api/config/history').json()['versions'][0]
        assert latest['summary'] == 'gain sweep step 3'
        assert latest['source'] == 'advanced-editor'


class TestValidation:
    @pytest.mark.parametrize('mutate,expect', [
        (lambda c: c.update(devices=[]), 'devices must be a non-empty list'),
        (lambda c: c.update(channels=[]), 'channels must be a non-empty list'),
    ])
    def test_structural_problems_are_422(self, client: Any, mutate: Any,
                                        expect: str) -> None:
        resp = _put(client, mutate)
        assert resp.status_code == 422
        assert expect in resp.json()['problems']

    def test_a_channel_pointing_at_no_device_is_rejected(self, client: Any) -> None:
        resp = _put(client, lambda c: c['channels'][0].update(device='nope'))
        assert resp.status_code == 422
        assert any('matches no device' in p for p in resp.json()['problems'])

    def test_a_malformed_gain_string_is_rejected(self, client: Any) -> None:
        resp = _put(client, lambda c: c['devices'][0].update(gains='40'))
        assert resp.status_code == 422
        assert any('STAGE:value' in p for p in resp.json()['problems'])

    def test_duplicate_device_names_are_rejected(self, client: Any) -> None:
        # They would make device_overrides and channels[].device ambiguous.
        resp = _put(client, lambda c: c['devices'].append(dict(c['devices'][0])))
        assert resp.status_code == 422
        assert any('duplicate device name' in p for p in resp.json()['problems'])

    def test_a_rejected_write_changes_nothing(self, client: Any) -> None:
        _put(client, lambda c: c.update(devices=[]))
        assert client.get('/api/config/state').json()['overlay'] == {}


class TestHistoryEndpoints:
    def test_history_lists_newest_first(self, client: Any) -> None:
        _put(client, lambda c: c['devices'][0].update(gains='LNA:41'))
        _put(client, lambda c: c['devices'][0].update(gains='LNA:42'))
        versions = client.get('/api/config/history').json()['versions']
        assert len(versions) == 2
        assert versions[0]['diff'][0]['new'] == 'LNA:42'

    def test_history_redacts_secrets(self, client: Any) -> None:
        _put(client, lambda c: c['terminal']['home_assistant'].update(enabled=True))
        assert 'a-real-secret' not in client.get('/api/config/history').text

    def test_rollback_restores_an_earlier_version(self, client: Any) -> None:
        _put(client, lambda c: c['devices'][0].update(gains='LNA:41'))
        target = client.get('/api/config/history').json()['versions'][0]['id']
        _put(client, lambda c: c['devices'][0].update(gains='LNA:42'))
        resp = client.post('/api/config/rollback/%d' % target)
        assert resp.status_code == 200
        state = client.get('/api/config/state').json()
        assert state['effective']['devices'][0]['gains'] == 'LNA:41'

    def test_rollback_of_an_unknown_version_is_404(self, client: Any) -> None:
        assert client.post('/api/config/rollback/9999').status_code == 404

    def test_reset_returns_to_the_preset(self, client: Any) -> None:
        _put(client, lambda c: c['devices'][0].update(gains='LNA:42'))
        assert client.post('/api/config/reset').status_code == 200
        state = client.get('/api/config/state').json()
        assert state['overlay'] == {}
        assert state['effective']['devices'][0]['gains'] == 'LNA:40'

    def test_reset_is_itself_a_version(self, client: Any) -> None:
        # So it can be rolled back like any other change.
        _put(client, lambda c: c['devices'][0].update(gains='LNA:42'))
        client.post('/api/config/reset')
        assert client.get('/api/config/history').json()['versions'][0]['summary'] \
            == 'reset to preset'


class TestPresetDriftEndpoint:
    def test_drift_is_reported_after_the_preset_moves(self, client: Any,
                                                     monkeypatch: Any) -> None:
        _put(client, lambda c: c['devices'][0].update(gains='LNA:30'))
        newer = copy.deepcopy(BASE)
        newer['devices'][0]['gains'] = 'LNA:44'
        monkeypatch.setattr(ws, '_config', newer)
        ws._init_config_store()
        drift = client.get('/api/config/state').json()['preset_drift']
        assert drift == [{'path': 'devices[sdr0].gains',
                          'preset': 'LNA:44', 'override': 'LNA:30'}]


class TestExportEndpoint:
    @pytest.fixture(autouse=True)
    def _allow_tmp(self, tmp_path: Any, monkeypatch: Any) -> None:
        # The real guard allows the working directory (which is the data dir) plus
        # /share, /config and /data. Point it at tmp_path instead of chdir-ing.
        monkeypatch.setenv('OP25_EXPORT_ROOTS', str(tmp_path))

    def test_export_writes_a_full_config(self, client: Any, tmp_path: Any) -> None:
        _put(client, lambda c: c['devices'][0].update(gains='LNA:42'))
        out = tmp_path / 'exported.json'
        resp = client.post('/api/config/export', json={'path': str(out)})
        assert resp.status_code == 200, resp.text
        written = json.loads(out.read_text())
        assert written['devices'][0]['gains'] == 'LNA:42'
        assert written['devices'][0]['rate'] == 2400000

    def test_export_says_it_stops_tracking_the_preset(self, client: Any,
                                                     tmp_path: Any) -> None:
        resp = client.post('/api/config/export',
                           json={'path': str(tmp_path / 'e.json')})
        assert 'no longer tracks the preset' in resp.json()['note']

    def test_absolute_paths_outside_the_data_dirs_are_refused(self, client: Any) -> None:
        resp = client.post('/api/config/export', json={'path': '/etc/passwd'})
        assert resp.status_code == 400

    def test_traversal_out_of_an_allowed_root_is_refused(self, client: Any) -> None:
        resp = client.post('/api/config/export',
                           json={'path': '../../../../etc/op25-escape.json'})
        assert resp.status_code == 400


class _SupervisorResp:
    """What GET /addons/self/info answers, cut down to the field that matters."""

    def __init__(self, role: str) -> None:
        self._role = role

    def read(self) -> bytes:
        return json.dumps({'result': 'ok', 'data': {'hassio_role': self._role}}).encode()

    def __enter__(self) -> Any:
        return self

    def __exit__(self, *_a: Any) -> None:
        return None


class TestRestartEndpoint:
    """Restarting is how a stored-but-not-running field takes effect.

    Gated exactly like a write: "restart the scanner" is not something a stranger
    on the LAN should be able to do.
    """

    def test_gated_like_a_write(self, client: Any, monkeypatch: Any) -> None:
        monkeypatch.setenv('OP25_CONFIG_WRITE', 'ingress')
        assert client.post('/api/restart').status_code == 403
        # Reachable via ingress -- 501 here only because there is no Supervisor.
        assert client.post('/api/restart', headers=INGRESS).status_code != 403

    def test_501_when_not_an_addon(self, client: Any, monkeypatch: Any) -> None:
        # A standalone install has no Supervisor to ask, so say so rather than
        # failing in a way that looks like a permission problem.
        monkeypatch.delenv('SUPERVISOR_TOKEN', raising=False)
        resp = client.post('/api/restart')
        assert resp.status_code == 501
        assert 'add-on' in resp.json()['error']

    def test_supervisor_403_explains_the_missing_permission(
            self, client: Any, monkeypatch: Any) -> None:
        # The add-on needs hassio_api + hassio_role: manager; without them
        # Supervisor answers 403 and names nothing.
        import urllib.error
        monkeypatch.setenv('SUPERVISOR_TOKEN', 'x')

        def boom(*_a: Any, **_k: Any) -> Any:
            raise urllib.error.HTTPError('http://supervisor', 403, 'Forbidden', {}, None)

        monkeypatch.setattr('urllib.request.urlopen', boom)
        resp = client.post('/api/restart')
        assert resp.status_code == 502
        assert 'hassio_role' in resp.json()['detail']

    def test_a_dropped_connection_counts_as_success(self, client: Any,
                                                   monkeypatch: Any) -> None:
        # The container going away mid-request IS the restart working.
        monkeypatch.setenv('SUPERVISOR_TOKEN', 'x')

        def boom(*_a: Any, **_k: Any) -> Any:
            raise OSError('connection reset')

        monkeypatch.setattr('urllib.request.urlopen', boom)
        assert client.post('/api/restart').json()['ok'] is True

    def test_the_restart_is_asked_for_after_the_response_not_during_it(
            self, client: Any, monkeypatch: Any) -> None:
        """Holding the response open across the restart is what produced a 502.

        Supervisor kills the container to carry the restart out, so a reply still
        in flight is never delivered and ingress answers the browser 502 -- a
        successful restart reported as a failure, which the user answers by
        restarting again. The POST therefore has to happen after the response.
        """
        monkeypatch.setenv('SUPERVISOR_TOKEN', 'x')
        calls: list[tuple[str, str]] = []

        def record(req: Any, *_a: Any, **_k: Any) -> Any:
            calls.append((req.get_method(), req.full_url))
            return _SupervisorResp('manager')

        monkeypatch.setattr('urllib.request.urlopen', record)
        resp = client.post('/api/restart')

        assert resp.status_code == 200
        assert resp.json()['restarting'] is True
        # TestClient runs background tasks after the response, so by here both
        # have happened -- but in this order, and the GET is the preflight.
        assert calls == [
            ('GET', 'http://supervisor/addons/self/info'),
            ('POST', 'http://supervisor/addons/self/restart'),
        ]

    def test_an_unreachable_supervisor_does_not_block_the_restart(
            self, client: Any, monkeypatch: Any) -> None:
        """Only an explicit refusal counts. A slow or unreachable Supervisor must
        not veto a restart that would probably have worked -- the fallback is the
        add-on page, which does exactly the same thing."""
        monkeypatch.setenv('SUPERVISOR_TOKEN', 'x')

        def boom(*_a: Any, **_k: Any) -> Any:
            raise OSError('name resolution failed')

        monkeypatch.setattr('urllib.request.urlopen', boom)
        assert client.post('/api/restart').status_code == 200

    def test_the_wrong_role_is_caught_before_the_response_goes_out(
            self, client: Any, monkeypatch: Any) -> None:
        """hassio_api without hassio_role: manager answers the preflight GET
        happily and refuses the POST — which now runs after the response, where
        nothing can report it. So the role itself is the precondition checked."""
        monkeypatch.setenv('SUPERVISOR_TOKEN', 'x')
        posted: list[str] = []

        def answer(req: Any, *_a: Any, **_k: Any) -> Any:
            if req.get_method() == 'POST':
                posted.append(req.full_url)
            return _SupervisorResp('default')

        monkeypatch.setattr('urllib.request.urlopen', answer)
        resp = client.post('/api/restart')
        assert resp.status_code == 502
        assert 'hassio_role' in resp.json()['detail']
        assert 'default' in resp.json()['detail']       # names what we are running as
        assert posted == []                              # and never tried

    def test_an_unrecognised_role_field_does_not_block_the_restart(
            self, client: Any, monkeypatch: Any) -> None:
        # A Supervisor that words this differently must not make the button dead.
        monkeypatch.setenv('SUPERVISOR_TOKEN', 'x')
        monkeypatch.setattr('urllib.request.urlopen',
                            lambda *_a, **_k: _SupervisorResp(''))
        assert client.post('/api/restart').status_code == 200

    def test_a_supervisor_500_is_not_read_as_a_permission_problem(
            self, client: Any, monkeypatch: Any) -> None:
        import urllib.error
        monkeypatch.setenv('SUPERVISOR_TOKEN', 'x')

        def boom(*_a: Any, **_k: Any) -> Any:
            raise urllib.error.HTTPError('http://supervisor', 500, 'Boom', {}, None)

        monkeypatch.setattr('urllib.request.urlopen', boom)
        assert client.post('/api/restart').status_code == 200


class TestFloatPrecisionOverTheApi:
    def test_a_long_float_is_trimmed_on_save(self, client: Any) -> None:
        # Whatever the client sends -- the form, the raw editor, or Save tuning --
        # the stored value is clean.
        _put(client, lambda c: c['devices'][0].update(ppm=2.3749999999999996))
        assert ws._config_store is not None
        assert ws._config_store.effective()['devices'][0]['ppm'] == 2.375

    def test_the_diff_reports_the_trimmed_value(self, client: Any) -> None:
        # Or the history would show digits the config does not contain.
        resp = _put(client, lambda c: c['devices'][0].update(ppm=1.23456789))
        change = next(c for c in resp.json()['live'] if c['path'].endswith('.ppm'))
        assert change['new'] == 1.235

    def test_untrimmed_fields_are_unchanged(self, client: Any) -> None:
        _put(client, lambda c: c['devices'][0].update(frequency=859262501))
        assert ws._config_store is not None
        assert ws._config_store.effective()['devices'][0]['frequency'] == 859262501

    def test_schema_advertises_precision(self, client: Any) -> None:
        body = client.get('/api/config/schema').json()
        ppm = next(f for s in body['sections'] for f in s['fields']
                   if f['path'] == 'devices[*].ppm')
        assert ppm['precision'] == 3


class TestDriftDisplayPrecision:
    def test_drift_values_are_trimmed(self, client: Any, monkeypatch: Any) -> None:
        # An overlay written before rounding existed still holds the long float;
        # the alert saying the preset moved is a bad place to show 16 digits.
        _put(client, lambda c: c['devices'][0].update(gains='LNA:30'))
        assert ws._config_store is not None
        ws._config_store._overlay['devices'][0]['ppm'] = 2.3749999999999996

        newer = copy.deepcopy(BASE)
        newer['devices'][0]['gains'] = 'LNA:44'
        newer['devices'][0]['ppm'] = 1.1111111111
        monkeypatch.setattr(ws, '_config', newer)
        store = ws._config_store
        monkeypatch.setattr(store, 'base', ws.config_store.strip_doc_keys(newer))

        drift = {d['path']: d for d in client.get('/api/config/state').json()['preset_drift']}
        assert drift['devices[sdr0].ppm']['override'] == 2.375
        assert drift['devices[sdr0].ppm']['preset'] == 1.111

    def test_fields_without_precision_are_left_alone(self, client: Any,
                                                     monkeypatch: Any) -> None:
        _put(client, lambda c: c['devices'][0].update(frequency=859262501))
        newer = copy.deepcopy(BASE)
        newer['devices'][0]['frequency'] = 859262502
        monkeypatch.setattr(ws, '_config', newer)
        monkeypatch.setattr(ws._config_store, 'base',
                            ws.config_store.strip_doc_keys(newer))
        drift = {d['path']: d for d in client.get('/api/config/state').json()['preset_drift']}
        assert drift['devices[sdr0].frequency']['override'] == 859262501
