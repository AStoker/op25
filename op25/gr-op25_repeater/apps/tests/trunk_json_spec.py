"""
Trunking-module payload contracts.

The GUI was written against tk_p25's trunk_update shape, so a SmartNet or
Connect+ system either rendered blank or crashed the card that assumed a P25
field.  These tests pin the payloads each module publishes, and the Connect+
call filtering, using synthesized module state — there is no SmartNet or
Connect+ system on air here, so this is the only verification available for the
DMR work.
"""

import json
import time
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Connect+ / DMR  (tk_trbo)
# ---------------------------------------------------------------------------

CHANS = [
    {'lcn': 1, 'frequency': 461300000, 'cc': 5},
    {'lcn': 2, 'frequency': 461800000, 'cc': 5},
    {'lcn': 3, 'frequency': 463225000, 'cc': 5},
]


@pytest.fixture()
def trbo() -> Any:
    # tk_trbo pulls in GNU Radio transitively, so this fixture cannot run on a
    # bare checkout (CI without the OOT module built).  Skip rather than error.
    tk_trbo = pytest.importorskip("tk_trbo", reason="needs GNU Radio")
    tuned: list[dict[str, Any]] = []
    ctl = tk_trbo.rx_ctl(
        debug=0,
        frequency_set=lambda params: tuned.append(params),
        fa_ctrl=lambda params: None,
        chans=[dict(c) for c in CHANS],
    )
    ctl.tuned = tuned            # type: ignore[attr-defined]
    return ctl


def _grant_buf(src: int, grp: int, lcn: int, slot: int) -> bytes:
    """A Connect+ channel-grant CSBK payload as process_grant parses it."""
    return (
        bytes([0x03, 0x06])                      # op / fid (unused by parser)
        + src.to_bytes(3, 'big')                 # m_buf[2:5]  srcAddr
        + grp.to_bytes(3, 'big')                 # m_buf[5:8]  grpAddr
        + bytes([(lcn << 4) | (slot << 3)])      # m_buf[8]    lcn / slot
    )


class TestTrboSystemPayload:
    def test_type_and_identity(self, trbo: Any) -> None:
        sysdata = trbo.system_json()
        assert sysdata['type'] == 'trbo'
        assert sysdata['system'] == 'Connect+'
        assert 'Connect+' in sysdata['top_line']

    def test_lcn_table_is_published(self, trbo: Any) -> None:
        lcns = trbo.system_json()['lcn_data']
        assert sorted(lcns) == ['1', '2', '3']
        assert lcns['1']['frequency'] == 461300000
        assert [s['slot'] for s in lcns['1']['slots']] == [0, 1]

    def test_frequency_data_covers_every_channel(self, trbo: Any) -> None:
        # The GUI's frequency grid reads frequency_data; it used to be empty.
        freqs = trbo.system_json()['frequency_data']
        assert sorted(freqs) == ['461300000', '461800000', '463225000'] or \
               sorted(int(k) for k in freqs) == [461300000, 461800000, 463225000]

    def test_p25_only_fields_are_absent(self, trbo: Any) -> None:
        sysdata = trbo.system_json()
        # Sending zeros for these would make the UI claim NAC 0x0 / site 0.0.
        for key in ('nac', 'wacn', 'sysid', 'rfid', 'stid', 'band_plan', 'wuid_data'):
            assert key not in sysdata, key

    def test_to_json_emits_one_system(self, trbo: Any) -> None:
        js = json.loads(trbo.to_json())
        assert js['json_type'] == 'trunk_update'
        assert '0' in js
        assert '1' not in js          # one system, not one per receiver

    def test_rest_channel_is_reported(self, trbo: Any) -> None:
        trbo.rest_lcn = 2
        sysdata = trbo.system_json()
        assert sysdata['rest_lcn'] == 2
        assert sysdata['frequency_data'][461800000]['type'] == 'control'


