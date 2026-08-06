# Copyright 2011, 2012, 2013, 2014, 2015 Max H. Parke KA1RBI
# 
# This file is part of OP25
# 
# OP25 is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.
# 
# OP25 is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public
# License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with OP25; see the file COPYING. If not, write to the Free
# Software Foundation, Inc., 51 Franklin Street, Boston, MA
# 02110-1301, USA.

"""Plot sinks for the OP25 signal displays.

Despite the module name, gnuplot is no longer invoked: the browser renders
these plots itself from the raw traces that send_plot() pushes onto out_q.
The gnuplot subprocess only ever existed for the removed http terminal's PNG
output and for rx.py's x11 windows, and both are gone.  The name is kept
because renaming it would churn six imports in multi_rx.py for no gain.
"""

import time
import json

from gnuradio import gr, eng_notation
from gnuradio import blocks, audio
# eng_option (GNURadio engineering-notation CLI helper) was removed in GNURadio
# 3.10 and is not used anywhere in this file.
import numpy as np
from gnuradio import gr

import gnuradio.op25_repeater as op25_repeater

_def_debug = 0
_def_sps = 5
_def_sps_mult = 2

Y_AVG    = 0.03
FFT_AVG  = 0.05
MIX_AVG  = 0.10
BAL_AVG  = 0.05
FFT_BINS = 512    # number of fft bins
FFT_FREQ = 0.05   # nominal time interval between fft updates
MIX_FREQ = 0.02   # nominal time interval between mixer updates

# How many spectrum averages to accumulate per plot actually sent to the UI.
#
# FFT_FREQ / MIX_FREQ were chosen for a gnuplot window redrawing continuously.
# The browser is fed at http_plot_interval (1.0s by default), so computing 20
# (fft) or 50 (mixer/fll) transforms per frame was 20-50x more work than the
# display could use.  The transforms are not pure overhead — they feed the
# exponential average that smooths the trace — so the rate is reduced rather
# than removed, and the averaging constant is compensated in
# _averaging_alpha() so the trace still settles over the same wall-clock time.
#
# 8 keeps enough independent looks per frame that the average is still visibly
# a smoothed spectrum and not a single noisy snapshot.
AVGS_PER_PLOT = 8

# Cached analysis window.  BUFSZ is FFT_BINS for every caller of the fft/mixer/
# fll paths, but key the cache anyway rather than assume it.
_WINDOWS = {}

def _blackman(n):
    w = _WINDOWS.get(n)
    if w is None:
        w = np.blackman(n)
        _WINDOWS[n] = w
    return w

# Cap on points sent to the web UI in one plot message.  Chosen to pass the
# natural buffer sizes through untouched (fft 512, eye 100*sps, constellation
# 1000) while decimating the much longer symbol trace (2400), which keeps the
# JSON payload small enough to push once a second on a Raspberry Pi.
PLOT_MAX_POINTS = 1200

# Titles matching the gnuplot output, so the web UI labels plots identically.
PLOT_TITLES = {
        'constellation': 'Constellation',
        'eye':           'Datascope',
        'symbol':        'Symbol',
        'mixer':         'Raw Mixer',
        'fll':           'Tuned Mixer',
        'fft':           'Spectrum',
        }

