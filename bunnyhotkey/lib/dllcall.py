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
    "getdesktopwindow": lambda p: 0,
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
}

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
    if h in CTRLS:
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
