# Browser audio

Audio reaches the browser by one mechanism: the decoder sends PCM to a UDP
port, `websocket_server.py` binds that port and re-streams it over HTTP on the
same port the UI is served from. There is no second port to open and nothing
extra to configure.

```json
"channels": [
    { "name": "voice channel", "destination": "udp://127.0.0.1:23456", ... }
],
"terminal": { "module": "websocket_server.py", "terminal_type": "ws:0.0.0.0:8080" }
```

## Endpoints

- `/api/stream` — all channels mixed. 8 kHz/16-bit/mono WAV; `rate=16000`
  resamples, `format=raw` drops the header.
- `/api/stream?channel=N` — a single channel. The Player card shows a source
  picker whenever more than one stream exists.
- `/api/stream?port=N` — one exact UDP port, which is how to reach a DMR
  slot B. Slot A and B stay separate because on DMR they are two unrelated
  conversations.
- `/api/audio/channels` — what is available, with byte counters.

## The one gotcha: local speaker output competes for the port

A unicast UDP port has exactly one consumer, so `sockaudio.py` (the
`audio.module` that drives local speakers) and this server cannot share one.
Local audio wins — `_discover_audio_ports()` excludes any port claimed by an
`audio.instances[]` entry, and logs that it did.

To run both, give the channel a second destination and let discovery find it:

```json
"destination": "udp://127.0.0.1:23456, udp://127.0.0.1:23458",
"terminal": { ..., "audio_ports": [23458] }
```

`terminal.audio_ports` is an explicit override that wins outright.
`Palmetto800-single.json` is a working example. See
[README-new-gui.md](README-new-gui.md) for the full protocol.

## `ws://` destinations

Older configs may carry a `ws://` destination. It used to run a websocketpp
server inside the C++ audio layer, feeding the removed legacy browser UI
directly. **That transport no longer exists.** The decoder now warns about an
unrecognised scheme and carries on, and endpoint discovery ignores it, so a
config saying

```json
"destination": "udp://127.0.0.1:23456, ws://0.0.0.0:9000"
```

still works — via the `udp://` half. A `ws://` destination *on its own* yields
no audio at all. Replace it with `udp://`.
