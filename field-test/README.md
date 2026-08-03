# NBFM Noise-Squelch Field Test Kit

Live-antenna test plan for the PA3FWM noise squelch on this branch
(`nbfm-noise-squelch`).  Target: a Ubuntu 22.04 or 24.04 host with an
RTL-SDR (any gr-osmosdr device works; the configs assume `rtl=0`).

## Quick start

```
sudo ./deploy.sh                  # deps + build + install + self-tests
rtl_test -t                       # dongle sanity (reboot once if DVB driver held it)
$EDITOR cfg-nbfm-noise.json       # set frequency, LNA gain, ppm
./run-field-test.sh noise         # go
```

`deploy.sh` finishes by running the two self-test suites
(`squelch_core_test.py`, `squelch_gr_test.py`); expect `15/15` and `9/9`.
The run script starts `multi_rx.py` at verbosity 2, where every squelch
transition prints with its measured quieting:

```
noise squelch closed->opening ...
noise squelch opening->open quieting=14.2dB
noise squelch open->hang quieting=4.8dB
noise squelch hang->closed quieting=0.3dB
```

Status page: `http://<host>:8080`.  Audio plays on the host's default
ALSA device.  Listening remotely instead: change the channel
`destination` to `udp://<your-workstation-ip>:23456` and on the
workstation run
`ffplay -f s16le -ar 8000 -ac 1 -i udp://0.0.0.0:23456 -nodisp`.

## Picking test frequencies

| Target | Why |
|---|---|
| NOAA weather radio (162.400-162.550 MHz) | Always-on carrier: first-light check. Gate must open within ~100 ms of tuning on and never chatter. Tune 25 kHz off-channel: gate must close and stay closed. |
| 2m ham repeater output (144-148 MHz) | Intermittent traffic: key-up attack, tail/hang behavior, weak mobile flutter. |
| VHF public safety / business (150-160 MHz, 12.5 kHz channels) | The design target: narrowband voice, varied signal strength. |
| MURS 151.820/151.880/151.940 MHz | Legal to monitor, sporadic short transmissions. |

NOAA WX uses wider deviation (+/-5 kHz); that's fine for squelch testing.
For narrowband channels `nbfm_deviation: 4000` in the configs is right
(lower it to 2500 if audio is too quiet on very narrow systems).

## Test matrix

1. **Empty channel** (tune somewhere quiet): gate stays closed for
   minutes on end.  Any false open is a finding - note the logged
   quieting value.
2. **Strong signal**: opens promptly on key-up, no mid-transmission
   dropouts, closes ~250 ms (hang) after unkey.
3. **Weak signal**: find a distant repeater or attenuate the antenna.
   Default `nbfm_noise_squelch_db: 8` should open around "weak but
   readable" (~6-7 dB CNR).  Compare intelligibility at the margin
   against power mode.
4. **A/B against legacy**: `./run-field-test.sh power` runs the same
   channel with the original power squelch (`-60 dB` absolute
   threshold).  The claim under test: noise mode needs no per-device
   threshold fiddling and opens on signals power mode misses (or vice
   versa - note which).
5. **Voice mode** (optional): `./run-field-test.sh voice` also requires
   speech to open.  A NOAA WX carrier is voice ~100% of the time so it
   should behave like noise mode there; on a channel with data bursts
   (MDC1200, telemetry) it should stay closed for the bursts.

## Capturing evidence

Set `"nbfm_raw_output": "/tmp/disc.raw"` in the running config to
record the raw discriminator (float32 @ 24 kHz).  Replay it later
through either squelch offline - no radio needed - by setting
`"nbfm_raw_input": "/tmp/disc.raw"` and toggling `nbfm_squelch_mode`,
which is the cleanest apples-to-apples comparison for a marginal
signal.  Keep captures of anything that misbehaves.

## Tuning

| Symptom | Adjust |
|---|---|
| Opens on noise flutter / distant intermod | raise `nbfm_noise_squelch_db` toward 12 |
| Misses weak-but-readable signals | lower it toward 5 |
| Tail chops syllables on fading mobiles | raise `nbfm_noise_squelch_hang` (ms) |
| Squelch tail noise burst audible | lower hang; report it - the gate should ramp, not click |

## Troubleshooting

- `rtl_test` shows `usb_claim_interface error`: DVB driver grabbed the
  dongle - `deploy.sh` installed the blacklist; reboot once.
- No audio: check `aplay -l`, set `device_name` in the config's audio
  section (e.g. `"hw:1,0"`, or `"pulse"` on a desktop).
- `vmcircbuf` warnings at startup are normal GNU Radio first-run noise.
- Frequency looks right but audio is off-pitch/garbled: set the
  dongle's `ppm` correction in the config.
