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

``precision``
    Decimal places a float is worth keeping. ``adj_tune`` works in fractional ppm
    and lands on values like ``2.3749999999999996``, which is noise: at 859 MHz
    1 ppm is 859 Hz, so the smallest tuning step is ~0.116 ppm and three decimals
    is already finer than the hardware. Long floats are only a readability
    problem, but the config is something a human reads.

``applies_to``
    Which trunking modules the field is meaningful for. ``encrypted`` is
    P25-only in the payload, SmartNet keeps encryption in a tgid bit, and
    Connect+ has slots that P25 does not -- so a field list that ignores the
    protocol shows the user knobs that do nothing.

``default``
    What the code does when the key is absent. Not a value that gets stored --
    it is what the control *displays* while nothing overrides it. Without it a
    switch for a field that defaults to on reads as off, which is worse than
    unhelpful: ``call_recording`` is on unless the config says otherwise, and a
    switch showing it off invites the user to "fix" it by turning it on and
    thereby writing an override that did nothing.

``group``
    Optional sub-heading within a section. Only the transcription section has
    enough fields to need it: twenty controls in one undifferentiated grid is a
    wall, and the reader cannot tell which of them affect *what gets sent* and
    which affect *what comes back*.

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
           unit='ppm', min=-200, max=200, step=0.1, precision=3,
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
           min=0.1, max=1.0, step=0.05, precision=3,
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
           min=0.05, max=0.5, step=0.05, precision=3, advanced=True,
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
           unit='s', min=0.1, max=60, step=0.1, precision=2,
           help='How often signal plots are sent. The demodulator reduces its '
                'transform rate to match, so a longer interval really is less '
                'CPU.'),
    _field('terminal.audio_ports', 'Extra audio ports', 'list',
           advanced=True,
           help='Explicit override of the UDP ports the browser stream listens '
                'on. Normally discovered from each channel destination.'),
]

# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------
#
# Its own section, and its own tab in the editor, because it is the one part of
# the config that is not about receiving radio: it decides which finished calls
# leave this host, where they go, and what comes back. Mixing that in with sample
# rates and filter shapes buried it.
#
# Everything here is read at startup -- HomeAssistantConfig is built once in
# start_call_capture -- so none of it is live. The one thing that *is* live is the
# pinned talkgroup list that ``talkgroup_scope: focused`` reads, which is
# deliberate: the scope is a setting, the pins are scanner state (ui_state.py).

