# OP25 → Home Assistant: speech-to-text and keyword alerts

This describes how to feed OP25's decoded scanner audio into Home Assistant,
run speech-to-text over it, and trigger automations on keywords ("structure
fire", "officer down", a unit number, …).

It applies to the **new** WebSocket/FastAPI stack only — the one selected by

```json
"terminal": { "module": "websocket_server.py", "terminal_type": "ws:0.0.0.0:8080" }
```

The legacy `http_server.py` terminal has none of this.

---

## 1. Why per-call clips, not a continuous stream

The obvious approach — point a speech-to-text engine at a live audio stream —
works badly for a scanner. A trunked control channel is silent most of the
time, so an always-on transcriber spends its cycles on digital silence and
emits hallucinated text between transmissions. Whisper in particular is prone
to inventing sentences ("Thank you for watching") when handed silence.

OP25's decoder only emits UDP audio *while a call is up*, which makes the
absence of packets a near-perfect voice-activity detector. The server uses
that to slice the feed into one clip per transmission:

```
decoder UDP ──> CallRecorder ──> clip (finite WAV + talkgroup metadata)
                                   ├─> POST to Home Assistant's STT API
                                   ├─> keyword match on the transcript
                                   └─> POST result to a Home Assistant webhook
```

Each clip is short, finite, speech-only, and already tagged with the talkgroup
and radio ID that produced it — so an automation knows not just *what* was
said but *who* said it and *on which talkgroup*.

Two integration styles are supported, and they can be combined:

| | Style | Who does the work | Best for |
|---|---|---|---|
| **A** | **Push** (recommended) | OP25 transcribes and pushes results | Keyword alerts, notifications, logging |
| **B** | **Pull** | Home Assistant consumes a live stream | Listening in HA, Assist pipelines, media players |

---

## 2. Prerequisites in Home Assistant

You need a speech-to-text provider. The usual choice is the **Whisper**
add-on, which speaks the Wyoming protocol:

1. **Settings → Add-ons → Add-on Store**, install **Whisper** and start it.
2. **Settings → Devices & Services → Add Integration → Wyoming Protocol**,
   host `core-whisper` (or `localhost`), port `10300`.
3. Note the entity id it creates — typically `stt.faster_whisper`.
   **Settings → Devices & Services → Entities**, filter on `stt.` to confirm.

On a Raspberry Pi, use the `tiny-int8` or `base-int8` Whisper model. `small`
and above are too slow to keep up with a busy trunked system, and clips will
be dropped from the queue rather than backing up.

You also need a **long-lived access token**: click your user name in the HA
sidebar → **Security** → **Long-lived access tokens** → **Create token**.

---

## 3. Style A — push (OP25 transcribes, Home Assistant reacts)

### 3.1 Configure OP25

Add a `home_assistant` block to the `terminal` section of your multi_rx JSON
config:

```json
"terminal": {
    "module": "websocket_server.py",
    "terminal_type": "ws:0.0.0.0:8080",

    "home_assistant": {
        "enabled": true,
        "url": "http://homeassistant.local:8123",
        "token": "eyJhbGciOi...",
        "stt_engine": "stt.faster_whisper",
        "webhook_id": "op25_call",
        "language": "en-US",
        "keywords": ["structure fire", "officer down", "signal 63", "10-33"],
        "keywords_only": false,
        "public_url": "http://op25.local:8080"
    }
}
```

Then restart OP25 and confirm the bridge came up:

```
$ curl -s http://localhost:8080/api/ha/status | python3 -m json.tool
```

The startup log also prints a one-line summary:

```
home assistant: url=http://homeassistant.local:8123 stt=stt.faster_whisper webhook=op25_call keywords=4
```

**Keep the token out of the config file** by exporting it instead — the config
value is optional and `$OP25_HA_TOKEN` is used when it is absent:

```bash
export OP25_HA_TOKEN='eyJhbGciOi...'
```

### 3.2 Receive the events in Home Assistant

Every completed call is POSTed as JSON to
`POST /api/webhook/<webhook_id>`. Webhooks need no authentication, which is
why the id should be long and unguessable in any setup where Home Assistant is
reachable from outside your LAN.

The payload:

```json
{
  "event": "op25_call",
  "id": "a1b2c3d4e5f6",
  "started": 1753900000.123,
  "ended": 1753900004.331,
  "duration": 4.21,
  "system": "Palmetto 800",
  "channel": "Richland",
  "tgid": 1211,
  "talkgroup": "Richland FD Dispatch",
  "source": 5551212,
  "source_tag": "Engine 12",
  "frequency": 851012500,
  "encrypted": false,
  "emergency": false,
  "transcript": "engine twelve on scene working structure fire send a second alarm",
  "keywords": ["structure fire"],
  "audio_url": "http://op25.local:8080/api/calls/a1b2c3d4e5f6/audio.wav"
}
```

`keywords` is empty when nothing matched, and `transcript` is empty when
speech-to-text is not configured or failed (a `stt_error` field is then
present with the reason).

A minimal automation — notify on any keyword hit:

```yaml
automation:
  - alias: "Scanner keyword alert"
    trigger:
      - platform: webhook
        webhook_id: op25_call
        allowed_methods: [POST]
        local_only: true
    condition:
      - condition: template
        value_template: "{{ trigger.json.keywords | length > 0 }}"
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "📻 {{ trigger.json.keywords | join(', ') | upper }}"
          message: >-
            {{ trigger.json.talkgroup }}
            {%- if trigger.json.source_tag %} ({{ trigger.json.source_tag }}){% endif %}:
            {{ trigger.json.transcript }}
          data:
            url: "{{ trigger.json.audio_url }}"
```

`local_only: true` is important — it stops the webhook being reachable from
the internet even if your HA instance is.

### 3.3 Keeping the last call in an entity

A template sensor makes the most recent transcript available to dashboards and
to voice assistants ("what did dispatch just say?"). Because the state field is
capped at 255 characters, put the transcript in an attribute:

```yaml
template:
  - trigger:
      - platform: webhook
        webhook_id: op25_call
        allowed_methods: [POST]
        local_only: true
    sensor:
      - name: "Scanner Last Call"
        unique_id: op25_last_call
        state: "{{ trigger.json.talkgroup | default('unknown') }}"
        attributes:
          transcript: "{{ trigger.json.transcript }}"
          keywords: "{{ trigger.json.keywords }}"
          source: "{{ trigger.json.source_tag or trigger.json.source }}"
          tgid: "{{ trigger.json.tgid }}"
          duration: "{{ trigger.json.duration }}"
          audio_url: "{{ trigger.json.audio_url }}"
```

### 3.4 Playing the call audio back

`audio_url` is a plain finite WAV file, so any media player can fetch it:

```yaml
      - service: media_player.play_media
        target:
          entity_id: media_player.kitchen_speaker
        data:
          media_content_id: "{{ trigger.json.audio_url }}"
          media_content_type: music
```

For this to work, `public_url` must be an address Home Assistant can reach.
When OP25 binds to `0.0.0.0` the server cannot infer one, and `audio_url` is
left as a relative path — set `public_url` explicitly in that case.

Clips live in a bounded in-memory ring (60 clips / 24 MB by default, roughly
25 minutes of voice), so fetch or play them promptly. They are not archived.

### 3.5 Filtering what gets transcribed

Transcription is the expensive step. Two options narrow it:

```json
"talkgroups": [1211, 1215, 3300],
"keywords_only": true
```

- `talkgroups` — only these TGIDs are transcribed at all. Everything else is
  still captured and still visible in the OP25 web UI, it just never reaches
  Home Assistant.
- `keywords_only` — transcribe everything, but only fire the webhook when a
  keyword matched. Useful when you want alerts without a firehose of
  automation triggers.

---

## 4. Style B — pull (Home Assistant consumes the live stream)

`GET /api/stream` serves continuous 16-bit mono PCM and takes two query
parameters:

| Parameter | Values | Default | Notes |
|---|---|---|---|
| `rate` | 8000, 16000, 22050, 24000, 44100, 48000 | 8000 | 16000 is what HA's voice pipeline and Whisper want |
| `format` | `wav`, `raw` | `wav` | `raw` omits the WAV header |

So `http://op25.local:8080/api/stream?rate=16000` is directly consumable by
anything that speaks ffmpeg.

**Listen on a speaker** — push the stream URL at any media player entity:

```yaml
script:
  listen_to_scanner:
    sequence:
      - service: media_player.play_media
        target:
          entity_id: media_player.kitchen_speaker
        data:
          media_content_id: http://op25.local:8080/api/stream
          media_content_type: music
```

How well this works depends on the receiver. The stream declares an unknown
length (the RIFF size field is `0xFFFFFFFF`), which browsers and ffmpeg handle
correctly but some cast targets do not. If a speaker refuses it, transcode
through something that re-containerises — Icecast via `example_liquidsoap.liq`
is the well-trodden path for that, see `README-rpi3-liquidsoap.md`.

**Continuous STT with Stream Assist** (custom integration, via HACS —
`AlexxIT/StreamAssist`): add it, set the **Stream** source to
`http://op25.local:8080/api/stream?rate=16000` and pick your Assist pipeline.
It runs its own VAD and feeds segments into the pipeline, exposing the
recognised text as a sensor.

Be aware of the trade-off: this path transcribes the raw stream including
silence, which is exactly the failure mode described in section 1. Style A is
the better fit for keyword alerting; Style B is the better fit for *listening*.

### The UDP port is single-consumer

A unicast UDP port has exactly one reader. If you also run local speaker
output (`audio.instances[]` in the config), `sockaudio.py` claims the decoder's
audio port and the WebSocket server's receiver gets nothing — no browser
audio, no clips, no transcripts. Give the channel a second destination:

```json
"destination": "udp://127.0.0.1:23456, udp://127.0.0.1:23458",
"terminal": { "audio_ports": [23458] }
```

`apps/richland-mac.json` is a working example. See `README-browser-audio.md`.

---

## 5. Configuration reference

All keys live under `terminal.home_assistant`.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | true when `url` is set | Master switch |
| `url` | — | Base URL of Home Assistant, e.g. `http://homeassistant.local:8123` |
| `token` | `$OP25_HA_TOKEN` | Long-lived access token; needed for speech-to-text only |
| `stt_engine` | `stt.faster_whisper` | Entity id of the HA speech-to-text provider |
| `language` | `en-US` | Passed to the STT engine |
| `webhook_id` | — | HA webhook to POST results to; omit to disable the push |
| `keywords` | `[]` | Terms to match in the transcript |
| `keywords_only` | false | Only fire the webhook when a keyword matched |
| `talkgroups` | `[]` (all) | Restrict transcription to these TGIDs |
| `public_url` | bound address | Base URL Home Assistant should use to fetch clip audio |
| `hang_time_secs` | 1.5 | Silence that ends a call |
| `min_call_secs` | 0.8 | Shorter transmissions are discarded |
| `max_call_secs` | 120 | A longer transmission is split at this point |
| `min_peak` | 250 | Clips quieter than this are discarded (catches encrypted traffic) |
| `stt_sample_rate` | 16000 | Rate clips are resampled to before transcription |
| `stt_audio` | `raw` | `raw` or `wav` — see troubleshooting |
| `timeout_secs` | 30 | HTTP timeout for both STT and webhook calls |

Plus one key directly under `terminal`:

| Key | Default | Meaning |
|---|---|---|
| `call_recording` | true | Set false to disable call capture entirely |

Keyword matching is case-insensitive. Terms made only of letters, digits,
spaces, apostrophes and hyphens are matched on word boundaries — `fire` does
not match `firehouse` — while terms containing anything else fall back to a
plain substring match.

---

## 6. HTTP API

| Endpoint | Purpose |
|---|---|
| `GET /api/stream?rate=&format=` | Continuous live audio |
| `GET /api/calls?limit=50` | Recent captured calls as JSON, newest first |
| `GET /api/calls/{id}/audio.wav?rate=` | One call as a finite WAV file |
| `GET /api/ha/status` | Capture and bridge diagnostics |

Clips also arrive over the existing WebSocket as `CALL_AUDIO` messages —
`json_type: "call_clip"` when the transmission ends, then
`json_type: "call_transcript"` once speech-to-text completes. The React UI's
**Call Audio & Transcripts** card is driven by these, and seeds itself from
`/api/calls` on load so a reloaded page is not empty.

If you would rather poll from Home Assistant than receive a webhook:

```yaml
rest:
  - resource: http://op25.local:8080/api/calls?limit=1
    scan_interval: 10
    sensor:
      - name: "Scanner Last Transcript"
        value_template: "{{ value_json.calls[0].talkgroup | default('idle') }}"
        json_attributes_path: "$.calls[0]"
        json_attributes: [transcript, keywords, tgid, source_tag, audio_url]
```

---

## 7. Troubleshooting

Start at `/api/ha/status`. It separates the three things that can fail:

```json
{
  "call_recording": true,
  "store": { "clips": 12, "bytes": 1930240 },
  "recorder": { "calls_captured": 12, "calls_dropped": 3, "hang_time_secs": 1.5 },
  "home_assistant": {
    "enabled": true, "submitted": 12, "transcribed": 11, "stt_errors": 1,
    "webhooks": 11, "webhook_errors": 0, "alerts": 2, "dropped": 0
  }
}
```

**`calls_captured` stays 0.** No audio is reaching the server. Check the
`ws audio:` lines on stderr — if they show `pcm=0`, either the decoder is not
sending (no traffic, or `destination` is not a `udp://` URL) or another
process owns the port. See "The UDP port is single-consumer" above.

**`calls_dropped` is high.** Transmissions are being rejected as too short or
too quiet. Encrypted talkgroups decode to near-silence and are *supposed* to be
dropped here. If real traffic is being lost, lower `min_call_secs` or
`min_peak`.

**Calls captured but `submitted` is 0.** The `talkgroups` filter is excluding
them, or `enabled` is false.

**`stt_errors` is climbing.** The error text is written to stderr with the HTTP
status. Common causes:

- `HTTP 401` — bad or expired token.
- `HTTP 404` — wrong `stt_engine`. Confirm the entity id under
  **Settings → Devices & Services → Entities**, filtered on `stt.`.
- `HTTP 400` — the provider rejected the audio format. Home Assistant's STT API
  accepts only 16 kHz / 16-bit / mono; that is the default here. If a
  particular provider wants a container rather than bare PCM, set
  `"stt_audio": "wav"`.

You can check what an engine accepts directly:

```bash
curl -H "Authorization: Bearer $OP25_HA_TOKEN" \
     http://homeassistant.local:8123/api/stt/stt.faster_whisper
```

**Transcripts are empty strings, no errors.** The engine ran and heard nothing
intelligible. P25 vocoded audio at 8 kHz is hard for speech models; a larger
Whisper model helps most, followed by monitoring talkgroups with clear
dispatch audio rather than field units.

**`dropped` is climbing.** Transcription is slower than the call rate and the
queue is shedding the oldest clips. Use a smaller Whisper model, or narrow
`talkgroups`.

**Webhook fires but the automation does not.** Check
`local_only` against where OP25 is on the network, and confirm the
`webhook_id` matches on both sides. **Developer Tools → Events**, listening for
`*`, shows whether the webhook is arriving at all.

---

## 8. Privacy and legality

Transcribing radio traffic and acting on it automatically is not the same as
listening to a scanner. Before deploying this:

- Monitoring is regulated differently by jurisdiction, and recording or
  redistributing what you receive is often regulated more tightly than
  receiving it.
- Transcripts of public-safety traffic routinely contain names, addresses, and
  medical information. Clips here are in-memory and short-lived, but anything
  you forward to Home Assistant — notifications, logbook entries, template
  sensors — is persisted by Home Assistant on your terms, not OP25's.
- Do not attempt to decode encrypted traffic. The recorder's `min_peak` gate
  drops it as silence, which is the correct outcome.
