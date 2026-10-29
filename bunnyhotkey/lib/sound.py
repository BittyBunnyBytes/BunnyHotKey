"""SoundBeep / SoundPlay / SoundGet*/SoundSet* via PipeWire/PulseAudio tools."""
from __future__ import annotations

import math
import os
import shutil
import struct
import subprocess
import tempfile
import wave

from .. import objects as O
from ..objects import throw
from ..values import UNSET
from . import export
from .files import host_path


def S(v):
    return O.RT.to_str(v)


def _player():
    for p in ("pw-play", "paplay", "aplay"):
        if shutil.which(p):
            return p
    return None


@export()
def SoundBeep(freq=523, duration=150):
    f = O.RT.to_int(freq) if freq != "" else 523
    d = O.RT.to_int(duration) if duration != "" else 150
    rate = 44100
    n = int(rate * d / 1000)
    path = os.path.join(tempfile.gettempdir(), f"bhk-beep-{f}-{d}.wav")
    if not os.path.exists(path):
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * f * i / rate))) for i in range(n)))
    p = _player()
    if p:
        subprocess.run([p, path], capture_output=True)
    return ""


@export()
def SoundPlay(filename, wait=0):
    fn = S(filename)
    if fn.startswith("*"):
        return SoundBeep(880 if fn != "*16" else 440, 120)
    p = _player()
    if not p:
        return ""
    proc = subprocess.Popen([p, host_path(fn)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if O.RT.to_int(wait) if wait != "" else 0:
        while proc.poll() is None:
            O.RT.sleep(20)
    return ""


def _wpctl(*args):
    if shutil.which("wpctl"):
        return subprocess.run(["wpctl", *args], capture_output=True, text=True).stdout
    return ""


# ---------------------------------------------------------------- devices (PulseAudio/PipeWire through pactl)
# AutoHotkey numbers audio endpoints from 1 and matches names by substring ("Speakers", "Headphones:2").  Here the
# endpoints are the playback devices (sinks) followed by the recording devices (sources, without sink monitors).
def _pactl_json(*args):
    import json
    if not shutil.which("pactl"):
        return None
    r = subprocess.run(["pactl", "-f", "json", *args], capture_output=True, text=True)
    try:
        return json.loads(r.stdout) if r.returncode == 0 else None
    except ValueError:
        return None


def _devices():
    sinks = _pactl_json("list", "sinks")
    if sinks is None:
        return None
    sources = [x for x in (_pactl_json("list", "sources") or []) if not x.get("name", "").endswith(".monitor")]
    return [("sink", x) for x in sinks] + [("source", x) for x in sources]


def _device(device):
    """(kind, pactl device dict) for an AutoHotkey Device parameter; None when pactl isn't available."""
    devs = _devices()
    if devs is None:
        if device in (UNSET, "") or device is None:
            return None
        throw("TargetError", "Device not found.", S(device))
    if device in (UNSET, "") or device is None:
        default = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True).stdout.strip()
        return next((d for d in devs if d[1].get("name") == default), devs[0] if devs else None)
    if isinstance(device, int) or S(device).strip().isdigit():
        i = O.RT.to_int(device) - 1
        if 0 <= i < len(devs):
            return devs[i]
        throw("TargetError", "Device not found.", S(device))
    name, _, nth = S(device).rpartition(":") if ":" in S(device) and S(device).rsplit(":", 1)[1].isdigit() \
        else (S(device), "", "1")
    want = name.lower()
    hits = [d for d in devs if want in d[1].get("description", "").lower() or want in d[1].get("name", "").lower()]
    n = int(nth or 1)
    if 1 <= n <= len(hits):
        return hits[n - 1]
    throw("TargetError", "Device not found.", S(device))


def _component(component):
    c = S(component).strip().lower() if component not in (UNSET, None) else ""
    if c not in ("", "master", "speakers", "headphones", "line out", "microphone", "line in", "1"):
        throw("TargetError", "Component not found.", S(component))


def _percent(dev):
    vols = [int(str(v.get("value_percent", "0")).rstrip("%") or 0) for v in dev.get("volume", {}).values()]
    return sum(vols) / len(vols) if vols else 0.0


@export()
def SoundGetVolume(component="", device=""):
    _component(component)
    d = _device(device)
    if d is None:
        out = _wpctl("get-volume", "@DEFAULT_AUDIO_SINK@")
        try:
            return float(out.split()[1]) * 100
        except (IndexError, ValueError):
            return 0.0
    return float(_percent(d[1]))


@export()
def SoundSetVolume(percent, component="", device=""):
    _component(component)
    p = S(percent)
    if p.startswith(("+", "-")):
        val = max(0.0, min(100.0, SoundGetVolume(component, device) + float(p)))
    else:
        val = max(0.0, min(100.0, float(p)))
    d = _device(device)
    if d is None:
        _wpctl("set-volume", "@DEFAULT_AUDIO_SINK@", f"{val / 100:.3f}")
    else:
        subprocess.run(["pactl", f"set-{d[0]}-volume", d[1]["name"], f"{round(val)}%"], capture_output=True)
    return ""


@export()
def SoundGetMute(component="", device=""):
    _component(component)
    d = _device(device)
    if d is None:
        return int("MUTED" in _wpctl("get-volume", "@DEFAULT_AUDIO_SINK@"))
    return int(bool(d[1].get("mute")))


@export()
def SoundSetMute(state, component="", device=""):
    _component(component)
    v = O.RT.to_int(state)
    d = _device(device)
    arg = "toggle" if v == -1 else str(int(bool(v)))
    if d is None:
        _wpctl("set-mute", "@DEFAULT_AUDIO_SINK@", arg)
    else:
        subprocess.run(["pactl", f"set-{d[0]}-mute", d[1]["name"], arg], capture_output=True)
    return ""


@export()
def SoundGetName(component="", device=""):
    """The device's name, or the component's when one is given (SoundGetName(Component, Device))."""
    if component not in (UNSET, "", None):
        _component(component)
        return "Master" if S(component).lower() in ("master", "1") else S(component).title()
    d = _device(device)
    if d is None:
        out = _wpctl("inspect", "@DEFAULT_AUDIO_SINK@")
        for line in out.splitlines():
            if "node.description" in line:
                return line.split("=", 1)[1].strip().strip('"')
        return ""
    return d[1].get("description") or d[1].get("name", "")


@export()
def SoundGetInterface(iid, component="", device=""):
    """A Core Audio interface of the device (Component omitted) or of its master component (IAudioVolumeLevel,
    IAudioMute), implemented over PulseAudio/PipeWire (coreaudio.py).  Returns the pointer, or 0 if unsupported."""
    from . import coreaudio
    from .comnative import guid_bytes
    i = S(iid).strip()
    try:
        if not i.startswith("{"):
            raise ValueError
        g = guid_bytes(i)
    except ValueError:
        throw("ValueError", "Parameter #1 of SoundGetInterface is invalid.", i)
    has_component = component not in (UNSET, "", None)
    if has_component:
        _component(component)
    d = _device(device)
    if d is None:
        throw("TargetError", "Device not found.", S(device) if device not in (UNSET, None) else "")
    return coreaudio.get_interface(g, coreaudio.Endpoint(d[0], d[1]), has_component)
