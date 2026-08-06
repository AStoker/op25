# Changelog

## 0.0.5

First image since 0.0.2: **0.0.3 and 0.0.4 never published one.** 0.0.3's build
was cancelled part-way by a GitHub Actions outage, and 0.0.4 was tagged without
bumping `config.yaml`, which the release workflow refuses by design. Everything
listed under 0.0.3 below therefore arrives here for the first time.

- **The header's Config and About entries do something.** Both were placeholders
  that swallowed the click.
- **Config → Decoder** holds the log level, which is the `-v` command-line
  option, alongside a read-only view of how the decoder was started (terminal,
  trunking module, plot interval, local speaker output, audio ports, the
  speech-to-text engine). Log level moved out of Tuning & Diagnostics: it is
  applied to every channel and device at once, so presenting it as a per-channel
  control was misleading.
- **Config → Interface** collects the browser's own preferences — theme, accent
  colour, talkgroup smart colours. The accent-colour picker is new; the theme
  service had always supported it with nothing in the UI to reach it. This
  replaces the gear menu in the header, which held a single switch.
- **Config → Running config** is the loaded JSON, moved out of the dashboard.
  It answers a question you ask while setting a system up, not one you scan.
- **About** says what this build is and how it differs from boatbod/op25, and
  now shows the add-on version — the answer to "what am I actually running".
- One version number across `config.yaml`, this changelog and the web UI, kept
  in step by `scripts/bump-version.py` and checked in CI.

## 0.0.3

- **Seeds a working config on first run** instead of refusing to start. Getting
  a file into an add-on's config directory is the most awkward step of a Home
  Assistant OS install -- there is no host shell -- so the add-on now writes
  the sample itself and starts. Edit it in place afterwards.
- The sample is now the **Palmetto 800** (South Carolina) single-SDR P25
  system, which is a real, heavily-used system rather than a placeholder.
  Sanitised: no serial number, no LAN addresses, and no `webhook_id` (that is
  a bearer secret -- anyone holding it can POST into your Home Assistant).
- DOCS explains the three ways to reach the config directory on HAOS, and the
  `/share` fallback for when none of them is convenient.
- Device args default to `rtl` rather than a specific serial: with one dongle
  that just works, and another machine's serial is actively wrong.

## 0.0.2

First image published to GHCR. Same content as 0.0.1, which never built: its
tag disagreed with the manifest version and the manifest tripped the add-on
linter.

## 0.0.1

Initial release. Experimental — not yet verified on real hardware.

- OP25 multi_rx with the React web UI, served through Home Assistant ingress
  and on port 8099.
- RTL-SDR via `usb: true`; Debian trixie's librtlsdr 2.0.2 supports the
  RTL-SDR Blog V4 without a patched build.
- Config comes from a JSON file in the add-on's config directory; add-on
  options cover only the things that change with hardware or credentials.
- Speech-to-text can use the Supervisor proxy, so no long-lived token.
