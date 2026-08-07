"""
Contract tests for per-call capture and the Home Assistant bridge.

These cover the pieces a Home Assistant integration depends on:

  - PCM helpers        → resampling, WAV framing, peak detection
  - CallRecorder       → segmentation on silence, min-length and squelch gates
  - ClipStore          → bounded ring, lookup by id
  - keyword matching   → word-boundary anchored, case-insensitive
  - HomeAssistantConfig → parsing, env-var token, enable/disable logic
  - REST endpoints     → /api/calls, /api/calls/{id}/audio.wav, /api/ha/status
                         and the /api/stream rate/format parameters

Nothing here touches the network, a dongle, or Home Assistant itself.
"""

import json
import math
import re
import socketserver
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

import ha_bridge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_RATE = 8_000
FRAME_BYTES = 320          # one 20 ms P25 voice frame


def tone(n_samples: int, freq: float = 440.0, amp: int = 9_000) -> bytes:
    """*n_samples* of a sine wave as 16-bit LE mono PCM."""
    return b''.join(
        struct.pack('<h', int(amp * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)))
        for i in range(n_samples)
    )


def push_seconds(recorder: ha_bridge.CallRecorder, secs: float, amp: int = 9_000) -> None:
    for _ in range(int(secs * SAMPLE_RATE / 160)):
        recorder.push(tone(160, amp=amp))


@pytest.fixture()
def store() -> ha_bridge.ClipStore:
    return ha_bridge.ClipStore()


@pytest.fixture()
def captured() -> list:
    return []


@pytest.fixture()
def recorder(store: ha_bridge.ClipStore, captured: list) -> ha_bridge.CallRecorder:
    """A recorder with a short hang time so tests do not have to wait."""
    return ha_bridge.CallRecorder(
        store,
        hang_time_secs=0.05,
        min_call_secs=0.3,
        normalize=False,          # keep amplitudes predictable for assertions
        metadata_fn=lambda: {'tgid': 1234, 'talkgroup': 'FD Dispatch'},
        on_complete=captured.append,
    )


# ---------------------------------------------------------------------------
# PCM helpers
# ---------------------------------------------------------------------------


class TestPcmHelpers:
    def test_resample_doubles_sample_count_for_8k_to_16k(self) -> None:
        out = ha_bridge.resample_pcm16(tone(800), 8_000, 16_000)
        assert len(out) == 800 * 2 * 2

    def test_resample_is_a_no_op_at_the_same_rate(self) -> None:
        pcm = tone(160)
        assert ha_bridge.resample_pcm16(pcm, 8_000, 8_000) is pcm

    def test_resample_preserves_amplitude(self) -> None:
        """Upsampling must not change how loud the audio is."""
        out = ha_bridge.resample_pcm16(tone(800), 8_000, 16_000)
        assert ha_bridge.peak_amplitude(out) == pytest.approx(9_000, rel=0.02)

    def test_resample_handles_empty_input(self) -> None:
        assert ha_bridge.resample_pcm16(b'', 8_000, 16_000) == b''

    def test_wav_bytes_declares_the_real_length(self) -> None:
        """Unlike the live stream, a clip must carry true RIFF/data sizes."""
        pcm = tone(1_600)
        wav = ha_bridge.wav_bytes(pcm, 8_000)
        assert wav[:4] == b'RIFF'
        assert wav[8:12] == b'WAVE'
        assert struct.unpack('<I', wav[4:8])[0] == 36 + len(pcm)
        assert struct.unpack('<I', wav[40:44])[0] == len(pcm)

    def test_wav_bytes_records_the_sample_rate(self) -> None:
        wav = ha_bridge.wav_bytes(tone(160), 16_000)
        assert struct.unpack('<I', wav[24:28])[0] == 16_000

    def test_peak_amplitude_of_silence_is_zero(self) -> None:
        assert ha_bridge.peak_amplitude(b'\x00' * FRAME_BYTES) == 0


# ---------------------------------------------------------------------------
# Call segmentation
# ---------------------------------------------------------------------------


class TestCallRecorder:
    def test_call_stays_open_while_audio_flows(
        self, recorder: ha_bridge.CallRecorder, captured: list
    ) -> None:
        push_seconds(recorder, 1.0)
        recorder.poll()
        assert captured == []

    def test_call_closes_after_the_hang_time(
        self, recorder: ha_bridge.CallRecorder, captured: list
    ) -> None:
        push_seconds(recorder, 1.0)
        time.sleep(0.08)
        recorder.poll()
        assert len(captured) == 1
        assert captured[0].duration == pytest.approx(1.0, abs=0.05)

    def test_consecutive_transmissions_become_separate_clips(
        self, recorder: ha_bridge.CallRecorder, captured: list
    ) -> None:
        push_seconds(recorder, 0.5)
        time.sleep(0.08)
        recorder.poll()
        push_seconds(recorder, 0.5)
        time.sleep(0.08)
        recorder.poll()
        assert len(captured) == 2
        assert captured[0].id != captured[1].id

    def test_short_blip_is_discarded(
        self, recorder: ha_bridge.CallRecorder, captured: list
    ) -> None:
        push_seconds(recorder, 0.1)          # below min_call_secs
        time.sleep(0.08)
        recorder.poll()
        assert captured == []
        assert recorder.calls_dropped == 1

    def test_silent_transmission_is_discarded(
        self, recorder: ha_bridge.CallRecorder, captured: list
    ) -> None:
        """Encrypted traffic decodes to near-silence; do not ship it to STT."""
        for _ in range(50):
            recorder.push(b'\x00' * FRAME_BYTES)
        time.sleep(0.08)
        recorder.poll()
        assert captured == []
        assert recorder.calls_dropped == 1

    def test_clip_is_tagged_with_live_metadata(
        self, recorder: ha_bridge.CallRecorder, captured: list
    ) -> None:
        push_seconds(recorder, 0.5)
        time.sleep(0.08)
        recorder.poll()
        assert captured[0].metadata['tgid'] == 1234
        assert captured[0].metadata['talkgroup'] == 'FD Dispatch'

    def test_metadata_arriving_late_still_tags_the_call(
        self, store: ha_bridge.ClipStore, captured: list
    ) -> None:
        """channel_update lands at 1 Hz, so a call can start before its tgid is known."""
        meta: dict[str, Any] = {}
        rec = ha_bridge.CallRecorder(
            store, hang_time_secs=0.05, min_call_secs=0.3,
            metadata_fn=lambda: dict(meta), on_complete=captured.append,
        )
        push_seconds(rec, 0.4)               # nothing known yet
        meta['tgid'] = 999
        push_seconds(rec, 0.4)
        time.sleep(0.08)
        rec.poll()
        assert captured[0].metadata['tgid'] == 999

    def test_metadata_from_the_next_call_does_not_overwrite_this_one(
        self, store: ha_bridge.ClipStore, captured: list
    ) -> None:
        meta: dict[str, Any] = {'tgid': 111}
        rec = ha_bridge.CallRecorder(
            store, hang_time_secs=0.05, min_call_secs=0.3,
            metadata_fn=lambda: dict(meta), on_complete=captured.append,
        )
        push_seconds(rec, 0.4)
        meta['tgid'] = 222                   # decoder has moved on mid-call
        push_seconds(rec, 0.4)
        time.sleep(0.08)
        rec.poll()
        assert captured[0].metadata['tgid'] == 111

    def test_long_transmission_is_split_at_max_call_secs(
        self, store: ha_bridge.ClipStore, captured: list
    ) -> None:
        rec = ha_bridge.CallRecorder(
            store, hang_time_secs=0.05, min_call_secs=0.1,
            max_call_secs=1.0, on_complete=captured.append,
        )
        push_seconds(rec, 2.5)
        assert len(captured) >= 2

    def test_flush_closes_an_in_progress_call(
        self, recorder: ha_bridge.CallRecorder, captured: list
    ) -> None:
        push_seconds(recorder, 1.0)
        recorder.flush()
        assert len(captured) == 1

    def test_completed_clip_lands_in_the_store(
        self, recorder: ha_bridge.CallRecorder, captured: list,
        store: ha_bridge.ClipStore,
    ) -> None:
        push_seconds(recorder, 0.5)
        time.sleep(0.08)
        recorder.poll()
        assert store.get(captured[0].id) is captured[0]


