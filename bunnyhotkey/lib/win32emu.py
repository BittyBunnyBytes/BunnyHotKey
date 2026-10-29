"""More of the Win32 API for DllCall (registered into dllcall.EMU): memory, coordinates and monitors,
rectangles, crypt32/advapi32 encoding and hashing, process handles and Toolhelp snapshots, the clipboard
and kernel32 file handles.  Struct layouts are the 64-bit Windows SDK's."""
from __future__ import annotations

import base64
import binascii
import ctypes
import hashlib
import itertools
import os
import signal
import struct
import time
import zlib

from .. import objects as O
from ..objects import VarRef
from ..values import UNSET
from .dllcall import EMU, I, S, _arg, _arg_value, _fail, _hwnd, _null, _put_str, _write_out

_libc = ctypes.CDLL(None, use_errno=True)
_libc.malloc.restype = ctypes.c_void_p
_libc.malloc.argtypes = [ctypes.c_size_t]
_libc.calloc.restype = ctypes.c_void_p
_libc.calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
_libc.realloc.restype = ctypes.c_void_p
_libc.realloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
_libc.free.argtypes = [ctypes.c_void_p]
_libc.mprotect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]

ERROR_FILE_NOT_FOUND, ERROR_ACCESS_DENIED, ERROR_INVALID_HANDLE, ERROR_NO_MORE_FILES = 2, 5, 6, 18
ERROR_INVALID_PARAMETER, ERROR_FILE_EXISTS, ERROR_MORE_DATA = 87, 80, 234
INVALID_HANDLE_VALUE = -1


def _ptr(v):
    return int(_arg_value(v)) if not _null(v) else 0


def _mem(addr, size):
    from .buffer import resolve
    data, idx = resolve(addr)
    return data, idx


def _read(addr, n):
    data, idx = _mem(addr, n)
    return bytes(data[idx:idx + n])


def _write(addr, raw):
    data, idx = _mem(addr, len(raw))
    data[idx:idx + len(raw)] = raw


def _str_arg(v, wide=True):
    """A string parameter: a script string (Str/AStr) or the address of one."""
    if isinstance(v, str) and not v.strip().lstrip("-").isdigit():
        return v
    if isinstance(v, VarRef):
        return S(v.cell.value)
    p = _ptr(v)
    if not p:
        return ""
    data, idx = _mem(p, 2)
    if wide:
        out = bytearray()
        while True:
            ch = bytes(data[idx:idx + 2])
            if len(ch) < 2 or ch == b"\0\0":
                break
            out += ch
            idx += 2
        return out.decode("utf-16-le", "replace")
    end = bytes(data[idx:idx + 65536]).find(b"\0")
    return bytes(data[idx:idx + (end if end >= 0 else 0)]).decode("cp1252", "replace")


# ---------------------------------------------------------------- handles
_handles: dict[int, object] = {}
_ids = itertools.count(0x7A000)


def _new_handle(obj):
    h = next(_ids) * 4
    _handles[h] = obj
    return h




# ---------------------------------------------------------------- memory: Global*/Local*/Heap*/VirtualProtect
_sizes: dict[int, int] = {}


def _alloc(size, zero):
    n = max(int(size), 1)
    p = _libc.calloc(1, n) if zero else _libc.malloc(n)
    if p:
        _sizes[p] = int(size)
    return p or 0


def _free(p):
    if p and p in _sizes:
        _sizes.pop(p, None)
        _libc.free(p)


def _realloc(p, size, zero):
    if not p:
        return _alloc(size, zero)
    old = _sizes.get(p, 0)
    q = _libc.realloc(p, max(int(size), 1))
    if not q:
        return 0
    _sizes.pop(p, None)
    _sizes[q] = int(size)
    if zero and size > old:
        ctypes.memset(q + old, 0, int(size) - old)
    return q


GMEM_ZEROINIT, HEAP_ZERO_MEMORY = 0x40, 0x8


def _virtual_protect(p):
    addr, size, new = _ptr(_arg(p, 0)), I(_arg(p, 1)), I(_arg(p, 2))
    prot = {0x01: 0, 0x02: 1, 0x04: 3, 0x08: 3, 0x10: 4, 0x20: 5, 0x40: 7, 0x80: 7}.get(new & 0xFF, 3)
    page = os.sysconf("SC_PAGE_SIZE")
    start = addr & ~(page - 1)
    length = ((addr + max(size, 1) - start) + page - 1) & ~(page - 1)
    ok = _libc.mprotect(start, length, prot) == 0
    out = _arg(p, 3)
    if not _null(out):
        _write_out(out, "I", 0x04)                      # PAGE_READWRITE was the old protection
    return 1 if ok else _fail(ERROR_INVALID_PARAMETER)


EMU.update({
    "globalalloc": lambda p: _alloc(I(_arg(p, 1)), I(_arg(p, 0)) & GMEM_ZEROINIT),
    "localalloc": lambda p: _alloc(I(_arg(p, 1)), I(_arg(p, 0)) & GMEM_ZEROINIT),
    "globalrealloc": lambda p: _realloc(_ptr(_arg(p, 0)), I(_arg(p, 1)), I(_arg(p, 2)) & GMEM_ZEROINIT),
    "localrealloc": lambda p: _realloc(_ptr(_arg(p, 0)), I(_arg(p, 1)), I(_arg(p, 2)) & GMEM_ZEROINIT),
    "globallock": lambda p: _ptr(_arg(p, 0)), "locallock": lambda p: _ptr(_arg(p, 0)),
    "globalunlock": lambda p: (setattr(O.RT, "last_error", 0), 0)[1],
    "localunlock": lambda p: (setattr(O.RT, "last_error", 0), 0)[1],
    "globalsize": lambda p: _sizes.get(_ptr(_arg(p, 0)), 0), "localsize": lambda p: _sizes.get(_ptr(_arg(p, 0)), 0),
    "globalfree": lambda p: (_free(_ptr(_arg(p, 0))), 0)[1], "localfree": lambda p: (_free(_ptr(_arg(p, 0))), 0)[1],
    "getprocessheap": lambda p: 0x7A0000,
    "heapcreate": lambda p: 0x7A0000 + 0x1000,
    "heapdestroy": lambda p: 1,
    "heapalloc": lambda p: _alloc(I(_arg(p, 2)), I(_arg(p, 1)) & HEAP_ZERO_MEMORY),
    "heaprealloc": lambda p: _realloc(_ptr(_arg(p, 2)), I(_arg(p, 3)), I(_arg(p, 1)) & HEAP_ZERO_MEMORY),
    "heapfree": lambda p: (_free(_ptr(_arg(p, 2))), 1)[1],
    "heapsize": lambda p: _sizes.get(_ptr(_arg(p, 2)), -1),
    "virtualprotect": _virtual_protect,
})


# ---------------------------------------------------------------- coordinates, monitors, rectangles
def _point_arg(v):
    """A POINT passed by value (Int64 x | y << 32) or by address."""
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.lstrip("-").isdigit()):
        n = int(v) & 0xFFFFFFFFFFFFFFFF
        x, y = n & 0xFFFFFFFF, n >> 32
        return (x - (1 << 32) if x & 0x80000000 else x, y - (1 << 32) if y & 0x80000000 else y)
    return struct.unpack("<2i", _read(_ptr(v), 8))


def _client_shift(p, sign):
    from .dllcall import _client_origin
    ox, oy = _client_origin(_hwnd(_arg(p, 0)))
    addr = _ptr(_arg(p, 1))
    x, y = struct.unpack("<2i", _read(addr, 8))
    _write(addr, struct.pack("<2i", x + sign * ox, y + sign * oy))
    return 1


def _window_from_point(p):
    from .window import _dpy, client_list, geometry, is_visible
    x, y = _point_arg(_arg(p, 0))
    d = _dpy()
    if d is None:
        return 0
    stack = d.get_longs(d.root, "_NET_CLIENT_LIST_STACKING") or client_list(d)
    for w in reversed(list(stack)):                     # topmost first
        try:
            if not is_visible(d, w):
                continue
            gx, gy, gw, gh = geometry(d, w)
        except Exception:
            continue
        if gx <= x < gx + gw and gy <= y < gy + gh:
            from .input_ import _control_at
            h = _control_at(w, x, y, True)
            return int(h) if h else int(w)
    return 0


_MON_BASE = 0x6D000


def _monitors():
    """[(x, y, w, h, work x, work y, work w, work h, primary)] in MonitorGet's order."""
    from .window import _monitors as mons, MonitorGetWorkArea
    from ..objects import Cell
    out = []
    for i, (_n, l, t, r, b, primary) in enumerate(mons()):
        refs = [VarRef(Cell("w")) for _ in range(4)]
        try:
            MonitorGetWorkArea(i + 1, *refs)
            wl, wt, wr, wb = (int(x.cell.value) for x in refs)
        except Exception:
            wl, wt, wr, wb = l, t, r, b
        out.append((l, t, r - l, b - t, wl, wt, wr - wl, wb - wt, primary))
    return out


def _monitor_for(x, y, w=1, h=1, flags=0):
    mons = _monitors()
    best, area = 0, 0
    for i, (mx, my, mw, mh, wx, wy, ww, wh, primary) in enumerate(mons):
        ix = max(0, min(x + w, mx + mw) - max(x, mx))
        iy = max(0, min(y + h, my + mh) - max(y, my))
        if ix * iy > area:
            best, area = i + 1, ix * iy
    if best:
        return _MON_BASE + best
    if flags == 0:                                      # MONITOR_DEFAULTTONULL
        return 0
    if flags == 1:                                      # MONITOR_DEFAULTTOPRIMARY
        return _MON_BASE + next((i + 1 for i, m in enumerate(mons) if m[8]), 1)
    cx, cy = x + w // 2, y + h // 2                     # MONITOR_DEFAULTTONEAREST
    near = min(range(len(mons)), key=lambda i: (max(mons[i][0] - cx, 0, cx - mons[i][0] - mons[i][2]) ** 2 +
                                                max(mons[i][1] - cy, 0, cy - mons[i][1] - mons[i][3]) ** 2))
    return _MON_BASE + near + 1


