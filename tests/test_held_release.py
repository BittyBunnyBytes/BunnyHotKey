"""A script that dies holding a key must not leave it down: SIGTERM, a SIGTERM it can't act on, SIGKILL, ExitApp.

Holds F23 on the real X display, which nothing binds.  Skipped without a display.
Run: python3 tests/test_held_release.py
"""
import ctypes
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if not os.environ.get("DISPLAY"):
    print("SKIP test_held_release: no DISPLAY")
    sys.exit(0)

from bunnyhotkey import keys as K, xlib  # noqa: E402

KEYCODE = K.lookup("F23").code + 8
d = xlib.Display()
failures = 0


def down():
    buf = ctypes.create_string_buffer(32)
    d.x.XQueryKeymap(d.dpy, buf)
    return bool(buf.raw[KEYCODE >> 3] & (1 << (KEYCODE & 7)))


def wait_for(cond, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def check(name, ok):
    global failures
    print(("PASS " if ok else "FAIL ") + name)
    failures += not ok


def release_f23():
    t = xlib.Xtst()
    t.XTestFakeKeyEvent(d.dpy, KEYCODE, 0, 0)
    d.x.XSync(d.dpy, 0)


def scenario(name, body, sig, exit_within, up_within, on_exit_file=None):
    path = os.path.join(tmp, name + ".ahk")
    with open(path, "w") as fh:
        fh.write(body)
    p = subprocess.Popen([sys.executable, "-m", "bunnyhotkey", "--console", "--no-tray", path], cwd=ROOT,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        check(name + ": key goes down", wait_for(down, 5))
        if sig is not None:
            p.send_signal(sig)
        check(name + ": key released", wait_for(lambda: not down(), up_within))
        try:
            p.wait(exit_within)
            exited = True
        except subprocess.TimeoutExpired:
            exited = False
        check(name + ": script exited", exited)
        if on_exit_file:
            check(name + ": OnExit ran", os.path.exists(on_exit_file))
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        release_f23()


tmp = tempfile.mkdtemp(prefix="bhk-held-")
try:
    marker = os.path.join(tmp, "onexit")
    scenario("sigterm", 'OnExit((*) => FileAppend("x", "%s"))\nSend "{F23 down}"\nPersistent\n' % marker,
             signal.SIGTERM, 3, 1, marker)
    scenario("sigterm-critical", 'Critical\nSend "{F23 down}"\nLoop\n    Sleep 50\n', signal.SIGTERM, 5, 1)
    scenario("sigkill", 'Send "{F23 down}"\nPersistent\n', signal.SIGKILL, 3, 2)
    scenario("exitapp", 'Send "{F23 down}"\nSleep 400\nExitApp\n', None, 3, 3)
finally:
    shutil.rmtree(tmp, True)
    release_f23()
sys.exit(1 if failures else 0)
