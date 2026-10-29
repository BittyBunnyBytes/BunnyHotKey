"""Live test: SendMessage to another program's controls through AT-SPI.  Starts tests/live/foreign_app.py with its
extra controls (mapped without taking focus) and runs x11_foreign_messages.ahk against it.  No keyboard input, so
it is safe to run while working, but it isn't in run_live.py's default list.
Run: python3 tests/live/run_foreign_messages.py"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def main():
    if not os.environ.get("DISPLAY"):
        print("skipped: no DISPLAY")
        return 0
    app = subprocess.Popen([sys.executable, os.path.join(HERE, "foreign_app.py")], cwd=ROOT,
                           env=dict(os.environ, BHK_FOREIGN_EXTRA="1"),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.5)
        r = subprocess.run([sys.executable, "-m", "bunnyhotkey", "--console",
                            os.path.join(HERE, "x11_foreign_messages.ahk")],
                           cwd=ROOT, capture_output=True, text=True, timeout=90)
    finally:
        app.terminate()
    got = r.stdout + r.stderr
    want = open(os.path.join(HERE, "x11_foreign_messages.expected")).read()
    if got == want:
        print("PASS x11_foreign_messages.ahk")
        return 0
    print("FAIL x11_foreign_messages.ahk")
    for i, (g, w) in enumerate(zip(got.splitlines() + [""] * 99, want.splitlines())):
        if g != w:
            print(f"  line {i + 1}: got {g!r} want {w!r}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
