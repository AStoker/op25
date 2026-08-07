"""
Field metadata for the config editor.

This exists so the GUI does not hardcode P25. The editor renders whatever this
module describes, which means adding a protocol is a matter of adding field
descriptions rather than writing another React form -- the first step toward the
UI being a scanner front-end rather than a P25 front-end.

Two properties of a field matter more than its type:

``live``
    Whether changing it takes effect without rebuilding the flowgraph. Very
    little is live. Device and channel parameters are read in ``multi_rx``'s
    constructors, so changing them needs a restart; the ones marked live here
    have a corresponding runtime command in ``multi_rx.process_qmsg``. Getting
    this wrong in the optimistic direction is the bad one: the UI would report
    success and the decoder would keep running the old value.

``applies_to``
    Which trunking modules the field is meaningful for. ``encrypted`` is
    P25-only in the payload, SmartNet keeps encryption in a tgid bit, and
    Connect+ has slots that P25 does not -- so a field list that ignores the
    protocol shows the user knobs that do nothing.

Paths use the same syntax as ``config_store.flatten``:
``devices[sdr0].gains``, with ``*`` standing for "every element of this list".
"""

from __future__ import annotations

from typing import Any

# Trunking modules a field can apply to. 'any' means protocol-independent.
P25 = 'tk_p25.py'
SMARTNET = 'tk_smartnet.py'
TRBO = 'tk_trbo.py'
ALL_PROTOCOLS = (P25, SMARTNET, TRBO)


def _field(path: str, label: str, kind: str, **kw: Any) -> dict[str, Any]:
    field: dict[str, Any] = {
        'path': path,
        'label': label,
        'type': kind,
        'live': False,
        'applies_to': list(ALL_PROTOCOLS),
    }
    field.update(kw)
    return field


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

DEVICE_FIELDS = [
    _field('devices[*].name', 'Name', 'string', readonly=True,
           help='Identity used by channels and by device_overrides. Changing it '
                'would orphan every reference, so it is not editable here.'),
    _field('devices[*].args', 'Device args', 'string',
           placeholder='rtl or rtl=00000101',
           help='osmosdr device string. Bare "rtl" takes the first dongle; pin a '
                'serial when more than one is attached.'),
    _field('devices[*].gains', 'Gain', 'string', live=True,
           placeholder='LNA:40',
           help='Stage:value pairs. The driver logs the tuner\'s supported steps '
                'at startup and rounds to the nearest. Live: applied without a '
                'restart, so it can be swept while watching symbol quality.'),
    _field('devices[*].gain_mode', 'Hardware AGC', 'boolean',
           help='Hand gain control to the tuner. Manual (off) plus a swept value '
                'is usually better on a trunked system.'),
    _field('devices[*].ppm', 'Frequency correction', 'number', live=True,
           unit='ppm', min=-200, max=200, step=0.1,
           help='Read "freq error" in Tuning & Diagnostics once the control '
                'channel locks and divide by the tuned frequency in MHz.'),
    _field('devices[*].frequency', 'Centre frequency', 'number',
           unit='Hz', min=0,
           help='Where the device parks. For a trunked system this is normally '
                'the control channel.'),
    _field('devices[*].rate', 'Sample rate', 'number', unit='Hz',
           suggestions=[250000, 1000000, 1024000, 1800000, 1920000, 2000000,
                        2048000, 2400000, 2560000],
           help='Prefer a rate that divides the channel if_rate exactly, which '
                'skips an arbitrary resampler in the demod chain. A wider rate '
                'also covers more voice channels without retuning the device.'),
    _field('devices[*].usable_bw_pct', 'Usable bandwidth', 'number',
           min=0.1, max=1.0, step=0.05,
           help='Fraction of the sample rate treated as usable. The edges of an '
                'RTL-SDR\'s span are not.'),
    _field('devices[*].tunable', 'Allow retuning', 'boolean',
           help='Let the receiver retune this device to follow a voice grant '
                'outside the current window. Off pins it, which is what you want '
                'for a dedicated control-channel receiver.'),
    _field('devices[*].offset', 'IF offset', 'number', unit='Hz',
           advanced=True,
           help='For hardware with a deliberate frequency offset. Normally 0.'),
]

# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------

