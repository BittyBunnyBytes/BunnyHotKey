"""DllCall: Win32 API emulation table (the Wine-like part) plus real calls into Linux shared libraries."""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import struct
import time

from .. import objects as O
from ..objects import AhkObject, VarRef, throw
from ..values import UNSET
from . import export, setref

_T0 = time.monotonic()


def S(v):
    return O.RT.to_str(v)


def I(v):
    return O.RT.to_int(v)


def _split_args(args):
    """[(type, value), ...], return_type"""
    a = list(args)
    ret = "Int"
    if len(a) % 2 == 1:
        ret = S(a.pop())
    pairs = [(S(a[i]), a[i + 1]) for i in range(0, len(a), 2)]
    return pairs, ret


def _write_out(target, fmt, value):
    """Write to an output arg: VarRef (Int* etc.) or Buffer/pointer."""
    if isinstance(target, VarRef):
        target.cell.value = value
        return
    from .buffer import resolve
    data, idx = resolve(target)
    struct.pack_into("<" + fmt, data, idx, value)


def _vk_state(vk):
    from .. import keys as K
    from .input_ import backend
    k = K.from_vk(I(vk))
    if k is None:
        return 0
    b = backend()
    down = b.key_state(k.code, physical=False) if k.kind == "key" else b.key_state(k.code, physical=False)
    return -32768 if down else 0


def _msgbox(pairs):
    from .gui import MsgBox
    vals = [p[1] for p in pairs]
    text = S(vals[1]) if len(vals) > 1 else ""
    title = S(vals[2]) if len(vals) > 2 else ""
    opts = I(vals[3]) if len(vals) > 3 else 0
    res = MsgBox(text, title, opts)
    return {"OK": 1, "Cancel": 2, "Abort": 3, "Retry": 4, "Ignore": 5, "Yes": 6, "No": 7, "TryAgain": 10,
            "Continue": 11}.get(res, 1)


def _cursor_pos(pairs):
    from .input_ import backend
    x, y = backend().mouse_pos()
    target = pairs[0][1]
    from .buffer import resolve
    data, idx = resolve(target)
    struct.pack_into("<ii", data, idx, x, y)
    return 1


def _keybd_event(pairs):
    from .. import keys as K
    from .input_ import backend
    vk = I(pairs[0][1])
    flags = I(pairs[2][1]) if len(pairs) > 2 else 0
    k = K.from_vk(vk)
    if k is not None:
        b = backend()
        b.key(k.code, not (flags & 2))
        b.flush()
    return 0


def _set_cursor(pairs):
    from .input_ import backend
    b = backend()
    b.move(I(pairs[0][1]), I(pairs[1][1]))
    b.flush()
    return 1


