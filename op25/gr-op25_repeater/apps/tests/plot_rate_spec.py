# Copyright 2026 OP25 Contributors
#
# This file is part of OP25
#
# OP25 is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.

"""Plot traces: payload shape, and how much work is done to produce one.

FFT_FREQ (20 Hz) and MIX_FREQ (50 Hz) were chosen for a gnuplot window redrawing
continuously.  The browser is fed at http_plot_interval, 1 Hz by default, so the
old code ran 20-50 transforms plus a 512-iteration pure-Python averaging loop for
every frame anyone actually saw.  These tests pin both halves of the fix: the
reduced compute rate, and the coefficient compensation that keeps the trace
settling over the same wall-clock time despite it.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest

gr_gnuplot = pytest.importorskip("gr_gnuplot", reason="needs GNU Radio")


class FakeQueue:
    """Stands in for the decoder's ui_in_q."""

    def __init__(self, full: bool = False) -> None:
        self.messages: list[dict[str, Any]] = []
        self._full = full

    def full_p(self) -> bool:
        return self._full

    def insert_tail(self, msg: Any) -> None:
        self.messages.append(json.loads(msg.to_string()))

    def flush(self) -> None:
        self.messages.clear()


@pytest.fixture()
def rng() -> Any:
    return np.random.default_rng(20260806)


def complex_buf(rng: Any, n: int = gr_gnuplot.FFT_BINS) -> Any:
    return (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)


def wrapper(q: FakeQueue, interval: float | None = 1.0, sps: int = 10) -> Any:
    w = gr_gnuplot.wrap_gp(sps=sps, plot_name="Ch:test", chan=0, out_q=q)
    w.set_width(2_400_000)
    w.set_center_freq(851_000_000)
    if interval is not None:
        w.set_interval(interval)
    return w


class TestComputeInterval:
    def test_slows_to_the_display_rate(self) -> None:
        w = wrapper(FakeQueue(), interval=1.0)
        # 8 averages per frame, so 8 Hz rather than 20 Hz (fft) or 50 Hz (mixer).
        assert w.compute_interval(gr_gnuplot.FFT_FREQ) == pytest.approx(0.125)
        assert w.compute_interval(gr_gnuplot.MIX_FREQ) == pytest.approx(0.125)

    def test_never_speeds_up_beyond_the_historical_rate(self) -> None:
        """A short plot_interval must not make the DSP work harder than before."""
        w = wrapper(FakeQueue(), interval=0.1)
        assert w.compute_interval(gr_gnuplot.FFT_FREQ) == gr_gnuplot.FFT_FREQ
        assert w.compute_interval(gr_gnuplot.MIX_FREQ) == gr_gnuplot.MIX_FREQ

    def test_no_interval_keeps_the_nominal_rate(self) -> None:
        # curses_plot_interval defaults to 0.0, i.e. every buffer.
        w = wrapper(FakeQueue(), interval=0.0)
        assert w.compute_interval(gr_gnuplot.FFT_FREQ) == gr_gnuplot.FFT_FREQ


