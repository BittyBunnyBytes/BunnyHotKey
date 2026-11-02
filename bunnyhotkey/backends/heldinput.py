"""A watcher process that lets go of the keys and buttons a script is holding if the script dies without cleaning up.

The X server keeps XTest presses down after the client that made them is gone, and nothing inside a process can run
after SIGKILL or a hard crash.  The script reports each press and release over a pipe; when the pipe closes without a
"done", the script is gone and the watcher releases whatever is still held.  The watcher's code is inline and its
libraries are loaded before it waits, so it still works if BHK's folder is moved or deleted while the script runs, and
its command line doesn't name BHK, so tools that stop BHK's scripts leave it to finish its job.
"""
from __future__ import annotations

import os
import subprocess
import sys

from .. import xlib

_CODE = """
import ctypes, os, signal, sys
for s in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
    signal.signal(s, signal.SIG_IGN)      # only the end of the script may end this process
x, t = ctypes.CDLL(sys.argv[1]), ctypes.CDLL(sys.argv[2])
vp, ul, cu, ci = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_uint, ctypes.c_int
x.XOpenDisplay.restype = vp
x.XOpenDisplay.argtypes = [ctypes.c_char_p]
x.XSync.argtypes = [vp, ci]
x.XCloseDisplay.argtypes = [vp]
t.XTestFakeKeyEvent.argtypes = [vp, cu, ci, ul]
t.XTestFakeButtonEvent.argtypes = [vp, cu, ci, ul]
held, buf = set(), b""
while True:
    data = os.read(0, 4096)
    if not data:
        break
    buf += data
    lines = buf.split(b"\\n")
    buf = lines.pop()
    for line in lines:
        if line == b"done":
            os._exit(0)
        if line == b"clear":
            held.clear()
        elif len(line) > 2:
            item = (line[:1], int(line[1:-1]))
            (held.add if line[-1:] == b"+" else held.discard)(item)
if held:
    d = x.XOpenDisplay(None)
    if d:
        for kind, n in held:
            (t.XTestFakeKeyEvent if kind == b"k" else t.XTestFakeButtonEvent)(d, n, 0, 0)
        x.XSync(d, 0)
        x.XCloseDisplay(d)
"""


class HeldInputWatcher:
    def __init__(self, display):
        self.fd = None
        self.proc = None
        try:
            libs = [display.x._name, xlib.Xtst()._name]
            self.proc = subprocess.Popen([sys.executable, "-I", "-S", "-c", _CODE, *libs], stdin=subprocess.PIPE,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         start_new_session=True)     # outlives a kill of the script's process group
            self.fd = self.proc.stdin.fileno()
            os.set_blocking(self.fd, False)                          # a stalled watcher must never stall input
        except (OSError, AttributeError):
            self.fd = None

    def _say(self, text):
        if self.fd is not None:
            try:
                os.write(self.fd, text)        # shorter than PIPE_BUF, so each line arrives whole
            except OSError:
                pass

    def key(self, keycode, down):
        self._say(b"k%d%c\n" % (keycode, 43 if down else 45))

    def button(self, btn, down):
        self._say(b"b%d%c\n" % (btn, 43 if down else 45))

    def clear(self):
        self._say(b"clear\n")

    def done(self):
        self._say(b"done\n")
        self.fd = None
        if self.proc is not None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(1)              # reap it; "done" makes it exit right away
            except subprocess.TimeoutExpired:
                pass
            self.proc = None
