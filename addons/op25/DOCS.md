# OP25 Trunking Scanner

Runs the OP25 P25/DMR/SmartNet decoder against a USB SDR and serves its web UI
through the Home Assistant sidebar.

## Before you start

You need an SDR that librtlsdr supports, plugged into the Home Assistant host.
The RTL-SDR Blog V4 works out of the box on this image (Debian trixie ships
librtlsdr 2.0.2).

On **x86-64** Home Assistant OS the DVB driver for these dongles is not built,
so unlike a normal Debian install there is nothing to blacklist — nothing can
claim the device before OP25 does. (Checked against HA OS 18.2, kernel 6.18.39:
`CONFIG_DVB_USB_RTL28XXU` appears only in the arm64-rockchip kernel fragment.)

On an **arm64 Rockchip** board it *is* built as a module, and may grab the
dongle first. HA OS ignores `/etc/modprobe.d`, so that cannot be solved from
inside the add-on.

## Setup

**1. Install, but do not start yet.**

**2. Put a config where the add-on can find it.** OP25 is configured by a JSON
file that is far too structured for add-on options — per-channel demodulator
parameters, control-channel lists, talkgroup tag files, crypt keys. Copy yours
into the add-on's config directory, which appears over Samba as:

```
addon_configs/<slug>_op25/op25.json
```

Copy any `.tsv` talkgroup tag files it references into the same directory:
paths inside the config are resolved relative to `work_dir` (`/config` by
default), not to the config file.

A starting point ships in the image at `/opt/op25/samples/op25.sample.json`.

**3. Set your dongle's serial.** Start the add-on once and read the log — the
pre-flight step runs `rtl_test -t` and prints every device it can see. Then set:

```yaml
device_overrides:
  - name: sdr0          # must match a "name" in your config's devices[]
    serial: "00000101"
```

This is a convenience so you do not have to edit the JSON when hardware moves;
it rewrites that device's `args` to `rtl=<serial>`.

> `rtl_test -t` always ends with `No E4000 tuner found, aborting.` That is an
> E4000-only benchmark declining to run, **not** a failure. What matters is the
> `Found 1 device(s)` line above it.

**4. Start it,** and open OP25 from the sidebar.

## Options

| Option | Default | Meaning |
|---|---|---|
| `config_file` | `/config/op25.json` | The multi_rx JSON config |
| `work_dir` | `/config` | Working directory. Tag files, whitelists and crypt keys resolve against this |
| `verbosity` | `1` | Decoder log level, 0–10 |
| `audio_output` | `browser` | `browser` streams audio to the UI. `alsa` sends it to a local sound device instead, which needs one mapped in. `none` disables it |
| `device_overrides` | `[]` | Per-device `serial` / `gains` / `ppm` overrides, matched on `name` |
| `home_assistant.use_supervisor` | `true` | Use the Supervisor proxy for speech-to-text, so no long-lived token is needed |
| `home_assistant.url` / `.token` | — | Point at a different Home Assistant instead |
| `dev_source_dir` | — | Run the Python from a checkout instead of the image (see below) |
| `extra_json` | `{}` | Merged over the rendered config, as an escape hatch |

The add-on always overrides `terminal.module`, `terminal.terminal_type` and
`audio.module` in the rendered config — the UI has to be reachable on the
ingress port, and the curses terminal is meaningless in a container. Your file
on disk is never rewritten.

## Audio

`audio_output: browser` leaves the UDP audio port free for the web UI to
re-stream. This matters because a unicast UDP port has exactly one consumer: if
you switch to `alsa`, the local player claims the port and browser audio goes
quiet unless you give the channel a second destination. See
`README-browser-audio.md` in the repository.

## Development loop

Set `dev_source_dir` to a checkout, for example `/share/op25/src`, and the
add-on runs `multi_rx.py` and friends from there instead of from the image.
Restart the add-on to pick up an edit. The compiled GNU Radio blocks still come
from the image, so C++ changes need a rebuild.

## Troubleshooting

**"Config file not found"** — the add-on refuses to start without one, on
purpose. See step 2.

**No devices in the log** — check `usb: true` is honoured (the pre-flight step
says whether `/dev/bus/usb` is visible), and that nothing else on the host holds
the dongle.

**UI loads but no audio** — check `/api/audio/channels` through the ingress
panel. An empty list means no UDP destination was discovered; the most common
cause is `audio_output: alsa` claiming the only port.

**Do not point Home Assistant media players at an ingress URL.** Ingress URLs
carry a rotating per-session token that only an authenticated browser has. Use
the direct port (8099) for anything that fetches audio itself.
