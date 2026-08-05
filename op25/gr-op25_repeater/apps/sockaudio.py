# Copyright 2017, 2018 Graham Norbury
# 
# Copyright 2011, 2012, 2013, 2014, 2015, 2016, 2017 Max H. Parke KA1RBI
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

from ctypes import *
import os
import sys
import time
import threading
import select
import socket
import errno
import struct
import ctypes
import numpy as np
from log_ts import log_ts

# Optional cross-platform PortAudio backend (python-sounddevice).  ALSA and
# PulseAudio are Linux-only shared libraries, so this is what gives macOS
# (CoreAudio) local speaker output.  A missing portaudio library must degrade
# to "backend unavailable" rather than breaking the whole audio module, so the
# import error is captured instead of raised.
try:
    import sounddevice as _sounddevice
except Exception as e:
    _sounddevice = None
    _sounddevice_error = e
else:
    _sounddevice_error = None

# OP25 defaults
PCM_RATE = 8000             # audio sample rate (Hz)
PCM_BUFFER_SIZE = 4000      # size of ALSA buffer in frames

# PortAudio latency hint.  Deliberately NOT derived from PCM_BUFFER_SIZE: the
# two are not the same quantity, and PortAudio inflates a requested latency
# substantially.  Measured on CoreAudio at 8kHz, asking for PCM_BUFFER_SIZE
# (0.5s) yields ~2.5s of real delay, which is unusable for a scanner, while
# 'low' resolves to ~165ms — about eight 20ms voice frames of jitter tolerance.
# Override with OP25_PORTAUDIO_LATENCY ('low', 'high', or a value in seconds).
PORTAUDIO_LATENCY = os.environ.get('OP25_PORTAUDIO_LATENCY', 'low')

# Depth of the PortAudio jitter buffer, in milliseconds of audio.  PRIME is how
# much must accumulate before playback starts (and again after the buffer runs
# dry); it trades start-of-transmission delay against robustness to jitter.
# MAX bounds the queue so a stalled device cannot make playback drift further
# and further behind real time.
PORTAUDIO_PRIME_MS = int(os.environ.get('OP25_PORTAUDIO_PRIME_MS', '120'))
PORTAUDIO_MAX_MS   = int(os.environ.get('OP25_PORTAUDIO_MAX_MS', '1000'))

MAX_SUPERFRAME_SIZE = 320   # maximum size of incoming UDP audio buffer

# Debug
LOG_AUDIO_XRUNS = True      # log audio underruns to stderr

# Alsa PCM constants
SND_PCM_FORMAT_S8 = c_int(0)
SND_PCM_FORMAT_U8 = c_int(1)
SND_PCM_FORMAT_S16_LE = c_int(2)
SND_PCM_FORMAT_S16_BE = c_int(3)
SND_PCM_FORMAT_U16_LE = c_int(4)
SND_PCM_FORMAT_U16_BE = c_int(5)
SND_PCM_FORMAT_S24_LE = c_int(6)
SND_PCM_FORMAT_S24_BE = c_int(7)
SND_PCM_FORMAT_U24_LE = c_int(8)
SND_PCM_FORMAT_U24_BE = c_int(9)
SND_PCM_FORMAT_S32_LE = c_int(10)
SND_PCM_FORMAT_S32_BE = c_int(11)
SND_PCM_FORMAT_U32_LE = c_int(12)
SND_PCM_FORMAT_U32_BE = c_int(13)
SND_PCM_FORMAT_FLOAT_LE = c_int(14)
SND_PCM_FORMAT_FLOAT_BE = c_int(15)
SND_PCM_FORMAT_FLOAT64_LE = c_int(16)
SND_PCM_FORMAT_FLOAT64_BE = c_int(17)
SND_PCM_FORMAT_IEC958_SUBFRAME_LE = c_int(18)
SND_PCM_FORMAT_IEC958_SUBFRAME_BE = c_int(19)
SND_PCM_FORMAT_MU_LAW = c_int(20)
SND_PCM_FORMAT_A_LAW = c_int(21)
SND_PCM_FORMAT_IMA_ADPCM = c_int(22)
SND_PCM_FORMAT_MPEG = c_int(23)
SND_PCM_FORMAT_GSM = c_int(24)
SND_PCM_FORMAT_SPECIAL = c_int(31)
SND_PCM_FORMAT_S24_3LE = c_int(32)
SND_PCM_FORMAT_S24_3BE = c_int(33)
SND_PCM_FORMAT_U24_3LE = c_int(34)
SND_PCM_FORMAT_U24_3BE = c_int(35)
SND_PCM_FORMAT_S20_3LE = c_int(36)
SND_PCM_FORMAT_S20_3BE = c_int(37)
SND_PCM_FORMAT_U20_3LE = c_int(38)
SND_PCM_FORMAT_U20_3BE = c_int(39)
SND_PCM_FORMAT_S18_3LE = c_int(40)
SND_PCM_FORMAT_S18_3BE = c_int(41)
SND_PCM_FORMAT_U18_3LE = c_int(42)
SND_PCM_FORMAT_U18_3BE = c_int(43)
SND_PCM_FORMAT_S16 = c_int(2)
SND_PCM_FORMAT_U16 = c_int(4)
SND_PCM_FORMAT_S24 = c_int(6)
SND_PCM_FORMAT_U24 = c_int(8)
SND_PCM_FORMAT_S32 = c_int(10)
SND_PCM_FORMAT_U32 = c_int(12)
SND_PCM_FORMAT_FLOAT = c_int(14)
SND_PCM_FORMAT_FLOAT64 = c_int(16)
SND_PCM_FORMAT_IEC958_SUBFRAME = c_int(18)
SND_PCM_FORMAT_LAST = SND_PCM_FORMAT_U18_3BE

