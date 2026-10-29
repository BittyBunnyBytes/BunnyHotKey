"""Object/type built-ins (script_object.cpp, lib/vars.cpp type functions)."""
from __future__ import annotations

import math

from .. import objects as O
from ..objects import (AhkArray, AhkClass, AhkMap, AhkObject, BoundFunc, BuiltinFunc, CLASSES, FuncBase, Prop,
                       VarRef, new_error, throw, type_error_msg, value_text)
from ..values import UNSET, fmt_float, str_to_number, to_bool, type_name, wrap
from . import export, setref


def rt():
    return O.RT


# ---------------------------------------------------------------- type checks
@export()
def Type(value):
    if isinstance(value, AhkObject):
        if isinstance(value, AhkClass):
            return "Class"
        p = value.own("__Class")
        if p is not None and p.is_value and value.base is not None and value.base.own("__Class") is not None and value is not CLASSES["Any"].prototype:
            # value is a prototype object
            return "Prototype"
        return value.type_name()
    return type_name(value)


@export()
def IsObject(value):
    return int(isinstance(value, AhkObject))


@export()
def IsInteger(value):
    t = type(value)
    if t is int:
        return 1
    if t is str:
        return int(type(str_to_number(value)) is int)
    return 0


@export()
def IsFloat(value):
    t = type(value)
    if t is float:
        return 1
    if t is str:
        return int(type(str_to_number(value)) is float)
    return 0


@export()
def IsNumber(value):
    t = type(value)
    if t is int or t is float:
        return 1
    if t is str:
        return int(str_to_number(value) is not None)
    return 0


def _strcheck(value, pred):
    if isinstance(value, AhkObject):
        throw("TypeError", type_error_msg("String", value))
    s = rt().to_str(value)
    if s == "":
        return 1
    return int(pred(s))


@export()
def IsDigit(value):
    return _strcheck(value, lambda s: all("0" <= c <= "9" for c in s))


@export()
def IsXDigit(value):
    s = rt().to_str(value)
    if s[:2].lower() == "0x":
        s = s[2:]
    return int(all(c in "0123456789abcdefABCDEF" for c in s))


@export()
def IsAlpha(value, mode=""):
    return _strcheck(value, lambda s: all(c.isalpha() for c in s))


@export()
def IsUpper(value, mode=""):
    return _strcheck(value, lambda s: all(c.isalpha() and c.isupper() for c in s))


@export()
def IsLower(value, mode=""):
    return _strcheck(value, lambda s: all(c.isalpha() and c.islower() for c in s))


@export()
def IsAlnum(value, mode=""):
    return _strcheck(value, lambda s: all(c.isalnum() for c in s))


@export()
def IsSpace(value):
    return _strcheck(value, lambda s: all(c in " \t\n\r\v\f" for c in s))


@export()
def IsTime(value):
    from .datetime_ import parse_timestamp
    try:
        parse_timestamp(rt().to_str(value))
        return 1
    except Exception:
        return 0


@export()
def IsSetRef(ref):
    return int(type(ref) is VarRef and ref.cell.value is not UNSET)


@export()
def IsLabel(name):
    return int(rt().to_str(name).lower() in rt().label_table)


# ---------------------------------------------------------------- conversions
@export()
def Integer(value):
    t = type(value)
    if t is int:
        return value
    if t is float:
        if not math.isfinite(value):
            throw("ValueError", "Invalid value.", fmt_float(value))
        return wrap(int(value))
    if t is str:
        n = str_to_number(value)
        if n is None:
            throw("TypeError", type_error_msg("Number", value), value)
        return n if type(n) is int else wrap(int(n))
    throw("TypeError", type_error_msg("Number", value), value_text(value))


@export()
def Float(value):
    t = type(value)
    if t is float:
        return value
    if t is int:
        return float(value)
    if t is str:
        n = str_to_number(value)
        if n is None:
            throw("TypeError", type_error_msg("Number", value), value)
        return float(n)
    throw("TypeError", type_error_msg("Number", value), value_text(value))


