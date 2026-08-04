# MotoTRBO trunking module
#
# Copyright 2019 Graham J. Norbury - gnorbury@bondcar.com
# 
# This file is part of OP25
# 
# OP25 is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.
# 
# OP25 is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public
# License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with OP25; see the file COPYING. If not, write to the Free
# Software Foundation, Inc., 51 Franklin Street, Boston, MA
# 02110-1301, USA.
#

import sys
import ctypes
import time
import json
import traceback
from helper_funcs import *
from log_ts import log_ts

CC_HUNT_TIMEOUTS  = 3   # number of sync timeouts to wait until control channel hunt
VC_SRCH_TIME      = 3.0 # seconds to wait from VC tuning until hunt
TGID_HOLD_TIME    = 2.0 # seconds to wait until releasing tgid after last GRANT message
TGID_SKIP_TIME    = 4.0 # seconds to ignore a tgid after 'skip'
TGID_DEFAULT_PRIO = 3   # default tgid priority when unassigned
CALL_LOG_MAX      = 200 # bound the call log; the UI drains it once a second


class _grant_info(object):
    """State of one time slot on one logical channel.

    One instance per slot: the two slots of a DMR channel carry independent
    conversations, so they must not share storage.  (This used to append the
    *class object* twice, which made both slots aliases of one set of class
    attributes — every slot-B grant overwrote slot A's.)
    """
    def __init__(self):
        self.grant_time = 0
        self.grp_addr = None
        self.src_addr = None


class dmr_chan:
    def __init__(self, debug=0, lcn=0, freq=0):
        self.debug = debug
        self.lcn = lcn
        self.frequency = freq
        self.slot = [_grant_info(), _grant_info()]

    def set_debug(self, dbglvl):
        self.debug = dbglvl

