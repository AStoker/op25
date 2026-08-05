#!/usr/bin/env python3
from gnuradio import gr, audio, eng_notation, blocks
import argparse

class app_top_block(gr.top_block):
    def __init__(self, options):
        gr.top_block.__init__(self)

        IN = blocks.file_source(gr.sizeof_char, options.input_file)
        bits_per_symbol = 2
        UNPACK = blocks.packed_to_unpacked_bb(bits_per_symbol, gr.GR_MSB_FIRST)
        OUT = blocks.file_sink(gr.sizeof_char, options.output)

        self.connect(IN, UNPACK, OUT)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input-file", type=str, default="in.dat", help="specify the input file")
    parser.add_argument("-o", "--output", type=str, default="out.dat", help="specify the output file")

    options = parser.parse_args()
 
    tb = app_top_block(options)
    try:
        tb.run()
    except KeyboardInterrupt:
        tb.stop()

if __name__ == "__main__":
    main()