@export()
def Number(value):
    t = type(value)
    if t is int or t is float:
        return value
    if t is str:
        n = str_to_number(value)
        if n is None:
            throw("TypeError", type_error_msg("Number", value), value)
        return n
    throw("TypeError", type_error_msg("Number", value), value_text(value))


@export()
def String(value):
    if isinstance(value, AhkObject):
        p, _ = value.find("ToString")
        if p is not None:
            return rt().call_method(value, "ToString", [])
        throw("MethodError", f'This value of type "{value.type_name()}" has no method named "ToString".', "ToString")
    return rt().to_str(value)


# ---------------------------------------------------------------- object functions
def _name(n):
    return rt().to_str(n)


def ObjGetBase(value):
    if isinstance(value, AhkObject):
        return value.base if value.base is not None else ""
    return rt().base_of(value)


def ObjSetBase(obj, base):
    if not isinstance(obj, AhkObject) or not isinstance(base, AhkObject):
        throw("TypeError", type_error_msg("Object", base))
    b = base
    while b is not None:
        if b is obj:
            throw("ValueError", "Invalid base.")
        b = b.base
    obj.base = base
    return ""


export("ObjGetBase")(ObjGetBase)
export("ObjSetBase")(ObjSetBase)


def HasBase(value, base):
    if not isinstance(base, AhkObject):
        throw("TypeError", type_error_msg("Object", base))
    if isinstance(value, AhkObject):
        return int(value.has_base(base))
    b = rt().base_of(value)
    return int(b is base or b.has_base(base))


export("HasBase")(HasBase)


def HasProp(value, name):
    p, _ = rt().find_prop(value, _name(name))
    return int(p is not None)


export("HasProp")(HasProp)


def HasMethod(value, name=UNSET, pc=UNSET):
    if name is UNSET:
        return int(isinstance(value, FuncBase) or (isinstance(value, AhkObject) and value.find("Call")[0] is not None))
    p, _ = rt().find_prop(value, _name(name))
    if p is None:
        return 0
    if p.call is not None:
        return 1
    if p.is_value and isinstance(p.value, AhkObject):
        return 1
    return 0


export("HasMethod")(HasMethod)


def GetMethod(value, name=UNSET, pc=UNSET):
    if name is UNSET:
        if isinstance(value, FuncBase):
            return value
        name = "Call"
    p, _ = rt().find_prop(value, _name(name))
    if p is not None:
        if p.call is not None:
            return p.call
        if p.is_value and isinstance(p.value, AhkObject):
            return p.value
    throw("MethodError", f'This value of type "{type_name(value)}" has no method named "{_name(name)}".', _name(name))


export("GetMethod")(GetMethod)


@export()
def ObjHasOwnProp(obj, name):
    return int(isinstance(obj, AhkObject) and obj.own(_name(name)) is not None)


@export()
def ObjOwnPropCount(obj):
    if not isinstance(obj, AhkObject):
        throw("TypeError", type_error_msg("Object", obj))
    return len(obj.props)


@export()
def ObjOwnProps(obj):
    return obj_own_props(obj)


@export()
def ObjGetCapacity(obj):
    return len(obj.props)


@export()
def ObjSetCapacity(obj, n):
    return n


@export()
def ObjBindMethod(obj, name=UNSET, *args):
    if name is UNSET:
        return BoundFunc(GetMethod(obj), [obj, *args])
    nm = _name(name)

    class _Late(FuncBase):
        __slots__ = ()

        def call(self, a):
            return rt().call_method(obj, nm, a)
    lf = _Late(CLASSES["Func"].prototype)
    return BoundFunc(lf, list(args))


