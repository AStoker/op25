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

import sys
import os
import time
import subprocess
import json

import shutil

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

GNUPLOT = shutil.which('gnuplot') or '/usr/bin/gnuplot'

Y_AVG    = 0.03
FFT_AVG  = 0.05
MIX_AVG  = 0.10
BAL_AVG  = 0.05
FFT_BINS = 512    # number of fft bins
FFT_FREQ = 0.05   # time interval between fft updates
MIX_FREQ = 0.02   # time interval between mixer updates

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
        self.sequence = 0
        self.output_dir = None
        self.filename = None
        self.chan = chan
        self.out_q = out_q
        if plot_name == "":
            self.plot_name = ""
        else:
            self.plot_name = plot_name + " "

        self.gp = None
        if out_q is None:   # only need gnuplot when not using the web-UI queue
            self.attach_gp()

    def attach_gp(self):
        args = [GNUPLOT]
        exe  = GNUPLOT
        self.gp = subprocess.Popen(args, executable=exe, stdin=subprocess.PIPE)

    def set_sps(self, sps):
        self.sps = int(sps)

    def kill(self):
        try:
            if self.gp is not None:
                self.gp.stdin.close()   # closing pipe should cause subprocess to exit
        except IOError:
            pass
        if self.out_q is not None:
            self.out_q.flush()
        self.out_q = None
        if self.gp is None:
            return
        sleep_count = 0
        while True:                     # wait politely, but only for so long
            self.gp.poll()
            if self.gp.returncode is not None:
                break
            time.sleep(0.1)
            sleep_count += 1
            if (sleep_count % 5) == 0:
                self.gp.kill()

    def set_interval(self, v):
        self.plot_interval = v

    def set_output_dir(self, v):
        self.output_dir = v
        # The http terminal serves gnuplot-rendered PNGs, so it needs a gnuplot
        # process even though out_q is set (which otherwise means the front-end
        # draws the plot itself and gnuplot can be skipped entirely).
        if v and self.gp is None:
            self.attach_gp()

    def plot(self, buf, bufsz, mode='eye'):
        BUFSZ = bufsz
        consumed = min(len(buf), BUFSZ-len(self.buf))
        if len(self.buf) < BUFSZ:
            self.buf = np.concatenate((self.buf, buf[:int(consumed)]))
        if len(self.buf) < BUFSZ:
            return consumed

        self.plot_count += 1
        if mode == 'eye' and self.plot_count % 20 != 0:
            self.buf = np.array([])
            return consumed

        plots = []
        s = ''
        traces = []     # numeric (xs, ys) series for the web UI
        while(len(self.buf)):
            if mode == 'eye':
                if len(self.buf) < self.sps:
                    break
                trace = np.asarray(self.buf[:self.sps], dtype=float)
                # x is the position within the trace so the web UI overlays the
                # traces into an eye diagram, as gnuplot does with separate lines.
                traces.append((np.arange(len(trace), dtype=float), trace))
                if self.gp is not None:
                    for i in range(self.sps):
                        s += '%f\n' % self.buf[i]
                    s += 'e\n'
                self.buf=self.buf[self.sps:]
                plots.append('"-" with lines')
            elif mode == 'constellation':
                arr = np.asarray(self.buf)
                traces.append((arr.real.astype(float), arr.imag.astype(float)))
                if self.gp is not None:
                    for b in self.buf:
                        s += '%f\t%f\n' % (b.real, b.imag)
                    s += 'e\n'
                self.buf = []
                plots.append('"-" with points')
            elif mode == 'symbol':
                arr = np.asarray(self.buf, dtype=float)
                traces.append((np.arange(len(arr), dtype=float), arr))
                if self.gp is not None:
                    for b in self.buf:
                        s += '%f\n' % (b)
                    s += 'e\n'
                self.buf = []
                plots.append('"-" with points')
            elif mode == 'fft' or mode == 'mixer' or mode == 'fll':
                sum_pwr = 0.0
                self.ffts = np.fft.fft((self.buf * np.blackman(BUFSZ)), BUFSZ , 0) / (0.42 * BUFSZ)
                self.ffts = np.fft.fftshift(self.ffts)
                self.freqs = np.fft.fftfreq(len(self.ffts))
                self.freqs = np.fft.fftshift(self.freqs)
                tune_freq = (self.center_freq - self.relative_freq) / 1e6
                if self.center_freq and self.width:
                                    self.freqs = ((self.freqs * self.width) + self.center_freq + self.offset_freq) / 1e6
                elif self.width:
                                    self.freqs = (self.freqs * self.width)
                fft_xs = []
                fft_ys = []
                for i in range(len(self.ffts)):
                    if mode == 'fft':
                        self.avg_pwr[i] = ((1.0 - FFT_AVG) * self.avg_pwr[i]) + (FFT_AVG * np.abs(self.ffts[i]))
                    else:
                        self.avg_pwr[i] = ((1.0 - MIX_AVG) * self.avg_pwr[i]) + (MIX_AVG * np.abs(self.ffts[i]))
                    if self.avg_pwr[i] == 0: # guard against divide by zero
                        break
                    y_val = 20 * np.log10(self.avg_pwr[i])
                    fft_xs.append(self.freqs[i])
                    fft_ys.append(y_val)
                    if self.gp is not None:
                        s += '%f\t%f\n' % (self.freqs[i], y_val)
                    if ((mode == 'mixer') or (mode == 'fll')) and (self.avg_pwr[i] > 1e-5):
                        if (self.freqs[i] - self.center_freq) < 0:
                            sum_pwr -= self.avg_pwr[i]
                        elif (self.freqs[i] - self.center_freq) > 0:
                            sum_pwr += self.avg_pwr[i]
                s += 'e\n'
                self.buf = []
                traces.append((fft_xs, fft_ys))
                plots.append('"-" with lines')
                if min(self.avg_pwr) == 0: # plot is broken, probably because source device was missing
                    return consumed
                min_y = 20 * np.log10(min(self.avg_pwr))
                self.min_y = ((1.0 - Y_AVG) * self.min_y) + (Y_AVG * min_y) 
        self.buf = []

        # FFT processing needs to be completed to maintain the weighted average buckets
        # regardless of whether we actually produce a new plot or not.
        if self.plot_interval and self.last_plot + self.plot_interval > time.time():
            return consumed
        self.last_plot = time.time()

        filename = None
        if self.output_dir:
            if self.sequence >= 2:
                delete_pathname = '%s/plot-%d-%s-%d.png' % (self.output_dir, self.chan, mode, self.sequence-2)
                if os.access(delete_pathname, os.W_OK):
                    os.remove(delete_pathname)
            h= 'set terminal png\n'
            filename = 'plot-%d-%s-%d.png' % (self.chan, mode, self.sequence)
            self.sequence += 1
            h += 'set output "%s/%s"\n' % (self.output_dir, filename)
        else:
            h= 'set terminal x11 noraise\n'

        #background = 'set object 1 circle at screen 0,0 size screen 1 fillcolor rgb"black"\n' #FIXME!
        background = ''
        h+= 'set key off\n'
        if mode == 'constellation':
            h+= background
            h+= 'set size square\n'
            h+= 'set xrange [-1:1]\n'
            h+= 'set yrange [-1:1]\n'
            h+= 'set title "%sConstellation"\n' % self.plot_name
        elif mode == 'eye':
            h+= background
            h+= 'set yrange [-4:4]\n'
            h+= 'set title "%sDatascope"\n' % self.plot_name
        elif mode == 'symbol':
            h+= background
            h+= 'set yrange [-4:4]\n'
            h+= 'set title "%sSymbol"\n' % self.plot_name
        elif mode == 'fft' or mode == 'mixer' or mode =='fll':
            h+= 'unset arrow; unset title\n'
            h+= 'set xrange [%f:%f]\n' % (self.freqs[0], self.freqs[len(self.freqs)-1])
            h+= 'set xlabel "Frequency"\n'
            h+= 'set ylabel "Power(dB)"\n'
            h+= 'set grid\n'
            h+= 'set yrange [%d:0]\n' % ((self.min_y // 20) * 20)
            if mode == 'mixer':
                h+= 'set title "%sRaw Mixer\n' % self.plot_name
            elif mode == 'fll':
                h+= 'set title "%sTuned Mixer"\n' % self.plot_name
            else:               # fft
                if self.center_freq:
                    arrow_pos = (self.center_freq - self.relative_freq) / 1e6
                    h+= 'set arrow from %f, graph 0 to %f, graph 1 nohead\n' % (arrow_pos, arrow_pos)
                    h+= 'set title "%sSpectrum: tuned to %f Mhz"\n' % (self.plot_name, arrow_pos)
                else:
                    h+= 'set title "%sSpectrum"\n' % self.plot_name
        dat = '%splot %s\n%s' % (h, ','.join(plots), s)
        dat = bytes(dat, 'utf8')
        if self.gp is not None:
            self.gp.poll()
            if self.gp.returncode is None:  # make sure gnuplot is still running
                try:
                    self.gp.stdin.write(dat)
                    self.gp.stdin.flush()
                except (IOError, ValueError):
                    pass
        if filename:
            self.filename = filename

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
        data = []
        for xs, ys in traces:
            data.extend([[float(x), float(y)] for x, y in zip(xs, ys)])
        if not data:
            return

        # Decimate rather than truncate, so a long trace still spans its full
        # range instead of showing only the beginning.
        if len(data) > PLOT_MAX_POINTS:
            step = (len(data) + PLOT_MAX_POINTS - 1) // PLOT_MAX_POINTS
            data = data[::step]

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
        if time.time() > self.next_due:
            self.next_due = time.time() + FFT_FREQ
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
        if time.time() > self.next_due:
            self.next_due = time.time() + MIX_FREQ
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
        if time.time() > self.next_due:
            self.next_due = time.time() + MIX_FREQ
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
