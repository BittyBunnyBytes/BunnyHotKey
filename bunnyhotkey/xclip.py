"""X11 clipboard owner/reader (used when xclip/xsel are not installed)."""
from __future__ import annotations

import ctypes
import sys
import time

from . import xlib


def read_clipboard(timeout=1.0) -> str:
    d = xlib.Display()
    x = d.x
    try:
        win = x.XCreateSimpleWindow(d.dpy, d.root, 0, 0, 1, 1, 0, 0, 0)
        sel = d.atom("CLIPBOARD")
        utf8 = d.atom("UTF8_STRING")
        prop = d.atom("BHK_CLIP")
        if not x.XGetSelectionOwner(d.dpy, sel):
            return ""
        x.XConvertSelection(d.dpy, sel, utf8, prop, win, 0)
        x.XFlush(d.dpy)
        ev = xlib.XEvent()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            while x.XPending(d.dpy):
                x.XNextEvent(d.dpy, ctypes.byref(ev))
                if ev.type == xlib.SelectionNotify:
                    if ev.xselection.property == 0:
                        return ""
                    r = d.get_prop(win, prop, max_len=1 << 24)
                    return r[2].decode("utf-8", "replace") if r else ""
            time.sleep(0.005)
        return ""
    finally:
        x.XCloseDisplay(d.dpy)


def own(text: bytes):
    d = xlib.Display()
    x = d.x
    win = x.XCreateSimpleWindow(d.dpy, d.root, 0, 0, 1, 1, 0, 0, 0)
    sel = d.atom("CLIPBOARD")
    targets = d.atom("TARGETS")
    utf8 = d.atom("UTF8_STRING")
    atoms = [targets, utf8, xlib.XA_STRING, d.atom("TEXT"), d.atom("text/plain;charset=utf-8")]
    x.XSetSelectionOwner(d.dpy, sel, win, 0)
    x.XFlush(d.dpy)
    ev = xlib.XEvent()
    while True:
        x.XNextEvent(d.dpy, ctypes.byref(ev))
        if ev.type == xlib.SelectionClear:
            return
        if ev.type == xlib.SelectionRequest:
            req = ev.xselectionrequest
            reply = xlib.XEvent()
            reply.xselection.type = xlib.SelectionNotify
            reply.xselection.requestor = req.requestor
            reply.xselection.selection = req.selection
            reply.xselection.target = req.target
            reply.xselection.time = req.time
            prop = req.property or req.target
            if req.target == targets:
                arr = (ctypes.c_ulong * len(atoms))(*atoms)
                x.XChangeProperty(d.dpy, req.requestor, prop, xlib.XA_ATOM, 32, 0, arr, len(atoms))
                reply.xselection.property = prop
            elif req.target in atoms:
                data = text if req.target != xlib.XA_STRING else text.decode("utf-8").encode("latin-1", "replace")
                x.XChangeProperty(d.dpy, req.requestor, prop, req.target, 8, 0, data, len(data))
                reply.xselection.property = prop
            else:
                reply.xselection.property = 0
            x.XSendEvent(d.dpy, req.requestor, 0, 0, ctypes.byref(reply))
            x.XFlush(d.dpy)


if __name__ == "__main__" and "--own" in sys.argv:
    own(sys.stdin.buffer.read())
