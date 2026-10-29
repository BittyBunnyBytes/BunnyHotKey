"""Buffer, NumGet/NumPut, StrGet/StrPut (lib/vars.cpp, script_object.cpp BufferObject).

Addresses are synthetic: each Buffer gets a stable fake address so pointer
arithmetic (buf.Ptr + offset) round-trips through NumGet/NumPut.
"""
from __future__ import annotations

import struct

from .. import objects as O
from ..objects import AhkObject, CLASSES, throw
from ..values import UNSET
from . import export

_BASE = 0x10000000
_next = [_BASE]
_by_addr: dict[int, "BufferObj"] = {}

TYPES = {"char": ("b", 1), "uchar": ("B", 1), "short": ("h", 2), "ushort": ("H", 2), "int": ("i", 4),
         "uint": ("I", 4), "int64": ("q", 8), "uint64": ("Q", 8), "ptr": ("q", 8), "uptr": ("Q", 8),
         "float": ("f", 4), "double": ("d", 8)}


class BufferObj(AhkObject):
    __slots__ = ("data", "addr")

    def __init__(self, size=0, fill=UNSET, base=None):
        super().__init__(base or CLASSES["Buffer"].prototype)
        self.data = bytearray(size)
        if fill is not UNSET:
            self.data[:] = bytes([O.RT.to_int(fill) & 255]) * size
        self.addr = _next[0]
        _next[0] += max(size, 1) + 0x1000 + (-(size) % 16)
        _by_addr[self.addr] = self


def resolve(target, offset=0):
    """(bytearray, index) for a Buffer object or synthetic address."""
    if isinstance(target, BufferObj):
        return target.data, offset
    if isinstance(target, AhkObject):
        ptr = O.RT.to_int(O.RT.get_prop(target, "Ptr"))
    else:
        ptr = O.RT.to_int(target)
    ptr += offset
    for addr, b in _by_addr.items():
        if addr <= ptr < addr + max(len(b.data), 1):
            return b.data, ptr - addr
    if ptr >= 0x10000:
        # a real address from native code (DllCall return values, callback arguments): read and write process
        # memory directly, as AutoHotkey does
        import ctypes
        return memoryview((ctypes.c_char * (1 << 20)).from_address(ptr)).cast("B"), 0
    throw("ValueError", "Invalid address.", hex(ptr))


def setup(rt, cls):
    from ..classes import method, prop
    cls.factory = lambda proto: BufferObj(0, UNSET, proto)
    p = cls.prototype
    method(p, "__New", lambda this, size=0, fill=UNSET: _new(this, size, fill))
    prop(p, "Ptr", get=lambda this: this.addr)
    prop(p, "Size", get=lambda this: len(this.data), set=lambda this, v: _resize(this, v))


def _new(this, size, fill):
    n = O.RT.to_int(size) if size != "" else 0
    this.data = bytearray(n)
    if fill is not UNSET:
        this.data[:] = bytes([O.RT.to_int(fill) & 255]) * n
    return ""


def _resize(this, v):
    n = O.RT.to_int(v)
    if n < len(this.data):
        del this.data[n:]
    else:
        this.data.extend(bytes(n - len(this.data)))
    return n


@export()
def NumGet(source, offset=0, type_=UNSET):
    if type_ is UNSET:
        type_, offset = offset, 0
    fmt, size = TYPES.get(O.RT.to_str(type_).lower(), (None, 0))
    if fmt is None:
        throw("ValueError", "Invalid value.", O.RT.to_str(type_))
    data, idx = resolve(source, O.RT.to_int(offset))
    if idx + size > len(data) or idx < 0:
        throw("IndexError", "Invalid index.", str(idx))
    return struct.unpack_from("<" + fmt, data, idx)[0]


