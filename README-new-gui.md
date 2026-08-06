# OP25 new GUI — FastAPI server and WebSocket protocol

This is the reference for the **current** web UI: a React SPA served by
`websocket_server.py` (FastAPI + uvicorn) on a **single port**.

Selected by the `terminal` block of the multi_rx JSON config:

```json
"terminal": {
    "module": "websocket_server.py",
    "terminal_type": "ws:0.0.0.0:8080"
}
```

The older two-port stack (`terminal.py` + `http_server.py`, waitress) has been
removed. `terminal.py` survives, but only for its `curses` and bare-UDP-port
terminals; a config naming `http:` prints a migration message and runs
headless.

---

## Layout

```
op25/gr-op25_repeater/
├── apps/websocket_server.py     FastAPI app, WS bridge, audio, call capture
├── apps/ha_bridge.py            call clip segmentation + Home Assistant STT
├── apps/tg_metadata.py          durable per-talkgroup last-heard / frequency
├── www/app/                     React 18 + MUI 6 + Vite (source)
│   └── yarn build ──► www/dist  committed build artifact, served by the above
```

Everything is on one port: static files, the control WebSocket, and the audio
stream.

```
Browser (React SPA)
   │
   ├── GET  /                     www/dist (SPA fallback for client routes)
   ├── WS   /ws                   control + state, JSON frames
   ├── GET  /api/stream           continuous audio (WAV or raw PCM)
   ├── GET  /api/config           the loaded multi_rx JSON
   ├── GET  /api/talkgroups       durable talkgroup history (?system= &heard=)
   ├── GET  /api/audio/channels   selectable audio streams
   ├── GET  /api/calls            captured call clips + transcripts
   ├── GET  /api/calls/{id}/audio.wav
   ├── GET  /api/captures         raw symbol-capture files
   ├── GET  /api/captures/{name}
   └── GET  /api/ha/status        capture / speech-to-text diagnostics
                    │
                    ▼
        ws_terminal thread  ◄── ui_in_q / ui_out_q ──►  multi_rx.py
```

---

## WebSocket protocol

Every frame is `{ "type": <MessageType>, "payload": <object> }`.

### Downstream (server → client)

| Type | Carries |
|---|---|
| `SYSTEM_STATE` | the health payload, **and** every decoder `json_type` without a more specific home: `trunk_update`, `channel_update`, `plot`, `terminal_config`, `full_config`, `ws_instances`, `meta_update` |
| `CALL_ACTIVITY` | `call_log` entries |
| `CALL_AUDIO` | a captured clip (`call_clip`), then again with its transcript (`call_transcript`) |
| `ERROR` | `{ detail }` — unknown message type or invalid JSON |

The decoder tags each of its own messages with `json_type`, so a client
discriminates on both the envelope type and the inner `json_type`. The routing
table is `_JSON_TYPE_TO_MSG` in `websocket_server.py`; anything unlisted falls
through to `SYSTEM_STATE`.

There is no `SDR_STATUS` type. An earlier revision declared one, plus routing
for `chan_status` / `trunked_site_status` / `sys_info`, none of which any
decoder module emits.

#### The health payload

Sent on connect and then once a second:

```json
{ "status": "running", "uptime": 1874, "site_name": "voice channel",
  "trunk_id": "palmetto", "error_detail": "" }
```

`status` is `stopped` before the first decoder message, `running` while updates
are arriving, and `error` after 5 s of silence (`error_detail` says how long).
Consumed by `useSystemState()`, which drives the decoder chip in the header.

#### Call history on connect

`call_log` is a **draining delta feed** — `tk_p25.get_call_log()` clears its
buffer on every read, and the bridge polls once a second whether or not a
browser is attached. The server therefore keeps a 200-entry ring and replays it
on connect as a `call_log` frame with `"replay": true`. Clients must still
accumulate; the ring only covers what the server itself has seen.

### Upstream (client → server)

| Type | Payload |
|---|---|
| `CALL_CONTROL` | `{ command, arg1, arg2 }` — forwarded verbatim to the decoder |
| `SYSTEM_CONTROL` | `{ action: "quit" }` |

`CALL_CONTROL` is a thin pipe onto `multi_rx.process_qmsg`, so every decoder UI
command is reachable: `hold`, `skip`, `lockout`, `whitelist`, `reload`,
`adj_tune`, `set_debug`, `capture`, `dump_tgids`, `dump_buffer`, `toggle_plot`,
`set_freq`, `close_plots`, `get_full_config`, `get_terminal_config`,
`get_ws_instances`, `update`. `arg1` is usually a TGID or value and `arg2` the
channel msgqid.

There is no mute command: muting is client-side, because the page simply stops
pulling `/api/stream`.

#### Commands whose argument is a list

