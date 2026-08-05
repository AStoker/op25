"""
Pytest wrapper around upstream's NBFM squelch validation scripts.

`squelch_core_test.py` and `squelch_gr_test.py` came from upstream (the W1JPI
noise/voice squelch work) as standalone `main()` scripts that print a
"N/N checks passed" line and exit non-zero on failure — they are not pytest
modules.  Rather than rewrite them (which would make every future upstream sync
a conflict), run them as subprocesses so a plain `pytest` from apps/ covers them
too.

`squelch_gr_test.py` additionally needs GNU Radio plus a built/installed
gr-op25_repeater, so it is skipped when the flowgraph modules are unavailable.
"""

import os
import subprocess
import sys
from typing import Any

import pytest

APPS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_script(name: str) -> subprocess.CompletedProcess[str]:
    """Run an upstream validation script with this interpreter, from apps/."""
    return subprocess.run(
        [sys.executable, name],
        cwd=APPS_DIR,
        capture_output=True,
        text=True,
        timeout=600,
    )


def _requires(module: str) -> Any:
    return pytest.mark.skipif(
        __import__('importlib').util.find_spec(module) is None,
        reason=f"{module} not available",
    )


class TestSquelchCore:
    """Pure-DSP checks — numpy only, no GNU Radio."""

    @_requires('numpy')
    def test_all_checks_pass(self) -> None:
        proc = _run_script('squelch_core_test.py')
        assert proc.returncode == 0, (
            f"squelch_core_test.py failed:\n{proc.stdout}\n{proc.stderr}"
        )
        # Guard against a script that silently stops running checks.
        assert 'checks passed' in proc.stdout, proc.stdout


class TestSquelchGnuRadio:
    """Flowgraph integration — needs gnuradio and the built op25 module."""

    @_requires('gnuradio')
    def test_all_checks_pass(self) -> None:
        proc = _run_script('squelch_gr_test.py')
        if proc.returncode != 0 and 'op25_repeater' in (proc.stderr or ''):
            pytest.skip('gr-op25_repeater not installed for this interpreter')
        assert proc.returncode == 0, (
            f"squelch_gr_test.py failed:\n{proc.stdout}\n{proc.stderr}"
        )
        assert 'checks passed' in proc.stdout, proc.stdout