@export()
def NumPut(*args):
    if len(args) < 3:
        throw("Error", "Too few parameters passed to function.")
    pairs = list(args)
    # trailing: Target [, Offset]
    if len(pairs) % 2 == 1:
        target, offset = pairs[-1], 0
        pairs = pairs[:-1]
    else:
        target, offset = pairs[-2], O.RT.to_int(pairs[-1])
        pairs = pairs[:-2]
    data, idx = resolve(target, offset)
    for i in range(0, len(pairs), 2):
        fmt, size = TYPES.get(O.RT.to_str(pairs[i]).lower(), (None, 0))
        if fmt is None:
            throw("ValueError", "Invalid value.", O.RT.to_str(pairs[i]))
        v = O.RT.to_num(pairs[i + 1])
        if fmt in "fd":
            v = float(v)
        else:
            v = int(v) & ((1 << (8 * size)) - 1)
            if fmt.islower() and v >= 1 << (8 * size - 1):
                v -= 1 << (8 * size)
        struct.pack_into("<" + fmt, data, idx, v)
        idx += size
    return idx


def _enc(enc):
    e = O.RT.to_str(enc).upper() if enc is not UNSET else "UTF-16"
    if e in ("UTF-16", "CP1200"):
        return "utf-16-le", 2
    if e in ("UTF-8", "CP65001"):
        return "utf-8", 1
    if e.startswith("CP"):
        return "cp" + e[2:], 1
    return e.lower(), 1


@export()
def StrGet(source, length=UNSET, encoding=UNSET):
    if isinstance(length, str) and not length.lstrip("-").isdigit() and encoding is UNSET:
        encoding, length = length, UNSET
    codec, unit = _enc(encoding)
    data, idx = resolve(source)
    if length is UNSET or length == "":
        end = idx
        while end + unit <= len(data) and data[end:end + unit] != b"\0" * unit:
            end += unit
        raw = bytes(data[idx:end])
    else:
        n = abs(O.RT.to_int(length))
        raw = bytes(data[idx:idx + n * unit])
        if O.RT.to_int(length) > 0:
            z = raw.find(b"\0" * unit)
            while z >= 0 and z % unit:
                z = raw.find(b"\0" * unit, z + 1)
            if z >= 0:
                raw = raw[:z]
    return raw.decode(codec, "replace")


@export()
def StrPut(string, target=UNSET, length=UNSET, encoding=UNSET):
    s = O.RT.to_str(string)
    if isinstance(target, str) and target and not target.lstrip("-").isdigit():
        encoding, target = target, UNSET
    elif isinstance(length, str) and length and not length.lstrip("-").isdigit():
        encoding, length = length, UNSET
    codec, unit = _enc(encoding)
    raw = s.encode(codec) + b"\0" * unit
    if target is UNSET:
        return len(raw) // unit if unit == 2 else len(raw)
    data, idx = resolve(target)
    if length is not UNSET and length != "":
        raw = raw[:O.RT.to_int(length) * unit]
    data[idx:idx + len(raw)] = raw
    return len(raw) // unit


@export()
def VarSetStrCapacity(ref, cap=UNSET):
    """Strings are Python strings, which size themselves; capacity is reported in characters.  0 frees (empties)
    the variable and -1 just reports, as in AutoHotkey."""
    from ..objects import VarRef
    if type(ref) is not VarRef:
        throw("TypeError", "Expected a VarRef.", "VarSetStrCapacity")
    cur = ref.cell.value
    length = len(cur) if isinstance(cur, str) else 0
    if cap is UNSET or cap == "":
        return length
    n = O.RT.to_int(cap)
    if n == 0:
        ref.cell.value = ""
        return 0
    if n < 0:
        return length
    if not isinstance(cur, str):
        ref.cell.value = ""
    return max(n, length)


@export()
def ClipboardAll(data=UNSET, size=UNSET):
    from .clipboard import get_text
    b = BufferObj(0, UNSET, CLASSES["ClipboardAll"].prototype)
    t = get_text().encode("utf-16-le")
    b.data = bytearray(t)
    return b
