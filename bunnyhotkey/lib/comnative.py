"""Native COM objects: real vtables in memory, so the parts of AutoHotkey that work on raw interface pointers
(ComCall, ComObjQuery, ComObjFromPtr, ComObjValue, ObjPtr, DllCall with "Ptr" to an interface) work on Linux.

COM's binary standard is just a pointer to a pointer to a table of function pointers, which ctypes can build.
Every emulated COM object (com.Impl) and every script object handed out by ObjPtr gets an IDispatch whose
GetIDsOfNames/Invoke route back to Python; the vtable functions follow the x64 calling convention the callers use.
Interface pointers that came from elsewhere (a Linux library, another script) are called through their own vtables:
ComObjFromPtr wraps any IDispatch, ComCall calls any method by index.  Strings at this boundary are UTF-16
(OLECHAR, BSTR), as on Windows.
"""
from __future__ import annotations

import ctypes
import struct
import threading
import uuid
import weakref

from .. import objects as O
from .com import ComDispatch, Impl, com_error
from ..objects import AhkObject, throw
from ..values import UNSET

c_hr = ctypes.c_int32
P = ctypes.c_void_p
_libc = ctypes.CDLL(None)
_libc.malloc.restype = P
_libc.malloc.argtypes = [ctypes.c_size_t]
_libc.free.argtypes = [P]

S_OK, S_FALSE = 0, 1
E_NOTIMPL, E_NOINTERFACE, E_POINTER, E_FAIL = 0x80004001, 0x80004002, 0x80004003, 0x80004005
DISP_E_UNKNOWNNAME, DISP_E_MEMBERNOTFOUND, DISP_E_EXCEPTION = 0x80020006, 0x80020003, 0x80020009
DISPATCH_METHOD, DISPATCH_PROPERTYGET, DISPATCH_PROPERTYPUT, DISPATCH_PROPERTYPUTREF = 1, 2, 4, 8
DISPID_VALUE, DISPID_PROPERTYPUT, DISPID_NEWENUM = 0, -3, -4

VT_EMPTY, VT_NULL, VT_I2, VT_I4, VT_R4, VT_R8, VT_CY, VT_DATE, VT_BSTR, VT_DISPATCH, VT_ERROR, VT_BOOL, \
    VT_VARIANT, VT_UNKNOWN = 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13
VT_I1, VT_UI1, VT_UI2, VT_UI4, VT_I8, VT_UI8, VT_INT, VT_UINT = 16, 17, 18, 19, 20, 21, 22, 23
VT_ARRAY, VT_BYREF = 0x2000, 0x4000
VARIANT_SIZE = 24


def hr32(code):
    """An HRESULT as the signed 32-bit value native code returns."""
    code &= 0xFFFFFFFF
    return code - 0x100000000 if code & 0x80000000 else code


# ---------------------------------------------------------------- GUIDs
def guid_bytes(s) -> bytes:
    """"{xxxxxxxx-xxxx-...}" -> the 16-byte GUID structure (Data1-3 little-endian)."""
    return uuid.UUID(str(s).strip()).bytes_le


def guid_str(b: bytes) -> str:
    return "{" + str(uuid.UUID(bytes_le=bytes(b))).upper() + "}"


def read_guid(addr) -> bytes:
    return ctypes.string_at(addr, 16) if addr else b"\0" * 16


IID_IUnknown = guid_bytes("{00000000-0000-0000-C000-000000000046}")
IID_IDispatch = guid_bytes("{00020400-0000-0000-C000-000000000046}")
IID_IEnumVARIANT = guid_bytes("{00020404-0000-0000-C000-000000000046}")
IID_IServiceProvider = guid_bytes("{6D5140C1-7436-11CE-8034-00AA006009FA}")
IID_NULL = b"\0" * 16


# ---------------------------------------------------------------- memory helpers
def rd(fmt, addr):
    return struct.unpack(fmt, ctypes.string_at(addr, struct.calcsize(fmt)))[0]