class TestAveragingCompensation:
    def test_settling_time_is_preserved(self) -> None:
        """The reason the throttle could not simply move above the FFT.

        A one-pole average retains (1-alpha) per step.  Taking (actual/nominal)
        fewer steps in the same second means retaining (1-alpha)**ratio per step
        to reach the same place -- otherwise cutting 20 Hz to 8 Hz would stretch
        FFT_AVG's ~1s time constant by 2.5x and the spectrum would lag the radio.
        """
        w = wrapper(FakeQueue(), interval=1.0)
        actual = w.compute_interval(gr_gnuplot.FFT_FREQ)
        alpha = w._averaging_alpha(gr_gnuplot.FFT_AVG, gr_gnuplot.FFT_FREQ, actual)

        def settled(steps: int, a: float) -> float:
            """Fraction of the final value reached after `steps` updates."""
            return 1.0 - (1.0 - a) ** steps

        old_steps = round(1.0 / gr_gnuplot.FFT_FREQ)      # 20 in one second
        new_steps = round(1.0 / actual)                   #  8 in one second
        assert settled(new_steps, alpha) == pytest.approx(
            settled(old_steps, gr_gnuplot.FFT_AVG), abs=1e-9)

    def test_alpha_grows_with_the_interval(self) -> None:
        w = wrapper(FakeQueue(), interval=1.0)
        alpha = w._averaging_alpha(gr_gnuplot.FFT_AVG, gr_gnuplot.FFT_FREQ, 0.125)
        assert gr_gnuplot.FFT_AVG < alpha < 1.0

    def test_alpha_is_unchanged_when_not_slowed(self) -> None:
        w = wrapper(FakeQueue(), interval=1.0)
        assert w._averaging_alpha(gr_gnuplot.FFT_AVG, gr_gnuplot.FFT_FREQ,
                                  gr_gnuplot.FFT_FREQ) == gr_gnuplot.FFT_AVG


class TestStatelessModesAreSkippedForFree:
    """eye / constellation / symbol carry nothing between frames.

    Every trace is built from one buffer and discarded, so when the UI is not due
    for a frame the work can be skipped outright rather than done and thrown away.
    """

    @pytest.mark.parametrize('mode,bufsz', [
        ('symbol', 2400), ('constellation', 1000), ('eye', 1000),
    ])
    def test_throttled_frames_do_no_work(self, rng: Any, mode: str, bufsz: int) -> None:
        q = FakeQueue()
        w = wrapper(q, interval=1.0)
        buf = (complex_buf(rng, bufsz) if mode == 'constellation'
               else rng.standard_normal(bufsz).astype(np.float32))

        w.plot(buf, bufsz, mode=mode)
        assert len(q.messages) == 1
        count_after_first = w.plot_count

        for _ in range(50):
            w.plot(buf, bufsz, mode=mode)
        # plot_count only advances when a buffer is actually processed.
        assert w.plot_count == count_after_first
        assert len(q.messages) == 1

    def test_eye_decimation_only_applies_when_unthrottled(self, rng: Any) -> None:
        """The %20 eye decimation used to compound with the send throttle.

        With plot_interval set, due() is the rate limiter; leaving the historical
        `plot_count % 20` in place as well would mean 20 plot intervals per eye
        frame -- one every 20 seconds at the default 1 Hz.
        """
        buf = rng.standard_normal(1000).astype(np.float32)

        throttled = FakeQueue()
        w = wrapper(throttled, interval=1.0)
        w.plot(buf, 1000, mode='eye')
        assert len(throttled.messages) == 1      # first due frame draws

        unthrottled = FakeQueue()
        w2 = wrapper(unthrottled, interval=0.0)
        for _ in range(19):
            w2.plot(buf, 1000, mode='eye')
        assert len(unthrottled.messages) == 0    # still decimating
        w2.plot(buf, 1000, mode='eye')
        assert len(unthrottled.messages) == 1


