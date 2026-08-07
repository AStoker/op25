"""
multi_rx's method surface, checked without importing it.

multi_rx imports osmosdr and gnuradio at module scope, so it cannot be imported
on a machine without GNU Radio -- and these checks have to run in CI, which has
neither. So they parse the source instead.

This exists because of a real regression: a second `find_device` was added to
`rx_block` for the live gain/ppm commands, shadowing the existing
`find_device(chan)` that resolves a *channel config dict* to a device. Python
keeps the later definition, so `configure_channels` compared `dev.name` against a
dict, matched nothing, and dropped every channel with "not attached to any device
- ignoring!". The receiver came up with no channels: RF fine, decoder running,
zero calls. Nothing in the test suite noticed, because nothing here could import
multi_rx to notice with.
"""

from __future__ import annotations

import ast
import os

import pytest

_APPS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MULTI_RX = os.path.join(_APPS, 'multi_rx.py')


def _classes() -> dict[str, ast.ClassDef]:
    with open(_MULTI_RX) as fh:
        tree = ast.parse(fh.read(), filename=_MULTI_RX)
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}


def _methods(cls: ast.ClassDef) -> list[str]:
    return [n.name for n in cls.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


class TestNoShadowedMethods:
    @pytest.mark.parametrize('class_name', ['rx_block', 'device', 'channel'])
    def test_no_method_is_defined_twice(self, class_name: str) -> None:
        """A duplicate definition silently wins and the first one vanishes."""
        cls = _classes().get(class_name)
        assert cls is not None, f'{class_name} not found in multi_rx.py'
        names = _methods(cls)
        duplicates = sorted({n for n in names if names.count(n) > 1})
        assert not duplicates, (
            f'{class_name} defines these more than once, so the earlier '
            f'definition is unreachable: {duplicates}'
        )

    def test_every_class_in_the_file(self) -> None:
        # Catches the same mistake in a class the list above forgot.
        offenders = {}
        for name, cls in _classes().items():
            names = _methods(cls)
            dupes = sorted({n for n in names if names.count(n) > 1})
            if dupes:
                offenders[name] = dupes
        assert not offenders, f'shadowed methods: {offenders}'


class TestDeviceLookupContract:
    def test_find_device_takes_a_channel_config(self) -> None:
        """find_device resolves a channel dict; the by-name lookup is separate.

        Keeping them distinct is the fix for the shadowing bug, so the names are
        pinned here rather than left to be re-collided later.
        """
        cls = _classes()['rx_block']
        methods = _methods(cls)
        assert 'find_device' in methods
        assert 'find_device_by_name' in methods

        find_device = next(n for n in cls.body
                           if isinstance(n, ast.FunctionDef) and n.name == 'find_device')
        args = [a.arg for a in find_device.args.args]
        assert args == ['self', 'chan'], (
            'find_device must keep taking a channel config dict -- '
            'configure_channels passes one'
        )

    def test_live_device_commands_use_the_by_name_lookup(self) -> None:
        with open(_MULTI_RX) as fh:
            source = fh.read()
        for method in ('set_device_gains', 'set_device_ppm'):
            start = source.index('def %s' % method)
            body = source[start:start + 600]
            assert 'find_device_by_name' in body, (
                f'{method} must use find_device_by_name, not find_device, which '
                f'expects a channel config dict'
            )


class TestLiveDeviceCommandsAreWired:
    def test_commands_are_registered_for_dispatch(self) -> None:
        # A method nothing routes to is dead code, and the failure is silent.
        with open(_MULTI_RX) as fh:
            source = fh.read()
        assert 'RX_DEVICE_COMMANDS' in source
        assert 'set_device_gains' in source
        assert 'set_device_ppm' in source

    def test_device_exposes_the_accessors_the_ui_reports(self) -> None:
        methods = _methods(_classes()['device'])
        for name in ('get_ppm', 'get_gains', 'set_gains', 'set_ppm'):
            assert name in methods, f'device.{name} missing'
