/**
 * Prefix-relative URL helpers.
 *
 * The app has to work from two places at once:
 *
 *   http://nuc:8099/                                  direct port
 *   http://homeassistant:8123/api/hassio_ingress/<t>/ Home Assistant ingress
 *
 * Under ingress, Supervisor strips the prefix before proxying — the Python
 * server still sees `/api/config` and `/ws` — but the *browser* does not. A
 * root-absolute `fetch('/api/config')` would escape the ingress path and hit
 * Home Assistant itself.
 *
 * So every runtime URL is resolved against `document.baseURI`, which Vite's
 * `base: './'` leaves pointing at the directory index.html was served from.
 * Paths are accepted with or without a leading slash, because some of these
 * strings come back from the server root-absolute (`/api/stream?port=N` from
 * `/api/audio/channels`, and `audio_url` on a call clip).
 */

/** Directory the document was served from; always ends in '/'. */
function baseUrl(): URL {
  const href = typeof document !== 'undefined' && document.baseURI
    ? document.baseURI
    : 'http://127.0.0.1:8080/';
  return new URL('.', href);
}

/**
 * Absolute-ise an API path.
 *
 * Already-absolute URLs (`http://`, `https://`) pass through untouched, so a
 * fully-qualified `audio_url` from a remote Home Assistant still works.
 */
export function apiUrl(path: string): string {
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(path)) return path;
  return new URL(path.replace(/^\/+/, ''), baseUrl()).toString();
}

/** Same, but switches http/https to ws/wss for a WebSocket endpoint. */
export function wsUrl(path: string): string {
  if (/^wss?:\/\//i.test(path)) return path;
  const u = new URL(path.replace(/^\/+/, ''), baseUrl());
  u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
  return u.toString();
}