class TestTrboSlotIndependence:
    def test_slots_are_separate_objects(self, trbo: Any) -> None:
        # Both slots used to alias one class object, so a slot-B grant
        # overwrote slot A — two conversations collapsed into one.
        chan = trbo.chans[1]
        assert chan.slot[0] is not chan.slot[1]
        chan.slot[0].grp_addr = 111
        chan.slot[1].grp_addr = 222
        assert chan.slot[0].grp_addr == 111

    def test_channels_do_not_share_slot_state(self, trbo: Any) -> None:
        trbo.chans[1].slot[0].grp_addr = 111
        assert trbo.chans[2].slot[0].grp_addr is None


class TestTrboGrantHandling:
    def _receiver(self, trbo: Any) -> Any:
        trbo.add_receiver(0, {})
        return trbo.receivers[0]

    def test_grant_records_talkgroup_and_logs_call(self, trbo: Any) -> None:
        rcvr = self._receiver(trbo)
        rcvr.process_grant(_grant_buf(0x123456, 4242, lcn=1, slot=0))

        assert 4242 in trbo.talkgroups
        assert trbo.talkgroups[4242]['srcaddr'] == 0x123456
        log = json.loads(trbo.get_call_log())['log']
        assert log[0]['tgid'] == 4242
        assert log[0]['slot'] == 0
        assert log[0]['freq'] == 461300000

    def test_call_log_drains(self, trbo: Any) -> None:
        rcvr = self._receiver(trbo)
        rcvr.process_grant(_grant_buf(1, 100, lcn=1, slot=0))
        assert len(json.loads(trbo.get_call_log())['log']) == 1
        assert json.loads(trbo.get_call_log())['log'] == []

    def test_grant_retunes_voice_receiver(self, trbo: Any) -> None:
        rcvr = self._receiver(trbo)
        rcvr.process_grant(_grant_buf(1, 100, lcn=2, slot=1))
        tuned = [p for p in trbo.tuned if p.get('tuner') == 1]
        assert tuned and tuned[-1]['freq'] == 461800000
        assert tuned[-1]['slot'] == 2          # slot+1

    def test_unknown_lcn_is_ignored(self, trbo: Any) -> None:
        rcvr = self._receiver(trbo)
        before = len(trbo.tuned)
        rcvr.process_grant(_grant_buf(1, 100, lcn=9, slot=0))
        assert len(trbo.tuned) == before
        assert trbo.talkgroups == {}

    def test_per_slot_grants_are_kept_apart(self, trbo: Any) -> None:
        rcvr = self._receiver(trbo)
        rcvr.process_grant(_grant_buf(0xAAA, 111, lcn=1, slot=0))
        rcvr.process_grant(_grant_buf(0xBBB, 222, lcn=1, slot=1))
        slots = trbo.system_json()['lcn_data']['1']['slots']
        assert slots[0]['tgid'] == 111
        assert slots[1]['tgid'] == 222


