"""
Scanner state that belongs to the receiver rather than to a browser.

Pins were per browser *and per origin*, so the same scanner reached through Home
Assistant ingress and through port 8099 kept two separate sets; holds lived only
in the decoder's memory and were lost on every restart -- which is most annoying
precisely when the restart was to apply a setting the user just changed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import ui_state as us
import websocket_server as ws


@pytest.fixture()
def store(tmp_path: Any) -> us.UiState:
    return us.UiState(str(tmp_path / 'ui.json'))


class TestPersistence:
    def test_a_merge_survives_a_reopen(self, tmp_path: Any) -> None:
        path = str(tmp_path / 'ui.json')
        us.UiState(path).merge({'focused_talkgroups': [3, 1, 2]})
        assert us.UiState(path).get('focused_talkgroups') == [1, 2, 3]

    def test_merge_leaves_other_keys_alone(self, store: us.UiState) -> None:
        # A phone that only knows about pins must not wipe a hold set elsewhere.
        store.merge({'holds': {'ch': 100}})
        store.merge({'focused_talkgroups': [7]})
        assert store.get('holds') == {'ch': 100}
        assert store.get('focused_talkgroups') == [7]

    def test_unknown_keys_are_rejected_not_stored(self, store: us.UiState) -> None:
        # The endpoint is unauthenticated, so this must not become a place to
        # park arbitrary data on someone's SD card.
        rejected = store.merge({'nonsense': 'x', 'focus_only': True})
        assert 'nonsense' in rejected
        assert 'nonsense' not in store.all()
        assert store.get('focus_only') is True

    def test_a_bad_value_does_not_lose_the_good_ones(self, store: us.UiState) -> None:
        rejected = store.merge({'holds': 'not a dict', 'focus_only': True})
        assert 'holds' in rejected
        assert store.get('focus_only') is True

    def test_a_corrupt_file_degrades_to_empty(self, tmp_path: Any) -> None:
        path = tmp_path / 'ui.json'
        path.write_text('{not json')
        store = us.UiState(str(path))
        assert store.all() == {}
        store.merge({'focus_only': True})     # still usable

    def test_one_bad_key_on_disk_does_not_lose_the_rest(self, tmp_path: Any) -> None:
        path = tmp_path / 'ui.json'
        path.write_text(json.dumps({'focused_talkgroups': 'nope', 'focus_only': True}))
        store = us.UiState(str(path))
        assert store.get('focus_only') is True

    def test_no_path_means_memory_only(self) -> None:
        store = us.UiState(None)
        store.merge({'focus_only': True})
        assert store.get('focus_only') is True
        assert store.persistent is False


class TestValueCleaning:
    def test_talkgroups_are_deduped_sorted_and_bounded(self, store: us.UiState) -> None:
        store.merge({'focused_talkgroups': [5, 5, 2, 0, -1, 99999, 3.0, True]})
        # 0 and negatives are not talkgroups; 99999 is past the protocol max;
        # True is a bool, which is an int subclass and must not become tgid 1.
        assert store.get('focused_talkgroups') == [2, 3, 5]

    def test_the_pinned_list_is_capped(self, store: us.UiState, monkeypatch: Any) -> None:
        monkeypatch.setattr(us, 'MAX_FOCUSED', 10)
        store.merge({'focused_talkgroups': list(range(1, 100))})
        assert len(store.get('focused_talkgroups')) == 10

    def test_a_zero_hold_is_dropped_not_stored(self, store: us.UiState) -> None:
        # 0 is the decoder's own "release the hold"; storing it would re-apply a
        # hold the user deliberately let go.
        store.merge({'holds': {'a': 100, 'b': 0}})
        assert store.get('holds') == {'a': 100}


class TestTalkgroupFilters:
    """The browser's saved search patterns. A union, so order is the user's."""

    def test_patterns_keep_their_order_and_kind(self, store: us.UiState) -> None:
        store.merge({'talkgroup_filters': [
            {'kind': 'contains', 'text': 'W Cola 1'},
            {'kind': 'wildcard', 'text': 'RCHP*'},
        ]})
        assert store.get('talkgroup_filters') == [
            {'kind': 'contains', 'text': 'W Cola 1'},
            {'kind': 'wildcard', 'text': 'RCHP*'},
        ]

    def test_an_unknown_kind_degrades_to_contains(self, store: us.UiState) -> None:
        # The text is what the user typed and is worth keeping; 'contains' is
        # the reading that cannot fail to compile.
        store.merge({'talkgroup_filters': [{'kind': 'fuzzy', 'text': 'FIRE'}]})
        assert store.get('talkgroup_filters') == [{'kind': 'contains', 'text': 'FIRE'}]

    def test_blank_and_duplicate_patterns_are_dropped(self, store: us.UiState) -> None:
        store.merge({'talkgroup_filters': [
            {'kind': 'contains', 'text': 'FIRE'},
            {'kind': 'contains', 'text': '  '},
            {'kind': 'contains', 'text': 'FIRE'},
            {'kind': 'regex', 'text': 'FIRE'},      # same text, different rule
        ]})
        assert store.get('talkgroup_filters') == [
            {'kind': 'contains', 'text': 'FIRE'},
            {'kind': 'regex', 'text': 'FIRE'},
        ]

    def test_one_malformed_entry_does_not_lose_the_others(self, store: us.UiState) -> None:
        store.merge({'talkgroup_filters': ['not an object', {'text': 'EMS'}]})
        assert store.get('talkgroup_filters') == [{'kind': 'contains', 'text': 'EMS'}]

    def test_the_list_and_each_pattern_are_capped(self, store: us.UiState,
                                                  monkeypatch: Any) -> None:
        # Unauthenticated endpoint, possibly an SD card.
        monkeypatch.setattr(us, 'MAX_FILTERS', 3)
        monkeypatch.setattr(us, 'MAX_FILTER_TEXT', 4)
        # Distinct after truncation: two patterns that truncate to the same text
        # really are one pattern, and dedupe collapsing them is correct.
        store.merge({'talkgroup_filters':
                     [{'kind': 'contains', 'text': 'p%d-long-tail' % i} for i in range(9)]})
        stored = store.get('talkgroup_filters')
        assert len(stored) == 3
        assert all(len(p['text']) <= 4 for p in stored)

    def test_a_non_list_is_rejected_whole(self, store: us.UiState) -> None:
        rejected = store.merge({'talkgroup_filters': 'FIRE', 'focus_only': True})
        assert 'talkgroup_filters' in rejected
        assert store.get('focus_only') is True

    def test_they_are_counted_in_stats(self, store: us.UiState) -> None:
        store.merge({'talkgroup_filters': [{'kind': 'contains', 'text': 'FIRE'}]})
        assert store.stats()['filter_count'] == 1


class TestSetHold:
    def test_setting_and_releasing(self, store: us.UiState) -> None:
        store.set_hold('Palmetto 800', 24671)
        assert store.get('holds') == {'Palmetto 800': 24671}
        store.set_hold('Palmetto 800', 0)
        assert store.get('holds') == {}

    def test_holds_are_keyed_by_channel(self, store: us.UiState) -> None:
        store.set_hold('a', 1)
        store.set_hold('b', 2)
        assert store.get('holds') == {'a': 1, 'b': 2}

    def test_stats_has_no_holds_key(self, store: us.UiState) -> None:
        # /api/ui-state spreads stats() beside the document; a same-named counter
        # would replace the map with an integer. Same trap as tg_metadata and
        # config_store.
        store.set_hold('a', 1)
        assert 'holds' not in store.stats()
        assert store.stats()['hold_count'] == 1


class TestPathResolution:
    def test_env_wins(self, monkeypatch: Any) -> None:
        monkeypatch.setenv('OP25_UI_STATE', '/tmp/x.json')
        assert us.state_path({'terminal': {'ui_state': 'ignored'}}) == '/tmp/x.json'

    def test_empty_env_disables(self, monkeypatch: Any) -> None:
        monkeypatch.setenv('OP25_UI_STATE', '')
        assert us.state_path(None) is None

    def test_default_is_in_the_cwd(self, monkeypatch: Any) -> None:
        monkeypatch.delenv('OP25_UI_STATE', raising=False)
        assert us.state_path({}) == 'op25_ui_state.json'


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path: Any, monkeypatch: Any) -> Any:
    monkeypatch.setattr(ws, '_config', {'terminal': {}})
    monkeypatch.setenv('OP25_UI_STATE', str(tmp_path / 'ui.json'))
    ws._init_ui_state()
    yield TestClient(ws.app)
    monkeypatch.setattr(ws, '_ui_state', None)


class TestApi:
    def test_round_trip(self, client: Any) -> None:
        client.put('/api/ui-state', json={'state': {'focused_talkgroups': [9, 4]}})
        body = client.get('/api/ui-state').json()
        assert body['state']['focused_talkgroups'] == [4, 9]
        assert body['persistent'] is True

    def test_a_bare_body_is_accepted(self, client: Any) -> None:
        assert client.put('/api/ui-state', json={'focus_only': True}).status_code == 200
        assert client.get('/api/ui-state').json()['state']['focus_only'] is True

    def test_rejected_keys_are_reported(self, client: Any) -> None:
        body = client.put('/api/ui-state', json={'state': {'bogus': 1}}).json()
        assert 'bogus' in body['rejected']

    def test_invalid_json_is_400(self, client: Any) -> None:
        resp = client.put('/api/ui-state', content=b'{nope',
                          headers={'Content-Type': 'application/json'})
        assert resp.status_code == 400

    def test_reads_are_not_gated(self, client: Any, monkeypatch: Any) -> None:
        # Holding a talkgroup is already unauthenticated over the WebSocket, so
        # gating the record of one would buy nothing.
        monkeypatch.setenv('OP25_CONFIG_WRITE', 'ingress')
        assert client.get('/api/ui-state').status_code == 200
        assert client.put('/api/ui-state', json={'focus_only': True}).status_code == 200


class TestHoldRestore:
    def test_a_hold_command_is_remembered_by_channel_name(self, client: Any,
                                                          monkeypatch: Any) -> None:
        monkeypatch.setattr(ws, '_last_channels', {'0': {'name': 'Palmetto 800'}})
        ws._remember_hold(0, 24671)
        assert ws._ui_state is not None
        assert ws._ui_state.get('holds') == {'Palmetto 800': 24671}

    def test_releasing_clears_it(self, client: Any, monkeypatch: Any) -> None:
        monkeypatch.setattr(ws, '_last_channels', {'0': {'name': 'ch'}})
        ws._remember_hold(0, 100)
        ws._remember_hold(0, 0)
        assert ws._ui_state.get('holds') == {}

    def test_restore_sends_the_hold_once_the_decoder_reports_channels(
            self, client: Any, monkeypatch: Any) -> None:
        sent: list[dict] = []
        monkeypatch.setattr(ws, '_send_upstream', lambda p: sent.append(p) or True)
        monkeypatch.setattr(ws, '_holds_applied', set())
        ws._ui_state.merge({'holds': {'ch': 24671}})
        ws._restore_holds({'0': {'name': 'ch', 'hold_tgid': 0}})
        assert sent == [{'command': 'hold', 'arg1': 24671.0, 'arg2': 0.0}]

    def test_restore_happens_only_once_per_decoder(self, client: Any,
                                                   monkeypatch: Any) -> None:
        # channel_update arrives once a second; re-sending would fight a user who
        # released the hold.
        sent: list[dict] = []
        monkeypatch.setattr(ws, '_send_upstream', lambda p: sent.append(p) or True)
        monkeypatch.setattr(ws, '_holds_applied', set())
        ws._ui_state.merge({'holds': {'ch': 5}})
        for _ in range(4):
            ws._restore_holds({'0': {'name': 'ch', 'hold_tgid': 0}})
        assert len(sent) == 1

    def test_an_existing_hold_is_not_disturbed(self, client: Any,
                                              monkeypatch: Any) -> None:
        sent: list[dict] = []
        monkeypatch.setattr(ws, '_send_upstream', lambda p: sent.append(p) or True)
        monkeypatch.setattr(ws, '_holds_applied', set())
        ws._ui_state.merge({'holds': {'ch': 5}})
        ws._restore_holds({'0': {'name': 'ch', 'hold_tgid': 5}})
        assert sent == []

    def test_nothing_stored_means_nothing_sent(self, client: Any,
                                              monkeypatch: Any) -> None:
        sent: list[dict] = []
        monkeypatch.setattr(ws, '_send_upstream', lambda p: sent.append(p) or True)
        monkeypatch.setattr(ws, '_holds_applied', set())
        ws._restore_holds({'0': {'name': 'ch', 'hold_tgid': 0}})
        assert sent == []


class TestFocusedTalkgroupsForTranscription:
    """The pinned list is what `talkgroup_scope: focused` transcribes."""

    def test_the_pins_are_read_from_the_store(self, client: Any) -> None:
        client.put('/api/ui-state', json={'state': {'focused_talkgroups': [9, 4]}})
        assert ws._focused_talkgroups() == [4, 9]

    def test_no_store_means_no_restriction(self, monkeypatch: Any) -> None:
        # start_call_capture can run before _init_ui_state, and an empty list is
        # "everything" rather than "nothing" -- see ha_bridge.wanted_talkgroups.
        monkeypatch.setattr(ws, '_ui_state', None)
        assert ws._focused_talkgroups() == []

    def test_the_bridge_is_wired_to_the_live_pins(self, client: Any,
                                                  monkeypatch: Any) -> None:
        """The wiring, not just the function: a bridge built with no callback
        would filter nothing and look identical from /api/ha/status."""
        monkeypatch.setattr(ws, '_ha_bridge', None)
        monkeypatch.setattr(ws, '_call_capture', None)
        ws.start_call_capture({'terminal': {'home_assistant': {
            'url': 'http://ha.local:8123', 'token': 't',
            'talkgroup_scope': 'focused',
        }}})
        try:
            client.put('/api/ui-state', json={'state': {'focused_talkgroups': [4]}})
            assert ws._ha_bridge.wanted_talkgroups() == {4}
        finally:
            ws.stop_call_capture()
