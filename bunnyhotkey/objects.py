"""AHK v2 object model (script_object.cpp): prototypes, classes, Array, Map, Error, Func.

Own properties are kept sorted case-insensitively like Object's binary-searched
field list, so OwnProps() enumerates alphabetically exactly as AutoHotkey does.
"""
from __future__ import annotations

import functools

from .errors import AhkThrow
from .values import UNSET, fmt_float, str_to_number, wrap

RT = None   # the running Runtime (set by runtime.py)


class Prop:
    __slots__ = ("name", "value", "get", "set", "call", "is_value")

    def __init__(self, name, value=UNSET, get=None, set=None, call=None, is_value=True):
        self.name = name
        self.value = value
        self.get = get
        self.set = set
        self.call = call
        self.is_value = is_value


class AhkObject:
    __slots__ = ("base", "props", "__weakref__")
    native_type = "Object"

    def __init__(self, base=None):
        self.base = base
        self.props: dict[str, Prop] = {}

    # --- identity/type ---
    def type_name(self) -> str:
        b = self.base
        while b is not None:
            p = b.props.get("__class")
            if p is not None and p.is_value and type(p.value) is str:
                return p.value
            b = b.base
        return "Object"

    # --- own property helpers ---
    def own(self, name: str):
        return self.props.get(name.lower())

    def define_value(self, name: str, value):
        p = self.props.get(name.lower())
        if p is None:
            self.props[name.lower()] = Prop(name, value)
        else:
            p.is_value = True
            p.value = value
            p.get = p.set = p.call = None

    def define_method(self, name: str, func):
        self.props[name.lower()] = Prop(name, call=func, is_value=False)

    def define_prop(self, name: str, get=None, set=None, call=None):
        p = self.props.get(name.lower())
        if p is None or p.is_value:
            p = Prop(name, is_value=False)
            self.props[name.lower()] = p
        if get is not None:
            p.get = get
        if set is not None:
            p.set = set
        if call is not None:
            p.call = call
        return p

    def find(self, name: str):
        """Find a property in the base chain."""
        key = name.lower()
        o = self
        while o is not None:
            p = o.props.get(key)
            if p is not None:
                return p, o
            o = o.base
        return None, None

    def has_base(self, b) -> bool:
        o = self.base
        while o is not None:
            if o is b:
                return True
            o = o.base
        return False

    def sorted_own(self):
        return [self.props[k] for k in sorted(self.props)]

    # --- native hooks for subclasses ---
    def native_item_get(self, args):
        return NotImplemented

    def native_item_set(self, value, args):
        return NotImplemented

    def __repr__(self):
        return f"<{self.type_name()} object>"


class AhkClass(AhkObject):
    __slots__ = ("name", "factory")
    native_type = "Class"

    def __init__(self, name, base=None, prototype=None, factory=None):
        super().__init__(base)
        self.name = name
        self.factory = factory
        if prototype is not None:
            self.define_value("Prototype", prototype)

    def type_name(self) -> str:
        return "Class"

    @property
    def prototype(self):
        p = self.props.get("prototype")
        return p.value if p else None

    def find_factory(self):
        c = self
        while c is not None:
            if isinstance(c, AhkClass) and c.factory is not None:
                return c.factory
            c = c.base
        return lambda proto: AhkObject(proto)


class AhkArray(AhkObject):
    __slots__ = ("items", "capacity")
    native_type = "Array"

    def __init__(self, base=None, items=None):
        super().__init__(base if base is not None else CLASSES["Array"].prototype)
        self.items = list(items) if items is not None else []
        self.capacity = 0

    def index(self, i, for_insert=False):
        if type(i) is not int:
            n = str_to_number(i) if type(i) is str else (i if type(i) is float else None)
            if type(n) is not int:
                throw("TypeError", type_error_msg("Integer", i), value_text(i))
            i = n
        L = len(self.items)
        if i > 0:
            idx = i - 1
        elif i < 0:
            idx = L + i
        else:
            idx = -1
        lim = L + 1 if for_insert else L
        if idx < 0 or idx >= lim:
            throw("IndexError", "Invalid index.", str(i))
        return idx

    def native_item_get(self, args):
        if len(args) != 1:
            throw("Error", "Too many parameters passed to function." if len(args) > 1 else "Too few parameters passed to function.")
        idx = self.index(args[0])
        v = self.items[idx]
        if v is UNSET:
            d = self.find("Default")[0]
            if d is not None:
                return RT.get_prop(self, "Default")
            throw("UnsetItemError", "Item has no value.", str(args[0]))
        return v

    def native_item_set(self, value, args):
        if len(args) != 1:
            throw("Error", "Too many parameters passed to function.")
        idx = self.index(args[0])
        self.items[idx] = value


def _map_key(k, casesense):
    t = type(k)
    if t is int:
        return (0, k)
    if t is float:
        k = fmt_float(k)
        t = str
    if t is str:
        if casesense == "Off":
            return (1, k.lower())
        if casesense == "Locale":
            return (1, k.casefold())
        return (1, k)
    if isinstance(k, AhkObject):
        return (2, id(k))
    throw("TypeError", "Invalid key.")