# Object addresses: an object's address is its native IDispatch (comnative), as in AutoHotkey, so the same pointer
# works with ObjFromPtr, ComObjFromPtr, ComCall and native code.  ObjAddRef/ObjRelease call the interface's
# AddRef/Release; references counted that way keep the object alive until released (counts include the reference
# the script holds, since Python does the real reference counting).
def _obj_arg(obj, fn):
    if not isinstance(obj, AhkObject):
        throw("TypeError", O.type_error_msg("Object", obj), fn)
    from .comnative import object_ptr
    return object_ptr(obj)


def _ptr_arg(ptr, fn):
    p = O.RT.to_int(ptr)
    if p < 65536:
        throw("ValueError", "Invalid object pointer.", fn)
    return p


def _from_ptr(ptr, fn):
    from .comnative import lookup
    p = _ptr_arg(ptr, fn)
    n = lookup(p)
    obj = n._obj() if n is not None and hasattr(n, "_obj") else None
    if obj is None:
        throw("ValueError", "Invalid object pointer.", fn)
    return p, obj


@export()
def ObjPtr(obj):
    return _obj_arg(obj, "ObjPtr")


@export()
def ObjPtrAddRef(obj):
    from .comnative import addref
    p = _obj_arg(obj, "ObjPtrAddRef")
    addref(p)
    return p


@export()
def ObjFromPtr(ptr):
    from .comnative import release
    p, obj = _from_ptr(ptr, "ObjFromPtr")
    release(p)            # takes ownership of one counted reference
    return obj


@export()
def ObjFromPtrAddRef(ptr):
    return _from_ptr(ptr, "ObjFromPtrAddRef")[1]


@export()
def ObjAddRef(ptr):
    from .comnative import addref
    return addref(_ptr_arg(ptr, "ObjAddRef"))


@export()
def ObjRelease(ptr):
    from .comnative import release
    return release(_ptr_arg(ptr, "ObjRelease"))


@export()
def Func(name):
    """v2 removed Func(); kept for v2 alpha scripts."""
    key = rt().to_str(name).lower()
    c = rt().globals.get(key)
    if c is not None and isinstance(c.value, FuncBase):
        return c.value
    if key in rt().builtins:
        return rt().builtins[key]
    return ""


@export()
def Array(*values):
    return AhkArray(None, values)


@export()
def Map(*kv):
    m = AhkMap(None)
    map_set(m, *kv)
    return m


@export()
def Object():
    return AhkObject(CLASSES["Object"].prototype)


@export()
def MemoryError(*a):
    return error_construct("MemoryError", a)


def error_construct(cls, args):
    return construct(CLASSES[cls], list(args))


def construct(cls, args):
    r = rt()
    proto_p = cls.own("Prototype")
    if proto_p is None:
        throw("TypeError", "This class cannot be instantiated.")
    proto = proto_p.value
    if isinstance(cls, AhkClass):
        r.class_ref(cls)
        factory = cls.find_factory()
    else:
        factory = lambda p: AhkObject(p)
    obj = factory(proto)
    r.call_method(obj, "__Init", [])
    p, _ = obj.find("__New")
    if p is not None and p.call is not None:
        r.call(p.call, [obj, *args])
    return obj


def obj_clone(this):
    if not isinstance(this, AhkObject):
        throw("TypeError", type_error_msg("Object", this))
    if type(this) is AhkArray:
        return arr_clone(this)
    if type(this) is AhkMap:
        return map_clone(this)
    o = type(this).__new__(type(this))
    AhkObject.__init__(o, this.base)
    for k, p in this.props.items():
        o.props[k] = Prop(p.name, p.value, p.get, p.set, p.call, p.is_value)
    return o


def obj_define_prop(this, name, desc):
    r = rt()
    nm = _name(name)
    if not isinstance(desc, AhkObject):
        throw("TypeError", type_error_msg("Object", desc))
    g = desc.own("Get")
    s = desc.own("Set")
    c = desc.own("Call")
    v = desc.own("Value")
    if v is not None:
        this.define_value(nm, v.value)
    else:
        p = this.props.get(nm.lower())
        if p is None or p.is_value:
            p = Prop(nm, is_value=False)
            this.props[nm.lower()] = p
        if g is not None:
            p.get = g.value
        if s is not None:
            p.set = s.value
        if c is not None:
            p.call = c.value
    return this


