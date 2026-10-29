"""Minimal ctypes bindings for Xlib / XTest / XInput2 (no third-party modules needed)."""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import threading

c_ulong = ctypes.c_ulong
c_long = ctypes.c_long
c_int = ctypes.c_int
c_uint = ctypes.c_uint
c_char_p = ctypes.c_char_p
c_void_p = ctypes.c_void_p
POINTER = ctypes.POINTER
byref = ctypes.byref

Window = c_ulong
Atom = c_ulong
Time = c_ulong

KeyPress, KeyRelease, ButtonPress, ButtonRelease, MotionNotify = 2, 3, 4, 5, 6
DestroyNotify, UnmapNotify, MapNotify, PropertyNotify = 17, 18, 19, 28
SelectionClear, SelectionRequest, SelectionNotify, ClientMessage, GenericEvent = 29, 30, 31, 33, 35
KeyPressMask, KeyReleaseMask, ButtonPressMask, ButtonReleaseMask = 1, 2, 4, 8
PropertyChangeMask, SubstructureNotifyMask, SubstructureRedirectMask = 1 << 22, 1 << 19, 1 << 20
ShiftMask, LockMask, ControlMask, Mod1Mask, Mod2Mask, Mod3Mask, Mod4Mask, Mod5Mask = 1, 2, 4, 8, 16, 32, 64, 128
AnyModifier = 1 << 15
GrabModeSync, GrabModeAsync = 0, 1
AsyncPointer, SyncPointer, ReplayPointer, AsyncKeyboard, SyncKeyboard, ReplayKeyboard = 0, 1, 2, 3, 4, 5
CurrentTime = 0
PropModeReplace = 0
AnyPropertyType = 0
XA_ATOM, XA_CARDINAL, XA_STRING, XA_WINDOW = 4, 6, 31, 33
ZPixmap = 2
XI_RawKeyPress, XI_RawKeyRelease, XI_RawButtonPress, XI_RawButtonRelease, XI_RawMotion = 13, 14, 15, 16, 17
XIAllMasterDevices = 1
XIAllDevices = 0


class XKeyEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p),
                ("window", Window), ("root", Window), ("subwindow", Window), ("time", Time), ("x", c_int),
                ("y", c_int), ("x_root", c_int), ("y_root", c_int), ("state", c_uint), ("keycode", c_uint),
                ("same_screen", c_int)]


XButtonEvent = XKeyEvent   # same layout; keycode == button


class XSelectionRequestEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p),
                ("owner", Window), ("requestor", Window), ("selection", Atom), ("target", Atom),
                ("property", Atom), ("time", Time)]


class XSelectionEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p),
                ("requestor", Window), ("selection", Atom), ("target", Atom), ("property", Atom), ("time", Time)]


class XClientMessageEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p),
                ("window", Window), ("message_type", Atom), ("format", c_int), ("data", c_long * 5)]


class XGenericEventCookie(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p),
                ("extension", c_int), ("evtype", c_int), ("cookie", c_uint), ("data", c_void_p)]


class XEvent(ctypes.Union):
    _fields_ = [("type", c_int), ("xkey", XKeyEvent), ("xbutton", XButtonEvent),
                ("xselectionrequest", XSelectionRequestEvent), ("xselection", XSelectionEvent),
                ("xclient", XClientMessageEvent), ("xcookie", XGenericEventCookie), ("pad", c_long * 24)]


class XIRawEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p),
                ("extension", c_int), ("evtype", c_int), ("time", Time), ("deviceid", c_int), ("sourceid", c_int),
                ("detail", c_int), ("flags", c_int)]


class XIEventMask(ctypes.Structure):
    _fields_ = [("deviceid", c_int), ("mask_len", c_int), ("mask", POINTER(ctypes.c_ubyte))]


class XImage(ctypes.Structure):
    _fields_ = [("width", c_int), ("height", c_int), ("xoffset", c_int), ("format", c_int), ("data", c_void_p),
                ("byte_order", c_int), ("bitmap_unit", c_int), ("bitmap_bit_order", c_int), ("bitmap_pad", c_int),
                ("depth", c_int), ("bytes_per_line", c_int), ("bits_per_pixel", c_int)]


