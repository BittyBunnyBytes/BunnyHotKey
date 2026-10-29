"""Window built-ins (lib/win.cpp, window.cpp WinTitle matching) on X11/EWMH.

HWNDs are X window IDs of top-level client windows (_NET_CLIENT_LIST).  On a
pure Wayland session only XWayland windows are visible to these functions.
"""
from __future__ import annotations

import os
import re
import struct
import time

from .. import objects as O
from ..objects import AhkArray, AhkObject, throw
from ..values import UNSET, str_to_number, to_bool
from . import export, setref


def rt():
    return O.RT


def S(v):
    return O.RT.to_str(v)


def _dpy():
    from .. import xlib
    if not xlib.available():
        return None
    try:
        return xlib.display()
    except OSError:
        return None


# ---------------------------------------------------------------- window info
def client_list(d, include_hidden=False):
    wins = d.get_longs(d.root, "_NET_CLIENT_LIST_STACKING") or d.get_longs(d.root, "_NET_CLIENT_LIST")
    wins = list(reversed(wins))           # topmost first, like EnumWindows z-order
    if include_hidden:
        from .. import xlib
        x = d.x
        root_ret = xlib.Window()
        parent = xlib.Window()
        children = xlib.POINTER(xlib.Window)()
        n = xlib.c_uint()
        if x.XQueryTree(d.dpy, d.root, xlib.byref(root_ret), xlib.byref(parent), xlib.byref(children), xlib.byref(n)):
            extra = [children[i] for i in range(n.value)]
            x.XFree(children)
            for w in reversed(extra):
                if w not in wins and title_of(d, w) is not None:
                    wins.append(w)
    return wins


def title_of(d, w):
    t = d.get_string(w, "_NET_WM_NAME")
    if t is None:
        r = d.get_prop(w, "WM_NAME")
        t = r[2].decode("latin-1") if r else None
    return t


def class_of(d, w):
    r = d.get_prop(w, "WM_CLASS")
    if not r:
        return "", ""
    parts = r[2].split(b"\0")
    inst = parts[0].decode("utf-8", "replace") if parts else ""
    cls = parts[1].decode("utf-8", "replace") if len(parts) > 1 else inst
    return inst, cls


def pid_of(d, w):
    v = d.get_longs(w, "_NET_WM_PID")
    return int(v[0]) if v else 0


def proc_name(pid):
    if not pid:
        return ""
    try:
        return os.path.basename(os.readlink(f"/proc/{pid}/exe"))
    except OSError:
        try:
            with open(f"/proc/{pid}/comm") as fh:
                return fh.read().strip()
        except OSError:
            return ""


def proc_path(pid):
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return ""


def active_window(d):
    v = d.get_longs(d.root, "_NET_ACTIVE_WINDOW")
    return int(v[0]) if v and v[0] else 0


def is_visible(d, w):
    from .. import xlib
    attrs = xlib.XWindowAttributes()
    if not d.x.XGetWindowAttributes(d.dpy, w, xlib.byref(attrs)):
        return False
    if attrs.map_state == 2:   # IsViewable
        return True
    states = d.get_longs(w, "_NET_WM_STATE")
    return d.atom("_NET_WM_STATE_HIDDEN") in states   # minimized windows still count as visible


# ---------------------------------------------------------------- WinTitle matching
class Criteria:
    __slots__ = ("title", "cls", "exe", "pid", "id", "group", "text", "ex_title", "ex_text", "active", "last_found")

    def __init__(self):
        self.title = ""
        self.cls = None
        self.exe = None
        self.pid = None
        self.id = None
        self.group = None
        self.text = ""
        self.ex_title = ""
        self.ex_text = ""
        self.active = False
        self.last_found = False


