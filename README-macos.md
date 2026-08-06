# Running OP25 on macOS

Tested on Apple Silicon with Homebrew GNURadio 3.10 and an RTL-SDR Blog V4.
Intel Macs use the same steps; only the Homebrew prefix differs
(`/usr/local` instead of `/opt/homebrew`).

## What works

Decoding, trunking, the web GUI, signal plots, **browser audio** and **local
speaker output** all work on macOS.

Local audio goes through PortAudio (CoreAudio underneath), because
`sockaudio.py`'s other two backends — ALSA (`libasound.so.2`) and PulseAudio
(`libpulse-simple.so.0`) — are Linux-only shared libraries. The backend is
selected automatically, so a config written for Linux that says
`"device_name": "pulse"` still works here; you will just see

```
audio: 'pulse' is Linux-only, using PortAudio on darwin
audio: using portaudio sound system
portaudio: output 'MacBook Pro Speakers' 8000Hz 2ch latency 102ms prime 120ms
```

`device_name` can also name a backend (`portaudio`, `coreaudio`) or a specific
PortAudio output device by name or numeric index; `default` uses the system
default output.

If PortAudio is missing entirely, op25 logs `no working sound system found,
local audio disabled` and carries on without sound rather than failing.

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
   `spdlog`, `cmake`, `pybind11`, `cppunit`, `doxygen`,
   `pkg-config`. (`gr-osmosdr` is not in homebrew-core, hence the tap.)
2. Create a virtualenv at `op25/gr-op25_repeater/apps/.venv`, seeded from the
   Python inside Homebrew's gnuradio formula so the ABI matches.
3. Copy Homebrew's `homebrew-gnuradio.pth` / `homebrew_gr_plugins.py` into that
   venv and add a `.pth` for `/opt/homebrew/lib/pythonX.Y/site-packages`, so
   `import gnuradio`, `import osmosdr` and `import gnuradio.op25_repeater` all
   resolve. This path-plumbing is the fiddly part of a Mac install and the most
   likely thing to break after a `brew upgrade`.
4. `pip install` numpy, requests, fastapi, `uvicorn[standard]` and
   `sounddevice`. The last one provides local speaker
   output via PortAudio; its macOS wheel bundles libportaudio, so no Homebrew
   package is needed.
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
         requests fastapi uvicorn sounddevice; do
    printf '%-24s ' "$m"
    $(cat op25_python) -c "import $m; print('OK')" 2>&1 | tail -1
done
```

All eleven must print `OK`. Anything else means the `.pth` plumbing from step 2
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

- The config above has **no `audio` section**, so audio plays in the browser
  only. The section is optional (`multi_rx.py` reads it `if "audio" in config`).
  To hear audio from the Mac's own speakers instead, add:
  ```json
  "audio": {
      "module": "sockaudio.py",
      "instances": [
          { "instance_name": "audio0", "device_name": "default",
            "udp_port": 23456, "audio_gain": 1.0, "number_channels": 1 }
      ]
  }
  ```
  Set `audio_gain` explicitly — it defaults to `0.0`, which is silence.
- **To get local speakers *and* browser audio at once**, give the channel a
  second UDP destination. A unicast UDP port has only one consumer, so local
  audio takes 23456 and the web server picks up the spare automatically:
  ```json
  "destination": "udp://127.0.0.1:23456, udp://127.0.0.1:23458"
  ```
  With only one destination and an `audio` section, local audio wins and the
  server logs that browser audio is disabled, telling you exactly this. If you
  need to pin the server to a specific port rather than let it choose, set
  `"audio_ports": [23458]` in the `terminal` block.
- `"args": "rtl=00000001"` selects the dongle by serial — take it from the
  `SN:` field in `rtl_test -t` output. Plain `"rtl"` also works with one dongle.
- `gains` values must be **integers**: `"LNA:49"` is fine, `"LNA:49.6"` aborts
  at startup with `invalid literal for int()`.
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

`pcm=0` after real traffic means nothing is arriving on the port the server
bound. Check the `ws audio: listening on udp ...` lines at startup against your
channel's `destination`. If you also configured local audio on the same port,
look for the message saying browser audio was disabled — that is the
one-consumer-per-port rule, and the fix is the second destination described
above. `underruns` simply count silence padding between transmissions and are
expected on a quiet system. You can also grab the raw stream directly,
bypassing the browser:

```bash
curl --max-time 20 http://127.0.0.1:8080/api/stream -o /tmp/op25.wav
afplay /tmp/op25.wav
```

**No sound from the Mac's speakers.** Check which backend was chosen — you want
`audio: using portaudio sound system` followed by a `portaudio: output ...`
line naming your device. `no working sound system found` means the
`sounddevice` module is missing; reinstall with
`$(cat op25_python) -m pip install sounddevice`. If audio is choppy, raise the
jitter buffer: `OP25_PORTAUDIO_PRIME_MS=240 ./op25.sh`. And check `audio_gain`
is set — it defaults to `0.0`.

**Signal plots stay empty.** Toggle a mode in the Signal Plots card; the
decoder only generates a plot once asked. Plots never involve `gnuplot` — the
browser draws them from the raw data stream, and the gnuplot subprocess was
removed along with the legacy UI. If a mode stays blank, check `stderr.2` for
errors from the plot sink. Plots require the `ws:` terminal; under curses the
toggle is a no-op and says so.
