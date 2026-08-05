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

### Where to put the token

**Do not put it in the config file.** `GET /api/config` and the decoder's
`get_full_config` both hand the loaded config to the browser, and neither is
authenticated — a `token` value there is readable by anything that can reach
port 8080. The server masks it on the way out, but the file itself is still the
wrong home for a credential that grants full API access to Home Assistant.

Three sources are consulted, in this order:

| | Source | Set it once by |
|---|---|---|
| 1 | `token` in the config | *(avoid)* |
| 2 | `token_file` in the config | writing the token to a file, `chmod 600` |
| 3 | `$OP25_HA_TOKEN` | your shell profile, a systemd unit, or a wrapper script |

`token_file` is the least fiddly of the three, because the config keeps working
unchanged whichever machine it is on and nothing has to be exported first:

```bash
install -m 600 /dev/null ~/.config/op25/ha_token
printf '%s' 'eyJhbGciOi...' > ~/.config/op25/ha_token
```

```json
"token_file": "~/.config/op25/ha_token"
```

`~` is expanded. A missing or unreadable file is logged and falls through to
`$OP25_HA_TOKEN`, so it is safe to leave the key in place on a machine that
uses the environment variable instead.

Under systemd on the Pi, the environment variable is the idiomatic route:

```ini
# /etc/systemd/system/op25.service
[Service]
EnvironmentFile=/etc/op25/env     # chmod 600, contains OP25_HA_TOKEN=...
```

Note that Home Assistant's own `secrets.yaml` is **not** an option: it is read
by Home Assistant's YAML loader for Home Assistant's own config. OP25 is a
separate process on a different machine and cannot see it.

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
  - triggers:
      - trigger: webhook
        webhook_id: op25_call
        allowed_methods: [POST]
        local_only: true
    sensor:
      - name: "Scanner Last Call"
        unique_id: op25_last_call
        state: >-
          {{ trigger.json.talkgroup
             or ('TG ' ~ trigger.json.tgid if trigger.json.tgid else 'unknown') }}
        attributes:
          transcript: "{{ trigger.json.transcript | default('', true) }}"
          keywords: "{{ trigger.json.keywords | default([], true) }}"
          source: "{{ trigger.json.source_tag or trigger.json.source }}"
          tgid: "{{ trigger.json.tgid }}"
          duration: "{{ trigger.json.duration }}"
          audio_url: "{{ trigger.json.audio_url }}"
```

> **This is not an automation.** It is a template *entity*, and it belongs in
> `configuration.yaml` under the top-level `template:` key — not in the
> automation editor, and not in `automations.yaml`. Pasting it into an
> automation gets you
> `Message malformed: extra keys not allowed @ data['template']`, because the
> automation schema has no `template:` key. A trigger-based template sensor
> carries its own trigger, so there is no separate automation to create.
>
> `triggers:` / `trigger: webhook` is the syntax from HA 2024.10 onward; the
> older `trigger:` / `platform: webhook` spelling still works.
>
> `triggers:` and `sensor:` must be keys of the **same list item** — one block
> means "on this trigger, build these entities". Splitting them produces a
> matched pair of complaints that describe the same fault from both ends:
> `Invalid template configuration found, trigger option is missing matching
> domain` (a trigger with no entities) and `'sensor' is an invalid option for
> 'template'` (entities with no trigger).
>
> If your `configuration.yaml` says `template: !include templates.yaml`, then
> `templates.yaml` *is* the value of `template:` — paste the `- triggers:` list
> item into it without a `template:` key.

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

### 3.6 Pushing the audio into Home Assistant

By default a clip stays in this process and `audio_url` points back here, so
anything that wants the audio has to reach OP25 over the network — and the
clip has to still be in the ring when it does. Both are avoidable:

```json
"media_upload": true,
"media_dir": "scanner"
```

Each clip is then POSTed to Home Assistant's
`/api/media_source/local_source/upload` as it completes, and the webhook that
follows carries a `media_path` field naming where it landed
(`/media/local/scanner/2026-08-05_161735_ffa24f1fcd21.wav`). The upload happens
*before* the webhook precisely so that field can be populated — an automation
has no way to wait for an upload it did not start.

This is the arrangement to prefer if Home Assistant is the more capable
machine. It means:

- Home Assistant never connects back to the scanner box, so nothing depends on
  `public_url`, on this host being reachable, or on NAT/firewall between them.
- Clips outlive OP25. The in-memory ring holds ~25 minutes; the media library
  holds whatever you choose to keep.
- The files are ordinary media — browsable under **Media → My media**, playable
  by any media player entity, and openable straight from a notification.

Retention becomes Home Assistant's problem, and it will not prune by itself.
A `shell_command` on a schedule is enough:

```yaml
shell_command:
  scanner_prune_clips: >-
    /bin/sh -c 'find /media/scanner -type f -name "*.wav"
    -mmin +2880 -exec rm -f {} +'