# ---------------------------------------------------------------------------
# Loudness normalisation
# ---------------------------------------------------------------------------


class TestNormalisation:
    """Live clips span ~28 dB of RMS between talkgroups; even that out."""

    def test_quiet_clip_is_brought_up(self) -> None:
        quiet = tone(8_000, amp=400)
        out, gain_db = ha_bridge.normalize_pcm16(quiet, 8_000, target_rms=3_000.0)
        assert gain_db > 6.0
        assert ha_bridge.speech_rms(out) > ha_bridge.speech_rms(quiet) * 2

    def test_loud_clip_is_brought_down(self) -> None:
        loud = tone(8_000, amp=30_000)
        out, gain_db = ha_bridge.normalize_pcm16(loud, 8_000, target_rms=3_000.0)
        assert gain_db < 0.0
        assert ha_bridge.peak_amplitude(out) < ha_bridge.peak_amplitude(loud)

    def test_normalised_clips_converge_on_a_similar_level(self) -> None:
        levels = [
            ha_bridge.speech_rms(ha_bridge.normalize_pcm16(tone(8_000, amp=a), 8_000)[0])
            for a in (400, 3_000, 12_000, 30_000)
        ]
        assert max(levels) / min(levels) < 1.5     # was ~75x before

    def test_never_exceeds_the_peak_ceiling(self) -> None:
        out, _g = ha_bridge.normalize_pcm16(tone(8_000, amp=1_000), 8_000,
                                            target_rms=30_000.0, peak_ceiling=29_000)
        assert ha_bridge.peak_amplitude(out) <= 29_000

    def test_gain_is_capped_so_silence_is_not_amplified_into_noise(self) -> None:
        _out, gain_db = ha_bridge.normalize_pcm16(tone(8_000, amp=5), 8_000,
                                                  target_rms=3_000.0, max_gain_db=24.0)
        assert gain_db <= 24.01

    def test_already_correct_level_is_left_alone(self) -> None:
        pcm = tone(8_000, amp=4_200)
        out, gain_db = ha_bridge.normalize_pcm16(pcm, 8_000, target_rms=3_000.0)
        assert gain_db == 0.0
        assert out is pcm

    def test_empty_input_is_safe(self) -> None:
        assert ha_bridge.normalize_pcm16(b'', 8_000) == (b'', 0.0)

    def test_speech_rms_ignores_pauses(self) -> None:
        """Whole-clip RMS would be dragged down by the gaps between phrases."""
        speech = tone(4_000, amp=8_000)
        with_pause = speech + b'\x00' * 8_000 + speech
        assert ha_bridge.speech_rms(with_pause) == pytest.approx(
            ha_bridge.speech_rms(speech), rel=0.15)

    def test_recorder_normalises_and_records_the_gain(
        self, store: ha_bridge.ClipStore, captured: list,
    ) -> None:
        rec = ha_bridge.CallRecorder(store, hang_time_secs=0.05, min_call_secs=0.3,
                                     on_complete=captured.append)
        for _ in range(50):
            rec.push(tone(160, amp=500))
        time.sleep(0.08)
        rec.poll()
        clip = captured[0]
        assert clip.metadata['gain_db'] > 0
        assert clip.metadata['peak'] == pytest.approx(500, rel=0.05)   # as received
        assert ha_bridge.peak_amplitude(clip.pcm) > 500                # as stored

    def test_normalisation_can_be_switched_off(
        self, store: ha_bridge.ClipStore, captured: list,
    ) -> None:
        rec = ha_bridge.CallRecorder(store, hang_time_secs=0.05, min_call_secs=0.3,
                                     normalize=False, on_complete=captured.append)
        for _ in range(50):
            rec.push(tone(160, amp=500))
        time.sleep(0.08)
        rec.poll()
        assert captured[0].metadata['gain_db'] == 0.0
        assert ha_bridge.peak_amplitude(captured[0].pcm) == pytest.approx(500, rel=0.05)


# ---------------------------------------------------------------------------
# Speech-likeness heuristic
# ---------------------------------------------------------------------------


class TestVoicedRatio:
    def test_periodic_tone_scores_high(self) -> None:
        assert ha_bridge.voiced_ratio(tone(16_000, freq=200)) > 0.8

    def test_silence_scores_zero(self) -> None:
        assert ha_bridge.voiced_ratio(b'\x00' * 16_000) == 0.0

    def test_too_short_input_is_safe(self) -> None:
        assert ha_bridge.voiced_ratio(tone(100)) == 0.0

    def test_gate_is_off_by_default(
        self, store: ha_bridge.ClipStore, captured: list,
    ) -> None:
        """It is a heuristic, so it must not silently discard traffic."""
        rec = ha_bridge.CallRecorder(store, hang_time_secs=0.05, min_call_secs=0.3,
                                     on_complete=captured.append)
        assert rec.min_voiced_ratio == 0.0
        for _ in range(50):
            rec.push(tone(160))
        time.sleep(0.08)
        rec.poll()
        assert len(captured) == 1
        assert 'voiced_ratio' not in captured[0].metadata

    def test_gate_discards_aperiodic_audio_when_enabled(
        self, store: ha_bridge.ClipStore, captured: list,
    ) -> None:
        rec = ha_bridge.CallRecorder(store, hang_time_secs=0.05, min_call_secs=0.3,
                                     min_voiced_ratio=0.5, on_complete=captured.append)
        # Deterministic pseudo-noise: aperiodic, so it should not read as voice.
        seed = 12345
        noise = bytearray()
        for _ in range(16_000):
            seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
            noise += struct.pack('<h', (seed % 16_000) - 8_000)
        for i in range(0, len(noise), 320):
            rec.push(bytes(noise[i:i + 320]))
        time.sleep(0.08)
        rec.poll()
        assert captured == []
        assert rec.calls_dropped == 1


# ---------------------------------------------------------------------------
# Hallucination filtering
# ---------------------------------------------------------------------------


class TestHallucinationDetection:
    @pytest.mark.parametrize('text', [
        'Thank you for watching!',
        'Please subscribe to my channel',
        'Subtitles by the Amara.org community',
        '[Music]',
        '(upbeat music)',
        '♪ ♪',
        'go ahead go ahead go ahead go ahead go ahead go ahead',
        'the the the the the the the the',
    ])
    def test_recognises_known_failure_output(self, text: str) -> None:
        assert ha_bridge.is_probable_hallucination(text) is True

    @pytest.mark.parametrize('text', [
        'engine twelve on scene working structure fire',
        'dispatch show me out at four hundred block main street',
        'copy that',
        '',
        'medic three transporting one patient priority two',
    ])
    def test_leaves_real_traffic_alone(self, text: str) -> None:
        assert ha_bridge.is_probable_hallucination(text) is False

    def test_extra_phrases_are_configurable(self) -> None:
        assert ha_bridge.is_probable_hallucination('This video is sponsored by') is False
        assert ha_bridge.is_probable_hallucination(
            'This video is sponsored by', ('sponsored by',)) is True

    def test_short_repeated_phrase_is_not_over_flagged(self) -> None:
        """Real radio traffic does repeat itself; only pathological loops count."""
        assert ha_bridge.is_probable_hallucination('copy copy') is False