TRANSCRIPTION_FIELDS = [
    _field('terminal.home_assistant.enabled', 'Enable transcription', 'boolean',
           group='Connection', default=False,
           help='Send finished calls to Home Assistant for speech-to-text, '
                'keyword matching and webhook alerts. Off leaves call recording '
                'and the in-browser clip list working.'),
    _field('terminal.home_assistant.url', 'Home Assistant URL', 'string',
           group='Connection', placeholder='http://supervisor/core',
           help='Injected by the add-on when home_assistant.use_supervisor is '
                'on, which is also what supplies the token. Set it here only for '
                'a standalone install.'),
    _field('terminal.home_assistant.token_file', 'Token file', 'string',
           group='Connection', advanced=True,
           help='Path to a file holding a long-lived access token. Preferred over '
                'putting the token in the config, which is served to the browser. '
                '$OP25_HA_TOKEN is the other way in.'),
    _field('terminal.call_recording', 'Record calls', 'boolean',
           group='Connection', default=True,
           help='Slice the UDP audio into one clip per transmission. Off disables '
                'the clip list, /api/calls and transcription together -- nothing '
                'downstream has anything to work on.'),

    # -- what gets sent -----------------------------------------------------
    _field('terminal.home_assistant.talkgroup_scope', 'Transcribe', 'enum',
           choices=['all', 'focused', 'list'], group='What gets sent', default='all',
           choice_labels={
               'all': 'All traffic',
               'focused': 'Only pinned talkgroups',
               'list': 'Only the talkgroups listed below',
           },
           help='"Only pinned" reuses the same selection the talkgroup table '
                'pins, so one list drives both what you watch and what gets '
                'transcribed. It is read live -- pinning a talkgroup takes effect '
                'on the next call, with no restart. An empty selection means no '
                'restriction rather than silence, so unpinning everything cannot '
                'quietly stop transcription.'),
    _field('terminal.home_assistant.talkgroups', 'Talkgroup list', 'list',
           group='What gets sent', placeholder='1001, 1002',
           help='Used when the scope above is "list". Talkgroup ids, comma '
                'separated. Empty means no restriction.'),
    _field('terminal.home_assistant.min_call_secs', 'Minimum call length', 'number',
           unit='s', min=0, max=30, step=0.1, precision=2, group='What gets sent',
           default=0.8,
           help='Shorter transmissions are dropped rather than transcribed. A '
                'radio keyed and released produces a fraction of a second of '
                'audio that no engine can do anything with.'),
    _field('terminal.home_assistant.min_peak', 'Minimum peak level', 'number',
           min=0, max=32767, step=10, group='What gets sent', default=250,
           help='Peak sample amplitude a clip must reach. This is the gate that '
                'drops encrypted traffic, which decodes to near-silence -- that '
                'is the intent, not a bug.'),
    _field('terminal.home_assistant.max_call_secs', 'Maximum call length', 'number',
           unit='s', min=1, max=3600, step=1, precision=2, advanced=True,
           group='What gets sent', default=120.0,
           help='A transmission this long is closed and sent anyway, so a stuck '
                'mic cannot grow one clip without bound.'),
    _field('terminal.home_assistant.hang_time_secs', 'Hang time', 'number',
           unit='s', min=0.1, max=30, step=0.1, precision=2, advanced=True,
           group='What gets sent', default=1.5,
           help='Gap in UDP audio that ends a call. The decoder only emits while '
                'a call is up, so this gap is the voice-activity detector -- too '
                'long and two transmissions merge into one clip.'),
    _field('terminal.home_assistant.min_voiced_ratio', 'Minimum voiced ratio',
           'number', min=0, max=1, step=0.05, precision=2, advanced=True,
           group='What gets sent', default=0.0,
           help='Speech-likeness gate, 0 to disable. Advisory and off by default '
                'so it cannot silently eat traffic.'),

    # -- speech to text -----------------------------------------------------
    _field('terminal.home_assistant.stt_engine', 'Speech-to-text engine', 'string',
           group='Speech to text', default='stt.faster_whisper',
           help='A Home Assistant stt entity id.'),
    _field('terminal.home_assistant.language', 'Language', 'string',
           group='Speech to text', default='en-US',
           help='Must match what the provider advertises -- HA Cloud says en-US, '
                'Wyoming says en, and a mismatch is a bare HTTP 415. The bridge '
                'asks the engine at startup and corrects this where it can.'),
    _field('terminal.home_assistant.filter_hallucinations',
           'Filter hallucinated text', 'boolean', group='Speech to text', default=True,
           help='Unintelligible audio makes Whisper produce confident boilerplate '
                '("Thank you for watching"). Rejected text is kept in the clip as '
                'discarded_transcript, so over-filtering stays visible.'),
    _field('terminal.home_assistant.hallucination_phrases', 'Extra phrases to reject',
           'list', advanced=True, group='Speech to text',
           help='Added to the built-in list of hallucinated boilerplate.'),
    _field('terminal.home_assistant.stt_sample_rate', 'Sample rate sent', 'number',
           unit='Hz', advanced=True, group='Speech to text',
           suggestions=[8000, 16000], default=16000,
           help="Clips are 8 kHz and are upsampled to this. Home Assistant's stt "
                'API accepts only what the provider advertises, normally 16000. '
                'Upsampling recovers no detail -- the vocoder is the quality '
                'floor -- it is purely a format requirement.'),
    _field('terminal.home_assistant.stt_audio', 'Audio format sent', 'enum',
           choices=['raw', 'wav'], advanced=True, group='Speech to text', default='raw',
           choice_labels={'raw': 'Headerless PCM', 'wav': 'WAV container'},
           help='Home Assistant passes the body straight to the provider as raw '
                'PCM chunks. Switch to wav only if a provider needs a container.'),
    _field('terminal.home_assistant.timeout_secs', 'Request timeout', 'number',
           unit='s', min=1, max=600, step=1, precision=2, advanced=True,
           group='Speech to text', default=30.0,
           help='Applies to every Home Assistant round-trip: transcription, '
                'webhook and media upload.'),

    # -- what comes back ----------------------------------------------------
    _field('terminal.home_assistant.keywords', 'Keywords', 'list',
           group='Alerts and storage',
           help='Phrases to match in a transcript. Plain words are matched on '
                'word boundaries, so "fire" does not fire on "firehouse".'),
    _field('terminal.home_assistant.keywords_only', 'Alert on keywords only',
           'boolean', group='Alerts and storage', default=False,
           help='Post the webhook only when a keyword matched, rather than for '
                'every transcribed call.'),
    _field('terminal.home_assistant.webhook_id', 'Webhook id', 'string',
           group='Alerts and storage',
           help='Home Assistant automation webhook to POST each result to. Empty '
                'means transcripts appear in this UI only.'),
    _field('terminal.home_assistant.media_upload', 'Upload clips', 'boolean',
           group='Alerts and storage', default=False,
           help='Push each clip into Home Assistant, which makes clips outlive '
                'the in-memory ring and removes any need for this host to be '
                'reachable. The upload endpoint needs an administrator token.'),
    _field('terminal.home_assistant.media_dir', 'Media folder', 'string',
           advanced=True, group='Alerts and storage', default='scanner',
           help='Folder within the media source. Created on demand.'),
    _field('terminal.home_assistant.media_source', 'Media source', 'string',
           advanced=True, group='Alerts and storage', default='local',
           help='Media source id; "local" on a default install.'),
    _field('terminal.home_assistant.media_url_base', 'Public media URL', 'string',
           advanced=True, group='Alerts and storage',
           placeholder='/local/scanner',
           help='/media/<source>/<dir> requires authentication, so a link to it '
                '401s. Uploading under <config>/www and pointing this at /local/... '
                'makes the clip linkable -- and unauthenticated.'),
    _field('terminal.home_assistant.normalize', 'Level clips', 'boolean',
           advanced=True, group='Alerts and storage', default=True,
           help='Loudness-normalise each clip at finalize. Measured 24 dB of RMS '
                'spread on live traffic. The peak/rms in clip metadata stay '
                'as-received, so they remain valid as an RF indicator.'),
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
    {'key': 'transcription', 'label': 'Transcription', 'kind': 'object',
     'fields': TRANSCRIPTION_FIELDS},
]