def obj_delete_prop(this, name):
    p = this.props.pop(_name(name).lower(), None)
    if p is None:
        return ""
    return p.value if p.is_value else ""


def obj_get_own_prop_desc(this, name):
    p = this.own(_name(name))
    if p is None:
        throw("PropertyError", f'This value of type "{this.type_name()}" has no own property named "{_name(name)}".', _name(name))
    d = AhkObject(CLASSES["Object"].prototype)
    if p.is_value:
        d.define_value("Value", p.value)
    else:
        if p.get is not None:
            d.define_value("Get", p.get)
        if p.set is not None:
            d.define_value("Set", p.set)
        if p.call is not None:
            d.define_value("Call", p.call)
    return d


class Enumerator(FuncBase):
    __slots__ = ("gen", "nparams")
    native_type = "Enumerator"

    def __init__(self, gen, nparams):
        super().__init__(CLASSES["Enumerator"].prototype)
        self.gen = gen
        self.nparams = nparams

    def call(self, args):
        try:
            vals = next(self.gen)
        except StopIteration:
            return 0
        for i, ref in enumerate(args):
            if i < len(vals):
                setref(ref, vals[i])
        return 1

    def type_name(self):
        return "Enumerator"

    def max_params(self):
        return self.nparams

    def min_params(self):
        return 0


def obj_own_props(this):
    if not isinstance(this, AhkObject):
        throw("TypeError", type_error_msg("Object", this))
    r = rt()

    def gen():
        for p in this.sorted_own():
            if p.is_value:
                yield (p.name, p.value)
            elif p.get is not None:
                try:
                    yield (p.name, r.call(p.get, [this]))
                except Exception:
                    yield (p.name, UNSET)
            else:
                yield (p.name, p.call if p.call is not None else UNSET)
    return Enumerator(gen(), 2)


def func_is_byref(this, n=0):
    r = rt()
    n = r.to_int(n)
    if n == 0:
        return int(any(this.is_byref(i) for i in range(this.max_params())))
    return int(this.is_byref(n - 1))


def func_is_optional(this, n=0):
    n = rt().to_int(n)
    if n == 0:
        return int(this.min_params() < this.max_params())
    return int(this.is_optional(n - 1))


# ---------------------------------------------------------------- Array
def arr_set_length(this, v):
    n = rt().to_int(v)
    if n < 0:
        throw("ValueError", "Invalid value.", str(n))
    L = len(this.items)
    if n < L:
        del this.items[n:]
    else:
        this.items.extend([UNSET] * (n - L))
    return n


def arr_set_capacity(this, v):
    this.capacity = rt().to_int(v)
    return v


def arr_pop(this):
    if not this.items:
        throw("Error", "No items to pop.") if False else throw("IndexError", "Invalid index.", "-1")
    v = this.items.pop()
    return v if v is not UNSET else ""


def arr_insert(this, idx, vals):
    i = this.index(idx, for_insert=True)
    this.items[i:i] = list(vals)
    return ""


def arr_remove(this, idx, length=UNSET):
    i = this.index(idx)
    if length is UNSET:
        v = this.items.pop(i)
        return v if v is not UNSET else ""
    n = rt().to_int(length)
    if n < 0 or i + n > len(this.items):
        throw("ValueError", "Invalid value.", str(n)) if i + n > len(this.items) else None
    del this.items[i:i + n]
    return ""


def arr_delete(this, idx):
    i = this.index(idx)
    v = this.items[i]
    this.items[i] = UNSET
    return v if v is not UNSET else ""


def arr_has(this, idx):
    try:
        i = this.index(idx)
    except Exception:
        return 0
    return int(this.items[i] is not UNSET)