class TestTrboCallFiltering:
    def _receiver(self, trbo: Any) -> Any:
        trbo.add_receiver(0, {})
        return trbo.receivers[0]

    def test_lockout_blocks_a_grant(self, trbo: Any) -> None:
        rcvr = self._receiver(trbo)
        trbo.ui_command('lockout', 555, 0)
        before = len([p for p in trbo.tuned if p.get('tuner') == 1])
        rcvr.process_grant(_grant_buf(1, 555, lcn=1, slot=0))
        assert len([p for p in trbo.tuned if p.get('tuner') == 1]) == before
        # …but the talkgroup is still recorded, so it stays visible in the UI.
        assert 555 in trbo.talkgroups

    def test_whitelist_blocks_everything_else(self, trbo: Any) -> None:
        rcvr = self._receiver(trbo)
        trbo.ui_command('whitelist', 100, 0)
        rcvr.process_grant(_grant_buf(1, 200, lcn=1, slot=0))
        assert not [p for p in trbo.tuned if p.get('tuner') == 1]
        rcvr.process_grant(_grant_buf(1, 100, lcn=1, slot=0))
        assert [p for p in trbo.tuned if p.get('tuner') == 1]

    def test_hold_pins_one_talkgroup(self, trbo: Any) -> None:
        rcvr = self._receiver(trbo)
        trbo.ui_command('hold', 100, 0)
        rcvr.process_grant(_grant_buf(1, 200, lcn=1, slot=0))
        assert not [p for p in trbo.tuned if p.get('tuner') == 1]
        rcvr.process_grant(_grant_buf(1, 100, lcn=2, slot=0))
        assert [p for p in trbo.tuned if p.get('tuner') == 1]

    def test_hold_zero_releases(self, trbo: Any) -> None:
        trbo.ui_command('hold', 100, 0)
        assert trbo.hold_tgid == 100
        trbo.ui_command('hold', 0, 0)
        assert trbo.hold_tgid is None

    def test_hold_is_reported_in_channel_status(self, trbo: Any) -> None:
        trbo.add_receiver(0, {})
        trbo.ui_command('hold', 777, 0)
        status = json.loads(trbo.get_chan_status())
        assert status['0']['hold_tgid'] == 777

    def test_skip_expires(self, trbo: Any) -> None:
        tk_trbo = pytest.importorskip("tk_trbo", reason="needs GNU Radio")
        rcvr = self._receiver(trbo)
        rcvr.process_grant(_grant_buf(1, 300, lcn=1, slot=0))
        trbo.ui_command('skip', 300, 0)
        assert not trbo.should_follow(300)
        # Rewind the skip deadline rather than sleeping.
        trbo.skiplist[300] = 0
        assert trbo.should_follow(300)

    def test_reload_clears_runtime_lockouts(self, trbo: Any) -> None:
        trbo.ui_command('lockout', 999, 0)
        assert not trbo.should_follow(999)
        trbo.ui_command('reload', 0, 0)
        assert trbo.should_follow(999)

    def test_unknown_command_is_harmless(self, trbo: Any) -> None:
        trbo.ui_command('no_such_command', 1, 0)   # must not raise

    def test_dump_tgids_does_not_raise(self, trbo: Any) -> None:
        # multi_rx calls this unconditionally; it used to be missing entirely.
        trbo.add_receiver(0, {})
        trbo.receivers[0].process_grant(_grant_buf(1, 100, lcn=1, slot=0))
        trbo.dump_tgids()