def parse_criteria(wintitle, wintext=UNSET, ex_title=UNSET, ex_text=UNSET) -> Criteria:
    c = Criteria()
    r = rt()
    if wintitle is UNSET and wintext is UNSET and ex_title is UNSET and ex_text is UNSET:
        c.last_found = True
        return c
    if isinstance(wintitle, AhkObject):
        h = r.get_prop(wintitle, "Hwnd")
        c.id = r.to_int(h)
        return c
    if type(wintitle) in (int, float):
        c.id = int(wintitle)
        return c
    t = S(wintitle) if wintitle is not UNSET else ""
    if t == "A":
        c.active = True
    else:
        # split on ahk_ keywords
        parts = re.split(r"(ahk_(?:class|exe|pid|id|group))\s*", t, flags=re.I)
        c.title = parts[0].strip() if parts[0].strip() or len(parts) == 1 else ""
        if len(parts) == 1:
            c.title = parts[0]
        i = 1
        while i < len(parts) - 1:
            kw = parts[i].lower()
            val = parts[i + 1]
            # value ends at the next keyword; trailing spaces are part of the title criteria otherwise
            val = val.strip() if kw not in ("ahk_class",) else val.rstrip()
            if kw == "ahk_class":
                c.cls = val.strip()
            elif kw == "ahk_exe":
                c.exe = val.strip()
            elif kw == "ahk_pid":
                c.pid = r.to_int(val.strip())
            elif kw == "ahk_id":
                c.id = r.to_int(val.strip())
            elif kw == "ahk_group":
                c.group = val.strip()
            i += 2
    c.text = S(wintext) if wintext is not UNSET else ""
    c.ex_title = S(ex_title) if ex_title is not UNSET else ""
    c.ex_text = S(ex_text) if ex_text is not UNSET else ""
    return c


def _str_match(pattern, value, mode):
    if mode == "RegEx":
        from .regex import compile_pattern
        rx, anchored = compile_pattern(pattern)
        return (rx.match(value) if anchored else rx.search(value)) is not None
    if mode == 1:
        return value.startswith(pattern)
    if mode == 3:
        return value == pattern
    return pattern in value


GROUPS: dict[str, list] = {}


def window_matches(d, w, c: Criteria, mode=None) -> bool:
    if mode is None:
        mode = rt().thread.settings.title_match_mode
    if c.id is not None and w != c.id:
        return False
    if c.title:
        t = title_of(d, w) or ""
        if not _str_match(c.title, t, mode):
            return False
    if c.ex_title:
        t = title_of(d, w) or ""
        if _str_match(c.ex_title, t, mode):
            return False
    if c.cls is not None:
        inst, cls = class_of(d, w)
        if mode == "RegEx":
            if not (_str_match(c.cls, cls, mode) or _str_match(c.cls, inst, mode)):
                return False
        elif c.cls.lower() not in (cls.lower(), inst.lower()):
            return False
    if c.pid is not None and pid_of(d, w) != c.pid:
        return False
    if c.exe is not None:
        pid = pid_of(d, w)
        name = proc_name(pid)
        want = c.exe
        if mode == "RegEx":
            if not (_str_match(want, name, mode) or _str_match(want, proc_path(pid), mode)):
                return False
        else:
            wl = want.lower().replace("\\", "/")
            nl = name.lower()
            base = os.path.basename(wl)
            stem = base[:-4] if base.endswith(".exe") else base
            if not (nl == base or nl == stem or proc_path(pid).lower() == wl
                    or (len(nl) == 15 and stem.startswith(nl))):      # /proc comm is truncated to 15 chars
                return False
    if c.group is not None:
        crits = GROUPS.get(c.group.lower(), [])
        if not any(window_matches(d, w, g) for g in crits):
            return False
    return True


def find_windows(c: Criteria, first_only=False):
    d = _dpy()
    if d is None:
        return []
    r = rt()
    if c.last_found:
        lf = r.thread.settings.last_found
        if lf and lf in client_list(d, True):
            return [lf]
        return []
    if c.active:
        a = active_window(d)
        return [a] if a else []
    hidden = r.thread.settings.detect_hidden_windows
    if c.id is not None and not c.title and c.cls is None and c.exe is None and c.pid is None and c.group is None:
        # ahk_id names any existing top-level window directly
        from .. import xlib
        attrs = xlib.XWindowAttributes()
        if c.id and d.x.XGetWindowAttributes(d.dpy, c.id, xlib.byref(attrs)) and (hidden or is_visible(d, c.id)):
            return [c.id]
        return []
    out = []
    for w in client_list(d, hidden):
        if not hidden and not is_visible(d, w):
            continue
        if window_matches(d, w, c):
            out.append(w)
            if first_only:
                break
    return out