class XWindowAttributes(ctypes.Structure):
    _fields_ = [("x", c_int), ("y", c_int), ("width", c_int), ("height", c_int), ("border_width", c_int),
                ("depth", c_int), ("visual", c_void_p), ("root", Window), ("class_", c_int),
                ("bit_gravity", c_int), ("win_gravity", c_int), ("backing_store", c_int),
                ("backing_planes", c_ulong), ("backing_pixel", c_ulong), ("save_under", c_int),
                ("colormap", c_ulong), ("map_installed", c_int), ("map_state", c_int),
                ("all_event_masks", c_long), ("your_event_mask", c_long), ("do_not_propagate_mask", c_long),
                ("override_redirect", c_int), ("screen", c_void_p)]


_libs = {}


def _lib(name):
    if name not in _libs:
        path = ctypes.util.find_library(name)
        _libs[name] = ctypes.CDLL(path) if path else None
    return _libs[name]


def available() -> bool:
    return bool(os.environ.get("DISPLAY")) and _lib("X11") is not None


_ERR_HANDLER = None


def _setup(x):
    global _ERR_HANDLER
    x.XOpenDisplay.restype = c_void_p
    x.XOpenDisplay.argtypes = [c_char_p]
    for fn, res, args in (
        ("XDefaultRootWindow", Window, [c_void_p]),
        ("XInternAtom", Atom, [c_void_p, c_char_p, c_int]),
        ("XGetAtomName", c_void_p, [c_void_p, Atom]),
        ("XGetWindowProperty", c_int, [c_void_p, Window, Atom, c_long, c_long, c_int, Atom, POINTER(Atom),
                                       POINTER(c_int), POINTER(c_ulong), POINTER(c_ulong), POINTER(c_void_p)]),
        ("XFree", c_int, [c_void_p]),
        ("XFlush", c_int, [c_void_p]),
        ("XSync", c_int, [c_void_p, c_int]),
        ("XPending", c_int, [c_void_p]),
        ("XNextEvent", c_int, [c_void_p, POINTER(XEvent)]),
        ("XConnectionNumber", c_int, [c_void_p]),
        ("XQueryPointer", c_int, [c_void_p, Window, POINTER(Window), POINTER(Window), POINTER(c_int), POINTER(c_int),
                                  POINTER(c_int), POINTER(c_int), POINTER(c_uint)]),
        ("XWarpPointer", c_int, [c_void_p, Window, Window, c_int, c_int, c_uint, c_uint, c_int, c_int]),
        ("XGetGeometry", c_int, [c_void_p, Window, POINTER(Window), POINTER(c_int), POINTER(c_int), POINTER(c_uint),
                                 POINTER(c_uint), POINTER(c_uint), POINTER(c_uint)]),
        ("XTranslateCoordinates", c_int, [c_void_p, Window, Window, c_int, c_int, POINTER(c_int), POINTER(c_int),
                                          POINTER(Window)]),
        ("XGetWindowAttributes", c_int, [c_void_p, Window, POINTER(XWindowAttributes)]),
        ("XGetImage", POINTER(XImage), [c_void_p, Window, c_int, c_int, c_uint, c_uint, c_ulong, c_int]),
        ("XGetPixel", c_ulong, [POINTER(XImage), c_int, c_int]),
        ("XDestroyImage", c_int, [POINTER(XImage)]),
        ("XSendEvent", c_int, [c_void_p, Window, c_int, c_long, POINTER(XEvent)]),
        ("XMapRaised", c_int, [c_void_p, Window]),
        ("XMapWindow", c_int, [c_void_p, Window]),
        ("XUnmapWindow", c_int, [c_void_p, Window]),
        ("XRaiseWindow", c_int, [c_void_p, Window]),
        ("XClearArea", c_int, [c_void_p, Window, c_int, c_int, c_uint, c_uint, c_int]),
        ("XIconifyWindow", c_int, [c_void_p, Window, c_int]),
        ("XKillClient", c_int, [c_void_p, c_ulong]),
        ("XMoveResizeWindow", c_int, [c_void_p, Window, c_int, c_int, c_uint, c_uint]),
        ("XMoveWindow", c_int, [c_void_p, Window, c_int, c_int]),
        ("XResizeWindow", c_int, [c_void_p, Window, c_uint, c_uint]),
        ("XGrabKey", c_int, [c_void_p, c_int, c_uint, Window, c_int, c_int, c_int]),
        ("XUngrabKey", c_int, [c_void_p, c_int, c_uint, Window]),
        ("XGrabButton", c_int, [c_void_p, c_uint, c_uint, Window, c_int, c_uint, c_int, c_int, Window, c_ulong]),
        ("XUngrabButton", c_int, [c_void_p, c_uint, c_uint, Window]),
        ("XGrabKeyboard", c_int, [c_void_p, Window, c_int, c_int, c_int, Time]),
        ("XUngrabKeyboard", c_int, [c_void_p, Time]),
        ("XAllowEvents", c_int, [c_void_p, c_int, Time]),
        ("XSelectInput", c_int, [c_void_p, Window, c_long]),
        ("XCreateSimpleWindow", Window, [c_void_p, Window, c_int, c_int, c_uint, c_uint, c_uint, c_ulong, c_ulong]),
        ("XDestroyWindow", c_int, [c_void_p, Window]),
        ("XSetSelectionOwner", c_int, [c_void_p, Atom, Window, Time]),
        ("XGetSelectionOwner", Window, [c_void_p, Atom]),
        ("XConvertSelection", c_int, [c_void_p, Atom, Atom, Atom, Window, Time]),
        ("XChangeProperty", c_int, [c_void_p, Window, Atom, Atom, c_int, c_int, c_void_p, c_int]),
        ("XDeleteProperty", c_int, [c_void_p, Window, Atom]),
        ("XKeysymToKeycode", ctypes.c_ubyte, [c_void_p, c_ulong]),
        ("XStringToKeysym", c_ulong, [c_char_p]),
        ("XKeysymToString", c_char_p, [c_ulong]),
        ("XGetKeyboardMapping", POINTER(c_ulong), [c_void_p, ctypes.c_ubyte, c_int, POINTER(c_int)]),
        ("XChangeKeyboardMapping", c_int, [c_void_p, c_int, c_int, POINTER(c_ulong), c_int]),
        ("XDisplayKeycodes", c_int, [c_void_p, POINTER(c_int), POINTER(c_int)]),
        ("XQueryKeymap", c_int, [c_void_p, ctypes.c_char * 32]),
        ("XDefaultScreen", c_int, [c_void_p]),
        ("XDisplayWidthMM", c_int, [c_void_p, c_int]),
        ("XDisplayWidth", c_int, [c_void_p, c_int]),
        ("XDisplayHeight", c_int, [c_void_p, c_int]),
        ("XQueryTree", c_int, [c_void_p, Window, POINTER(Window), POINTER(Window), POINTER(POINTER(Window)), POINTER(c_uint)]),
        ("XGetInputFocus", c_int, [c_void_p, POINTER(Window), POINTER(c_int)]),
        ("XSetInputFocus", c_int, [c_void_p, Window, c_int, Time]),
        ("XStoreName", c_int, [c_void_p, Window, c_char_p]),
        ("XBell", c_int, [c_void_p, c_int]),
        ("XGetEventData", c_int, [c_void_p, POINTER(XGenericEventCookie)]),
        ("XFreeEventData", None, [c_void_p, POINTER(XGenericEventCookie)]),
        ("XQueryExtension", c_int, [c_void_p, c_char_p, POINTER(c_int), POINTER(c_int), POINTER(c_int)]),
        ("XInitThreads", c_int, []),
        ("XCloseDisplay", c_int, [c_void_p]),
        ("XkbKeycodeToKeysym", c_ulong, [c_void_p, ctypes.c_ubyte, c_int, c_int]),
    ):
        f = getattr(x, fn, None)
        if f is not None:
            f.restype = res
            f.argtypes = args
    handler_t = ctypes.CFUNCTYPE(c_int, c_void_p, c_void_p)
    _ERR_HANDLER = handler_t(lambda d, e: 0)       # ignore BadWindow etc. like xdotool does
    x.XSetErrorHandler.argtypes = [handler_t]
    x.XSetErrorHandler(_ERR_HANDLER)
    x.XInitThreads()