class TestTrboScanLists:
    """Batch scan-list replacement (set_whitelist / set_blacklist).

    Deliberately not N single 'whitelist' commands: each of those expires the
    current call when the tgid it is on falls outside the new list, so applying a
    50-entry list one entry at a time tears the receiver down repeatedly on the
    way to the same end state.
    """

    def _receiver(self, trbo: Any) -> Any:
        trbo.add_receiver(0, {})
        return trbo.receivers[0]

    def test_whitelist_replaces_rather_than_adds(self, trbo: Any) -> None:
        trbo.ui_command('whitelist', 100, 0)
        trbo.ui_command('set_whitelist', {'tgids': [200, 300]}, 0)
        assert trbo.get_scan_lists()['whitelist'] == [200, 300]
        assert not trbo.should_follow(100)
        assert trbo.should_follow(200)

    def test_empty_whitelist_means_scan_everything(self, trbo: Any) -> None:
        # An empty *dict* would mean "scan nothing" -- find_voice_candidate reads
        # `whitelist is not None and tgid not in whitelist`.
        trbo.ui_command('set_whitelist', {'tgids': [100]}, 0)
        assert not trbo.should_follow(999)
        trbo.ui_command('set_whitelist', {'tgids': []}, 0)
        assert trbo.get_scan_lists()['whitelist'] is None
        assert trbo.should_follow(999)

    def test_blacklist_replaces_rather_than_adds(self, trbo: Any) -> None:
        trbo.ui_command('lockout', 100, 0)
        trbo.ui_command('set_blacklist', {'tgids': [200]}, 0)
        assert trbo.get_scan_lists()['blacklist'] == [200]
        assert trbo.should_follow(100)
        assert not trbo.should_follow(200)

    def test_whitelisting_clears_a_conflicting_lockout(self, trbo: Any) -> None:
        trbo.ui_command('lockout', 100, 0)
        trbo.ui_command('set_whitelist', {'tgids': [100]}, 0)
        assert trbo.get_scan_lists()['blacklist'] == []
        assert trbo.should_follow(100)

    def test_blacklisting_removes_from_the_whitelist(self, trbo: Any) -> None:
        trbo.ui_command('set_whitelist', {'tgids': [100, 200]}, 0)
        trbo.ui_command('set_blacklist', {'tgids': [100]}, 0)
        assert trbo.get_scan_lists()['whitelist'] == [200]
        assert not trbo.should_follow(100)

    def test_a_timed_skip_survives_a_blacklist_replacement(self, trbo: Any) -> None:
        """Timed entries are skips in flight, not user intent."""
        rcvr = self._receiver(trbo)
        rcvr.process_grant(_grant_buf(1, 300, lcn=1, slot=0))
        trbo.ui_command('skip', 300, 0)
        assert not trbo.should_follow(300)
        trbo.ui_command('set_blacklist', {'tgids': [999]}, 0)
        assert not trbo.should_follow(300)      # still skipped
        assert trbo.get_scan_lists()['blacklist'] == [999]   # but not shown as a lockout

    def test_a_newly_excluded_active_call_is_released(self, trbo: Any) -> None:
        rcvr = self._receiver(trbo)
        rcvr.process_grant(_grant_buf(1, 400, lcn=1, slot=0))
        assert 400 in rcvr.active_tgids
        trbo.ui_command('set_whitelist', {'tgids': [999]}, 0)
        assert 400 not in rcvr.active_tgids

    def test_a_still_included_active_call_is_left_alone(self, trbo: Any) -> None:
        rcvr = self._receiver(trbo)
        rcvr.process_grant(_grant_buf(1, 400, lcn=1, slot=0))
        trbo.ui_command('set_whitelist', {'tgids': [400, 999]}, 0)
        assert 400 in rcvr.active_tgids

    def test_out_of_range_tgid_is_rejected_wholesale(self, trbo: Any) -> None:
        # All-or-nothing: a partially applied scan list is worse than none.
        trbo.ui_command('set_whitelist', {'tgids': [100]}, 0)
        with pytest.raises(ValueError):
            trbo.ui_command('set_whitelist', {'tgids': [200, 70000]}, 0)
        assert trbo.get_scan_lists()['whitelist'] == [100]

    def test_non_list_payload_is_rejected(self, trbo: Any) -> None:
        with pytest.raises(TypeError):
            trbo.ui_command('set_whitelist', {'tgids': 100}, 0)


class TestTrboChannelStatus:
    def test_status_reports_tuned_frequency(self, trbo: Any) -> None:
        trbo.add_receiver(0, {})
        status = json.loads(trbo.get_chan_status())
        assert status['json_type'] == 'channel_update'
        assert status['channels'] == ['0']
        assert status['0']['freq'] == 461300000     # was hard-coded 0
        assert status['0']['system'] == 'Connect+'

    def test_scan_lists_are_reported(self, trbo: Any) -> None:
        """Without this the UI could set a scan list but never read one back --
        and a whitelist loaded from a file was invisible entirely."""
        trbo.add_receiver(0, {})
        trbo.ui_command('set_whitelist', {'tgids': [100, 200]}, 0)
        trbo.ui_command('set_blacklist', {'tgids': [300]}, 0)
        status = json.loads(trbo.get_chan_status())['0']
        assert status['whitelist'] == [100, 200]
        assert status['blacklist'] == [300]

    def test_no_whitelist_is_reported_as_null_not_empty(self, trbo: Any) -> None:
        # None means "scan everything"; [] would mean "scan nothing".
        trbo.add_receiver(0, {})
        status = json.loads(trbo.get_chan_status())['0']
        assert status['whitelist'] is None
        assert status['blacklist'] == []