class AhkMap(AhkObject):
    __slots__ = ("data", "casesense")
    native_type = "Map"

    def __init__(self, base=None):
        super().__init__(base if base is not None else CLASSES["Map"].prototype)
        self.data: dict = {}      # normalized key -> (original key, value)
        self.casesense = "On"

    def key(self, k):
        return _map_key(k, self.casesense)

    def sorted_items(self):
        def sortkey(item):
            nk, (orig, _v) = item
            if nk[0] == 0:
                return (0, nk[1], "")
            if nk[0] == 1:
                return (1, 0, nk[1])
            return (2, nk[1], "")
        return [v for _, v in sorted(self.data.items(), key=sortkey)]

    def native_item_get(self, args):
        if len(args) != 1:
            throw("Error", "Too many parameters passed to function.")
        hit = self.data.get(self.key(args[0]))
        if hit is None:
            d, _ = self.find("Default")
            if d is not None:
                return RT.get_prop(self, "Default")
            throw("UnsetItemError", "Item has no value.", value_text(args[0]))
        return hit[1]

    def native_item_set(self, value, args):
        if len(args) != 1:
            throw("Error", "Too many parameters passed to function.")
        self.data[self.key(args[0])] = (args[0], value)


class VarRef(AhkObject):
    __slots__ = ("cell",)
    native_type = "VarRef"

    def __init__(self, cell):
        super().__init__(CLASSES["VarRef"].prototype)
        self.cell = cell


class Cell:
    """A variable's storage; shared by closures and ByRef parameters."""
    __slots__ = ("value", "name", "scope")

    def __init__(self, name="", value=UNSET, scope="local"):
        self.value = value
        self.name = name
        self.scope = scope


class FuncBase(AhkObject):
    __slots__ = ()
    native_type = "Func"

    def call(self, args):
        raise NotImplementedError

    @property
    def name(self):
        return ""

    def min_params(self):
        return 0

    def max_params(self):
        return 0

    def is_variadic(self):
        return False

    def is_builtin(self):
        return False

    def is_byref(self, i):
        return False

    def is_optional(self, i):
        return False


class BuiltinFunc(FuncBase):
    __slots__ = ("fname", "fn", "minp", "maxp", "variadic", "byref_params", "pass_rt")

    def __init__(self, name, fn, minp, maxp, variadic=False, byref_params=()):
        super().__init__(CLASSES["Func"].prototype if "Func" in CLASSES else None)
        self.fname = name
        self.fn = fn
        self.minp = minp
        self.maxp = maxp
        self.variadic = variadic
        self.byref_params = byref_params

    @property
    def name(self):
        return self.fname

    def call(self, args):
        n = len(args)
        if n < self.minp:
            # omitted trailing args may still count; check for required missing args
            throw("Error", "Too few parameters passed to function.", self.fname)
        if n > self.maxp and not self.variadic:
            while n > self.maxp and args[n - 1] is UNSET:
                n -= 1
            if n > self.maxp:
                throw("Error", "Too many parameters passed to function.", self.fname)
            args = args[:n]
        for i in range(min(self.minp, n)):
            if args[i] is UNSET:
                throw("Error", "Missing a required parameter.", self.fname)
        return self.fn(*args)

    def min_params(self):
        return self.minp

    def max_params(self):
        return self.maxp

    def is_variadic(self):
        return self.variadic

    def is_builtin(self):
        return True

    def is_byref(self, i):
        return i in self.byref_params

    def is_optional(self, i):
        return i >= self.minp


class BoundFunc(FuncBase):
    __slots__ = ("target", "bound")
    native_type = "BoundFunc"

    def __init__(self, target, bound):
        super().__init__(CLASSES["BoundFunc"].prototype)
        self.target = target
        self.bound = bound

    def call(self, args):
        merged = list(self.bound)
        ai = 0
        for i, v in enumerate(merged):
            if v is UNSET and ai < len(args):
                merged[i] = args[ai]
                ai += 1
        merged.extend(args[ai:])
        return RT.call(self.target, merged)

    @property
    def name(self):
        return ""

    def type_name(self):
        return "BoundFunc"


CLASSES: dict[str, AhkClass] = {}
ANY_PROTO = None


def make_class(name, parent: AhkClass | None, factory=None, proto_base=None):
    pbase = parent.prototype if parent is not None else proto_base
    proto = AhkObject(pbase)
    proto.define_value("__Class", name)
    cbase = parent if parent is not None else None
    cls = AhkClass(name, cbase, proto, factory)
    CLASSES[name] = cls
    return cls


def value_text(v) -> str:
    t = type(v)
    if t is str:
        return v
    if t is int:
        return str(v)
    if t is float:
        return fmt_float(v)
    if v is UNSET:
        return ""
    if isinstance(v, AhkObject):
        return f"{v.type_name()} object"
    return str(v)


def _an(word):
    return "n" if word[:1].lower() in "aeiou" else ""


def type_error_msg(expected, value):
    from .values import type_name
    actual = type_name(value)
    return f"Expected a{_an(expected)} {expected} but got a{_an(actual)} {actual}."


def new_error(cls_name, message, extra="", what=None):
    cls = CLASSES.get(cls_name) or CLASSES["Error"]
    err = AhkObject(cls.prototype)
    err.define_value("Message", message)
    err.define_value("What", what if what is not None else (RT.current_what() if RT else ""))
    err.define_value("Extra", extra)
    if RT is not None:
        f, ln = RT.current_location()
        err.define_value("File", f)
        err.define_value("Line", ln)
        err.define_value("Stack", RT.stack_text())
    return err


def throw(cls_name, message, extra="", what=None):
    raise AhkThrow(new_error(cls_name, message, extra, what))