class dmr_receiver:
    def __init__(self, msgq_id, frequency_set=None, fa_ctrl=None, chans={}, debug=0, rx_ctl=None):
        class _states(object):
            IDLE = 0
            CC   = 1
            VC   = 2
            SRCH = 3
            REST = 4
        self.current_type = -1
        self.states = _states
        self.current_state = self.states.IDLE
        self.frequency_set = frequency_set
        self.fa_ctrl = fa_ctrl
        self.msgq_id = msgq_id
        self.debug = debug
        self.cc_timeouts = 0
        self.chans = chans
        self.chan_list = list(self.chans.keys())
        self.current_chan = 0
        self.rest_lcn = 0
        self.active_tgids = {}
        self.tune_time = 0
        self.rx_ctl = rx_ctl        # shared system state: tgids, lists, call log
        self.current_slot = None    # slot this receiver is following, when known

    def set_debug(self, dbglvl):
        self.debug = dbglvl

    def post_init(self):
        if self.debug >= 1:
            sys.stderr.write("%s [%d] Initializing DMR receiver\n" % (log_ts.get(), self.msgq_id))
        if self.msgq_id == 0:
            self.tune_next_chan(msgq_id=0, chan=0, slot=0)
        else:
            self.tune_next_chan(msgq_id=1, chan=0, slot=4)

    def to_json(self):
        """Per-receiver view.  The system-wide payload is built by rx_ctl."""
        return json.dumps(self.rx_ctl.system_json() if self.rx_ctl is not None else {})

    def process_grant(self, m_buf):
            src_addr = get_ordinals(m_buf[2:5])
            grp_addr = get_ordinals(m_buf[5:8])
            lcn      = get_ordinals(m_buf[8]) >> 4
            slot     = (get_ordinals(m_buf[8]) >> 3) & 0x1
            chan, freq = self.find_freq(lcn)
            if freq is not None:
                lcn_sl = (lcn << 1) + slot
                if self.debug >= 9:
                    sys.stderr.write("%s [%d] CONNECT PLUS CHANNEL GRANT: srcAddr(%06x), grpAddr(%06x), lcn(%d), slot(%d), freq(%f)\n" % (log_ts.get(), self.msgq_id, src_addr, grp_addr, lcn, slot, (freq/1e6)))

                # Record what the control channel said even when we choose not
                # to follow it, so the talkgroup list and per-slot state stay
                # complete regardless of hold/lockout.
                if self.rx_ctl is not None:
                    self.rx_ctl.note_grant(grp_addr, src_addr, lcn, slot, freq, self.msgq_id)

                # Blacklist / whitelist / skip / hold all decide the same thing:
                # whether this grant is worth retuning the voice receiver for.
                follow = (self.rx_ctl is None) or self.rx_ctl.should_follow(grp_addr)
                if not follow:
                    if self.debug >= 5:
                        sys.stderr.write("%s [%d] Ignoring grant for tg(%d): filtered by hold/lockout/whitelist/skip\n" % (log_ts.get(), self.msgq_id, grp_addr))
                elif (grp_addr not in self.active_tgids) or ((grp_addr in self.active_tgids) and (lcn_sl != self.active_tgids[grp_addr])):
                    if self.debug >= 1:
                        sys.stderr.write("%s [%d] Voice update:  tg(%d), freq(%f), slot(%d), lcn(%d)\n" % (log_ts.get(), self.msgq_id, grp_addr, (freq/1e6), slot, lcn))
                    self.frequency_set({'tuner': 1,
                                        'freq': freq,
                                        'slot': (slot + 1),
                                        'chan': chan,
                                        'state': self.states.SRCH,
                                        'type': self.current_type,
                                        'time': time.time()})
                    self.active_tgids[grp_addr] = lcn_sl
                self.chans[lcn].slot[slot].grant_time = time.time()
                self.chans[lcn].slot[slot].grp_addr = grp_addr
                self.chans[lcn].slot[slot].src_addr = src_addr
            elif self.debug >=9:
                sys.stderr.write("%s [%d] CONNECT PLUS CHANNEL GRANT: srcAddr(%06x), grpAddr(%06x), unknown lcn(%d), slot(%d)\n" % (log_ts.get(), self.msgq_id, src_addr, grp_addr, lcn, slot))

    def find_freq(self, lcn):
        if lcn in self.chans:
            return (self.chan_list.index(lcn), self.chans[lcn].frequency)
        else:
            return (None, None)

    def find_next_chan(self):
        next_chan = (self.current_chan + 1) % len(self.chan_list)
        return next_chan

    def tune_next_chan(self, msgq_id=None, chan=None, slot=None):
        if chan is not None:
            next_ch = chan
        else:
            next_ch = self.find_next_chan()
        
        tune_params = {'tuner': self.msgq_id,
                       'freq': self.chans[self.chan_list[next_ch]].frequency,
                       'chan': next_ch,
                       'time': time.time()}

        if msgq_id is not None:
            tune_params['tuner'] = msgq_id

        if slot is not None:
            tune_params['slot'] = slot
            # 4 means "no slot" (set_slotid off); anything else is 1-based here.
            self.current_slot = None if slot >= 4 else max(0, slot - 1)

        self.current_chan = next_ch
        self.frequency_set(tune_params)

        if (self.msgq_id == 0) and (self.debug >= 1):
            sys.stderr.write("%s [%d] Searching for control channel: lcn(%d), freq(%f)\n" % (log_ts.get(), self.msgq_id, self.chan_list[self.current_chan], (self.chans[self.chan_list[self.current_chan]].frequency/1e6)))

    def ui_command(self, cmd, data, curr_time):
        """Per-receiver UI command.

        All the state these act on is shared across the control and voice
        receivers (one Connect+ system, two tuners), so it lives on rx_ctl and
        this just forwards.
        """
        if self.rx_ctl is not None:
            self.rx_ctl.apply_ui_command(cmd, data, curr_time)

    def process_qmsg(self, msg):
        m_type = ctypes.c_int16(msg.type() & 0xffff).value  # lower 16 bits of msg.type() is signed message type
        m_slot = int(msg.arg1()) & 0x1                      # message slot id
        m_ts   = float(msg.arg2())                          # message sender timestamp
        m_buf = msg.to_string()                             # message data

        if m_type == -1:    # Sync Timeout
            if self.debug >= 9:
                sys.stderr.write("%s [%d] Timeout waiting for sync sequence\n" % (log_ts.get(), self.msgq_id))

            if self.msgq_id == 0: # primary/control channel
                self.cc_timeouts += 1
                if self.cc_timeouts >= CC_HUNT_TIMEOUTS:
                    self.cc_timeouts = 0
                    self.current_state = self.states.IDLE
                    self.tune_next_chan()
                    return
            else:                 # secondary/voice channel
                pass

        elif m_type >= 0:   # Receiving a PDU means sync must be present
            if self.msgq_id == 0:
                self.cc_timeouts = 0

        # If voice channel not identified, begin LCN search
        if (self.msgq_id > 0) and (self.current_state == self.states.SRCH) and (self.tune_time + VC_SRCH_TIME < time.time()):
            self.tune_next_chan()

        # log received message
        if self.debug >= 10:
            d_buf = "0x"
            for byte in m_buf:
                d_buf += format(get_ordinals(byte),"02x")
            sys.stderr.write("%s [%d] DMR PDU: lcn(%d), state(%d), type(%d), slot(%d), data(%s)\n" % (log_ts.get(), self.msgq_id, self.chan_list[self.current_chan], self.current_state, m_type, m_slot, d_buf))

        if m_type == 0:   # CACH SLC
            self.rx_CACH_SLC(m_buf)
        elif m_type == 1: # CACH CSBK
            pass
        elif m_type == 2: # SLOT PI
            self.rx_SLOT_PI(m_slot, m_buf)
        elif m_type == 3: # SLOT VLC
            self.rx_SLOT_VLC(m_slot, m_buf)
        elif m_type == 4: # SLOT TLC
            self.rx_SLOT_TLC(m_slot, m_buf)
        elif m_type == 5: # SLOT CSBK
            self.rx_SLOT_CSBK(m_slot, m_buf)
        elif m_type == 6: # SLOT MBC
            pass
        elif m_type == 7: # SLOT ELC
            self.rx_SLOT_ELC(m_slot, m_buf)
        elif m_type == 8: # SLOT ERC
            pass
        elif m_type == 9: # SLOT ESB
            pass
        else:             # Unknown Message
            return

        # If this is Capacity Plus, try to keep the first receiver tuned to a control channel
        if (self.current_type == 1) and (self.msgq_id == 0) and (self.current_state > self.states.CC):
            if self.debug >= 1:
                sys.stderr.write("%s [%d] Looking for control channel\n" % (log_ts.get(), self.msgq_id))
            self.cc_timeouts = 0
            self.current_state = self.states.IDLE
            self.tune_next_chan()

    def rx_CACH_SLC(self, m_buf):
        slco = get_ordinals(m_buf[0])
        d0   = get_ordinals(m_buf[1])
        d1   = get_ordinals(m_buf[2])
        d2   = get_ordinals(m_buf[3])

        if slco == 0:    # Null Msg (Idle Channel)
            if self.debug >= 9:
                sys.stderr.write("%s [%d] SLCO NULL MSG\n" % (log_ts.get(), self.msgq_id))
        elif slco == 1:  # Act Update
                ts1_act = d0 >> 4;
                ts2_act = d0 & 0xf;
                if self.debug >= 9:
                    sys.stderr.write("%s [%d] ACTIVITY UPDATE TS1(%x), TS2(%x), HASH1(%02x), HASH2(%02x)\n" % (log_ts.get(), self.msgq_id, ts1_act, ts2_act, d1, d2))
        elif slco == 9:  # Connect Plus Voice Channel
            netId = (d0 << 4) + (d1 >> 4)
            siteId = ((d1 & 0xf) << 4) + (d2 >> 4)
            if self.current_type < 0:
                self.current_type = 1
                if self.debug >= 2:
                    sys.stderr.write("%s [%d] System type is TRBO Connect Plus\n" % (log_ts.get(), self.msgq_id))
            # Sometimes only a voice channel exists and no control channel is present.  It's probably better to lock
            # on to a voice channel and wait for it to either dissapear or become a control channel rather than aimlessly
            # cycling the tuning looking for the non-existent control channel.
            self.current_state=self.states.VC
            if self.debug >= 9:
                sys.stderr.write("%s [%d] CONNECT PLUS VOICE CHANNEL: state(%d), netId(%d), siteId(%d)\n" % (log_ts.get(), self.msgq_id, self.current_state, netId, siteId))
        elif slco == 10: # Connect Plus Control Channel
            netId = (d0 << 4) + (d1 >> 4)
            siteId = ((d1 & 0xf) << 4) + (d2 >> 4)
            if self.current_type < 0:
                self.current_type = 1
                if self.debug >= 2:
                    sys.stderr.write("%s [%d] System type is TRBO Connect Plus\n" % (log_ts.get(), self.msgq_id))
            if self.msgq_id == 0:
                if self.current_state != self.states.CC:
                    self.current_state=self.states.CC # Found control channel
                    if self.debug >= 1:
                        sys.stderr.write("%s [%d] Found control channel: lcn(%d), freq(%f)\n" % (log_ts.get(), self.msgq_id, self.chan_list[self.current_chan], (self.chans[self.chan_list[self.current_chan]].frequency/1e6)))
            else:
                if self.current_state != self.states.VC:
                    self.current_state=self.states.VC # Control channel can also carry voice
            if self.debug >= 9:
                sys.stderr.write("%s [%d] CONNECT PLUS CONTROL CHANNEL: state(%d), netId(%d), siteId(%d)\n" % (log_ts.get(), self.msgq_id, self.current_state, netId, siteId))
        elif slco == 15: # Capacity Plus Channel
            lcn = d1
            if self.current_type < 0:
                self.current_type = 0
                self.fa_ctrl({'tuner': 0, 'cmd': 'set_slotid', 'slotid': 3})
                if self.debug >= 2:
                    sys.stderr.write("%s [%d] System type is TRBO Connect Plus\n" % (log_ts.get(), self.msgq_id))
            self.rest_lcn = d1
            if self.rx_ctl is not None:
                self.rx_ctl.rest_lcn = d1   # shared with the terminal payload
            if self.debug >= 9:
                sys.stderr.write("%s [%d] CAPACITY PLUS REST CHANNEL: lcn(%d)\n" % (log_ts.get(), self.msgq_id, lcn))
        else:
            if self.debug >= 9:
                sys.stderr.write("%s [%d] UNKNOWN CACH SLCO(%d)\n" % (log_ts.get(), self.msgq_id, slco))
            return

    def rx_SLOT_CSBK(self, m_slot, m_buf):
        op  = get_ordinals(m_buf[0]) & 0x3f
        fid = get_ordinals(m_buf[1])

        if (op == 1) and (fid == 6) and (self.msgq_id == 0):   # ConnectPlus Neighbors (control channel only)
            nb1 = get_ordinals(m_buf[2]) & 0x3f
            nb2 = get_ordinals(m_buf[3]) & 0x3f
            nb3 = get_ordinals(m_buf[4]) & 0x3f
            nb4 = get_ordinals(m_buf[5]) & 0x3f
            nb5 = get_ordinals(m_buf[6]) & 0x3f
            if self.debug >= 10:
                sys.stderr.write("%s [%d] CONNECT PLUS NEIGHBOR SITES: %d, %d, %d, %d, %d\n" % (log_ts.get(), self.msgq_id, nb1, nb2, nb3, nb4, nb5))

        elif (op == 3) and (fid == 6) and (self.msgq_id == 0): # ConnectPlus Channel Grant (control channel only)
            self.process_grant(m_buf)

        elif (op == 59) and (fid == 16): # CapacityPlus Sys/Sites/TS
            fl   =  (get_ordinals(m_buf[2]) >> 6)
            ts   = ((get_ordinals(m_buf[2]) >> 5) & 0x1)
            rest =  (get_ordinals(m_buf[2]) & 0x1f)
            bcn  = ((get_ordinals(m_buf[3]) >> 7) & 0x1)
            site = ((get_ordinals(m_buf[3]) >> 3) & 0xf)
            nn   =  (get_ordinals(m_buf[3]) & 0x7)
            if nn > 6:
                nn = 6
            if self.debug >= 9:
                sys.stderr.write("%s [%d] CAPACITY PLUS SYS/SITES: rest(%d), beacon(%d), siteId(%d), nn(%d)\n" % (log_ts.get(), self.msgq_id, rest, bcn, site, nn))

        elif (op == 62):                 # 
            pass

    def rx_SLOT_VLC(self, m_slot, m_buf):
        flco    = get_ordinals(m_buf[0]) & 0x3f
        fid     = get_ordinals(m_buf[1])
        svcopt  = get_ordinals(m_buf[2])
        dstaddr = get_ordinals(m_buf[3:6])
        srcaddr = get_ordinals(m_buf[6:9])
        if self.debug >= 9:
            sys.stderr.write("%s [%d] VOICE HDR LC: slot(%d), flco(%02x), fid(%02x), svcopt(%02x), srcAddr(%06x), grpAddr(%06x)\n" % (log_ts.get(), self.msgq_id, m_slot, flco, fid, svcopt, srcaddr, dstaddr))

        # TODO: handle flco

    def rx_SLOT_TLC(self, m_slot, m_buf):
        flco    = get_ordinals(m_buf[0]) & 0x3f
        fid     = get_ordinals(m_buf[1])
        svcopt  = get_ordinals(m_buf[2])
        dstaddr = get_ordinals(m_buf[3:6])
        srcaddr = get_ordinals(m_buf[6:9])
        if self.debug >= 9:
            sys.stderr.write("%s [%d] VOICE TERM LC: slot(%d), flco(%02x), fid(%02x), svcopt(%02x), srcAddr(%06x), grpAddr(%06x)\n" % (log_ts.get(), self.msgq_id, m_slot, flco, fid, svcopt, srcaddr, dstaddr))

        # TODO: handle flco

    def rx_SLOT_ELC(self, m_slot, m_buf):
        flco    = get_ordinals(m_buf[0]) & 0x3f
        fid     = get_ordinals(m_buf[1])
        svcopt  = get_ordinals(m_buf[2])
        dstaddr = get_ordinals(m_buf[3:6])
        srcaddr = get_ordinals(m_buf[6:9])
        if self.debug >= 9:
            sys.stderr.write("%s [%d] VOICE EMB LC: slot(%d), flco(%02x), fid(%02x), svcopt(%02x), srcAddr(%06x), grpAddr(%06x)\n" % (log_ts.get(), self.msgq_id, m_slot, flco, fid, svcopt, srcaddr, dstaddr))

        # TODO: handle flco

    def rx_SLOT_PI(self, m_slot, m_buf):
        algid   = get_ordinals(m_buf[0])
        keyid   = get_ordinals(m_buf[2])
        mi      = get_ordinals(m_buf[3:7])
        dstaddr = get_ordinals(m_buf[7:10])
        if self.debug >= 9:
            sys.stderr.write("%s [%d] PI HEADER: slot(%d), algId(%02x), keyId(%02x), mi(%08x), grpAddr(%06x)\n" % (log_ts.get(), self.msgq_id, m_slot, algid, keyid, mi, dstaddr))

    def get_status(self):
        """Per-channel status for the terminal's channel_update.

        Reports what this receiver is tuned to and, for a voice receiver, the
        call on the slot it is following.  Previously every field was hard-coded
        empty, so the GUI showed a channel with no frequency and no call.
        """
        lcn  = self.chan_list[self.current_chan] if self.chan_list else None
        freq = self.chans[lcn].frequency if lcn in self.chans else 0

        tgid = None
        srcaddr = 0
        if lcn in self.chans and self.current_slot is not None:
            slot_state = self.chans[lcn].slot[self.current_slot]
            # Only report a call that is still within its hold time.
            if slot_state.grant_time and (slot_state.grant_time + TGID_HOLD_TIME) >= time.time():
                tgid = slot_state.grp_addr
                srcaddr = slot_state.src_addr or 0

        tag = ''
        if tgid is not None and self.rx_ctl is not None:
            tag = self.rx_ctl.get_tag(tgid)

        d = {}
        d['freq'] = freq
        d['tdma'] = self.current_slot
        d['slot'] = self.current_slot
        d['lcn'] = lcn
        d['tgid'] = tgid
        d['system'] = self.rx_ctl.sysname if self.rx_ctl is not None else ""
        d['tag'] = tag
        d['srcaddr'] = srcaddr
        d['srctag'] = ""
        d['encrypted'] = 0
        d['emergency'] = 0
        d['hold_tgid'] = self.rx_ctl.hold_tgid if self.rx_ctl is not None else None
        d['mode'] = None
        d['stream'] = ""
        d['msgqid'] = self.msgq_id
        return json.dumps(d)


