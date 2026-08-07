"""
Editable configuration: preset base + user overlay + version history.

The whole design rests on the overlay holding *only deltas*, because that is what
lets a preset keep receiving fixes while the user still edits things. Most of
these cases are about that invariant and the ways it can quietly break.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any

import pytest

import config_schema
import config_store as cs


BASE: dict[str, Any] = {
    'devices': [{'name': 'sdr0', 'args': 'rtl', 'gains': 'LNA:40',
                 'rate': 2400000, 'ppm': 0.0, 'frequency': 859262500}],
    'channels': [{'name': 'Palmetto 800', 'device': 'sdr0', 'if_rate': 24000,
                  'symbol_rate': 4800, 'demod_type': 'cqpsk'}],
    'trunking': {'module': 'tk_p25.py',
                 'chans': [{'sysname': 'P800', 'nac': '0x1D1',
                            'control_channel_list': '859.26250'}]},
    'terminal': {'http_plot_interval': 1.0,
                 'home_assistant': {'enabled': False, 'language': 'en'}},
}


@pytest.fixture()
def store(tmp_path: Any) -> cs.ConfigStore:
    return cs.ConfigStore(copy.deepcopy(BASE),
                          overlay_file=str(tmp_path / 'overlay.json'),
                          history_file=str(tmp_path / 'history.sqlite'),
                          base_id='preset:palmetto800')


# ---------------------------------------------------------------------------
# Merge primitives
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_effective_never_aliases_the_base(self) -> None:
        """The bug this replaces: dict(base) is a shallow copy.

        effective() handed out references into the preset, so a caller editing
        the returned config rewrote the base -- after which the overlay looked
        empty and the diff looked empty, because the "before" had already moved.
        """
        base = copy.deepcopy(BASE)
        store = cs.ConfigStore(base)
        eff = store.effective()
        eff['devices'][0]['gains'] = 'MUTATED'
        eff['trunking']['chans'][0]['nac'] = 'MUTATED'
        assert store.base['devices'][0]['gains'] == 'LNA:40'
        assert store.base['trunking']['chans'][0]['nac'] == '0x1D1'

    def test_lists_of_named_objects_merge_by_name(self) -> None:
        # jq's `*` replaces arrays, which would force an overlay to restate a
        # whole device to change one field -- and then a preset fix to another
        # field of it could never arrive.
        merged = cs.deep_merge(
            {'devices': [{'name': 'a', 'gains': 'LNA:1', 'rate': 10},
                         {'name': 'b', 'gains': 'LNA:2'}]},
            {'devices': [{'name': 'b', 'gains': 'LNA:9'}]})
        by_name = {d['name']: d for d in merged['devices']}
        assert by_name['b']['gains'] == 'LNA:9'
        assert by_name['a']['gains'] == 'LNA:1'
        assert by_name['a']['rate'] == 10

    def test_chans_merge_by_sysname(self) -> None:
        merged = cs.deep_merge(
            {'chans': [{'sysname': 'X', 'nac': '0x1', 'crypt_behavior': 2}]},
            {'chans': [{'sysname': 'X', 'nac': '0x2'}]})
        assert merged['chans'][0] == {'sysname': 'X', 'nac': '0x2',
                                      'crypt_behavior': 2}

    def test_unnamed_lists_are_replaced(self) -> None:
        # audio_ports and keywords have no identity field; element-wise merging
        # would make removing an entry impossible.
        assert cs.deep_merge({'p': [1, 2, 3]}, {'p': [9]}) == {'p': [9]}

    def test_new_list_entries_are_appended(self) -> None:
        merged = cs.deep_merge({'devices': [{'name': 'a'}]},
                               {'devices': [{'name': 'b', 'rate': 1}]})
        assert [d['name'] for d in merged['devices']] == ['a', 'b']


class TestPruneOverlay:
    def test_values_equal_to_the_base_are_dropped(self) -> None:
        # Or a value that merely matches today's preset would pin itself and
        # stop tracking a future change to it.
        pruned = cs.prune_overlay(BASE, copy.deepcopy(BASE))
        assert pruned is None

    def test_only_the_changed_field_survives(self) -> None:
        proposed = copy.deepcopy(BASE)
        proposed['devices'][0]['gains'] = 'LNA:42'
        pruned = cs.prune_overlay(BASE, proposed)
        assert pruned == {'devices': [{'name': 'sdr0', 'gains': 'LNA:42'}]}

    def test_identity_field_is_carried_so_the_merge_can_find_it(self) -> None:
        proposed = copy.deepcopy(BASE)
        proposed['trunking']['chans'][0]['nac'] = '0x2AA'
        pruned = cs.prune_overlay(BASE, proposed)
        assert pruned['trunking']['chans'][0]['sysname'] == 'P800'

    def test_new_keys_are_kept(self) -> None:
        proposed = copy.deepcopy(BASE)
        proposed['devices'][0]['offset'] = 1200
        assert cs.prune_overlay(BASE, proposed) == {
            'devices': [{'name': 'sdr0', 'offset': 1200}]}


class TestFlattenAndDiff:
    def test_lists_are_keyed_by_identity_not_position(self) -> None:
        # So a diff stays readable, and stays correct when an entry is inserted
        # ahead of the one that changed.
        flat = cs.flatten(BASE)
        assert 'devices[sdr0].gains' in flat
        assert 'trunking.chans[P800].nac' in flat

    def test_diff_reports_change_add_and_remove(self) -> None:
        after = copy.deepcopy(BASE)
        after['devices'][0]['gains'] = 'LNA:42'
        after['devices'][0]['offset'] = 5
        del after['terminal']['home_assistant']['language']
        ops = {c['path']: c['op'] for c in cs.diff_fields(BASE, after)}
        assert ops['devices[sdr0].gains'] == 'change'
        assert ops['devices[sdr0].offset'] == 'add'
        assert ops['terminal.home_assistant.language'] == 'remove'

    def test_identical_structures_diff_empty(self) -> None:
        assert cs.diff_fields(BASE, copy.deepcopy(BASE)) == []


class TestUnredact:
    def test_a_masked_secret_means_unchanged(self) -> None:
        # A read-modify-write from the browser would otherwise persist the mask
        # as the token, and surface later as a Home Assistant 401.
        base = {'terminal': {'home_assistant': {'token': 'real', 'language': 'en'}}}
        proposed = {'terminal': {'home_assistant': {'token': cs.REDACTED,
                                                    'language': 'en-US'}}}
        out = cs.unredact(proposed, base)
        assert out['terminal']['home_assistant']['token'] == 'real'
        assert out['terminal']['home_assistant']['language'] == 'en-US'

    def test_a_real_new_secret_is_kept(self) -> None:
        base = {'terminal': {'home_assistant': {'token': 'old'}}}
        out = cs.unredact({'terminal': {'home_assistant': {'token': 'new'}}}, base)
        assert out['terminal']['home_assistant']['token'] == 'new'

    def test_save_never_persists_the_mask(self, tmp_path: Any) -> None:
        base = copy.deepcopy(BASE)
        base['terminal']['home_assistant']['token'] = 'real-secret'
        store = cs.ConfigStore(base, overlay_file=str(tmp_path / 'o.json'))
        proposed = store.effective()
        proposed['terminal']['home_assistant']['token'] = cs.REDACTED
        proposed['terminal']['home_assistant']['enabled'] = True
        store.save(proposed)
        assert cs.REDACTED not in json.dumps(store.overlay())
        assert store.effective()['terminal']['home_assistant']['token'] == 'real-secret'


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


class TestSaveAndCompose:
    def test_overlay_holds_only_deltas(self, store: cs.ConfigStore) -> None:
        eff = store.effective()
        eff['devices'][0]['gains'] = 'LNA:42'
        store.save(eff)
        assert store.overlay() == {'devices': [{'name': 'sdr0', 'gains': 'LNA:42'}]}

    def test_unoverridden_fields_track_a_newer_preset(self, tmp_path: Any) -> None:
        """The entire point of the overlay model."""
        overlay = str(tmp_path / 'o.json')
        store = cs.ConfigStore(copy.deepcopy(BASE), overlay_file=overlay)
        eff = store.effective()
        eff['devices'][0]['gains'] = 'LNA:42'
        store.save(eff)

        newer = copy.deepcopy(BASE)
        newer['devices'][0]['rate'] = 1920000        # a preset fix
        reopened = cs.ConfigStore(newer, overlay_file=overlay)
        assert reopened.effective()['devices'][0]['rate'] == 1920000   # arrived
        assert reopened.effective()['devices'][0]['gains'] == 'LNA:42'  # kept

    def test_setting_a_field_back_to_the_preset_stops_overriding_it(
            self, store: cs.ConfigStore) -> None:
        eff = store.effective()
        eff['devices'][0]['gains'] = 'LNA:42'
        store.save(eff)
        back = store.effective()
        back['devices'][0]['gains'] = 'LNA:40'
        store.save(back)
        assert store.overlay() == {}

    def test_overlay_survives_a_reopen(self, tmp_path: Any) -> None:
        overlay = str(tmp_path / 'o.json')
        first = cs.ConfigStore(copy.deepcopy(BASE), overlay_file=overlay)
        eff = first.effective()
        eff['terminal']['http_plot_interval'] = 5.0
        first.save(eff)
        second = cs.ConfigStore(copy.deepcopy(BASE), overlay_file=overlay)
        assert second.effective()['terminal']['http_plot_interval'] == 5.0

    def test_doc_keys_never_reach_the_overlay(self, tmp_path: Any) -> None:
        base = copy.deepcopy(BASE)
        base['#note'] = 'documentation'
        store = cs.ConfigStore(base, overlay_file=str(tmp_path / 'o.json'))
        assert '#note' not in store.base
        eff = store.effective()
        eff['#other'] = 'more prose'
        store.save(eff)
        assert store.overlay() == {}

    def test_save_without_an_overlay_path_raises(self) -> None:
        store = cs.ConfigStore(copy.deepcopy(BASE))
        assert not store.editable
        with pytest.raises(RuntimeError):
            store.save({'devices': []})

    def test_a_failed_write_leaves_memory_matching_disk(self, tmp_path: Any) -> None:
        # A half-applied save is worse than a rejected one: the decoder would be
        # told about a change that is not on disk.
        store = cs.ConfigStore(copy.deepcopy(BASE),
                               overlay_file=str(tmp_path / 'nope' / 'o.json'))
        os.makedirs(tmp_path / 'nope', exist_ok=True)
        os.chmod(tmp_path / 'nope', 0o500)
        try:
            eff = store.effective()
            eff['devices'][0]['gains'] = 'LNA:42'
            with pytest.raises(OSError):
                store.save(eff)
            assert store.overlay() == {}
        finally:
            os.chmod(tmp_path / 'nope', 0o700)

    def test_a_corrupt_overlay_is_ignored_not_fatal(self, tmp_path: Any) -> None:
        # The preset alone is a working scanner; refusing to start because an
        # *override* is malformed would be the worse failure.
        path = tmp_path / 'o.json'
        path.write_text('{not json')
        store = cs.ConfigStore(copy.deepcopy(BASE), overlay_file=str(path))
        assert store.overlay() == {}
        assert store.effective()['devices'][0]['gains'] == 'LNA:40'

    def test_a_non_object_overlay_is_ignored(self, tmp_path: Any) -> None:
        path = tmp_path / 'o.json'
        path.write_text('[1, 2, 3]')
        assert cs.ConfigStore(copy.deepcopy(BASE), overlay_file=str(path)).overlay() == {}


class TestPresetDrift:
    def test_reports_only_fields_an_override_is_masking(self, tmp_path: Any) -> None:
        overlay = str(tmp_path / 'o.json')
        store = cs.ConfigStore(copy.deepcopy(BASE), overlay_file=overlay)
        eff = store.effective()
        eff['devices'][0]['gains'] = 'LNA:30'
        store.save(eff)

        newer = copy.deepcopy(BASE)
        newer['devices'][0]['gains'] = 'LNA:44'      # preset moved
        newer['devices'][0]['rate'] = 1920000        # also moved, not overridden
        reopened = cs.ConfigStore(newer, overlay_file=overlay)
        drift = reopened.preset_drift()
        assert drift == [{'path': 'devices[sdr0].gains',
                          'preset': 'LNA:44', 'override': 'LNA:30'}]

    def test_no_overrides_means_no_drift(self, store: cs.ConfigStore) -> None:
        assert store.preset_drift() == []


class TestHistoryAndRollback:
    def test_every_save_records_a_version(self, store: cs.ConfigStore) -> None:
        eff = store.effective()
        eff['devices'][0]['gains'] = 'LNA:42'
        store.save(eff, summary='sweep')
        assert [v['summary'] for v in store.history()] == ['sweep']

    def test_version_carries_the_field_diff(self, store: cs.ConfigStore) -> None:
        eff = store.effective()
        eff['devices'][0]['ppm'] = 1.5
        version = store.save(eff)
        assert version['diff'] == [{'path': 'devices[sdr0].ppm', 'op': 'change',
                                    'old': 0.0, 'new': 1.5}]

    def test_summary_is_generated_when_not_given(self, store: cs.ConfigStore) -> None:
        eff = store.effective()
        eff['devices'][0]['gains'] = 'LNA:42'
        assert 'LNA:40 -> LNA:42' in store.save(eff)['summary']

    def test_rollback_restores_the_overlay_of_that_version(
            self, store: cs.ConfigStore) -> None:
        eff = store.effective()
        eff['devices'][0]['gains'] = 'LNA:42'
        target = store.save(eff, summary='wanted')['id']
        store.reset_to_preset()
        assert store.effective()['devices'][0]['gains'] == 'LNA:40'
        store.rollback(target)
        assert store.effective()['devices'][0]['gains'] == 'LNA:42'

    def test_rollback_replays_intent_onto_the_current_preset(
            self, tmp_path: Any) -> None:
        """Restoring an overlay, not a whole config, is what makes this exact.

        Otherwise a rollback would reinstate the old preset's values too, and
        silently undo a fix the user never chose to undo.
        """
        overlay = str(tmp_path / 'o.json')
        history = str(tmp_path / 'h.sqlite')
        store = cs.ConfigStore(copy.deepcopy(BASE), overlay_file=overlay,
                               history_file=history)
        eff = store.effective()
        eff['devices'][0]['gains'] = 'LNA:42'
        target = store.save(eff)['id']
        store.reset_to_preset()

        newer = copy.deepcopy(BASE)
        newer['devices'][0]['rate'] = 1920000
        reopened = cs.ConfigStore(newer, overlay_file=overlay, history_file=history)
        reopened.rollback(target)
        assert reopened.effective()['devices'][0]['gains'] == 'LNA:42'
        assert reopened.effective()['devices'][0]['rate'] == 1920000

    def test_rollback_of_an_unknown_version_raises(self, store: cs.ConfigStore) -> None:
        with pytest.raises(KeyError):
            store.rollback(9999)

    def test_reset_clears_every_override(self, store: cs.ConfigStore) -> None:
        eff = store.effective()
        eff['devices'][0]['gains'] = 'LNA:42'
        eff['terminal']['http_plot_interval'] = 9.0
        store.save(eff)
        store.reset_to_preset()
        assert store.overlay() == {}
        assert store.effective() == store.base

    def test_history_is_bounded(self, tmp_path: Any, monkeypatch: Any) -> None:
        monkeypatch.setattr(cs, 'MAX_VERSIONS', 3)
        store = cs.ConfigStore(copy.deepcopy(BASE),
                               overlay_file=str(tmp_path / 'o.json'),
                               history_file=str(tmp_path / 'h.sqlite'))
        for i in range(6):
            eff = store.effective()
            eff['devices'][0]['ppm'] = float(i)
            store.save(eff)
        assert store.version_count() == 3

    def test_saving_still_works_without_a_history_db(self, tmp_path: Any) -> None:
        # Losing the audit trail must never stop a config from being saved.
        store = cs.ConfigStore(copy.deepcopy(BASE),
                               overlay_file=str(tmp_path / 'o.json'))
        eff = store.effective()
        eff['devices'][0]['gains'] = 'LNA:42'
        version = store.save(eff)
        assert version['id'] is None
        assert store.history() == []
        assert store.effective()['devices'][0]['gains'] == 'LNA:42'

    def test_a_bad_history_path_degrades_quietly(self, tmp_path: Any) -> None:
        target = tmp_path / 'not-a-dir'
        target.write_text('')
        store = cs.ConfigStore(copy.deepcopy(BASE),
                               overlay_file=str(tmp_path / 'o.json'),
                               history_file=str(target / 'h.sqlite'))
        eff = store.effective()
        eff['devices'][0]['gains'] = 'LNA:42'
        store.save(eff)
        assert store.effective()['devices'][0]['gains'] == 'LNA:42'


class TestExport:
    def test_export_writes_the_full_effective_config(self, store: cs.ConfigStore,
                                                     tmp_path: Any) -> None:
        eff = store.effective()
        eff['devices'][0]['gains'] = 'LNA:42'
        store.save(eff)
        out = str(tmp_path / 'full.json')
        store.export(out)
        with open(out) as fh:
            written = json.load(fh)
        assert written['devices'][0]['gains'] == 'LNA:42'
        assert written['devices'][0]['rate'] == 2400000     # base fields included
        assert written['trunking']['chans'][0]['nac'] == '0x1D1'

    def test_export_is_independent_of_the_preset(self, store: cs.ConfigStore,
                                                 tmp_path: Any) -> None:
        out = str(tmp_path / 'full.json')
        store.export(out)
        with open(out) as fh:
            assert json.load(fh) == store.effective()


class TestStats:
    def test_stats_has_no_history_key(self, store: cs.ConfigStore) -> None:
        # /api/config/state spreads stats() beside its own keys; a same-named one
        # would silently replace a list with a counter. tg_metadata has the same
        # note for the same reason.
        assert 'history' not in store.stats()
        assert 'versions' in store.stats()

    def test_override_count_reflects_the_overlay(self, store: cs.ConfigStore) -> None:
        eff = store.effective()
        eff['devices'][0]['gains'] = 'LNA:42'
        eff['devices'][0]['ppm'] = 2.0
        store.save(eff)
        # gains + ppm, plus the carried identity field.
        assert store.stats()['overrides'] == 3


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


class TestPathResolution:
    def test_env_wins(self, monkeypatch: Any) -> None:
        monkeypatch.setenv('OP25_CONFIG_OVERLAY', '/tmp/x.json')
        assert cs.overlay_path({'terminal': {'config_overlay': 'ignored'}}) == '/tmp/x.json'

    def test_empty_env_disables_editing(self, monkeypatch: Any) -> None:
        monkeypatch.setenv('OP25_CONFIG_OVERLAY', '')
        assert cs.overlay_path(None) is None

    def test_terminal_key_is_next(self, monkeypatch: Any) -> None:
        monkeypatch.delenv('OP25_CONFIG_OVERLAY', raising=False)
        assert cs.overlay_path({'terminal': {'config_overlay': 'a.json'}}) == 'a.json'

    def test_terminal_false_disables(self, monkeypatch: Any) -> None:
        monkeypatch.delenv('OP25_CONFIG_OVERLAY', raising=False)
        assert cs.overlay_path({'terminal': {'config_overlay': False}}) is None

    def test_default_is_in_the_cwd(self, monkeypatch: Any) -> None:
        monkeypatch.delenv('OP25_CONFIG_OVERLAY', raising=False)
        assert cs.overlay_path({}) == 'op25_config_overlay.json'

    def test_history_path_follows_the_same_rules(self, monkeypatch: Any) -> None:
        monkeypatch.setenv('OP25_CONFIG_HISTORY_DB', '')
        assert cs.history_db_path(None) is None
        monkeypatch.delenv('OP25_CONFIG_HISTORY_DB')
        assert cs.history_db_path({}) == 'op25_config_history.sqlite'


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_every_field_has_the_keys_the_editor_needs(self) -> None:
        for section in config_schema.schema()['sections']:
            for field in section['fields']:
                assert {'path', 'label', 'type', 'live', 'applies_to'} <= set(field)

    def test_protocol_filter_hides_inapplicable_fields(self) -> None:
        p25 = config_schema.schema(config_schema.P25)
        smartnet = config_schema.schema(config_schema.SMARTNET)

        def paths(s: dict) -> set[str]:
            return {f['path'] for sec in s['sections'] for f in sec['fields']}

        # nac is P25-only; bandplan is SmartNet-only.
        assert 'trunking.chans[*].nac' in paths(p25)
        assert 'trunking.chans[*].nac' not in paths(smartnet)
        assert 'trunking.chans[*].bandplan' in paths(smartnet)
        assert 'trunking.chans[*].bandplan' not in paths(p25)

    def test_unfiltered_schema_has_everything(self) -> None:
        allp = {f['path'] for sec in config_schema.schema()['sections']
                for f in sec['fields']}
        assert 'trunking.chans[*].nac' in allp
        assert 'trunking.chans[*].bandplan' in allp


class TestLiveClassification:
    @pytest.mark.parametrize('path', [
        'devices[sdr0].gains', 'devices[sdr0].ppm',
        'devices[with.dots].gains',
    ])
    def test_live_paths_are_recognised(self, path: str) -> None:
        assert config_schema.is_live(path)

    @pytest.mark.parametrize('path', [
        'devices[sdr0].rate', 'devices[sdr0].args', 'devices[sdr0].frequency',
        'channels[a].if_rate', 'trunking.chans[X].nac',
        'terminal.http_plot_interval',
    ])
    def test_restart_required_paths_are_not_live(self, path: str) -> None:
        # Being optimistic here is the dangerous direction: the UI would report
        # success and the decoder would keep running the old value.
        assert not config_schema.is_live(path)

    def test_a_pattern_does_not_match_a_different_depth(self) -> None:
        assert not config_schema.is_live('devices[sdr0].gains.extra')
        assert not config_schema.is_live('gains')

    def test_classify_splits_a_diff(self) -> None:
        verdict = config_schema.classify([
            {'path': 'devices[sdr0].gains', 'op': 'change'},
            {'path': 'devices[sdr0].rate', 'op': 'change'},
        ])
        assert [c['path'] for c in verdict['live']] == ['devices[sdr0].gains']
        assert [c['path'] for c in verdict['restart_required']] == ['devices[sdr0].rate']
        assert verdict['needs_restart'] is True

    def test_an_all_live_change_needs_no_restart(self) -> None:
        verdict = config_schema.classify([{'path': 'devices[sdr0].ppm', 'op': 'change'}])
        assert verdict['needs_restart'] is False

    def test_an_empty_diff_needs_no_restart(self) -> None:
        assert config_schema.classify([])['needs_restart'] is False


# ---------------------------------------------------------------------------
# Startup overlay application
#
# The overlay was written and read by the *web server*, but nothing applied it to
# the config the decoder was started from -- so /api/config/state reported the
# user's override while multi_rx ran the preset value, and a saved gain reverted
# on every restart. This is the missing startup step.
# ---------------------------------------------------------------------------


class TestApplyOverlayStream:
    def test_overlay_is_merged_onto_the_base(self, tmp_path: Any) -> None:
        overlay = tmp_path / 'o.json'
        overlay.write_text(json.dumps({'devices': [{'name': 'sdr0', 'gains': 'LNA:39'}]}))
        out = json.loads(cs.apply_overlay_stream(json.dumps(BASE), str(overlay)))
        assert out['devices'][0]['gains'] == 'LNA:39'

    def test_untouched_device_fields_survive(self, tmp_path: Any) -> None:
        """The bug jq's `*` would have caused.

        Replacing the array would leave a device with only name and gains -- no
        args, no rate, no frequency -- and the receiver would not start.
        """
        overlay = tmp_path / 'o.json'
        overlay.write_text(json.dumps({'devices': [{'name': 'sdr0', 'gains': 'LNA:39'}]}))
        dev = json.loads(cs.apply_overlay_stream(json.dumps(BASE), str(overlay)))['devices'][0]
        for field in ('args', 'rate', 'frequency', 'ppm'):
            assert field in dev, f'{field} lost merging the overlay'
        assert dev['rate'] == 2400000

    def test_other_sections_survive(self, tmp_path: Any) -> None:
        overlay = tmp_path / 'o.json'
        overlay.write_text(json.dumps({'devices': [{'name': 'sdr0', 'ppm': 1.0}]}))
        out = json.loads(cs.apply_overlay_stream(json.dumps(BASE), str(overlay)))
        assert out['channels'][0]['if_rate'] == 24000
        assert out['trunking']['chans'][0]['nac'] == '0x1D1'

    def test_a_missing_overlay_is_a_passthrough(self, tmp_path: Any) -> None:
        out = json.loads(cs.apply_overlay_stream(json.dumps(BASE), str(tmp_path / 'nope.json')))
        assert out == cs.strip_doc_keys(BASE)

    def test_no_overlay_path_is_a_passthrough(self) -> None:
        assert json.loads(cs.apply_overlay_stream(json.dumps(BASE), None)) \
            == cs.strip_doc_keys(BASE)

    def test_a_corrupt_overlay_degrades_to_the_base(self, tmp_path: Any) -> None:
        # The base alone is a working scanner; refusing to start because an
        # override is malformed would be the worse failure.
        overlay = tmp_path / 'o.json'
        overlay.write_text('{not json')
        out = json.loads(cs.apply_overlay_stream(json.dumps(BASE), str(overlay)))
        assert out['devices'][0]['gains'] == 'LNA:40'

    def test_a_non_object_overlay_degrades_to_the_base(self, tmp_path: Any) -> None:
        overlay = tmp_path / 'o.json'
        overlay.write_text('[1,2,3]')
        out = json.loads(cs.apply_overlay_stream(json.dumps(BASE), str(overlay)))
        assert out['devices'][0]['gains'] == 'LNA:40'

    def test_doc_keys_are_stripped(self, tmp_path: Any) -> None:
        base = dict(BASE)
        base['#note'] = 'prose'
        out = json.loads(cs.apply_overlay_stream(json.dumps(base), None))
        assert '#note' not in out

    def test_a_bad_base_is_fatal(self) -> None:
        # Unlike a bad overlay: there is nothing to fall back to.
        with pytest.raises(ValueError):
            cs.apply_overlay_stream('{not json', None)

    def test_cli_round_trips_stdin_to_stdout(self, tmp_path: Any,
                                            monkeypatch: Any, capsys: Any) -> None:
        overlay = tmp_path / 'o.json'
        overlay.write_text(json.dumps({'devices': [{'name': 'sdr0', 'ppm': 3.5}]}))
        monkeypatch.setattr('sys.stdin', __import__('io').StringIO(json.dumps(BASE)))
        assert cs._main(['--apply-overlay', str(overlay)]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out['devices'][0]['ppm'] == 3.5

    def test_cli_reports_failure_on_a_bad_base(self, monkeypatch: Any,
                                               capsys: Any) -> None:
        monkeypatch.setattr('sys.stdin', __import__('io').StringIO('{nope'))
        assert cs._main([]) == 1

    def test_what_the_editor_previews_is_what_startup_produces(self,
                                                              tmp_path: Any) -> None:
        """The property that matters: one merge function, two call sites.

        If these could disagree, the UI would show a config the decoder is not
        running -- which is the failure mode the whole overlay design exists to
        avoid.
        """
        overlay_path = str(tmp_path / 'o.json')
        store = cs.ConfigStore(copy.deepcopy(BASE), overlay_file=overlay_path)
        proposed = store.effective()
        proposed['devices'][0]['gains'] = 'LNA:39'
        proposed['devices'][0]['ppm'] = 2.5
        store.save(proposed)

        at_startup = json.loads(cs.apply_overlay_stream(json.dumps(BASE), overlay_path))
        assert at_startup == store.effective()