# ---------------------------------------------------------------------------
# Clip store
# ---------------------------------------------------------------------------


def make_clip(clip_id: str, samples: int = 8_000) -> ha_bridge.CallClip:
    return ha_bridge.CallClip(clip_id, 0.0, 1.0, tone(samples), 8_000, {})


class TestClipStore:
    def test_recent_is_newest_first(self) -> None:
        s = ha_bridge.ClipStore()
        for i in range(3):
            s.add(make_clip('c%d' % i, samples=160))
        assert [c.id for c in s.recent()] == ['c2', 'c1', 'c0']

    def test_evicts_by_clip_count(self) -> None:
        s = ha_bridge.ClipStore(max_clips=2)
        for i in range(4):
            s.add(make_clip('c%d' % i, samples=160))
        assert [c.id for c in s.recent()] == ['c3', 'c2']

    def test_evicts_by_total_bytes(self) -> None:
        s = ha_bridge.ClipStore(max_clips=100, max_bytes=8_000)
        for i in range(5):
            s.add(make_clip('c%d' % i, samples=2_000))   # 4 000 bytes each
        assert s.stats()['bytes'] <= 8_000

    def test_evicted_clip_is_no_longer_retrievable(self) -> None:
        s = ha_bridge.ClipStore(max_clips=1)
        s.add(make_clip('old', samples=160))
        s.add(make_clip('new', samples=160))
        assert s.get('old') is None
        assert s.get('new') is not None


# ---------------------------------------------------------------------------
# Keyword matching
# ---------------------------------------------------------------------------


class TestKeywordMatching:
    def test_matching_is_case_insensitive(self) -> None:
        kw = ha_bridge._compile_keywords(['structure fire'])
        assert ha_bridge.match_keywords('a STRUCTURE FIRE on main', kw) == ['structure fire']

    def test_returns_the_configured_spelling_not_the_transcript_spelling(self) -> None:
        kw = ha_bridge._compile_keywords(['Officer Down'])
        assert ha_bridge.match_keywords('officer down', kw) == ['Officer Down']

    def test_does_not_match_inside_a_longer_word(self) -> None:
        kw = ha_bridge._compile_keywords(['fire'])
        assert ha_bridge.match_keywords('the firehouse is quiet', kw) == []

    def test_matches_every_keyword_present(self) -> None:
        kw = ha_bridge._compile_keywords(['fire', 'ems', 'police'])
        assert ha_bridge.match_keywords('fire and ems responding', kw) == ['fire', 'ems']

    def test_terms_with_punctuation_fall_back_to_substring(self) -> None:
        kw = ha_bridge._compile_keywords(['10-33'])
        assert ha_bridge.match_keywords('we have a 10-33', kw) == ['10-33']

    def test_blank_terms_are_ignored(self) -> None:
        assert ha_bridge._compile_keywords(['', '   ', 'fire']) != []
        assert len(ha_bridge._compile_keywords(['', '   ', 'fire'])) == 1

    def test_empty_transcript_matches_nothing(self) -> None:
        kw = ha_bridge._compile_keywords(['fire'])
        assert ha_bridge.match_keywords('', kw) == []


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestHomeAssistantConfig:
    def test_absent_block_is_disabled(self) -> None:
        assert ha_bridge.HomeAssistantConfig(None).enabled is False

    def test_a_url_alone_enables_the_bridge(self) -> None:
        cfg = ha_bridge.HomeAssistantConfig({'url': 'http://ha.local:8123'})
        assert cfg.enabled is True

    def test_enabled_false_wins_over_a_url(self) -> None:
        cfg = ha_bridge.HomeAssistantConfig({'url': 'http://ha.local:8123', 'enabled': False})
        assert cfg.enabled is False

    def test_trailing_slash_is_stripped_from_the_url(self) -> None:
        cfg = ha_bridge.HomeAssistantConfig({'url': 'http://ha.local:8123/'})
        assert cfg.url == 'http://ha.local:8123'

    def test_token_can_come_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """So a long-lived credential need not be committed to the config file."""
        monkeypatch.setenv('OP25_HA_TOKEN', 'from-env')
        cfg = ha_bridge.HomeAssistantConfig({'url': 'http://ha.local:8123'})
        assert cfg.token == 'from-env'

    def test_config_token_wins_over_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('OP25_HA_TOKEN', 'from-env')
        cfg = ha_bridge.HomeAssistantConfig({'url': 'http://x', 'token': 'from-cfg'})
        assert cfg.token == 'from-cfg'

    def test_stt_requires_url_token_and_engine(self) -> None:
        assert ha_bridge.HomeAssistantConfig({'url': 'http://x'}).stt_configured is False
        cfg = ha_bridge.HomeAssistantConfig({'url': 'http://x', 'token': 't'})
        assert cfg.stt_configured is True

    def test_webhook_requires_url_and_id(self) -> None:
        assert ha_bridge.HomeAssistantConfig({'url': 'http://x'}).webhook_configured is False
        cfg = ha_bridge.HomeAssistantConfig({'url': 'http://x', 'webhook_id': 'w'})
        assert cfg.webhook_configured is True

    def test_talkgroup_filter_is_parsed_as_integers(self) -> None:
        cfg = ha_bridge.HomeAssistantConfig({'url': 'http://x', 'talkgroups': ['101', 202]})
        assert cfg.talkgroups == [101, 202]


class TestBridgeFiltering:
    """submit() must be cheap and must never block the audio thread."""

    def test_disabled_bridge_accepts_nothing(self) -> None:
        bridge = ha_bridge.HomeAssistantBridge(ha_bridge.HomeAssistantConfig(None))
        bridge.submit(make_clip('a'))
        assert bridge.submitted == 0

    def test_talkgroup_filter_rejects_other_talkgroups(self) -> None:
        cfg = ha_bridge.HomeAssistantConfig({'url': 'http://x', 'talkgroups': [101]})
        bridge = ha_bridge.HomeAssistantBridge(cfg)
        clip = make_clip('a')
        clip.metadata['tgid'] = 999
        bridge.submit(clip)
        assert bridge.submitted == 0

    def test_talkgroup_filter_accepts_a_listed_talkgroup(self) -> None:
        cfg = ha_bridge.HomeAssistantConfig({'url': 'http://x', 'talkgroups': [101]})
        bridge = ha_bridge.HomeAssistantBridge(cfg)
        clip = make_clip('a')
        clip.metadata['tgid'] = 101
        bridge.submit(clip)
        assert bridge.submitted == 1

    def test_a_full_queue_drops_the_oldest_not_the_newest(self) -> None:
        """A keyword alert cares about what is happening now."""
        cfg = ha_bridge.HomeAssistantConfig({'url': 'http://x'})
        bridge = ha_bridge.HomeAssistantBridge(cfg, queue_size=2)
        for i in range(5):
            bridge.submit(make_clip('c%d' % i, samples=160))
        assert bridge.dropped == 3
        assert bridge._q.qsize() == 2


