# Browser audio

There are two web stacks in this fork and they deliver audio differently. Pick
the section that matches your `terminal` config block.

| Your config says | Audio mechanism | Section |
|---|---|---|
| `"module": "websocket_server.py"`, `"terminal_type": "ws:host:port"` | UDP → HTTP re-stream on the same port | [New stack](#new-stack-websocket_serverpy) |
| `"module": "terminal.py"`, `"terminal_type": "http:host:port"` | `ws://` sinks in the C++ audio layer, one port per channel | [Legacy stack](#legacy-stack-http_serverpy) below |

---

## New stack (`websocket_server.py`)

**`ws://` destinations are not used here.** The server binds the channel's UDP
audio ports itself and re-streams them over HTTP on the same port the UI is
served from, so there is nothing extra to configure and no second port to open:

```json
"channels": [
    { "name": "voice channel", "destination": "udp://127.0.0.1:23456", ... }
],
"terminal": { "module": "websocket_server.py", "terminal_type": "ws:0.0.0.0:8080" }
```

- `/api/stream` — all channels mixed. 8 kHz/16-bit/mono WAV; `rate=16000`
  resamples, `format=raw` drops the header.
- `/api/stream?channel=N` — a single channel. The Player card shows a source
  picker whenever more than one stream exists.
- `/api/stream?port=N` — one exact UDP port, which is how to reach a DMR
  slot B. Slot A and B stay separate because on DMR they are two unrelated
  conversations.
- `/api/audio/channels` — what is available, with byte counters.

Local speaker output and browser audio cannot share one UDP port (a unicast
port has exactly one consumer); give the channel a second destination to run
both — see [README-new-gui.md](README-new-gui.md).

Adding a `ws://` destination does no harm — it is simply ignored by this
stack — but on its own it will produce **no browser audio**. A `udp://`
destination is what this server listens for.

---

## Legacy stack (`http_server.py`)

Everything below applies to the legacy two-port GUI only.

As of 5/4/2026, op25 has the capability to stream live audio to the web-based
terminal window across a network. There are several configuration steps that
must be in place for this to work.

i. Pull the latest code changes from https://github.com/boatbod/op25, build
and install it.
    cd ~/op25
    git pull        # <<< make sure there are no errors
    ./rebuild.sh

2. Browser audio capability only applies to the "New UI", which means it
only works with the multi_rx.py version of the app.

3. Audio streams via websockets which can run in parallel with the existing
udp based stream.  The server configuration must include a ws: destination
for each channel that you want to stream to the browser.
    "destination": "udp://127.0.0.1:23456, ws://0.0.0.0:9000",
or
    "destination": "ws://0.0.0.0:9000",
If you use the loopback address (127.0.0.1) you will only be able to connect
locally on the same machine.  Using 0.0.0.0 means connections will be accepted
on all interfaces.  Each channel needs it's own unique websocket port.  
Port 9000 is a suggested default, but by no means special.  If there are three
channels you might use 9000, 9001, and 9002 respectively.

The Headphones Icon between the Channel and Tuning buttons is how audio is toggled on a per-channel basis. Channels can be cycled through and the audio muted or enabled on each one depending on the user's preferences. 

4. Audio is streamed on all channels configured with a websocket by default. However, modern browser security requires the user to create AudioContext in order for the audio to play. You should be able to click anywhere in the UI with most browsers to create AudioContext and play the audio. Depending on your browser and security settings, you may have to actually interact with a button or menu for your browser to allow the audio to play.

5. If you want to mute audio by default, you can toggle "Mute Browser Audio at Startup" in the Settings Menu. If you have strict browser history and local storage settings configured, this setting may not be retained between program launches.