A `gr.message` carries a string plus two floats, so `arg1`/`arg2` cannot hold a
scan list. When a `CALL_CONTROL` payload contains **any field beyond
`command`/`arg1`/`arg2`**, `handle_call_control` forwards the whole payload as
JSON instead of the bare command name — a form `multi_rx.process_qmsg` has always
accepted, since it tries `json.loads()` first. Two commands use it:

```json
{ "type": "CALL_CONTROL",
  "payload": { "command": "set_whitelist", "msgqid": 0, "tgids": [1010, 1011] } }
```

`set_whitelist` / `set_blacklist` **replace** a list rather than adding to it.
Deliberately not a loop over single `whitelist` commands: `add_whitelist()`
expires the current call whenever the talkgroup it is on falls outside the new
list, so applying 50 entries one at a time tears the receiver down repeatedly on
the way to the same end state. The decoder validates the entire list before
applying any of it — a half-applied scan list is worse than none.

An **empty** `tgids` for `set_whitelist` means "no whitelist", i.e. scan
everything, which is how a scan list is cleared. An empty *dict* internally would
mean scan nothing, so `None` and `[]` are not interchangeable anywhere in this
path — `channel_update.whitelist` is `null` for "unrestricted" for the same
reason.

The list applies to **every receiver of the system** that owns `msgqid`, because
those receivers all scan the same traffic. Each gets its own copy of the dict:
with a whitelist file configured, `load_bl_wl()` hands every receiver the *same*
object while `add_whitelist()` silently un-shares it, so the copy makes that
aliasing irrelevant rather than load-bearing.

`channel_update` reports `whitelist` and `blacklist` back, so the UI can read a
scan list rather than only write one — a whitelist loaded from a file used to be
invisible entirely. Only permanent blacklist entries are listed; a timed one is a
`TGID_SKIP_TIME` skip in flight and would make the UI flicker.

---

## Audio

The decoder sends voice as UDP PCM. The server binds those ports, re-streams
them over HTTP, and (optionally) slices them into per-call clips.

- Ports are discovered from each channel's `destination` (`udp://host:port`,
  plus `port+1` for slot B). `terminal.audio_ports` overrides outright.
- `GET /api/stream` — every port mixed together. 8 kHz/16-bit/mono WAV by
  default. `rate=` resamples (16 kHz for Home Assistant/Whisper), `format=raw`
  drops the header.
- `GET /api/stream?channel=N` — one config channel. `?port=N` — one exact
  stream, which is how to reach a DMR slot B. `GET /api/audio/channels` lists
  what is available, with byte counters so a client can hide slots that never
  carry anything.
- `ws://` destinations are **not** used. They were the legacy stack's C++
  websocketpp sinks and that transport has been removed; the decoder now warns
  about one and carries on. See
  [README-browser-audio.md](README-browser-audio.md).

Slot A and slot B stay separate streams on purpose: on DMR they are two
unrelated conversations, so mixing them would interleave two people.

### Local speaker output at the same time

A unicast UDP port has exactly one consumer, so `sockaudio.py` and this server
cannot share one. Local audio wins — port discovery excludes anything claimed by
an `audio.instances[]` entry. To run both, give the channel a second
destination:

```json
"destination": "udp://127.0.0.1:23456, udp://127.0.0.1:23458"
```

`apps/richland-mac.json` is a working example.

---

## Signal plots

Plots are rendered client-side from raw data rather than as gnuplot PNGs.
`wrap_gp.send_plot()` emits `json_type: "plot"` with
`{chan, mode, data: [[x,y],…], xrange, yrange, title}` for all six modes
(`fft`, `constellation`, `symbol`, `eye`, `mixer`, `fll`).

- Rate is `http_plot_interval` (default 1.0 s) — *not* `curses_plot_interval`,
  which defaults to 0.0 and would emit every buffer.
- Payloads are decimated to 1200 points by striding, so a long trace still
  spans its full range.
- The decoder owns plot on/off state and it survives a page reload, so the UI
  adopts any mode it sees data for.

### Cost, and how it is bounded

`FFT_FREQ` (20 Hz) and `MIX_FREQ` (50 Hz) were chosen for a gnuplot window
redrawing continuously. Feeding a browser at 1 Hz, that was 20–50 transforms plus
a 512-iteration pure-Python averaging loop per frame anyone actually saw.
Measured on an M-series Mac, that loop cost 0.37 ms (fft) / 0.48 ms (mixer) per
call against 0.020 ms vectorised — roughly 0.7 % and 2.4 % of a core, or several
times that on an N100 E-core.

Three things bound it now:

- The averaging is vectorised, and a `sum_pwr` running total that nothing ever
  read is gone. The Blackman window is cached rather than rebuilt per call.