#: Sections the editor gives a tab of their own rather than listing under
#: Settings. Named here so the server decides it, not the React file: a client
#: that does not know about the tab still gets the fields.
STANDALONE_SECTIONS = ('transcription',)

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
        'standalone_sections': list(STANDALONE_SECTIONS),
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


#: Declared decimal places, by path pattern.
PRECISION_PATHS = {f['path']: f['precision'] for section in SECTIONS
                   for f in section['fields'] if 'precision' in f}


def precision_for(path: str) -> int | None:
    """Declared precision for a concrete flattened path, if any."""
    for pattern, places in PRECISION_PATHS.items():
        if _matches(pattern, path):
            return places
    return None


def round_floats(config: Any, _prefix: str = '') -> Any:
    """Round every float to the precision its field declares.

    Applied on save, so the value is clean whichever client produced it -- the
    form, the raw JSON editor, or the Save-tuning button. Without it a ppm of
    2.3749999999999996 goes straight into the config file, and the file is
    something a human reads.

    Only touches paths the schema gives a precision, so nothing else is silently
    altered. A frequency in Hz has no precision declared and is left exactly as
    given.
    """
    if isinstance(config, dict):
        return {k: round_floats(v, f'{_prefix}.{k}' if _prefix else str(k))
                for k, v in config.items()}
    if isinstance(config, list):
        out = []
        for i, item in enumerate(config):
            label: Any = i
            if isinstance(item, dict):
                for candidate in ('name', 'sysname', 'instance_name'):
                    if candidate in item:
                        label = item[candidate]
                        break
            out.append(round_floats(item, f'{_prefix}[{label}]'))
        return out
    # bool is an int subclass; rounding it would turn True into 1.
    if isinstance(config, float) and not isinstance(config, bool):
        places = precision_for(_prefix)
        if places is not None:
            return round(config, places)
    return config


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