```

Notes:

- **The endpoint requires an administrator's token**, not merely a valid one
  (`@require_admin`). A non-admin token gets an HTTP 401 that says nothing
  else; OP25 adds that hint to the log line.
- Uploads are capped at 20 MB and must declare an image, video or audio
  content type. Clips are sent as real RIFF/WAVE, unlike the headerless PCM
  the STT endpoint receives.
- Every captured clip is uploaded, not just ones matching `keywords` — which
  is usually what you want, since it lets you go back to a call nothing
  flagged. Narrow it with `talkgroups` if the volume is too high. At roughly
  two calls a minute and two seconds a call, expect on the order of 100 MB a
  day.
- A failed upload is logged and counted in `media_errors` at `/api/ha/status`;
  the webhook still fires, just with no `media_path`.

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
| `token` | — | Long-lived access token; needed for speech-to-text only. **Avoid** — see below |
| `token_file` | — | Path to a file containing the token. Preferred: the config holds a path, not a secret |
| `stt_engine` | `stt.faster_whisper` | Entity id of the HA speech-to-text provider |
| `language` | `en-US` | Passed to the STT engine |
| `webhook_id` | — | HA webhook to POST results to; omit to disable the push |
| `keywords` | `[]` | Terms to match in the transcript |
| `keywords_only` | false | Only fire the webhook when a keyword matched |
| `talkgroups` | `[]` (all) | Restrict transcription to these TGIDs |
| `public_url` | inferred | Base URL Home Assistant should use to fetch clip audio. Only needed when `media_upload` is off |
| `media_upload` | false | Push each clip into Home Assistant's media library (see §4.1) |
| `media_dir` | `scanner` | Folder within the media source to upload into |
| `media_source` | `local` | Which entry of HA's `media_dirs` to upload into |
| `hang_time_secs` | 1.5 | Silence that ends a call |
| `min_call_secs` | 0.8 | Shorter transmissions are discarded |
| `max_call_secs` | 120 | A longer transmission is split at this point |
| `min_peak` | 250 | Clips quieter than this are discarded (catches encrypted traffic) |
| `normalize` | true | Even out the loudness of captured clips (see §7) |
| `normalize_target_rms` | 3000 | Target speech RMS, 0–32767 |
| `normalize_max_gain_db` | 24 | Ceiling on boost, so near-silence is not amplified into noise |
| `min_voiced_ratio` | 0 (off) | Discard clips scoring below this on the speech-likeness heuristic |
| `filter_hallucinations` | true | Drop stock speech-model filler before keyword matching |
| `hallucination_phrases` | `[]` | Extra phrases to treat as hallucinations |
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

The first of those two messages carries `"transcript_pending": true` when the
clip has been accepted for transcription — which is what lets the UI show
*awaiting transcript* rather than *no transcript* during the gap. The field is
omitted when false, and is cleared on every terminal outcome: transcribed,
failed, filtered as a hallucination, or shed from a full queue. So a row can
never be left waiting on a transcript that is not coming.

**Call History** shows transcripts too. The decoder's call log and the captured
clips share no identifier — one is written when a voice grant is issued, the
other when the transmission ends — so they are joined on talkgroup plus start
time (`www/app/src/utils/callTranscripts.ts`). That is exact on a
single-channel receiver and best-effort with several channels up at once, the
same caveat that applies to clip metadata attribution generally.

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

## 7. Getting the best transcription out of P25

### What cannot be fixed

P25 Phase 1 uses the IMBE vocoder at 4400 bps; Phase 2 uses AMBE+2 at 2450 bps.
These are *parametric* codecs — they do not transmit a waveform. They transmit
pitch, per-band voicing decisions and a spectral envelope, and the decoder
**resynthesizes** speech from those parameters. Measured across live clips from
this decoder, the energy distribution in voiced frames is:

```
   0- 300 Hz    9.1%
 300-1000 Hz   66.3%
