# Running OP25 on macOS

Tested on Apple Silicon with Homebrew GNURadio 3.10 and an RTL-SDR Blog V4.
Intel Macs use the same steps; only the Homebrew prefix differs
(`/usr/local` instead of `/opt/homebrew`).

## What works, and the one thing that doesn't

Decoding, trunking, the web GUI and **browser audio** all work on macOS.

The one real limitation: **there is no local speaker output.** `sockaudio.py`
talks to ALSA (`libasound.so.2`) or PulseAudio (`libpulse-simple.so.0`)
directly via ctypes — both are Linux-only shared libraries. On macOS neither
loads, so the audio module prints

```
unable to load PulseAudio library
unable to load ALSA library
```

and continues with no sound device. It does not crash, but you get silence.

**Listen in the browser instead.** The `audio` section of the config is
optional (`multi_rx.py` only reads it `if "audio" in config`), so leave it out
entirely on macOS and let the web GUI play the stream. This is why
`cfg.json` — which ships an `audio` block with `"device_name": "pulse"` — is a
poor starting point on a Mac.

## 1. Prerequisites

[Homebrew](https://brew.sh). `install-mac.sh` will install it for you if it is
missing, but having it already set up is simpler.

## 2. Install

```bash
git clone https://github.com/boatbod/op25
cd op25
./install-mac.sh          # add -f to skip the confirmation prompt
```

The script must be run from the repository root. It will:

1. Tap `trunkrecorder/install` and install the Homebrew dependencies —
   `gnuradio`, `gr-osmosdr`, `librtlsdr`, `hackrf`, `airspy`, `libsndfile`,
   `spdlog`, `cmake`, `pybind11`, `cppunit`, `gnuplot`, `doxygen`,
   `pkg-config`. (`gr-osmosdr` is not in homebrew-core, hence the tap.)
2. Create a virtualenv at `op25/gr-op25_repeater/apps/.venv`, seeded from the
   Python inside Homebrew's gnuradio formula so the ABI matches.
3. Copy Homebrew's `homebrew-gnuradio.pth` / `homebrew_gr_plugins.py` into that
   venv and add a `.pth` for `/opt/homebrew/lib/pythonX.Y/site-packages`, so
   `import gnuradio`, `import osmosdr` and `import gnuradio.op25_repeater` all
   resolve. This path-plumbing is the fiddly part of a Mac install and the most
   likely thing to break after a `brew upgrade`.
4. `pip install` numpy, waitress, requests, websockets, fastapi,
   `uvicorn[standard]`.
5. Write the venv's interpreter path into
   `op25/gr-op25_repeater/apps/op25_python`.
6. Configure and build with cmake, then `sudo make install` into the Homebrew
   prefix.

It does **not** build the web frontend — see step 5 below.

## 3. Verify the install

Check the dongle:

```bash
rtl_test -t
```

Expect `Found 1 device(s)`, your tuner, and for a V4 the line
`RTL-SDR Blog V4 Detected`. `rtl_test -t` then ends with
`No E4000 tuner found, aborting.` — **that is normal**, not a failure; `-t`
only knows how to probe E4000 tuners.

Check the Python side:

```bash
cd op25/gr-op25_repeater/apps
for m in numpy gnuradio osmosdr gnuradio.op25_repeater gnuradio.op25 \
         waitress requests websockets fastapi uvicorn; do
    printf '%-24s ' "$m"
    $(cat op25_python) -c "import $m; print('OK')" 2>&1 | tail -1
done
```

All ten must print `OK`. Anything else means the `.pth` plumbing from step 2
didn't take — re-run `./install-mac.sh`.

## 4. Configure

All configuration lives in `op25/gr-op25_repeater/apps/`. See
`README-configuration.md` there for the full reference. A minimal
Mac-friendly single-dongle P25 trunking config:

```json
{
    "devices": [
        {
            "name": "sdr0",
            "args": "rtl=00000001",
            "frequency": 860337500,
            "gains": "LNA:39",
            "gain_mode": false,
            "offset": 0,
            "ppm": 0.0,
            "rate": 1000000,
            "usable_bw_pct": 0.85,
            "tunable": true
        }
    ],
    "channels": [
        {
            "name": "My System",
            "device": "sdr0",
            "trunking_sysname": "MySystem",
            "demod_type": "cqpsk",
            "filter_type": "rc",
            "excess_bw": 0.2,
            "destination": "udp://127.0.0.1:23456",
            "if_rate": 24000,
            "symbol_rate": 4800,
            "enable_analog": "off"
        }
    ],
    "trunking": {
        "module": "tk_p25.py",
        "chans": [
            {
                "sysname": "MySystem",
                "control_channel_list": "860.33750,853.53750",
                "tgid_tags_file": "my_tags.tsv",
                "nac": "0x0",
                "crypt_behavior": 2
            }
        ]
    },
    "terminal": {
        "module": "websocket_server.py",
        "terminal_type": "ws:0.0.0.0:8080"
    }
}
```

Points that matter on macOS:

- **No `audio` section.** See the caveat above.
- `"args": "rtl=00000001"` selects the dongle by serial — take it from the
  `SN:` field in `rtl_test -t` output. Plain `"rtl"` also works with one dongle.
- `"destination": "udp://127.0.0.1:23456"` is what the browser audio path
  reads. `websocket_server.py` currently discovers audio ports from a config it
  does not actually load when run under `multi_rx.py`, so it falls back to
  `23456`/`23457` — **keep 23456 or browser audio will be silent.**
- `terminal.module` selects the UI stack. `websocket_server.py` with
  `ws:host:port` is the current React GUI. The older stack is `terminal.py`
  with `http:host:port`, and `terminal.py` with `curses` gives a TUI (curses
  works fine on macOS).

Note that `apps/.gitignore` excludes `*.json` and `*.tsv`, so your configs stay
local and untracked.

## 5. Build the web GUI

Needed once, and again after any change under `www/app/src`:

```bash
cd op25/gr-op25_repeater/www/app
yarn install
yarn build            # → ../dist
```

## 6. Run

```bash
cd op25/gr-op25_repeater/apps
$(cat op25_python) multi_rx.py -c my_config.json -v 1 2> stderr.2
```

Then open <http://localhost:8080>.

Always launch with the interpreter recorded in `op25_python` — the system
`python3` cannot see the GNURadio modules. Raise `-v` for more log detail;
`-v 10` adds encryption sync info.

Startup is healthy when `stderr.2` shows your device, then a control-channel
lock in the `trunk_update` top line, e.g.

```
Using device #0 RTLSDRBlog Blog V4 SN: 00000001
RTL-SDR Blog V4 Detected
WebSocket terminal server starting on 0.0.0.0:8080
P25  System BEE00.1D9  Site 2.40  NAC 1D1  CC 860.337500  tsbks 116
```

A few `control channel timeout` lines while it walks the
`control_channel_list` are normal; continuous timeouts are not — see below.

## Troubleshooting

**`import gnuradio` fails after `brew upgrade`.** Homebrew may have moved
gnuradio onto a new Python minor version, leaving the venv and its `.pth`
pointing at the old `site-packages`. Re-run `./install-mac.sh`.

**`usb_claim_interface error -6`, or the device is busy.** Something else holds
the dongle. Most often a previous run that didn't exit — `pkill -f multi_rx.py`.

**No supported devices found** while the dongle is plugged in: same cause.
Unlike Linux, macOS needs no DVB kernel-module blacklist (`blacklist-rtl.conf`
is Linux-only), so a stray process is almost always the answer.

**Continuous `control channel timeout`.** The receiver never locks. Check the
antenna, then that `control_channel_list` is right for your area, then gain —
`"gains": "LNA:39"` is a starting point, and `"gain_mode": true` enables AGC.
Confirm the dongle itself is healthy with `rtl_test -t` first.

**Web page loads but shows no data.** The page is served but the WebSocket
bridge isn't delivering. Check `stderr.2` for a `ws_terminal:` traceback, and
confirm the port: static files and the control WebSocket share the single port
from `terminal_type` (`ws://host:8080/ws`). The legacy `http:` stack is
different — there the control WebSocket is on **port + 1**.

**Browser plays no audio.** Confirm bytes are arriving from the decoder — the
server logs throughput once a second:

```
ws audio: rx pcm=54 flag=97 ... pushed=17280 yielded=60480 underruns=162
```

`pcm=0` after real traffic means the UDP port doesn't match; check the
`destination` port is 23456. `underruns` simply count silence padding between
transmissions and are expected on a quiet system. You can also grab the raw
stream directly, bypassing the browser:

```bash
curl --max-time 20 http://127.0.0.1:8080/api/stream -o /tmp/op25.wav
afplay /tmp/op25.wav
```

**Signal plots stay empty.** Expected — plots are not yet implemented for the
`ws:` terminal, regardless of platform. `gnuplot` is installed for the legacy
`http:` stack, which does render them.
