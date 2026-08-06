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

**1. Install and start it.** On first run the add-on writes a working sample
config for you, so there is nothing to place beforehand. It is set up for the
**Palmetto 800** P25 system in South Carolina — if that is not your system it
will run without locking, which is harmless.

**2. Edit that config for your system.** It lands at `/config/op25.json`
*inside* the add-on. Reaching it from outside is the genuinely awkward part of
Home Assistant OS, because there is no host shell. Pick whichever of these you
already have:

| Method | Where the file appears |
|---|---|
| **Samba share** add-on | the `addon_configs` share → `<slug>_op25/op25.json`. If you only see `config`, `share`, `media`… your Samba add-on predates `addon_configs` — update it. |
| **Studio Code Server** or **File editor** add-on | needs its own config changed to see other add-ons' directories; simplest is to point OP25 at `/share` instead (below) |
| **Advanced SSH & Web Terminal** add-on | `/addon_configs/<slug>_op25/` with Protection mode **off** |

`<slug>` is a hash for a repository add-on, so expect a directory like
`a1b2c3d4_op25`. Just look for the one ending in `_op25`.

**If none of that is convenient, use `/share` instead.** That share is visible
to essentially every file-access add-on. Set the options:

```yaml
config_file: /share/op25/op25.json
work_dir: /share/op25
```

and put your JSON and `.tsv` files in the `op25` folder of the `share` share.

Whichever you choose, **`.tsv` talkgroup tag files must sit in `work_dir`** —
paths inside the config resolve against it, not against the config file. Without
them you get talkgroup numbers instead of names, which is a soft failure.

The pristine sample is always in the image at
`/opt/op25/samples/op25.sample.json`.

**3. Only if you have more than one SDR: pin the serial.** With a single
dongle the sample's `"args": "rtl"` selects it and there is nothing to do. With
several, read the log — the pre-flight runs `rtl_test -t` and prints each
device's serial — then set:

```yaml
device_overrides:
  - name: sdr0          # must match a "name" in your config's devices[]
    serial: "00000101"
```

This rewrites that device's `args` to `rtl=<serial>` without you editing the
JSON, which is handy when hardware moves between machines.

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