# ---------------------------------------------------------------------------
# P25 scan lists  (tk_p25)
# ---------------------------------------------------------------------------


@pytest.fixture()
def p25_pair() -> Any:
    """An rx_ctl with two receivers on one system.

    Built with __new__ because the real constructors need a flowgraph.  Starting
    state matches load_bl_wl() with no lists configured: whitelist None ("scan
    everything") and an empty blacklist.
    """
    tk_p25 = pytest.importorskip("tk_p25", reason="needs GNU Radio")

    shared_bl: dict[int, Any] = {}

    def receiver(msgq_id: int) -> Any:
        rx = tk_p25.p25_receiver.__new__(tk_p25.p25_receiver)
        rx.debug = 0
        rx.msgq_id = msgq_id
        rx.whitelist = None
        rx.blacklist = shared_bl          # shared, as load_bl_wl leaves it
        rx.skiplist = {}
        rx.current_tgid = None
        rx.hold_mode = False
        rx.hold_tgid = None
        rx.hold_until = 0.0
        rx.expired: list[str] = []        # type: ignore[attr-defined]
        rx.expire_talkgroup = lambda **kw: rx.expired.append(kw.get('reason', ''))
        return rx

    ctl = tk_p25.rx_ctl.__new__(tk_p25.rx_ctl)
    ctl.debug = 0
    rx0, rx1 = receiver(0), receiver(1)
    ctl.receivers = {0: {'msgq_id': 0, 'sysname': 'sys', 'rx_rcvr': rx0},
                     1: {'msgq_id': 1, 'sysname': 'sys', 'rx_rcvr': rx1}}
    ctl.systems = {'sys': {'system': None, 'receivers': [rx0, rx1]}}
    ctl.check_cc_assignments = lambda: None
    ctl.pair = (rx0, rx1)                 # type: ignore[attr-defined]
    return ctl