def wr(fmt, addr, value):
    raw = struct.pack(fmt, value)
    ctypes.memmove(addr, raw, len(raw))


def wstr_at(addr, n=None) -> str:
    """A UTF-16 string at addr (n chars, or up to the terminator)."""
    if not addr:
        return ""
    if n is None:
        n = 0
        while rd("<H", addr + 2 * n):
            n += 1
    return ctypes.string_at(addr, 2 * n).decode("utf-16-le", "replace")


def sys_alloc_string(s) -> int:
    """A BSTR: length prefix, UTF-16 text, terminator; the pointer is to the text."""
    raw = str(s).encode("utf-16-le")
    p = _libc.malloc(4 + len(raw) + 2)
    wr("<I", p, len(raw))
    ctypes.memmove(p + 4, raw + b"\0\0", len(raw) + 2)
    return p + 4


def sys_free_string(b):
    if b:
        _libc.free(b - 4)


def bstr_at(b) -> str:
    return wstr_at(b, rd("<I", b - 4) // 2) if b else ""


# ---------------------------------------------------------------- the object table
_lock = threading.RLock()
_OBJECTS: dict[int, "NativeObject"] = {}            # interface pointer -> object


class NativeObject:
    """One COM object in native memory: [vtable pointer] followed by a reference count.  `methods` are the entries
    after IUnknown, as (restype, argtypes, function) with `this` excluded from argtypes and the call."""

    def __init__(self, methods, iids=(), keep=None):
        self.refs = 1
        self.iids = {IID_IUnknown, *iids}
        self.keep = keep                 # what this object stands for (strong while native refs exist)
        protos = [(c_hr, [P, P]), (ctypes.c_uint32, []), (ctypes.c_uint32, [])]
        funcs = [self._qi, self._addref, self._release]
        for restype, argtypes, fn in methods:
            protos.append((restype, list(argtypes)))
            funcs.append(fn)
        self._cfuncs = []
        for (restype, argtypes), fn in zip(protos, funcs):
            cf = ctypes.CFUNCTYPE(restype, P, *argtypes)(self._guard(fn, restype))
            self._cfuncs.append(cf)
        self._vtbl = (P * len(self._cfuncs))(*[ctypes.cast(f, P).value for f in self._cfuncs])
        self._mem = (P * 2)(ctypes.addressof(self._vtbl), 0)
        self.ptr = ctypes.addressof(self._mem)
        with _lock:
            _OBJECTS[self.ptr] = self

    @staticmethod
    def _guard(fn, restype):
        def call(this, *args):
            try:
                r = fn(*args)
            except ComFailure as e:
                return hr32(e.hr)
            except Exception:
                return hr32(DISP_E_EXCEPTION) if restype is c_hr else 0
            return (hr32(r) if restype is c_hr else r) if r is not None else 0
        return call

    # IUnknown
    def query(self, iid):
        """Another interface of this object (overridden for objects with more than one vtable)."""
        return None

    def _qi(self, riid, ppv):
        if not ppv:
            return E_POINTER
        iid = read_guid(riid)
        if iid in self.iids:
            self._addref()
            wr("<Q", ppv, self.ptr)
            return S_OK
        other = self.query(iid)
        if other is not None:
            other._addref()
            wr("<Q", ppv, other.ptr)
            return S_OK
        wr("<Q", ppv, 0)
        return E_NOINTERFACE

    def _addref(self):
        self.refs += 1
        return self.refs

    def _release(self):
        self.refs -= 1
        if self.refs <= 0:
            self.refs = 0
            self.on_last_release()
        return self.refs

    def on_last_release(self):
        pass


class ComFailure(Exception):
    def __init__(self, hr):
        self.hr = hr


def lookup(ptr):
    return _OBJECTS.get(ptr)


# ---------------------------------------------------------------- VARIANTs
def variant_read(addr):
    """The AutoHotkey value of a VARIANT (VariantToToken)."""
    vt = rd("<H", addr)
    data = addr + 8
    if vt & VT_BYREF:
        data = rd("<Q", data)
        vt &= ~VT_BYREF
        if vt == VT_VARIANT:
            return variant_read(data)
    if vt & VT_ARRAY:
        from .com import ComValueObj
        return ComValueObj(vt, rd("<Q", data))
    if vt in (VT_EMPTY, VT_NULL):
        return ""
    fmt = {VT_I2: "<h", VT_I4: "<i", VT_R4: "<f", VT_R8: "<d", VT_ERROR: "<i", VT_I1: "<b", VT_UI1: "<B",
           VT_UI2: "<H", VT_UI4: "<I", VT_I8: "<q", VT_UI8: "<Q", VT_INT: "<i", VT_UINT: "<I"}.get(vt)
    if fmt:
        return rd(fmt, data)
    if vt == VT_BOOL:
        return int(rd("<h", data) != 0)
    if vt == VT_BSTR:
        return bstr_at(rd("<Q", data))
    if vt == VT_CY:
        return rd("<q", data) / 10000
    if vt == VT_DATE:
        return rd("<d", data)
    if vt in (VT_DISPATCH, VT_UNKNOWN):
        p = rd("<Q", data)
        return object_from_ptr(p, addref=True, vt=vt) if p else ""
    from .com import ComValueObj
    return ComValueObj(vt, rd("<Q", data))


def variant_write(addr, v):
    """Store an AutoHotkey value in a VARIANT (TokenToVariant).  Objects become IDispatch with a reference
    owned by the VARIANT; strings become BSTRs."""
    from .com import ComDispatch, ComValueObj
    ctypes.memset(addr, 0, VARIANT_SIZE)
    if v is UNSET or v is None or (isinstance(v, str) and v == "" and False):
        return
    if isinstance(v, bool):
        wr("<H", addr, VT_BOOL)
        wr("<h", addr + 8, -1 if v else 0)
    elif isinstance(v, int):
        if -0x80000000 <= v <= 0x7FFFFFFF:
            wr("<H", addr, VT_I4)
            wr("<i", addr + 8, v)
        else:
            wr("<H", addr, VT_I8)
            wr("<q", addr + 8, v)
    elif isinstance(v, float):
        wr("<H", addr, VT_R8)
        wr("<d", addr + 8, v)
    elif isinstance(v, str):
        wr("<H", addr, VT_BSTR)
        wr("<Q", addr + 8, sys_alloc_string(v))
    elif isinstance(v, ComValueObj):
        vt = v.vt
        wr("<H", addr, vt)
        if vt == VT_BSTR and isinstance(v.val, str):
            wr("<Q", addr + 8, sys_alloc_string(v.val))
        elif vt == VT_BOOL:
            wr("<h", addr + 8, -1 if O.RT.to_bool(v.val) else 0)
        elif vt in (VT_R4,):
            wr("<f", addr + 8, float(O.RT.to_num(v.val)))
        elif vt in (VT_R8, VT_DATE):
            wr("<d", addr + 8, float(O.RT.to_num(v.val)))
        elif vt in (VT_DISPATCH, VT_UNKNOWN):
            p = O.RT.to_int(v.val) if not isinstance(v.val, AhkObject) else object_ptr(v.val)
            addref(p)
            wr("<Q", addr + 8, p)
        elif v.val not in ("", UNSET):
            wr("<q", addr + 8, O.RT.to_int(v.val))
    elif isinstance(v, AhkObject):
        p = object_ptr(v)
        addref(p)
        wr("<H", addr, VT_DISPATCH)
        wr("<Q", addr + 8, p)


def variant_clear(addr):
    vt = rd("<H", addr)
    if vt == VT_BSTR:
        sys_free_string(rd("<Q", addr + 8))
    elif vt in (VT_DISPATCH, VT_UNKNOWN):
        release(rd("<Q", addr + 8))
    ctypes.memset(addr, 0, VARIANT_SIZE)


# ---------------------------------------------------------------- calling through a vtable
def vfunc(ptr, index, restype, argtypes):
    """Method `index` of the interface at ptr, as a ctypes function taking (this, *args)."""
    vtbl = rd("<Q", ptr)
    fp = rd("<Q", vtbl + 8 * index)
    return ctypes.CFUNCTYPE(restype, P, *argtypes)(fp)


def addref(ptr):
    if not ptr:
        return 0
    return vfunc(ptr, 1, ctypes.c_uint32, [])(ptr)


def release(ptr):
    if not ptr:
        return 0
    return vfunc(ptr, 2, ctypes.c_uint32, [])(ptr)


def query_interface(ptr, iid: bytes):
    """(hresult, interface pointer) from IUnknown::QueryInterface."""
    out = ctypes.c_void_p(0)
    g = ctypes.create_string_buffer(iid, 16)
    hr = vfunc(ptr, 0, c_hr, [P, P])(ptr, ctypes.addressof(g), ctypes.addressof(out))
    return hr & 0xFFFFFFFF, out.value or 0


# ---------------------------------------------------------------- IDispatch servers
class DispatchObject(NativeObject):
    """IDispatch over a member interface: get(name, params), set(name, params, value), call(name, args), enum()."""

    def __init__(self, target, iids=(), keep=None):
        self.target = target
        self.names: dict[str, int] = {}
        self.by_id: dict[int, str] = {}
        super().__init__([
            (c_hr, [P], self.get_type_info_count),
            (c_hr, [ctypes.c_uint, ctypes.c_uint32, P], self.get_type_info),
            (c_hr, [P, P, ctypes.c_uint, ctypes.c_uint32, P], self.get_ids_of_names),
            (c_hr, [ctypes.c_int32, P, ctypes.c_uint32, ctypes.c_uint16, P, P, P, P], self.invoke),
        ], (IID_IDispatch, *iids), keep)

    def get_type_info_count(self, pct):
        if pct:
            wr("<I", pct, 0)
        return S_OK

    def get_type_info(self, i, lcid, pp):
        if pp:
            wr("<Q", pp, 0)
        return E_NOTIMPL

    def dispid(self, name):
        key = name.lower()
        d = self.names.get(key)
        if d is None:
            d = len(self.names) + 1
            self.names[key] = d
            self.by_id[d] = name
        return d

    def get_ids_of_names(self, riid, names, n, lcid, ids):
        for i in range(n):
            name = wstr_at(rd("<Q", names + 8 * i))
            wr("<i", ids + 4 * i, self.dispid(name) if i == 0 else -1)
        return S_OK

    def invoke(self, dispid, riid, lcid, flags, params, result, excep, argerr):
        args, named = [], {}
        if params:
            rgvarg, rgnamed, cargs, cnamed = struct.unpack("<QQII", ctypes.string_at(params, 24))
            vals = [variant_read(rgvarg + VARIANT_SIZE * i) for i in range(cargs)]
            for j in range(cnamed):
                named[rd("<i", rgnamed + 4 * j)] = vals[j]
            args = list(reversed(vals[cnamed:]))
        name = None if dispid in (DISPID_VALUE, DISPID_NEWENUM) else self.by_id.get(dispid)
        if dispid not in (DISPID_VALUE, DISPID_NEWENUM) and name is None:
            return DISP_E_MEMBERNOTFOUND
        if dispid == DISPID_NEWENUM:
            r = self.target.enum_object()
        elif flags & (DISPATCH_PROPERTYPUT | DISPATCH_PROPERTYPUTREF):
            self.target.set(name, args, named.get(DISPID_PROPERTYPUT, ""))
            r = None
        elif flags & DISPATCH_METHOD:
            r = self.target.call(name, args)
        else:
            r = self.target.get(name, args)
        if result:
            variant_write(result, r if r is not None else "")
        return S_OK


class _ImplTarget:
    """A com.Impl seen through IDispatch."""

    def __init__(self, impl):
        self.impl = impl

    def _wrap(self, v):
        from .com import wrap
        return wrap(v)

    def get(self, name, args):
        if name is None:
            return self._wrap(self.impl.get(self.impl.default or "Item", args))
        return self._wrap(self.impl.get(name, args))

    def set(self, name, args, value):
        self.impl.set(name or self.impl.default or "Item", args, value)

    def call(self, name, args):
        return self._wrap(self.impl.call(name or self.impl.default or "Item", args))

    def enum_object(self):
        from .com import _enumerator
        return EnumVariant(_enumerator(self.impl.enum(), 1))


class _ScriptTarget:
    """A script object seen through IDispatch, as AutoHotkey exposes its objects to COM."""

    def __init__(self, obj):
        self.obj = obj

    def get(self, name, args):
        r = O.RT
        if name is None:
            return r.get_item(self.obj, list(args)) if args else self.obj
        return r.get_prop(self.obj, name, list(args))

    def set(self, name, args, value):
        r = O.RT
        if name is None:
            r.set_item(self.obj, value, list(args))
        else:
            r.set_prop(self.obj, name, value, list(args))

    def call(self, name, args):
        r = O.RT
        if name is None:
            return r.call(self.obj, list(args))
        return r.call_method(self.obj, name, list(args))

    def enum_object(self):
        return EnumVariant(O.RT.call_method(self.obj, "__Enum", [1]))


class EnumVariant(AhkObject):
    """_NewEnum results: an IEnumVARIANT over an AutoHotkey enumerator."""

    def __init__(self, enumerator):
        from ..objects import CLASSES
        super().__init__(CLASSES["Object"].prototype)
        self.enumerator = enumerator


class EnumVariantObject(NativeObject):
    def __init__(self, ev):
        self.ev = ev
        super().__init__([
            (c_hr, [ctypes.c_uint32, P, P], self.next),
            (c_hr, [ctypes.c_uint32], self.skip),
            (c_hr, [], self.reset),
            (c_hr, [P], self.clone),
        ], (IID_IEnumVARIANT,), ev)

    def _one(self):
        from ..objects import VarRef
        from ..values import Cell
        cell = Cell("")
        ref = VarRef(cell)
        if not O.RT.to_bool(O.RT.call(self.ev.enumerator, [ref])):
            raise StopIteration
        return cell.value

    def next(self, n, out, fetched):
        got = 0
        try:
            for i in range(n):
                variant_write(out + VARIANT_SIZE * i, self._one())
                got += 1
        except StopIteration:
            pass
        if fetched:
            wr("<I", fetched, got)
        return S_OK if got == n else S_FALSE

    def skip(self, n):
        try:
            for _ in range(n):
                self._one()
        except StopIteration:
            return S_FALSE
        return S_OK

    def reset(self):
        return E_NOTIMPL

    def clone(self, pp):
        return E_NOTIMPL


# ---------------------------------------------------------------- AutoHotkey objects <-> pointers
_BY_OBJ: dict[int, "NativeObject"] = {}             # id(AutoHotkey object) -> its IDispatch


def object_ptr(obj) -> int:
    """The IDispatch pointer of an AutoHotkey object (ComObject, script object), created on first use and stable
    for the object's lifetime.  Native references (AddRef) keep the object alive."""
    from .com import ComDispatch, ComValueObj
    if isinstance(obj, ComValueObj) and obj.vt in (VT_DISPATCH, VT_UNKNOWN):
        return O.RT.to_int(obj.val) if not isinstance(obj.val, AhkObject) else object_ptr(obj.val)
    if isinstance(obj, ComDispatch) and isinstance(obj.impl, ForeignImpl):
        return obj.impl.ptr
    with _lock:
        n = _BY_OBJ.get(id(obj))
        if n is not None:
            return n.ptr
        if isinstance(obj, ComDispatch):
            n = _ImplObject(obj)
        elif isinstance(obj, EnumVariant):
            n = EnumVariantObject(obj)
        else:
            n = _ScriptObject(obj)
        n.refs = 0                      # the script's own reference isn't counted, as in AutoHotkey
        _BY_OBJ[id(obj)] = n
        weakref.finalize(obj, _forget, id(obj), n.ptr)
        return n.ptr


def _forget(key, ptr):
    with _lock:
        _BY_OBJ.pop(key, None)
        _OBJECTS.pop(ptr, None)


class _Holding:
    """Strong reference to the AutoHotkey object while native code holds references; weak otherwise, so the
    object's lifetime stays the script's."""

    def _addref(self):
        self.refs += 1
        self.keep = self._obj()
        return self.refs + 1

    def _release(self):
        self.refs = max(self.refs - 1, 0)
        if self.refs == 0:
            self.keep = None
        return self.refs + 1


class _ImplObject(_Holding, DispatchObject):
    def __init__(self, disp):
        self._obj = weakref.ref(disp)
        iids = {guid_bytes(i) for i in getattr(disp.impl, "iids", ())}
        DispatchObject.__init__(self, _ImplTarget(disp.impl), iids)

    def query(self, iid):
        q = getattr(self._obj().impl, "query_native", None) if self._obj() is not None else None
        return q(iid) if q is not None else None


class _ScriptObject(_Holding, DispatchObject):
    def __init__(self, obj):
        self._obj = weakref.ref(obj)
        DispatchObject.__init__(self, _ScriptTarget(obj))


def object_from_ptr(p, addref=False, vt=VT_DISPATCH):
    """The AutoHotkey value for an interface pointer: the original object when the pointer is one of ours,
    otherwise a ComObject wrapping it (calls go through its vtable).  addref: take a new reference rather than
    the caller's."""
    from .com import ComValueObj
    n = _OBJECTS.get(p)
    if n is not None:
        obj = n._obj() if hasattr(n, "_obj") else getattr(n, "keep", None)
        if obj is not None:
            return obj
    if vt == VT_UNKNOWN:
        if addref:
            globals()["addref"](p)
        return ComValueObj(VT_UNKNOWN, p)
    if addref:
        globals()["addref"](p)
    return ComDispatch(ForeignImpl(p))


# ---------------------------------------------------------------- IDispatch clients
class ForeignImpl(Impl):
    """An IDispatch pointer from outside, as a ComObject: member access goes through GetIDsOfNames/Invoke.
    Owns one reference, released when the wrapper goes away."""
    iface = "IDispatch"

    def __init__(self, ptr):
        self.ptr = ptr
        self._ids = {}

    def __del__(self):
        try:
            release(self.ptr)
        except Exception:
            pass

    def dispid(self, name):
        key = name.lower()
        if key not in self._ids:
            name_buf = ctypes.create_string_buffer(name.encode("utf-16-le") + b"\0\0")
            names = (P * 1)(ctypes.addressof(name_buf))
            out = ctypes.c_int32(0)
            iid = ctypes.create_string_buffer(IID_NULL, 16)
            hr = vfunc(self.ptr, 5, c_hr, [P, P, ctypes.c_uint, ctypes.c_uint32, P])(
                self.ptr, ctypes.addressof(iid), ctypes.addressof(names), 1, 0x400, ctypes.addressof(out))
            if hr < 0:
                com_error(hr, "Unknown name.", name)
            self._ids[key] = out.value
        return self._ids[key]

    def invoke(self, name, flags, args, put=None):
        d = DISPID_VALUE if name is None else self.dispid(name)
        vals = list(args) + ([put] if put is not None else [])
        n = len(vals)
        arr = (ctypes.c_ubyte * (VARIANT_SIZE * max(n, 1)))()
        base = ctypes.addressof(arr)
        for i, v in enumerate(reversed(vals)):
            variant_write(base + VARIANT_SIZE * i, v)
        named = ctypes.c_int32(DISPID_PROPERTYPUT)
        dpb = ctypes.create_string_buffer(struct.pack("<QQII", base if n else 0,
                                                      ctypes.addressof(named) if put is not None else 0, n,
                                                      1 if put is not None else 0), 24)
        res = (ctypes.c_ubyte * VARIANT_SIZE)()
        iid = ctypes.create_string_buffer(IID_NULL, 16)
        excep = (ctypes.c_ubyte * 64)()
        argerr = ctypes.c_uint(0)
        hr = vfunc(self.ptr, 6, c_hr, [ctypes.c_int32, P, ctypes.c_uint32, ctypes.c_uint16, P, P, P, P])(
            self.ptr, d, ctypes.addressof(iid), 0x400, flags, ctypes.addressof(dpb), ctypes.addressof(res),
            ctypes.addressof(excep), ctypes.addressof(argerr))
        for i in range(n):
            variant_clear(base + VARIANT_SIZE * i)
        if hr < 0:
            com_error(hr, "Exception occurred." if hr & 0xFFFFFFFF == DISP_E_EXCEPTION else "Call failed.",
                      name or "")
        v = variant_read(ctypes.addressof(res))
        variant_clear(ctypes.addressof(res))
        return v

    def get(self, name, params):
        return self.invoke(None if name.lower() == (self.default or "").lower() else name,
                           DISPATCH_PROPERTYGET | DISPATCH_METHOD, params)

    def set(self, name, params, value):
        self.invoke(None if name.lower() == (self.default or "").lower() else name, DISPATCH_PROPERTYPUT,
                    params, value)
        return value

    def call(self, name, args):
        return self.invoke(None if name.lower() == (self.default or "").lower() else name,
                           DISPATCH_METHOD | DISPATCH_PROPERTYGET, args)

    default = "\0value"        # obj[x] / obj(x) use DISPID_VALUE

    def enum(self):
        res = (ctypes.c_ubyte * VARIANT_SIZE)()
        dpb = ctypes.create_string_buffer(24)
        iid = ctypes.create_string_buffer(IID_NULL, 16)
        hr = vfunc(self.ptr, 6, c_hr, [ctypes.c_int32, P, ctypes.c_uint32, ctypes.c_uint16, P, P, P, P])(
            self.ptr, DISPID_NEWENUM, ctypes.addressof(iid), 0x400, DISPATCH_METHOD | DISPATCH_PROPERTYGET,
            ctypes.addressof(dpb), ctypes.addressof(res), 0, 0)
        if hr < 0:
            com_error(hr, "Member not found.", "_NewEnum")
        punk = rd("<Q", ctypes.addressof(res) + 8)
        hr, penum = query_interface(punk, IID_IEnumVARIANT)
        release(punk)
        if hr & 0x80000000:
            com_error(hr, "No such interface supported.", "_NewEnum")
        try:
            nxt = vfunc(penum, 3, c_hr, [ctypes.c_uint32, P, P])
            v = (ctypes.c_ubyte * VARIANT_SIZE)()
            got = ctypes.c_uint32(0)
            while nxt(penum, 1, ctypes.addressof(v), ctypes.addressof(got)) == S_OK and got.value:
                val = variant_read(ctypes.addressof(v))
                variant_clear(ctypes.addressof(v))
                yield val
        finally:
            release(penum)


# ---------------------------------------------------------------- the COM runtime's DLL entry points
def _addr(v):
    """A pointer argument: Buffer/object Ptr or integer."""
    if isinstance(v, AhkObject):
        return O.RT.to_int(O.RT.get_prop(v, "Ptr"))
    return O.RT.to_int(v) if v not in ("", UNSET) else 0


def _text_arg(v):
    """A Str/WStr argument (a string) or a pointer to UTF-16 text."""
    if isinstance(v, str) and not v.lstrip("-").isdigit():
        return v
    return wstr_at(_addr(v))


def _out_ptr(target, value, fmt="<Q"):
    from .dllcall import _write_out
    _write_out(target, fmt[1:], value)


def _clsid(pairs, name_arg, out_arg, progids=True):
    from .rot import PROGID_CLSID
    s = _text_arg(pairs[name_arg][1]).strip()
    try:
        b = guid_bytes(s) if s.startswith("{") else guid_bytes(PROGID_CLSID[s.lower()]) if progids else None
    except (ValueError, KeyError):
        b = None
    if b is None:
        return hr32(0x800401F3)                  # CO_E_CLASSSTRING
    ctypes.memmove(_addr(pairs[out_arg][1]), b, 16)
    return S_OK


def _string_from_guid2(pairs):
    s = guid_str(read_guid(_addr(pairs[0][1])))
    n = O.RT.to_int(pairs[2][1]) if len(pairs) > 2 else 39
    if n < 39:
        return 0
    raw = s.encode("utf-16-le") + b"\0\0"
    ctypes.memmove(_addr(pairs[1][1]), raw, len(raw))
    return 39


def _co_create_guid(pairs):
    ctypes.memmove(_addr(pairs[0][1]), uuid.uuid4().bytes_le, 16)
    return S_OK


def _register_active(pairs):
    from .rot import register
    obj = object_from_ptr(_addr(pairs[0][1]), addref=True)
    cookie = register(obj, guid_str(read_guid(_addr(pairs[1][1]))))
    if len(pairs) > 3:
        _out_ptr(pairs[3][1], cookie, "<I")
    return S_OK


def _revoke_active(pairs):
    from .rot import revoke
    return S_OK if revoke(O.RT.to_int(pairs[0][1])) else hr32(0x80070057)


def _get_active(pairs):
    from .rot import get_active
    from ..errors import AhkThrow
    try:
        obj = get_active(guid_str(read_guid(_addr(pairs[0][1]))))
    except AhkThrow:
        _out_ptr(pairs[2][1], 0)
        return hr32(0x800401E3)                  # MK_E_UNAVAILABLE
    p = object_ptr(obj)
    addref(p)
    _out_ptr(pairs[2][1], p)
    return S_OK


def _co_create_instance(pairs):
    from .com import PROGIDS, _proto_setup
    _proto_setup()
    key = guid_str(read_guid(_addr(pairs[0][1]))).lower()
    factory = PROGIDS.get(key)
    out = pairs[4][1]
    if factory is None:
        _out_ptr(out, 0)
        return hr32(0x80040154)                  # REGDB_E_CLASSNOTREG
    obj = ComDispatch(factory())
    hr, p = query_interface(object_ptr(obj), read_guid(_addr(pairs[3][1])))
    _out_ptr(out, p)
    return hr32(hr)


def _variant_init(pairs):
    ctypes.memset(_addr(pairs[0][1]), 0, VARIANT_SIZE)
    return S_OK


def _variant_clear(pairs):
    variant_clear(_addr(pairs[0][1]))
    return S_OK


def install_dll_api():
    """oleaut32/ole32 functions scripts call around COM, added to DllCall's emulation table."""
    from .dllcall import EMU
    EMU.update({
        "sysallocstring": lambda p: sys_alloc_string(_text_arg(p[0][1])),
        "sysallocstringlen": lambda p: sys_alloc_string(_text_arg(p[0][1])[:O.RT.to_int(p[1][1])]),
        "sysfreestring": lambda p: sys_free_string(_addr(p[0][1])) or 0,
        "sysstringlen": lambda p: rd("<I", _addr(p[0][1]) - 4) // 2 if _addr(p[0][1]) else 0,
        "sysstringbytelen": lambda p: rd("<I", _addr(p[0][1]) - 4) if _addr(p[0][1]) else 0,
        "variantinit": _variant_init, "variantclear": _variant_clear,
        "clsidfromstring": lambda p: _clsid(p, 0, 1), "clsidfromprogid": lambda p: _clsid(p, 0, 1),
        "iidfromstring": lambda p: _clsid(p, 0, 1, progids=False),
        "stringfromguid2": _string_from_guid2, "cocreateguid": _co_create_guid,
        "registeractiveobject": _register_active, "revokeactiveobject": _revoke_active,
        "getactiveobject": _get_active, "cocreateinstance": _co_create_instance,
        "cotaskmemalloc": lambda p: _libc.malloc(max(O.RT.to_int(p[0][1]), 1)) or 0,
        "cotaskmemfree": lambda p: _libc.free(_addr(p[0][1])) or 0,
        "coinitializeex": lambda p: S_OK, "oleinitialize": lambda p: S_OK, "oleuninitialize": lambda p: 0,
    })