def find_window(wintitle=UNSET, wintext=UNSET, ex_title=UNSET, ex_text=UNSET, required=True):
    c = parse_criteria(wintitle, wintext, ex_title, ex_text)
    ws = find_windows(c, True)
    if not ws:
        if required:
            throw("TargetError", "Target window not found.")
        return 0
    rt().thread.settings.last_found = ws[0]
    return ws[0]


# ---------------------------------------------------------------- EWMH actions
def _client_msg(d, w, mtype, data):
    from .. import xlib
    ev = xlib.XEvent()
    ev.xclient.type = xlib.ClientMessage
    ev.xclient.window = w
    ev.xclient.message_type = d.atom(mtype)
    ev.xclient.format = 32
    for i, v in enumerate(data[:5]):
        ev.xclient.data[i] = v
    d.x.XSendEvent(d.dpy, d.root, 0, xlib.SubstructureRedirectMask | xlib.SubstructureNotifyMask, xlib.byref(ev))
    d.flush()


def _wm_state(d, w, action, a1, a2=""):
    # action: 0 remove, 1 add, 2 toggle
    _client_msg(d, w, "_NET_WM_STATE", [action, d.atom(a1), d.atom(a2) if a2 else 0, 2, 0])


def activate(d, w):
    states = d.get_longs(w, "_NET_WM_STATE")
    if d.atom("_NET_WM_STATE_HIDDEN") in states:
        d.x.XMapRaised(d.dpy, w)
    _client_msg(d, w, "_NET_ACTIVE_WINDOW", [2, 0, 0, 0, 0])
    d.x.XRaiseWindow(d.dpy, w)
    d.flush()


def frame_extents(d, w):
    v = d.get_longs(w, "_NET_FRAME_EXTENTS")
    return tuple(int(x) for x in v[:4]) if len(v) >= 4 else (0, 0, 0, 0)


def geometry(d, w, client=False):
    from .. import xlib
    root = xlib.Window()
    x = xlib.c_int()
    y = xlib.c_int()
    wd = xlib.c_uint()
    ht = xlib.c_uint()
    bw = xlib.c_uint()
    dep = xlib.c_uint()
    if not d.x.XGetGeometry(d.dpy, w, xlib.byref(root), xlib.byref(x), xlib.byref(y), xlib.byref(wd), xlib.byref(ht),
                            xlib.byref(bw), xlib.byref(dep)):
        return 0, 0, 0, 0
    ax = xlib.c_int()
    ay = xlib.c_int()
    child = xlib.Window()
    d.x.XTranslateCoordinates(d.dpy, w, d.root, 0, 0, xlib.byref(ax), xlib.byref(ay), xlib.byref(child))
    if client:
        return ax.value, ay.value, wd.value, ht.value
    l, r, t, b = frame_extents(d, w)
    return ax.value - l, ay.value - t, wd.value + l + r, ht.value + t + b


def screen_size():
    d = _dpy()
    if d is None:
        return 1920, 1080
    scr = d.x.XDefaultScreen(d.dpy)
    return d.x.XDisplayWidth(d.dpy, scr), d.x.XDisplayHeight(d.dpy, scr)


# ---------------------------------------------------------------- built-ins
def _win_arg(*a):
    return find_window(*a, required=True)