CHANNEL_FIELDS = [
    _field('channels[*].name', 'Name', 'string',
           help='Shown in the UI. Free text.'),
    _field('channels[*].device', 'Device', 'string',
           help='Must match a devices[].name.'),
    _field('channels[*].trunking_sysname', 'System', 'string',
           help='Must match a trunking.chans[].sysname.'),
    _field('channels[*].demod_type', 'Demodulator', 'enum',
           choices=['cqpsk', 'fsk4'],
           help='cqpsk handles P25 phase 1 and phase 2 and is the general '
                'choice; fsk4 is C4FM-only and can do better on a weak '
                'non-simulcast signal.'),
    _field('channels[*].filter_type', 'Filter', 'enum',
           choices=['rc', 'rrc', 'nxdn', 'gmsk', 'fsk4mm', 'fsk2', 'fsk2mm',
                    'widepulse'],
           advanced=True,
           help='Matched filter shape. Only consulted by the fsk4 chain; under '
                'cqpsk it affects baseband gain and the FLL only.'),
    _field('channels[*].excess_bw', 'Excess bandwidth', 'number',
           min=0.05, max=0.5, step=0.05, advanced=True,
           help='Filter rolloff, and the FLL band-edge width.'),
    _field('channels[*].if_rate', 'IF rate', 'number', unit='Hz',
           suggestions=[24000, 25000, 32000],
           help='Demodulator input rate. 24000 is five samples per symbol at '
                '4800 baud.'),
    _field('channels[*].symbol_rate', 'Symbol rate', 'number', unit='baud',
           suggestions=[4800, 6000],
           help='4800 for P25 phase 1 and SmartNet; phase 2 TDMA switches to '
                '6000 on its own when it detects it.'),
    _field('channels[*].destination', 'Audio destination', 'string',
           placeholder='udp://127.0.0.1:23456',
           help='Comma-separated. A second destination is how local speaker '
                'output and browser audio coexist -- a unicast UDP port has '
                'exactly one consumer.'),
    _field('channels[*].enable_analog', 'Analog', 'enum',
           choices=['off', 'on', 'auto'],
           help='Conventional analog FM on this channel.'),
]

# ---------------------------------------------------------------------------
# Trunking systems
# ---------------------------------------------------------------------------

TRUNKING_FIELDS = [
    _field('trunking.module', 'Protocol', 'enum',
           choices=list(ALL_PROTOCOLS),
           help='Which trunking decoder to load. This is the field that decides '
                'which of the system settings below mean anything.'),
    _field('trunking.chans[*].sysname', 'System name', 'string',
           help='Referenced by channels[].trunking_sysname.'),
    _field('trunking.chans[*].control_channel_list', 'Control channels', 'string',
           placeholder='859.26250,853.50000',
           help='Comma-separated MHz, primary first. The receiver hunts these in '
                'order when it loses lock.'),
    _field('trunking.chans[*].nac', 'NAC', 'string', applies_to=[P25],
           placeholder='0x1D1',
           help='P25 network access code. Hex.'),
    _field('trunking.chans[*].tgid_tags_file', 'Talkgroup tags', 'string',
           placeholder='palmetto_tgs.tsv',
           help='TSV of talkgroup names, resolved against the working directory '
                'rather than against the config file.'),
    _field('trunking.chans[*].rid_tags_file', 'Radio ID tags', 'string',
           advanced=True, help='TSV of subscriber names.'),
    _field('trunking.chans[*].whitelist', 'Whitelist file', 'string',
           advanced=True,
           help='Restrict scanning to these talkgroups. Empty means scan '
                'everything -- an empty *list* would mean scan nothing.'),
    _field('trunking.chans[*].blacklist', 'Blacklist file', 'string',
           advanced=True, help='Talkgroups to skip.'),
    _field('trunking.chans[*].crypt_behavior', 'Encrypted traffic', 'enum',
           choices=[0, 1, 2], applies_to=[P25, TRBO],
           help='2 drops encrypted calls before audio. They decode to '
                'near-silence, so the alternative is recording nothing.'),
    _field('trunking.chans[*].bandplan', 'Band plan', 'string',
           applies_to=[SMARTNET], advanced=True,
           help='SmartNet band plan identifier.'),
]

# ---------------------------------------------------------------------------
# Terminal / integration
# ---------------------------------------------------------------------------

