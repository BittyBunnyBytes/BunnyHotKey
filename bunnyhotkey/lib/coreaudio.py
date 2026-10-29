"""SoundGetInterface: Windows Core Audio interfaces over PulseAudio/PipeWire, as native COM objects.

Scripts take an interface with SoundGetInterface(IID, Component, Device) and call it by vtable index with ComCall,
e.g. IAudioMeterInformation::GetPeakValue (index 3) for a level meter, or IAudioEndpointVolume methods for
volume in decibels and per channel.  The vtables here follow the Windows SDK headers (endpointvolume.h,
devicetopology.h, mmdeviceapi.h), so those scripts run unchanged; the work is done with pactl/parec.
"""
from __future__ import annotations

import ctypes
import math
import shutil
import struct
import subprocess
import threading

from .. import objects as O
from . import comnative as N
from .comnative import P, S_OK, c_hr, guid_bytes, rd, wr

IID_IAudioEndpointVolume = guid_bytes("{5CDF2C82-841E-4546-9722-0CF74078229A}")
IID_IAudioMeterInformation = guid_bytes("{C02216F6-8C67-4B5B-9D00-D008E73E0064}")
IID_IMMEndpoint = guid_bytes("{1BE09788-6894-4089-8586-9A2A6C265AC5}")
IID_IAudioVolumeLevel = guid_bytes("{7FB7B48F-531D-44A2-BCB3-5AD5A134B3DC}")
IID_IAudioMute = guid_bytes("{DF45AEEA-B74A-4B6B-AFAD-2366B6AA012E}")
IID_IPerChannelDbLevel = guid_bytes("{C2F8E001-F205-4BC9-99BC-C13B1E048CCB}")

MIN_DB, MAX_DB, STEP_DB = -65.25, 0.0, 0.03125     # the range Windows reports for typical endpoints
E_INVALIDARG = 0x80070057
ENDPOINT_HARDWARE_SUPPORT_VOLUME, ENDPOINT_HARDWARE_SUPPORT_MUTE, ENDPOINT_HARDWARE_SUPPORT_METER = 1, 2, 4


def scalar_to_db(s):
    """Pulse's cubic volume curve: linear amplitude = s**3."""
    if s <= 0:
        return MIN_DB
    return max(MIN_DB, min(MAX_DB, 60.0 * math.log10(s)))


def db_to_scalar(db):
    if db <= MIN_DB:
        return 0.0
    return min(1.0, 10 ** (min(db, MAX_DB) / 60.0))


# ---------------------------------------------------------------- one audio endpoint
class Endpoint:
    """A sink or source by pactl name."""

    def __init__(self, kind, info):
        self.kind = kind                    # "sink" or "source"
        self.name = info.get("name", "")

    def info(self):
        from .sound import _pactl_json
        for d in _pactl_json("list", self.kind + "s") or []:
            if d.get("name") == self.name:
                return d
        return {}

    def channels(self):
        vols = self.info().get("volume", {})
        return [int(str(v.get("value_percent", "0")).rstrip("%") or 0) / 100 for v in vols.values()] or [0.0]

    def set_channels(self, scalars):
        args = [f"{max(0, round(s * 100))}%" for s in scalars]
        subprocess.run(["pactl", f"set-{self.kind}-volume", self.name, *args], capture_output=True)

    def master(self):
        ch = self.channels()
        return max(ch) if ch else 0.0       # Windows' master scalar is the loudest channel's

    def set_master(self, s):
        ch = self.channels()
        top = max(ch) if ch else 0.0
        s = max(0.0, min(1.0, s))
        # keep the balance between channels, as IAudioEndpointVolume does
        self.set_channels([s * (c / top) if top > 0 else s for c in ch])

    def muted(self):
        return int(bool(self.info().get("mute")))

    def set_mute(self, on):
        subprocess.run(["pactl", f"set-{self.kind}-mute", self.name, "1" if on else "0"], capture_output=True)

    def monitor_source(self):
        return self.name + ".monitor" if self.kind == "sink" else self.name


