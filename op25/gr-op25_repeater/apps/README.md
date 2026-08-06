
This file contains notes on the OP25 multi receiver (`multi_rx.py`), which is
the only receiver app in this fork. The older single-receiver `rx.py` and its
command-line interface were removed — everything is configured through a JSON
file now.

## Example command line

```
./multi_rx.py -v 1 -c p25_rtl_example.json 2> stderr.2
```

Running stderr to a file (e.g., `2> stderr.2`) is recommended: all logging goes
to stderr, and under the curses terminal it would otherwise corrupt the screen.

```
Usage: multi_rx.py [options]

Options:
  -h, --help            show this help message and exit
  -c CONFIG_FILE, --config-file=CONFIG_FILE
                        specify config file name ('-' reads JSON from stdin)
  -v VERBOSITY, --verbosity=VERBOSITY
                        message debug level
  -p, --pause           block on startup
```

Paths inside the config (tag files, whitelists, `crypt_keys`) are opened
relative to the **current working directory**, not to the config file, so run
from the directory holding them or use absolute paths.

## Terminal types

`multi_rx.py` picks its terminal from the `terminal` block of the JSON config:

| `module` | `terminal_type` | Result |
|---|---|---|
| `websocket_server.py` | `ws:<host>:<port>` | **Web GUI** — React SPA, FastAPI/uvicorn, single port. See [README-new-gui.md](../../../README-new-gui.md). |
| `terminal.py` | `curses` | Text UI in the terminal (keys below). |
| `terminal.py` | `<udp port>` | Headless; attach `terminal.py <host> <port>` later. |

The older `http:<host>:<port>` terminal (waitress + the `www-static` UI) was
removed. A config that still names it prints a message pointing at the `ws:`
replacement and then runs headless.

## Terminal Operation

Keyboard commands in the curses terminal:

- `B`: dynamically add tgid to blacklist
- `d`: dump list of known tgids to log
- `h`: hold
- `H`: hold/goto the specified tgid
- `l`: lockout
- `q`: quit program
- `s`: skip
- `v`: dynamically change log level
- `W`: dynamically add tgid to Whitelist
- `,`: decrease fine tune by 100Hz
- `.`: increase fine tune by 100Hz
- `<`: decrease fine tune by 1200Hz
- `>`: increase fine tune by 1200Hz
- `1` … `6`: toggle fft / constellation / symbol / datascope / raw mixer /
  tuned mixer plots — **`ws:` terminal only**, see Plot Modes below
- <cursor left> / <cursor right>: cycle through available receivers

## Remote Terminal

Set `"terminal_type"` to a bare UDP port number and `multi_rx.py` runs in the
foreground with no attached terminal (hit CTRL-C to end it). To connect a
curses view to the running instance:

```
./terminal.py 127.0.0.1 56111
```

**Note:** the two need not run on the same machine, and the machine running
`terminal.py` needs no SDR — but GNU Radio (and OP25) must be available.

**Warning:** there is no security or encryption on the UDP port.

## Audio

Local speaker output is the `audio` block (`"module": "sockaudio.py"`), which
plays PCM arriving on a UDP port. Browser audio is served by the `ws:` terminal
re-streaming the same kind of UDP port over HTTP.

A unicast UDP port has exactly one consumer, so the two cannot share one — see
[README-browser-audio.md](../../../README-browser-audio.md) for the
dual-destination arrangement that runs both.

The decoder can also simply be pointed at any UDP listener:

```
nc -kluvw 1 127.0.0.1 23456 | aplay -c1 -f S16_LE -r 8000
vlc.exe --clock-jitter=500 --network-caching=0 --demux=rawaud \
        --rawaud-channels 1 --rawaud-samplerate 8000 udp://@:23456
```

**Note:** audio underruns are expected with `nc | aplay`, since the PCM stream
stops every time a transmission ends. `sockaudio.py` handles that gracefully.

## Plot Modes

Six plot types: `fft`, `constellation`, `symbol`, `datascope`, `mixer`, `fll`.
Symbol and datascope work in both fsk4 and cqpsk modes; constellation requires
cqpsk.

Plots are **rendered by the browser** from raw trace data over the WebSocket, so
they require the `ws:` terminal. There is no gnuplot process any more — under
curses or a UDP terminal the toggle is a no-op and says so on stderr. Rate is
`http_plot_interval` (default 1.0s) for `ws:`.

## Multi-receiver

`multi_rx.py` allows an arbitrary number of SDR devices and channels to be
defined. Each channel may have one or more plots attached.

Configuration is via a JSON file (see `cfg.json`). Channels are automatically
assigned to the first device found whose frequency span includes the selected
frequency.

P25 Trunking, Motorola SmartNet/SmartZone and DMR/Connect+ are supported.

Below is a summary of the major config file keys used under the channel section:
```
demod_type:     'cqpsk' for qpsk p25 only
                'fsk4' for ysf/dstar/dmr/fsk4 p25
                'fsk' for Smartnet/Smartzone control channel
filter_type:    'rc' for p25; 'rrc' for dmr and ysf; 'gmsk' for d-star
                'fsk' for Smartnet/Smartzone control channel
                'widepulse' for Smartnet/Smartzone P25CAI voice
plot:           'fft', 'constellation', 'datascope', 'symbol', 'mixer', 'fll'
                [if more than one plot desired, provide a comma-separated list]
destination:    'udp://host:port' [comma-separated list for multiple sinks]
name:           arbitrary string used to identify channels and devices
```

**Note:** DMR audio for the second time slot is sent on the specified port
number plus two. In the example `udp://127.0.0.1:56122`, audio for the first
slot would use 56122; and 56124 for the second.

## Encryption

P25 ADP/RC4 (algid `0xAA`), DES-OFB (algid `0x81`) and AES-OFB (algid `0x84`)
decryption with a known key is supported. See the example configurations:
`p25_rtl_example.json`, `p25_conventional_example.json` and also the example
json formatting of the keys file: `example_keys.json`.