- `wrap_gp.compute_interval()` slows the transform rate to `AVGS_PER_PLOT` (8) per
  frame, and `_averaging_alpha()` rescales the exponential-average coefficient to
  match: `alpha' = 1 - (1-alpha)**(actual/nominal)`. Without that compensation,
  dropping 20 Hz to 8 Hz would stretch `FFT_AVG`'s ~1 s time constant by 2.5× and
  the spectrum would visibly lag the radio — which is why the throttle could not
  simply move above the FFT. It never speeds *up* past the historical rate, so a
  short `http_plot_interval` cannot make the DSP work harder than before.
- `eye` / `constellation` / `symbol` keep no state between frames, so a throttled
  frame is skipped before any work at all. (The historical `plot_count % 20` eye
  decimation now applies only when unthrottled: with `plot_interval` set it would
  compound with the throttle into one eye frame every 20 seconds.)

Net effect at the default 1 Hz: ~35× less CPU on `fft`, ~120× on `mixer`/`fll`.

**Plots also stop when nobody is watching.** The decoder owns their on/off state
so it survives a reload, which also means an enabled plot outlives the tab that
enabled it. `multi_rx`'s own `watchdog` cannot catch this — it keys off `update`
going quiet, and the bridge keeps sending those forever so the call-log ring stays
filled for the next client. So `ws_terminal._reap_idle_plots()` sends
`close_plots` once the client count has been zero for `PLOT_IDLE_GRACE` (5 s),
long enough that a page reload does not cost the user their plots.

`rx_update` — the http terminal's list of gnuplot PNG filenames — is gated on
`terminal_type == "http"` in `multi_rx.ui_plot_update()`, so this stack never
receives one. Nothing is missing; the data arrives as `plot` instead.

---

## Talkgroup metadata and the Talkgroup Browser

### Why "Last" only ever said "Now"

The talkgroup table's last-activity column read
`frequency_data[freq].last_activity` — a per-*frequency* preformatted string —
and a talkgroup is only listed against a frequency while its call is up
(`TGID_EXPIRY_TIME`, **one second**, `tk_p25.py:1957`). So every row showed either
`"  Now"` or nothing, and the same lookup was the only source for the Freq column.
Sorting was broken too, because it string-compared `"  Now"` against `" 4.1s"`.

The per-talkgroup data already existed and simply was not sent. `tgid_tags` now
carries it, in the same shape from all three trunking modules:

```json
"tgid_tags": {
  "1001": { "tag": "FIRE DISP", "configured": true, "prio": 2,
            "last_seen": 1786047983.5, "last_freq": 851012500, "count": 4 }
}
```

- `last_seen` is a **raw epoch**, not a formatted string: the browser knows the
  viewer's clock and locale, and a number sorts. `0` means never heard.
- `last_freq` is a new sticky key. It cannot reuse the decoder's `frequency`,
  which `expire_talkgroup()` clears to `None` to mean "no call up" — a distinction
  the trunking logic depends on.
- `encrypted` is **P25 only**. SmartNet keeps encryption in a bit of the tgid
  (`tgid & 0x8`) and never records it per talkgroup; its
  `talkgroups[tgid]['mode']` is analog-vs-digital, so publishing that as
  `encrypted` would mark every digital talkgroup on the system as encrypted.

### Surviving a restart (`apps/tg_metadata.py`)

In-process history is lost on restart, which is exactly when a last-heard column
matters most: a `tgid_tags_file` with two thousand entries would read "never
heard" after every reboot. `TalkgroupStore` keeps the durable copy.

- The **in-memory dict is the source of truth**; SQLite is a write-behind cache.
  Dirty rows are flushed in one transaction on a timer (`FLUSH_INTERVAL`, 30 s)
  and at shutdown, so a talkgroup heard twice a second is not two disk writes a
  second. On Home Assistant OS that database may live on an SD card, so the
  batching is the point rather than an optimisation.
- `_note_trunk_update()` folds each `trunk_update` into the store and then merges
  the durable values *back into the payload* before it is broadcast, so the
  browser sees one merged view and needs no idea persistence exists.
- `last_seen` never moves backwards, and a reported `0` never erases a real
  timestamp — two receivers on one system report independently and out of order,
  and a fresh decoder reports `0` for everything it has not yet heard.
- `count` accumulates by **delta**. The decoder's counter is per-process, so
  adding the raw value would re-add the whole session on every update; a counter
  that goes *down* is treated as a restart and rebased.
- Path: `$OP25_METADATA_DB`, else `terminal.metadata_db`, else
  `op25_metadata.sqlite` in the cwd (the user's data directory — `tgid_tags_file`
  and the whitelists resolve against it too). Either source may be set empty to
  turn persistence off.
- **Nothing here can fail the decoder.** An unusable path or a corrupt database
  logs once and the store keeps working in memory only; `persistent: false` in
  `/api/talkgroups` is how you notice.