class wrap_gp(object):
    def __init__(self, sps=_def_sps, plot_name="", chan = 0, out_q = None):
        self.sps = sps
        self.center_freq = 0.0
        self.relative_freq = 0.0
        self.offset_freq = 0.0
        self.width = None
        self.ffts = ()
        self.freqs = ()
        self.avg_pwr = np.zeros(FFT_BINS)
        self.min_y = -100.0
        self.buf = []
        self.plot_count = 0
        self.last_plot = 0
        self.plot_interval = None
        self.chan = chan
        self.out_q = out_q
        if plot_name == "":
            self.plot_name = ""
        else:
            self.plot_name = plot_name + " "

    def set_sps(self, sps):
        self.sps = int(sps)

    def kill(self):
        if self.out_q is not None:
            self.out_q.flush()
        self.out_q = None

    def set_interval(self, v):
        self.plot_interval = v

    def compute_interval(self, nominal):
        """How often the caller should actually hand us a buffer, in seconds.

        ``nominal`` is the sink's historical rate (FFT_FREQ / MIX_FREQ), which
        was set for a continuously-redrawing gnuplot window.  Nothing is served
        by transforming faster than AVGS_PER_PLOT times per frame the UI will
        ever see, so slow down to that when it is slower than nominal.  Never
        speed up: a short plot_interval must not make the DSP work harder than
        the original code did.
        """
        if not self.plot_interval:
            return nominal
        return max(nominal, float(self.plot_interval) / AVGS_PER_PLOT)

    def _averaging_alpha(self, base_alpha, nominal, actual):
        """Rescale an exponential-average coefficient for a slower update rate.

        A one-pole average with coefficient ``a`` applied every ``nominal``
        seconds retains (1-a) per step.  Sampling every ``actual`` seconds
        instead means (actual/nominal) fewer steps in the same wall-clock time,
        so retaining (1-a)**(actual/nominal) per step keeps the settling time
        the same.  Without this, cutting the FFT rate from 20 Hz to 1 Hz would
        stretch FFT_AVG's ~1s time constant to ~20s and the spectrum would
        visibly lag the radio.
        """
        if actual <= nominal:
            return base_alpha
        return 1.0 - (1.0 - base_alpha) ** (actual / nominal)

    def due(self):
        """True when the next completed buffer should be turned into a plot.

        For modes with no averaging state this is checked *before* any work, so
        a throttled frame costs nothing at all.
        """
        if not self.plot_interval:
            return True
        return self.last_plot + self.plot_interval <= time.time()

    def plot(self, buf, bufsz, mode='eye'):
        # Modes that carry no state between frames — every trace is built from
        # one buffer and discarded — can be skipped outright when the UI is not
        # due for a frame.  Only the fft/mixer/fll paths have to keep running to
        # feed their exponential average, and those pay for it by computing at a
        # reduced rate with a compensated coefficient instead.
        if mode in ('eye', 'constellation', 'symbol') and not self.due():
            return len(buf)

        BUFSZ = bufsz
        consumed = min(len(buf), BUFSZ-len(self.buf))
        if len(self.buf) < BUFSZ:
            self.buf = np.concatenate((self.buf, buf[:int(consumed)]))
        if len(self.buf) < BUFSZ:
            return consumed

        self.plot_count += 1
        # Historical decimation for the eye trace, which fills its buffer far
        # faster than anything wants to draw it.  With plot_interval set, due()
        # above is already the rate limiter and this would compound with it —
        # 20 plot intervals per eye frame, i.e. one every 20 seconds — so it
        # only applies to the unthrottled (curses_plot_interval == 0.0) case.
        if mode == 'eye' and not self.plot_interval and self.plot_count % 20 != 0:
            self.buf = np.array([])
            return consumed

        traces = []     # numeric (xs, ys) series for the web UI
        while(len(self.buf)):
            if mode == 'eye':
                if len(self.buf) < self.sps:
                    break
                trace = np.asarray(self.buf[:self.sps], dtype=float)
                # x is the position within the trace so the web UI overlays the
                # traces into an eye diagram, as gnuplot did with separate lines.
                traces.append((np.arange(len(trace), dtype=float), trace))
                self.buf=self.buf[self.sps:]
            elif mode == 'constellation':
                arr = np.asarray(self.buf)
                traces.append((arr.real.astype(float), arr.imag.astype(float)))
                self.buf = []
            elif mode == 'symbol':
                arr = np.asarray(self.buf, dtype=float)
                traces.append((np.arange(len(arr), dtype=float), arr))
                self.buf = []
            elif mode == 'fft' or mode == 'mixer' or mode == 'fll':
                # Vectorized: the per-bin Python loop this replaces cost ~0.37ms
                # (fft) / ~0.48ms (mixer) per call against ~0.02ms here, and ran
                # 20-50 times a second.  It also computed a `sum_pwr` running
                # total over every bin that nothing ever read.
                self.ffts = np.fft.fftshift(
                        np.fft.fft(self.buf * _blackman(BUFSZ), BUFSZ, 0) / (0.42 * BUFSZ))
                self.freqs = np.fft.fftshift(np.fft.fftfreq(len(self.ffts)))
                if self.center_freq and self.width:
                    self.freqs = ((self.freqs * self.width) + self.center_freq + self.offset_freq) / 1e6
                elif self.width:
                    self.freqs = (self.freqs * self.width)

                nominal = FFT_FREQ if mode == 'fft' else MIX_FREQ
                base    = FFT_AVG  if mode == 'fft' else MIX_AVG
                alpha   = self._averaging_alpha(base, nominal, self.compute_interval(nominal))
                # In-place so the accumulator is not reallocated 20-50 times a
                # second; np.abs() of a 512-point complex array is the only
                # temporary left.
                self.avg_pwr *= (1.0 - alpha)
                self.avg_pwr += alpha * np.abs(self.ffts)

                self.buf = []
                if not self.avg_pwr.all(): # plot is broken, probably because source device was missing
                    return consumed
                traces.append((self.freqs, 20.0 * np.log10(self.avg_pwr)))
                min_y = 20 * np.log10(self.avg_pwr.min())
                self.min_y = ((1.0 - Y_AVG) * self.min_y) + (Y_AVG * min_y)
        self.buf = []

        # The fft/mixer/fll averages above are maintained on every completed
        # buffer whether or not a frame goes out; the *rate* those buffers
        # arrive at is what compute_interval() tunes, in the sink's work().
        if not self.due():
            return consumed
        self.last_plot = time.time()

        if self.out_q is not None:
            self.send_plot(mode, traces)

        return consumed

    def send_plot(self, mode, traces):
        """Push plot data to the web UI as a 'plot' message.

        The browser renders the plot itself, so this sends numbers rather than
        the gnuplot script (x11 terminal) or PNG filename (http terminal) the
        other front-ends consume.  Shape is fixed by PlotPayload in
        www/app/src/types/op25.ts: data is a flat list of [x, y] pairs.
        """
        # Assembled through numpy rather than a per-point Python comprehension:
        # this runs once per frame but on up to 2400 points (the symbol trace),
        # and tolist() converts to native floats in C.
        chunks = [np.column_stack((np.asarray(xs, dtype=float),
                                   np.asarray(ys, dtype=float)))
                  for xs, ys in traces if len(xs)]
        if not chunks:
            return
        pairs = chunks[0] if len(chunks) == 1 else np.concatenate(chunks)

        # Decimate rather than truncate, so a long trace still spans its full
        # range instead of showing only the beginning.
        if len(pairs) > PLOT_MAX_POINTS:
            step = (len(pairs) + PLOT_MAX_POINTS - 1) // PLOT_MAX_POINTS
            pairs = pairs[::step]
        data = pairs.tolist()

        d = {'json_type': 'plot', 'chan': self.chan, 'mode': mode, 'data': data}

        title = PLOT_TITLES.get(mode, mode)
        if mode == 'constellation':
            d['xrange'] = [-1.0, 1.0]
            d['yrange'] = [-1.0, 1.0]
        elif mode in ('eye', 'symbol'):
            d['yrange'] = [-4.0, 4.0]
        elif mode in ('fft', 'mixer', 'fll'):
            if len(self.freqs):
                d['xrange'] = [float(self.freqs[0]), float(self.freqs[-1])]
            d['yrange'] = [float((self.min_y // 20) * 20), 0.0]
            if mode == 'fft' and self.center_freq:
                tuned = (self.center_freq - self.relative_freq) / 1e6
                title = 'Spectrum: tuned to %f Mhz' % tuned
        d['title'] = '%s%s' % (self.plot_name, title)

        try:
            msg = gr.message().make_from_string(json.dumps(d), -4, 0, 0)
            if not self.out_q.full_p():
                self.out_q.insert_tail(msg)
        except Exception:
            pass    # a dropped plot frame is not worth disturbing the flowgraph

    def set_center_freq(self, f):
        self.center_freq = f

    def set_relative_freq(self, f):
        self.relative_freq = f

    def set_offset(self, f):
        self.offset_freq = f

    def set_width(self, w):
        self.width = w

class eye_sink_f(gr.sync_block):
    """
    """
    def __init__(self, debug = _def_debug, sps = _def_sps, plot_name = "", chan = 0, out_q = None):
        gr.sync_block.__init__(self,
            name="eye_sink_f",
            in_sig=[np.float32],
            out_sig=None)
        self.debug = debug
        self.sps = sps * _def_sps_mult
        self.gnuplot = wrap_gp(sps=self.sps, plot_name=plot_name, chan=chan, out_q=out_q)

    def set_sps(self, sps):
        self.sps = sps * _def_sps_mult
        self.gnuplot.set_sps(self.sps)

    def work(self, input_items, output_items):
        in0 = input_items[0]
        self.gnuplot.plot(in0, 100 * self.sps, mode='eye')
        return len(input_items[0])

    def kill(self):
        self.gnuplot.kill()

class constellation_sink_c(gr.sync_block):
    """
    """
    def __init__(self, debug = _def_debug, plot_name = "", chan = 0, out_q = None):
        gr.sync_block.__init__(self,
            name="constellation_sink_c",
            in_sig=[np.complex64],
            out_sig=None)
        self.debug = debug
        self.gnuplot = wrap_gp(plot_name=plot_name, chan=chan, out_q=out_q)

    def work(self, input_items, output_items):
        in0 = input_items[0]
        self.gnuplot.plot(in0, 1000, mode='constellation')
        return len(input_items[0])

    def kill(self):
        self.gnuplot.kill()

class fft_sink_c(gr.sync_block):
    """
    """
    def __init__(self, debug = _def_debug, plot_name = "", chan = 0, out_q = None):
        gr.sync_block.__init__(self,
            name="fft_sink_c",
            in_sig=[np.complex64],
            out_sig=None)
        self.debug = debug
        self.gnuplot = wrap_gp(plot_name=plot_name, chan=chan, out_q=out_q)
        self.next_due = time.time()

    def work(self, input_items, output_items):
        now = time.time()
        if now > self.next_due:
            self.next_due = now + self.gnuplot.compute_interval(FFT_FREQ)
            in0 = input_items[0]
            self.gnuplot.plot(in0, FFT_BINS, mode='fft')
        return len(input_items[0])

    def kill(self):
        self.gnuplot.kill()

    def set_center_freq(self, f):
        self.gnuplot.set_center_freq(f)
        self.gnuplot.set_relative_freq(0.0)

    def set_relative_freq(self, f):
        self.gnuplot.set_relative_freq(f)

    def set_offset(self, f):
        self.gnuplot.set_offset(f)

    def set_width(self, w):
        self.gnuplot.set_width(w)

class mixer_sink_c(gr.sync_block):
    """
    """
    def __init__(self, debug = _def_debug, plot_name = "", chan = 0, out_q = None):
        gr.sync_block.__init__(self,
            name="mixer_sink_c",
            in_sig=[np.complex64],
            out_sig=None)
        self.debug = debug
        self.gnuplot = wrap_gp(plot_name=plot_name, chan=chan, out_q=out_q)
        self.next_due = time.time()

    def work(self, input_items, output_items):
        now = time.time()
        if now > self.next_due:
            self.next_due = now + self.gnuplot.compute_interval(MIX_FREQ)
            in0 = input_items[0]
            self.gnuplot.plot(in0, FFT_BINS, mode='mixer')
        return len(input_items[0])

    def kill(self):
        self.gnuplot.kill()

    def set_width(self, w):
        self.gnuplot.set_width(w)

class fll_sink_c(gr.sync_block):
    """
    """
    def __init__(self, debug = _def_debug, plot_name = "", chan = 0, out_q = None):
        gr.sync_block.__init__(self,
            name="fll_sink_c",
            in_sig=[np.complex64],
            out_sig=None)
        self.debug = debug
        self.gnuplot = wrap_gp(plot_name=plot_name, chan=chan, out_q=out_q)
        self.next_due = time.time()

    def work(self, input_items, output_items):
        now = time.time()
        if now > self.next_due:
            self.next_due = now + self.gnuplot.compute_interval(MIX_FREQ)
            in0 = input_items[0]
            self.gnuplot.plot(in0, FFT_BINS, mode='fll')
        return len(input_items[0])

    def kill(self):
        self.gnuplot.kill()

    def set_width(self, w):
        self.gnuplot.set_width(w)

class symbol_sink_f(gr.sync_block):
    """
    """
    def __init__(self, debug = _def_debug, plot_name = "", chan = 0, out_q = None):
        gr.sync_block.__init__(self,
            name="symbol_sink_f",
            in_sig=[np.float32],
            out_sig=None)
        self.debug = debug
        self.gnuplot = wrap_gp(plot_name=plot_name, chan=chan, out_q=out_q)

    def work(self, input_items, output_items):
        in0 = input_items[0]
        self.gnuplot.plot(in0, 2400, mode='symbol')
        return len(input_items[0])

    def kill(self):
        self.gnuplot.kill()
