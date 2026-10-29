"""Live X11 input tests: real grabs, XTest input, the modifier map, AT-SPI and the script's own Gui.  They act on
the running desktop (keys no application reacts to, a BHK window and a small test GTK app that briefly takes
keyboard focus), so they aren't part of tests/run.py.  Don't type while they run.
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
    "x11_bare_modifier_hotif.ahk": "RCtrl F24 | ^F24",
    "x11_hotstring_endchar.ahk": "button saw: by the way",
}


def main():
    if not os.environ.get("DISPLAY"):
        print("skipped: no DISPLAY")
        return 0
    failed = 0
    # another program's controls through AT-SPI: a plain GTK app stands in for "some other application"
    app = subprocess.Popen([sys.executable, os.path.join(HERE, "live", "foreign_app.py")], cwd=ROOT,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import time
        time.sleep(1.5)
        r = subprocess.run([sys.executable, "-m", "bunnyhotkey", "--console",
                            os.path.join(HERE, "live", "x11_foreign_controls.ahk")],
                           cwd=ROOT, capture_output=True, text=True, timeout=60)
        want = open(os.path.join(HERE, "live", "x11_foreign_controls.expected")).read()
        ok = r.stdout + r.stderr == want
        print(("PASS " if ok else "FAIL ") + "x11_foreign_controls.ahk" + ("" if ok else ":\n" + r.stdout + r.stderr))
        failed += not ok
    finally:
        app.terminate()
    # a "*" hotstring's final character must never reach the app: the app logs every change of its entry
    import tempfile
    import time
    log = os.path.join(tempfile.mkdtemp(), "entry.log")
    app = subprocess.Popen([sys.executable, os.path.join(HERE, "live", "foreign_app.py")], cwd=ROOT,
                           env=dict(os.environ, BHK_FOREIGN_LOG=log), stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.5)
        r = subprocess.run([sys.executable, "-m", "bunnyhotkey", "--console",
                            os.path.join(HERE, "live", "x11_hotstring_star.ahk")],
                           cwd=ROOT, capture_output=True, text=True, timeout=60)
        seen = open(log).read().split("\n") if os.path.exists(log) else []
        ok = (r.stdout + r.stderr).strip() == "bunny" and "zqx" not in seen
        print(("PASS " if ok else "FAIL ") + "x11_hotstring_star.ahk" +
              ("" if ok else f": got {(r.stdout + r.stderr).strip()!r}, app saw {seen!r}"))
        failed += not ok
    finally:
        app.terminate()
    for name, want in EXPECT.items():
        r = subprocess.run([sys.executable, "-m", "bunnyhotkey", "--console", os.path.join(HERE, "live", name)],
                           cwd=ROOT, capture_output=True, text=True, timeout=30)
        got = (r.stdout + r.stderr).strip()
        print(("PASS " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r} want {want!r}"))
        failed += got != want
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
