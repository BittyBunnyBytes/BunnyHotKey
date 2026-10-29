"""Live X11 input tests: real grabs, XTest input, the modifier map and the script's own Gui.  They act on the
running desktop (keys no application reacts to, and a BHK window), so they aren't part of tests/run.py.
Run: python3 tests/run_live.py"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXPECT = {
    "x11_hotkey.ahk": "hotkey fired: F24",
    "x11_sendlevel.ahk": "F23 | F24 F22 | F21",
    "x11_bare_modifier.ahk": "RCtrl F24",
    "x11_hotstring_endchar.ahk": "button saw: by the way",
}


def main():
    if not os.environ.get("DISPLAY"):
        print("skipped: no DISPLAY")
        return 0
    failed = 0
    for name, want in EXPECT.items():
        r = subprocess.run([sys.executable, "-m", "bunnyhotkey", "--console", os.path.join(HERE, "live", name)],
                           cwd=ROOT, capture_output=True, text=True, timeout=30)
        got = (r.stdout + r.stderr).strip()
        print(("PASS " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r} want {want!r}"))
        failed += got != want
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