_X = None


def X():
    global _X
    if _X is None:
        x = _lib("X11")
        if x is None:
            raise OSError("libX11 not found")
        _setup(x)
        _X = x
    return _X


def Xtst():
    t = _lib("Xtst")
    if t is not None and not getattr(t, "_bhk_setup", False):
        t.XTestFakeKeyEvent.argtypes = [c_void_p, c_uint, c_int, c_ulong]
        t.XTestFakeButtonEvent.argtypes = [c_void_p, c_uint, c_int, c_ulong]
        t.XTestFakeMotionEvent.argtypes = [c_void_p, c_int, c_int, c_int, c_ulong]
        t.XTestFakeRelativeMotionEvent.argtypes = [c_void_p, c_int, c_int, c_ulong]
        t._bhk_setup = True
    return t


def Xi():
    t = _lib("Xi")
    if t is not None and not getattr(t, "_bhk_setup", False):
        t.XISelectEvents.argtypes = [c_void_p, Window, POINTER(XIEventMask), c_int]
        t._bhk_setup = True
    return t


class Display:
    """One X connection (Xlib is not thread-safe per connection; each thread opens its own)."""

    def __init__(self):
        x = X()
        self.x = x
        self.dpy = x.XOpenDisplay(None)
        if not self.dpy:
            raise OSError("cannot open X display " + os.environ.get("DISPLAY", ""))
        self.root = x.XDefaultRootWindow(self.dpy)
        self._atoms = {}
        self.lock = threading.RLock()

    def atom(self, name: str) -> int:
        a = self._atoms.get(name)
        if a is None:
            a = self.x.XInternAtom(self.dpy, name.encode(), 0)
            self._atoms[name] = a
        return a

    def get_prop(self, win, name, type_=AnyPropertyType, max_len=1 << 20):
        """Returns (type, format, bytes)."""
        with self.lock:
            atype = Atom()
            fmt = c_int()
            nitems = c_ulong()
            after = c_ulong()
            data = c_void_p()
            st = self.x.XGetWindowProperty(self.dpy, win, self.atom(name) if isinstance(name, str) else name, 0,
                                           max_len, 0, type_, byref(atype), byref(fmt), byref(nitems), byref(after),
                                           byref(data))
            if st != 0 or not data.value:
                return None
            n = nitems.value
            f = fmt.value
            size = n * (8 if f == 32 else f // 8)   # 32-bit items are longs in Xlib
            raw = ctypes.string_at(data.value, size)
            self.x.XFree(data)
            return atype.value, f, raw, n

    def get_longs(self, win, name):
        r = self.get_prop(win, name)
        if not r:
            return []
        _, f, raw, n = r
        if f != 32:
            return []
        return list((c_ulong * n).from_buffer_copy(raw))

    def get_string(self, win, name):
        r = self.get_prop(win, name)
        if not r:
            return None
        return r[2].decode("utf-8", "replace")

    def flush(self):
        self.x.XFlush(self.dpy)

    def sync(self):
        self.x.XSync(self.dpy, 0)


_main_display = None
_main_lock = threading.Lock()


def display() -> Display:
    """A shared connection for use from the script thread."""
    global _main_display
    with _main_lock:
        if _main_display is None:
            _main_display = Display()
        return _main_display


class XRRMonitorInfo(ctypes.Structure):
    _fields_ = [("name", c_ulong), ("primary", c_int), ("automatic", c_int), ("noutput", c_int), ("x", c_int),
                ("y", c_int), ("width", c_int), ("height", c_int), ("mwidth", c_int), ("mheight", c_int),
                ("outputs", c_void_p)]


def monitors(d):
    """[(name, x, y, w, h, primary)] from XRandR 1.5 (XRRGetMonitors); [] if unavailable."""
    xr = _lib("Xrandr")
    if xr is None or d is None or not hasattr(xr, "XRRGetMonitors"):
        return []
    xr.XRRGetMonitors.restype = ctypes.POINTER(XRRMonitorInfo)
    xr.XRRGetMonitors.argtypes = [c_void_p, c_ulong, c_int, ctypes.POINTER(c_int)]
    xr.XRRFreeMonitors.argtypes = [c_void_p]
    d.x.XGetAtomName.restype = c_void_p
    d.x.XGetAtomName.argtypes = [c_void_p, c_ulong]
    d.x.XFree.argtypes = [c_void_p]
    n = c_int()
    arr = xr.XRRGetMonitors(d.dpy, d.root, 1, ctypes.byref(n))
    if not arr:
        return []
    out = []
    for i in range(n.value):
        m = arr[i]
        p = d.x.XGetAtomName(d.dpy, m.name) if m.name else None
        name = ctypes.string_at(p).decode(errors="replace") if p else ""
        if p:
            d.x.XFree(p)
        out.append((name, m.x, m.y, m.width, m.height, bool(m.primary)))
    xr.XRRFreeMonitors(arr)
    return out