SND_PCM_NORMAL = c_int(0x00000000)
SND_PCM_NONBLOCK = c_int(0x00000001)

SND_PCM_STREAM_PLAYBACK = c_int(0)
SND_PCM_STREAM_CAPTURE = c_int(1)
SND_PCM_STREAM_LAST = SND_PCM_STREAM_CAPTURE

SND_PCM_ACCESS_MMAP_INTERLEAVED = c_int(0)
SND_PCM_ACCESS_MMAP_NONINTERLEAVED = c_int(1)
SND_PCM_ACCESS_MMAP_COMPLEX = c_int(2)
SND_PCM_ACCESS_RW_INTERLEAVED = c_int(3)
SND_PCM_ACCESS_RW_NONINTERLEAVED = c_int(4)
SND_PCM_ACCESS_LAST = SND_PCM_ACCESS_RW_NONINTERLEAVED

PA_STREAM_PLAYBACK = 1
PA_SAMPLE_S16LE = 3

# Python CTypes wrapper to Alsa libasound2
class alsasound(object):
    def __init__(self):
        self.libasound = cdll.LoadLibrary("libasound.so.2")
        self.c_pcm = c_void_p()
        self.format = 0
        self.channels = 0
        self.rate = 0
        self.framesize = 0

    def open(self, hwdev):
        b_hwdev = create_string_buffer(str.encode(hwdev))
        c_stream = SND_PCM_STREAM_PLAYBACK
        err = self.libasound.snd_pcm_open(byref(self.c_pcm), b_hwdev, c_stream, SND_PCM_NORMAL)
        return err

    def close(self):
        if (self.c_pcm.value == None):
            return
        self.libasound.snd_pcm_close(self.c_pcm)
        self.c_pcm.value = None

    def setup(self, pcm_format, pcm_channels, pcm_rate, pcm_buffer_size):
        if (self.c_pcm.value == None):
            return

        self.format = pcm_format
        self.channels = pcm_channels
        self.rate = pcm_rate
        pcm_buf_sz = c_ulong(pcm_buffer_size)

        c_pars = (c_void_p * int(self.libasound.snd_pcm_hw_params_sizeof() / sizeof(c_void_p)))()
        err = self.libasound.snd_pcm_hw_params_any(self.c_pcm, c_pars)
        if err < 0:
            sys.stderr.write("hw_params_any failed: %d\n" % err)
            return err

        err = self.libasound.snd_pcm_hw_params_set_access(self.c_pcm, c_pars, SND_PCM_ACCESS_RW_INTERLEAVED)
        if err < 0:
            sys.stderr.write("set_access failed: %d\n" % err)
            return err
        err = self.libasound.snd_pcm_hw_params_set_format(self.c_pcm, c_pars, c_uint(self.format))
        if err < 0:
            sys.stderr.write("set_format failed: %d\n" % err)
            return err
        err = self.libasound.snd_pcm_hw_params_set_channels(self.c_pcm, c_pars, c_uint(self.channels))
        if err < 0:
            sys.stderr.write("set_channels failed: %d\n" % err)
            return err
        err = self.libasound.snd_pcm_hw_params_set_rate(self.c_pcm, c_pars, c_uint(self.rate), c_int(0))
        if err < 0:
            sys.stderr.write("set_rate failed: %d\n" % err)
            return err
        err = self.libasound.snd_pcm_hw_params_set_buffer_size_near(self.c_pcm, c_pars, byref(pcm_buf_sz))
        if err < 0:
            sys.stderr.write("set_buffer_size_near failed: %d\n" % err)
            return err
        if pcm_buf_sz.value != pcm_buffer_size:
            sys.stderr.write("set_buffer_size_near requested %d, but returned %d\n" % (pcm_buffer_size, pcm_buf_sz.value))
        err = self.libasound.snd_pcm_hw_params(self.c_pcm, c_pars)
        if err < 0:
            sys.stderr.write("hw_params failed: %d\n" % err)
            return err

        self.libasound.snd_pcm_hw_params_current(self.c_pcm, c_pars)
        c_bits =  self.libasound.snd_pcm_hw_params_get_sbits(c_pars)
        self.framesize = self.channels * c_bits//8

        c_sw_pars = (c_void_p * int(self.libasound.snd_pcm_sw_params_sizeof() / sizeof(c_void_p)))()
        err = self.libasound.snd_pcm_sw_params_current(self.c_pcm, c_sw_pars)
        if err < 0:
            sys.stderr.write("get_sw_params_current failed: %d\n" % err)
            return err
        pcm_start_threshold = int(pcm_buf_sz.value * 0.75)
        err = self.libasound.snd_pcm_sw_params_set_start_threshold(self.c_pcm, c_sw_pars, c_uint(pcm_start_threshold))
        if err < 0:
            sys.stderr.write("set_sw_params_start_threshold failed: %d\n" % err)
            return err
        err = self.libasound.snd_pcm_sw_params(self.c_pcm, c_sw_pars)
        if err < 0:
            sys.stderr.write("sw_params failed: %d\n" % err)
            return err

        ret = self.libasound.snd_pcm_prepare(self.c_pcm)
        #self.dump()
        return ret

    def write(self, pcm_data):
        datalen = len(pcm_data)
        n_frames = c_ulong(datalen // self.framesize)
        c_data = c_char_p(pcm_data)
        ret = 0

        if (self.c_pcm.value == None):
            sys.stderr.write("PCM device is closed\n")
            return -1

        ret = self.libasound.snd_pcm_writei(self.c_pcm, cast(c_data, POINTER(c_void_p)), n_frames)
        if (ret < 0):
            if (ret == -errno.EPIPE): # underrun
                if (LOG_AUDIO_XRUNS):
                    sys.stderr.write("%s PCM underrun\n" % log_ts.get())
                ret = self.libasound.snd_pcm_recover(self.c_pcm, ret, 1)
                if (ret >= 0):
                    ret = self.libasound.snd_pcm_writei(self.c_pcm, cast(c_data, POINTER(c_void_p)), n_frames)
                else:
                    ret = self.libasound.snd_pcm_prepare(self.c_pcm)
                    ret = self.libasound.snd_pcm_writei(self.c_pcm, cast(c_data, POINTER(c_void_p)), n_frames)
            elif (ret == -errno.ESTRPIPE): # suspended
                while True:
                    ret = self.libasound.snd_pcm_resume(self.c_pcm)
                    if (ret != -errno.EAGAIN):
                        break
                    time.sleep(1)
                if (ret < 0):
                    ret = self.libasound.snd_pcm_prepare(self.c_pcm)
            elif (ret < 0): # other error
                ret = self.libasound.snd_pcm_prepare(self.c_pcm)

        return ret

    def drain(self):
        ret = self.libasound.snd_pcm_drain(self.c_pcm)
        if (ret == -errno.ESTRPIPE): # suspended
            while True:
                ret = self.libasound.snd_pcm_resume(self.c_pcm)
                if (ret != -errno.EAGAIN):
                    break
                time.sleep(1)
        ret = self.libasound.snd_pcm_prepare(self.c_pcm)
        return ret

    def drop(self):
        ret = self.libasound.snd_pcm_drop(self.c_pcm)
        if (ret == -errno.ESTRPIPE): # suspended
            while True:
                ret = self.libasound.snd_pcm_resume(self.c_pcm)
                if (ret != -errno.EAGAIN):
                    break
                time.sleep(1)
        ret = self.libasound.snd_pcm_prepare(self.c_pcm)
        return ret

    def dump(self):
        if (self.c_pcm.value == None):
            return

        c_buf_p = c_void_p()
        c_str_p = c_char_p()
        c_strlen = c_uint(0)
        self.libasound.snd_output_buffer_open(byref(c_buf_p))
        self.libasound.snd_pcm_dump_setup(self.c_pcm, c_buf_p)
        c_strlen = self.libasound.snd_output_buffer_string(c_buf_p, byref(c_str_p))
        sys.stderr.write("%s\n" % c_str_p.value[0:c_strlen-1])
        self.libasound.snd_output_close(c_buf_p)

    def check(self):
        return 0

class _struct_pa_sample_spec(Structure):
    _fields_ = [("format", c_int),
                ("rate", c_int),
                ("channels", c_byte)]

class pa_sound(object):
    def __init__(self, instance_name):
        self.instance_name = instance_name
        self.out = c_void_p(None)
        self.error = c_int(0)
        self.libpa = cdll.LoadLibrary("libpulse-simple.so.0")
       	self.libpa.strerror.restype = c_char_p
        self.ss = _struct_pa_sample_spec(PA_SAMPLE_S16LE, 8000, 2)

    def open(self, hwdevice):
        pa_simple_new = self.libpa.pa_simple_new
        pa_simple_new.restype = c_void_p
        self.out = pa_simple_new(None,
                                self.instance_name.encode("ascii"),
                                PA_STREAM_PLAYBACK,
                                None,
                                "OP25 Playback".encode('ascii'),
                                byref(self.ss),
                                None,
                                None,
                                byref(self.error))

        if self.out is None:
            sys.stderr.write("Could not open PulseAudio stream: %s\n" % self.libpa.strerror(self.error))
        else:
            sys.stderr.write("Opened PulseAudio stream: %016x\n" % self.out)

        return self.error.value

    def close(self):
        if self.out is None:
            return
        self.libpa.pa_simple_free(c_void_p(self.out))
        self.out = None

    def setup(self, pcm_format, pcm_channels, pcm_rate, pcm_buffer_size):
        self.ss.format = PA_SAMPLE_S16LE # fixed format
        self.ss.channels = pcm_channels
        self.ss.rate = pcm_rate
        return 0

    def write(self, pcm_data):
        if self.out is None:
            return -1
        self.libpa.pa_simple_write(c_void_p(self.out), pcm_data, len(pcm_data), byref(self.error))
        return self.error

    def drain(self):
        if self.out is None:
            return -1
        self.libpa.pa_simple_drain(c_void_p(self.out), byref(self.error))
        return self.error.value

    def drop(self):
        if self.out is None:
            return -1
        self.libpa.pa_simple_flush(c_void_p(self.out), byref(self.error))
        return self.error.value

    def dump(self):
        return 0

    def check(self):
        return 0


# PCM output via PortAudio, using the python-sounddevice module.
#
# Implements the same duck-typed interface as alsasound and pa_sound
# (open/close/setup/write/drain/drop/dump/check) so socket_audio can use any of
# them interchangeably.  This is the only cross-platform backend: it is the
# default on macOS, where it reaches CoreAudio, and is available on Linux both
# as an explicit choice and as a last-resort fallback.
class portaudio_sound(object):
    # Device strings that mean "use the system default output" rather than
    # naming a specific PortAudio device.  "pulse" is included so an existing
    # Linux config keeps working unchanged when run on macOS.
    DEFAULT_ALIASES = ("", "default", "pulse", "pulseaudio", "portaudio", "coreaudio", "sounddevice")

    # ALSA device syntax has no PortAudio equivalent; fall back to the default.
    ALSA_PREFIXES = ("hw:", "plughw:", "sysdefault", "dmix", "dsnoop", "surround")

    def __init__(self, instance_name = "OP25"):
        if _sounddevice is None:
            raise RuntimeError("sounddevice/portaudio unavailable: %s" % _sounddevice_error)
        self.instance_name = instance_name
        self.stream = None
        self.device = None
        self.channels = 2
        self.rate = PCM_RATE
        self.framesize = 4          # 2 channels * 2 bytes (S16_LE)
        # Jitter buffer shared with the PortAudio callback thread.  A blocking
        # write() cannot work here: the decoder produces 20ms of audio every
        # 20ms, so a directly-fed stream sits permanently on the edge of empty
        # and underruns on virtually every callback.  Buffering a short prime
        # before playback starts, and re-priming whenever the buffer runs dry,
        # keeps the device fed through normal network and scheduling jitter.
        self.buf = bytearray()
        self.buf_lock = threading.Lock()
        self.primed = False
        self.prime_bytes = 0
        self.max_bytes = 0
        self.underruns = 0
        self.last_xrun_log = 0.0

    def _resolve_device(self, hwdev):
        """Map an op25 device string onto a PortAudio device, or None for default."""
        name = (hwdev or "").strip()
        if name.lower() in self.DEFAULT_ALIASES:
            return None
        if name.lower().startswith(self.ALSA_PREFIXES):
            sys.stderr.write("portaudio: '%s' is ALSA-only syntax, using default output device\n" % name)
            return None
        try:
            return int(name)        # numeric PortAudio device index
        except ValueError:
            pass
        try:
            _sounddevice.query_devices(name)     # substring match; raises if missing/ambiguous
            return name
        except Exception as e:
            sys.stderr.write("portaudio: device '%s' not usable (%s), using default output device\n" % (name, e))
            return None

    def open(self, hwdev):
        self.device = self._resolve_device(hwdev)
        return 0

    def close(self):
        if self.stream is None:
            return
        try:
            self.stream.stop()
            self.stream.close()
        except Exception as e:
            sys.stderr.write("portaudio: close failed: %s\n" % e)
        self.stream = None

    def _latency(self):
        """PORTAUDIO_LATENCY as either a float (seconds) or a PortAudio keyword."""
        try:
            return float(PORTAUDIO_LATENCY)
        except (TypeError, ValueError):
            return PORTAUDIO_LATENCY

    def _callback(self, outdata, frames, time_info, status):
        """Fill one PortAudio output block from the jitter buffer.

        Runs on the PortAudio thread.  Missing audio is filled with silence
        rather than left as stale data, and running dry re-arms priming so the
        buffer refills before playback continues.
        """
        need = frames * self.framesize
        with self.buf_lock:
            if not self.primed:
                if len(self.buf) < self.prime_bytes:
                    outdata[:] = bytes(need)        # still filling — output silence
                    return
                self.primed = True
            avail = min(need, len(self.buf))
            if avail:
                outdata[:avail] = bytes(self.buf[:avail])
                del self.buf[:avail]
            if avail < need:
                outdata[avail:] = bytes(need - avail)
                self.primed = False
                self.underruns += 1

    def setup(self, pcm_format, pcm_channels, pcm_rate, pcm_buffer_size):
        # pcm_format is an ALSA enum; op25 only ever asks for S16_LE.
        if pcm_format != SND_PCM_FORMAT_S16_LE.value:
            sys.stderr.write("portaudio: unsupported format %d requested, using S16_LE\n" % pcm_format)
        self.channels = pcm_channels
        self.rate = pcm_rate
        self.framesize = pcm_channels * 2
        self.prime_bytes = int(pcm_rate * PORTAUDIO_PRIME_MS / 1000.0) * self.framesize
        # Hard cap on queued audio.  If the device stalls or the decoder floods
        # us, drop the oldest audio rather than growing without bound and
        # playing back further and further behind real time.
        self.max_bytes = int(pcm_rate * PORTAUDIO_MAX_MS / 1000.0) * self.framesize
        self.close()
        with self.buf_lock:
            self.buf = bytearray()
            self.primed = False
        try:
            # pcm_buffer_size is intentionally unused — see PORTAUDIO_LATENCY.
            self.stream = _sounddevice.RawOutputStream(
                    samplerate = pcm_rate,
                    channels   = pcm_channels,
                    dtype      = 'int16',
                    device     = self.device,
                    latency    = self._latency(),
                    callback   = self._callback)
            self.stream.start()
        except Exception as e:
            sys.stderr.write("portaudio: unable to open output stream: %s\n" % e)
            self.stream = None
            return -1
        try:
            dev_name = _sounddevice.query_devices(self.stream.device)['name']
        except Exception:
            dev_name = "default"
        sys.stderr.write("portaudio: output '%s' %dHz %dch latency %.0fms prime %dms\n" %
                         (dev_name, pcm_rate, pcm_channels, self.stream.latency * 1000, PORTAUDIO_PRIME_MS))
        return 0

    def write(self, pcm_data):
        if self.stream is None:
            sys.stderr.write("PCM device is closed\n")
            return -1
        # PortAudio only consumes whole frames.
        n_frames = len(pcm_data) // self.framesize
        if n_frames == 0:
            return 0
        with self.buf_lock:
            self.buf.extend(pcm_data[:n_frames * self.framesize])
            excess = len(self.buf) - self.max_bytes
            if excess > 0:
                del self.buf[:excess]
        self._log_xruns()
        return n_frames

    def _log_xruns(self):
        """Report accumulated underruns at most once a second.

        Gaps between transmissions legitimately empty the buffer, so this would
        otherwise log constantly on a quiet system.
        """
        if not LOG_AUDIO_XRUNS or not self.underruns:
            return
        now = time.time()
        if now - self.last_xrun_log < 1.0:
            return
        self.last_xrun_log = now
        count, self.underruns = self.underruns, 0
        sys.stderr.write("%s PCM underrun (x%d)\n" % (log_ts.get(), count))

    def drain(self):
        # End of transmission.  Let the buffered tail play out; stopping the
        # stream here would truncate the end of the call.
        return 0

    def drop(self):
        # Discard buffered audio (talkgroup skip / hold change) so the next
        # transmission is not preceded by stale audio.
        if self.stream is None:
            return -1
        with self.buf_lock:
            self.buf = bytearray()
            self.primed = False
        return 0

    def dump(self):
        if _sounddevice is None:
            return
        try:
            sys.stderr.write("%s\n" % _sounddevice.query_devices())
        except Exception:
            pass

    def check(self):
        # Called when the UDP sockets have gone quiet.  Make sure the stream
        # did not get stopped underneath us, e.g. by the default output device
        # changing when headphones are unplugged.
        if self.stream is None:
            return -1
        try:
            if not self.stream.active:
                self.stream.start()
        except Exception as e:
            sys.stderr.write("portaudio: unable to restart stream: %s\n" % e)
            return -1
        return 0


# Wrapper to emulate pcm writes of sound samples to stdout (for liquidsoap)
class stdout_wrapper(object): 
    def __init__(self):
        self.silence = bytearray(640)
        pass

    def open(self, hwdev):
        return 0

    def close(self):
        return 0

    def setup(self, pcm_format, pcm_channels, pcm_rate, pcm_buffer_size):
        return 0

    def drain(self):
        try:
            sys.stdout.flush()
        except IOError: # IOError means listener has terminated
            sys.stderr.write("stdout_wrapper::drain() broken pipe\n")
            return -1
        return 0

    def drop(self):
        return 0

    def write(self, pcm_data):
        try:
            sys.stdout.write(pcm_data)
        except IOError: # IOError means listener has terminated
            sys.stderr.write("stdout_wrapper::write() broken pipe\n")
            return -1
        return 0

    def check(self):
        rc = 0
        if (self.write(self.silence) < 0) or (self.drain() < 0): # write silence to check pipe connectivity 
            sys.stderr.write("stdout_wrapper::check() broken pipe\n")
            rc = -1
        return rc

    def dump(self):
        pass

# Main class that receives UDP audio samples and sends them to a PCM subsystem (currently ALSA or STDOUT)
class socket_audio(object):
    def __init__(self, udp_host, udp_port, pcm_device, two_channels = False, audio_gain = 1.0, dest_stdout = False, instance_name = "OP25", **kwds):
        self.keep_running = True
        self.two_channels = two_channels
        self.audio_gain = audio_gain
        self.dest_stdout = dest_stdout
        self.instance_name = instance_name
        self.sock_a = None
        self.sock_b = None
        self.pcm = None
        if dest_stdout:
            pcm_device = "stdout"
            sys.stdout = os.fdopen(sys.stdout.fileno(), 'wb', 0) # reopen stdout with buffering disabled
            self.pcm = stdout_wrapper()
        else:
            self.pcm, pcm_device = self.open_pcm_backend(pcm_device)

        if self.pcm is not None:
            self.setup_pcm(pcm_device)
        else:
            self.keep_running = False

        self.setup_sockets(udp_host, udp_port)

    # "device_name" values that select a sound system rather than a device
    # within one.  Anything else (e.g. "default", "hw:0,0", a PortAudio device
    # name or index) is treated as a device name for the platform default.
    BACKEND_ALIASES = {
            "pulse":       "pulseaudio",
            "pulseaudio":  "pulseaudio",
            "alsa":        "alsa",
            "portaudio":   "portaudio",
            "coreaudio":   "portaudio",
            "sounddevice": "portaudio",
            }

    def open_pcm_backend(self, pcm_device):
        """Pick a PCM backend that actually exists on this platform.

        ALSA and PulseAudio are Linux-only shared libraries.  On macOS (and
        anything else that is not Linux) go straight to PortAudio, which
        reaches CoreAudio.  On Linux keep the historical behavior — PulseAudio
        when asked for, otherwise ALSA — and only fall back to PortAudio if
        neither library loads.

        Returns (backend_or_None, device_name_to_open).
        """
        requested = self.BACKEND_ALIASES.get((pcm_device or "").strip().lower())

        if sys.platform.startswith("linux"):
            if requested == "pulseaudio":
                order = ["pulseaudio", "alsa", "portaudio"]
            elif requested == "portaudio":
                order = ["portaudio"]
            else:
                order = ["alsa", "portaudio"]
        else:
            if requested in ("pulseaudio", "alsa"):
                sys.stderr.write("audio: '%s' is Linux-only, using PortAudio on %s\n" % (pcm_device, sys.platform))
            order = ["portaudio"]

        for backend in order:
            # 'pulse' is not a device name ALSA can be relied on to open, so
            # reset to 'default' when falling back off PulseAudio.
            device = pcm_device
            if backend == "alsa" and requested == "pulseaudio":
                device = "default"
            try:
                if backend == "pulseaudio":
                    pcm = pa_sound(self.instance_name)
                elif backend == "alsa":
                    pcm = alsasound()
                else:
                    pcm = portaudio_sound(self.instance_name)
            except Exception as e:
                sys.stderr.write("audio: %s unavailable (%s)\n" % (backend, e))
                continue
            sys.stderr.write("audio: using %s sound system\n" % backend)
            return pcm, device

        sys.stderr.write("audio: no working sound system found, local audio disabled\n")
        return None, pcm_device

    def run(self):
        rc = 0
        while self.keep_running and (rc >= 0):
            readable, writable, exceptional = select.select( [self.sock_a, self.sock_b], [], [self.sock_a, self.sock_b], 5.0)
            in_a = None
            in_b = None
            data_a = bytearray()
            data_b = bytearray()
            flag_a = -1
            flag_b = -1

            # Check for select() polling timeout and pcm self-check
            if (not readable) and (not writable) and (not exceptional):
                rc = self.pcm.check()
                if isinstance(rc, ctypes.c_int):
                    rc = rc.value
                continue

            # Data received on the udp port is 320 bytes for an audio frame or 2 bytes for a flag
            if self.sock_a in readable:
                in_a = self.sock_a.recvfrom(MAX_SUPERFRAME_SIZE)

            if self.sock_b in readable:
                in_b = self.sock_b.recvfrom(MAX_SUPERFRAME_SIZE)

            if in_a is not None:
                len_a = len(in_a[0])
                if len_a == 2:
                    flag_a = np.frombuffer(in_a[0], dtype=np.int16)[0]
                elif len_a > 0:
                    data_a = in_a[0]

            if in_b is not None:
                len_b = len(in_b[0])
                if len_b == 2:
                    flag_b = np.frombuffer(in_b[0], dtype=np.int16)[0]
                elif len_b > 0:
                    data_b = in_b[0]

            if (flag_a == 0) or (flag_b == 0):
                rc = self.pcm.drain()
                if isinstance(rc, ctypes.c_int):
                    rc = rc.value
                continue

            if (((flag_a == 1) and (flag_b == 1)) or
                ((flag_a == 1) and (in_b is None)) or 
                ((flag_b == 1) and (in_a is None))):
                rc = self.pcm.drop()
                if isinstance(rc, ctypes.c_int):
                    rc = rc.value
                continue

            if not self.two_channels:
                data_a = self.scale(data_a)
                rc = self.pcm.write(self.interleave(data_a, data_a))
                if isinstance(rc, ctypes.c_int):
                    rc = rc.value
            else:
                data_a = self.scale(data_a)
                data_b = self.scale(data_b)
                rc = self.pcm.write(self.interleave(data_a, data_b))
                if isinstance(rc, ctypes.c_int):
                    rc = rc.value

        self.close_sockets()
        self.close_pcm()
        return

    def scale(self, data):  # crude amplitude scaler (volume) for S16_LE samples
        arr = np.array(np.frombuffer(data, dtype=np.int16), dtype=np.float32)
        result = np.zeros(len(arr), dtype=np.int16)
        arr = np.clip(arr*self.audio_gain, -32767, 32766, out=result, casting='unsafe')
        return result.tobytes('C')

    def interleave(self, data_a, data_b):
        arr_a = np.frombuffer(data_a, dtype=np.int16)
        arr_b = np.frombuffer(data_b, dtype=np.int16)
        d_len = max(len(arr_a), len(arr_b))
        result = np.zeros(d_len*2, dtype=np.int16)
        if len(arr_a):
            # copy arr_a to result[0,2,4, ...]
            result[ range(0, len(arr_a)*2, 2) ] = arr_a
        if len(arr_b):
            # copy arr_b to result[1,3,5, ...]
            result[ range(1, len(arr_b)*2, 2) ] = arr_b
        return result.tobytes('C')

    def stop(self):
        self.keep_running = False
        return

    def setup_sockets(self, udp_host, udp_port):
        sys.stderr.write("Listening on %s:%d\n" % (udp_host, udp_port))
        self.sock_a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_a.setblocking(0)
        self.sock_b.setblocking(0)
        self.sock_a.bind((udp_host, udp_port))
        self.sock_b.bind((udp_host, udp_port + 1))
        return

    def close_sockets(self):
        self.sock_a.close()
        self.sock_b.close()
        return

    def setup_pcm(self, hwdevice):
        sys.stderr.write('audio device: %s\n' % hwdevice)
        err = self.pcm.open(hwdevice)
        if err < 0:
            sys.stderr.write('failed to open audio device: %s\n' % hwdevice)
            self.pcm.dump()
            self.keep_running = False
            return

        err = self.pcm.setup(SND_PCM_FORMAT_S16_LE.value, 2, PCM_RATE, PCM_BUFFER_SIZE)
        if err < 0:
            sys.stderr.write('failed to set up pcm stream\n')
            self.keep_running = False
            return
        return

    def close_pcm(self):
        sys.stderr.write('audio closing\n')
        if self.pcm is not None:
            self.pcm.close()
        return

class audio_thread(threading.Thread):
    def __init__(self, udp_host, udp_port, pcm_device, two_channels = False, audio_gain = 1.0, dest_stdout = False, instance_name = "OP25", **kwds):
        threading.Thread.__init__(self, **kwds)
        self.setDaemon(True)
        self.keep_running = True
        self.sock_audio = socket_audio(udp_host, udp_port, pcm_device, two_channels, audio_gain, dest_stdout, instance_name, **kwds)
        self.start()
        return

    def run(self):
        self.sock_audio.run()

    def stop(self):
        self.sock_audio.stop()