class rx_ctl(object):
    def __init__(self, debug=0, frequency_set=None, nbfm_ctrl=None, fa_ctrl=None, chans={}):
        self.frequency_set = frequency_set
        self.fa_ctrl = fa_ctrl
        self.debug = debug
        self.receivers = {}

        self.chans = {}
        for _chan in chans:
            if not 'lcn' in _chan:
                sys.stderr.write("%s Trunking chan[%d] has no lcn defined\n" % (log_ts.get(), chans.index(_chan)))
                continue
            self.chans[_chan['lcn']] = dmr_chan(debug, _chan['lcn'], get_frequency(from_dict(_chan, 'frequency', 0.0)))
            sys.stderr.write("%s Configuring channel lcn(%d), freq(%f), cc(%d)\n" % (log_ts.get(), _chan['lcn'], get_frequency(from_dict(_chan, 'frequency', 0.0))/1e6, int(from_dict(_chan, 'cc', 0))))
        if len(self.chans) == 0:
            sys.stderr.write("%s Trunking has no valid chans, aborting\n" % (log_ts.get()))
            exit(1)

        # ------------------------------------------------------------------
        # System-wide state shared by the control and voice receivers.
        #
        # Everything below runs on multi_rx's main thread — decoder messages,
        # UI commands and the terminal's status polls all arrive through
        # process_qmsg — so no locking is needed here.
        # ------------------------------------------------------------------
        self.talkgroups = {}   # tgid -> {tag, prio, srcaddr, time, counter, lcn, slot, configured}
        self.call_log  = []    # drained by get_call_log() once a second
        self.rest_lcn  = 0
        self.blacklist = {}
        self.whitelist = None
        self.skiplist  = {}
        self.hold_tgid = None
        self.hold_until = 0

        # tk_trbo's chans are LCN entries rather than systems, so there is no
        # per-system config block to hang these off; accept them on whichever
        # chan entry defines them (first wins) and remember the paths so
        # 'reload' can re-read the files.
        def _first(key):
            return next((str(from_dict(c, key, '')) for c in chans
                         if from_dict(c, key, '')), '')

        self.sysname        = _first('sysname') or 'Connect+'
        self.tags_file      = _first('tgid_tags_file')
        self.blacklist_file = _first('blacklist')
        self.whitelist_file = _first('whitelist')

        if self.tags_file:
            self.read_tags_file(self.tags_file)
        self.load_bl_wl()

    # ----------------------------------------------------------------------
    # Talkgroup bookkeeping
    # ----------------------------------------------------------------------

    def add_default_tgid(self, tgid):
        if tgid not in self.talkgroups:
            self.talkgroups[tgid] = {
                'tgid':       tgid,
                'tag':        '',
                'prio':       TGID_DEFAULT_PRIO,
                'srcaddr':    0,
                'time':       0,
                'counter':    0,
                'lcn':        None,
                'slot':       None,
                'configured': False,
            }

    def get_tag(self, tgid):
        return self.talkgroups.get(tgid, {}).get('tag', '')

    def read_tags_file(self, tags_file):
        """Load tgid<TAB>tag[<TAB>priority] the same way the other modules do."""
        try:
            tags = read_tsv_file(tags_file, 'tgid')
        except Exception as e:
            sys.stderr.write("%s Error reading tgid_tags_file %s: %s\n" % (log_ts.get(), tags_file, e))
            return
        for tgid in tags:
            self.add_default_tgid(tgid)
            self.talkgroups[tgid]['tag'] = tags[tgid].get('tag', '')
            try:
                self.talkgroups[tgid]['prio'] = int(tags[tgid].get('prio', TGID_DEFAULT_PRIO))
            except (TypeError, ValueError):
                self.talkgroups[tgid]['prio'] = TGID_DEFAULT_PRIO
            self.talkgroups[tgid]['configured'] = True
        sys.stderr.write("%s Read %d tgid tags from %s\n" % (log_ts.get(), len(tags), tags_file))

    def load_bl_wl(self):
        if self.blacklist_file:
            sys.stderr.write("%s reading blacklist file: %s\n" % (log_ts.get(), self.blacklist_file))
            self.blacklist = get_int_dict(self.blacklist_file)
        if self.whitelist_file:
            sys.stderr.write("%s reading whitelist file: %s\n" % (log_ts.get(), self.whitelist_file))
            self.whitelist = get_int_dict(self.whitelist_file)

    def note_grant(self, tgid, srcaddr, lcn, slot, freq, msgq_id):
        """Record a channel grant seen on the control channel."""
        self.add_default_tgid(tgid)
        tg = self.talkgroups[tgid]
        tg['srcaddr'] = srcaddr
        tg['lcn']     = lcn
        tg['slot']    = slot
        tg['time']    = time.time()
        tg['counter'] += 1
        self.log_call(msgq_id, freq, slot, tg['prio'], tgid, tg['tag'], srcaddr)

    def log_call(self, rcvr, freq, slot, prio, tgid, tgtag, rid):
        """Append to the draining call log the terminal polls each second."""
        self.call_log.append({
            'time':    time.time(),
            'sysid':   0,
            'rcvr':    rcvr,
            'rcvrtag': '',
            'freq':    freq,
            'slot':    slot,
            'prio':    prio,
            'tgid':    tgid,
            'tgtag':   tgtag,
            'rid':     rid,
            'rtag':    '',
        })
        if len(self.call_log) > CALL_LOG_MAX:
            del self.call_log[:len(self.call_log) - CALL_LOG_MAX]

    # ----------------------------------------------------------------------
    # Call filtering
    # ----------------------------------------------------------------------

    def should_follow(self, tgid):
        """Whether a grant for *tgid* should retune the voice receiver."""
        curr_time = time.time()

        # An expired hold releases itself.
        if self.hold_tgid is not None and self.hold_until and curr_time > self.hold_until:
            self.hold_tgid = None

        if self.hold_tgid is not None:
            return tgid == self.hold_tgid

        for skipped, until in list(self.skiplist.items()):
            if until is not None and curr_time > until:
                del self.skiplist[skipped]
        if tgid in self.skiplist:
            return False

        if tgid in self.blacklist:
            return False
        if self.whitelist is not None and tgid not in self.whitelist:
            return False
        return True

    def add_blacklist(self, tgid, end_time=None):
        if not tgid or tgid <= 0:
            if self.debug >= 1:
                sys.stderr.write("%s blacklist tgid(%s) out of range\n" % (log_ts.get(), tgid))
            return
        if tgid in self.blacklist:
            return
        self.blacklist[tgid] = end_time
        if self.debug >= 1:
            sys.stderr.write("%s blacklisting tgid(%d)\n" % (log_ts.get(), tgid))
        self.release_tgid(tgid)

    def add_whitelist(self, tgid):
        if not tgid or tgid <= 0:
            return
        if self.whitelist is None:
            self.whitelist = {}
        if tgid in self.whitelist:
            return
        self.whitelist[tgid] = None
        if self.debug >= 1:
            sys.stderr.write("%s whitelisting tgid(%d)\n" % (log_ts.get(), tgid))

    def add_skiplist(self, tgid, end_time=None):
        if not tgid or tgid <= 0:
            return
        self.skiplist[tgid] = end_time
        if self.debug >= 1:
            sys.stderr.write("%s skiplisting tgid(%d)\n" % (log_ts.get(), tgid))
        self.release_tgid(tgid)

    def release_tgid(self, tgid):
        """Stop following *tgid* right now, on whichever receiver has it."""
        for rcvr in self.receivers.values():
            rcvr.active_tgids.pop(tgid, None)

    def current_tgid(self):
        """Newest talkgroup still inside its hold time, or None."""
        newest, newest_time = None, 0
        for tgid, tg in self.talkgroups.items():
            if tg['time'] > newest_time:
                newest, newest_time = tgid, tg['time']
        if newest is not None and (newest_time + TGID_HOLD_TIME) >= time.time():
            return newest
        return None

    def ui_command(self, cmd, data, msgq_id):
        """Entry point used by multi_rx (cmd, arg1, arg2) — arg2 is a msgq_id.

        Connect+ state is system-wide rather than per-receiver, so unlike
        tk_p25/tk_smartnet there is nothing to dispatch: apply it directly.
        """
        self.apply_ui_command(cmd, data, time.time())

    def apply_ui_command(self, cmd, data, curr_time):
        """hold / skip / lockout / whitelist / reload from the terminal.

        This used to be `pass  # TODO`, so every one of these was silently
        dropped on Connect+ systems in both the curses and web UIs.
        """
        data = int(data) if data else 0
        if self.debug >= 10:
            sys.stderr.write("%s ui_command: cmd(%s), data(%d)\n" % (log_ts.get(), cmd, data))

        if cmd == 'hold':
            if data == 0:                       # 0 releases the hold
                if self.hold_tgid is not None and self.debug >= 1:
                    sys.stderr.write("%s releasing hold on tgid(%d)\n" % (log_ts.get(), self.hold_tgid))
                self.hold_tgid = None
                self.hold_until = 0
            else:
                self.hold_tgid = data
                self.hold_until = curr_time + TGID_HOLD_TIME
                self.add_default_tgid(data)
                if self.debug >= 1:
                    sys.stderr.write("%s holding tgid(%d)\n" % (log_ts.get(), data))
        elif cmd == 'whitelist':
            self.add_whitelist(data)
        elif cmd == 'skip':
            tgid = data if data else self.current_tgid()
            if tgid:
                self.add_skiplist(tgid, curr_time + TGID_SKIP_TIME)
        elif cmd == 'lockout':
            tgid = data if data else self.current_tgid()
            if tgid:
                self.add_blacklist(tgid)
        elif cmd == 'reload':
            self.blacklist = {}
            self.whitelist = None
            self.load_bl_wl()

    # ----------------------------------------------------------------------
    # Terminal payloads
    # ----------------------------------------------------------------------

    def system_json(self):
        """The trunk_update payload for this Connect+ system.

        NAC/WACN/RFSS, band plans and adjacent sites are P25 concepts with no
        Connect+ equivalent and are deliberately absent — the GUI hides what a
        system type does not have rather than showing zeros.
        """
        t = time.time()
        d = {}
        d['type']           = 'trbo'
        d['system']         = self.sysname
        d['top_line']       = 'Connect+   %d LCN   rest %s' % (
                                  len(self.chans),
                                  self.rest_lcn if self.rest_lcn else '--')
        d['secondary']      = []
        d['rest_lcn']       = self.rest_lcn
        d['frequencies']    = {}
        d['frequency_data'] = {}
        d['patch_data']     = {}
        d['adjacent_data']  = {}
        d['lcn_data']       = {}
        d['last_tsbk']      = max((tg['time'] for tg in self.talkgroups.values()), default=0)

        for lcn in sorted(self.chans):
            chan = self.chans[lcn]
            slots = []
            tgids = []
            tags  = []
            srcaddrs = []
            newest = 0
            for slot_id, slot in enumerate(chan.slot):
                active = bool(slot.grant_time) and (slot.grant_time + TGID_HOLD_TIME) >= t
                slots.append({
                    'slot':       slot_id,
                    'tgid':       slot.grp_addr if active else 0,
                    'srcaddr':    slot.src_addr if active else 0,
                    'grant_time': int(slot.grant_time or 0),
                })
                if active and slot.grp_addr:
                    tgids.append(str(slot.grp_addr))
                    tags.append(self.get_tag(slot.grp_addr))
                    srcaddrs.append(slot.src_addr or 0)
                newest = max(newest, slot.grant_time or 0)

            d['lcn_data'][str(lcn)] = {
                'lcn':       lcn,
                'frequency': chan.frequency,
                'slots':     slots,
            }

            if newest == 0:
                last_activity = 'Never'
            elif (t - newest) < TGID_HOLD_TIME:
                last_activity = '  Now'
            else:
                last_activity = '%4.1fs' % (t - newest)

            chan_type = 'control' if lcn == self.rest_lcn else 'voice'
            d['frequency_data'][chan.frequency] = {
                'type':          chan_type,
                'tgids':         tgids,
                'last_activity': last_activity,
                'counter':       sum(1 for s in slots if s['tgid']),
                'tags':          tags,
                'srcaddrs':      srcaddrs,
                'srctags':       ['' for _ in srcaddrs],
            }
            d['frequencies'][chan.frequency] = '- %f  lcn %d  %s' % (
                chan.frequency / 1e6, lcn, last_activity)

        tgid_tags = {}
        for tgid, tg in self.talkgroups.items():
            tgid_tags[str(tgid)] = {
                'tag':        tg['tag'],
                'configured': tg['configured'],
                'prio':       tg['prio'],
            }
        d['tgid_tags'] = tgid_tags
        return d

    def set_debug(self, dbglvl):
        self.debug = dbglvl
        for chan in self.chans:
            self.chans[chan].set_debug(dbglvl)
        for rcvr in self.receivers:
            self.receivers[rcvr].set_debug(dbglvl)

    def post_init(self):
        for rx_id in self.receivers:
            self.receivers[rx_id].post_init()

    def add_receiver(self, msgq_id, config, meta_q = None, freq = 0):
        self.receivers[msgq_id] = dmr_receiver(msgq_id, self.frequency_set, self.fa_ctrl,
                                              self.chans, self.debug, rx_ctl = self)

    def process_qmsg(self, msg):
        m_proto = ctypes.c_int16(msg.type() >> 16).value    # upper 16 bits of msg.type() is signed protocol
        m_type = ctypes.c_int16(msg.type() & 0xffff).value  # lower 16 bits of msg.type() is signed message type
        if (m_proto != 1) and (m_type != -1): # DMR m_proto=1 except for timeout when m_proto=0
            return

        self.check_expired_grants()

        m_rxid = int(msg.arg1()) >> 1
        if m_rxid in self.receivers:
            self.receivers[m_rxid].process_qmsg(msg)

    def check_expired_grants(self):
        cur_time = time.time()
        for tgid in list(self.receivers[0].active_tgids):
            act_lcn = self.receivers[0].active_tgids[tgid] >> 1
            act_slot = self.receivers[0].active_tgids[tgid] & 1

            if (self.chans[act_lcn].slot[act_slot].grant_time + TGID_HOLD_TIME) < cur_time:
                self.receivers[0].active_tgids.pop(tgid, None)
                if self.receivers[0].current_type > 0: # turn off voice channel receiver for Connect Plus systems
                    if self.debug >=2:
                        sys.stderr.write("%s Shutting off voice channel lcn(%d), slot(%d)\n" % (log_ts.get(), act_lcn, act_slot))
                    self.receivers[1].vc_timeouts = 0
                    self.receivers[1].current_state = self.receivers[1].states.IDLE
                    self.fa_ctrl({'tuner': 1, 'cmd': 'set_slotid', 'slotid': 4})

    def get_chan_status(self):
        d = {'json_type': 'channel_update'}
        rcvr_ids = []
        for rcvr in self.receivers:
            if self.receivers[rcvr] is not None:
                rcvr_name = ("chan[%d]" % self.receivers[rcvr].msgq_id)
                d[str(rcvr)] = json.loads(self.receivers[rcvr].get_status())
                d[str(rcvr)]['name'] = rcvr_name
                rcvr_ids.append(str(rcvr))
        d['channels'] = rcvr_ids
        return json.dumps(d)

    def dump_tgids(self):
        """Log every known talkgroup, as the other trunking modules do.

        multi_rx calls this unconditionally for the 'dump_tgids' command, so
        its absence here was an AttributeError waiting for the first Connect+
        user to press the button.
        """
        sys.stderr.write("Known tgids for %s:\n" % self.sysname)
        for tgid in sorted(self.talkgroups):
            tg = self.talkgroups[tgid]
            sys.stderr.write('%d\t"%s"\t%d\t#%d\n' % (tgid, tg['tag'], tg['prio'], tg['counter']))
        if self.blacklist:
            sys.stderr.write("blacklist: %s\n" % sorted(self.blacklist))
        if self.whitelist is not None:
            sys.stderr.write("whitelist: %s\n" % sorted(self.whitelist))
        if self.hold_tgid:
            sys.stderr.write("hold: %d\n" % self.hold_tgid)

    def get_call_log(self):
        """Drain the call log, matching tk_p25/tk_smartnet's delta-feed contract.

        This used to be a stub returning an empty list, so Call History was
        permanently blank on Connect+ systems.
        """
        d = {'json_type': 'call_log', 'log': self.call_log}
        self.call_log = []
        return json.dumps(d)

    def to_json(self):
        # One Connect+ system, however many receivers are tuned to it — unlike
        # tk_p25/tk_smartnet, where each entry is a separate configured system.
        d = {'json_type': 'trunk_update'}
        d[0] = self.system_json()
        d['nac'] = 0
        return json.dumps(d)