def _monitor_from_window(p):
    from .window import _dpy, geometry
    from .dllcall import _win
    d, w, c = _win(_hwnd(_arg(p, 0)))
    flags = I(_arg(p, 1))
    if not w:
        return _monitor_for(0, 0, 1, 1, flags if flags else 1) if flags else 0
    x, y, ww, wh = geometry(d, w)
    return _monitor_for(x, y, ww, wh, flags)


def _monitor_from_rect(p):
    left, top, right, bottom = struct.unpack("<4i", _read(_ptr(_arg(p, 0)), 16))
    return _monitor_for(left, top, right - left, bottom - top, I(_arg(p, 1)))


def _get_monitor_info(p):
    n = _ptr(_arg(p, 0)) - _MON_BASE
    mons = _monitors()
    if not 1 <= n <= len(mons):
        return _fail(ERROR_INVALID_PARAMETER)
    mx, my, mw, mh, wx, wy, ww, wh, _p = mons[n - 1]
    from .window import MonitorGetPrimary
    primary = n == MonitorGetPrimary()                  # (RandR may name no primary; MonitorGetPrimary decides)
    addr = _ptr(_arg(p, 1))
    cb = struct.unpack("<I", _read(addr, 4))[0]
    _write(addr + 4, struct.pack("<4i4iI", mx, my, mx + mw, my + mh, wx, wy, wx + ww, wy + wh, 1 if primary else 0))
    if cb >= 104:                                       # MONITORINFOEX: szDevice
        name = ("\\\\.\\DISPLAY%d" % n).encode("utf-16-le")[:62] + b"\0\0"
        _write(addr + 40, name)
    return 1


def _dpi_for_monitor(p):
    from .window import screen_dpi
    dpi = int(screen_dpi())
    _write_out(_arg(p, 2), "I", dpi)
    _write_out(_arg(p, 3), "I", dpi)
    return 0                                            # S_OK


def _rect_op(p, op):
    def rd(i):
        return struct.unpack("<4i", _read(_ptr(_arg(p, i)), 16))

    def wr(i, r):
        _write(_ptr(_arg(p, i)), struct.pack("<4i", *r))
    if op == "intersect":
        a, b = rd(1), rd(2)
        r = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
        ok = r[0] < r[2] and r[1] < r[3]
        wr(0, r if ok else (0, 0, 0, 0))
        return int(ok)
    if op == "union":
        a, b = rd(1), rd(2)
        if a[0] >= a[2] or a[1] >= a[3]:
            r = b
        elif b[0] >= b[2] or b[1] >= b[3]:
            r = a
        else:
            r = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
        wr(0, r)
        return int(r[0] < r[2] and r[1] < r[3])
    if op == "ptin":
        r = rd(0)
        x, y = _point_arg(_arg(p, 1))
        return int(r[0] <= x < r[2] and r[1] <= y < r[3])
    if op == "offset":
        r = rd(0)
        dx, dy = I(_arg(p, 1)), I(_arg(p, 2))
        wr(0, (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy))
        return 1
    if op == "inflate":
        r = rd(0)
        dx, dy = I(_arg(p, 1)), I(_arg(p, 2))
        wr(0, (r[0] - dx, r[1] - dy, r[2] + dx, r[3] + dy))
        return 1
    if op == "set":
        wr(0, tuple(I(_arg(p, i)) for i in range(1, 5)))
        return 1
    if op == "copy":
        wr(0, rd(1))
        return 1
    if op == "empty":
        r = rd(0)
        return int(r[0] >= r[2] or r[1] >= r[3])
    if op == "equal":
        return int(rd(0) == rd(1))
    return 0


_messages: dict[str, int] = {}


def _register_window_message(p):
    name = _str_arg(_arg(p, 0)).lower()
    if name not in _messages:
        _messages[name] = 0xC000 + (zlib.crc32(name.encode()) % 0x3FFF)     # stable across BHK processes
    return _messages[name]


def _get_window(p):
    from .window import _dpy, client_list
    from .dllcall import _win
    from .guiobj import gui_for_window
    d, w, c = _win(_hwnd(_arg(p, 0)))
    cmd = I(_arg(p, 1))
    if not w:
        return 0
    if cmd == 5:                                        # GW_CHILD
        g = gui_for_window(w)
        return g.ctrls[0].cid if g is not None and g.ctrls and c is None else 0
    if cmd == 4:                                        # GW_OWNER
        g = gui_for_window(w)
        return getattr(g, "owner", 0) or 0
    stack = list(d.get_longs(d.root, "_NET_CLIENT_LIST_STACKING") or client_list(d))[::-1]   # top first
    if w not in stack:
        return 0
    i = stack.index(w)
    return {0: stack[0], 1: stack[-1], 2: stack[i + 1] if i + 1 < len(stack) else 0,
            3: stack[i - 1] if i > 0 else 0}.get(cmd, 0)


EMU.update({
    "screentoclient": lambda p: _client_shift(p, -1), "clienttoscreen": lambda p: _client_shift(p, 1),
    "windowfrompoint": _window_from_point, "windowfromphysicalpoint": _window_from_point,
    "monitorfromwindow": _monitor_from_window,
    "monitorfrompoint": lambda p: _monitor_for(*_point_arg(_arg(p, 0)), 1, 1, I(_arg(p, 1))),
    "monitorfromrect": _monitor_from_rect, "getmonitorinfo": _get_monitor_info,
    "getdpiformonitor": _dpi_for_monitor,
    "intersectrect": lambda p: _rect_op(p, "intersect"), "unionrect": lambda p: _rect_op(p, "union"),
    "ptinrect": lambda p: _rect_op(p, "ptin"), "offsetrect": lambda p: _rect_op(p, "offset"),
    "inflaterect": lambda p: _rect_op(p, "inflate"), "setrect": lambda p: _rect_op(p, "set"),
    "copyrect": lambda p: _rect_op(p, "copy"), "isrectempty": lambda p: _rect_op(p, "empty"),
    "equalrect": lambda p: _rect_op(p, "equal"),
    "registerwindowmessage": _register_window_message,
    "getacp": lambda p: 1252, "getoemcp": lambda p: 437,
    "getwindow": _get_window,
    "getsystemmenu": lambda p: 0x7B000 + (_hwnd(_arg(p, 0)) & 0xFFF), "drawmenubar": lambda p: 1,
    "redrawwindow": lambda p: 1, "updatewindow": lambda p: 1, "invalidaterect": lambda p: 1,
    "validaterect": lambda p: 1,
})


# ---------------------------------------------------------------- crypt32: CryptStringToBinary / CryptBinaryToString
CRYPT_STRING_BASE64HEADER, CRYPT_STRING_BASE64, CRYPT_STRING_BINARY = 0, 1, 2
CRYPT_STRING_BASE64REQUESTHEADER, CRYPT_STRING_HEX, CRYPT_STRING_HEXASCII = 3, 4, 5
CRYPT_STRING_BASE64_ANY, CRYPT_STRING_ANY, CRYPT_STRING_HEX_ANY = 6, 7, 8
CRYPT_STRING_BASE64X509CRLHEADER, CRYPT_STRING_HEXADDR, CRYPT_STRING_HEXASCIIADDR = 9, 10, 11
CRYPT_STRING_HEXRAW, CRYPT_STRING_NOCRLF, CRYPT_STRING_NOCR = 12, 0x40000000, 0x80000000