# ---------------------------------------------------------------- peak metering
class Meter:
    """Peak levels from parec, kept while an IAudioMeterInformation exists."""

    def __init__(self, ep, nch):
        self.peaks = [0.0] * nch
        self.nch = nch
        self.proc = None
        if shutil.which("parec"):
            try:
                self.proc = subprocess.Popen(
                    ["parec", f"--device={ep.monitor_source()}", "--format=float32le", f"--channels={nch}",
                     "--rate=8000", "--latency-msec=20", "--raw"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                threading.Thread(target=self._read, daemon=True).start()
            except OSError:
                self.proc = None

    def _read(self):
        frame = 4 * self.nch
        chunk = frame * 160                 # 20 ms
        while self.proc is not None:
            data = self.proc.stdout.read(chunk)
            if not data:
                return
            n = len(data) // frame
            vals = struct.unpack(f"<{n * self.nch}f", data[:n * frame])
            self.peaks = [min(1.0, max((abs(v) for v in vals[c::self.nch]), default=0.0)) for c in range(self.nch)]

    def stop(self):
        p, self.proc = self.proc, None
        if p is not None:
            p.kill()


# ---------------------------------------------------------------- interfaces
class _AudioObject(N.NativeObject):
    """An interface returned to the script as a raw pointer: it holds itself until its last Release."""

    def __init__(self, methods, iids, ep):
        self.ep = ep
        super().__init__(methods, iids)
        self.keep = self

    def on_last_release(self):
        self.keep = None
        self.close()
        with N._lock:
            N._OBJECTS.pop(self.ptr, None)

    def close(self):
        pass


def _f(addr, v):
    if addr:
        wr("<f", addr, float(v))


def _u(addr, v):
    if addr:
        wr("<I", addr, int(v))


class EndpointVolume(_AudioObject):
    """IAudioEndpointVolume (endpointvolume.h): methods 3-20."""

    def __init__(self, ep):
        self.callbacks = []
        self.watch = None
        u, f, p = ctypes.c_uint, ctypes.c_float, P
        super().__init__([
            (c_hr, [p], self.register_notify),                     # 3 RegisterControlChangeNotify
            (c_hr, [p], self.unregister_notify),                   # 4 UnregisterControlChangeNotify
            (c_hr, [p], lambda o: _u(o, len(ep.channels()))),      # 5 GetChannelCount
            (c_hr, [f, p], lambda db, g: ep.set_master(db_to_scalar(db))),            # 6 SetMasterVolumeLevel
            (c_hr, [f, p], self.set_master_scalar),                # 7 SetMasterVolumeLevelScalar
            (c_hr, [p], lambda o: _f(o, scalar_to_db(ep.master()))),                  # 8 GetMasterVolumeLevel
            (c_hr, [p], lambda o: _f(o, ep.master())),             # 9 GetMasterVolumeLevelScalar
            (c_hr, [u, f, p], lambda ch, db, g: self.set_channel(ch, db_to_scalar(db))),  # 10 SetChannelVolumeLevel
            (c_hr, [u, f, p], lambda ch, s, g: self.set_channel(ch, s)),             # 11 SetChannelVolumeLevelScalar
            (c_hr, [u, p], lambda ch, o: self.get_channel(ch, o, db=True)),         # 12 GetChannelVolumeLevel
            (c_hr, [u, p], lambda ch, o: self.get_channel(ch, o, db=False)),        # 13 GetChannelVolumeLevelScalar
            (c_hr, [ctypes.c_int, p], lambda on, g: ep.set_mute(on)),                # 14 SetMute
            (c_hr, [p], lambda o: _u(o, ep.muted())),              # 15 GetMute
            (c_hr, [p, p], self.step_info),                        # 16 GetVolumeStepInfo
            (c_hr, [p], lambda g: self.step(+1)),                  # 17 VolumeStepUp
            (c_hr, [p], lambda g: self.step(-1)),                  # 18 VolumeStepDown
            (c_hr, [p], lambda o: _u(o, ENDPOINT_HARDWARE_SUPPORT_VOLUME | ENDPOINT_HARDWARE_SUPPORT_MUTE)),  # 19
            (c_hr, [p, p, p], self.volume_range),                  # 20 GetVolumeRange
        ], (IID_IAudioEndpointVolume,), ep)

    def set_master_scalar(self, s, g):
        if not 0.0 <= s <= 1.0:
            return E_INVALIDARG
        self.ep.set_master(s)
        return S_OK

    def set_channel(self, ch, s):
        cur = self.ep.channels()
        if ch >= len(cur) or not 0.0 <= s <= 1.0:
            return E_INVALIDARG
        cur[ch] = s
        self.ep.set_channels(cur)
        return S_OK

    def get_channel(self, ch, out, db):
        cur = self.ep.channels()
        if ch >= len(cur):
            return E_INVALIDARG
        _f(out, scalar_to_db(cur[ch]) if db else cur[ch])
        return S_OK

    STEPS = 51          # Windows endpoints usually report 51 steps (2% each)

    def step_info(self, step, count):
        _u(step, round(self.ep.master() * (self.STEPS - 1)))
        _u(count, self.STEPS)
        return S_OK

    def step(self, d):
        cur = round(self.ep.master() * (self.STEPS - 1)) + d
        self.ep.set_master(max(0, min(self.STEPS - 1, cur)) / (self.STEPS - 1))
        return S_OK

    def volume_range(self, lo, hi, inc):
        _f(lo, MIN_DB)
        _f(hi, MAX_DB)
        _f(inc, STEP_DB)
        return S_OK

    # IAudioEndpointVolumeCallback::OnNotify(PAUDIO_VOLUME_NOTIFICATION_DATA) when the volume or mute changes
    def register_notify(self, cb):
        if not cb:
            return N.E_POINTER
        N.addref(cb)
        self.callbacks.append(cb)
        if self.watch is None and shutil.which("pactl"):
            self.watch = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                          text=True)
            threading.Thread(target=self._watch, args=(self.watch,), daemon=True).start()
        return S_OK

    def unregister_notify(self, cb):
        if cb in self.callbacks:
            self.callbacks.remove(cb)
            N.release(cb)
            return S_OK
        return E_INVALIDARG

    def _watch(self, proc):
        index = str(self.ep.info().get("index", ""))
        last = None
        for line in proc.stdout:
            if f"'change' on {self.ep.kind} #{index}" not in line:
                continue
            state = (self.ep.muted(), tuple(self.ep.channels()))
            if state == last:
                continue
            last = state
            O.RT.post_sync(lambda st=state: self._notify(*st))

    def _notify(self, muted, chans):
        n = len(chans)
        raw = bytes(16) + struct.pack(f"<ifI{n}f", muted, max(chans) if chans else 0.0, n, *chans)
        buf = ctypes.create_string_buffer(raw, len(raw))
        for cb in list(self.callbacks):
            try:
                N.vfunc(cb, 3, c_hr, [P])(cb, ctypes.addressof(buf))
            except Exception:
                pass

    def close(self):
        w, self.watch = self.watch, None
        if w is not None:
            w.kill()
        for cb in self.callbacks:
            N.release(cb)
        self.callbacks = []


class MeterInformation(_AudioObject):
    """IAudioMeterInformation: 3 GetPeakValue, 4 GetMeteringChannelCount, 5 GetChannelsPeakValues,
    6 QueryHardwareSupport."""

    def __init__(self, ep):
        self.meter = Meter(ep, max(len(ep.channels()), 1))
        super().__init__([
            (c_hr, [P], lambda o: _f(o, max(self.meter.peaks))),
            (c_hr, [P], lambda o: _u(o, self.meter.nch)),
            (c_hr, [ctypes.c_uint, P], self.channel_peaks),
            (c_hr, [P], lambda o: _u(o, ENDPOINT_HARDWARE_SUPPORT_METER)),
        ], (IID_IAudioMeterInformation,), ep)

    def channel_peaks(self, n, out):
        if n != self.meter.nch or not out:
            return E_INVALIDARG
        for i, v in enumerate(self.meter.peaks[:n]):
            wr("<f", out + 4 * i, v)
        return S_OK

    def close(self):
        self.meter.stop()


class MMEndpoint(_AudioObject):
    """IMMEndpoint::GetDataFlow (eRender 0, eCapture 1)."""

    def __init__(self, ep):
        super().__init__([(c_hr, [P], lambda o: _u(o, 0 if ep.kind == "sink" else 1))], (IID_IMMEndpoint,), ep)


class VolumeLevel(_AudioObject):
    """IAudioVolumeLevel / IPerChannelDbLevel (devicetopology.h): 3 GetChannelCount, 4 GetLevelRange,
    5 GetLevel, 6 SetLevel, 7 SetLevelUniform, 8 SetLevelAllChannels.  Levels are in dB."""

    def __init__(self, ep):
        u, f = ctypes.c_uint, ctypes.c_float
        super().__init__([
            (c_hr, [P], lambda o: _u(o, len(ep.channels()))),
            (c_hr, [u, P, P, P], self.level_range),
            (c_hr, [u, P], self.get_level),
            (c_hr, [u, f, P], self.set_level),
            (c_hr, [f, P], lambda db, g: ep.set_channels([db_to_scalar(db)] * len(ep.channels()))),
            (c_hr, [P, u, P], self.set_all),
        ], (IID_IAudioVolumeLevel, IID_IPerChannelDbLevel), ep)

    def level_range(self, ch, lo, hi, step):
        if ch >= len(self.ep.channels()):
            return E_INVALIDARG
        _f(lo, MIN_DB)
        _f(hi, MAX_DB)
        _f(step, STEP_DB)
        return S_OK

    def get_level(self, ch, out):
        cur = self.ep.channels()
        if ch >= len(cur):
            return E_INVALIDARG
        _f(out, scalar_to_db(cur[ch]))
        return S_OK

    def set_level(self, ch, db, g):
        cur = self.ep.channels()
        if ch >= len(cur):
            return E_INVALIDARG
        cur[ch] = db_to_scalar(db)
        self.ep.set_channels(cur)
        return S_OK

    def set_all(self, levels, n, g):
        cur = self.ep.channels()
        if n != len(cur) or not levels:
            return E_INVALIDARG
        self.ep.set_channels([db_to_scalar(rd("<f", levels + 4 * i)) for i in range(n)])
        return S_OK


class Mute(_AudioObject):
    """IAudioMute: 3 SetMute(BOOL, LPCGUID), 4 GetMute(BOOL*)."""

    def __init__(self, ep):
        super().__init__([
            (c_hr, [ctypes.c_int, P], lambda on, g: ep.set_mute(on)),
            (c_hr, [P], lambda o: _u(o, ep.muted())),
        ], (IID_IAudioMute,), ep)


DEVICE_IFACES = {IID_IAudioEndpointVolume: EndpointVolume, IID_IAudioMeterInformation: MeterInformation,
                 IID_IMMEndpoint: MMEndpoint}
COMPONENT_IFACES = {IID_IAudioVolumeLevel: VolumeLevel, IID_IPerChannelDbLevel: VolumeLevel, IID_IAudioMute: Mute}


def get_interface(iid: bytes, ep: Endpoint, component: bool) -> int:
    """The interface pointer (owned by the caller, released with ObjRelease), or 0 when the device or component
    doesn't support it (AutoHotkey returns the result even on failure, like ComObjQuery)."""
    cls = (COMPONENT_IFACES if component else DEVICE_IFACES).get(iid)
    if cls is None:
        return 0
    return cls(ep).ptr