class TestFftPayload:
    def test_shape_and_ranges(self, rng: Any) -> None:
        q = FakeQueue()
        w = wrapper(q)
        w.plot(complex_buf(rng), gr_gnuplot.FFT_BINS, mode='fft')

        msg = q.messages[0]
        assert msg['json_type'] == 'plot'
        assert msg['mode'] == 'fft'
        assert msg['chan'] == 0
        assert len(msg['data']) == gr_gnuplot.FFT_BINS
        assert all(isinstance(p, list) and len(p) == 2 for p in msg['data'])
        assert all(isinstance(v, float) for p in msg['data'] for v in p)
        # x is MHz across the sampled span, ascending.
        xs = [p[0] for p in msg['data']]
        assert xs == sorted(xs)
        assert msg['xrange'][0] < 851.0 < msg['xrange'][1]
        assert msg['yrange'][1] == 0.0
        assert 'Spectrum' in msg['title'] and 'Ch:test' in msg['title']

    def test_averaging_converges_towards_the_input_spectrum(self, rng: Any) -> None:
        """Guards the vectorised replacement of the per-bin Python loop."""
        q = FakeQueue()
        w = wrapper(q, interval=0.0)     # unthrottled: every buffer is a frame
        buf = complex_buf(rng)
        expected = np.abs(np.fft.fftshift(
            np.fft.fft(buf * np.blackman(gr_gnuplot.FFT_BINS), gr_gnuplot.FFT_BINS, 0)
            / (0.42 * gr_gnuplot.FFT_BINS)))

        for _ in range(400):
            w.plot(buf, gr_gnuplot.FFT_BINS, mode='fft')
        assert np.allclose(w.avg_pwr, expected, rtol=1e-3)

        # And the trace is that average in dB, bin for bin.
        ys = np.array([p[1] for p in q.messages[-1]['data']])
        assert np.allclose(ys, 20.0 * np.log10(w.avg_pwr), rtol=1e-9)

    def test_a_dead_source_produces_no_frame(self, rng: Any) -> None:
        """All-zero input means the device is missing; a -inf trace is not useful."""
        q = FakeQueue()
        w = wrapper(q)
        w.plot(np.zeros(gr_gnuplot.FFT_BINS, dtype=np.complex64),
               gr_gnuplot.FFT_BINS, mode='fft')
        assert q.messages == []

    @pytest.mark.parametrize('mode,title', [('mixer', 'Raw Mixer'), ('fll', 'Tuned Mixer')])
    def test_mixer_and_fll_payloads(self, rng: Any, mode: str, title: str) -> None:
        q = FakeQueue()
        w = wrapper(q)
        w.plot(complex_buf(rng), gr_gnuplot.FFT_BINS, mode=mode)
        msg = q.messages[0]
        assert msg['mode'] == mode
        assert title in msg['title']
        assert len(msg['data']) == gr_gnuplot.FFT_BINS


class TestDecimation:
    def test_long_traces_are_strided_not_truncated(self, rng: Any) -> None:
        """A truncated symbol trace would show only the beginning of the buffer."""
        q = FakeQueue()
        w = wrapper(q)
        buf = np.arange(2400, dtype=np.float32)
        w.plot(buf, 2400, mode='symbol')

        data = q.messages[0]['data']
        assert len(data) <= gr_gnuplot.PLOT_MAX_POINTS
        # Still spans the full x range of the input.
        assert data[0][0] == 0.0
        assert data[-1][0] >= 2400 - gr_gnuplot.PLOT_MAX_POINTS
        assert data[-1][1] == data[-1][0]     # y is the sample value, unchanged

    def test_short_traces_pass_through_untouched(self, rng: Any) -> None:
        q = FakeQueue()
        w = wrapper(q)
        w.plot(complex_buf(rng, 1000), 1000, mode='constellation')
        assert len(q.messages[0]['data']) == 1000


class TestRobustness:
    def test_a_full_queue_drops_the_frame_silently(self, rng: Any) -> None:
        """A dropped plot frame must never disturb the flowgraph."""
        q = FakeQueue(full=True)
        w = wrapper(q)
        w.plot(complex_buf(rng), gr_gnuplot.FFT_BINS, mode='fft')
        assert q.messages == []

    def test_kill_detaches_the_queue(self, rng: Any) -> None:
        q = FakeQueue()
        w = wrapper(q)
        w.kill()
        w.plot(complex_buf(rng), gr_gnuplot.FFT_BINS, mode='fft')
        assert q.messages == []

    def test_window_is_cached_per_size(self) -> None:
        a = gr_gnuplot._blackman(gr_gnuplot.FFT_BINS)
        b = gr_gnuplot._blackman(gr_gnuplot.FFT_BINS)
        assert a is b                                    # not rebuilt per call
        assert gr_gnuplot._blackman(256) is not a        # but keyed by size
