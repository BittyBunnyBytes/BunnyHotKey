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
    if c.text or c.ex_text:
        # WinText: this script's Gui windows directly, other programs' through AT-SPI
        texts = _gui_texts(w)
        if texts is None:
            texts = _foreign_texts(w)
        if texts is not None:
            if c.text and not any(_str_match(c.text, x, mode) for x in texts):
                return False
            if c.ex_text and any(_str_match(c.ex_text, x, mode) for x in texts):
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


# Window styles <-> X11.  Decorations and window-manager functions are the Motif hints every X11 window manager
# honours; visibility, minimize/maximize and disabled come from the window state.
WS_POPUP, WS_MINIMIZE_ST, WS_MAXIMIZE_ST = 0x80000000, 0x20000000, 0x01000000
WS_CAPTION, WS_BORDER, WS_DLGFRAME, WS_SYSMENU, WS_THICKFRAME = 0xC00000, 0x800000, 0x400000, 0x80000, 0x40000
WS_MINIMIZEBOX, WS_MAXIMIZEBOX, WS_CLIPSIBLINGS = 0x20000, 0x10000, 0x04000000
MWM_FUNC = {"resize": 2, "move": 4, "minimize": 8, "maximize": 16, "close": 32}
MWM_DECOR = {"border": 2, "resizeh": 4, "title": 8, "menu": 16, "minimize": 32, "maximize": 64}


def _motif(d, w):
    v = d.get_longs(w, "_MOTIF_WM_HINTS")
    return [int(x) for x in v[:5]] + [0] * (5 - len(v[:5])) if v else None


_STYLE_SET: dict[int, tuple] = {}     # window -> (Motif hints we wrote, frame style bits the script asked for)
FRAME_BITS = WS_POPUP | WS_CAPTION | WS_SYSMENU | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX


def _style_bits(d, w):
    m = _motif(d, w)
    remembered = _STYLE_SET.get(w)
    if remembered is not None and remembered[0] == m:
        style = WS_CLIPSIBLINGS | remembered[1]     # e.g. WS_SYSMENU stays set without a caption, as on Windows
        return style | _state_bits(d, w)
    style = WS_CLIPSIBLINGS
    if m is None or not (m[0] & 2) or (m[2] & 1):
        decor = {"border", "resizeh", "title", "menu", "minimize", "maximize"}
    else:
        decor = {k for k, b in MWM_DECOR.items() if m[2] & b}
    if m is not None and m[0] & 1 and not (m[1] & 1):
        funcs = {k for k, b in MWM_FUNC.items() if m[1] & b}
        decor &= ({"minimize"} if "minimize" in funcs else set()) | ({"maximize"} if "maximize" in funcs else set()) \
            | {"border", "title", "menu"} | ({"resizeh"} if "resize" in funcs else set())
    if "title" in decor:
        style |= WS_CAPTION
    elif "border" in decor:
        style |= WS_BORDER
    else:
        style |= WS_POPUP
    if "menu" in decor:
        style |= WS_SYSMENU
    if "resizeh" in decor:
        style |= WS_THICKFRAME
    if "minimize" in decor:
        style |= WS_MINIMIZEBOX
    if "maximize" in decor:
        style |= WS_MAXIMIZEBOX
    return style | _state_bits(d, w)


def _state_bits(d, w):
    style = 0
    st = d.get_longs(w, "_NET_WM_STATE")
    if is_visible(d, w):
        style |= WS_VISIBLE
    if d.atom("_NET_WM_STATE_HIDDEN") in st:
        style |= WS_MINIMIZE_ST
    if d.atom("_NET_WM_STATE_MAXIMIZED_VERT") in st and d.atom("_NET_WM_STATE_MAXIMIZED_HORZ") in st:
        style |= WS_MAXIMIZE_ST
    from .guiobj import gui_for_window
    g = gui_for_window(w)
    if g is not None and getattr(g, "disabled", False):
        style |= WS_DISABLED
    return style


def _set_motif(d, w, style):
    import ctypes
    decor = 0
    if style & WS_CAPTION == WS_CAPTION:
        decor |= MWM_DECOR["title"] | MWM_DECOR["border"]
    elif style & WS_BORDER:
        decor |= MWM_DECOR["border"]
    if style & WS_POPUP and not style & WS_CAPTION:
        decor = 0
    for bit, key in ((WS_SYSMENU, "menu"), (WS_THICKFRAME, "resizeh"), (WS_MINIMIZEBOX, "minimize"),
                     (WS_MAXIMIZEBOX, "maximize")):
        if style & bit and decor & (MWM_DECOR["title"] | MWM_DECOR["border"]):
            decor |= MWM_DECOR[key]
    funcs = MWM_FUNC["move"] | (MWM_FUNC["close"] if style & WS_SYSMENU else 0) | \
        (MWM_FUNC["resize"] if style & WS_THICKFRAME else 0) | (MWM_FUNC["minimize"] if style & WS_MINIMIZEBOX else 0) | \
        (MWM_FUNC["maximize"] if style & WS_MAXIMIZEBOX else 0)
    hints = (ctypes.c_ulong * 5)(1 | 2, funcs, decor, 0, 0)
    a = d.atom("_MOTIF_WM_HINTS")
    d.x.XChangeProperty(d.dpy, w, a, a, 32, 0, hints, 5)
    d.flush()
    _STYLE_SET[w] = ([1 | 2, funcs, decor, 0, 0], style & FRAME_BITS)