def arr_get(this, idx, default=UNSET):
    i = this.index(idx)
    v = this.items[i]
    if v is UNSET:
        if default is not UNSET:
            return default
        d, _ = this.find("Default")
        if d is not None:
            return rt().get_prop(this, "Default")
        throw("UnsetItemError", "Item has no value.", value_text(idx))
    return v


def arr_clone(this):
    a = AhkArray(this.base, this.items)
    for k, p in this.props.items():
        a.props[k] = Prop(p.name, p.value, p.get, p.set, p.call, p.is_value)
    return a


def arr_enum(this, n=1):
    n = rt().to_int(n)

    def gen():
        i = 0
        while i < len(this.items):
            v = this.items[i]
            yield (v,) if n <= 1 else (i + 1, v)
            i += 1
    return Enumerator(gen(), n)


# ---------------------------------------------------------------- Map
def map_set(this, *kv):
    if len(kv) % 2:
        throw("ValueError", "Invalid number of parameters.") if False else throw("Error", "Invalid number of parameters.")
    for i in range(0, len(kv), 2):
        this.data[this.key(kv[i])] = (kv[i] if type(kv[i]) is not float else fmt_float(kv[i]), kv[i + 1])
    return this if kv else ""


def map_get(this, key, default=UNSET):
    hit = this.data.get(this.key(key))
    if hit is None:
        if default is not UNSET:
            return default
        d, _ = this.find("Default")
        if d is not None:
            return rt().get_prop(this, "Default")
        throw("UnsetItemError", "Item has no value.", value_text(key))
    return hit[1]


def map_delete(this, key):
    hit = this.data.pop(this.key(key), None)
    if hit is None:
        throw("UnsetItemError", "Item has no value.", value_text(key))
    return hit[1]


def map_clone(this):
    m = AhkMap(this.base)
    m.casesense = this.casesense
    m.data = dict(this.data)
    for k, p in this.props.items():
        m.props[k] = Prop(p.name, p.value, p.get, p.set, p.call, p.is_value)
    return m


def map_enum(this, n=1):
    n = rt().to_int(n)
    items = this.sorted_items()

    def gen():
        for k, v in items:
            yield (k,) if n <= 1 else (k, v)
    return Enumerator(gen(), n)


def map_set_casesense(this, v):
    if this.data:
        throw("Error", "Map must be empty.") if True else None
    s = rt().to_str(v) if not isinstance(v, int) else ("On" if v else "Off")
    sl = s.lower()
    this.casesense = "On" if sl in ("on", "1") else "Off" if sl in ("off", "0") else "Locale" if sl == "locale" else throw("ValueError", "Invalid value.", s)
    return this.casesense


# ---------------------------------------------------------------- Error
def error_new(this, msg=UNSET, what=UNSET, extra=UNSET):
    r = rt()
    this.define_value("Message", msg if msg is not UNSET else this.type_name())
    if what is UNSET:
        # the function that called Error() (skip __New and construct)
        stack = r.call_stack
        w = ""
        for cf in reversed(stack):
            if not cf.name.endswith(".__New") and not cf.name.endswith("__Init"):
                w = cf.name
                break
        what = w
    elif isinstance(what, int) and what < 0:
        stack = r.call_stack
        idx = len(stack) + what - 1
        what = stack[idx].name if 0 <= idx < len(stack) else ""
    this.define_value("What", what if not isinstance(what, AhkObject) else "")
    if extra is not UNSET:
        this.define_value("Extra", extra)
    this.define_value("File", r.file)
    this.define_value("Line", r.line)
    this.define_value("Stack", r.stack_text())
    return ""


for _n in ("Error", "OSError", "TargetError", "TimeoutError", "TypeError", "UnsetError", "MemberError",
           "PropertyError", "MethodError", "UnsetItemError", "ValueError", "IndexError", "ZeroDivisionError"):
    pass
