"""
Built-in add-on presets.

`addons/op25/presets/*.json` ship inside the image and are selected by the
`preset` add-on option, so a fix to one reaches every install on update. That is
the whole reason they exist: a config copied into the user's config directory is
written once and never touched again, so it cannot receive one.

The trap is that the RF facts about a system are now stated twice -- once in the
preset and once in the standalone config under apps/. They went out of step
exactly once already: the gain and sample-rate fix landed in
Palmetto800-single.json and the shipped sample kept LNA:39 / 1000000, so every
add-on install carried the old values. These cases pin the two together, and
pin the container-specific parts that must *not* be copied across.
"""

import json
import os

import pytest

_APPS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_APPS)))
_PRESETS = os.path.join(_ROOT, 'addons', 'op25', 'presets')


def _load(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def _strip_docs(node):
    """Drop "#"-prefixed documentation keys, as the add-on run script does."""
    if isinstance(node, dict):
        return {k: _strip_docs(v) for k, v in node.items() if not k.startswith('#')}
    if isinstance(node, list):
        return [_strip_docs(v) for v in node]
    return node


def _preset_paths() -> list[str]:
    if not os.path.isdir(_PRESETS):
        return []
    return sorted(os.path.join(_PRESETS, f) for f in os.listdir(_PRESETS)
                  if f.endswith('.json'))


class TestPresetsAreLoadable:
    def test_at_least_one_preset_ships(self) -> None:
        assert _preset_paths(), 'no presets found in addons/op25/presets'

    def test_palmetto800_exists(self) -> None:
        # config.yaml's `preset` schema names it, and it is also what init-op25
        # copies when preset is 'custom' and no file exists.
        assert os.path.isfile(os.path.join(_PRESETS, 'palmetto800.json'))

    @pytest.mark.parametrize('path', _preset_paths(), ids=os.path.basename)
    def test_preset_is_valid_json(self, path: str) -> None:
        _load(path)

    @pytest.mark.parametrize('path', _preset_paths(), ids=os.path.basename)
    def test_preset_has_the_sections_multi_rx_needs(self, path: str) -> None:
        cfg = _strip_docs(_load(path))
        for key in ('devices', 'channels', 'trunking', 'audio', 'terminal'):
            assert key in cfg, key
        assert cfg['devices'] and cfg['channels']


class TestPalmetto800MatchesTheStandaloneConfig:
    """The RF facts must agree with apps/Palmetto800-single.json."""

    @pytest.fixture()
    def preset(self) -> dict:
        return _strip_docs(_load(os.path.join(_PRESETS, 'palmetto800.json')))

    @pytest.fixture()
    def standalone(self) -> dict:
        return _strip_docs(_load(os.path.join(_APPS, 'Palmetto800-single.json')))

    @pytest.mark.parametrize('field', [
        'frequency', 'gains', 'rate', 'gain_mode', 'usable_bw_pct', 'tunable',
    ])
    def test_device_rf_fields_agree(self, preset: dict, standalone: dict,
                                    field: str) -> None:
        assert preset['devices'][0][field] == standalone['devices'][0][field], (
            f'{field} drifted between the add-on preset and the standalone '
            f'config -- this is how LNA:39 / rate 1000000 kept shipping'
        )

    @pytest.mark.parametrize('field', [
        'demod_type', 'filter_type', 'excess_bw', 'if_rate', 'symbol_rate',
        'trunking_sysname', 'enable_analog',
    ])
    def test_channel_demod_fields_agree(self, preset: dict, standalone: dict,
                                        field: str) -> None:
        assert preset['channels'][0][field] == standalone['channels'][0][field], field

    @pytest.mark.parametrize('field', [
        'sysname', 'control_channel_list', 'nac', 'crypt_behavior',
    ])
    def test_trunking_fields_agree(self, preset: dict, standalone: dict,
                                   field: str) -> None:
        a = preset['trunking']['chans'][0]
        b = standalone['trunking']['chans'][0]
        assert a[field] == b[field], field

    def test_sample_rate_divides_the_if_rate_exactly(self, preset: dict) -> None:
        # An inexact ratio inserts an arbitrary resampler in the demod chain --
        # see p25_demodulator_dev.py, which falls back to arb_resampler_ccf
        # whenever input_rate/decimation != if_rate.
        rate = preset['devices'][0]['rate']
        if_rate = preset['channels'][0]['if_rate']
        assert rate % if_rate == 0, f'{rate} / {if_rate} is not an integer'

    def test_sample_rate_is_one_multi_rx_approves_of(self, preset: dict) -> None:
        # Mirrors the `speeds` list in multi_rx.py, which warns on anything else.
        approved = (250000, 1000000, 1024000, 1800000, 1920000, 2000000,
                    2048000, 2400000, 2560000)
        assert preset['devices'][0]['rate'] in approved


class TestPresetIsContainerAppropriate:
    """Things the standalone config does that the add-on preset must not."""

    @pytest.fixture()
    def preset(self) -> dict:
        return _strip_docs(_load(os.path.join(_PRESETS, 'palmetto800.json')))

    def test_no_local_speaker_output(self, preset: dict) -> None:
        # There is no sound device in the container by default, and sockaudio
        # would take the UDP port that websocket_server needs for /api/stream.
        # The audio_output add-on option sets this when the user asks for it.
        assert preset['audio']['module'] == ''
        assert preset['audio']['instances'] == []

    def test_single_audio_destination(self, preset: dict) -> None:
        # The dual-destination trick exists to run local speakers and browser
        # audio at once, which needs a speaker to be worth anything.
        assert ',' not in preset['channels'][0]['destination']

    def test_no_device_serial_pinned(self, preset: dict) -> None:
        # A serial baked into a shipped preset matches exactly one person's
        # dongle. device_overrides[].serial is how an install pins its own.
        assert preset['devices'][0]['args'] == 'rtl'

    def test_terminal_transport_is_left_to_the_run_script(self, preset: dict) -> None:
        # It forces websocket_server.py on the ingress port; a value here would
        # be silently overwritten, which is worse than being absent.
        assert 'module' not in preset['terminal']
        assert 'terminal_type' not in preset['terminal']

    def test_no_secrets_and_no_host_specific_urls(self, preset: dict) -> None:
        # /api/config serves the loaded config to an unauthenticated browser.
        # The add-on injects url, and the token goes via $OP25_HA_TOKEN.
        ha = preset['terminal'].get('home_assistant', {})
        for leaky in ('token', 'token_file', 'url'):
            assert leaky not in ha, leaky

    def test_home_assistant_integration_is_off_by_default(self, preset: dict) -> None:
        # Transcription costs CPU on an N100 that is also running Home
        # Assistant, so it must be something the user turns on.
        assert preset['terminal']['home_assistant']['enabled'] is False