class TestP25ScanLists:
    def test_applies_to_every_receiver_of_the_system(self, p25_pair: Any) -> None:
        """Receivers on one system all scan the same traffic, so a scan list that
        only some of them honour is not a scan list."""
        p25_pair.ui_command('set_whitelist', {'tgids': [100, 200]}, 0)
        for rx in p25_pair.pair:
            assert rx.get_scan_lists()['whitelist'] == [100, 200]

    def test_each_receiver_gets_its_own_dict(self, p25_pair: Any) -> None:
        """The aliasing guard.

        With a whitelist file configured, load_bl_wl() hands every receiver of a
        system the *same* dict object, while add_whitelist() silently un-shares it
        by assigning a fresh {} -- so whether one receiver's change is seen by the
        others depended on which call happened to run first.  set_scan_list gives
        each receiver its own copy, making that irrelevant rather than
        load-bearing.
        """
        rx0, rx1 = p25_pair.pair
        shared = {50: None}
        rx0.whitelist = rx1.whitelist = shared       # as a whitelist file leaves it
        assert rx0.whitelist is rx1.whitelist

        p25_pair.ui_command('set_whitelist', {'tgids': [100]}, 0)
        assert rx0.whitelist is not rx1.whitelist    # not shared any more
        rx0.add_whitelist(999)
        assert rx1.get_scan_lists()['whitelist'] == [100]
        assert shared == {50: None}                  # the original is untouched

    def test_blacklist_replacement_does_not_leak_between_receivers(self, p25_pair: Any) -> None:
        rx0, rx1 = p25_pair.pair
        assert rx0.blacklist is rx1.blacklist        # shared by load_bl_wl
        p25_pair.ui_command('set_blacklist', {'tgids': [100]}, 0)
        assert rx0.blacklist is not rx1.blacklist
        rx0.add_blacklist(999)
        assert rx1.get_scan_lists()['blacklist'] == [100]

    def test_an_unknown_msgq_id_applies_to_all_systems(self, p25_pair: Any) -> None:
        p25_pair.ui_command('set_whitelist', {'tgids': [42]}, -1)
        for rx in p25_pair.pair:
            assert rx.get_scan_lists()['whitelist'] == [42]

    def test_empty_whitelist_becomes_none(self, p25_pair: Any) -> None:
        p25_pair.ui_command('set_whitelist', {'tgids': [100]}, 0)
        p25_pair.ui_command('set_whitelist', {'tgids': []}, 0)
        for rx in p25_pair.pair:
            assert rx.whitelist is None
            assert rx.get_scan_lists()['whitelist'] is None

    def test_a_newly_excluded_current_call_is_expired(self, p25_pair: Any) -> None:
        rx0, rx1 = p25_pair.pair
        rx0.current_tgid = 500
        p25_pair.ui_command('set_whitelist', {'tgids': [100]}, 0)
        assert rx0.expired == ['not whitelisted']
        assert rx1.expired == []              # rx1 had no call up

    def test_a_still_included_current_call_is_left_alone(self, p25_pair: Any) -> None:
        rx0, _ = p25_pair.pair
        rx0.current_tgid = 100
        p25_pair.ui_command('set_whitelist', {'tgids': [100, 200]}, 0)
        assert rx0.expired == []

    def test_timed_blacklist_entries_survive_a_replacement(self, p25_pair: Any) -> None:
        rx0, _ = p25_pair.pair
        rx0.blacklist = {777: 1e12}          # a TGID_SKIP_TIME skip in flight
        p25_pair.ui_command('set_blacklist', {'tgids': [888]}, 0)
        assert 777 in rx0.blacklist
        assert rx0.get_scan_lists()['blacklist'] == [888]   # timed one is not a lockout

    def test_out_of_range_tgid_is_rejected_before_anything_is_applied(self, p25_pair: Any) -> None:
        with pytest.raises(ValueError):
            p25_pair.ui_command('set_whitelist', {'tgids': [100, 0]}, 0)
        for rx in p25_pair.pair:
            assert rx.get_scan_lists()['whitelist'] is None


# ---------------------------------------------------------------------------
# SmartNet  (tk_smartnet)
# ---------------------------------------------------------------------------


@pytest.fixture()
def smartnet_system() -> Any:
    """A tk_smartnet control-channel object with no flowgraph attached."""
    tk_smartnet = pytest.importorskip("tk_smartnet", reason="needs GNU Radio")
    sys_obj = tk_smartnet.osw_receiver.__new__(tk_smartnet.osw_receiver)

    # Only the state to_json() reads — building the real object needs GNURadio.
    sys_obj.debug = 0
    sys_obj.msgq_id = 0
    sys_obj.sysname = 'smartzone'
    sys_obj.config = {'sysname': 'smartzone'}
    sys_obj.rx_sys_id = 0x1234
    sys_obj.rx_site_id = 7
    sys_obj.rx_cc_freq = 855_000_000
    sys_obj.cc_list = [855_000_000]
    sys_obj.cc_index = 0
    sys_obj.last_osw = 0
    sys_obj.stats = {'osw_count': 42}
    sys_obj.alternate_cc_freqs = {}
    sys_obj.voice_frequencies = {}
    sys_obj.patches = {}
    sys_obj.adjacent_sites = {}
    sys_obj.talkgroups = {
        101: {'tgid': 101, 'tag': 'FIRE DISP', 'prio': 2, 'srcaddr': 0,
              'time': 0, 'release_time': 0, 'mode': -1, 'receiver': None,
              'status': 0, 'counter': 0, 'configured': True},
        202: {'tgid': 202, 'tag': '', 'prio': 3, 'srcaddr': 0,
              'time': 0, 'release_time': 0, 'mode': -1, 'receiver': None,
              'status': 0, 'counter': 0, 'configured': False},
    }
    sys_obj.talkgroups_mutex = tk_smartnet.TimeoutLock(timeout=1.0)
    sys_obj.patches_mutex = tk_smartnet.TimeoutLock(timeout=1.0)
    return sys_obj