@export()
def WinGetStyle(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    return _style_bits(d, _win_arg(t, txt, xt, xx))


@export()
def WinGetExStyle(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    w = _win_arg(t, txt, xt, xx)
    return 0x8 if d.atom("_NET_WM_STATE_ABOVE") in d.get_longs(w, "_NET_WM_STATE") else 0


def _gui_texts(win, hidden=None):
    """Control texts of one of this script's Gui windows, in creation order (as WinGetText lists them)."""
    from .guiobj import ctrl_get, gui_for_window
    g = gui_for_window(win)
    if g is None:
        return None
    if hidden is None:
        hidden = rt().thread.settings.detect_hidden_text
    out = []
    for c in g.ctrls:
        if not hidden and not c.visible:
            continue
        if c.ctype in ("ListView", "TreeView", "Picture", "Progress", "Slider", "UpDown", "MonthCal"):
            continue
        try:
            v = ctrl_get(c, "Text")
        except Exception:
            continue
        v = v if isinstance(v, str) else "\r\n".join(S(i) for i in v.items)
        if c.ctype in ("Button", "CheckBox", "Radio"):
            v = v.replace("&&", "\0").replace("&", "").replace("\0", "&")
        if v != "":
            out.append(v)
    return out


@export()
def WinGetText(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    win = _win_arg(t, txt, xt, xx)
    texts = _gui_texts(win)
    if texts is None:
        texts = _foreign_texts(win)
    return "".join(x + "\r\n" for x in texts) if texts else ""


def _foreign_texts(win):
    cs = _foreign_window(win) or []
    hidden = rt().thread.settings.detect_hidden_text
    out = []
    for f in cs:
        if f.role in ("table", "tree table", "tree", "list", "list box", "scroll bar", "slider", "progress bar"):
            continue
        if not hidden and not f.visible():
            continue
        try:
            v = f.text()
        except Exception:
            continue
        if v:
            out.append(v)
    return out


def _gui_ctrls(t, txt, xt, xx):
    from .guiobj import gui_for_window
    g = gui_for_window(_win_arg(t, txt, xt, xx))
    return g.ctrls if g is not None else []


@export()
def WinGetControls(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    from .guiobj import classnn, gui_for_window
    win = _win_arg(t, txt, xt, xx)
    if gui_for_window(win) is None:
        return AhkArray(None, [f.classnn for f in _foreign_window(win) or []])
    return AhkArray(None, [classnn(c) for c in _gui_ctrls(t, txt, xt, xx)])


@export()
def WinGetControlsHwnd(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    from .guiobj import gui_for_window
    win = _win_arg(t, txt, xt, xx)
    if gui_for_window(win) is None:
        return AhkArray(None, [f.hwnd for f in _foreign_window(win) or []])
    return AhkArray(None, [c.cid for c in _gui_ctrls(t, txt, xt, xx)])


@export()
def WinGetTransparent(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    w = _win_arg(t, txt, xt, xx)
    v = d.get_longs(w, "_NET_WM_WINDOW_OPACITY")
    return "" if not v else int(v[0]) * 255 // 0xFFFFFFFF


@export()
def WinGetTransColor(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return _TRANS_COLOR.get(_win_arg(t, txt, xt, xx), "")


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


_TRANS_COLOR: dict[int, str] = {}


@export()
def WinSetTransColor(color, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    """Colour-keyed transparency.  X11 has no colour key, so the window is shaped (X Shape extension) to cut out the
    pixels that currently have that colour; an optional second number also sets the window's opacity."""
    d = _dpy()
    win = _win_arg(t, txt, xt, xx)
    s = S(color).strip()
    if s.lower() == "off" or s == "":
        _TRANS_COLOR.pop(win, None)
        _shape_reset(d, win)
        WinSetTransparent("Off", f"ahk_id {win}")
        return ""
    parts = s.split()
    from .guiobj import parse_color
    col = parse_color(parts[0])
    if not col:
        throw("ValueError", "Parameter #1 of WinSetTransColor is invalid.", s)
    rgb = int(col[1:], 16)
    _TRANS_COLOR[win] = "0x%06X" % rgb
    gx, gy, gw, gh = geometry(d, win, client=True)
    if gw and gh:
        w, h, rows = grab(gx, gy, gw, gh)
        tr, tg, tb = (rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255
        rects = []
        for y in range(h):
            row, x = rows[y], 0
            while x < w:
                while x < w and (row[x * 4 + 2], row[x * 4 + 1], row[x * 4]) == (tr, tg, tb):
                    x += 1
                start = x
                while x < w and (row[x * 4 + 2], row[x * 4 + 1], row[x * 4]) != (tr, tg, tb):
                    x += 1
                if x > start:
                    rects.append((start, y, x - start, 1))
        _shape_set(d, win, rects)
    if len(parts) > 1:
        WinSetTransparent(parts[1], f"ahk_id {win}")
    return ""


def _xext():
    from .. import xlib
    ext = xlib._lib("Xext")
    if ext is None:
        throw("Error", "The X Shape extension (libXext) is not available.")
    return ext


def _shape_set(d, w, rects):
    """Set the window's bounding shape to the union of (x, y, w, h) rectangles."""
    import ctypes

    class XRectangle(ctypes.Structure):
        _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short), ("width", ctypes.c_ushort),
                    ("height", ctypes.c_ushort)]
    ext = _xext()
    arr = (XRectangle * max(len(rects), 1))(*[XRectangle(int(x), int(y), int(rw), int(rh)) for x, y, rw, rh in rects])
    ext.XShapeCombineRectangles.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    ext.XShapeCombineRectangles(d.dpy, w, 0, 0, 0, arr, len(rects), 0, 0)      # ShapeBounding, ShapeSet, Unsorted
    d.flush()


def _shape_reset(d, w):
    import ctypes
    ext = _xext()
    ext.XShapeCombineMask.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_ulong, ctypes.c_int]
    ext.XShapeCombineMask(d.dpy, w, 0, 0, 0, 0, 0)
    d.flush()


def _region_rects(spec, width, height):
    """WinSetRegion options -> rectangles (one per scanline span).  "X-Y Wn Hn [Rw-h | E]" or a polygon of up to
    2000 "X-Y" points, with "Wind" for the winding fill rule (script2.cpp WinSetRegion)."""
    import math
    toks = spec.split()
    pts, w = [], None
    h = rw = rh = None
    ellipse = wind = False
    for t in toks:
        tl = t.lower()
        if tl == "e":
            ellipse = True
        elif tl == "wind":
            wind = True
        elif tl.startswith("w") and tl[1:].isdigit():
            w = int(tl[1:])
        elif tl.startswith("h") and tl[1:].isdigit():
            h = int(tl[1:])
        elif tl.startswith("r"):
            a, _, b = tl[1:].partition("-")
            rw, rh = int(a or 30), int(b or a or 30)
        else:
            a, _, b = tl.partition("-")
            try:
                pts.append((int(a), int(b)))
            except ValueError:
                throw("ValueError", "Parameter #1 of WinSetRegion is invalid.", t)
    rects = []
    if w is not None or h is not None:
        x0, y0 = pts[0] if pts else (0, 0)
        w, h = w or width, h or height
        for y in range(h):
            if ellipse:
                cy = (y + 0.5 - h / 2) / (h / 2)
                if abs(cy) > 1:
                    continue
                half = (w / 2) * math.sqrt(1 - cy * cy)
                left, right = round(w / 2 - half), round(w / 2 + half)
            elif rw:
                rx, ry = rw / 2, rh / 2
                left, right = 0, w
                dy = ry - y - 0.5 if y < ry else (y + 0.5 - (h - ry) if y >= h - ry else None)
                if dy is not None and dy > 0:
                    inset = rx - rx * math.sqrt(max(0.0, 1 - (dy / ry) ** 2))
                    left, right = round(inset), round(w - inset)
            else:
                left, right = 0, w
            if right > left:
                rects.append((x0 + left, y0 + y, right - left, 1))
        return rects
    if len(pts) < 3:
        throw("ValueError", "Parameter #1 of WinSetRegion is invalid.", spec)
    ys = [p[1] for p in pts]
    edges = list(zip(pts, pts[1:] + pts[:1]))
    for y in range(min(ys), max(ys)):
        yc = y + 0.5
        xs = []
        for (x1, y1), (x2, y2) in edges:
            if (y1 <= yc < y2) or (y2 <= yc < y1):
                xs.append((x1 + (yc - y1) * (x2 - x1) / (y2 - y1), 1 if y2 > y1 else -1))
        xs.sort()
        if wind:
            n, start = 0, None
            for x, dirn in xs:
                was = n != 0
                n += dirn
                if not was and n != 0:
                    start = x
                elif was and n == 0:
                    rects.append((round(start), y, round(x) - round(start), 1))
        else:
            for i in range(0, len(xs) - 1, 2):
                a, b = round(xs[i][0]), round(xs[i + 1][0])
                if b > a:
                    rects.append((a, y, b - a, 1))
    return rects


def _set_window_enabled(w, on):
    from .guiobj import gui_for_window, gui_opt
    g = gui_for_window(w)
    if g is None:
        throw("OSError", "X11 can't disable another program's window.")
    g.disabled = not on
    gui_opt(g, "-Disabled" if on else "+Disabled")


@export()
def WinSetEnabled(v, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    w = _win_arg(t, txt, xt, xx)
    cur = not (_style_bits(d, w) & WS_DISABLED)
    s = S(v).strip().lower()
    on = (not cur) if s in ("-1", "toggle") else s not in ("0", "off", "false")
    _set_window_enabled(w, on)
    return ""


@export()
def WinSetStyle(v, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    """Decorations and window-manager functions through the Motif hints; WS_VISIBLE, WS_MINIMIZE, WS_MAXIMIZE
    and WS_DISABLED through the window state."""
    d = _dpy()
    w = _win_arg(t, txt, xt, xx)
    old = _style_bits(d, w)
    new = _new_style(old, v) & 0xFFFFFFFF
    frame = WS_POPUP | WS_CAPTION | WS_SYSMENU | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
    if (old ^ new) & frame:
        _set_motif(d, w, new)
    if (old ^ new) & WS_VISIBLE:
        (WinShow if new & WS_VISIBLE else WinHide)(f"ahk_id {w}")
    if (old ^ new) & WS_MAXIMIZE_ST:
        _wm_state(d, w, 1 if new & WS_MAXIMIZE_ST else 0, "_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ")
    if (old ^ new) & WS_MINIMIZE_ST:
        if new & WS_MINIMIZE_ST:
            d.x.XIconifyWindow(d.dpy, w, d.x.XDefaultScreen(d.dpy))
        else:
            activate(d, w)
    if (old ^ new) & WS_DISABLED:
        _set_window_enabled(w, not new & WS_DISABLED)
    d.flush()
    return ""


@export()
def WinSetExStyle(v, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    s = S(v)
    if s in ("^0x8", "+0x8", "-0x8", "0x8"):
        WinSetAlwaysOnTop(-1 if s.startswith("^") else 0 if s.startswith("-") else 1, t, txt, xt, xx)
    return ""


@export()
def WinSetRegion(options="", t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    win = _win_arg(t, txt, xt, xx)
    spec = S(options).strip()
    if spec == "":
        _shape_reset(d, win)
        return ""
    # AutoHotkey's coordinates are relative to the window's outer top-left; the shape applies to the client window
    l, r_, tp, b = frame_extents(d, win)
    gx, gy, gw, gh = geometry(d, win, client=True)
    rects = [(x - l, y - tp, w, h) for x, y, w, h in _region_rects(spec, gw + l + r_, gh + tp + b)]
    _shape_set(d, win, rects)
    return ""


@export()
def WinRedraw(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    d = _dpy()
    win = _win_arg(t, txt, xt, xx)
    d.x.XClearArea(d.dpy, win, 0, 0, 0, 0, 1)     # exposures=True: the app repaints the whole window
    d.flush()
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
    """Activate the most recently used window that isn't in the group."""
    d = _dpy()
    c = Criteria()
    c.group = S(name)
    if c.group.lower() not in GROUPS:
        throw("TargetError", "Nonexistent group.", S(name))
    stack = [w for w in reversed(d.get_longs(d.root, "_NET_CLIENT_LIST_STACKING")) if is_visible(d, w)]
    skip_types = {d.atom(a) for a in ("_NET_WM_WINDOW_TYPE_DESKTOP", "_NET_WM_WINDOW_TYPE_DOCK")}
    for w in stack:
        if skip_types & set(d.get_longs(w, "_NET_WM_WINDOW_TYPE")):
            continue
        if not window_matches(d, w, c):
            activate(d, w)
            return ""
    return ""


@export()
def GroupClose(name, mode=""):
    c = Criteria()
    c.group = S(name)
    d = _dpy()
    for w in find_windows(c, S(mode).upper() != "A"):
        _client_msg(d, w, "_NET_CLOSE_WINDOW", [0, 2, 0, 0, 0])
    return ""


# ---------------------------------------------------------------- controls
# Control* functions act fully on this script's own Gui windows (resolved by Gui.Control object, Hwnd, ClassNN such as
# "Edit1" or control text, as in AutoHotkey).  Other applications' widgets aren't exposed by X11, so for those the
# functions act on the target window itself where that makes sense.
def _ctl(control, t, txt, xt, xx):
    """-> (Gui control or None, X window)."""
    from .guiobj import CtrlObj, CTRLS, find_ctrl, gui_for_window
    if isinstance(control, CtrlObj):
        if control.gui.destroyed:
            throw("TargetError", "Target control not found.")
        return control, control.gui.xid
    if isinstance(control, AhkObject):
        control = rt().to_int(rt().get_prop(control, "Hwnd"))
    if type(control) is int:
        c = CTRLS.get(control)
        return (c, c.gui.xid) if c is not None else (None, control)
    win = _win_arg(t, txt, xt, xx)
    if control is UNSET or S(control) == "":
        return None, win
    c = find_ctrl(control, win)
    if c is None and gui_for_window(win) is not None:
        throw("TargetError", "Target control not found.", S(control))
    return c, win


def _need(c, *types):
    if c is None or (types and c.ctype not in types):
        throw("Error", "The control type is not supported by this function." if c is not None else
              "Target control not found.")
    return c


def _target_for_control(control, t, txt, xt, xx):
    c, win = _ctl(control, t, txt, xt, xx)
    return c.cid if c is not None else win


def _items(c):
    from .guiobj import _srv
    return _srv().call("query", ctrl=c.cid, what="items")


def _gset(c, prop, value, notify=True):
    from .guiobj import _srv
    _srv().call("set", ctrl=c.cid, prop=prop, value=value, notify=notify)


@export()
def ControlSend(keys, control=UNSET, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    from .input_ import send_to_window
    c, win = _ctl(control, t, txt, xt, xx)
    if c is not None:
        from .guiobj import _srv
        _srv().call("focus", ctrl=c.cid)
    send_to_window(win, S(keys), raw=False)
    return ""


@export()
def ControlSendText(keys, control=UNSET, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    from .input_ import send_to_window
    c, win = _ctl(control, t, txt, xt, xx)
    if c is not None:
        from .guiobj import _srv
        _srv().call("focus", ctrl=c.cid)
    send_to_window(win, S(keys), raw=True)
    return ""


@export()
def ControlClick(target=UNSET, t=UNSET, txt=UNSET, button="Left", count=1, options="", xt=UNSET, xx=UNSET):
    from .input_ import click_window
    m = re.match(r"\s*x(-?\d+)\s+y(-?\d+)", target) if isinstance(target, str) else None
    if m is None and target is not UNSET and S(target) != "":
        c, win = _ctl(target, t, txt, xt, xx)
        if c is not None:
            from .guiobj import _srv
            if S(button).lower() in ("", "left", "l"):
                for _ in range(max(rt().to_int(count) if count != "" else 1, 1)):
                    _srv().call("click", ctrl=c.cid)
            _srv().call("focus", ctrl=c.cid)
            return ""
    else:
        win = _win_arg(t, txt, xt, xx)
    pos = (int(m.group(1)), int(m.group(2))) if m else None
    click_window(win, S(button), rt().to_int(count) if count != "" else 1, pos)
    return ""


@export()
def ControlFocus(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c, win = _ctl(control, t, txt, xt, xx)
    activate(_dpy(), win)
    if c is not None:
        from .guiobj import _srv
        _srv().call("focus", ctrl=c.cid)
    return ""


@export()
def ControlGetHwnd(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return _target_for_control(control, t, txt, xt, xx)


@export()
def ControlGetFocus(t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    from .guiobj import _srv, gui_for_window
    win = _win_arg(t, txt, xt, xx)
    g = gui_for_window(win)
    if g is not None:
        return _srv().call("focused", win=g.wid) or 0
    from . import atspi_
    if atspi_.available():
        f = atspi_.focused(*_win_info(win))
        return f.hwnd if f is not None else 0
    return win


@export()
def ControlGetText(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c, win = _ctl(control, t, txt, xt, xx)
    if c is not None:
        from .guiobj import ctrl_get
        v = ctrl_get(c, "Text")
        return v if isinstance(v, str) else "\n".join(S(i) for i in v.items)
    return title_of(_dpy(), win) or ""


@export()
def ControlSetText(newtext, control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c, win = _ctl(control, t, txt, xt, xx)
    if c is not None:
        if c.ctype in ("DDL", "ListBox", "Tab"):
            return ""        # WM_SETTEXT doesn't change a list's selection in Win32 either
        _gset(c, "Text", S(newtext))
    return ""


@export(byref=(0, 1, 2, 3))
def ControlGetPos(x=UNSET, y=UNSET, w=UNSET, h=UNSET, control=UNSET, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c, win = _ctl(control, t, txt, xt, xx)
    if c is not None:
        setref(x, c.x); setref(y, c.y); setref(w, c.w); setref(h, c.h)
        return ""
    gx, gy, gw, gh = geometry(_dpy(), win, client=True)
    setref(x, 0); setref(y, 0); setref(w, gw); setref(h, gh)
    return ""


@export()
def ControlMove(x=UNSET, y=UNSET, w=UNSET, h=UNSET, control=UNSET, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c, win = _ctl(control, t, txt, xt, xx)
    if c is not None:
        from .guiobj import _ctrl_move
        _ctrl_move(c, x, y, w, h)
    return ""


@export()
def ControlGetVisible(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c, win = _ctl(control, t, txt, xt, xx)
    return int(c.visible) if c is not None else int(is_visible(_dpy(), win))


@export()
def ControlGetEnabled(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c, win = _ctl(control, t, txt, xt, xx)
    return int(c.enabled) if c is not None else 1


@export()
def ControlGetClassNN(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c, win = _ctl(control, t, txt, xt, xx)
    if c is not None:
        from .guiobj import classnn
        return classnn(c)
    return class_of(_dpy(), win)[1] + "1"


@export()
def ControlShow(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c, win = _ctl(control, t, txt, xt, xx)
    if c is not None:
        from .guiobj import ctrl_set_visible
        ctrl_set_visible(c, 1)
    return ""


@export()
def ControlHide(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c, win = _ctl(control, t, txt, xt, xx)
    if c is not None:
        from .guiobj import ctrl_set_visible
        ctrl_set_visible(c, 0)
    return ""


@export()
def ControlSetEnabled(value, control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c, win = _ctl(control, t, txt, xt, xx)
    if c is not None:
        from .guiobj import ctrl_set_enabled
        v = rt().to_int(value)
        ctrl_set_enabled(c, (not c.enabled) if v == -1 else bool(v))
    return ""


@export()
def ControlChooseIndex(n, control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c = _need(_ctl(control, t, txt, xt, xx)[0], "DDL", "ComboBox", "ListBox", "Tab")
    i = rt().to_int(n)
    if not 0 <= i <= len(_items(c)) or (i == 0 and c.ctype == "Tab"):
        throw("ValueError", "Parameter #1 of ControlChooseIndex is invalid.", n)
    _gset(c, "Value", i)
    return ""


@export()
def ControlChooseString(s, control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c = _need(_ctl(control, t, txt, xt, xx)[0], "DDL", "ComboBox", "ListBox", "Tab")
    sl = S(s).lower()
    idx = next((i for i, it in enumerate(_items(c), 1) if it.lower().startswith(sl)), 0)
    if not idx:
        throw("TargetError", "Target item not found.", S(s))
    _gset(c, "Value", idx)
    return idx


@export()
def ControlGetChecked(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c = _need(_ctl(control, t, txt, xt, xx)[0])
    if c.ctype not in ("CheckBox", "Radio"):
        return 0
    from .guiobj import ctrl_get
    return 1 if ctrl_get(c, "Value") == 1 else 0


@export()
def ControlSetChecked(value, control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c = _need(_ctl(control, t, txt, xt, xx)[0], "CheckBox", "Radio")
    from .guiobj import ctrl_get
    v = rt().to_int(value)
    cur = ctrl_get(c, "Value") == 1
    want = (not cur) if v == -1 else bool(v)
    if want != cur:
        _gset(c, "Value", int(want))
    return ""


@export()
def ControlGetItems(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c = _need(_ctl(control, t, txt, xt, xx)[0], "DDL", "ComboBox", "ListBox", "ListView", "Tab")
    return AhkArray(None, list(_items(c)))


@export()
def ControlGetChoice(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c = _need(_ctl(control, t, txt, xt, xx)[0], "DDL", "ComboBox", "ListBox", "Tab")
    from .guiobj import ctrl_get
    if c.ctype in ("DDL", "ComboBox") and ctrl_get(c, "Value") == 0:
        throw("Error", "Nothing is selected.")
    v = ctrl_get(c, "Text")
    return v if isinstance(v, str) else (S(v.items[0]) if v.items else "")


@export()
def ControlGetIndex(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c = _need(_ctl(control, t, txt, xt, xx)[0], "DDL", "ComboBox", "ListBox", "Tab")
    from .guiobj import ctrl_get
    v = ctrl_get(c, "Value")
    return v if isinstance(v, int) else (v.items[0] if v.items else 0)


WS_VISIBLE, WS_DISABLED, WS_CHILD, WS_TABSTOP = 0x10000000, 0x08000000, 0x40000000, 0x00010000


def _style_of(c):
    s = WS_CHILD | (WS_VISIBLE if c.visible else 0) | (WS_DISABLED if not c.enabled else 0)
    if c.ctype not in ("Text", "GroupBox", "Picture", "Progress", "StatusBar"):
        s |= WS_TABSTOP
    if c.ctype == "Edit":
        s |= 0x80 | (0x800 if c.readonly else 0) | (0x20 if c.password else 0)        # ES_AUTOHSCROLL etc.
    elif c.ctype == "CheckBox":
        s |= 0x3
    elif c.ctype == "Radio":
        s |= 0x9
    elif c.ctype == "GroupBox":
        s |= 0x7
    elif c.ctype == "DDL":
        s |= 0x3 | 0x200000
    elif c.ctype == "ComboBox":
        s |= 0x2 | 0x200000
    elif c.ctype == "ListBox":
        s |= 0x1 | (0x8 if c.multi else 0) | 0x200000
    elif c.ctype == "ListView":
        s |= 0x1
    return s


@export()
def ControlGetStyle(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c, win = _ctl(control, t, txt, xt, xx)
    return _style_of(c) if c is not None else WinGetStyle(win and f"ahk_id {win}")


@export()
def ControlGetExStyle(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c, win = _ctl(control, t, txt, xt, xx)
    if c is None:
        return 0
    if getattr(c, "exstyle", None) is not None:
        return c.exstyle
    return 0x200 if c.ctype in ("Edit", "ListBox", "ListView", "TreeView", "ComboBox", "DateTime", "Hotkey") else 0


def _new_style(cur, value):
    if isinstance(value, str) and value[:1] in ("+", "-", "^"):
        n = rt().to_int(value[1:])
        return cur | n if value[0] == "+" else cur & ~n if value[0] == "-" else cur ^ n
    return rt().to_int(value)


@export()
def ControlSetStyle(value, control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c, win = _ctl(control, t, txt, xt, xx)
    if c is None:
        return ""
    from .guiobj import ctrl_set_enabled, ctrl_set_visible, _srv
    new = _new_style(_style_of(c), value)
    if bool(new & WS_VISIBLE) != c.visible:
        ctrl_set_visible(c, int(bool(new & WS_VISIBLE)))
    if bool(new & WS_DISABLED) == c.enabled:
        ctrl_set_enabled(c, int(not new & WS_DISABLED))
    if c.ctype == "Edit" and bool(new & 0x800) != c.readonly:
        c.readonly = bool(new & 0x800)
        _srv().call("set", ctrl=c.cid, prop="ReadOnly", value=int(c.readonly))
    return ""


@export()
def ControlSetExStyle(value, control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c, win = _ctl(control, t, txt, xt, xx)
    if c is None:
        throw("TargetError", "Target control not found.")
    c.exstyle = _new_style(ControlGetExStyle(c), value) & 0xFFFFFFFF      # extended styles are cosmetic in GTK
    return ""


@export()
def ControlAddItem(s, control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c = _need(_ctl(control, t, txt, xt, xx)[0], "DDL", "ComboBox", "ListBox", "Tab")
    from .guiobj import _srv
    return _srv().call("items", ctrl=c.cid, add=[S(s)])


@export()
def ControlDeleteItem(n, control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c = _need(_ctl(control, t, txt, xt, xx)[0], "DDL", "ComboBox", "ListBox", "Tab")
    i = rt().to_int(n)
    if not 1 <= i <= len(_items(c)):
        throw("ValueError", "Parameter #1 of ControlDeleteItem is invalid.", n)
    from .guiobj import _srv
    _srv().call("items", ctrl=c.cid, delete=i)
    return ""


@export()
def ControlFindItem(s, control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c = _need(_ctl(control, t, txt, xt, xx)[0], "DDL", "ComboBox", "ListBox", "Tab")
    sl = S(s).lower()
    idx = next((i for i, it in enumerate(_items(c), 1) if it.lower() == sl), 0)
    if not idx:
        throw("TargetError", "Target item not found.", S(s))
    return idx


@export()
def ControlShowDropDown(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c = _need(_ctl(control, t, txt, xt, xx)[0], "DDL", "ComboBox")
    from .guiobj import _srv
    _srv().call("dropdown", ctrl=c.cid, show=True)
    return ""


@export()
def ControlHideDropDown(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c = _need(_ctl(control, t, txt, xt, xx)[0], "DDL", "ComboBox")
    from .guiobj import _srv
    _srv().call("dropdown", ctrl=c.cid, show=False)
    return ""


@export()
def ControlEditPaste(text, control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c, win = _ctl(control, t, txt, xt, xx)
    if c is not None:
        _need(c, "Edit", "ComboBox")
        from .guiobj import _srv
        if c.ctype == "ComboBox":
            from .guiobj import ctrl_get
            _gset(c, "Text", ctrl_get(c, "Text") + S(text))
        else:
            _srv().call("paste", ctrl=c.cid, text=S(text))
        return ""
    from .input_ import send_to_window
    send_to_window(win, S(text), raw=True)
    return ""


def _edit(control, t, txt, xt, xx, what):
    c = _need(_ctl(control, t, txt, xt, xx)[0], "Edit")
    from .guiobj import _srv
    return _srv().call("query", ctrl=c.cid, what=what)


@export()
def EditGetLineCount(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return len(_edit(control, t, txt, xt, xx, "lines"))


@export()
def EditGetCurrentLine(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return _edit(control, t, txt, xt, xx, "caret")[0]


@export()
def EditGetCurrentCol(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return _edit(control, t, txt, xt, xx, "caret")[1]


@export()
def EditGetLine(n, control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    lines = _edit(control, t, txt, xt, xx, "lines")
    i = rt().to_int(n)
    if not 1 <= i <= len(lines):
        throw("ValueError", "Parameter #1 of EditGetLine is invalid.", n)
    return lines[i - 1]


@export()
def EditGetSelectedText(control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    return _edit(control, t, txt, xt, xx, "seltext")


@export()
def ListViewGetContent(options="", control=UNSET, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c = _need(_ctl(control, t, txt, xt, xx)[0], "ListView")
    from .guiobj import _lv
    return _lv(c, "content", opts=S(options) if options is not UNSET else "")


def _statusbar(t, txt, xt, xx):
    from .guiobj import gui_for_window
    win = _win_arg(t, txt, xt, xx)
    g = gui_for_window(win)
    sb = next((c for c in g.ctrls if c.ctype == "StatusBar"), None) if g is not None else None
    if g is None:
        sb = next((f for f in _foreign_window(win) or [] if f.role == "status bar"), None)
    if sb is None:
        throw("TargetError", "Target control not found.")
    return sb


@export()
def StatusBarGetText(part=1, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    sb = _statusbar(t, txt, xt, xx)
    from .guiobj import sb_text
    return _sb_text(sb, rt().to_int(part) if part not in (UNSET, "") else 1)


def _sb_text(sb, part):
    from .guiobj import sb_text
    from .atspi_ import Foreign
    if isinstance(sb, Foreign):
        return sb.text() if part == 1 else ""
    return sb_text(sb, part)


@export()
def StatusBarWait(bartext=UNSET, timeout=UNSET, part=1, t=UNSET, txt=UNSET, interval=50, xt=UNSET, xx=UNSET):
    sb = _statusbar(t, txt, xt, xx)
    if sb is None:
        return 0
    want = S(bartext) if bartext is not UNSET else ""
    p = rt().to_int(part) if part not in (UNSET, "") else 1
    mode = rt().thread.settings.title_match_mode
    r = rt()
    end = None if timeout in (UNSET, "") else time.monotonic() + float(r.to_num(timeout))
    step = r.to_int(interval) if interval not in (UNSET, "") else 50
    while True:
        cur = _sb_text(sb, p)
        if (cur == "" if want == "" else _str_match(want, cur, mode)):
            return 1
        if end is not None and time.monotonic() >= end:
            return 0
        r.sleep(step)



@export()
def MenuSelect(t=UNSET, txt=UNSET, menu=UNSET, *rest):
    """Choose an item from one of this script's Gui menu bars (other apps' menus aren't reachable on X11)."""
    from .guiobj import gui_for_window
    names = [menu, *rest][:7]
    xt = names.pop() if len(names) == 7 else UNSET
    xx = UNSET
    win = _win_arg(t, txt, xt, xx)
    g = gui_for_window(win)
    path = [S(n) for n in names if n is not UNSET and S(n) != ""]
    if g is None:
        return _foreign_menu_select(win, path)
    if g.menubar is None:
        throw("TargetError", "Target menu not found.")
    m = g.menubar
    for depth, name in enumerate(path):
        it = m.find_item(name, required=False)
        if it is None:
            throw("TargetError", "Target menu item not found.", name)
        if depth == len(path) - 1:
            if it.sub is not None:
                throw("TargetError", "Target menu item is a submenu.", name)
            m.activate(m.items.index(it))
            return ""
        if it.sub is None:
            throw("TargetError", "Target menu item not found.", name)
        m = it.sub
    return ""


# ---------------------------------------------------------------- window messages
# SendMessage/PostMessage reach OnMessage handlers for this script's own windows, and the common Win32 messages are
# translated for this script's Gui controls and for any window (WM_CLOSE, WM_SYSCOMMAND).
WM_CLOSE, WM_SETTEXT, WM_GETTEXTLENGTH, WM_SYSCOMMAND = 0x10, 0x0C, 0x0E, 0x112


def _msg_target(control, t, txt, xt, xx):
    from .guiobj import GUIS
    if isinstance(control, AhkObject) or (control is not UNSET and S(control) != ""):
        c, win = _ctl(control, t, txt, xt, xx)
        return c, win
    if t is UNSET and txt is UNSET:
        throw("TargetError", "Target window not found.")
    if type(t) is int and any(g.wid == t for g in GUIS.values()):
        return None, next(g.xid or g.wid for g in GUIS.values() if g.wid == t)
    return None, _win_arg(t, txt, xt, xx)


def _num_arg(v):
    if isinstance(v, str) and not v.strip().lstrip("-").isdigit():
        from .strings import StrPtr
        return StrPtr(v)
    if isinstance(v, AhkObject):
        return rt().to_int(rt().get_prop(v, "Ptr"))
    return rt().to_int(v) if v not in (UNSET, "") else 0


def _builtin_message(c, win, msg, wp, lp):
    """Win32 messages with an X11/GTK meaning.  Returns (handled, result)."""
    from .guiobj import _srv, ctrl_get, gui_for_window, gui_state
    d = _dpy()
    if msg == WM_CLOSE and c is None:
        _client_msg(d, win, "_NET_CLOSE_WINDOW", [0, 2, 0, 0, 0])
        return True, 0
    if msg == WM_SYSCOMMAND and c is None:
        g = gui_for_window(win)
        sc = wp & 0xFFF0
        if sc == 0xF060:
            _client_msg(d, win, "_NET_CLOSE_WINDOW", [0, 2, 0, 0, 0])
        elif sc == 0xF020:
            gui_state(g, "min") if g else d.x.XIconifyWindow(d.dpy, win, d.x.XDefaultScreen(d.dpy))
        elif sc == 0xF030:
            gui_state(g, "max") if g else _wm_state(d, win, 1, "_NET_WM_STATE_MAXIMIZED_VERT",
                                                    "_NET_WM_STATE_MAXIMIZED_HORZ")
        elif sc == 0xF120:
            gui_state(g, "restore") if g else _wm_state(d, win, 0, "_NET_WM_STATE_MAXIMIZED_VERT",
                                                        "_NET_WM_STATE_MAXIMIZED_HORZ")
        else:
            return False, 0
        d.flush()
        return True, 0
    if c is None:
        return False, 0
    t = c.ctype
    if msg == 0xF5 and t in ("Button", "CheckBox", "Radio"):                  # BM_CLICK
        _srv().call("click", ctrl=c.cid)
        return True, 0
    if msg == 0xF0 and t in ("CheckBox", "Radio"):                            # BM_GETCHECK
        v = ctrl_get(c, "Value")
        return True, 2 if v == -1 else v
    if msg == 0xF1 and t in ("CheckBox", "Radio"):                            # BM_SETCHECK
        _gset(c, "Value", -1 if wp == 2 else int(bool(wp)), notify=False)
        return True, 0
    if (msg == 0x14E and t in ("DDL", "ComboBox")) or (msg == 0x186 and t == "ListBox") or \
            (msg == 0x130C and t == "Tab"):                                   # CB_/LB_/TCM_SETCURSEL
        _gset(c, "Value", (wp & 0xFFFFFFFF) + 1 if wp != -1 and wp != 0xFFFFFFFF else 0, notify=False)
        return True, wp
    if (msg == 0x147 and t in ("DDL", "ComboBox")) or (msg == 0x188 and t == "ListBox") or \
            (msg == 0x130B and t == "Tab"):                                   # CB_/LB_/TCM_GETCURSEL
        v = ctrl_get(c, "Value")
        v = v if isinstance(v, int) else (v.items[0] if v.items else 0)
        return True, v - 1
    if (msg == 0x146 and t in ("DDL", "ComboBox")) or (msg == 0x18B and t == "ListBox") or \
            (msg == 0x1304 and t == "Tab"):                                   # CB_/LB_/TCM_GETCOUNT
        return True, len(_items(c))
    if msg == 0xBA and t == "Edit":                                           # EM_GETLINECOUNT
        return True, len(_srv().call("query", ctrl=c.cid, what="lines"))
    if msg == WM_GETTEXTLENGTH:
        v = ctrl_get(c, "Text")
        return True, len(v) if isinstance(v, str) else 0
    if msg == WM_SETTEXT:
        from .buffer import StrGet
        _gset(c, "Text", StrGet(lp) if lp else "")
        return True, 1
    if msg == 0x0A:                                                          # WM_ENABLE
        from .guiobj import ctrl_set_enabled
        ctrl_set_enabled(c, int(bool(wp)))
        return True, 0
    return False, 0


def _deliver(msg, wp, lp, c, win, sync, timeout=5.0):
    from .flow import message_handlers
    from .guiobj import gui_for_window
    from . import ipc
    r = rt()
    hwnd = c.cid if c is not None else win
    main = bool(win) and win == getattr(r, "script_hwnd", 0) and c is None
    ours = c is not None or gui_for_window(win) is not None or main
    if not ours:
        d = _dpy()
        pid = pid_of(d, win) if d is not None and win else 0
        if pid and pid != os.getpid():
            delivered, result = ipc.send(pid, msg, wp, lp, win, sync, timeout)
            if delivered:
                return result
        return _builtin_message(c, win, msg, wp, lp)[1]
    if main and msg in (ipc.WM_CLOSE, ipc.WM_COMMAND) and not message_handlers(msg):
        if sync:
            return ipc.main_window_default(msg, wp)
        r.post(lambda: ipc.main_window_default(msg, wp))
        return 0
    handled, result = _builtin_message(c, win, msg, wp, lp)
    for fn in message_handlers(msg):
        if sync:
            res = r.call(fn, [wp, lp, msg, hwnd])
            if res != "" and res is not None:
                return res
        else:
            r.post(lambda fn=fn: r.call(fn, [wp, lp, msg, hwnd]))
    return result


@export()
def PostMessage(msg, wparam=0, lparam=0, control=UNSET, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    c, win = _msg_target(control, t, txt, xt, xx)
    _deliver(rt().to_int(msg), _num_arg(wparam), _num_arg(lparam), c, win, False)
    return ""


@export()
def SendMessage(msg, wparam=0, lparam=0, control=UNSET, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET, timeout=5000):
    c, win = _msg_target(control, t, txt, xt, xx)
    ms = rt().to_int(timeout) if timeout not in (UNSET, "") else 5000
    return _deliver(rt().to_int(msg), _num_arg(wparam), _num_arg(lparam), c, win, True, ms / 1000 if ms > 0 else None)


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


def screen_dpi():
    """A_ScreenDPI: Xft.dpi from the X resource database (what toolkits scale by), else the screen's physical DPI."""
    d = _dpy()
    if d is None:
        return 96
    res = d.get_string(d.root, "RESOURCE_MANAGER") or ""
    m = re.search(r"^Xft\.dpi:\s*([0-9.]+)", res, re.M)
    if m:
        return int(round(float(m.group(1))))
    scr = d.x.XDefaultScreen(d.dpy)
    mm = d.x.XDisplayWidthMM(d.dpy, scr)
    return int(round(d.x.XDisplayWidth(d.dpy, scr) * 25.4 / mm)) if mm else 96


# X cursor names (XFixes) -> A_Cursor values
_CURSORS = {"left_ptr": "Arrow", "default": "Arrow", "arrow": "Arrow", "top_left_arrow": "Arrow",
            "xterm": "IBeam", "text": "IBeam", "ibeam": "IBeam", "watch": "Wait", "wait": "Wait",
            "left_ptr_watch": "AppStarting", "progress": "AppStarting", "half-busy": "AppStarting",
            "crosshair": "Cross", "cross": "Cross", "tcross": "Cross", "question_arrow": "Help", "help": "Help",
            "fleur": "SizeAll", "move": "SizeAll", "all-scroll": "SizeAll", "size_all": "SizeAll",
            "sb_v_double_arrow": "SizeNS", "ns-resize": "SizeNS", "row-resize": "SizeNS", "v_double_arrow": "SizeNS",
            "top_side": "SizeNS", "bottom_side": "SizeNS", "n-resize": "SizeNS", "s-resize": "SizeNS",
            "sb_h_double_arrow": "SizeWE", "ew-resize": "SizeWE", "col-resize": "SizeWE", "h_double_arrow": "SizeWE",
            "left_side": "SizeWE", "right_side": "SizeWE", "e-resize": "SizeWE", "w-resize": "SizeWE",
            "fd_double_arrow": "SizeNWSE", "nwse-resize": "SizeNWSE", "top_left_corner": "SizeNWSE",
            "bottom_right_corner": "SizeNWSE", "nw-resize": "SizeNWSE", "se-resize": "SizeNWSE",
            "bd_double_arrow": "SizeNESW", "nesw-resize": "SizeNESW", "top_right_corner": "SizeNESW",
            "bottom_left_corner": "SizeNESW", "ne-resize": "SizeNESW", "sw-resize": "SizeNESW",
            "sb_up_arrow": "UpArrow", "up-arrow": "UpArrow", "center_ptr": "UpArrow",
            "not-allowed": "No", "crossed_circle": "No", "no-drop": "No", "circle": "No",
            "hand2": "Unknown", "hand1": "Unknown", "pointer": "Unknown", "pointing_hand": "Unknown"}


def cursor_name():
    """A_Cursor: the current mouse cursor's type, from the XFixes cursor name."""
    import ctypes
    from .. import xlib
    d = _dpy()
    xf = xlib._lib("Xfixes")
    if d is None or xf is None:
        return "Unknown"

    class XFixesCursorImage(ctypes.Structure):
        _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short), ("width", ctypes.c_ushort),
                    ("height", ctypes.c_ushort), ("xhot", ctypes.c_ushort), ("yhot", ctypes.c_ushort),
                    ("cursor_serial", ctypes.c_ulong), ("pixels", ctypes.c_void_p), ("atom", ctypes.c_ulong),
                    ("name", ctypes.c_char_p)]
    xf.XFixesGetCursorImage.restype = ctypes.POINTER(XFixesCursorImage)
    xf.XFixesGetCursorImage.argtypes = [ctypes.c_void_p]
    img = xf.XFixesGetCursorImage(d.dpy)
    if not img:
        return "Unknown"
    name = (img.contents.name or b"").decode(errors="replace")
    d.x.XFree.argtypes = [ctypes.c_void_p]
    d.x.XFree(img)
    return _CURSORS.get(name, "Unknown" if name else "Arrow")


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


def _monitors():
    """[(name, left, top, right, bottom, primary)] in AutoHotkey's order (primary first is NOT implied)."""
    from .. import xlib
    d = _dpy()
    mons = xlib.monitors(d) if d is not None else []
    if not mons:
        w, h = screen_size()
        return [("DISPLAY1", 0, 0, w, h, True)]
    return [(n, x, y, x + w, y + h, p) for n, x, y, w, h, p in mons]


def _monitor_n(n):
    mons = _monitors()
    if n is UNSET or n == "":
        return mons, next((i for i, m in enumerate(mons) if m[5]), 0)
    i = rt().to_int(n) - 1
    if not 0 <= i < len(mons):
        throw("ValueError", "Parameter #1 of MonitorGet is invalid.", n)
    return mons, i


@export(byref=(1, 2, 3, 4))
def MonitorGet(n=UNSET, left=UNSET, top=UNSET, right=UNSET, bottom=UNSET):
    mons, i = _monitor_n(n)
    _, l, t, r, b, _p = mons[i]
    setref(left, l); setref(top, t); setref(right, r); setref(bottom, b)
    return i + 1


@export(byref=(1, 2, 3, 4))
def MonitorGetWorkArea(n=UNSET, left=UNSET, top=UNSET, right=UNSET, bottom=UNSET):
    mons, i = _monitor_n(n)
    _, l, t, r, b, _p = mons[i]
    d = _dpy()
    wa = d.get_longs(d.root, "_NET_WORKAREA") if d else []
    if len(wa) >= 4:
        # _NET_WORKAREA spans all monitors; panels shrink it, so intersect it with this monitor
        wl, wt, wr, wb = int(wa[0]), int(wa[1]), int(wa[0] + wa[2]), int(wa[1] + wa[3])
        nl, nt, nr, nb = max(l, wl), max(t, wt), min(r, wr), min(b, wb)
        if nl < nr and nt < nb:
            l, t, r, b = nl, nt, nr, nb
    setref(left, l); setref(top, t); setref(right, r); setref(bottom, b)
    return i + 1


@export()
def MonitorGetCount():
    return len(_monitors())


@export()
def MonitorGetPrimary():
    return next((i + 1 for i, m in enumerate(_monitors()) if m[5]), 1)


@export()
def MonitorGetName(n=UNSET):
    mons, i = _monitor_n(n)
    return "\\\\.\\DISPLAY%d" % (i + 1)


@export()
def SysGet(n):
    i = rt().to_int(n)
    w, h = screen_size()
    if i in (76, 77, 78, 79, 80):
        mons = _monitors()
        vl, vt = min(m[1] for m in mons), min(m[2] for m in mons)
        vr, vb = max(m[3] for m in mons), max(m[4] for m in mons)
        return {76: vl, 77: vt, 78: vr - vl, 79: vb - vt, 80: len(mons)}[i]
    return {0: w, 1: h, 16: w, 17: h, 43: 3, 4: 23, 5: 1, 6: 1, 7: 3, 8: 3,
            32: 8, 33: 8, 19: 1}.get(i, 0)


# ---------------------------------------------------------------- other programs' controls (AT-SPI)
# When the Control parameter names a control in another program's window, the functions below act on it through
# the accessibility bus (lib/atspi_.py).  They are installed over the exported functions by _install_foreign().
def _win_info(win):
    d = _dpy()
    return win, pid_of(d, win), title_of(d, win) or ""


def _foreign(control, t, txt, xt, xx):
    """Another program's control named by the Control parameter, or None if it is this script's (or omitted)."""
    from .guiobj import CtrlObj, gui_for_window
    from . import atspi_
    if isinstance(control, CtrlObj) or control is UNSET or (isinstance(control, str) and control == ""):
        return None
    if isinstance(control, AhkObject):
        try:
            control = rt().to_int(rt().get_prop(control, "Hwnd"))
        except Exception:
            return None
    if type(control) is int:
        return atspi_.by_hwnd(control)
    win = _win_arg(t, txt, xt, xx)
    if gui_for_window(win) is not None:
        return None
    f = atspi_.find(*_win_info(win), control, rt().thread.settings.title_match_mode, _str_match) \
        if atspi_.available() else None
    if f is None:
        throw("TargetError", "Target control not found.", S(control))
    return f


def _no_change(*_):
    throw("OSError", "Other programs' controls can't be moved, shown, hidden or restyled on Linux "
                     "(AT-SPI has no such operation).")


def _f_style(f):
    return WS_CHILD | (WS_VISIBLE if f.visible() else 0) | (0 if f.enabled() else WS_DISABLED) | \
        (WS_TABSTOP if f.role not in ("label", "status bar", "image") else 0)


def _f_choose_string(f, s):
    sl = S(s).lower()
    idx = next((i for i, it in enumerate(f.items(), 1) if it.lower().startswith(sl)), 0)
    if not idx or not f.choose(idx):
        throw("TargetError", "Target item not found.", S(s))
    return idx


def _f_find_item(f, s):
    sl = S(s).lower()
    idx = next((i for i, it in enumerate(f.items(), 1) if it.lower() == sl), 0)
    if not idx:
        throw("TargetError", "Target item not found.", S(s))
    return idx


def _f_line(f, n):
    lines = f.lines()
    i = rt().to_int(n)
    if not 1 <= i <= len(lines):
        throw("ValueError", "Parameter #1 of EditGetLine is invalid.", n)
    return lines[i - 1]


def _f_lv_content(f, options):
    o = S(options).lower().split() if options is not UNSET else []
    rows = f.table_rows(selected="selected" in o or "focused" in o)
    if "count" in o:
        return len(rows) if "col" not in o else f.n_columns()
    col = next((int(t[3:]) - 1 for t in o if t.startswith("col") and t[3:].isdigit()), None)
    if "focused" in o:
        rows = rows[:1]
    return "\n".join("\t".join(r if col is None else r[col:col + 1]) for r in rows)


def _f_send(f, keys, raw):
    from .input_ import send_to_window
    f.focus()
    send_to_window(f.win, S(keys), raw=raw)
    return ""


def _f_pos(f, x, y, w, h):
    px, py, pw, ph = f.pos()
    setref(x, px); setref(y, py); setref(w, pw); setref(h, ph)
    return ""


def _f_checked(f, v):
    n = rt().to_int(v)
    f.set_checked((not f.checked()) if n == -1 else bool(n))
    return ""


def _f_choose(f, n):
    i = rt().to_int(n)
    if not f.choose(i):
        throw("ValueError", "Parameter #1 of ControlChooseIndex is invalid.", n)
    return ""


def _f_set_text(f, s):
    if not f.set_text(S(s)):
        throw("OSError", "The control's text can't be changed.")
    return ""


def _f_choice(f):
    if f.role == "combo box":
        return f.text()
    i = f.index()
    items = f.items()
    return items[i - 1] if 0 < i <= len(items) else ""


# function name -> (index of Control, index of WinTitle, index of ExcludeTitle, handler(f, *args))
_FOREIGN = {
    "ControlGetText": (0, 1, 3, lambda f, *a: f.text()),
    "ControlSetText": (1, 2, 4, lambda f, s, *a: _f_set_text(f, s)),
    "ControlClick": (0, 1, 6, lambda f, *a: (f.focus(), f.click(), "")[-1]),
    "ControlFocus": (0, 1, 3, lambda f, *a: (f.focus(), "")[-1]),
    "ControlGetHwnd": (0, 1, 3, lambda f, *a: f.hwnd),
    "ControlGetPos": (4, 5, 7, lambda f, x, y, w, h, *a: _f_pos(f, x, y, w, h)),
    "ControlGetVisible": (0, 1, 3, lambda f, *a: f.visible()),
    "ControlGetEnabled": (0, 1, 3, lambda f, *a: f.enabled()),
    "ControlGetClassNN": (0, 1, 3, lambda f, *a: f.classnn),
    "ControlMove": (4, 5, 7, _no_change),
    "ControlShow": (0, 1, 3, _no_change),
    "ControlHide": (0, 1, 3, _no_change),
    "ControlSetEnabled": (1, 2, 4, _no_change),
    "ControlSetStyle": (1, 2, 4, _no_change),
    "ControlSetExStyle": (1, 2, 4, _no_change),
    "ControlAddItem": (1, 2, 4, _no_change),
    "ControlDeleteItem": (1, 2, 4, _no_change),
    "ControlGetStyle": (0, 1, 3, lambda f, *a: _f_style(f)),
    "ControlGetExStyle": (0, 1, 3, lambda f, *a: 0x200 if f.role in TEXTUAL_ROLES else 0),
    "ControlChooseIndex": (1, 2, 4, lambda f, n, *a: _f_choose(f, n)),
    "ControlChooseString": (1, 2, 4, lambda f, s, *a: _f_choose_string(f, s)),
    "ControlGetChecked": (0, 1, 3, lambda f, *a: f.checked()),
    "ControlSetChecked": (1, 2, 4, lambda f, v, *a: _f_checked(f, v)),
    "ControlGetItems": (0, 1, 3, lambda f, *a: AhkArray(None, f.items())),
    "ControlGetChoice": (0, 1, 3, lambda f, *a: _f_choice(f)),
    "ControlGetIndex": (0, 1, 3, lambda f, *a: f.index()),
    "ControlFindItem": (1, 2, 4, lambda f, s, *a: _f_find_item(f, s)),
    "ControlShowDropDown": (0, 1, 3, lambda f, *a: (f.do_action("press", "click"), "")[-1]),
    "ControlHideDropDown": (0, 1, 3, lambda f, *a: (f.do_action("press", "click"), "")[-1]),
    "ControlEditPaste": (1, 2, 4, lambda f, s, *a: (f.insert(S(s)), "")[-1]),
    "ControlSend": (1, 2, 4, lambda f, k, *a: _f_send(f, k, False)),
    "ControlSendText": (1, 2, 4, lambda f, k, *a: _f_send(f, k, True)),
    "EditGetLineCount": (0, 1, 3, lambda f, *a: len(f.lines())),
    "EditGetCurrentLine": (0, 1, 3, lambda f, *a: f.caret()[0]),
    "EditGetCurrentCol": (0, 1, 3, lambda f, *a: f.caret()[1]),
    "EditGetLine": (1, 2, 4, lambda f, n, *a: _f_line(f, n)),
    "EditGetSelectedText": (0, 1, 3, lambda f, *a: f.seltext()),
    "ListViewGetContent": (1, 2, 4, lambda f, o, *a: _f_lv_content(f, o)),
}
TEXTUAL_ROLES = {"text", "password text", "entry", "spin button", "editbar", "document frame", "terminal"}


def _install_foreign():
    import functools
    from . import EXPORTS
    g = globals()
    for i, (name, fn, byref) in enumerate(EXPORTS):
        spec = _FOREIGN.get(name)
        if spec is None or getattr(fn, "_foreign", False):
            continue
        ci, ti, xi, handler = spec

        def make(fn=fn, ci=ci, ti=ti, xi=xi, handler=handler):
            @functools.wraps(fn)
            def wrapper(*args):
                a = list(args) + [UNSET] * 12
                f = _foreign(a[ci], a[ti], a[ti + 1], a[xi], a[xi + 1])
                return handler(f, *args) if f is not None else fn(*args)
            wrapper._foreign = True
            return wrapper
        w = make()
        EXPORTS[i] = (name, w, byref)
        g[name] = w


def _foreign_window(win):
    """(controls) of another program's window via AT-SPI, or None if it is this script's or AT-SPI is off."""
    from .guiobj import gui_for_window
    from . import atspi_
    if not win or gui_for_window(win) is not None or not atspi_.available():
        return None
    return atspi_.controls(*_win_info(win))


def _foreign_menu_select(win, path):
    """MenuSelect on another program's menu bar through AT-SPI (names match without "&", case-insensitively;
    "N&" picks the Nth item)."""
    from . import atspi_
    if not atspi_.available():
        throw("TargetError", "Target menu not found.")
    root = atspi_.window_accessible(*_win_info(win))
    bar = next((a for a in atspi_._descendants(root, 4) if a.get_role_name() == "menu bar"), None) if root else None
    if bar is None:
        throw("TargetError", "Target menu not found.")
    node = bar
    for depth, name in enumerate(path):
        items = [a for a in atspi_._descendants(node, 2)
                 if a.get_role_name() in ("menu", "menu item", "check menu item", "radio menu item")
                 and a.get_parent() in (node,) + tuple(c for c in atspi_._children(node) if c.get_role_name() == "menu")]
        want = name.replace("&", "").lower()
        hit = None
        if name.endswith("&") and name[:-1].isdigit():
            i = int(name[:-1]) - 1
            hit = items[i] if 0 <= i < len(items) else None
        else:
            hit = next((a for a in items if (a.get_name() or "").replace("_", "").lower() == want), None)
        if hit is None:
            throw("TargetError", "Target menu item not found.", name)
        f = atspi_.Foreign(hit, hit.get_role_name(), "", 0, win)
        if depth == len(path) - 1:
            f.do_action("click", "activate")
            return ""
        node = hit
    return ""


_install_foreign()
