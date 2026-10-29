#!/usr/bin/env python3
"""Find a script's tray icon on the X11 desktop (for tests/conformance/v2_tray.ahk).

    python3 tools/x11_tray_probe.py PID

Looks for a viewable window reparented into another client (a system tray embeds its icons) whose
_NET_WM_PID is PID or a child process of PID (BHK's Gui helper owns the icon).  Prints "x y" (screen
centre of the icon) and exits 0 if found, exits 1 if not.
"""
import ctypes
import sys

x = ctypes.CDLL("libX11.so.6")
x.XOpenDisplay.restype = ctypes.c_void_p
x.XDefaultRootWindow.restype = ctypes.c_ulong
x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
x.XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                         ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
                         ctypes.POINTER(ctypes.c_uint)]
x.XFetchName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_char_p)]
x.XFree.argtypes = [ctypes.c_void_p]
x.XInternAtom.restype = ctypes.c_ulong
x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
x.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long,
                                 ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                 ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
                                 ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]


def wm_pid(d, w):
    atom = x.XInternAtom(d, b"_NET_WM_PID", 0)
    t, f, n, rest, data = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
    if x.XGetWindowProperty(d, w, atom, 0, 1, 0, 0, ctypes.byref(t), ctypes.byref(f), ctypes.byref(n),
                            ctypes.byref(rest), ctypes.byref(data)) != 0 or not data.value:
        return 0
    v = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[0] if n.value else 0
    x.XFree(data)
    return v


def parent_pid(pid):
    try:
        with open(f"/proc/{pid}/stat") as fh:
            st = fh.read()
        return int(st[st.rfind(")") + 2:].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


class XWindowAttributes(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("border_width", ctypes.c_int), ("depth", ctypes.c_int), ("visual", ctypes.c_void_p),
                ("root", ctypes.c_ulong), ("class", ctypes.c_int), ("bit_gravity", ctypes.c_int),
                ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int), ("backing_planes", ctypes.c_ulong),
                ("backing_pixel", ctypes.c_ulong), ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong),
                ("map_installed", ctypes.c_int), ("map_state", ctypes.c_int), ("all_event_masks", ctypes.c_long),
                ("your_event_mask", ctypes.c_long), ("do_not_propagate_mask", ctypes.c_long),
                ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p)]


x.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XWindowAttributes)]
x.XTranslateCoordinates.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                                    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                    ctypes.POINTER(ctypes.c_ulong)]


def find(d, root, pid):
    stack = [(root, 0)]
    while stack:
        w, depth = stack.pop()
        r, p, n = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_uint()
        ch = ctypes.POINTER(ctypes.c_ulong)()
        if not x.XQueryTree(d, w, ctypes.byref(r), ctypes.byref(p), ctypes.byref(ch), ctypes.byref(n)):
            continue
        kids = [ch[i] for i in range(n.value)]
        if ch:
            x.XFree(ch)
        for c in kids:
            owner = wm_pid(d, c) if depth >= 1 else 0
            if owner and (owner == pid or parent_pid(owner) == pid):
                a = XWindowAttributes()
                x.XGetWindowAttributes(d, c, ctypes.byref(a))
                if a.map_state == 2 and a.width > 0:          # IsViewable
                    sx, sy, child = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
                    x.XTranslateCoordinates(d, c, root, a.width // 2, a.height // 2,
                                            ctypes.byref(sx), ctypes.byref(sy), ctypes.byref(child))
                    return sx.value, sy.value
            stack.append((c, depth + 1))
    return None


if __name__ == "__main__":
    d = x.XOpenDisplay(None)
    if not d or len(sys.argv) < 2:
        sys.exit(2)
    pos = find(d, x.XDefaultRootWindow(d), int(sys.argv[1]))
    if pos is None:
        sys.exit(1)
    print(*pos)
