"""SoundGetInterface: IAudioEndpointVolume, IAudioMeterInformation and IAudioMute over PulseAudio/PipeWire, called
with ComCall.  The script sets the default sink to 30% and back; this test also saves and restores the volume
and mute itself, in case the script stops halfway.  Skipped without pactl or a sound server.

Run: python3 tests/test_coreaudio.py
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PATTERNS = [
    r"ptr 1",
    r"scalar ([\d.]+) vs \1",
    r"channels [1-9]\d*",
    r"mute ([01]) vs \1",
    r"range -65\.25 0\.0 0\.03125",
    r"db -?[\d.]+",
    r"set30 -> 30",
    r"restored [\d.]+",
    r"bad \(0x80070057\) The parameter is incorrect\.",
    r"release 0",
    r"peak ok 1",
    r"unknown 0",
    r"comp mute [01]",
    r"verr Parameter #1 of SoundGetInterface is invalid\.",
]


def pactl(*args):
    return subprocess.run(["pactl", *args], capture_output=True, text=True)


def main():
    if not shutil.which("pactl") or pactl("info").returncode != 0:
        print("SKIP coreaudio: no pactl / sound server")
        return 0
    vol = re.findall(r"(\d+)%", pactl("get-sink-volume", "@DEFAULT_SINK@").stdout)
    mute = "yes" in pactl("get-sink-mute", "@DEFAULT_SINK@").stdout
    try:
        r = subprocess.run([sys.executable, "-m", "bunnyhotkey", "--console", "--backend=null",
                            os.path.join(HERE, "coreaudio", "snd.ahk")],
                           cwd=ROOT, capture_output=True, text=True, timeout=60)
    finally:
        if vol:
            pactl("set-sink-volume", "@DEFAULT_SINK@", *[v + "%" for v in vol])
        pactl("set-sink-mute", "@DEFAULT_SINK@", "1" if mute else "0")
    lines = (r.stdout + r.stderr).splitlines()
    bad = [(i, w, g) for i, (w, g) in enumerate(zip(PATTERNS, lines + [""] * len(PATTERNS)))
           if not re.fullmatch(w, g)]
    if len(lines) != len(PATTERNS):
        bad.append((len(lines), f"{len(PATTERNS)} lines", f"{len(lines)} lines"))
    restored = re.search(r"restored ([\d.]+)", r.stdout)
    if vol and restored and round(float(restored.group(1)) * 100) != int(vol[0]):
        bad.append(("restore", vol[0] + "%", restored.group(1)))
    if bad:
        print("FAIL coreaudio:")
        for i, w, g in bad:
            print(f"  line {i}: got {g!r} want /{w}/")
        return 1
    print("PASS coreaudio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
