#!/usr/bin/env python

import sys
import math
from gnuradio import gr, audio, eng_notation, filter, blocks
from gnuradio import analog, digital
import argparse

def eng_float(v):
    try:
        return eng_notation.str_to_num(str(v))
    except:
        raise argparse.ArgumentTypeError(f"invalid value: {v}")

class my_top_block(gr.top_block):
    def __init__(self):
        gr.top_block.__init__(self)
        parser = argparse.ArgumentParser()

        parser.add_argument("-c", "--calibration", type=eng_float, default=0, help="freq offset")
        parser.add_argument("-g", "--gain", type=eng_float, default=1)
        parser.add_argument("-i", "--input-file", type=str, default="in.dat", help="specify the input file")
        parser.add_argument("-o", "--output-file", type=str, default="out.dat", help="specify the output file")
        parser.add_argument("-r", "--new-sample-rate", type=int, default=96000, help="output sample rate")
        parser.add_argument("-s", "--sample-rate", type=int, default=48000, help="input sample rate")
        options = parser.parse_args()
 
        sample_rate = options.sample_rate
        new_sample_rate = options.new_sample_rate

        IN = blocks.file_source(gr.sizeof_gr_complex, options.input_file)
        OUT = blocks.file_sink(gr.sizeof_gr_complex, options.output_file)

        LO = analog.sig_source_c(sample_rate, analog.GR_COS_WAVE, options.calibration, 1.0, 0)
        MIXER = blocks.multiply_cc()

        AMP = blocks.multiply_const_cc(options.gain)

        nphases = 32
        frac_bw = 0.05
        p1 = frac_bw
        p2 = frac_bw
        rs_taps = filter.firdes.low_pass(nphases, nphases, p1, p2)
        RESAMP = filter.pfb_arb_resampler_ccf(float(new_sample_rate) / float(sample_rate), (rs_taps), nphases, )

        self.connect(IN, (MIXER, 0))
        self.connect(LO, (MIXER, 1))

        self.connect(MIXER, AMP, RESAMP, OUT)

if __name__ == "__main__":
    try:
        my_top_block().run()
    except KeyboardInterrupt:
        tb.stop()