TERMINAL_FIELDS = [
    _field('terminal.http_plot_interval', 'Plot interval', 'number',
           unit='s', min=0.1, max=60, step=0.1,
           help='How often signal plots are sent. The demodulator reduces its '
                'transform rate to match, so a longer interval really is less '
                'CPU.'),
    _field('terminal.audio_ports', 'Extra audio ports', 'list',
           advanced=True,
           help='Explicit override of the UDP ports the browser stream listens '
                'on. Normally discovered from each channel destination.'),
    _field('terminal.home_assistant.enabled', 'Transcription', 'boolean',
           help='Speech-to-text and call recording via Home Assistant.'),
    _field('terminal.home_assistant.stt_engine', 'Speech-to-text engine', 'string',
           placeholder='stt.faster_whisper',
           help='A Home Assistant stt entity id.'),
    _field('terminal.home_assistant.language', 'Language', 'string',
           help='Must match what the provider advertises -- HA Cloud says en-US, '
                'Wyoming says en, and a mismatch is a bare HTTP 415.'),
    _field('terminal.home_assistant.keywords', 'Keywords', 'list',
           help='Phrases to match in a transcript.'),
    _field('terminal.home_assistant.media_upload', 'Upload clips', 'boolean',
           help='Push each clip to Home Assistant, which makes clips outlive the '
                'in-memory ring and removes any need for this host to be '
                'reachable.'),
]

SECTIONS = [
    {'key': 'devices', 'label': 'Devices', 'kind': 'list',
     'list_path': 'devices', 'identity': 'name', 'fields': DEVICE_FIELDS},
    {'key': 'channels', 'label': 'Channels', 'kind': 'list',
     'list_path': 'channels', 'identity': 'name', 'fields': CHANNEL_FIELDS},
    {'key': 'trunking', 'label': 'Systems', 'kind': 'mixed',
     'list_path': 'trunking.chans', 'identity': 'sysname',
     'fields': TRUNKING_FIELDS},
    {'key': 'terminal', 'label': 'Interface & integration', 'kind': 'object',
     'fields': TERMINAL_FIELDS},
]

#: Fields with a runtime command behind them, by config path pattern.
#: Everything else needs the flowgraph rebuilt -- i.e. an add-on restart.
LIVE_PATHS = tuple(f['path'] for section in SECTIONS
                   for f in section['fields'] if f.get('live'))


def schema(protocol: str | None = None) -> dict[str, Any]:
    """The editor schema, optionally filtered to one trunking module."""
    out = []
    for section in SECTIONS:
        fields = [f for f in section['fields']
                  if protocol is None or protocol in f['applies_to']]
        out.append({**section, 'fields': fields})
    return {
        'protocol': protocol,
        'protocols': list(ALL_PROTOCOLS),
        'sections': out,
        'live_paths': list(LIVE_PATHS),
    }


def _split_path(path: str) -> list[str]:
    """Split on '.' but not inside brackets.

    A device may be called anything, including ``base.station``, and its
    flattened path is then ``devices[base.station].gains``. A plain ``split('.')``
    turns that into four segments and the pattern stops matching -- so a live
    field would be misreported as restart-required for that device only.
    """
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in path:
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth = max(0, depth - 1)
        if ch == '.' and depth == 0:
            parts.append(''.join(current))
            current = []
        else:
            current.append(ch)
    parts.append(''.join(current))
    return parts


def _matches(pattern: str, path: str) -> bool:
    """Does a concrete flattened path match a schema pattern?

    ``devices[*].gains`` matches ``devices[sdr0].gains``. Comparing segment by
    segment rather than with a regex keeps a device called ``a.b`` from matching
    the wrong pattern.
    """
    pat_parts, path_parts = _split_path(pattern), _split_path(path)
    if len(pat_parts) != len(path_parts):
        return False
    for pat, actual in zip(pat_parts, path_parts):
        if pat == actual:
            continue
        if '[*]' in pat:
            prefix = pat.split('[*]')[0]
            suffix = pat.split('[*]')[1]
            if not (actual.startswith(prefix + '[') and actual.endswith(']' + suffix)):
                return False
            continue
        return False
    return True


def is_live(path: str) -> bool:
    """Whether a changed field takes effect without a restart."""
    return any(_matches(p, path) for p in LIVE_PATHS)


def classify(changes: list[dict[str, Any]]) -> dict[str, Any]:
    """Split a diff into what applied immediately and what needs a restart.

    The UI needs this to be honest: reporting a restart-required change as
    applied is the failure mode that matters, because the user then trusts a
    value the decoder is not using.
    """
    live, restart = [], []
    for change in changes:
        (live if is_live(change['path']) else restart).append(change)
    return {
        'live': live,
        'restart_required': restart,
        'needs_restart': bool(restart),
    }