def _decode(text, fmt):
    import re
    if fmt in (CRYPT_STRING_BASE64HEADER, CRYPT_STRING_BASE64REQUESTHEADER, CRYPT_STRING_BASE64X509CRLHEADER):
        text = re.sub(r"-----[^-]+-----", "", text)
    if fmt in (CRYPT_STRING_BASE64, CRYPT_STRING_BASE64HEADER, CRYPT_STRING_BASE64REQUESTHEADER,
               CRYPT_STRING_BASE64X509CRLHEADER, CRYPT_STRING_BASE64_ANY, CRYPT_STRING_ANY):
        try:
            return base64.b64decode(re.sub(r"\s+|-----[^-]+-----", "", text), validate=False)
        except (binascii.Error, ValueError):
            if fmt != CRYPT_STRING_ANY:
                return None
    if fmt == CRYPT_STRING_BINARY or fmt == CRYPT_STRING_ANY:
        return text.encode("latin-1", "replace")
    if fmt in (CRYPT_STRING_HEX, CRYPT_STRING_HEXRAW, CRYPT_STRING_HEX_ANY, CRYPT_STRING_HEXASCII,
               CRYPT_STRING_HEXADDR, CRYPT_STRING_HEXASCIIADDR):
        lines = text.splitlines() or [text]
        hexes = []
        for ln in lines:
            if fmt in (CRYPT_STRING_HEXADDR, CRYPT_STRING_HEXASCIIADDR):
                ln = ln[ln.find(" ") + 1:] if " " in ln.strip() else ln
            if fmt in (CRYPT_STRING_HEXASCII, CRYPT_STRING_HEXASCIIADDR):
                ln = ln[:48]
            hexes.append(re.sub(r"[^0-9A-Fa-f]", "", ln))
        h = "".join(hexes)
        try:
            return bytes.fromhex(h[:len(h) // 2 * 2])
        except ValueError:
            return None
    return None


def _string_to_binary(p, wide=True):
    text = _str_arg(_arg(p, 0), wide)
    n = I(_arg(p, 1))
    if n > 0:
        text = text[:n]
    raw = _decode(text, I(_arg(p, 2)) & 0xFFFF)
    if raw is None:
        return _fail(0x80090005 & 0xFFFFFFFF)            # CRYPT_E_BAD_DATA... (ERROR_INVALID_DATA = 13)
    out, pcb = _arg(p, 3), _arg(p, 4)
    if _null(out):
        _write_out(pcb, "I", len(raw))
        return 1
    have = struct.unpack("<I", _read(_ptr(pcb), 4))[0] if not isinstance(pcb, VarRef) else I(pcb.cell.value)
    if have < len(raw):
        _write_out(pcb, "I", len(raw))
        return _fail(ERROR_MORE_DATA)
    _write(_ptr(out), raw)
    _write_out(pcb, "I", len(raw))
    for i, v in ((5, 0), (6, I(_arg(p, 2)) & 0xFFFF)):  # pdwSkip, pdwFlags
        if not _null(_arg(p, i)):
            _write_out(_arg(p, i), "I", v)
    return 1


def _encode(raw, flags):
    fmt = flags & 0xFFFF
    nl = "" if flags & CRYPT_STRING_NOCRLF else ("\n" if flags & CRYPT_STRING_NOCR else "\r\n")
    if fmt in (CRYPT_STRING_BASE64, CRYPT_STRING_BASE64HEADER, CRYPT_STRING_BASE64REQUESTHEADER,
               CRYPT_STRING_BASE64X509CRLHEADER):
        b = base64.b64encode(raw).decode()
        body = nl.join(b[i:i + 64] for i in range(0, len(b), 64)) + (nl if b else "")
        if fmt == CRYPT_STRING_BASE64HEADER:
            body = "-----BEGIN CERTIFICATE-----" + nl + body + "-----END CERTIFICATE-----" + nl
        elif fmt == CRYPT_STRING_BASE64REQUESTHEADER:
            body = "-----BEGIN NEW CERTIFICATE REQUEST-----" + nl + body + "-----END NEW CERTIFICATE REQUEST-----" + nl
        return body
    if fmt == CRYPT_STRING_HEXRAW:
        return raw.hex() + nl
    if fmt in (CRYPT_STRING_HEX, CRYPT_STRING_HEXASCII, CRYPT_STRING_HEXADDR, CRYPT_STRING_HEXASCIIADDR):
        lines = []
        for off in range(0, len(raw), 16):
            chunk = raw[off:off + 16]
            hx = " ".join(f"{c:02x}" for c in chunk[:8])
            if len(chunk) > 8:
                hx += "  " + " ".join(f"{c:02x}" for c in chunk[8:])
            line = (f"{off:04x}    " if fmt in (CRYPT_STRING_HEXADDR, CRYPT_STRING_HEXASCIIADDR) else "") + hx
            if fmt in (CRYPT_STRING_HEXASCII, CRYPT_STRING_HEXASCIIADDR):
                line = line.ljust((8 if "ADDR" else 0) + 48) + "   " + "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
            lines.append(line)
        return nl.join(lines) + (nl if lines else "")
    if fmt == CRYPT_STRING_BINARY:
        return raw.decode("latin-1")
    return None


def _binary_to_string(p, wide=True):
    raw = _read(_ptr(_arg(p, 0)), I(_arg(p, 1))) if I(_arg(p, 1)) else b""
    text = _encode(raw, I(_arg(p, 2)) & 0xFFFFFFFF)
    if text is None:
        return _fail(ERROR_INVALID_PARAMETER)
    out, pcch = _arg(p, 3), _arg(p, 4)
    need = len(text) + 1
    if _null(out):
        _write_out(pcch, "I", need)                     # including the terminating null
        return 1
    have = I(pcch.cell.value) if isinstance(pcch, VarRef) else struct.unpack("<I", _read(_ptr(pcch), 4))[0]
    if have < need:
        _write_out(pcch, "I", need)
        return _fail(ERROR_MORE_DATA)
    if isinstance(out, VarRef):
        out.cell.value = text
    else:
        _write(_ptr(out), (text.encode("utf-16-le") + b"\0\0") if wide else (text.encode("cp1252", "replace") + b"\0"))
    _write_out(pcch, "I", len(text))                    # excluding the null
    return 1


# advapi32 CryptoAPI hashing (CryptAcquireContext / CryptCreateHash / CryptHashData / CryptGetHashParam)
_ALG = {0x8001: "md2", 0x8002: "md4", 0x8003: "md5", 0x8004: "sha1", 0x800C: "sha256", 0x800D: "sha384",
        0x800E: "sha512"}


class _Hash:
    def __init__(self, alg):
        self.h = hashlib.new(alg)


def _create_hash(p):
    alg = _ALG.get(I(_arg(p, 1)))
    if alg is None or alg not in hashlib.algorithms_available:
        return _fail(0x80090008 & 0xFFFFFFFF)            # NTE_BAD_ALGID
    _write_out(_arg(p, 4), "Q", _new_handle(_Hash(alg)))
    return 1


def _hash_data(p):
    h = _handles.get(_ptr(_arg(p, 0)))
    if not isinstance(h, _Hash):
        return _fail(ERROR_INVALID_HANDLE)
    src, n = _arg(p, 1), I(_arg(p, 2))
    raw = src.encode("utf-16-le")[:n] if isinstance(src, str) and not src.isdigit() else _read(_ptr(src), n)
    h.h.update(raw)
    return 1


def _get_hash_param(p):
    h = _handles.get(_ptr(_arg(p, 0)))
    if not isinstance(h, _Hash):
        return _fail(ERROR_INVALID_HANDLE)
    param = I(_arg(p, 1))
    digest = h.h.digest()
    if param == 4:                                      # HP_HASHSIZE
        val = struct.pack("<I", len(digest))
    elif param == 1:                                    # HP_ALGID
        val = struct.pack("<I", next(k for k, v in _ALG.items() if v == h.h.name.replace("-", "")))
    else:                                               # HP_HASHVAL
        val = digest
    out, pcb = _arg(p, 2), _arg(p, 3)
    if _null(out):
        _write_out(pcb, "I", len(val))
        return 1
    have = I(pcb.cell.value) if isinstance(pcb, VarRef) else struct.unpack("<I", _read(_ptr(pcb), 4))[0]
    if have < len(val):
        _write_out(pcb, "I", len(val))
        return _fail(ERROR_MORE_DATA)
    _write(_ptr(out), val)
    _write_out(pcb, "I", len(val))
    return 1


EMU.update({
    "cryptstringtobinary": _string_to_binary, "cryptstringtobinaryw": _string_to_binary,
    "cryptstringtobinarya": lambda p: _string_to_binary(p, False),
    "cryptbinarytostring": _binary_to_string, "cryptbinarytostringw": _binary_to_string,
    "cryptbinarytostringa": lambda p: _binary_to_string(p, False),
    "cryptacquirecontext": lambda p: (_write_out(_arg(p, 0), "Q", _new_handle("prov")), 1)[1],
    "cryptreleasecontext": lambda p: (_handles.pop(_ptr(_arg(p, 0)), None), 1)[1],
    "cryptcreatehash": _create_hash, "crypthashdata": _hash_data, "cryptgethashparam": _get_hash_param,
    "cryptdestroyhash": lambda p: (_handles.pop(_ptr(_arg(p, 0)), None), 1)[1],
})


# ---------------------------------------------------------------- processes: OpenProcess, Toolhelp snapshots
class _Proc:
    def __init__(self, pid):
        self.pid = pid


def _proc_alive(pid):
    from .process import _alive
    return _alive(pid)


def _open_process(p):
    pid = I(_arg(p, 2))
    if pid in (0, os.getpid()) or _proc_alive(pid):
        return _new_handle(_Proc(pid or os.getpid()))
    return _fail(ERROR_INVALID_PARAMETER)


def _proc_of(h):
    if h in (-1, 0xFFFFFFFFFFFFFFFF):                  # GetCurrentProcess() pseudo-handle
        return _Proc(os.getpid())
    obj = _handles.get(h)
    return obj if isinstance(obj, _Proc) else None


def _exit_code(pid):
    from .process import _CHILDREN
    ch = _CHILDREN.get(pid)
    if ch is not None and ch.poll() is not None:
        return ch.returncode
    return 259 if _proc_alive(pid) else 0               # STILL_ACTIVE


def _get_exit_code_process(p):
    pr = _proc_of(_ptr(_arg(p, 0)))
    if pr is None:
        return _fail(ERROR_INVALID_HANDLE)
    _write_out(_arg(p, 1), "I", _exit_code(pr.pid) & 0xFFFFFFFF)
    return 1


def _terminate_process(p):
    pr = _proc_of(_ptr(_arg(p, 0)))
    if pr is None:
        return _fail(ERROR_INVALID_HANDLE)
    try:
        os.kill(pr.pid, signal.SIGTERM)
    except OSError:
        return _fail(ERROR_ACCESS_DENIED)
    return 1


def _exe_of(pid):
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return ""


def _image_name(p, size_at=2, out_at=1, size_by_ref=True):
    pr = _proc_of(_ptr(_arg(p, 0)))
    if pr is None:
        return _fail(ERROR_INVALID_HANDLE)
    path = _script_host_path() if pr.pid == os.getpid() else _exe_of(pr.pid)
    out = _arg(p, out_at)
    _put_str(out, path)
    if size_by_ref:
        _write_out(_arg(p, size_at), "I", len(path))
        return 1
    return len(path)


def _script_host_path():
    return O.RT.bivars["a_ahkpath"][0]()


def _module_file_name(p):
    h = _ptr(_arg(p, 0))
    path = _script_host_path() if h == 0 else ""
    if not path:
        path = _module_path(h)
    n = I(_arg(p, 2)) if len(p) > 2 else 260
    path = path[:max(n - 1, 0)]
    _put_str(_arg(p, 1), path)
    return len(path)


def _module_path(h):
    """The file mapped at a module handle (a real library address), from /proc/self/maps."""
    try:
        with open("/proc/self/maps") as fh:
            for line in fh:
                parts = line.split()
                lo, hi = (int(x, 16) for x in parts[0].split("-"))
                if lo <= h < hi and len(parts) >= 6:
                    return parts[5]
    except (OSError, ValueError):
        pass
    return ""


class _Snap:
    def __init__(self, flags, pid):
        self.procs, self.threads, self.mods = [], [], []
        self.i = {"p": 0, "t": 0, "m": 0}
        if flags & 0x2:                                 # TH32CS_SNAPPROCESS
            for d in sorted(os.listdir("/proc"), key=lambda s: int(s) if s.isdigit() else 0):
                if d.isdigit():
                    info = _proc_info(int(d))
                    if info:
                        self.procs.append(info)
        if flags & 0x4:                                 # TH32CS_SNAPTHREAD (all processes)
            for d in os.listdir("/proc"):
                if d.isdigit():
                    try:
                        for t in os.listdir(f"/proc/{d}/task"):
                            self.threads.append((int(t), int(d)))
                    except OSError:
                        pass
        if flags & 0x18:                                # TH32CS_SNAPMODULE(32)
            target = pid or os.getpid()
            seen = {}
            try:
                with open(f"/proc/{target}/maps") as fh:
                    for line in fh:
                        parts = line.split()
                        if len(parts) >= 6 and parts[5].startswith("/"):
                            lo, hi = (int(x, 16) for x in parts[0].split("-"))
                            b = seen.setdefault(parts[5], [lo, hi])
                            b[0], b[1] = min(b[0], lo), max(b[1], hi)
            except OSError:
                pass
            self.mods = [(target, path, lo, hi - lo) for path, (lo, hi) in seen.items()]


def _proc_info(pid):
    try:
        with open(f"/proc/{pid}/stat") as fh:
            st = fh.read()
        name = st[st.index("(") + 1:st.rindex(")")]
        rest = st[st.rindex(")") + 2:].split()
        ppid, nthreads, prio = int(rest[1]), int(rest[17]), int(rest[15])
    except (OSError, ValueError, IndexError):
        return None
    exe = os.path.basename(_exe_of(pid)) or name
    return pid, ppid, nthreads, prio, exe


def _snap_next(p, kind, first):
    snap = _handles.get(_ptr(_arg(p, 0)))
    if not isinstance(snap, _Snap):
        return _fail(ERROR_INVALID_HANDLE)
    if first:
        snap.i[kind] = 0
    lst = {"p": snap.procs, "t": snap.threads, "m": snap.mods}[kind]
    i = snap.i[kind]
    if i >= len(lst):
        return _fail(ERROR_NO_MORE_FILES)
    snap.i[kind] = i + 1
    addr = _ptr(_arg(p, 1))
    if kind == "p":                                     # PROCESSENTRY32W
        pid, ppid, nthreads, prio, exe = lst[i]
        name = exe.encode("utf-16-le")[:518] + b"\0\0"
        _write(addr + 4, struct.pack("<IIQIIIiI", 0, pid, 0, 0, nthreads, ppid, 8, 0))
        _write(addr + 44, name)
    elif kind == "t":                                   # THREADENTRY32
        tid, pid = lst[i]
        _write(addr + 4, struct.pack("<IIIiiI", 0, tid, pid, 8, 0, 0))
    else:                                               # MODULEENTRY32W
        pid, path, base, size = lst[i]
        _write(addr + 4, struct.pack("<IIII", 1, pid, 0xFFFF, 0xFFFF))
        _write(addr + 24, struct.pack("<QIxxxxQ", base, size, base))
        _write(addr + 48, os.path.basename(path).encode("utf-16-le")[:510] + b"\0\0")
        _write(addr + 560, path.encode("utf-16-le")[:518] + b"\0\0")
    return 1


def _token_information(p):
    cls = I(_arg(p, 1))
    out, n = _arg(p, 2), I(_arg(p, 3))
    if cls == 20:                                       # TokenElevation
        val = struct.pack("<I", 1 if os.geteuid() == 0 else 0)
    elif cls == 18:                                     # TokenElevationType: TokenElevationTypeDefault
        val = struct.pack("<I", 1)
    else:
        return _fail(ERROR_INVALID_PARAMETER)
    if not _null(_arg(p, 4)):
        _write_out(_arg(p, 4), "I", len(val))
    if _null(out) or n < len(val):
        return _fail(122)                               # ERROR_INSUFFICIENT_BUFFER
    _write(_ptr(out), val)
    return 1


EMU.update({
    "openprocess": _open_process, "getcurrentprocess": lambda p: -1,
    "getexitcodeprocess": _get_exit_code_process,
    "terminateprocess": _terminate_process,
    "getprocessid": lambda p: (_proc_of(_ptr(_arg(p, 0))) or _Proc(0)).pid,
    "queryfullprocessimagename": lambda p: _image_name(p, 3, 2, True),
    "getprocessimagefilename": lambda p: _image_name(p, 2, 1, False),
    "getmodulefilenameex": lambda p: _image_name(p, 3, 2, False),
    "getmodulefilename": _module_file_name,
    "createtoolhelp32snapshot": lambda p: _new_handle(_Snap(I(_arg(p, 0)), I(_arg(p, 1)))),
    "process32first": lambda p: _snap_next(p, "p", True), "process32next": lambda p: _snap_next(p, "p", False),
    "process32firstw": lambda p: _snap_next(p, "p", True), "process32nextw": lambda p: _snap_next(p, "p", False),
    "thread32first": lambda p: _snap_next(p, "t", True), "thread32next": lambda p: _snap_next(p, "t", False),
    "module32first": lambda p: _snap_next(p, "m", True), "module32next": lambda p: _snap_next(p, "m", False),
    "module32firstw": lambda p: _snap_next(p, "m", True), "module32nextw": lambda p: _snap_next(p, "m", False),
    "openprocesstoken": lambda p: (_write_out(_arg(p, 2), "Q", _new_handle("token")), 1)[1],
    "gettokeninformation": _token_information,
})


# ---------------------------------------------------------------- clipboard (user32)
CF_TEXT, CF_OEMTEXT, CF_UNICODETEXT = 1, 7, 13
_clip_seq = {"n": 1, "last": None}


def _clip_text():
    from .clipboard import get_text
    try:
        t = get_text()
    except Exception:
        t = ""
    if t != _clip_seq["last"]:
        _clip_seq["last"] = t
        _clip_seq["n"] += 1
    return t


def _get_clipboard_data(p):
    fmt = I(_arg(p, 0))
    t = _clip_text()
    if fmt == CF_UNICODETEXT:
        raw = t.encode("utf-16-le") + b"\0\0"
    elif fmt in (CF_TEXT, CF_OEMTEXT):
        raw = t.encode("cp1252" if fmt == CF_TEXT else "cp437", "replace") + b"\0"
    else:
        return 0
    if not t:
        return 0
    h = _alloc(len(raw), False)
    ctypes.memmove(h, raw, len(raw))
    return h


def _set_clipboard_data(p):
    fmt, h = I(_arg(p, 0)), _ptr(_arg(p, 1))
    from .clipboard import set_text
    if fmt == CF_UNICODETEXT and h:
        set_text(_str_arg(h, True))
    elif fmt in (CF_TEXT, CF_OEMTEXT) and h:
        set_text(_str_arg(h, False))
    return h


EMU.update({
    "openclipboard": lambda p: 1, "closeclipboard": lambda p: 1,
    "emptyclipboard": lambda p: (__import__("bunnyhotkey.lib.clipboard", fromlist=["set_text"]).set_text(""), 1)[1],
    "isclipboardformatavailable": lambda p: int(I(_arg(p, 0)) in (CF_TEXT, CF_OEMTEXT, CF_UNICODETEXT)
                                                and _clip_text() != ""),
    "getclipboarddata": _get_clipboard_data, "setclipboarddata": _set_clipboard_data,
    "countclipboardformats": lambda p: 3 if _clip_text() else 0,
    "enumclipboardformats": lambda p: {0: CF_UNICODETEXT, CF_UNICODETEXT: CF_TEXT, CF_TEXT: CF_OEMTEXT}.get(
        I(_arg(p, 0)), 0) if _clip_text() else 0,
    "getclipboardsequencenumber": lambda p: (_clip_text(), _clip_seq["n"])[1],
    "getclipboardowner": lambda p: 0,
})


# ---------------------------------------------------------------- kernel32 file handles
class _File:
    def __init__(self, fd, path, owned=True):
        self.fd, self.path, self.owned = fd, path, owned

    def close(self):
        if self.owned and self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None


_STD = {}


def _std_handle(p):
    which = I(_arg(p, 0)) & 0xFFFFFFFF
    fd = {0xFFFFFFF6: 0, 0xFFFFFFF5: 1, 0xFFFFFFF4: 2}.get(which)
    if fd is None:
        return INVALID_HANDLE_VALUE
    if fd not in _STD:
        _STD[fd] = _new_handle(_File(fd, "<std>", owned=False))
    return _STD[fd]


def _create_file(p):
    from .files import host_path
    name = _str_arg(_arg(p, 0))
    access, disp = I(_arg(p, 1)) & 0xFFFFFFFF, I(_arg(p, 4))
    if name.upper() in ("CONOUT$", "CONIN$"):
        return _new_handle(_File(1 if name.upper() == "CONOUT$" else 0, name, owned=False))
    path = host_path(name)
    rd, wr = bool(access & 0x80000000 or access & 0x1 or access == 0x10000000), bool(access & 0x40000000 or access & 0x2
                                                                                    or access == 0x10000000)
    flags = os.O_RDWR if rd and wr else (os.O_WRONLY if wr else os.O_RDONLY)
    exists = os.path.exists(path)
    if disp == 1:                                       # CREATE_NEW
        if exists:
            return _fail(ERROR_FILE_EXISTS, INVALID_HANDLE_VALUE)
        flags |= os.O_CREAT | os.O_EXCL
    elif disp == 2:                                     # CREATE_ALWAYS
        flags |= os.O_CREAT | os.O_TRUNC
    elif disp == 3:                                     # OPEN_EXISTING
        if not exists:
            return _fail(ERROR_FILE_NOT_FOUND, INVALID_HANDLE_VALUE)
    elif disp == 4:                                     # OPEN_ALWAYS
        flags |= os.O_CREAT
    elif disp == 5:                                     # TRUNCATE_EXISTING
        if not exists:
            return _fail(ERROR_FILE_NOT_FOUND, INVALID_HANDLE_VALUE)
        flags |= os.O_TRUNC
    if os.path.isdir(path):
        return _new_handle(_File(None, path, owned=False))
    try:
        fd = os.open(path, flags, 0o666)
    except FileNotFoundError:
        return _fail(3 if not os.path.isdir(os.path.dirname(path) or ".") else ERROR_FILE_NOT_FOUND,
                     INVALID_HANDLE_VALUE)
    except PermissionError:
        return _fail(ERROR_ACCESS_DENIED, INVALID_HANDLE_VALUE)
    except OSError:
        return _fail(ERROR_INVALID_PARAMETER, INVALID_HANDLE_VALUE)
    O.RT.last_error = 183 if exists and disp in (2, 4) else 0      # ERROR_ALREADY_EXISTS
    return _new_handle(_File(fd, path))


def _file_of(p):
    f = _handles.get(_ptr(_arg(p, 0)))
    return f if isinstance(f, _File) and f.fd is not None else None


def _read_file(p):
    f = _file_of(p)
    if f is None:
        return _fail(ERROR_INVALID_HANDLE)
    n = I(_arg(p, 2))
    try:
        raw = os.read(f.fd, n) if n > 0 else b""
    except OSError:
        return _fail(ERROR_ACCESS_DENIED)
    if raw:
        _write(_ptr(_arg(p, 1)), raw)
    if not _null(_arg(p, 3)):
        _write_out(_arg(p, 3), "I", len(raw))
    return 1


def _write_file(p):
    f = _file_of(p)
    if f is None:
        return _fail(ERROR_INVALID_HANDLE)
    src, n = _arg(p, 1), I(_arg(p, 2))
    raw = src.encode("utf-16-le")[:n] if isinstance(src, str) and not src.lstrip("-").isdigit() else _read(_ptr(src), n)
    try:
        done = os.write(f.fd, raw)
    except OSError:
        return _fail(ERROR_ACCESS_DENIED)
    if not _null(_arg(p, 3)):
        _write_out(_arg(p, 3), "I", done)
    return 1


def _file_size(p, ex):
    f = _file_of(p)
    if f is None:
        return _fail(ERROR_INVALID_HANDLE, 0 if ex else 0xFFFFFFFF)
    size = os.fstat(f.fd).st_size
    if ex:
        _write_out(_arg(p, 1), "q", size)
        return 1
    if not _null(_arg(p, 1)):
        _write_out(_arg(p, 1), "I", size >> 32)
    return size & 0xFFFFFFFF


def _set_file_pointer(p, ex):
    f = _file_of(p)
    if f is None:
        return _fail(ERROR_INVALID_HANDLE, 0 if ex else 0xFFFFFFFF)
    method = I(_arg(p, 3))
    if ex:
        dist = I(_arg(p, 1))
    else:
        dist = I(_arg(p, 1)) & 0xFFFFFFFF
        high = _arg(p, 2)
        if not _null(high):
            hi = I(high.cell.value) if isinstance(high, VarRef) else struct.unpack("<i", _read(_ptr(high), 4))[0]
            dist = (hi << 32) | dist
        elif dist & 0x80000000:
            dist -= 1 << 32
    pos = os.lseek(f.fd, dist, method)
    if ex:
        if not _null(_arg(p, 2)):
            _write_out(_arg(p, 2), "q", pos)
        return 1
    if not _null(_arg(p, 2)):
        _write_out(_arg(p, 2), "i", pos >> 32)
    return pos & 0xFFFFFFFF


def _set_end_of_file(p):
    f = _file_of(p)
    if f is None:
        return _fail(ERROR_INVALID_HANDLE)
    os.ftruncate(f.fd, os.lseek(f.fd, 0, os.SEEK_CUR))
    return 1


def _get_file_attributes(p):
    from .files import host_path
    path = host_path(_str_arg(_arg(p, 0)))
    if not os.path.exists(path):
        return _fail(ERROR_FILE_NOT_FOUND, 0xFFFFFFFF)  # INVALID_FILE_ATTRIBUTES
    attrs = 0x10 if os.path.isdir(path) else 0x20       # DIRECTORY / ARCHIVE
    if not os.access(path, os.W_OK):
        attrs |= 0x1                                    # READONLY
    if os.path.basename(path).startswith("."):
        attrs |= 0x2                                    # HIDDEN
    return attrs


def _full_path_name(p):
    from .files import ahk_path, host_path
    name = _str_arg(_arg(p, 0))
    full = os.path.abspath(host_path(name))
    try:
        full = ahk_path(full)
    except Exception:
        pass
    n = I(_arg(p, 1))
    if n <= len(full):
        return len(full) + 1
    _put_str(_arg(p, 2), full)
    return len(full)


EMU.update({
    "getstdhandle": _std_handle, "createfile": _create_file, "readfile": _read_file, "writefile": _write_file,
    "getfilesize": lambda p: _file_size(p, False), "getfilesizeex": lambda p: _file_size(p, True),
    "setfilepointer": lambda p: _set_file_pointer(p, False), "setfilepointerex": lambda p: _set_file_pointer(p, True),
    "setendoffile": _set_end_of_file, "flushfilebuffers": lambda p: 1,
    "getfiletype": lambda p: 1 if _file_of(p) is not None else 0,      # FILE_TYPE_DISK
    "getfileattributes": _get_file_attributes, "getfullpathname": _full_path_name,
})


# ---------------------------------------------------------------- synchronization: events, mutexes, semaphores
# Unnamed objects live in this process.  A named object's name is also visible to other BHK scripts (a lock file
# under $XDG_RUNTIME_DIR held with a shared flock while any handle is open), so the usual single-instance check -
# CreateMutex then GetLastError() = ERROR_ALREADY_EXISTS - works across scripts, and a named mutex's ownership is
# an exclusive flock that other scripts wait on.  Events and semaphores signal within one script only.
ERROR_ALREADY_EXISTS, ERROR_NOT_OWNER, ERROR_TOO_MANY_POSTS = 183, 288, 298
WAIT_OBJECT_0, WAIT_ABANDONED, WAIT_TIMEOUT, WAIT_FAILED = 0, 0x80, 258, 0xFFFFFFFF


def _sync_dir():
    d = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "bhk-sync-%d" % os.getuid())
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def _lock_path(kind, name):
    safe = "".join(c if c.isalnum() or c in "-_." else "%%%02X" % ord(c) for c in name.replace("\\", "/"))
    return os.path.join(_sync_dir(), f"{kind}.{safe}")


class _Sync:
    def __init__(self, kind, name):
        self.kind, self.name, self.refs = kind, name, 0
        self.name_fd = self.own_fd = None
        if name:                                            # announce the name to other processes
            import fcntl
            self.name_fd = os.open(_lock_path(kind, name), os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(self.name_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.elsewhere = False
            except OSError:
                self.elsewhere = True                       # another script has it open
            fcntl.flock(self.name_fd, fcntl.LOCK_SH)

    def release_name(self):
        for fd in (self.name_fd, self.own_fd):
            if fd is not None:
                os.close(fd)
        self.name_fd = self.own_fd = None


class _Event(_Sync):
    def __init__(self, name, manual, state):
        super().__init__("event", name)
        self.manual, self.state = manual, state

    def signalled(self):
        return self.state

    def acquire(self):
        if not self.manual:
            self.state = False


class _Mutex(_Sync):
    def __init__(self, name):
        super().__init__("mutex", name)
        self.owner, self.count = None, 0

    def _tid(self):
        return 1                                            # every AutoHotkey thread runs on the one OS thread

    def signalled(self):
        if self.owner is not None:
            return self.owner == self._tid()
        if self.name:                                       # free here; is it free in other scripts too?
            import fcntl
            if self.own_fd is None:
                self.own_fd = os.open(_lock_path("mutex", self.name) + ".owner", os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(self.own_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return False
        return True

    def acquire(self):
        self.owner = self._tid()
        self.count += 1

    def release(self):
        if self.owner != self._tid():
            return False
        self.count -= 1
        if self.count == 0:
            self.owner = None
            if self.own_fd is not None:
                import fcntl
                fcntl.flock(self.own_fd, fcntl.LOCK_UN)
        return True


class _Semaphore(_Sync):
    def __init__(self, name, count, maximum):
        super().__init__("semaphore", name)
        self.count, self.max = count, maximum

    def signalled(self):
        return self.count > 0

    def acquire(self):
        self.count -= 1


_NAMED: dict[tuple, _Sync] = {}


def _open_sync(obj_kind, name, make):
    """A handle to the named object (an existing one in this script, else a new one); sets ERROR_ALREADY_EXISTS."""
    key = (obj_kind, name)
    if name and key in _NAMED:
        obj = _NAMED[key]
        exists = True
    else:
        obj = make()
        exists = bool(name) and obj.elsewhere
        if name:
            _NAMED[key] = obj
    obj.refs += 1
    O.RT.last_error = ERROR_ALREADY_EXISTS if exists else 0
    return obj, _new_handle(obj)


def _sync_name(v):
    from .dllcall import _get_str
    return _get_str(v) or ""


def _create_event(p, ex=False):
    name = _sync_name(_arg(p, 1 if ex else 3))
    if ex:
        flags = I(_arg(p, 2))
        manual, state = bool(flags & 1), bool(flags & 2)
    else:
        manual, state = bool(I(_arg(p, 1))), bool(I(_arg(p, 2)))
    _obj, h = _open_sync("event", name, lambda: _Event(name, manual, state))
    return h


def _create_mutex(p):
    return _mutex_common(_sync_name(_arg(p, 2)), bool(I(_arg(p, 1))))


def _mutex_common(name, initial_owner):
    obj, h = _open_sync("mutex", name, lambda: _Mutex(name))
    err = O.RT.last_error
    if initial_owner and err != ERROR_ALREADY_EXISTS and obj.signalled():
        obj.acquire()
    O.RT.last_error = err
    return h


def _create_semaphore(p):
    count, maximum = I(_arg(p, 1)), I(_arg(p, 2))
    name = _sync_name(_arg(p, 3))
    if maximum <= 0 or not 0 <= count <= maximum:
        return _fail(ERROR_INVALID_PARAMETER)
    _obj, h = _open_sync("semaphore", name, lambda: _Semaphore(name, count, maximum))
    return h


def _open_named(p, kind):
    name = _sync_name(_arg(p, 2))
    obj = _NAMED.get((kind, name))
    if obj is None:
        if not name or not os.path.exists(_lock_path(kind, name)):
            return _fail(ERROR_FILE_NOT_FOUND)
        probe = _Sync(kind, name)                           # still open in another script?
        alive = probe.elsewhere
        probe.release_name()
        if not alive:
            return _fail(ERROR_FILE_NOT_FOUND)
        obj = {"event": lambda: _Event(name, True, False), "mutex": lambda: _Mutex(name),
               "semaphore": lambda: _Semaphore(name, 0, 0x7FFFFFFF)}[kind]()
        _NAMED[(kind, name)] = obj
    obj.refs += 1
    O.RT.last_error = 0
    return _new_handle(obj)


def _sync_of(p, cls):
    obj = _handles.get(_ptr(_arg(p, 0)))
    return obj if isinstance(obj, cls) else None


def _set_event(p, state):
    ev = _sync_of(p, _Event)
    if ev is None:
        return _fail(ERROR_INVALID_HANDLE)
    ev.state = state
    return 1


def _pulse_event(p):
    ev = _sync_of(p, _Event)
    if ev is None:
        return _fail(ERROR_INVALID_HANDLE)
    ev.state = False                                        # nobody can be waiting while the script runs here
    return 1


def _release_mutex(p):
    m = _sync_of(p, _Mutex)
    if m is None:
        return _fail(ERROR_INVALID_HANDLE)
    return 1 if m.release() else _fail(ERROR_NOT_OWNER)


def _release_semaphore(p):
    s = _sync_of(p, _Semaphore)
    if s is None:
        return _fail(ERROR_INVALID_HANDLE)
    n = I(_arg(p, 1))
    if n <= 0 or s.count + n > s.max:
        return _fail(ERROR_TOO_MANY_POSTS if n > 0 else ERROR_INVALID_PARAMETER)
    if not _null(_arg(p, 2)):
        _write_out(_arg(p, 2), "i", s.count)
    s.count += n
    return 1


def _waitable(h):
    """(signalled() -> bool, acquire()) for a handle, or None for an invalid one."""
    obj = _handles.get(h)
    if isinstance(obj, (_Event, _Mutex, _Semaphore)):
        return obj.signalled, obj.acquire
    pr = _proc_of(h)
    if pr is not None:
        def done():
            from .process import _reap
            _reap()
            return not _proc_alive(pr.pid)
        return done, lambda: None
    return None


def _wait(handles, wait_all, ms, any_input=False):
    objs = [_waitable(h) for h in handles]
    if any(o is None for o in objs):
        return _fail(ERROR_INVALID_HANDLE, WAIT_FAILED)
    end = None if ms == 0xFFFFFFFF else time.monotonic() + ms / 1000
    while True:
        if wait_all:
            if objs and all(sig() for sig, _a in objs):
                for _s, acq in objs:
                    acq()
                return WAIT_OBJECT_0
        else:
            for i, (sig, acq) in enumerate(objs):
                if sig():
                    acq()
                    return WAIT_OBJECT_0 + i
        if end is not None and time.monotonic() >= end:
            return WAIT_TIMEOUT
        # MsgSleep: timers, hotkeys and callbacks keep running (they may signal the objects)
        O.RT.sleep(10 if end is None else max(0, min(10, int((end - time.monotonic()) * 1000))))


def _handle_array(addr, n):
    return [struct.unpack_from("<Q", _read(addr + 8 * i, 8))[0] for i in range(n)]


def _wait_for_single_object(p):
    h = _ptr(_arg(p, 0))
    if _waitable(h) is None:
        return 0                                            # other kernel objects (threads, files): signalled
    return _wait([h], False, I(_arg(p, 1)) & 0xFFFFFFFF)


def _wait_for_multiple(p, msg=False):
    n = I(_arg(p, 0))
    hs = _handle_array(_ptr(_arg(p, 1)), n) if n else []
    r = _wait(hs, bool(I(_arg(p, 2))) and bool(hs), I(_arg(p, 3)) & 0xFFFFFFFF)
    return r


def _close_handle(p):
    h = _ptr(_arg(p, 0))
    obj = _handles.pop(h, None)
    if isinstance(obj, _File):
        obj.close()
    elif isinstance(obj, _Sync):
        obj.refs -= 1
        if obj.refs <= 0:
            if isinstance(obj, _Mutex) and obj.owner is not None:
                obj.count = 1
                obj.release()                               # abandoned
            obj.release_name()
            _NAMED.pop((obj.kind, obj.name), None)
    return 1


EMU.update({
    "createevent": _create_event, "createeventex": lambda p: _create_event(p, True),
    "openevent": lambda p: _open_named(p, "event"),
    "setevent": lambda p: _set_event(p, True), "resetevent": lambda p: _set_event(p, False),
    "pulseevent": _pulse_event,
    "createmutex": _create_mutex, "createmutexex": lambda p: _mutex_common(_sync_name(_arg(p, 1)),
                                                                           bool(I(_arg(p, 2)) & 1)),
    "openmutex": lambda p: _open_named(p, "mutex"), "releasemutex": _release_mutex,
    "createsemaphore": _create_semaphore, "opensemaphore": lambda p: _open_named(p, "semaphore"),
    "releasesemaphore": _release_semaphore,
    "waitforsingleobject": _wait_for_single_object,
    "waitforsingleobjectex": _wait_for_single_object,
    "waitformultipleobjects": _wait_for_multiple, "waitformultipleobjectsex": _wait_for_multiple,
    "msgwaitformultipleobjects": lambda p: _wait_for_multiple(p, True),
    "msgwaitformultipleobjectsex": lambda p: _wait([*_handle_array(_ptr(_arg(p, 1)), I(_arg(p, 0)))], False,
                                                   I(_arg(p, 2)) & 0xFFFFFFFF),
    "closehandle": _close_handle,
})


# ---------------------------------------------------------------- code pages: MultiByteToWideChar & co.
ERROR_NO_UNICODE_TRANSLATION, ERROR_INSUFFICIENT_BUFFER = 1113, 122
_CODEPAGES = {0: "cp1252", 1: "cp437", 2: "cp1252", 3: "cp1252", 437: "cp437", 1200: "utf-16-le",
              1201: "utf-16-be", 20127: "ascii", 28591: "latin-1", 65000: "utf-7", 65001: "utf-8",
              936: "gbk", 54936: "gb18030", 20936: "gb2312", 51949: "euc-kr", 20932: "euc-jp", 51932: "euc-jp"}


def _codec(cp):
    name = _CODEPAGES.get(cp) or (f"iso8859-{cp - 28590}" if 28591 < cp <= 28606 else f"cp{cp}")
    import codecs
    try:
        codecs.lookup(name)
    except LookupError:
        return None
    return name


def _src_bytes(v, n):
    """n bytes of a multibyte source (-1: up to and including the NUL)."""
    if isinstance(v, str) and not v.strip().lstrip("-").isdigit():
        raw = v.encode("cp1252", "replace")                 # an AStr argument arrives in the ANSI code page
        return raw + b"\0" if n == -1 else raw[:n]
    addr = _ptr(v)
    if n != -1:
        return _read(addr, n)
    out = bytearray()
    while True:
        chunk = _read(addr + len(out), 256)
        k = chunk.find(b"\0")
        if k >= 0:
            return bytes(out + chunk[:k + 1])
        out += chunk


def _src_wide(v, n):
    """A UTF-16 source as a str of n code units (-1: up to and including the NUL)."""
    if isinstance(v, str) and not v.strip().lstrip("-").isdigit():
        s = v
    else:
        addr = _ptr(v)
        if n == -1:
            s = _str_arg(addr)
        else:
            return _read(addr, 2 * n).decode("utf-16-le", "surrogatepass")
    units = s.encode("utf-16-le", "surrogatepass")
    if n == -1:
        return (units + b"\0\0").decode("utf-16-le", "surrogatepass")
    return units[:2 * n].decode("utf-16-le", "surrogatepass")


def _multibyte_to_wide(p):
    cp, flags, src, n, dst, cch = I(_arg(p, 0)), I(_arg(p, 1)), _arg(p, 2), I(_arg(p, 3)), _arg(p, 4), I(_arg(p, 5))
    codec = _codec(cp)
    if codec is None or n == 0 or cch < 0:
        return _fail(ERROR_INVALID_PARAMETER)
    raw = _src_bytes(src, n)
    try:
        text = raw.decode(codec, "strict" if flags & 0x8 else "replace")      # MB_ERR_INVALID_CHARS
    except UnicodeDecodeError:
        return _fail(ERROR_NO_UNICODE_TRANSLATION)
    out = text.encode("utf-16-le", "surrogatepass")
    units = len(out) // 2
    if cch == 0:
        return units
    if units > cch:
        return _fail(ERROR_INSUFFICIENT_BUFFER)
    if isinstance(dst, VarRef):
        dst.cell.value = text.rstrip("\0")
    else:
        _write(_ptr(dst), out)
    return units


def _wide_to_multibyte(p):
    cp, flags, src, n, dst, cb = I(_arg(p, 0)), I(_arg(p, 1)), _arg(p, 2), I(_arg(p, 3)), _arg(p, 4), I(_arg(p, 5))
    codec = _codec(cp)
    if codec is None or n == 0 or cb < 0:
        return _fail(ERROR_INVALID_PARAMETER)
    text = _src_wide(src, n)
    used = False
    if codec.startswith("utf"):
        try:
            out = text.encode(codec, "strict" if flags & 0x80 else "replace")  # WC_ERR_INVALID_CHARS
        except UnicodeEncodeError:
            return _fail(ERROR_NO_UNICODE_TRANSLATION)
    else:
        default = _src_bytes(_arg(p, 6), -1)[:-1] if not _null(_arg(p, 6)) else b"?"
        parts = []
        for ch in text:
            try:
                parts.append(ch.encode(codec))
            except UnicodeEncodeError:
                parts.append(default)
                used = True
        out = b"".join(parts)
    if not _null(_arg(p, 7)):
        _write_out(_arg(p, 7), "i", int(used))
    if cb == 0:
        return len(out)
    if len(out) > cb:
        return _fail(ERROR_INSUFFICIENT_BUFFER)
    _write(_ptr(dst), out)
    return len(out)


# lead-byte ranges of the double-byte code pages (pairs, as CPINFO.LeadByte holds them)
_LEAD_BYTES = {932: bytes((0x81, 0x9F, 0xE0, 0xFC)), 936: bytes((0x81, 0xFE)), 949: bytes((0x81, 0xFE)),
               950: bytes((0x81, 0xFE)), 1361: bytes((0x84, 0xD3, 0xD8, 0xDE, 0xE0, 0xF9))}


def _cp_info(p):
    cp = I(_arg(p, 0))
    codec = _codec(cp)
    if codec is None:
        return _fail(ERROR_INVALID_PARAMETER)
    size = {"utf-8": 4, "utf-7": 5, "utf-16-le": 2, "utf-16-be": 2, "gb18030": 4}.get(codec, 1)
    lead = _LEAD_BYTES.get(cp, b"")
    if lead:
        size = 2
    _write(_ptr(_arg(p, 1)), struct.pack("<I2s12s", size, b"?\0", lead.ljust(12, b"\0")))
    return 1


EMU.update({
    "multibytetowidechar": _multibyte_to_wide, "widechartomultibyte": _wide_to_multibyte,
    "getcpinfo": _cp_info, "isvalidcodepage": lambda p: int(_codec(I(_arg(p, 0))) is not None),
})


# ---------------------------------------------------------------- FormatMessage
# System message texts as Windows 10 (en-US) words them; each ends with ".\r\n" like the originals.
_MESSAGES = {
    0: "The operation completed successfully.", 1: "Incorrect function.",
    2: "The system cannot find the file specified.", 3: "The system cannot find the path specified.",
    4: "The system cannot open the file.", 5: "Access is denied.", 6: "The handle is invalid.",
    8: "Not enough memory resources are available to process this command.",
    14: "Not enough memory resources are available to complete this operation.",
    15: "The system cannot find the drive specified.", 18: "There are no more files.",
    21: "The device is not ready.",
    32: "The process cannot access the file because it is being used by another process.",
    33: "The process cannot access the file because another process has locked a portion of the file.",
    38: "Reached the end of the file.", 50: "The request is not supported.", 80: "The file exists.",
    87: "The parameter is incorrect.", 111: "The file name is too long.",
    112: "There is not enough space on the disk.",
    120: "This function is not supported on this system.",
    122: "The data area passed to a system call is too small.",
    123: "The filename, directory name, or volume label syntax is incorrect.",
    126: "The specified module could not be found.", 127: "The specified procedure could not be found.",
    145: "The directory is not empty.", 183: "Cannot create a file when that file already exists.",
    203: "The system could not find the environment option that was entered.",
    206: "The filename or extension is too long.", 234: "More data is available.",
    258: "The wait operation timed out.", 259: "No more data is available.",
    288: "Attempt to release mutex not owned by caller.", 298: "Too many posts were made to a semaphore.",
    1113: "No mapping for the Unicode character exists in the target multi-byte code page.",
    1168: "Element not found.", 1223: "The operation was canceled by the user.",
    1400: "Invalid window handle.", 1401: "Invalid menu handle.", 1413: "Invalid index.",
    1460: "This operation returned because the timeout period expired.",
    0x80004001: "Not implemented", 0x80004002: "No such interface supported", 0x80004005: "Unspecified error",
    0x80070005: "Access is denied.", 0x80070057: "The parameter is incorrect.",
    0x8007000E: "Not enough memory resources are available to complete this operation.",
    0x800401F3: "Invalid class string", 0x80040154: "Class not registered",
}
ERROR_MR_MID_NOT_FOUND = 317
FORMAT_MESSAGE_ALLOCATE_BUFFER, FORMAT_MESSAGE_IGNORE_INSERTS, FORMAT_MESSAGE_FROM_STRING = 0x100, 0x200, 0x400
FORMAT_MESSAGE_FROM_HMODULE, FORMAT_MESSAGE_FROM_SYSTEM, FORMAT_MESSAGE_ARGUMENT_ARRAY = 0x800, 0x1000, 0x2000


def _format_inserts(text, flags, args, wide):
    """Expand %1..%99 (with !printf-format!), %0, %n, %r, %t, %%, %. and %! the way FormatMessage does."""
    import re
    width = flags & 0xFF
    get_arg = None
    if args:
        def get_arg(i):
            return struct.unpack("<Q", _read(args + 8 * (i - 1), 8))[0]

    out, pos, stop = [], 0, False
    for m in re.finditer(r"%(?:([1-9][0-9]?)(?:!([^!]*)!)?|(.))", text, re.S):
        out.append(text[pos:m.start()])
        pos = m.end()
        if m.group(1):
            if flags & FORMAT_MESSAGE_IGNORE_INSERTS or get_arg is None:
                out.append(m.group(0))
                continue
            v = get_arg(int(m.group(1)))
            fmt = m.group(2) or "s"
            if fmt.endswith(("s", "S")):
                s = _str_arg(v, wide) if v else "(null)"
                pre = fmt[:-1]
                out.append(("%" + pre + "s") % s if pre else s)
            else:
                spec = fmt[-1]
                if spec in "dic":
                    v = v - (1 << 32) if v & 0x80000000 and v < (1 << 32) else v
                    if spec == "c":
                        out.append(chr(v & 0xFFFF))
                        continue
                    spec = "d"
                if spec in "I":
                    spec = "d"
                out.append(("%" + fmt[:-1].replace("I64", "").replace("l", "").replace("h", "") + spec) % v)
            continue
        c = m.group(3)
        if c == "0":
            stop = True
            break
        out.append({"n": "\r\n", "r": "\r", "t": "\t", "b": " ", "%": "%", ".": ".", "!": "!"}.get(c, c))
    if not stop:
        out.append(text[pos:])
    s = "".join(out)
    if width and width != 0xFF:
        import textwrap
        s = "\r\n".join(textwrap.wrap(s.replace("\r\n", " "), width))
    elif width == 0xFF:
        s = s.replace("\r\n", " ")
    return s


def _format_message(p, wide=True):
    flags, source, msgid = I(_arg(p, 0)), _arg(p, 1), I(_arg(p, 2)) & 0xFFFFFFFF
    buf, size, args = _arg(p, 4), I(_arg(p, 5)), _ptr(_arg(p, 6))
    if flags & FORMAT_MESSAGE_FROM_STRING:
        text = _str_arg(source, wide)
    elif flags & (FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_FROM_HMODULE):
        if msgid & 0xFFFF0000 == 0x80070000 and msgid not in _MESSAGES:
            msgid &= 0xFFFF                                 # HRESULT_FROM_WIN32
        if msgid not in _MESSAGES:
            return _fail(ERROR_MR_MID_NOT_FOUND)
        text = _MESSAGES[msgid] + "\r\n"
    else:
        return _fail(ERROR_INVALID_PARAMETER)
    if not flags & FORMAT_MESSAGE_ARGUMENT_ARRAY and args:
        args = 0                                            # a va_list can't be walked here; inserts stay as-is
        flags |= FORMAT_MESSAGE_IGNORE_INSERTS
    s = _format_inserts(text, flags, args, wide)
    raw = s.encode("utf-16-le") + b"\0\0" if wide else s.encode("cp1252", "replace") + b"\0"
    n = len(s)
    if flags & FORMAT_MESSAGE_ALLOCATE_BUFFER:
        mem = _alloc(max(len(raw), size * (2 if wide else 1)), True)
        ctypes.memmove(mem, raw, len(raw))
        _write_out(buf, "Q", mem)
        return n
    if isinstance(buf, VarRef):
        buf.cell.value = s
        return n
    if n + 1 > size:
        return _fail(ERROR_INSUFFICIENT_BUFFER)
    _write(_ptr(buf), raw)
    return n


EMU.update({
    "formatmessage": _format_message, "formatmessagew": _format_message,
    "formatmessagea": lambda p: _format_message(p, False),
})


# ---------------------------------------------------------------- DWM, EnumDisplayMonitors, keyboard layout
S_OK, E_INVALIDARG = 0, 0x80070057


def _dwm_attribute(p):
    from .dllcall import _win
    from .window import geometry
    h, attr, out, cb = _hwnd(_arg(p, 0)), I(_arg(p, 1)), _arg(p, 2), I(_arg(p, 3))
    d, w, c = _win(h)
    if not w:
        return 0x80070006                                   # E_HANDLE
    if attr == 9:                                           # DWMWA_EXTENDED_FRAME_BOUNDS: the visible frame
        if cb < 16:
            return E_INVALIDARG
        x, y, ww, wh = geometry(d, w) if c is None else (0, 0, c.w, c.h)
        _write(_ptr(out), struct.pack("<4i", x, y, x + ww, y + wh))
        return S_OK
    values = {1: 1, 14: 0, 20: 0, 19: 0, 2: 0, 3: 0}       # NCRENDERING_ENABLED, CLOAKED, dark mode, ...
    if attr not in values or cb < 4:
        return E_INVALIDARG
    _write_out(out, "I", values[attr])
    return S_OK


def _enum_display_monitors(p):
    """EnumDisplayMonitors(hdc, lprcClip, callback, lParam): one call per monitor (that meets the clip rect)."""
    from .dllcall import call_address
    clip = _ptr(_arg(p, 1))
    cb, lp = _ptr(_arg(p, 2)), _ptr(_arg(p, 3))
    rect = _alloc(16, True)
    try:
        for i, (mx, my, mw, mh, *_rest) in enumerate(_monitors()):
            r = (mx, my, mx + mw, my + mh)
            if clip:
                cl, ct, cr, cbm = struct.unpack("<4i", _read(clip, 16))
                r = (max(r[0], cl), max(r[1], ct), min(r[2], cr), min(r[3], cbm))
                if r[0] >= r[2] or r[1] >= r[3]:
                    continue
            ctypes.memmove(rect, struct.pack("<4i", *r), 16)
            hdc = _ptr(_arg(p, 0))
            if not I(call_address(cb, [("Ptr", _MON_BASE + i + 1), ("Ptr", hdc), ("Ptr", rect), ("Ptr", lp)]) or 0):
                break
    finally:
        _free(rect)
    return 1


def _keyboard_layout(p):
    from .vars_ import _language
    lang = int(_language(), 16)
    return lang | lang << 16


def _crc32(p):
    init, addr, n = I(_arg(p, 0)) & 0xFFFFFFFF, _ptr(_arg(p, 1)), I(_arg(p, 2))
    return zlib.crc32(_read(addr, n), init)


def _search_path(p):
    from .files import ahk_path, host_path
    path, name, ext = _str_arg(_arg(p, 0)), _str_arg(_arg(p, 1)), _str_arg(_arg(p, 2))
    n, out = I(_arg(p, 3)), _arg(p, 4)
    dirs = [host_path(d) for d in path.split(";")] if path else [os.getcwd()] + os.environ.get("PATH", "").split(":")
    names = [name] + ([name + ext] if ext and "." not in os.path.basename(name) else [])
    for d in dirs:
        for nm in reversed(names):
            full = os.path.join(d, host_path(nm)) if not os.path.isabs(host_path(nm)) else host_path(nm)
            if os.path.isfile(full):
                s = ahk_path(full)
                if n <= len(s):
                    return len(s) + 1
                _put_str(out, s)
                if not _null(_arg(p, 5)):
                    _write_out(_arg(p, 5), "Q", 0)
                return len(s)
    return _fail(ERROR_FILE_NOT_FOUND)


# HSTRING (WinRT strings): immutable UTF-16 in native memory
_HSTRINGS: dict[int, tuple] = {}


def _create_hstring(p):
    s = _src_wide(_arg(p, 0), I(_arg(p, 1))) if not _null(_arg(p, 0)) else ""
    raw = s.encode("utf-16-le", "surrogatepass")
    mem = _alloc(len(raw) + 2, True)
    ctypes.memmove(mem, raw, len(raw))
    _HSTRINGS[mem] = (mem, len(raw) // 2)
    _write_out(_arg(p, 2), "Q", mem if raw else 0)
    if not raw:
        _HSTRINGS.pop(mem, None)
        _free(mem)
    return S_OK


def _hstring_buffer(p):
    h = _ptr(_arg(p, 0))
    mem, n = _HSTRINGS.get(h, (0, 0))
    if not _null(_arg(p, 1)):
        _write_out(_arg(p, 1), "I", n)
    if not mem:
        if "empty" not in _HSTRINGS:
            _HSTRINGS["empty"] = (_alloc(2, True), 0)
        return _HSTRINGS["empty"][0]
    return mem


def _delete_hstring(p):
    h = _ptr(_arg(p, 0))
    if _HSTRINGS.pop(h, None) is not None:
        _free(h)
    return S_OK


EMU.update({
    "dwmiscompositionenabled": lambda p: (_write_out(_arg(p, 0), "i", 1), S_OK)[1],
    "dwmgetwindowattribute": _dwm_attribute,
    "dwmsetwindowattribute": lambda p: S_OK, "dwmextendframeintoclientarea": lambda p: S_OK,
    "dwmenableblurbehindwindow": lambda p: S_OK, "dwmflush": lambda p: S_OK,
    "enumdisplaymonitors": _enum_display_monitors,
    "getkeyboardlayout": _keyboard_layout,
    "rtlcomputecrc32": _crc32,
    "searchpath": _search_path,
    "netapibufferfree": lambda p: (_free(_ptr(_arg(p, 0))), 0)[1],
    "getconsolewindow": lambda p: 0, "freeconsole": lambda p: 1,
    "attachconsole": lambda p: _fail(ERROR_INVALID_HANDLE),
    "processidtosessionid": lambda p: (_write_out(_arg(p, 1), "I", 1), 1)[1] if _proc_alive(I(_arg(p, 0)))
    else _fail(ERROR_INVALID_PARAMETER),
    "getpriorityclass": lambda p: 0x20 if _proc_of(_ptr(_arg(p, 0))) is not None else _fail(ERROR_INVALID_HANDLE),
    "windowscreatestring": _create_hstring, "windowsdeletestring": _delete_hstring,
    "windowsgetstringrawbuffer": _hstring_buffer,
    "windowsgetstringlen": lambda p: _HSTRINGS.get(_ptr(_arg(p, 0)), (0, 0))[1],
})


# ---------------------------------------------------------------- SetWinEventHook (out-of-context events)
# X11 has no WinEvents, so the hooks are fed by watching the window list every 100 ms: foreground changes,
# windows created/destroyed/shown/hidden, title changes, moves/resizes and minimize start/end.
EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND = 0x3, 0x16, 0x17
EVENT_OBJECT_CREATE, EVENT_OBJECT_DESTROY, EVENT_OBJECT_SHOW, EVENT_OBJECT_HIDE = 0x8000, 0x8001, 0x8002, 0x8003
EVENT_OBJECT_LOCATIONCHANGE, EVENT_OBJECT_NAMECHANGE = 0x800B, 0x800C
_HOOKS: dict[int, tuple] = {}
_hook_ids = itertools.count(0x5E000)
_WATCH = {"timer": None, "state": None}


def _snapshot():
    from .window import _dpy, active_window, client_list, geometry, is_visible, pid_of, title_of
    d = _dpy()
    if d is None:
        return None
    wins = {}
    hidden = d.atom("_NET_WM_STATE_HIDDEN")
    for w in client_list(d, True):
        try:
            wins[w] = {"title": title_of(d, w), "geo": geometry(d, w), "visible": is_visible(d, w),
                       "min": hidden in d.get_longs(w, "_NET_WM_STATE"), "pid": pid_of(d, w)}
        except Exception:
            continue
    return {"active": active_window(d), "wins": wins}


def _poll_win_events():
    old = _WATCH["state"]
    new = _snapshot()
    if new is None:
        return ""
    _WATCH["state"] = new
    if old is None:
        return ""
    events = []
    ow, nw = old["wins"], new["wins"]
    for w in nw.keys() - ow.keys():
        events.append((EVENT_OBJECT_CREATE, w))
        if nw[w]["visible"]:
            events.append((EVENT_OBJECT_SHOW, w))
    for w in ow.keys() - nw.keys():
        events.append((EVENT_OBJECT_DESTROY, w))
    for w in nw.keys() & ow.keys():
        a, b = ow[w], nw[w]
        if a["visible"] != b["visible"]:
            events.append((EVENT_OBJECT_SHOW if b["visible"] else EVENT_OBJECT_HIDE, w))
        if a["min"] != b["min"]:
            events.append((EVENT_SYSTEM_MINIMIZESTART if b["min"] else EVENT_SYSTEM_MINIMIZEEND, w))
        if a["title"] != b["title"]:
            events.append((EVENT_OBJECT_NAMECHANGE, w))
        if a["geo"] != b["geo"]:
            events.append((EVENT_OBJECT_LOCATIONCHANGE, w))
    if new["active"] != old["active"] and new["active"]:
        events.append((EVENT_SYSTEM_FOREGROUND, new["active"]))
    from .dllcall import call_address
    now = int(time.monotonic() * 1000) & 0xFFFFFFFF
    for ev, w in events:
        pid = (nw.get(w) or ow.get(w) or {}).get("pid", 0)
        for hid, (mn, mx, cb, want_pid, flags) in list(_HOOKS.items()):
            if not mn <= ev <= mx or (want_pid and want_pid != pid):
                continue
            if flags & 0x2 and pid == os.getpid():          # WINEVENT_SKIPOWNPROCESS
                continue
            call_address(cb, [("Ptr", hid), ("UInt", ev), ("Ptr", w), ("Int", 0), ("Int", 0),
                              ("UInt", pid), ("UInt", now)])
    return ""


def _set_win_event_hook(p):
    mn, mx, cb = I(_arg(p, 0)), I(_arg(p, 1)), _ptr(_arg(p, 3))
    pid, flags = I(_arg(p, 4)), I(_arg(p, 6))
    if not cb or mn > mx:
        return _fail(ERROR_INVALID_PARAMETER)
    hid = next(_hook_ids) * 4
    _HOOKS[hid] = (mn, mx, cb, pid, flags)
    if _WATCH["timer"] is None:
        from .flow import Timer
        from ..objects import BuiltinFunc

        class _HookTimer(Timer):
            __slots__ = ()
            background = True                               # doesn't keep the script running by itself
        t = _HookTimer(BuiltinFunc("WinEventHook", _poll_win_events, 0, 0), 100, 0)
        _WATCH["timer"] = t
        _WATCH["state"] = _snapshot()
        O.RT.timers.append(t)
    return hid


def _unhook_win_event(p):
    if _HOOKS.pop(_ptr(_arg(p, 0)), None) is None:
        return 0
    if not _HOOKS and _WATCH["timer"] is not None:
        t = _WATCH["timer"]
        t.enabled = False
        if t in O.RT.timers:
            O.RT.timers.remove(t)
        _WATCH["timer"] = _WATCH["state"] = None
    return 1


EMU.update({"setwineventhook": _set_win_event_hook, "unhookwinevent": _unhook_win_event})
