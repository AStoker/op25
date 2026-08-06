# Changelog

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
