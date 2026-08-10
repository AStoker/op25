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

**1. Install and start it.** There is nothing to place beforehand. The add-on
ships with a built-in config selected by the `preset` option, which defaults to
`palmetto800` — the **Palmetto 800** P25 system in South Carolina.

**If that is your system, you are done.** Set your dongle's serial under
`device_overrides` if you have more than one SDR (step 3), and skip the rest.
Because the preset lives inside the image rather than in a file on disk, fixes
to it — gain, sample rate, control-channel list — reach you when the add-on
updates.

**2. If you monitor something else,** set `preset: custom`. The add-on then
reads `config_file`, and on first run copies the palmetto800 preset there as a
starting point so you have something valid to edit. Change
`trunking.chans[].control_channel_list` and `nac` at minimum, or the receiver
runs without ever locking.

> A `custom` config is **yours**, which means the add-on never rewrites it — so
> it also never receives a fix. That is the trade: a preset tracks updates, a
> file does not. Prefer the add-on options (`device_overrides`,
> `home_assistant`, `audio_output`, `extra_json`) over copying a preset just to
> change one value.

The file lands at `/config/op25.json` *inside* the add-on. Reaching it from
outside is the genuinely awkward part of Home Assistant OS, because there is no
host shell. Pick whichever of these you already have:

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

The built-in presets are always in the image at `/opt/op25/presets/`. Reading
one is the quickest way to see what a working config looks like; every field
carries a `#`-prefixed note explaining why it is set the way it is. Those
`#` keys are documentation only and are stripped before the decoder sees
them.

**3. Only if you have more than one SDR: pin the serial.** With a single
dongle the preset's `"args": "rtl"` selects it and there is nothing to do. With
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
| `preset` | `palmetto800` | Use a config built into the image, which therefore tracks add-on updates. `custom` reads `config_file` instead |
| `config_file` | `/config/op25.json` | The multi_rx JSON config. Only read when `preset` is `custom` |
| `work_dir` | `/config` | Working directory. Tag files, whitelists and crypt keys resolve against this |
| `verbosity` | `1` | Decoder log level, 0–10 |
| `audio_output` | `browser` | `browser` streams audio to the UI. `alsa` sends it to a local sound device instead, which needs one mapped in. `none` disables it |
| `conceal_frames` | `3` | How many missing 20 ms voice frames the decoder repeats before leaving a gap silent, 0–3. `0` turns concealment off, so a dropout is a hard cut again |
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

## Finding a talkgroup

The talkgroup table shows when each one was last heard, on what frequency, and how
many calls it has carried. That history is kept in `op25_metadata.sqlite` in the
work directory, so it survives a restart — a tags file with two thousand entries
would otherwise read "never heard" every time the add-on came back. It is a cache:
deleting it loses history and nothing else.

**Browse** opens a picker over the full configured list. The list holds still
while it is open (the dashboard table re-sorts as traffic arrives, which is what
makes hunting for one talkgroup there so annoying), filters live by substring or
regex against both tag and TGID, and its header checkbox selects every current
match — so `^(FIRE|EMS)` then one click.

Selecting talkgroups only pins them to the top of the table. **Apply as scan list**
is a separate, explicit action, because it makes the decoder ignore everything
else — including for recording and transcription. The table marks off-list
talkgroups so it is obvious when one is in force, and the chip in the section
heading clears it.

## Development loop

Set `dev_source_dir` to a checkout, for example `/share/op25/src`, and the
add-on runs `multi_rx.py` and friends from there instead of from the image.
Restart the add-on to pick up an edit. The compiled GNU Radio blocks still come
from the image, so C++ changes need a rebuild.

To work on the **web UI** from a development machine instead, point Vite's proxy
at the add-on rather than copying builds around:

```bash
cd op25/gr-op25_repeater/www/app
OP25_BACKEND=http://homeassistant.local:8099 yarn dev
```

The browser only talks to `localhost:5173`; Vite forwards `/api` and `/ws`. Note
that port 8099 has **no authentication** — ingress is the authenticated path — so
this is for a network you trust, and it is a good reason to set the port to
`disabled` once the sidebar panel works.

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