1000-2000 Hz   16.8%
2000-3000 Hz    7.0%
3000-3400 Hz    0.8%
3400-4000 Hz    0.1%
```

Two consequences follow, and no amount of post-processing changes either:

- **The 8 kHz sample rate is not the bottleneck.** There is nothing above
  3.4 kHz to recover, so upsampling adds no information. OP25 resamples to
  16 kHz only because Home Assistant's STT API accepts nothing else.
- **Consonant cues are largely gone.** Two-thirds of the energy sits in the
  pitch and first-formant region. The high-frequency detail that separates
  *fifteen* from *sixteen*, or *B* from *D*, lives above 2 kHz — where under
  8% of the energy remains. Expect numbers and letters to be the least
  reliable part of any transcript, and phonetic alphabet ("Adam", "Boy") to
  fare better than bare letters.

Phase 2 is audibly worse than Phase 1 for the same reason: roughly half the
bit rate for the same job.

### What OP25 does about it

**Loudness normalisation** (`normalize`, on by default). Decoder output varies
enormously between talkgroups and radios — measured at 24 dB of RMS spread
across ten consecutive live calls, some pinned near full scale and others
20 dB down. Each clip is levelled before it is stored or transcribed:

```
RMS spread as received : 24.4 dB  (112 .. 1874)
RMS spread normalised  :  6.1 dB  (1159 .. 2339)
```

Gain targets speech RMS (ignoring the pauses between phrases, which would
otherwise drag the measurement down and over-amplify sparse clips), then is
clamped so peaks *reach* but never cross a ceiling — so levelling never
introduces clipping. `normalize_max_gain_db` stops a nearly-silent clip being
amplified into pure noise. The `peak`, `rms` and `gain_db` fields on each clip
report the levels **as received**, so they stay usable as an RF health
indicator.

**Hallucination filtering** (`filter_hallucinations`, on by default). Whisper
does not return silence for unintelligible input — it returns fluent, confident
boilerplate from its training data ("Thank you for watching", "[Music]", a
phrase looped a dozen times). A keyword alert fired from invented text is worse
than no alert, so this text is dropped before keyword matching and surfaced
separately as `discarded_transcript` — visible in the web UI and the API, so
you can tell if the filter is being too aggressive.

**Speech-likeness gate** (`min_voiced_ratio`, off by default). Scores each clip
on pitch periodicity. This is a heuristic, not a decode-quality measurement —
OP25 does not surface a bit error rate to Python, and the `error` field on a
channel is the demodulator's *frequency* error in Hz (used for AFC), not a BER.
Left off by default so it cannot silently discard traffic; enable it around
0.3–0.4 if noise is reaching the transcriber, and watch `calls_dropped`.

### What you can do about it

Ranked by how much difference it makes:

1. **Fix the RF first.** Bit errors corrupt vocoder *parameters*, so a marginal
   signal produces warbling and dropped syllables that look like codec limits
   but are not. Correct gain (enough for sensitivity, not so much that the
   front end intermodulates), correct `ppm`, and a better antenna are free.
   The frequency-error figure and `calls_dropped` are your indicators.
2. **Run a bigger model, on a bigger machine.** Nothing in OP25 cares where
   Home Assistant's STT engine lives. `medium` or `large-v3` on a desktop or
   GPU box is a different league from `tiny`/`base`, and this is usually the
   single largest available improvement.
3. **Prime the model with your vocabulary.** The Whisper add-on's
   `initial_prompt` accepts a sample of expected language — unit designators,
   ten-codes, street and agency names. Biasing the decoder toward your
   jargon measurably reduces nonsense on marginal audio.
4. **Monitor dispatch, not field units.** Console audio comes from a wired
   microphone in a quiet room; a portable held at arm's length beside a running
   pump panel does not. The difference is larger than any tuning here.

Things that sound helpful but are not: resampling above 16 kHz (there is no
information up there to reconstruct), and general-purpose denoisers such as
RNNoise — they target additive noise, whereas this is resynthesis artefact.
Bandwidth-extension and speech-restoration models can make audio sound better
to a human while inventing spectral detail, which is the last thing you want in
front of a transcriber.

---

## 8. Troubleshooting

Start at `/api/ha/status`. It separates the three things that can fail:

```json
{
  "call_recording": true,
  "store": { "clips": 12, "bytes": 1930240 },
  "recorder": { "ports": [23456], "calls_captured": 12, "calls_dropped": 3 },
  "home_assistant": {
    "enabled": true, "submitted": 12, "transcribed": 11, "stt_errors": 1,
    "hallucinations": 1, "webhooks": 11, "webhook_errors": 0,
    "alerts": 2, "dropped": 0
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
- `HTTP 415` — the engine refused the `X-Speech-Content` declaration. Home
  Assistant sends a bare "Unsupported Media Type" naming none of the six
  fields, so OP25 fetches the engine's capabilities and says which one differs.
  **The usual cause is the language tag.** Home Assistant Cloud advertises
  regional codes (`en-US`, `en-GB`); the Wyoming/Whisper add-on advertises bare
  ISO-639-1 codes (`en`). A config that worked against one fails against the
  other. OP25 reconciles this automatically at startup — `en-US` against a
  Whisper engine becomes `en`, and the substitution is logged — but setting
  `language` correctly avoids the round-trip.

You can check what an engine accepts directly:

```bash
curl -H "Authorization: Bearer $OP25_HA_TOKEN" \
     http://homeassistant.local:8123/api/stt/stt.faster_whisper
```

**Transcripts are empty strings, no errors.** Either the engine heard nothing
intelligible, or the output was filtered as a hallucination — check
`hallucinations` in the status block and the `discarded_transcript` field on
the affected calls. If real traffic is being discarded, add to or disable
`filter_hallucinations`. Otherwise see §7 for what actually improves results.

**`dropped` is climbing.** Transcription is slower than the call rate and the
queue is shedding the oldest clips. Use a smaller Whisper model, or narrow
`talkgroups`.

**Webhook fires but the automation does not.** Check
`local_only` against where OP25 is on the network, and confirm the
`webhook_id` matches on both sides. **Developer Tools → Events**, listening for
`*`, shows whether the webhook is arriving at all.

---

## 9. Privacy and legality

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