class TestSmartnetSystemPayload:
    def test_site_identity_is_published(self, smartnet_system: Any) -> None:
        d = json.loads(smartnet_system.to_json())
        assert d['type'] == 'smartnet'
        assert d['sysid_smartnet'] == 0x1234
        assert d['siteid'] == 7
        assert d['rxchan'] == 855_000_000

    def test_talkgroup_tags_are_published(self, smartnet_system: Any) -> None:
        # Without these the talkgroup table was empty on SmartNet.
        tags = json.loads(smartnet_system.to_json())['tgid_tags']
        assert tags['101'] == {
            'tag': 'FIRE DISP', 'configured': True, 'prio': 2,
            # A talkgroup known only from tgid_tags_file has never been heard.
            'last_seen': 0, 'last_freq': None, 'count': 0,
        }
        assert tags['202']['configured'] is False

    def test_talkgroup_activity_is_published(self, smartnet_system: Any) -> None:
        """last_seen / last_freq / count are what the GUI's Last column reads.

        It used to derive that from frequency_data, which only lists a talkgroup
        while its call is up (TGID_EXPIRY_TIME), so the column could only ever
        say "Now" or nothing at all.

        The tgid here is a multiple of 16 because update_talkgroup() splits the
        low nibble off as status flags (``tgid & 0xfff0``), so 1616 is the record
        that a grant for 1616-1631 lands in.
        """
        before = json.loads(smartnet_system.to_json())['tgid_tags']
        assert '1616' not in before

        smartnet_system.update_talkgroups(time.time(), 855_012_500, 1616, 0, mode=1)
        after = json.loads(smartnet_system.to_json())['tgid_tags']['1616']
        assert after['last_seen'] > 0
        assert after['last_freq'] == 855_012_500
        assert after['count'] == 0   # counter is bumped by the call logger, not here

        # last_freq has to outlive the call: it is the *last* frequency heard,
        # not the current one.  tk_p25 clears 'frequency' on expiry and the trunk
        # logic depends on that, which is the whole reason for the second key.
        smartnet_system.talkgroups[1616]['frequency'] = None
        held = json.loads(smartnet_system.to_json())['tgid_tags']['1616']
        assert held['last_freq'] == 855_012_500

    def test_smartnet_publishes_no_encrypted_flag(self, smartnet_system: Any) -> None:
        """talkgroups[tgid]['mode'] is analog-vs-digital, not clear-vs-encrypted.

        Publishing it as 'encrypted' would mark every digital talkgroup on the
        system as encrypted.  SmartNet carries encryption as a bit in the tgid.
        """
        smartnet_system.update_talkgroups(time.time(), 855_012_500, 1616, 0, mode=1)
        assert smartnet_system.talkgroups[1616]['mode'] == 1
        assert 'encrypted' not in json.loads(smartnet_system.to_json())['tgid_tags']['1616']

    def test_priority_is_published(self, smartnet_system: Any) -> None:
        tags = json.loads(smartnet_system.to_json())['tgid_tags']
        assert tags['101']['prio'] == 2

    def test_single_site_smartnet_has_no_site_id(self, smartnet_system: Any) -> None:
        smartnet_system.rx_site_id = None
        d = json.loads(smartnet_system.to_json())
        assert d['siteid'] is None
        assert 'SmartNet' in d['top_line']

    def test_p25_only_fields_stay_absent(self, smartnet_system: Any) -> None:
        d = json.loads(smartnet_system.to_json())
        for key in ('wacn', 'band_plan', 'wuid_data', 'rfid', 'stid'):
            assert key not in d, key