def _qpc(pairs):
    _write_out(pairs[0][1], "q", int(time.perf_counter_ns() // 100))
    return 1


def _qpf(pairs):
    _write_out(pairs[0][1], "q", 10_000_000)
    return 1


def _active(pairs):
    from .window import _dpy, active_window
    d = _dpy()
    return active_window(d) if d else 0


def _sleep(pairs):
    time.sleep(I(pairs[0][1]) / 1000.0)
    return 0


def _beep(pairs):
    from .sound import SoundBeep
    SoundBeep(pairs[0][1], pairs[1][1] if len(pairs) > 1 else 150)
    return 1


def _lock(pairs):
    import subprocess
    subprocess.Popen(["loginctl", "lock-session"])
    return 1


def _suspend(pairs):
    import subprocess
    subprocess.Popen(["systemctl", "suspend"])
    return 1


def _sysmetrics(pairs):
    from .window import SysGet
    return SysGet(pairs[0][1])


def _get_window_text(pairs):
    from .window import _dpy, title_of
    from .buffer import resolve
    d = _dpy()
    t = (title_of(d, I(pairs[0][1])) or "") if d else ""
    n = I(pairs[2][1]) if len(pairs) > 2 else 256
    t = t[:max(n - 1, 0)]
    target = pairs[1][1]
    if isinstance(target, VarRef):
        target.cell.value = t
    else:
        data, idx = resolve(target)
        raw = t.encode("utf-16-le") + b"\0\0"
        data[idx:idx + len(raw)] = raw
    return len(t)


EMU = {
    "sleep": _sleep,
    "gettickcount": lambda p: int((time.monotonic()) * 1000) & 0xFFFFFFFF,
    "gettickcount64": lambda p: int(time.monotonic() * 1000),
    "queryperformancecounter": _qpc,
    "queryperformancefrequency": _qpf,
    "getcurrentprocessid": lambda p: os.getpid(),
    "getcurrentthreadid": lambda p: os.getpid(),
    "getlasterror": lambda p: O.RT.last_error,
    "setlasterror": lambda p: setattr(O.RT, "last_error", I(p[0][1])) or 0,
    "messagebox": _msgbox, "messageboxw": _msgbox, "messageboxa": _msgbox,
    "messagebeep": lambda p: _beep([("UInt", 800), ("UInt", 100)]),
    "beep": _beep,
    "getcursorpos": _cursor_pos,
    "setcursorpos": _set_cursor,
    "getforegroundwindow": _active,
    "getactivewindow": _active,
    "getsystemmetrics": _sysmetrics,
    "getkeystate": lambda p: _vk_state(p[0][1]),
    "getasynckeystate": lambda p: _vk_state(p[0][1]),
    "keybd_event": _keybd_event,
    "blockinput": lambda p: 1,
    "isuseranadmin": lambda p: int(os.geteuid() == 0),
    "lockworkstation": _lock,
    "setsuspendstate": _suspend,
    "sendmessage": lambda p: _send_message(p, True), "postmessage": lambda p: _send_message(p, False),
    "enumwindows": lambda p: _enum_windows(p),
    "getdpiforwindow": lambda p: 96, "getdpiforsystem": lambda p: 96,
    "setprocessdpiaware": lambda p: 1, "setthreaddpiawarenesscontext": lambda p: 0,
    "iswindowvisible": lambda p: _is_window(p, True), "iswindow": lambda p: _is_window(p, False),
    "getwindowtextw": _get_window_text, "getwindowtext": _get_window_text,
    "systemparametersinfo": lambda p: 0, "systemparametersinfow": lambda p: 0,
    "timebeginperiod": lambda p: 0, "timeendperiod": lambda p: 0,
    "setcurrentprocessexplicitappusermodelid": lambda p: 0,
    "coinitialize": lambda p: 0, "couninitialize": lambda p: 0,
    "globalmemorystatusex": lambda p: 0,
    "getsystemtimeasfiletime": lambda p: (_write_out(p[0][1], "q", int((time.time() + 11644473600) * 10_000_000)), 0)[1],
    "getmenuitemcount": lambda p: _menu_count(p),
    "mapwindowpoints": lambda p: _map_window_points(p),
    "getsyscolor": lambda p: _sys_color(I(p[0][1])),
    "setwindowtheme": lambda p: 0,                       # uxtheme: S_OK; GTK draws with its own theme
    "setthreaddpihostingbehavior": lambda p: 0,
}

# GetSysColor index -> GTK theme colour (the desktop's real scheme); others keep Windows 10's defaults
_THEME_OF = {15: "theme_bg_color", 4: "theme_bg_color", 0: "theme_bg_color", 12: "theme_bg_color",
             22: "theme_bg_color", 25: "theme_bg_color", 30: "theme_bg_color", 5: "theme_base_color",
             8: "theme_text_color", 18: "theme_fg_color", 7: "theme_fg_color", 9: "theme_fg_color",
             19: "theme_fg_color", 13: "theme_selected_bg_color", 29: "theme_selected_bg_color",
             14: "theme_selected_fg_color", 17: "insensitive_fg_color", 26: "link_color", 16: "borders",
             10: "borders", 11: "borders", 3: "theme_unfocused_bg_color"}
_THEME = None


def _sys_color(n):
    global _THEME
    if _THEME is None:
        try:
            from .guiobj import _srv
            _THEME = _srv().call("syscolors") or {}
        except Exception:
            _THEME = {}
    hexrgb = _THEME.get(_THEME_OF.get(n, ""))
    if hexrgb:
        r, g, b = int(hexrgb[0:2], 16), int(hexrgb[2:4], 16), int(hexrgb[4:6], 16)
        return (b << 16) | (g << 8) | r                  # COLORREF 0x00BBGGRR
    return _SYS_COLORS.get(n, 0)


# GetSysColor fallback: Windows 10's default colour scheme (COLORREF, 0x00BBGGRR)
_SYS_COLORS = {0: 0xC8C8C8, 1: 0x000000, 2: 0xD1B499, 3: 0xDBCDBF, 4: 0xF0F0F0, 5: 0xFFFFFF, 6: 0x646464,
               7: 0x000000, 8: 0x000000, 9: 0x000000, 10: 0xB4B4B4, 11: 0xFCF7F4, 12: 0xABABAB, 13: 0xD77800,
               14: 0xFFFFFF, 15: 0xF0F0F0, 16: 0xA0A0A0, 17: 0x6D6D6D, 18: 0x000000, 19: 0x000000,
               20: 0xFFFFFF, 21: 0x696969, 22: 0xE3E3E3, 23: 0x000000, 24: 0xE1FFFF, 26: 0xCC6600,
               27: 0xEAD1B9, 28: 0xF2E4D7, 29: 0xD77800, 30: 0xF0F0F0}


def _client_origin(h):
    """Screen position of a window's (or one of this script's controls') client area; 0 = the screen."""
    if not h:
        return 0, 0
    from .guiobj import CTRLS, gui_for_window
    from .window import _dpy, geometry
    d = _dpy()
    c = CTRLS.get(h)
    if c is not None:
        gx, gy = _client_origin(c.gui.xid or c.gui.wid)
        return gx + (c.x or 0), gy + (c.y or 0)
    g = gui_for_window(h)
    win = g.xid if g is not None and g.xid else h
    x, y, _, _ = geometry(d, win, client=True)
    return x, y


def _map_window_points(p):
    """MapWindowPoints(hFrom, hTo, lpPoints, cPoints): returns LOWORD dx | HIWORD dy, like user32."""
    import struct
    from .buffer import resolve
    fx, fy = _client_origin(I(p[0][1]))
    tx, ty = _client_origin(I(p[1][1]))
    dx, dy = fx - tx, fy - ty
    n = I(p[3][1]) if len(p) > 3 else 1
    data, idx = resolve(p[2][1])
    for k in range(n):
        x, y = struct.unpack_from("<2i", data, idx + 8 * k)
        struct.pack_into("<2i", data, idx + 8 * k, x + dx, y + dy)
    return ((dy & 0xFFFF) << 16) | (dx & 0xFFFF)


def _menu_count(p):
    """GetMenuItemCount on a Menu.Handle of this script (separators count as items); -1 for other handles."""
    from .guiobj import MENUS
    m = MENUS.get(I(p[0][1]))
    if m is None:
        for mm in MENUS.values():
            if mm.mid == I(p[0][1]):
                m = mm
                break
    return len(m.items) if m is not None else -1

_CTYPES = {"int": ctypes.c_int, "uint": ctypes.c_uint, "int64": ctypes.c_int64, "uint64": ctypes.c_uint64,
           "short": ctypes.c_short, "ushort": ctypes.c_ushort, "char": ctypes.c_byte, "uchar": ctypes.c_ubyte,
           "float": ctypes.c_float, "double": ctypes.c_double, "ptr": ctypes.c_void_p, "uptr": ctypes.c_void_p,
           "astr": ctypes.c_char_p, "str": ctypes.c_wchar_p, "wstr": ctypes.c_wchar_p}


def _linux_call(libname, fname, pairs, ret):
    path = libname
    if not os.path.exists(path):
        path = ctypes.util.find_library(libname.replace("lib", "", 1).split(".so")[0]) or libname
    try:
        lib = ctypes.CDLL(path)
        fn = getattr(lib, fname)
    except (OSError, AttributeError):
        throw("Error", "Call to nonexistent function.", f"{libname}\\{fname}")
    return _c_call(fn, pairs, ret)


def _c_call(fn, pairs, ret):
    """Call a native function with AutoHotkey-typed arguments."""
    cargs = []
    outs = []
    for t, v in pairs:
        tl = t.lower().replace("cdecl", "").strip()
        star = tl.endswith("*") or tl.endswith("p") and tl[:-1] in _CTYPES
        base = tl.rstrip("*")
        if base.endswith("p") and base[:-1] in _CTYPES:
            base = base[:-1]
            star = True
        ct = _CTYPES.get(base, ctypes.c_int64)
        if star:
            cell = ct(O.RT.to_num(v.cell.value) if isinstance(v, VarRef) and v.cell.value not in (UNSET, "") else 0)
            cargs.append(ctypes.byref(cell))
            outs.append((v, cell))
        elif base == "astr":
            cargs.append(S(v).encode())
        elif base in ("str", "wstr"):
            cargs.append(S(v))
        elif base == "ptr" and isinstance(v, AhkObject):
            from .buffer import BufferObj
            if isinstance(v, BufferObj):
                buf = (ctypes.c_char * len(v.data)).from_buffer(v.data)
                cargs.append(ctypes.cast(buf, ctypes.c_void_p))
            else:
                cargs.append(ct(0))
        elif ct in (ctypes.c_float, ctypes.c_double):
            cargs.append(ct(float(O.RT.to_num(v))))
        else:
            cargs.append(ct(int(O.RT.to_num(v))))
    rl = ret.lower().replace("cdecl", "").strip()
    fn.restype = _CTYPES.get(rl, ctypes.c_int)
    r = fn(*cargs)
    for ref, cell in outs:
        setref(ref, cell.value)
    if isinstance(r, bytes):
        return r.decode("utf-8", "replace")
    return r if r is not None else 0


@export()
def DllCall(func, *args):
    pairs, ret = _split_args(args)
    if isinstance(func, AhkObject):
        func = I(O.RT.get_prop(func, "Ptr"))
    if type(func) is int:
        return call_address(func, pairs, ret)
    name = S(func).replace("/", "\\")
    lib, _, fn = name.rpartition("\\")
    if lib and (".so" in lib or lib.startswith("lib")) and not lib.lower().endswith(".dll"):
        return _linux_call(lib, fn, pairs, ret)
    if not lib:
        for handle in _LOADED:
            f = getattr(handle, fn, None)
            if f is not None:
                return _c_call(f, pairs, ret)
    key = fn.lower()
    if key.endswith(".dll"):
        key = key[:-4]
    h = EMU.get(key) or EMU.get(key.rstrip("w").rstrip("a"))
    if h is not None:
        return h(pairs)
    throw("Error", f"DllCall: {fn} is a Windows API that Bunny Hot Key does not emulate yet.", name)


# ---------------------------------------------------------------- callbacks and calls by address
_CALLBACKS: dict[int, tuple] = {}


def _arg_value(v):
    if isinstance(v, AhkObject):
        try:
            return I(O.RT.get_prop(v, "Ptr"))
        except Exception:
            return id(v)
    if isinstance(v, str) and not v.strip().lstrip("-").isdigit():
        from .strings import StrPtr
        return StrPtr(v)
    return O.RT.to_num(v) if v not in (UNSET, "") else 0


def call_address(addr, pairs, ret="Int"):
    """DllCall(address): a CallbackCreate address runs the script function directly; any other address is called
    as a native (cdecl) function pointer, as AutoHotkey does."""
    emu = _PSEUDO_FN.get(addr)
    if emu is not None:
        return EMU[emu](pairs)
    cb = _CALLBACKS.get(addr)
    if cb is not None:
        r = O.RT.call(cb[1], [_arg_value(v) for _, v in pairs])
        return r if r not in (UNSET,) else ""
    if addr == 0:
        throw("Error", "Invalid function address.", "DllCall")
    return _c_call(ctypes.CFUNCTYPE(ctypes.c_int64)(addr), pairs, ret)


@export()
def CallbackCreate(fn, options="", count=UNSET):
    """A native function pointer that calls the script function (usable by Linux libraries, e.g. qsort, and by the
    emulated Win32 APIs such as EnumWindows)."""
    opts = S(options).lower().split() if options not in (UNSET, "") else []
    if count in (UNSET, ""):
        try:
            n = I(O.RT.get_prop(fn, "MinParams"))
        except Exception:
            n = 0
    else:
        n = I(count)
    by_addr = "&" in opts or any(o.startswith("&") for o in opts)
    from .buffer import BufferObj

    def tramp(*args):
        try:
            if by_addr:
                b = BufferObj(8 * max(n, 1))
                b.data[:] = ctypes.string_at(args[0], 8 * max(n, 1))
                call_args = [b.addr]
            else:
                call_args = list(args)
            r = O.RT.call(fn, call_args)
            return int(O.RT.to_num(r)) if r not in ("", UNSET, None) else 0
        except Exception:
            return 0
    proto = ctypes.CFUNCTYPE(ctypes.c_ssize_t, *([ctypes.c_ssize_t] * (1 if by_addr else n)))
    cf = proto(tramp)
    addr = ctypes.cast(cf, ctypes.c_void_p).value
    _CALLBACKS[addr] = (cf, fn, by_addr, n)
    return addr


@export()
def CallbackFree(addr):
    if _CALLBACKS.pop(I(addr), None) is None:
        throw("ValueError", "Parameter #1 of CallbackFree is invalid.", addr)
    return ""


def _enum_windows(pairs):
    from .window import _dpy, client_list
    cb = I(pairs[0][1])
    lp = _arg_value(pairs[1][1]) if len(pairs) > 1 else 0
    d = _dpy()
    for w in (client_list(d, True) if d else []):
        if not I(call_address(cb, [("Ptr", w), ("Ptr", lp)], "Int") or 0):
            break
    return 1


def _is_window(pairs, visible):
    from .guiobj import CTRLS
    from .window import _dpy, client_list, is_visible
    h = I(pairs[0][1]) if pairs else 0
    if h in CTRLS:
        return int(CTRLS[h].visible) if visible else 1
    d = _dpy()
    if d is None or h not in client_list(d, True):
        return 0
    return int(is_visible(d, h)) if visible else 1


def _send_message(pairs, sync):
    from .window import SendMessage, PostMessage
    from .guiobj import CTRLS
    h, msg = I(pairs[0][1]), I(pairs[1][1])
    wp = _arg_value(pairs[2][1]) if len(pairs) > 2 else 0
    lp = _arg_value(pairs[3][1]) if len(pairs) > 3 else 0
    from .atspi_ import by_hwnd
    if h in CTRLS or by_hwnd(h) is not None:
        return (SendMessage if sync else PostMessage)(msg, wp, lp, h)
    return (SendMessage if sync else PostMessage)(msg, wp, lp, UNSET, f"ahk_id {h}") if sync else \
        (PostMessage(msg, wp, lp, UNSET, f"ahk_id {h}"), 1)[1]


@export()
def ClipWait(timeout=UNSET, wait_for_any=0):
    from .clipboard import clip_wait
    return clip_wait(None if timeout is UNSET else float(O.RT.to_num(timeout)), wait_for_any)


_LOADED: list = []          # libraries preloaded with #DllLoad, searched by DllCall("FunctionName")


def dll_load(spec):
    """#DllLoad [*i] FileOrDirName.  Linux shared libraries are loaded so their functions can be called by bare
    name.  A Windows DLL that doesn't exist here is skipped, so scripts that preload one still load (calls into
    it raise a clear error), and *i suppresses the error for a missing library, as in AutoHotkey."""
    s = spec.strip()
    optional = s.lower().startswith("*i ")
    if optional:
        s = s[3:].strip()
    if not s:
        return True
    from .files import host_path
    path = host_path(s) if ("/" in s or "\\" in s) else s
    if s.lower().endswith(".dll") or s.lower().endswith(".dll\""):
        return True
    for candidate in (path, ctypes.util.find_library(os.path.basename(s).replace("lib", "", 1).split(".so")[0]) or ""):
        if candidate:
            try:
                _LOADED.append(ctypes.CDLL(candidate))
                return True
            except OSError:
                continue
    return optional


# ---------------------------------------------------------------- more Win32 emulation: windows
def _arg(pairs, i, default=0):
    return pairs[i][1] if len(pairs) > i else default


def _null(v):
    return v is UNSET or v == "" or (type(v) is int and v == 0) or (isinstance(v, float) and v == 0)


def _int32(v):
    v = int(_arg_value(v)) & 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def _hwnd(v):
    """A window handle argument; HWND_TOPMOST etc. come back signed whatever type the script declared."""
    v = int(_arg_value(v)) & 0xFFFFFFFFFFFFFFFF
    return v - (1 << 64) if v & (1 << 63) else v


def _fail(code, ret=0):
    O.RT.last_error = code
    return ret


ERROR_INVALID_WINDOW_HANDLE, ERROR_MOD_NOT_FOUND, ERROR_PROC_NOT_FOUND = 1400, 126, 127
ERROR_INSUFFICIENT_BUFFER, ERROR_BUFFER_OVERFLOW, ERROR_ENVVAR_NOT_FOUND = 122, 111, 203


def _put_str(target, s, wide=True):
    """Write a NUL-terminated string to an output argument (VarRef, Buffer or address)."""
    if isinstance(target, VarRef):
        target.cell.value = s
        return
    if _null(target) or isinstance(target, str) and not target.lstrip("-").isdigit():
        return
    from .buffer import resolve
    data, idx = resolve(target)
    raw = s.encode("utf-16-le") + b"\0\0" if wide else s.encode("utf-8", "replace") + b"\0"
    data[idx:idx + len(raw)] = raw


def _get_str(v, wide=True):
    """A string argument passed as Str/AStr (a script string) or as a pointer."""
    if _null(v):
        return None
    if isinstance(v, str) and not v.strip().lstrip("-").isdigit():
        return v
    if isinstance(v, VarRef):
        return S(v.cell.value)
    from .buffer import StrGet
    return StrGet(v, UNSET, "UTF-16" if wide else "UTF-8")


def _get_num(v, fmt="I"):
    if isinstance(v, VarRef):
        x = v.cell.value
        return 0 if x in (UNSET, "") else I(x)
    from .buffer import resolve
    data, idx = resolve(v)
    return struct.unpack_from("<" + fmt, data, idx)[0]


def _wide(pairs, i):
    """Whether argument i was declared as an ANSI string (AStr)."""
    return not (len(pairs) > i and pairs[i][0].lower().startswith("astr"))


def _win(h):
    """-> (display, X window, Gui control or None) for a handle, or (d, 0, None) when it isn't a window."""
    from .guiobj import CTRLS
    from .window import _dpy, client_list
    d = _dpy()
    c = CTRLS.get(h)
    if c is not None and not c.gui.destroyed:
        return d, c.gui.xid, c
    if d is None or not h or h not in client_list(d, True):
        return d, 0, None
    return d, h, None


def _rect(pairs, client):
    from .window import geometry
    d, w, c = _win(_hwnd(_arg(pairs, 0)))
    if not w:
        return _fail(ERROR_INVALID_WINDOW_HANDLE)
    if c is not None:
        gx, gy, _, _ = geometry(d, w, client=True)
        x, y = (0, 0) if client else (gx + c.x, gy + c.y)
        cw, ch = c.w, c.h
    else:
        x, y, cw, ch = geometry(d, w, client=client)
        if client:
            x = y = 0
    from .buffer import resolve
    data, idx = resolve(_arg(pairs, 1))
    struct.pack_into("<iiii", data, idx, x, y, x + cw, y + ch)
    return 1


def _move_window(pairs):
    from .window import WinMove
    from .guiobj import _ctrl_move
    d, w, c = _win(_hwnd(_arg(pairs, 0)))
    if not w:
        return _fail(ERROR_INVALID_WINDOW_HANDLE)
    x, y, cw, ch = (I(_arg(pairs, i)) for i in range(1, 5))
    if c is not None:
        _ctrl_move(c, x, y, cw, ch)
    else:
        WinMove(x, y, cw, ch, f"ahk_id {w}")
    return 1


SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10
SWP_SHOWWINDOW, SWP_HIDEWINDOW = 0x40, 0x80


def _set_window_pos(pairs):
    from .window import WinMove, _wm_state, activate, geometry
    d, w, c = _win(_hwnd(_arg(pairs, 0)))
    if not w:
        return _fail(ERROR_INVALID_WINDOW_HANDLE)
    after = _hwnd(_arg(pairs, 1))
    x, y, cw, ch = (I(_arg(pairs, i)) for i in range(2, 6))
    flags = I(_arg(pairs, 6))
    if c is not None:
        from .guiobj import _ctrl_move, ctrl_set_visible
        _ctrl_move(c, UNSET if flags & SWP_NOMOVE else x, UNSET if flags & SWP_NOMOVE else y,
                   UNSET if flags & SWP_NOSIZE else cw, UNSET if flags & SWP_NOSIZE else ch)
        if flags & SWP_SHOWWINDOW:
            ctrl_set_visible(c, 1)
        elif flags & SWP_HIDEWINDOW:
            ctrl_set_visible(c, 0)
        return 1
    if not flags & SWP_NOZORDER:
        if after == -1:                                             # HWND_TOPMOST
            _wm_state(d, w, 1, "_NET_WM_STATE_ABOVE")
        elif after == -2:                                           # HWND_NOTOPMOST
            _wm_state(d, w, 0, "_NET_WM_STATE_ABOVE")
        elif after == 0:                                            # HWND_TOP
            d.x.XRaiseWindow(d.dpy, w)
        elif after == 1:                                            # HWND_BOTTOM
            d.x.XLowerWindow(d.dpy, w)
    if (flags & (SWP_NOMOVE | SWP_NOSIZE)) != (SWP_NOMOVE | SWP_NOSIZE):
        gx, gy, gw, gh = geometry(d, w)
        if flags & SWP_NOMOVE:
            x, y = gx, gy
        if flags & SWP_NOSIZE:
            cw, ch = gw, gh
        WinMove(x, y, cw, ch, f"ahk_id {w}")
    if flags & SWP_HIDEWINDOW:
        d.x.XUnmapWindow(d.dpy, w)
    elif flags & SWP_SHOWWINDOW:
        d.x.XMapWindow(d.dpy, w)
    if not flags & (SWP_NOACTIVATE | SWP_HIDEWINDOW) and not flags & SWP_NOZORDER and after in (0, -1):
        activate(d, w)
    d.flush()
    return 1


def _wstate(d, w):
    st = d.get_longs(w, "_NET_WM_STATE")
    return (d.atom("_NET_WM_STATE_HIDDEN") in st,
            d.atom("_NET_WM_STATE_MAXIMIZED_VERT") in st and d.atom("_NET_WM_STATE_MAXIMIZED_HORZ") in st)


def _show_window(pairs):
    """ShowWindow returns nonzero if the window was visible before the call."""
    from .guiobj import ctrl_set_visible, gui_for_window, gui_state, gui_hide
    from .window import _wm_state, activate, is_visible
    d, w, c = _win(_hwnd(_arg(pairs, 0)))
    if not w:
        return _fail(ERROR_INVALID_WINDOW_HANDLE)
    cmd = I(_arg(pairs, 1))
    if c is not None:
        was = int(c.visible)
        ctrl_set_visible(c, 0 if cmd == 0 else 1)
        return was
    was = int(is_visible(d, w))
    g = gui_for_window(w)
    if cmd == 0:                                                    # SW_HIDE
        gui_hide(g) if g else d.x.XUnmapWindow(d.dpy, w)
    elif cmd in (2, 6, 7, 11):                                      # SW_SHOWMINIMIZED, MINIMIZE, ...
        gui_state(g, "min") if g else d.x.XIconifyWindow(d.dpy, w, d.x.XDefaultScreen(d.dpy))
    elif cmd == 3:                                                  # SW_MAXIMIZE
        gui_state(g, "max") if g else (d.x.XMapWindow(d.dpy, w), _wm_state(
            d, w, 1, "_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ"))
    elif cmd in (1, 9):                                             # SW_SHOWNORMAL, SW_RESTORE
        if g:
            gui_state(g, "restore")
        else:
            minimized, maxed = _wstate(d, w)
            if minimized or not was:
                activate(d, w) if minimized else d.x.XMapWindow(d.dpy, w)
            elif maxed:
                _wm_state(d, w, 0, "_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ")
    else:                                                           # SW_SHOW, SHOWNA, SHOWNOACTIVATE, SHOWDEFAULT
        if g:
            from .guiobj import gui_show
            gui_show(g, "NA" if cmd in (4, 8) else "")
        else:
            d.x.XMapWindow(d.dpy, w)
            if cmd in (5, 10):
                activate(d, w)
    if d is not None:
        d.flush()
    return was


def _iconic(pairs, which):
    d, w, c = _win(_hwnd(_arg(pairs, 0)))
    if not w or c is not None:
        return 0
    return int(_wstate(d, w)[which])


def _win32_class(d, w, c):
    from .guiobj import WIN32_CLASS
    if c is not None:
        return WIN32_CLASS.get(c.ctype, c.ctype)
    from .window import class_of
    return class_of(d, w)[1]


def _find_window(pairs, ex):
    from .guiobj import CTRLS, gui_for_window
    from .window import _dpy, client_list, title_of
    off = 2 if ex else 0
    cls, title = _get_str(_arg(pairs, off), _wide(pairs, off)), _get_str(_arg(pairs, off + 1), _wide(pairs, off + 1))
    if cls is not None and isinstance(_arg(pairs, off), int) and _arg(pairs, off) < 0x10000:
        cls = None                                                  # an atom: no way to look it up here
    parent = _hwnd(_arg(pairs, 0)) if ex else 0
    after = _hwnd(_arg(pairs, 1)) if ex else 0
    d = _dpy()
    g = gui_for_window(parent) if parent else None
    if parent and parent != (d.root if d else -1):
        if g is None:
            return 0
        cands = [(c.cid, c) for c in g.ctrls if c.cid in CTRLS]
    else:
        cands = [(w, None) for w in (client_list(d, True) if d else [])]
    if after:
        ids = [h for h, _ in cands]
        cands = cands[ids.index(after) + 1:] if after in ids else []
    for h, c in cands:
        if cls is not None and _win32_class(d, h, c).lower() != cls.lower():
            continue
        if title is not None:
            if c is not None:
                from .guiobj import ctrl_get
                t = ctrl_get(c, "Text")
                t = t if isinstance(t, str) else ""
            else:
                t = title_of(d, h) or ""
            if t != title:
                continue
        return h
    return _fail(2)                                                 # ERROR_FILE_NOT_FOUND, as FindWindow sets


def _get_class_name(pairs):
    d, w, c = _win(_hwnd(_arg(pairs, 0)))
    if not w:
        return _fail(ERROR_INVALID_WINDOW_HANDLE)
    n = I(_arg(pairs, 2, 256))
    s = _win32_class(d, w if c is None else 0, c)[:max(n - 1, 0)]
    _put_str(_arg(pairs, 1), s, _wide(pairs, 1))
    return len(s)


def _get_window_pid(pairs):
    from .window import pid_of
    d, w, c = _win(_hwnd(_arg(pairs, 0)))
    if not w:
        return _fail(ERROR_INVALID_WINDOW_HANDLE)
    pid = os.getpid() if c is not None else pid_of(d, w)
    out = _arg(pairs, 1)
    if not _null(out):
        _write_out(out, "I", pid)
    return pid or 1                                                 # the thread id; threads aren't separate here


def _set_foreground(pairs):
    from .window import activate
    d, w, c = _win(_hwnd(_arg(pairs, 0)))
    if not w:
        return 0
    activate(d, w)
    return 1


def _owner(d, w):
    from .guiobj import gui_for_window
    g = gui_for_window(w)
    if g is not None:
        return g.owner.xid if g.owner is not None and not g.owner.destroyed else 0
    v = d.get_longs(w, "WM_TRANSIENT_FOR") if d else []
    return int(v[0]) if v and v[0] != d.root else 0


def _desktop_window(pairs):
    from .window import _dpy
    d = _dpy()
    return d.root if d else 0


def _get_parent(pairs):
    d, w, c = _win(_hwnd(_arg(pairs, 0)))
    if not w:
        return _fail(ERROR_INVALID_WINDOW_HANDLE)
    return w if c is not None else _owner(d, w)


def _get_ancestor(pairs):
    d, w, c = _win(_hwnd(_arg(pairs, 0)))
    if not w:
        return 0
    flag = I(_arg(pairs, 1))
    if flag == 1:                                                   # GA_PARENT
        return w if c is not None else d.root
    if flag == 3:                                                   # GA_ROOTOWNER
        seen = {w}
        while (o := _owner(d, w)) and o not in seen:
            seen.add(o)
            w = o
    return w                                                        # GA_ROOT


GWL_STYLE, GWL_EXSTYLE, GWL_ID, GWLP_HWNDPARENT = -16, -20, -12, -8


def _get_window_long(pairs):
    from .window import _style_bits, _style_of, ControlGetExStyle
    d, w, c = _win(_hwnd(_arg(pairs, 0)))
    if not w:
        return _fail(ERROR_INVALID_WINDOW_HANDLE)
    idx = _int32(_arg(pairs, 1))
    if idx == GWL_STYLE:
        return _int32(_style_of(c) if c is not None else _style_bits(d, w))
    if idx == GWL_EXSTYLE:
        if c is not None:
            return _int32(ControlGetExStyle(c))
        return 0x8 if d.atom("_NET_WM_STATE_ABOVE") in d.get_longs(w, "_NET_WM_STATE") else 0
    if idx == GWL_ID:                                               # GetDlgCtrlID, as WM_COMMAND reports it
        from .notify import ctrl_id
        return ctrl_id(c) if c is not None else 0
    if idx == GWLP_HWNDPARENT:
        return w if c is not None else _owner(d, w)
    return 0


def _set_window_long(pairs):
    from .window import ControlSetExStyle, ControlSetStyle, WinSetExStyle, WinSetStyle
    old = _get_window_long(pairs[:2])
    h = _hwnd(_arg(pairs, 0))
    d, w, c = _win(h)
    if not w:
        return 0
    idx, v = _int32(_arg(pairs, 1)), int(_arg_value(_arg(pairs, 2))) & 0xFFFFFFFF
    if idx == GWL_STYLE:
        ControlSetStyle(v, c) if c is not None else WinSetStyle(v, f"ahk_id {w}")
    elif idx == GWL_EXSTYLE:
        ControlSetExStyle(v, c) if c is not None else WinSetExStyle(v, f"ahk_id {w}")
    return old


# ---------------------------------------------------------------- libraries
# Handles for the system DLLs whose functions are emulated: GetProcAddress on them returns an address that
# DllCall dispatches to the emulation table, so the GetModuleHandle + GetProcAddress idiom keeps working.
_SYSTEM_DLLS = ("kernel32", "user32", "shell32", "gdi32", "advapi32", "ole32", "winmm", "ntdll", "msvcrt",
                "kernelbase", "comctl32", "powrprof", "shcore", "dwmapi", "uxtheme")
_PSEUDO_BASE = 0x7FFE0000_0000
_PSEUDO_MOD = {_PSEUDO_BASE + (i << 20): n for i, n in enumerate(_SYSTEM_DLLS)}
_PSEUDO_FN: dict[int, str] = {}         # address -> EMU key
_OPENED: dict[int, int] = {}            # dlopen handle -> LoadLibrary reference count


def _dll_name(name):
    n = os.path.basename(name.replace("\\", "/")).lower()
    return n[:-4] if n.endswith(".dll") else n


def _pseudo_module(name):
    n = _dll_name(name)
    return next((h for h, m in _PSEUDO_MOD.items() if m == n), 0)


def _dlopen(name, load):
    """A real handle for a Linux shared library (or 0)."""
    from .files import host_path
    path = host_path(name) if "/" in name or "\\" in name else name
    cands = [path]
    if not os.path.exists(path):
        cands.append(ctypes.util.find_library(os.path.basename(name).replace("lib", "", 1).split(".so")[0]) or "")
    for cand in cands:
        if not cand:
            continue
        try:
            lib = ctypes.CDLL(cand, mode=(0 if load else getattr(os, "RTLD_NOLOAD", 4)) | ctypes.RTLD_GLOBAL)
        except OSError:
            continue
        return lib._handle
    return 0


def _get_module_handle(pairs):
    v = _arg(pairs, 0)
    name = _get_str(v, _wide(pairs, 0))
    if name is None:
        return ctypes.CDLL(None)._handle                            # the main program, like the .exe's base
    if name.lower().endswith(".dll") or "." not in name:
        h = _pseudo_module(name)
        return h or _fail(ERROR_MOD_NOT_FOUND)
    return _dlopen(name, False) or _fail(ERROR_MOD_NOT_FOUND)


def _load_library(pairs):
    name = _get_str(_arg(pairs, 0), _wide(pairs, 0)) or ""
    if name.lower().endswith(".dll") or ("." not in name and "/" not in name):
        return _pseudo_module(name) or _fail(ERROR_MOD_NOT_FOUND)
    h = _dlopen(name, True)
    if not h:
        return _fail(ERROR_MOD_NOT_FOUND)
    _OPENED[h] = _OPENED.get(h, 0) + 1
    return h


def _get_proc_address(pairs):
    h = int(_arg_value(_arg(pairs, 0)))
    v = _arg(pairs, 1)
    if type(v) is int and v < 0x10000:
        return _fail(ERROR_PROC_NOT_FOUND)                          # by ordinal
    name = _get_str(v, False) or ""
    if h in _PSEUDO_MOD:
        key = name.lower()
        k = key if key in EMU else key[:-1] if key[-1:] in ("w", "a") and key[:-1] in EMU else None
        if k is None:
            return _fail(ERROR_PROC_NOT_FOUND)
        addr = next((a for a, kk in _PSEUDO_FN.items() if kk == k), 0)
        if not addr:
            addr = _PSEUDO_BASE + (len(_SYSTEM_DLLS) << 20) + 16 * (len(_PSEUDO_FN) + 1)
            _PSEUDO_FN[addr] = k
        return addr
    if not h:
        return _fail(ERROR_MOD_NOT_FOUND)
    try:
        fn = getattr(ctypes.CDLL("", handle=h), name)
    except AttributeError:
        return _fail(ERROR_PROC_NOT_FOUND)
    return ctypes.cast(fn, ctypes.c_void_p).value or 0


def _free_library(pairs):
    h = int(_arg_value(_arg(pairs, 0)))
    if h in _PSEUDO_MOD:
        return 1
    if h not in _OPENED:
        return _fail(ERROR_MOD_NOT_FOUND)
    _OPENED[h] -= 1
    if not _OPENED[h]:
        del _OPENED[h]
        import _ctypes
        _ctypes.dlclose(h)
    return 1


# ---------------------------------------------------------------- memory and strings
def _mem(target):
    from .buffer import resolve
    return resolve(target)


def _move_memory(pairs):
    n = I(_arg(pairs, 2))
    if n > 0:
        sd, si = _mem(_arg(pairs, 1))
        chunk = bytes(sd[si:si + n])
        dd, di = _mem(_arg(pairs, 0))
        dd[di:di + n] = chunk
    return int(_arg_value(_arg(pairs, 0)))


def _fill_memory(pairs, value=None):
    n = I(_arg(pairs, 1))
    b = (I(_arg(pairs, 2)) & 255) if value is None else value
    if n > 0:
        dd, di = _mem(_arg(pairs, 0))
        dd[di:di + n] = bytes([b]) * n
    return 0


def _memset(pairs):
    n = I(_arg(pairs, 2))
    if n > 0:
        dd, di = _mem(_arg(pairs, 0))
        dd[di:di + n] = bytes([I(_arg(pairs, 1)) & 255]) * n
    return int(_arg_value(_arg(pairs, 0)))


def _lstrlen(pairs, wide):
    v = _arg(pairs, 0)
    if _null(v):
        return 0
    if isinstance(v, str) and not v.strip().lstrip("-").isdigit():
        return len(v.encode("utf-16-le")) // 2 if wide else len(v.encode("utf-8"))
    data, idx = _mem(v)
    unit = 2 if wide else 1
    end = idx
    while end + unit <= len(data) and bytes(data[end:end + unit]) != b"\0" * unit:
        end += unit
    return (end - idx) // unit


def _muldiv(pairs):
    a, b, c = (_int32(_arg(pairs, i)) for i in range(3))
    if c == 0:
        return -1
    q, r = divmod(abs(a * b), abs(c))
    if 2 * r >= abs(c):                                             # rounds half away from zero
        q += 1
    q = q if (a * b < 0) == (c < 0) else -q
    return q if -(1 << 31) <= q < (1 << 31) else -1


# ---------------------------------------------------------------- system information
def _sized_string(pairs, s, size_counts_nul):
    """GetComputerName/GetUserName: buffer + in/out size in characters."""
    size_arg = _arg(pairs, 1)
    have = _get_num(size_arg)
    need = len(s) + 1
    if have < need:
        _write_out(size_arg, "I", need)
        return _fail(ERROR_INSUFFICIENT_BUFFER if size_counts_nul else ERROR_BUFFER_OVERFLOW)
    _put_str(_arg(pairs, 0), s, _wide(pairs, 0))
    _write_out(size_arg, "I", need if size_counts_nul else len(s))
    return 1


def _computer_name(pairs):
    import socket
    return _sized_string(pairs, socket.gethostname().split(".")[0].upper(), False)


def _user_name(pairs):
    import getpass
    return _sized_string(pairs, getpass.getuser(), True)


def _buffer_result(target, s, n, wide=True):
    """The 'length, or required size when the buffer is too small' convention (GetTempPath and friends)."""
    if n < len(s) + 1:
        return len(s) + 1
    _put_str(target, s, wide)
    return len(s)


def _temp_path(pairs):
    from .files import shell_folder
    p = shell_folder("temp").rstrip("/") + "/"
    return _buffer_result(_arg(pairs, 1), p, I(_arg(pairs, 0)), _wide(pairs, 1))


def _command_line(pairs, wide=True):
    import sys

    def q(a):
        return f'"{a}"' if not a or any(ch in a for ch in " \t\"") else a
    args = [sys.executable] + [a for a in sys.argv]
    s = " ".join(q(a) for a in args)
    if not wide:
        from .buffer import BufferObj
        b = _CMDLINE_A.get(s)
        if b is None:
            b = BufferObj(len(s.encode()) + 1)
            b.data[:len(s.encode())] = s.encode()
            _CMDLINE_A[s] = b
        return b.addr
    from .strings import StrPtr
    return StrPtr(s)


_CMDLINE_A: dict = {}


def _expand_env(s):
    import re
    return re.sub(r"%([^%]+)%", lambda m: os.environ.get(m.group(1), m.group(0)), s)


def _expand_env_strings(pairs):
    s = _expand_env(_get_str(_arg(pairs, 0), _wide(pairs, 0)) or "")
    n = I(_arg(pairs, 2))
    if n >= len(s) + 1:
        _put_str(_arg(pairs, 1), s, _wide(pairs, 1))
    return len(s) + 1                                               # characters required, including the NUL


def _get_env(pairs):
    name = _get_str(_arg(pairs, 0), _wide(pairs, 0)) or ""
    if name not in os.environ:
        return _fail(ERROR_ENVVAR_NOT_FOUND)
    return _buffer_result(_arg(pairs, 1), os.environ[name], I(_arg(pairs, 2)), _wide(pairs, 1))


def _set_env(pairs):
    name = _get_str(_arg(pairs, 0), _wide(pairs, 0)) or ""
    if not name or "=" in name:
        return _fail(87)                                            # ERROR_INVALID_PARAMETER
    v = _get_str(_arg(pairs, 1), _wide(pairs, 1)) if len(pairs) > 1 else None
    if v is None:
        if name not in os.environ:
            return _fail(ERROR_ENVVAR_NOT_FOUND)
        del os.environ[name]
    else:
        os.environ[name] = v
    return 1


def _put_systemtime(target, t, ms):
    from .buffer import resolve
    data, idx = resolve(target)
    struct.pack_into("<8H", data, idx, t.tm_year, t.tm_mon, (t.tm_wday + 1) % 7, t.tm_mday, t.tm_hour, t.tm_min,
                     t.tm_sec, ms)


def _system_time(pairs, local):
    now = time.time()
    _put_systemtime(_arg(pairs, 0), time.localtime(now) if local else time.gmtime(now), int(now * 1000) % 1000)
    return 0


def _filetime_to_systemtime(pairs):
    v = _arg(pairs, 0)
    ft = _get_num(v, "Q") if not isinstance(v, VarRef) else I(v.cell.value)
    if ft >= 0x8000000000000000:
        return _fail(87)
    secs, rem = divmod(ft, 10_000_000)
    _put_systemtime(_arg(pairs, 1), time.gmtime(secs - 11644473600), rem // 10_000)
    return 1


# ---------------------------------------------------------------- shell
def _shell_execute(pairs):
    """ShellExecute(hwnd, verb, file, params, dir, show) -> a value above 32 on success, an SE_ERR code otherwise."""
    import shlex
    import subprocess
    from .files import host_path
    verb = (_get_str(_arg(pairs, 1), _wide(pairs, 1)) or "open").lower()
    target = _get_str(_arg(pairs, 2), _wide(pairs, 2)) or ""
    params = _get_str(_arg(pairs, 3), _wide(pairs, 3)) or ""
    cwd = _get_str(_arg(pairs, 4), _wide(pairs, 4)) or None
    if not target:
        return 2                                                    # SE_ERR_FNF
    cwd = host_path(cwd) if cwd else None
    if cwd and not os.path.isdir(cwd):
        return 3                                                    # SE_ERR_PNF
    is_url = "://" in target or target.lower().startswith(("mailto:", "www."))
    path = target if is_url else host_path(target)
    try:
        if not is_url and os.path.isfile(path) and os.access(path, os.X_OK) and verb in ("open", "runas", ""):
            subprocess.Popen([path] + shlex.split(params), cwd=cwd, start_new_session=True)
        elif is_url or os.path.exists(path):
            subprocess.Popen(["xdg-open", path], cwd=cwd, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            import shutil
            exe = shutil.which(target)
            if exe is None:
                return 2
            subprocess.Popen([exe] + shlex.split(params), cwd=cwd, start_new_session=True)
    except OSError:
        return 5                                                    # SE_ERR_ACCESSDENIED
    return 42


EMU.update({
    "getwindowrect": lambda p: _rect(p, False), "getclientrect": lambda p: _rect(p, True),
    "movewindow": _move_window, "setwindowpos": _set_window_pos, "showwindow": _show_window,
    "isiconic": lambda p: _iconic(p, 0), "iszoomed": lambda p: _iconic(p, 1),
    "findwindow": lambda p: _find_window(p, False), "findwindowex": lambda p: _find_window(p, True),
    "getclassname": _get_class_name, "getwindowthreadprocessid": _get_window_pid,
    "setforegroundwindow": _set_foreground, "getparent": _get_parent, "getancestor": _get_ancestor,
    "getwindowlong": _get_window_long, "getwindowlongptr": _get_window_long,
    "setwindowlong": _set_window_long, "setwindowlongptr": _set_window_long,
    "getdesktopwindow": _desktop_window,
    "getmodulehandle": _get_module_handle, "loadlibrary": _load_library, "loadlibraryex": _load_library,
    "getprocaddress": _get_proc_address, "freelibrary": _free_library,
    "rtlmovememory": _move_memory, "movememory": _move_memory, "copymemory": _move_memory,
    "rtlcopymemory": _move_memory, "memcpy": _move_memory, "memmove": _move_memory, "memset": _memset,
    "rtlfillmemory": _fill_memory, "fillmemory": _fill_memory,
    "rtlzeromemory": lambda p: _fill_memory(p, 0), "zeromemory": lambda p: _fill_memory(p, 0),
    "lstrlen": lambda p: _lstrlen(p, True), "lstrlenw": lambda p: _lstrlen(p, True),
    "lstrlena": lambda p: _lstrlen(p, False), "wcslen": lambda p: _lstrlen(p, True),
    "strlen": lambda p: _lstrlen(p, False), "muldiv": _muldiv,
    "getcomputername": _computer_name, "getusername": _user_name, "gettemppath": _temp_path,
    "getcommandline": lambda p: _command_line(p), "getcommandlinew": lambda p: _command_line(p),
    "getcommandlinea": lambda p: _command_line(p, False),
    "expandenvironmentstrings": _expand_env_strings, "getenvironmentvariable": _get_env,
    "setenvironmentvariable": _set_env,
    "getsystemtime": lambda p: _system_time(p, False), "getlocaltime": lambda p: _system_time(p, True),
    "filetimetosystemtime": _filetime_to_systemtime, "closehandle": lambda p: 1,
    "shellexecute": _shell_execute,
})

from . import win32emu  # noqa: E402,F401  (registers more of the Win32 API into EMU)
from . import win32gdi  # noqa: E402,F401  (GDI: DCs, bitmaps, BitBlt)