class TestTokenSources:
    """Three ways to supply the token; the config file should be the last resort."""

    def test_token_file_is_read(self, tmp_path: Any) -> None:
        p = tmp_path / 'ha_token'
        p.write_text('  file-token\n')
        cfg = ha_bridge.HomeAssistantConfig(
            {'url': 'http://x', 'token_file': str(p)})
        assert cfg.token == 'file-token'

    def test_explicit_token_wins_over_the_file(self, tmp_path: Any) -> None:
        p = tmp_path / 'ha_token'
        p.write_text('file-token')
        cfg = ha_bridge.HomeAssistantConfig(
            {'url': 'http://x', 'token': 'inline', 'token_file': str(p)})
        assert cfg.token == 'inline'

    def test_token_file_wins_over_the_environment(
        self, tmp_path: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv('OP25_HA_TOKEN', 'from-env')
        p = tmp_path / 'ha_token'
        p.write_text('file-token')
        cfg = ha_bridge.HomeAssistantConfig(
            {'url': 'http://x', 'token_file': str(p)})
        assert cfg.token == 'file-token'

    def test_a_missing_token_file_falls_back_to_the_environment(
        self, tmp_path: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv('OP25_HA_TOKEN', 'from-env')
        cfg = ha_bridge.HomeAssistantConfig(
            {'url': 'http://x', 'token_file': str(tmp_path / 'nope')})
        assert cfg.token == 'from-env'


class TestConfigRedaction:
    """/api/config and get_full_config are both unauthenticated."""

    def test_token_is_masked(self) -> None:
        out = ha_bridge.redact_config(
            {'terminal': {'home_assistant': {'token': 'secret', 'url': 'http://x'}}})
        ha = out['terminal']['home_assistant']
        assert ha['token'] == '***redacted***'
        assert ha['url'] == 'http://x'

    def test_an_empty_token_is_left_alone(self) -> None:
        out = ha_bridge.redact_config({'token': ''})
        assert out['token'] == ''

    def test_lists_are_walked(self) -> None:
        out = ha_bridge.redact_config({'a': [{'token': 'secret'}]})
        assert out['a'][0]['token'] == '***redacted***'

    def test_the_original_is_not_mutated(self) -> None:
        original = {'token': 'secret'}
        ha_bridge.redact_config(original)
        assert original['token'] == 'secret'

    def test_token_file_path_is_not_a_secret(self) -> None:
        """The point of token_file is that the path can stay in the config."""
        out = ha_bridge.redact_config({'token_file': '/etc/op25/ha_token'})
        assert out['token_file'] == '/etc/op25/ha_token'


class TestTranscriptPending:
    """The UI must be able to tell "waiting" from "nothing came back"."""

    def test_a_new_clip_is_not_pending(self) -> None:
        assert make_clip('a').transcript_pending is False

    def test_pending_is_omitted_from_the_payload_when_false(self) -> None:
        assert 'transcript_pending' not in make_clip('a').to_dict()

    def test_pending_is_published_when_set(self) -> None:
        clip = make_clip('a')
        clip.transcript_pending = True
        assert clip.to_dict()['transcript_pending'] is True

    def test_will_transcribe_needs_speech_to_text_configured(self) -> None:
        """A webhook-only bridge has no transcript to wait for."""
        cfg = ha_bridge.HomeAssistantConfig({'url': 'http://x', 'webhook_id': 'w'})
        bridge = ha_bridge.HomeAssistantBridge(cfg)
        assert bridge.accepts(make_clip('a')) is True
        assert bridge.will_transcribe(make_clip('a')) is False

    def test_will_transcribe_when_stt_is_configured(self) -> None:
        cfg = ha_bridge.HomeAssistantConfig(
            {'url': 'http://x', 'token': 't', 'stt_engine': 'stt.faster_whisper'})
        bridge = ha_bridge.HomeAssistantBridge(cfg)
        assert bridge.will_transcribe(make_clip('a')) is True

    def test_a_filtered_talkgroup_is_never_pending(self) -> None:
        cfg = ha_bridge.HomeAssistantConfig(
            {'url': 'http://x', 'token': 't', 'talkgroups': [101]})
        bridge = ha_bridge.HomeAssistantBridge(cfg)
        clip = make_clip('a')
        clip.metadata['tgid'] = 999
        assert bridge.will_transcribe(clip) is False

    def test_a_disabled_bridge_is_never_pending(self) -> None:
        bridge = ha_bridge.HomeAssistantBridge(ha_bridge.HomeAssistantConfig(None))
        assert bridge.will_transcribe(make_clip('a')) is False

    def test_a_shed_clip_stops_being_pending(self) -> None:
        """Otherwise its row spins forever: it will never be transcribed."""
        cfg = ha_bridge.HomeAssistantConfig({'url': 'http://x', 'token': 't'})
        settled: list = []
        bridge = ha_bridge.HomeAssistantBridge(
            cfg, on_transcript=settled.append, queue_size=1)
        clips = [make_clip('c%d' % i, samples=160) for i in range(3)]
        for c in clips:
            c.transcript_pending = True
            bridge.submit(c)

        assert bridge.dropped == 2
        # The two evicted clips were released; the one still queued was not.
        assert [c.id for c in settled] == ['c0', 'c1']
        assert [c.transcript_pending for c in clips] == [False, False, True]

    def test_processing_clears_pending_before_notifying(self, stub_ha: Any) -> None:
        """The UI's row update and the flag clear must be the same message."""
        _srv, url = stub_ha
        seen: list = []
        bridge = bridge_for(url)
        bridge.on_transcript = lambda c: seen.append(c.transcript_pending)
        clip = make_clip('a')
        clip.transcript_pending = True
        bridge._process(clip)
        assert seen == [False]
        assert clip.transcript_pending is False


# ---------------------------------------------------------------------------
# Home Assistant HTTP round-trips (against a stub HA)
# ---------------------------------------------------------------------------


class _StubHA(BaseHTTPRequestHandler):
    """Stands in for Home Assistant: /api/stt/<engine> and /api/webhook/<id>."""

    requests: list = []          # class-level: (path, headers, body)
    stt_status = 200
    stt_body = {'result': 'success', 'text': 'engine twelve structure fire'}
    # What GET /api/stt/<engine> advertises. Defaults mirror the Wyoming
    # Whisper add-on, which is the engine that actually trips people up: bare
    # ISO-639-1 language codes, not the regional tags HA Cloud uses.
    stt_caps: Any = {
        'languages': ['en', 'es', 'fr', 'de'],
        'formats': ['wav'],
        'codecs': ['pcm'],
        'sample_rates': [16000],
        'bit_rates': [16],
        'channels': [1],
    }

    def do_GET(self) -> None:                        # noqa: N802 (BaseHTTPRequestHandler API)
        type(self).requests.append((self.path, dict(self.headers), b''))
        caps = type(self).stt_caps
        if not self.path.startswith('/api/stt/') or caps is None:
            self.send_response(404)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        payload = json.dumps(caps).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    upload_status = 200

    def do_POST(self) -> None:                       # noqa: N802 (BaseHTTPRequestHandler API)
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        type(self).requests.append((self.path, dict(self.headers), body))
        if self.path == '/api/media_source/local_source/upload':
            payload = json.dumps({'media_content_id': 'x'}).encode()
            self.send_response(type(self).upload_status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif self.path.startswith('/api/stt/'):
            payload = json.dumps(type(self).stt_body).encode()
            self.send_response(type(self).stt_status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.send_response(200)
            self.send_header('Content-Length', '0')
            self.end_headers()

    def log_message(self, *_args: Any) -> None:
        pass                                          # keep pytest output clean


class _FastHTTPServer(HTTPServer):
    """HTTPServer without the reverse-DNS lookup in ``server_bind``.

    ``HTTPServer.server_bind`` calls ``socket.getfqdn()`` purely to populate
    ``server_name``, which nothing here reads — and on a machine whose
    resolver is slow to answer for 127.0.0.1 that lookup blocks for tens of
    seconds before the first test can run.
    """

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


@pytest.fixture(scope='module')
def _stub_ha_server():
    """One stub server for the module — shutdown() polls, so avoid per-test."""
    srv = _FastHTTPServer(('127.0.0.1', 0), _StubHA)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()


@pytest.fixture()
def stub_ha(_stub_ha_server: Any):
    _StubHA.requests = []
    _StubHA.stt_status = 200
    _StubHA.upload_status = 200
    _StubHA.stt_body = {'result': 'success', 'text': 'engine twelve structure fire'}
    _StubHA.stt_caps = {
        'languages': ['en', 'es', 'fr', 'de'],
        'formats': ['wav'],
        'codecs': ['pcm'],
        'sample_rates': [16000],
        'bit_rates': [16],
        'channels': [1],
    }
    return _stub_ha_server, 'http://127.0.0.1:%d' % _stub_ha_server.server_address[1]


def bridge_for(url: str, **extra: Any) -> ha_bridge.HomeAssistantBridge:
    cfg = ha_bridge.HomeAssistantConfig(dict(
        {'url': url, 'token': 'tok', 'webhook_id': 'op25_call',
         'keywords': ['structure fire'], 'public_url': 'http://op25.local:8080'},
        **extra,
    ))
    return ha_bridge.HomeAssistantBridge(cfg)


class TestMediaUpload:
    """Push the audio to Home Assistant instead of waiting to be asked for it."""

    def _upload(self, url: str, **extra: Any):
        bridge = bridge_for(url, media_upload=True, **extra)
        clip = make_clip('ffa24f1fcd21')
        clip.started = 1785961055.15
        path = bridge._upload_media(clip)
        req = next((r for r in _StubHA.requests
                    if r[0] == '/api/media_source/local_source/upload'), None)
        return bridge, path, req

    def test_off_by_default(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        assert bridge_for(url)._upload_media(make_clip('a')) == ''
        assert _StubHA.requests == []

    def test_returns_the_path_home_assistant_will_serve(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _bridge, path, _req = self._upload(url)
        assert path.startswith('/media/local/scanner/')
        assert path.endswith('_ffa24f1fcd21.wav')

    def test_the_filename_carries_the_call_time(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _bridge, path, _req = self._upload(url)
        stamp = time.strftime('%Y-%m-%d_%H%M%S', time.localtime(1785961055.15))
        assert path.split('/')[-1].startswith(stamp)

    def test_url_base_can_differ_from_the_upload_target(self, stub_ha: Any) -> None:
        """Uploaded under <config>/www, but reachable at /local/... .

        /media/<source>/<dir> is served by a view with requires_auth = True,
        so a notification or a dashboard link to it gets a 401. The same file
        under <config>/www is served as an unauthenticated static path.
        """
        _srv, url = stub_ha
        _bridge, path, req = self._upload(
            url, media_source='www', media_dir='scanner',
            media_url_base='/local/scanner')
        assert path.startswith('/local/scanner/')
        # ...while the upload still addresses the media source, not the URL.
        assert b'media-source://media_source/www/scanner' in req[2]

    def test_url_base_tolerates_a_trailing_slash(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _bridge, path, _req = self._upload(url, media_url_base='/local/scanner/')
        assert '//' not in path

    def test_target_folder_is_configurable(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _bridge, path, req = self._upload(url, media_dir='op25')
        assert path.startswith('/media/local/op25/')
        assert b'media-source://media_source/local/op25' in req[2]

    def test_posts_multipart_with_both_fields(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _bridge, _path, req = self._upload(url)
        headers, body = req[1], req[2]
        assert headers['Content-Type'].startswith('multipart/form-data; boundary=')
        assert b'name="media_content_id"' in body
        assert b'name="file"; filename="' in body

    def test_declares_an_audio_content_type(self, stub_ha: Any) -> None:
        """The endpoint rejects anything not image/video/audio."""
        _srv, url = stub_ha
        _bridge, _path, req = self._upload(url)
        assert b'Content-Type: audio/wav' in req[2]

    def test_body_is_a_real_riff_container_not_bare_pcm(self, stub_ha: Any) -> None:
        """It has to play in a browser, unlike what the STT endpoint gets."""
        _srv, url = stub_ha
        _bridge, _path, req = self._upload(url)
        body = req[2]
        assert b'RIFF' in body and b'WAVE' in body

    def test_multipart_is_well_formed(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _bridge, _path, req = self._upload(url)
        boundary = req[1]['Content-Type'].split('boundary=')[1]
        body = req[2]
        assert body.startswith(('--' + boundary).encode())
        assert body.endswith(('--' + boundary + '--\r\n').encode())
        assert body.count(('--' + boundary).encode()) == 3   # 2 parts + closer

    def test_sends_the_bearer_token(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _bridge, _path, req = self._upload(url)
        assert req[1]['Authorization'] == 'Bearer tok'

    def test_counts_a_success(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        bridge, _path, _req = self._upload(url)
        assert bridge.stats()['media_uploaded'] == 1
        assert bridge.stats()['media_errors'] == 0

    def test_a_rejected_upload_is_reported_not_raised(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _StubHA.upload_status = 401                   # non-admin token
        bridge, path, _req = self._upload(url)
        assert path == ''
        assert bridge.stats()['media_errors'] == 1

    def test_a_failed_upload_leaves_the_clip_without_a_path(self, stub_ha: Any) -> None:
        """The hit is still logged and still notified — just without audio."""
        _srv, url = stub_ha
        _StubHA.upload_status = 500
        bridge = bridge_for(url, media_upload=True)
        clip = make_clip('a')
        bridge._process(clip)
        assert clip.media_path == ''
        assert 'media_path' not in clip.to_dict()

    def test_the_webhook_names_the_uploaded_file(self, stub_ha: Any) -> None:
        """Upload must land before the webhook, or the automation has no path."""
        _srv, url = stub_ha
        bridge = bridge_for(url, media_upload=True)
        bridge._process(make_clip('ffa24f1fcd21'))
        hook = next(r for r in _StubHA.requests if r[0].startswith('/api/webhook/'))
        payload = json.loads(hook[2])
        assert payload['media_path'].startswith('/media/local/scanner/')
        # ...and the ordering that guarantees it.
        paths = [r[0] for r in _StubHA.requests]
        assert (paths.index('/api/media_source/local_source/upload')
                < paths.index(hook[0]))


class TestMediaFilename:
    """The filename is the only metadata that travels with the audio.

    Home Assistant's media library is bare files — no sidecar, no database —
    so a dashboard can only filter on what the name itself carries.
    """

    def _name(self, tgid: Any = 27104, tag: str = 'SCHP Lexington', **cfg: Any) -> str:
        bridge = ha_bridge.HomeAssistantBridge(
            ha_bridge.HomeAssistantConfig(dict({'url': 'http://x'}, **cfg)))
        clip = make_clip('ffa24f1fcd21')
        clip.started = 1785961055.15
        clip.metadata.update({'tgid': tgid, 'talkgroup': tag})
        return bridge._media_filename(clip)

    def test_has_exactly_five_underscore_fields(self) -> None:
        """The dashboard splits on '_' — the count must not vary."""
        parts = self._name()[:-len('.wav')].split('_')
        assert len(parts) == ha_bridge.HomeAssistantBridge.MEDIA_NAME_FIELDS

    def test_carries_date_time_tgid_tag_and_id(self) -> None:
        parts = self._name()[:-len('.wav')].split('_')
        assert parts[0] == time.strftime('%Y-%m-%d', time.localtime(1785961055.15))
        assert parts[2] == '27104'
        assert parts[3] == 'SCHP-Lexington'
        assert parts[4] == 'ffa24f1fcd21'

    def test_spaces_and_punctuation_become_single_dashes(self) -> None:
        assert self._name(tag='Lex Co EMS / LMC (North)').split('_')[3] \
            == 'Lex-Co-EMS-LMC-North'

    def test_underscores_in_the_tag_cannot_add_a_field(self) -> None:
        """Otherwise one oddly-named talkgroup breaks every row's parsing."""
        name = self._name(tag='RCSD_Reg_4/5')
        assert len(name[:-4].split('_')) == 5
        assert name.split('_')[3] == 'RCSD-Reg-4-5'

    def test_an_unnamed_talkgroup_is_labelled_not_blank(self) -> None:
        assert self._name(tag='').split('_')[3] == 'unknown'
        assert self._name(tag='///').split('_')[3] == 'unknown'

    def test_a_missing_tgid_becomes_zero(self) -> None:
        assert self._name(tgid=None).split('_')[2] == '0'
        assert self._name(tgid='rubbish').split('_')[2] == '0'

    def test_a_long_tag_is_truncated(self) -> None:
        name = self._name(tag='A' * 200)
        assert len(name.split('_')[3]) == 40

    def test_stays_url_and_filesystem_safe(self) -> None:
        """It becomes both a filename and a path segment in a URL."""
        name = self._name(tag='Weird/\\:*?"<>| tag')
        assert re.fullmatch(r'[A-Za-z0-9._-]+', name), name

    def test_names_sort_chronologically(self) -> None:
        """A directory listing is then already in call order."""
        early = self._name()
        bridge = ha_bridge.HomeAssistantBridge(
            ha_bridge.HomeAssistantConfig({'url': 'http://x'}))
        clip = make_clip('bbbb')
        clip.started = 1785961055.15 + 3600
        clip.metadata.update({'tgid': 1, 'talkgroup': 'A'})
        assert sorted([bridge._media_filename(clip), early])[0] == early


class TestCapabilityNegotiation:
    """HA answers a format mismatch with a bare 415, so ask what it wants first."""

    def test_reads_the_engine_capabilities(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        caps = bridge_for(url).fetch_stt_capabilities()
        assert caps is not None and caps['sample_rates'] == [16000]

    def test_regional_language_falls_back_to_the_base_code(self, stub_ha: Any) -> None:
        """en-US is what HA Cloud advertises; Wyoming/Whisper offers only en."""
        _srv, url = stub_ha
        bridge = bridge_for(url, language='en-US')
        bridge.negotiate()
        assert bridge.cfg.language == 'en'

    def test_a_supported_language_is_left_alone(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        bridge = bridge_for(url, language='es')
        bridge.negotiate()
        assert bridge.cfg.language == 'es'

    def test_a_base_code_matches_a_regional_engine(self, stub_ha: Any) -> None:
        """The mirror image: our 'en' against a cloud engine's en-US/en-GB."""
        _srv, url = stub_ha
        _StubHA.stt_caps = dict(_StubHA.stt_caps, languages=['en-US', 'en-GB', 'de-DE'])
        bridge = bridge_for(url, language='en')
        bridge.negotiate()
        assert bridge.cfg.language == 'en-US'

    def test_an_unmatchable_language_is_left_for_the_user(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        bridge = bridge_for(url, language='cy')
        bridge.negotiate()
        assert bridge.cfg.language == 'cy'

    def test_sample_rate_is_raised_to_something_supported(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _StubHA.stt_caps = dict(_StubHA.stt_caps, sample_rates=[22050, 44100])
        bridge = bridge_for(url, stt_sample_rate=16000)
        bridge.negotiate()
        assert bridge.cfg.stt_rate == 22050

    def test_negotiation_survives_an_unreachable_engine(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _StubHA.stt_caps = None                       # 404 on the capability GET
        bridge = bridge_for(url, language='en-US')
        bridge.negotiate()
        assert bridge.cfg.language == 'en-US'         # unchanged, and no raise

    def test_a_415_names_the_offending_field(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _StubHA.stt_status = 415
        bridge = bridge_for(url, language='en-US')    # deliberately not negotiated
        _text, err = bridge._transcribe(make_clip('a'))
        assert '415' in err
        assert "language 'en-US' is not in the engine list" in err

    def test_a_415_with_nothing_obviously_wrong_says_so(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _StubHA.stt_status = 415
        bridge = bridge_for(url, language='en')
        _text, err = bridge._transcribe(make_clip('a'))
        assert 'advertises all of those as supported' in err


class TestRoutableAddress:
    """public_url has to be somewhere Home Assistant can actually fetch from."""

    def test_returns_a_non_loopback_address_for_a_real_host(self) -> None:
        import websocket_server as ws
        addr = ws._routable_address_for('http://192.0.2.1:8123')   # TEST-NET-1
        # No packets are sent, so this works without a route to the host on
        # any machine with a default route; on a fully isolated one it is ''.
        assert addr == '' or not addr.startswith('127.')

    def test_loopback_target_is_rejected(self) -> None:
        """Resolving to 127.0.0.1 is the bug, not the fix."""
        import websocket_server as ws
        assert ws._routable_address_for('http://127.0.0.1:8123') == ''

    def test_garbage_and_empty_are_safe(self) -> None:
        import websocket_server as ws
        assert ws._routable_address_for('') == ''
        assert ws._routable_address_for('not a url') == ''
        assert ws._routable_address_for('http://') == ''


class TestSpeechToTextRequest:
    def test_transcript_is_returned(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        text, err = bridge_for(url)._transcribe(make_clip('a', samples=4_000))
        assert err == ''
        assert text == 'engine twelve structure fire'

    def test_posts_to_the_configured_engine(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        bridge_for(url, stt_engine='stt.my_whisper')._transcribe(make_clip('a', samples=800))
        assert _StubHA.requests[0][0] == '/api/stt/stt.my_whisper'

    def test_sends_the_bearer_token(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        bridge_for(url)._transcribe(make_clip('a', samples=800))
        assert _StubHA.requests[0][1]['Authorization'] == 'Bearer tok'

    def test_declares_16k_mono_16bit(self, stub_ha: Any) -> None:
        """Home Assistant's STT API accepts nothing else."""
        _srv, url = stub_ha
        bridge_for(url)._transcribe(make_clip('a', samples=800))
        header = _StubHA.requests[0][1]['X-Speech-Content']
        assert 'sample_rate=16000' in header
        assert 'bit_rate=16' in header
        assert 'channel=1' in header

    def test_body_is_raw_pcm_upsampled_to_16k(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        bridge_for(url)._transcribe(make_clip('a', samples=800))
        body = _StubHA.requests[0][2]
        assert body[:4] != b'RIFF'
        assert len(body) == 800 * 2 * 2

    def test_wav_mode_sends_a_container(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        bridge_for(url, stt_audio='wav')._transcribe(make_clip('a', samples=800))
        assert _StubHA.requests[0][2][:4] == b'RIFF'

    def test_http_error_is_reported_not_raised(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _StubHA.stt_status = 401
        text, err = bridge_for(url)._transcribe(make_clip('a', samples=800))
        assert text == ''
        assert '401' in err

    def test_unreachable_home_assistant_is_reported_not_raised(self) -> None:
        bridge = bridge_for('http://127.0.0.1:1')      # nothing listening
        bridge.cfg.timeout = 2.0
        text, err = bridge._transcribe(make_clip('a', samples=800))
        assert text == ''
        assert err != ''

    def test_non_success_result_is_an_error(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _StubHA.stt_body = {'result': 'error', 'text': ''}
        text, err = bridge_for(url)._transcribe(make_clip('a', samples=800))
        assert text == ''
        assert 'error' in err


class TestWebhookPost:
    def _process(self, url: str, transcript_ok: bool = True, **extra: Any):
        bridge = bridge_for(url, **extra)
        clip = make_clip('a', samples=4_000)
        clip.metadata.update({'tgid': 1211, 'talkgroup': 'FD Dispatch'})
        bridge._process(clip)
        return bridge, clip

    def test_posts_to_the_configured_webhook(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        self._process(url)
        assert _StubHA.requests[-1][0] == '/api/webhook/op25_call'

    def test_payload_carries_transcript_metadata_and_audio_url(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        self._process(url)
        body = json.loads(_StubHA.requests[-1][2])
        assert body['event'] == 'op25_call'
        assert body['transcript'] == 'engine twelve structure fire'
        assert body['talkgroup'] == 'FD Dispatch'
        assert body['tgid'] == 1211
        assert body['audio_url'] == 'http://op25.local:8080/api/calls/a/audio.wav'

    def test_keywords_are_matched_against_the_transcript(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _bridge, clip = self._process(url)
        assert clip.keywords == ['structure fire']
        assert json.loads(_StubHA.requests[-1][2])['keywords'] == ['structure fire']

    def test_keywords_only_suppresses_calls_that_did_not_match(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _StubHA.stt_body = {'result': 'success', 'text': 'nothing of interest here'}
        bridge, _clip = self._process(url, keywords_only=True)
        assert bridge.webhooks == 0
        assert all(not p.startswith('/api/webhook') for p, _h, _b in _StubHA.requests)

    def test_keywords_only_still_sends_a_match(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        bridge, _clip = self._process(url, keywords_only=True)
        assert bridge.webhooks == 1

    def test_hallucinated_transcript_never_reaches_the_webhook(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _StubHA.stt_body = {'result': 'success', 'text': 'Thank you for watching!'}
        bridge, clip = self._process(url)
        assert clip.transcript == ''
        assert clip.keywords == []
        assert clip.discarded_transcript == 'Thank you for watching!'
        assert bridge.hallucinations == 1
        assert json.loads(_StubHA.requests[-1][2])['transcript'] == ''

    def test_hallucination_filter_can_be_switched_off(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _StubHA.stt_body = {'result': 'success', 'text': 'Thank you for watching!'}
        _bridge, clip = self._process(url, filter_hallucinations=False)
        assert clip.transcript == 'Thank you for watching!'

    def test_hallucination_is_not_counted_as_a_transcription(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        _StubHA.stt_body = {'result': 'success', 'text': '[Music]'}
        bridge, _clip = self._process(url)
        assert bridge.transcribed == 0

    def test_transcript_callback_fires_for_the_ui(self, stub_ha: Any) -> None:
        _srv, url = stub_ha
        seen: list = []
        cfg = ha_bridge.HomeAssistantConfig({'url': url, 'token': 't', 'webhook_id': 'w'})
        bridge = ha_bridge.HomeAssistantBridge(cfg, on_transcript=seen.append)
        bridge._process(make_clip('a', samples=4_000))
        assert len(seen) == 1
        assert seen[0].transcript == 'engine twelve structure fire'

    def test_a_failing_webhook_does_not_raise(self, stub_ha: Any) -> None:
        _srv, _url = stub_ha
        bridge = bridge_for('http://127.0.0.1:1')
        bridge.cfg.timeout = 2.0
        bridge._post_webhook(make_clip('a', samples=800))
        assert bridge.webhook_errors == 1


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_client(client: Any) -> Any:
    """The TestClient with one transcribed clip already in the store."""
    import websocket_server

    websocket_server.clip_store = ha_bridge.ClipStore()
    clip = ha_bridge.CallClip('deadbeef', 100.0, 104.0, tone(8_000), 8_000,
                              {'tgid': 1234, 'talkgroup': 'FD Dispatch'})
    clip.transcript = 'engine twelve responding structure fire'
    clip.keywords = ['structure fire']
    websocket_server.clip_store.add(clip)
    return client


class TestCallsEndpoint:
    def test_lists_captured_calls(self, seeded_client: Any) -> None:
        body = seeded_client.get('/api/calls').json()
        assert body['count'] == 1
        assert body['calls'][0]['id'] == 'deadbeef'

    def test_exposes_transcript_and_keywords(self, seeded_client: Any) -> None:
        call = seeded_client.get('/api/calls').json()['calls'][0]
        assert call['transcript'] == 'engine twelve responding structure fire'
        assert call['keywords'] == ['structure fire']

    def test_exposes_talkgroup_metadata(self, seeded_client: Any) -> None:
        call = seeded_client.get('/api/calls').json()['calls'][0]
        assert call['tgid'] == 1234
        assert call['talkgroup'] == 'FD Dispatch'

    def test_audio_url_points_at_a_fetchable_clip(self, seeded_client: Any) -> None:
        call = seeded_client.get('/api/calls').json()['calls'][0]
        assert seeded_client.get(call['audio_url']).status_code == 200

    def test_limit_is_bounded(self, seeded_client: Any) -> None:
        assert seeded_client.get('/api/calls?limit=0').status_code == 422
        assert seeded_client.get('/api/calls?limit=5000').status_code == 422

    def test_empty_store_returns_an_empty_list(self, client: Any) -> None:
        import websocket_server
        websocket_server.clip_store = ha_bridge.ClipStore()
        assert client.get('/api/calls').json() == {
            'calls': [], 'count': 0, 'clips': 0, 'bytes': 0
        }


class TestCallAudioEndpoint:
    def test_serves_a_wav_file(self, seeded_client: Any) -> None:
        resp = seeded_client.get('/api/calls/deadbeef/audio.wav')
        assert resp.status_code == 200
        assert resp.headers['content-type'] == 'audio/wav'
        assert resp.content[:4] == b'RIFF'

    def test_wav_length_matches_the_clip(self, seeded_client: Any) -> None:
        resp = seeded_client.get('/api/calls/deadbeef/audio.wav')
        assert len(resp.content) == 44 + 8_000 * 2

    def test_resamples_on_request(self, seeded_client: Any) -> None:
        """Home Assistant's STT wants 16 kHz; the clip is stored at 8 kHz."""
        resp = seeded_client.get('/api/calls/deadbeef/audio.wav?rate=16000')
        assert struct.unpack('<I', resp.content[24:28])[0] == 16_000
        assert len(resp.content) == 44 + 8_000 * 2 * 2

    def test_unknown_id_is_404(self, seeded_client: Any) -> None:
        assert seeded_client.get('/api/calls/nope/audio.wav').status_code == 404

    def test_unsupported_rate_is_400(self, seeded_client: Any) -> None:
        assert seeded_client.get('/api/calls/deadbeef/audio.wav?rate=999').status_code == 400

    def test_filename_is_suggested_for_download(self, seeded_client: Any) -> None:
        resp = seeded_client.get('/api/calls/deadbeef/audio.wav')
        assert 'op25-deadbeef.wav' in resp.headers['content-disposition']


class TestStreamParameters:
    def test_unsupported_rate_is_rejected(self, client: Any) -> None:
        resp = client.get('/api/stream?rate=12345')
        assert resp.status_code == 400
        assert 16_000 in resp.json()['supported']

    def test_unsupported_format_is_rejected(self, client: Any) -> None:
        assert client.get('/api/stream?format=mp3').status_code == 422


class TestHaStatusEndpoint:
    def test_reports_disabled_when_unconfigured(self, client: Any) -> None:
        body = client.get('/api/ha/status').json()
        assert body['home_assistant']['enabled'] is False

    def test_reports_store_stats(self, seeded_client: Any) -> None:
        body = seeded_client.get('/api/ha/status').json()
        assert body['store']['clips'] == 1

    def test_reports_bridge_configuration_when_enabled(
        self, client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import websocket_server

        cfg = ha_bridge.HomeAssistantConfig({
            'url': 'http://ha.local:8123', 'token': 't',
            'webhook_id': 'op25_call', 'keywords': ['fire'],
        })
        monkeypatch.setattr(websocket_server, '_ha_bridge',
                            ha_bridge.HomeAssistantBridge(cfg))
        body = client.get('/api/ha/status').json()['home_assistant']
        assert body['enabled'] is True
        assert body['webhook_id'] == 'op25_call'
        assert body['keywords'] == ['fire']


# ---------------------------------------------------------------------------
# Server-side wiring
# ---------------------------------------------------------------------------


class TestServerWiring:
    def test_channel_update_becomes_clip_metadata(self) -> None:
        import websocket_server

        websocket_server._note_channel_state({
            'json_type': 'channel_update',
            'channels': ['0'],
            '0': {'tgid': 4321, 'tag': 'PD Dispatch', 'name': 'ch0',
                  'system': 'Palmetto 800', 'freq': 851_012_500,
                  'srcaddr': 55, 'srctag': 'Unit 5',
                  'encrypted': 0, 'emergency': 0},
        })
        meta = websocket_server._current_call_metadata()
        assert meta['tgid'] == 4321
        assert meta['talkgroup'] == 'PD Dispatch'
        assert meta['source_tag'] == 'Unit 5'
        assert meta['encrypted'] is False

    def test_idle_channels_produce_no_metadata(self) -> None:
        import websocket_server

        websocket_server._note_channel_state({
            'json_type': 'channel_update', 'channels': ['0'],
            '0': {'tgid': 0, 'tag': '', 'name': 'ch0'},
        })
        assert websocket_server._current_call_metadata() == {}

    def test_call_recording_can_be_switched_off(self) -> None:
        import websocket_server

        websocket_server.stop_call_capture()
        websocket_server.start_call_capture({'terminal': {'call_recording': False}})
        assert websocket_server._call_capture is None

    def test_capture_starts_without_home_assistant_configured(self) -> None:
        """/api/calls is useful on its own; HA is opt-in on top of it."""
        import websocket_server

        websocket_server.stop_call_capture()
        try:
            websocket_server.start_call_capture({'terminal': {}})
            assert websocket_server._call_capture is not None
            assert websocket_server._ha_bridge is None
        finally:
            websocket_server.stop_call_capture()

    def test_each_udp_port_gets_its_own_recorder(self) -> None:
        """DMR stereo puts timeslot B on port+1 — two independent conversations.

        Merging them into one recorder would interleave two people into a
        single clip.  (P25 only ever uses one port, so this is a no-op there.)
        """
        import websocket_server

        clips: list = []
        store = ha_bridge.ClipStore()
        capture = websocket_server.CallCapture(lambda _p: ha_bridge.CallRecorder(
            store, hang_time_secs=0.05, min_call_secs=0.3, on_complete=clips.append))

        for _ in range(50):                       # both slots talking at once
            capture.push(23456, tone(160, freq=300))
            capture.push(23457, tone(160, freq=900))
        time.sleep(0.08)
        capture.poll()

        assert len(clips) == 2
        assert {round(c.duration, 1) for c in clips} == {1.0}
        assert capture.stats()['ports'] == [23456, 23457]

    def test_capture_stats_are_aggregated_across_ports(self) -> None:
        import websocket_server

        store = ha_bridge.ClipStore()
        capture = websocket_server.CallCapture(lambda _p: ha_bridge.CallRecorder(
            store, hang_time_secs=0.05, min_call_secs=0.3))
        for port in (23456, 23457):
            for _ in range(50):
                capture.push(port, tone(160))
        capture.flush()
        assert capture.stats()['calls_captured'] == 2

    def test_public_url_defaults_to_the_bound_endpoint(self) -> None:
        import websocket_server

        websocket_server.stop_call_capture()
        try:
            websocket_server.start_call_capture(
                {'terminal': {'home_assistant': {'url': 'http://ha.local:8123'}}},
                endpoint='192.168.1.50:8080',
            )
            assert websocket_server._ha_bridge is not None
            assert websocket_server._ha_bridge.cfg.public_url == 'http://192.168.1.50:8080'
        finally:
            websocket_server.stop_call_capture()

    def test_wildcard_bind_does_not_become_a_public_url(self) -> None:
        """0.0.0.0 is not an address Home Assistant could fetch audio from."""
        import websocket_server

        websocket_server.stop_call_capture()
        try:
            websocket_server.start_call_capture(
                {'terminal': {'home_assistant': {'url': 'http://ha.local:8123'}}},
                endpoint='0.0.0.0:8080',
            )
            assert websocket_server._ha_bridge.cfg.public_url == ''
        finally:
            websocket_server.stop_call_capture()


class TestContinuity:
    """Per-call decode completeness.

    A clip is a *concatenation* of the PCM that arrived -- push() extends a
    buffer and nothing fills gaps -- so a call that lost half its LDUs yields a
    clip half as long that still sounds continuous. The live stream, paced at
    real time, renders the same loss as silence. That asymmetry is why "the
    recording is fine but the live audio is choppy" means lost frames, not a
    streaming fault, and continuity is the number that says so.
    """

    def _recorder(self, store: Any) -> Any:
        return ha_bridge.CallRecorder(store, hang_time_secs=0.05, min_call_secs=0.05,
                               min_peak=0, normalize=False)

    def _loud(self, ms: int) -> bytes:
        n = 8_000 * ms // 1_000
        return struct.pack('<%dh' % n, *([8_000] * n))

    def test_a_complete_call_is_continuity_one(self, monkeypatch: Any) -> None:
        store = ha_bridge.ClipStore()
        rec = self._recorder(store)
        t = [1_000.0]
        monkeypatch.setattr(ha_bridge.time, 'time', lambda: t[0])
        # 500 ms of audio pushed over 500 ms of wall clock: nothing lost.
        for _ in range(5):
            rec.push(self._loud(100))
            t[0] += 0.1
        t[0] += 1.0
        rec.poll()
        clip = store.recent()[0]
        assert clip.metadata['continuity'] >= 0.95

    def test_lost_frames_show_as_reduced_continuity(self, monkeypatch: Any) -> None:
        store = ha_bridge.ClipStore()
        rec = self._recorder(store)
        t = [1_000.0]
        monkeypatch.setattr(ha_bridge.time, 'time', lambda: t[0])
        # 500 ms of audio spread over 1000 ms of wall clock: half the LDUs
        # never decoded, which live playback renders as 500 ms of chop.
        for _ in range(5):
            rec.push(self._loud(100))
            t[0] += 0.2
        t[0] += 1.0
        rec.poll()
        clip = store.recent()[0]
        assert 0.4 <= clip.metadata['continuity'] <= 0.65, clip.metadata

    def test_continuity_never_exceeds_one(self, monkeypatch: Any) -> None:
        # A producer ahead of real time (UDP coalescing, a burst of LDUs) must
        # not report better-than-perfect reception.
        store = ha_bridge.ClipStore()
        rec = self._recorder(store)
        t = [1_000.0]
        monkeypatch.setattr(ha_bridge.time, 'time', lambda: t[0])
        for _ in range(5):
            rec.push(self._loud(100))
            t[0] += 0.01
        t[0] += 1.0
        rec.poll()
        assert store.recent()[0].metadata['continuity'] == 1.0

    def test_clip_duration_is_the_audio_not_the_wall_clock(
            self, monkeypatch: Any) -> None:
        # The property continuity is derived from, pinned so it cannot drift:
        # the clip holds only what arrived.
        store = ha_bridge.ClipStore()
        rec = self._recorder(store)
        t = [1_000.0]
        monkeypatch.setattr(ha_bridge.time, 'time', lambda: t[0])
        for _ in range(4):
            rec.push(self._loud(100))
            t[0] += 0.25
        t[0] += 1.0
        rec.poll()
        clip = store.recent()[0]
        assert 0.35 <= clip.duration <= 0.45      # 400 ms of audio...
        assert clip.metadata['continuity'] < 0.6   # ...over ~1 s of wall clock