@export()
def WinExist(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return find_window(t, txt, xt, xx, required=False)


@export()
def WinActive(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    if d is None:
        return 0
    a = active_window(d)
    if not a:
        return 0
    c = parse_criteria(t, txt, xt, xx)
    if c.last_found:
        lf = rt().thread.settings.last_found
        return a if lf == a else 0
    if c.active or window_matches(d, a, c):
        rt().thread.settings.last_found = a
        return a
    return 0


@export()
def WinActivate(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    w = _win_arg(t, txt, xt, xx)
    d = _dpy()
    activate(d, w)
    _delay()
    return ""


@export()
def WinActivateBottom(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    ws = find_windows(parse_criteria(t, txt, xt, xx))
    if not ws:
        throw("TargetError", "Target window not found.")
    activate(_dpy(), ws[-1])
    return ""


def _delay():
    d = rt().thread.settings.win_delay
    if d > 0:
        rt().sleep(d)


def _wait(cond, timeout):
    r = rt()
    end = None if timeout in (UNSET, "") else time.monotonic() + float(r.to_num(timeout))
    while True:
        v = cond()
        if v:
            return v
        if end is not None and time.monotonic() >= end:
            return 0
        r.sleep(50)


@export()
def WinWait(t=UNSET, txt=UNSET, timeout=UNSET, xt=UNSET, xx=UNSET):
    return _wait(lambda: find_window(t, txt, xt, xx, required=False), timeout)


@export()
def WinWaitActive(t=UNSET, txt=UNSET, timeout=UNSET, xt=UNSET, xx=UNSET):
    return _wait(lambda: WinActive(t, txt, xt, xx), timeout)


@export()
def WinWaitNotActive(t=UNSET, txt=UNSET, timeout=UNSET, xt=UNSET, xx=UNSET):
    return int(bool(_wait(lambda: not WinActive(t, txt, xt, xx), timeout)))


@export()
def WinWaitClose(t=UNSET, txt=UNSET, timeout=UNSET, xt=UNSET, xx=UNSET):
    return int(bool(_wait(lambda: not find_window(t, txt, xt, xx, required=False), timeout)))


@export()
def WinGetTitle(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return title_of(_dpy(), _win_arg(t, txt, xt, xx)) or ""


@export()
def WinGetClass(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return class_of(_dpy(), _win_arg(t, txt, xt, xx))[1]


@export()
def WinGetID(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return _win_arg(t, txt, xt, xx)


@export()
def WinGetIDLast(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    ws = find_windows(parse_criteria(t, txt, xt, xx))
    if not ws:
        throw("TargetError", "Target window not found.")
    return ws[-1]


@export()
def WinGetPID(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return pid_of(_dpy(), _win_arg(t, txt, xt, xx))


@export()
def WinGetProcessName(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return proc_name(pid_of(_dpy(), _win_arg(t, txt, xt, xx)))


@export()
def WinGetProcessPath(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return proc_path(pid_of(_dpy(), _win_arg(t, txt, xt, xx)))


@export()
def WinGetCount(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c = parse_criteria(t if t is not UNSET else "", txt, xt, xx)
    return len(find_windows(c))


@export()
def WinGetList(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c = parse_criteria(t if t is not UNSET else "", txt, xt, xx)
    return AhkArray(None, find_windows(c))


@export(byref=(0, 1, 2, 3))
def WinGetPos(x=UNSET, y=UNSET, w=UNSET, h=UNSET, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    win = _win_arg(t, txt, xt, xx)
    gx, gy, gw, gh = geometry(_dpy(), win)
    setref(x, gx); setref(y, gy); setref(w, gw); setref(h, gh)
    return ""


@export(byref=(0, 1, 2, 3))
def WinGetClientPos(x=UNSET, y=UNSET, w=UNSET, h=UNSET, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    win = _win_arg(t, txt, xt, xx)
    gx, gy, gw, gh = geometry(_dpy(), win, client=True)
    setref(x, gx); setref(y, gy); setref(w, gw); setref(h, gh)
    return ""


@export()
def WinGetMinMax(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    w = _win_arg(t, txt, xt, xx)
    st = d.get_longs(w, "_NET_WM_STATE")
    if d.atom("_NET_WM_STATE_HIDDEN") in st:
        return -1
    if d.atom("_NET_WM_STATE_MAXIMIZED_VERT") in st and d.atom("_NET_WM_STATE_MAXIMIZED_HORZ") in st:
        return 1
    return 0


@export()
def WinGetStyle(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    _win_arg(t, txt, xt, xx)
    return 0x14CF0000   # WS_OVERLAPPEDWINDOW | WS_VISIBLE


@export()
def WinGetExStyle(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    w = _win_arg(t, txt, xt, xx)
    return 0x8 if d.atom("_NET_WM_STATE_ABOVE") in d.get_longs(w, "_NET_WM_STATE") else 0


@export()
def WinGetText(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    _win_arg(t, txt, xt, xx)
    return ""


@export()
def WinGetControls(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    _win_arg(t, txt, xt, xx)
    return AhkArray(None, [])


@export()
def WinGetControlsHwnd(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    _win_arg(t, txt, xt, xx)
    return AhkArray(None, [])


@export()
def WinGetTransparent(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    w = _win_arg(t, txt, xt, xx)
    v = d.get_longs(w, "_NET_WM_WINDOW_OPACITY")
    return "" if not v else int(v[0]) * 255 // 0xFFFFFFFF


@export()
def WinGetTransColor(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return ""


@export()
def WinMove(x=UNSET, y=UNSET, w=UNSET, h=UNSET, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    win = _win_arg(t, txt, xt, xx)
    gx, gy, gw, gh = geometry(d, win)
    l, r_, tp, b = frame_extents(d, win)
    r = rt()
    nx = r.to_int(x) if x not in (UNSET, "") else gx
    ny = r.to_int(y) if y not in (UNSET, "") else gy
    nw = r.to_int(w) if w not in (UNSET, "") else gw
    nh = r.to_int(h) if h not in (UNSET, "") else gh
    # gravity StaticGravity(10) + flags x,y,w,h -> outer coordinates handled by the WM
    _client_msg(d, win, "_NET_MOVERESIZE_WINDOW", [(1 << 8) | (1 << 9) | (1 << 10) | (1 << 11) | 1, nx, ny,
                                                    max(nw - l - r_, 1), max(nh - tp - b, 1)])
    _delay()
    return ""


@export()
def WinClose(t=UNSET, txt=UNSET, wait=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    win = _win_arg(t, txt, xt, xx)
    _client_msg(d, win, "_NET_CLOSE_WINDOW", [0, 2, 0, 0, 0])
    if wait is not UNSET:
        _wait(lambda: win not in client_list(d), wait)
    _delay()
    return ""


@export()
def WinKill(t=UNSET, txt=UNSET, wait=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    win = _win_arg(t, txt, xt, xx)
    pid = pid_of(d, win)
    if pid:
        import signal
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            d.x.XKillClient(d.dpy, win)
    else:
        d.x.XKillClient(d.dpy, win)
    d.flush()
    return ""


@export()
def WinMinimize(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    win = _win_arg(t, txt, xt, xx)
    d.x.XIconifyWindow(d.dpy, win, d.x.XDefaultScreen(d.dpy))
    d.flush()
    _delay()
    return ""


@export()
def WinMaximize(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    win = _win_arg(t, txt, xt, xx)
    _wm_state(d, win, 1, "_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ")
    _delay()
    return ""


@export()
def WinRestore(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    win = _win_arg(t, txt, xt, xx)
    st = d.get_longs(win, "_NET_WM_STATE")
    if d.atom("_NET_WM_STATE_HIDDEN") in st:
        activate(d, win)
    else:
        _wm_state(d, win, 0, "_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ")
    _delay()
    return ""


@export()
def WinHide(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    win = _win_arg(t, txt, xt, xx)
    d.x.XUnmapWindow(d.dpy, win)
    d.flush()
    return ""


@export()
def WinShow(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    win = _win_arg(t, txt, xt, xx)
    d.x.XMapWindow(d.dpy, win)
    d.flush()
    return ""


@export()
def WinSetTitle(newtitle, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    win = _win_arg(t, txt, xt, xx)
    data = S(newtitle).encode()
    d.x.XChangeProperty(d.dpy, win, d.atom("_NET_WM_NAME"), d.atom("UTF8_STRING"), 8, 0, data, len(data))
    d.x.XStoreName(d.dpy, win, data)
    d.flush()
    return ""


@export()
def WinSetAlwaysOnTop(value=1, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    win = _win_arg(t, txt, xt, xx)
    v = rt().to_int(value) if not isinstance(value, str) or value.lstrip("-").isdigit() else (1 if value.lower() == "on" else 0 if value.lower() == "off" else -1)
    _wm_state(d, win, 2 if v == -1 else (1 if v else 0), "_NET_WM_STATE_ABOVE")
    return ""


@export()
def WinSetTransparent(n, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    win = _win_arg(t, txt, xt, xx)
    s = S(n)
    if s.lower() == "off" or s == "":
        d.x.XDeleteProperty(d.dpy, win, d.atom("_NET_WM_WINDOW_OPACITY"))
    else:
        val = max(0, min(255, rt().to_int(n))) * 0xFFFFFFFF // 255
        import ctypes
        buf = (ctypes.c_ulong * 1)(val)
        d.x.XChangeProperty(d.dpy, win, d.atom("_NET_WM_WINDOW_OPACITY"), 6, 32, 0, buf, 1)
    d.flush()
    return ""


@export()
def WinSetTransColor(color, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return ""


@export()
def WinSetEnabled(v, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    _win_arg(t, txt, xt, xx)
    return ""


@export()
def WinSetStyle(v, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    _win_arg(t, txt, xt, xx)
    return ""


@export()
def WinSetExStyle(v, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    s = S(v)
    if s in ("^0x8", "+0x8", "-0x8", "0x8"):
        WinSetAlwaysOnTop(-1 if s.startswith("^") else 0 if s.startswith("-") else 1, t, txt, xt, xx)
    return ""


@export()
def WinSetRegion(*a):
    return ""


@export()
def WinRedraw(*a):
    return ""


@export()
def WinMoveTop(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    d.x.XRaiseWindow(d.dpy, _win_arg(t, txt, xt, xx))
    d.flush()
    return ""


@export()
def WinMoveBottom(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    _wm_state(_dpy(), _win_arg(t, txt, xt, xx), 1, "_NET_WM_STATE_BELOW")
    return ""


@export()
def WinMinimizeAll():
    d = _dpy()
    if d:
        _client_msg(d, d.root, "_NET_SHOWING_DESKTOP", [1, 0, 0, 0, 0])
    return ""


@export()
def WinMinimizeAllUndo():
    d = _dpy()
    if d:
        _client_msg(d, d.root, "_NET_SHOWING_DESKTOP", [0, 0, 0, 0, 0])
    return ""


@export()
def GroupAdd(name, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    GROUPS.setdefault(S(name).lower(), []).append(parse_criteria(t if t is not UNSET else "", txt, xt, xx))
    return ""


@export()
def GroupActivate(name, mode=""):
    c = Criteria()
    c.group = S(name)
    ws = find_windows(c)
    if not ws:
        return 0
    d = _dpy()
    a = active_window(d)
    target = ws[(ws.index(a) + 1) % len(ws)] if a in ws else ws[0]
    activate(d, target)
    return target


@export()
def GroupDeactivate(name, mode=""):
    return ""


@export()
def GroupClose(name, mode=""):
    c = Criteria()
    c.group = S(name)
    d = _dpy()
    for w in find_windows(c, S(mode).upper() != "A"):
        _client_msg(d, w, "_NET_CLOSE_WINDOW", [0, 2, 0, 0, 0])
    return ""


# ---------------------------------------------------------------- controls (limited on X11)
def _target_for_control(control, t, txt, xt, xx):
    if isinstance(control, AhkObject):
        return rt().to_int(rt().get_prop(control, "Hwnd"))
    if type(control) is int:
        return control
    return _win_arg(t, txt, xt, xx)


@export()
def ControlSend(keys, control=UNSET, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    from .input_ import send_to_window
    win = _target_for_control(control, t, txt, xt, xx)
    send_to_window(win, S(keys), raw=False)
    return ""


@export()
def ControlSendText(keys, control=UNSET, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    from .input_ import send_to_window
    win = _target_for_control(control, t, txt, xt, xx)
    send_to_window(win, S(keys), raw=True)
    return ""


@export()
def ControlClick(target=UNSET, t=UNSET, txt=UNSET, button="Left", count=1, options="", xt=UNSET, xx=UNSET):
    from .input_ import click_window
    win = _win_arg(t, txt, xt, xx)
    m = re.match(r"\s*x(-?\d+)\s+y(-?\d+)", S(target)) if target is not UNSET and isinstance(target, str) else None
    pos = (int(m.group(1)), int(m.group(2))) if m else None
    click_window(win, S(button), rt().to_int(count) if count != "" else 1, pos)
    return ""


@export()
def ControlFocus(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    activate(_dpy(), _target_for_control(control, t, txt, xt, xx))
    return ""


@export()
def ControlGetHwnd(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return _target_for_control(control, t, txt, xt, xx)


@export()
def ControlGetFocus(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return _win_arg(t, txt, xt, xx)


@export()
def ControlGetText(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return title_of(_dpy(), _target_for_control(control, t, txt, xt, xx)) or ""


@export()
def ControlSetText(newtext, control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return ""


@export(byref=(0, 1, 2, 3))
def ControlGetPos(x=UNSET, y=UNSET, w=UNSET, h=UNSET, control=UNSET, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    win = _target_for_control(control, t, txt, xt, xx)
    gx, gy, gw, gh = geometry(_dpy(), win, client=True)
    setref(x, 0); setref(y, 0); setref(w, gw); setref(h, gh)
    return ""


@export()
def ControlGetVisible(*a):
    return 1


@export()
def ControlGetEnabled(*a):
    return 1


@export()
def ControlGetClassNN(control, *a):
    return ""


@export()
def ControlMove(*a):
    return ""


@export()
def ControlShow(*a):
    return ""


@export()
def ControlHide(*a):
    return ""


@export()
def ControlSetEnabled(*a):
    return ""


@export()
def ControlChooseIndex(*a):
    return ""


@export()
def ControlChooseString(*a):
    return 0


@export()
def ControlGetChecked(*a):
    return 0


@export()
def ControlSetChecked(*a):
    return ""


@export()
def ControlGetItems(*a):
    return AhkArray(None, [])


@export()
def ControlGetChoice(*a):
    return ""


@export()
def ControlGetIndex(*a):
    return 0


@export()
def ControlGetStyle(*a):
    return 0


@export()
def ControlGetExStyle(*a):
    return 0


@export()
def ControlSetStyle(*a):
    return ""


@export()
def ControlSetExStyle(*a):
    return ""


@export()
def ControlAddItem(*a):
    return 0


@export()
def ControlDeleteItem(*a):
    return ""


@export()
def ControlFindItem(*a):
    return 0


@export()
def ControlShowDropDown(*a):
    return ""


@export()
def ControlHideDropDown(*a):
    return ""


@export()
def ControlEditPaste(text, control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    from .input_ import send_to_window
    send_to_window(_target_for_control(control, t, txt, xt, xx), S(text), raw=True)
    return ""


@export()
def EditGetLineCount(*a):
    return 1


@export()
def EditGetCurrentLine(*a):
    return 1


@export()
def EditGetCurrentCol(*a):
    return 1


@export()
def EditGetLine(*a):
    return ""


@export()
def EditGetSelectedText(*a):
    return ""


@export()
def ListViewGetContent(*a):
    return ""


@export()
def StatusBarGetText(*a):
    return ""


@export()
def StatusBarWait(*a):
    return 0


@export()
def MenuSelect(*a):
    return ""


@export()
def PostMessage(*a):
    return ""


@export()
def SendMessage(*a):
    return 0


# ---------------------------------------------------------------- pixels
def _coord_origin(kind):
    mode = rt().thread.settings.coord_mode.get(kind, "Client")
    if mode == "Screen":
        return 0, 0
    d = _dpy()
    if d is None:
        return 0, 0
    a = active_window(d)
    if not a:
        return 0, 0
    x, y, w, h = geometry(d, a, client=(mode == "Client"))
    return x, y


def grab(x, y, w, h):
    """Returns (width, height, rgb bytes) for a screen region."""
    from .. import xlib
    d = _dpy()
    if d is None:
        throw("Error", "No X display available.")
    img = d.x.XGetImage(d.dpy, d.root, x, y, w, h, 0xFFFFFFFF, xlib.ZPixmap)
    if not img:
        throw("Error", "Could not capture the screen.")
    im = img.contents
    bpl = im.bytes_per_line
    raw = xlib.ctypes.string_at(im.data, bpl * h)
    d.x.XDestroyImage(img)
    rows = []
    for row in range(h):
        line = raw[row * bpl: row * bpl + w * 4]
        rows.append(line)
    return w, h, rows


@export()
def PixelGetColor(x, y, mode=""):
    r = rt()
    ox, oy = _coord_origin("Pixel")
    w, h, rows = grab(r.to_int(x) + ox, r.to_int(y) + oy, 1, 1)
    b, g, rr = rows[0][0], rows[0][1], rows[0][2]
    return "0x%02X%02X%02X" % (rr, g, b)


@export(byref=(0, 1))
def PixelSearch(outx, outy, x1, y1, x2, y2, color, variation=0):
    r = rt()
    ox, oy = _coord_origin("Pixel")
    X1, Y1, X2, Y2 = (r.to_int(v) for v in (x1, y1, x2, y2))
    c = r.to_int(color)
    tr, tg, tb = (c >> 16) & 255, (c >> 8) & 255, c & 255
    var = r.to_int(variation) if variation != "" else 0
    lx, hx = min(X1, X2), max(X1, X2)
    ly, hy = min(Y1, Y2), max(Y1, Y2)
    w, h, rows = grab(lx + ox, ly + oy, hx - lx + 1, hy - ly + 1)
    ys = range(h) if Y1 <= Y2 else range(h - 1, -1, -1)
    xs = list(range(w)) if X1 <= X2 else list(range(w - 1, -1, -1))
    for yy in ys:
        row = rows[yy]
        for xx in xs:
            b, g, rr = row[xx * 4], row[xx * 4 + 1], row[xx * 4 + 2]
            if abs(rr - tr) <= var and abs(g - tg) <= var and abs(b - tb) <= var:
                setref(outx, lx + xx)
                setref(outy, ly + yy)
                return 1
    setref(outx, "")
    setref(outy, "")
    return 0


@export(byref=(0, 1))
def ImageSearch(outx, outy, x1, y1, x2, y2, image):
    from .images import image_search
    return image_search(outx, outy, x1, y1, x2, y2, S(image))


@export(byref=(0, 1, 2, 3))
def MonitorGet(n=UNSET, left=UNSET, top=UNSET, right=UNSET, bottom=UNSET):
    w, h = screen_size()
    setref(left, 0); setref(top, 0); setref(right, w); setref(bottom, h)
    return 1


@export(byref=(1, 2, 3, 4))
def MonitorGetWorkArea(n=UNSET, left=UNSET, top=UNSET, right=UNSET, bottom=UNSET):
    d = _dpy()
    w, h = screen_size()
    wa = d.get_longs(d.root, "_NET_WORKAREA") if d else []
    if len(wa) >= 4:
        setref(left, int(wa[0])); setref(top, int(wa[1])); setref(right, int(wa[0] + wa[2])); setref(bottom, int(wa[1] + wa[3]))
    else:
        setref(left, 0); setref(top, 0); setref(right, w); setref(bottom, h)
    return 1


@export()
def MonitorGetCount():
    return 1


@export()
def MonitorGetPrimary():
    return 1


@export()
def MonitorGetName(n=UNSET):
    return "\\\\.\\DISPLAY1"


@export()
def SysGet(n):
    i = rt().to_int(n)
    w, h = screen_size()
    return {0: w, 1: h, 78: w, 79: h, 80: 1, 16: w, 17: h, 43: 3, 4: 23, 5: 1, 6: 1, 7: 3, 8: 3,
            32: 8, 33: 8, 19: 1}.get(i, 0)