`GET /api/talkgroups` is the durable view, and unlike `tgid_tags` it includes
talkgroups last heard in an *earlier* run. `?system=` filters, `?heard=true` drops
never-heard entries. Its `total` counter is deliberately not named `talkgroups`,
which would shadow the list it is spread alongside.

### Finding a talkgroup

Two separate mechanisms, kept apart on purpose:

| | Focus / pin | Scan list |
|---|---|---|
| Scope | this browser (`localStorage`) | the decoder, system-wide |
| Effect | sorts to the top of the table; optionally filters it | **stops other talkgroups being received**, recorded and transcribed |
| Set by | pin icon, or the Browser's checkboxes | the Browser's explicit "Apply as scan list" button |

Narrowing what you are *looking at* must not silently narrow what gets recorded,
so the second one is never implicit.

`components/TalkgroupBrowser` is a dialog over the full list from
`/api/talkgroups`, merged with whatever the live payload says is `configured`. It
solves the findability problem three ways:

- **The list is frozen** while the dialog is open (`systems` is deliberately not a
  dependency of the loader). Chasing a row that re-sorts as traffic arrives is the
  bug being fixed, so re-sorting it under the user would defeat the point.
- **Live filter, substring or regex**, matched against both tag and TGID. Regex is
  case-insensitive. A pattern mid-typing is usually a syntax error, so an invalid
  one shows everything and says why rather than emptying the table mid-word;
  filtering is deferred (`useDeferredValue`) so the input stays responsive over a
  couple of thousand rows.
- **The header checkbox selects every current match**, which is what makes the
  regex worth having: `^(FIRE|EMS)` then one click.

`useTalkgroupFocus` is in `localStorage` rather than on the server for the same
reason the theme is: it is per browser, not per decoder, and two people watching
one receiver should not fight over it. Selections can outlive the rows they came
from (a talkgroup dropped from the tags file), so the chip row counts from the set
and labels the difference rather than silently losing entries.

---

## System types

The payload shape differs by trunking module, and the UI branches on
`system.type` (`utils/systemKind.ts`):

| | P25 | SmartNet | Connect+ |
|---|---|---|---|
| identity | NAC, WACN, SysID, RFSS/Site, LRA | System ID, Site | LCN count, rest channel |
| band plan | yes | — | — |
| adjacent sites | yes | yes | — |
| subscribers (affiliation) | yes | — | — |
| patches | yes | yes | — |
| talkgroup tags + priority | yes | yes | yes |

Fields a system type does not have are **absent**, not zero, and the cards say
so rather than implying data is still coming.

---

## Testing without a browser

`multi_rx.py` holds the dongle, so run one instance and probe it:

```python
async with websockets.connect("ws://127.0.0.1:8080/ws") as ws:
    print(json.loads(await ws.recv()))   # health payload
```

At 1 Hz you should see `SYSTEM_STATE` (health), `SYSTEM_STATE/trunk_update`,
`SYSTEM_STATE/channel_update` and `CALL_ACTIVITY/call_log`.

For UI checks, headless Chrome with `--virtual-time-budget` gives false
negatives — virtual time outruns the real WebSocket handshake, so the app is
frozen at "connecting" in the screenshot even when the backend is healthy.
Drive Chrome over CDP with real `asyncio.sleep()` waits instead.

Python tests: `pytest` from `apps/` (specs are `tests/*_spec.py`), in-process
via FastAPI's `TestClient` — no network or dongle needed. Note that
`TestClient.stream()` hangs on `/api/stream` because it is an unbounded
generator; drive `AudioStreamManager.generate()` directly under asyncio.

---

## Developing the UI against a remote decoder

The dongle lives on the Home Assistant box; the frontend is easier to iterate on
locally. `yarn dev`'s proxy target is `OP25_BACKEND`:

```bash
cd op25/gr-op25_repeater/www/app
OP25_BACKEND=http://homeassistant.local:8099 yarn dev
```

The browser still only talks to `http://localhost:5173`, so Vite proxies both
`/api` and `/ws` and nothing on the Python side changes — no CORS involved, no
flag to set, no code path that only exists in development.

**Know what port 8099 is.** It is the add-on's published direct port and it has
**no authentication at all** (`allow_origins=["*"]`, no token). Anyone on the
network can hold a talkgroup, apply a scan list, quit the decoder, or listen.
Ingress is the authenticated path; 8099 exists for debugging and for media players
that cannot authenticate against ingress. Treat this workflow as a trusted-LAN
convenience.

A tunnel is not a substitute here: unpublishing 8099 also hides it from the Home
Assistant host, so there would be nothing to forward to. If the port needs to be
reachable from somewhere untrusted, the fix is authentication on the server, which
this stack does not currently have.
