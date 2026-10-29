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


@export()
def SoundGetVolume(component="", device=""):
    out = _wpctl("get-volume", "@DEFAULT_AUDIO_SINK@")
    try:
        return float(out.split()[1]) * 100
    except (IndexError, ValueError):
        return 0.0


@export()
def SoundSetVolume(percent, component="", device=""):
    p = S(percent)
    if p.startswith(("+", "-")):
        cur = SoundGetVolume()
        val = max(0.0, min(100.0, cur + float(p)))
    else:
        val = max(0.0, min(100.0, float(p)))
    _wpctl("set-volume", "@DEFAULT_AUDIO_SINK@", f"{val / 100:.3f}")
    return ""


@export()
def SoundGetMute(component="", device=""):
    return int("MUTED" in _wpctl("get-volume", "@DEFAULT_AUDIO_SINK@"))


@export()
def SoundSetMute(state, component="", device=""):
    v = O.RT.to_int(state)
    _wpctl("set-mute", "@DEFAULT_AUDIO_SINK@", "toggle" if v == -1 else str(v))
    return ""


@export()
def SoundGetName(component="", device=""):
    return "Speakers"


@export()
def SoundGetInterface(*a):
    return 0
