"""AutoHotkey v1 runtime library: the __v1_* functions emitted by the v1 frontend (bunnyhotkey/legacy.py).

v1 commands report failure through ErrorLevel instead of throwing, keep v1 argument
orders and conventions, and are implemented on top of the v2 built-ins.
"""
from __future__ import annotations

import math
import os
import re
import time

from .. import objects as O
from ..errors import AhkThrow, ExitThread, GotoEx, ReturnEx
from ..objects import AhkArray, AhkClass, AhkMap, AhkObject, Cell, CLASSES, FuncBase, Prop, VarRef, make_class, throw
from ..values import UNSET, fmt_float, str_to_number, to_bool, wrap
from . import export, setref


def rt():
    return O.RT


def S(v):
    if v is UNSET:
        return ""
    return O.RT.to_str(v)


def I(v, default=0):
    if v is UNSET or v == "":
        return default
    n = str_to_number(v) if type(v) is str else v
    if n is None or isinstance(n, AhkObject):
        return default
    return int(n) if type(n) is float else n


def N(v, default=0):
    if v is UNSET or v == "":
        return default
    n = str_to_number(v) if type(v) is str else v
    return default if n is None or isinstance(n, AhkObject) else n


def B(name, *args):
    """Call a v2 built-in."""
    return O.RT.builtins[name.lower()].call(list(args))


def U(*args):
    """v1 omitted/blank parameters -> v2 omitted parameters."""
    return [UNSET if a == "" else a for a in args]


def EL(v):
    O.RT.v1_set_errorlevel(v)
    return v


def try_el(fn, *args):
    """Run a v2 built-in; ErrorLevel = 0 on success, 1 when it throws."""
    try:
        r = fn(*args)
        EL(0)
        return r
    except AhkThrow:
        EL(1)
        return ""


def quiet(fn, *args):
    try:
        return fn(*args)
    except AhkThrow:
        return ""


def out(ref, value):
    if type(ref) is VarRef:
        ref.cell.value = value
    return value


def var_name(ref):
    return ref.cell.name if type(ref) is VarRef else ""


def setvar(name, value):
    O.RT.v1_cell(name).value = value


def onoff(v, cur=None):
    s = S(v).strip().lower()
    if s in ("on", "1", "true"):
        return 1
    if s in ("off", "0", "false"):
        return 0
    if s == "toggle" or s == "-1":
        return -1
    return cur


# ================================================================ setup

V1_BIVARS = ("errorlevel", "clipboard", "a_thislabel", "a_thismenu", "a_thismenuitem", "a_thismenuitempos",
             "a_gui", "a_guicontrol", "a_guievent", "a_guicontrolevent", "a_guix", "a_guiy", "a_guiwidth",
             "a_guiheight", "a_defaultgui", "a_defaultlistview", "a_defaulttreeview", "a_autotrim",
             "a_formatinteger", "a_formatfloat", "a_batchlines", "a_numbatchlines", "a_ostype", "a_exitreason",
             "a_ipaddress1", "a_ipaddress2", "a_ipaddress3", "a_ipaddress4", "a_caretx", "a_carety",
             "a_stringcasesense", "a_detecthiddenwindows", "a_detecthiddentext", "a_titlematchmode",
             "a_loopfiletimemodified", "a_iscritical", "a_issuspended", "a_ispaused", "a_osversion",
             "a_programfiles", "a_loopregsubkey", "a_loopregtype", "a_ahkversion", "a_thisfunc",
             "a_timeidlephysical", "a_endchar", "a_priorkey")


V1_VERSION = "1.1.37.02"      # the last v1.1 release; A_AhkVersion in v1 scripts


class V1State:
    pass


def setup(r, tr):
    """Called by the loader once a v1 script has been translated, before it is compiled."""
    r.v1 = True
    r.ahk_version = V1_VERSION
    r.v1_labels = tr.labels                 # lower v1 label name -> label name in the translated script
    r.v1_noenv = tr.flags["noenv"]
    r.v1_superglobals = {n.lower() for n in tr.superglobals}
    r.v1_funcs = {}
    r.v1_shadow = {}
    r.v1_frames = []
    r.v1_local_labels = []
    r.v1_block = ([], {})
    r.v1_block_labels = {}
    r.v1_float_fmt = "0.6"
    r.v1_int_fmt = "D"
    r.v1_hex = False
    r.v1_autotrim = True
    r.v1_state = st = V1State()
    st.msg_result = ""
    st.this_label = ""
    st.batchlines = "10ms"
    st.exit_label = None
    st.exit_reason = ""
    st.menu = {"name": "", "item": "", "pos": ""}
    st.gui_event = {}
    st.splash = {}
    r.v1_bivar_names = set(V1_BIVARS)
    r.v1_set_errorlevel = _set_el
    r.v1_base = v1_base
    r.v1_cell = _cell
    r.v1_lookup_func = lookup_func
    r.v1_run_from = run_from
    r.v1_fmt_float = _fmt_float
    r.v1_fmt_int = _fmt_int
    r.v1_to_str = _to_str
    r.v1_arith = _arith
    r.v1_relational = _relational
    _register_vars(r)
    _register_base(r)
    from . import v1gui
    v1gui.setup(r)


def _set_el(v):
    r = O.RT
    r.v1_errorlevel = v


def _register_vars(r):
    V = r.bivars
    st = r.v1_state
    r.v1_errorlevel = 0

    def rw(name, get, set_=None):
        V[name] = (get, set_)

    def set_el(v):
        r.v1_errorlevel = v
    rw("errorlevel", lambda: r.v1_errorlevel, set_el)
    rw("clipboard", V["a_clipboard"][0], V["a_clipboard"][1])
    rw("a_thislabel", lambda: st.this_label)
    rw("a_thismenu", lambda: st.menu["name"])
    rw("a_thismenuitem", lambda: st.menu["item"])
    rw("a_thismenuitempos", lambda: st.menu["pos"])
    for k in ("gui", "guicontrol", "guievent", "guix", "guiy", "guiwidth", "guiheight"):
        rw("a_" + k, (lambda k=k: st.gui_event.get(k, "")))
    rw("a_guicontrolevent", lambda: st.gui_event.get("guievent", ""))
    rw("a_eventinfo", lambda: st.gui_event.get("eventinfo", getattr(r.thread, "event_info", 0)),
       lambda v: st.gui_event.__setitem__("eventinfo", v))
    rw("a_defaultgui", lambda: r.v1_gui.default_name())
    rw("a_defaultlistview", lambda: r.v1_gui.default_ctrl_name("ListView"))
    rw("a_defaulttreeview", lambda: r.v1_gui.default_ctrl_name("TreeView"))
    rw("a_autotrim", lambda: "On" if r.v1_autotrim else "Off")
    rw("a_formatinteger", lambda: r.v1_int_fmt)
    rw("a_formatfloat", lambda: r.v1_float_fmt)
    rw("a_batchlines", lambda: st.batchlines)
    rw("a_numbatchlines", lambda: st.batchlines)
    rw("a_ostype", lambda: "WIN32_NT")
    rw("a_osversion", lambda: "WIN_10" if False else "10.0.19045")
    rw("a_exitreason", lambda: st.exit_reason)
    for i in range(1, 5):
        rw(f"a_ipaddress{i}", (lambda i=i: _ip(i)))
    rw("a_caretx", lambda: _caret(0))
    rw("a_carety", lambda: _caret(1))
    old_scs = V["a_stringcasesense"]
    rw("a_stringcasesense", lambda: {"On": "On", "Off": "Off"}.get(S(old_scs[0]()), S(old_scs[0]())), old_scs[1])
    old_dhw = V["a_detecthiddenwindows"]
    rw("a_detecthiddenwindows", lambda: "On" if to_bool(old_dhw[0]()) else "Off", old_dhw[1])
    old_dht = V["a_detecthiddentext"]
    rw("a_detecthiddentext", lambda: "On" if to_bool(old_dht[0]()) else "Off", old_dht[1])
    rw("a_iscritical", lambda: r.thread.settings.critical)
    rw("a_loopregsubkey", lambda: "")
    rw("a_programfiles", V["a_programfiles"][0])


def _ip(i):
    try:
        lst = B("SysGetIPAddresses")
        return lst.items[i - 1] if len(lst.items) >= i else "0.0.0.0"
    except Exception:
        return "0.0.0.0"


def _caret(i):
    try:
        x, y = Cell(), Cell()
        B("CaretGetPos", VarRef(x), VarRef(y))
        return [x, y][i].value if [x, y][i].value is not UNSET else ""
    except Exception:
        return ""


def _cell(name):
    """The variable `name` as the running v1 code sees it (local in an assume-local function)."""
    r = O.RT
    f = r.v1_frames[-1] if r.v1_frames else None
    if f is not None:
        cf = f.func.fdef if f.func is not None else None
        find = getattr(cf, "dyn_find", None)
        if find is not None:
            c = find(f, name)
            if c is None:
                c = find.create(f, name)
            return c
    return _global_cell(name)


def _global_cell(name):
    r = O.RT
    key = name.lower()
    c = r.v1_shadow.get(key)
    if c is not None:
        return c
    c = r.globals.get(key)
    if c is not None and c.scope == "const":
        c = r.v1_shadow[key] = Cell(name, UNSET, "global")
        return c
    if c is None:
        c = r.globals[key] = Cell(name, UNSET, "global")
    return c


def _fmt_float(f):
    fmt = O.RT.v1_float_fmt
    if math.isinf(f) or math.isnan(f):
        return fmt_float(f)
    m = re.fullmatch(r'\s*(\d*)\.?(\d*)\s*([eEgG]?)\s*', fmt)
    if not m:
        return "%.6f" % f
    width = m[1] or ""
    prec = m[2] if m[2] != "" else "6"
    kind = m[3] or "f"
    if kind in "eE":
        return ("%" + width + "." + prec + kind) % f
    if kind in "gG":
        return ("%" + width + "." + prec + kind) % f
    s = ("%" + "." + prec + "f") % f
    return s.rjust(int(width)) if width.isdigit() and width and int(width) > 0 else s


def _fmt_int(v):
    if O.RT.v1_int_fmt.lower().startswith("h"):
        s = "%x" % abs(v) if O.RT.v1_int_fmt[0] == "h" else "%X" % abs(v)
        return ("-" if v < 0 else "") + "0x" + s
    return str(v)


def _to_str(v):
    if v is UNSET:
        return ""
    if isinstance(v, V1StrBuf):
        return v.text()
    return ""        # objects are blank in a string context


def _arith(op, x, y):
    if x is None or y is None:
        return ""
    if op in ("/", "//") and y == 0:
        return ""
    if op == "/" and type(x) is int and type(y) is int:
        return x / y if x % y else float(x // y)
    if op in ("|", "^", "&", "<<", ">>", ">>>", "//"):
        if type(x) is float or type(y) is float:
            if op == "//":
                return float(math.floor(x / y)) if (x / y) >= 0 else float(-math.floor(-x / y))
            x, y = int(x), int(y)
            r = O.RT
            from ..runtime import arith
            return arith(r, op, x, y)
    return NotImplemented


def _relational(op, a, b):
    from ..runtime import _num_operand
    r = O.RT
    if isinstance(a, AhkObject) or isinstance(b, AhkObject):
        a = "" if isinstance(a, AhkObject) else a
        b = "" if isinstance(b, AhkObject) else b
    na = a if type(a) in (int, float) else str_to_number(a) if type(a) is str else None
    nb = b if type(b) in (int, float) else str_to_number(b) if type(b) is str else None
    if na is None or nb is None:
        sa, sb = S(a), S(b)
        if r.thread.settings.string_case_sense != "On":
            sa, sb = sa.lower(), sb.lower()
        na, nb = sa, sb
    if op == "<":
        return int(na < nb)
    if op == ">":
        return int(na > nb)
    if op == "<=":
        return int(na <= nb)
    return int(na >= nb)


# ================================================================ labels, Gosub, functions by name

def run_from(items, labels, i, f, catch_return=True):
    n = len(items)
    while i < n:
        try:
            while i < n:
                items[i](f)
                i += 1
        except GotoEx as g:
            key = g.label.lower()
            if key in labels:
                i = labels[key]
                continue
            raise
        except ReturnEx:
            if catch_return:
                return
            raise


def label_key(name):
    r = O.RT
    s = S(name).strip()
    low = s.lower()
    return r.v1_labels.get(low, s).lower()


def find_label(name):
    """(items, labels, index, frame, is_global) for a v1 label name, or None."""
    r = O.RT
    key = label_key(name)
    if r.v1_local_labels:
        items, labels, f = r.v1_local_labels[-1]
        if key in labels:
            return items, labels, labels[key], f, False
    items, labels = r.v1_block
    if key in labels:
        return items, labels, labels[key], None, True
    return None


def gosub(name):
    r = O.RT
    hit = find_label(name)
    if hit is None:
        throw("Error", "Target label does not exist.", S(name))
    items, labels, idx, f, glob = hit
    st = r.v1_state
    prev = st.this_label
    st.this_label = S(name)
    if glob:
        r.v1_frames.append(None)
    try:
        run_from(items, labels, idx, f)
    finally:
        if glob:
            r.v1_frames.pop()
        st.this_label = prev
    return ""


@export("__v1_gosub")
def _gosub(name):
    return gosub(name)


@export("__v1_goto")
def _goto(name):
    raise GotoEx(O.RT.v1_labels.get(S(name).strip().lower(), S(name).strip()))


@export("__v1_IsLabel")
def _islabel(name):
    return int(find_label(name) is not None)


class LabelFunc(FuncBase):
    """A callable that runs a v1 label as a subroutine (for timers, menus, hotkeys, Gui events)."""
    __slots__ = ("label",)

    def __init__(self, label):
        super().__init__(CLASSES["Func"].prototype)
        self.label = label

    def call(self, args):
        gosub(self.label)
        return ""

    @property
    def name(self):
        return self.label

    def max_params(self):
        return 0

    def is_variadic(self):
        return True


def lookup_func(name, required=False):
    r = O.RT
    key = S(name).lower()
    c = r.v1_funcs.get(key)
    if c is not None:
        return c.value
    if key in r.builtins:
        return r.builtins[key]
    from ..legacy import FUNCS
    if key in FUNCS and FUNCS[key][0].lower() in r.builtins:
        return r.builtins[FUNCS[key][0].lower()]
    if required:
        throw("Error", "Call to nonexistent function.", S(name))
    return None


def callable_of(target, labels_first=True):
    """A v1 label or function name (or a function object) -> something rt.call accepts."""
    if isinstance(target, AhkObject):
        return target
    name = S(target).strip()
    if not name:
        return None
    if labels_first and find_label(name) is not None:
        return LabelFunc(name)
    f = lookup_func(name)
    if f is not None:
        return f
    if find_label(name) is not None:
        return LabelFunc(name)
    return None


@export("__v1_fn")
def _fn(name):
    if isinstance(name, AhkObject):
        return name
    return lookup_func(name, True)


@export("__v1_Func")
def _func(name):
    f = lookup_func(name)
    return f if f is not None else 0


@export("__v1_IsFunc")
def _isfunc(name):
    f = name if isinstance(name, FuncBase) else lookup_func(name)
    if f is None:
        return 0
    try:
        return f.min_params() + 1
    except Exception:
        return 1


@export("__v1_arg")
def _arg(n):
    a = O.RT.args_array.items
    n = I(n)
    if n == 0:
        return len(a)
    return a[n - 1] if 0 < n <= len(a) else ""


@export("__v1_IsByRef")
def _isbyref(ref):
    if type(ref) is not VarRef:
        return 0
    frames = O.RT.v1_frames
    f = frames[-1] if frames else None
    if f is None or not any(c is ref.cell for c in f.cells):
        return 0
    return 1 if f.aliased and id(ref.cell) in f.aliased else 0


# ================================================================ v1 objects

def _okey(k):
    t = type(k)
    if t is int:
        return (0, k)
    if t is float:
        return (1, fmt_float(k).lower())
    if t is str:
        return (1, k.lower())
    if isinstance(k, AhkObject):
        return (2, id(k))
    return (1, S(k).lower())


class V1Obj(AhkObject):
    """A v1 Object: one case-insensitive key/value store shared by obj.key and obj[key]."""
    __slots__ = ("data",)
    native_type = "Object"

    def __init__(self, base=None):
        super().__init__(base if base is not None else O.RT.v1_obj_proto)
        self.data = {}

    def type_name(self):
        return "Object"

    def find(self, name):
        low = name.lower()
        key = (1, low)
        o = self
        while o is not None:
            if isinstance(o, V1Obj):
                p = o.data.get(key)
                if p is not None:
                    return p, o
            p = o.props.get(low)
            if p is not None:
                return p, o
            if "__class" in o.props and not isinstance(o, AhkClass) and low != "prototype":
                cls = proto_class(o)       # v1 instances see their class's static members
                p = cls.props.get(low) if cls is not None else None
                if p is not None and p.is_value:
                    return p, cls
            o = o.base
        return None, None

    def define_value(self, name, value):
        key = _okey(name)
        p = self.data.get(key)
        if p is None:
            self.data[key] = Prop(name, value)
        else:
            p.value = value

    def get(self, k, default=""):
        p = self.data.get(_okey(k))
        return p.value if p is not None else default

    def set(self, k, v):
        key = _okey(k)
        p = self.data.get(key)
        if p is None:
            self.data[key] = Prop(k, v)
        else:
            p.value = v

    def native_item_get(self, args):
        if not args:
            return ""
        p = self.data.get(_okey(args[0]))
        if p is None:
            if type(args[0]) is str and args[0].lower() == "base":
                return v1_base(self)
            o = self.base
            while o is not None:
                if isinstance(o, V1Obj) and _okey(args[0]) in o.data:
                    v = o.data[_okey(args[0])].value
                    break
                if type(args[0]) is str and "__class" in o.props and not isinstance(o, AhkClass):
                    cls = proto_class(o)
                    q = cls.props.get(args[0].lower()) if cls is not None else None
                    if q is not None and q.is_value and args[0].lower() != "prototype":
                        v = q.value
                        break
                o = o.base
            else:
                return ""
        else:
            v = p.value
        if len(args) > 1:
            return O.RT.get_item(v, list(args[1:])) if isinstance(v, AhkObject) else ""
        return v

    def native_item_set(self, value, args):
        if len(args) > 1:
            cur = self.get(args[0], None)
            if not isinstance(cur, AhkObject):
                cur = V1Obj()
                self.set(args[0], cur)
            O.RT.set_item(cur, value, list(args[1:]))
            return value
        if type(args[0]) is str and args[0].lower() == "base" and isinstance(value, AhkObject):
            self.base = value
            return value
        self.set(args[0], value)
        return value

    def int_keys(self):
        return sorted(k[1] for k in self.data if k[0] == 0)

    def ordered(self):
        def sk(item):
            k, p = item
            return (k[0], k[1] if k[0] != 1 else 0, k[1] if k[0] == 1 else "")
        return [(p.name, p.value) for k, p in sorted(self.data.items(), key=sk)]


def v1_base(o):
    """obj.base in v1: an instance's base is its class object, not v2's prototype."""
    b = o.base
    if b is None or b is O.RT.v1_obj_proto:
        return ""
    return proto_class(b) or b


_PROTO_CLASS = {}


def index_classes(r):
    """Remember every class's prototype once the script is compiled, before any class variable is reassigned."""
    def walk(cls):
        proto = cls.prototype
        if proto is not None:
            _PROTO_CLASS[id(proto)] = (proto, cls)
        for p in list(cls.props.values()):
            if p.is_value and isinstance(p.value, AhkClass) and p.value is not cls and p.name.lower() != "base":
                walk(p.value)
    for c in list(r.globals.values()):
        if isinstance(c.value, AhkClass):
            walk(c.value)


def proto_class(b):
    """The class whose Prototype is `b`, or None."""
    hit = _PROTO_CLASS.get(id(b))
    if hit is not None and hit[0] is b:
        return hit[1]
    p = b.props.get("__class")
    if p is not None and p.is_value and type(p.value) is str and not isinstance(b, AhkClass):
        parts = p.value.split(".")
        c = O.RT.globals.get(parts[0].lower())
        cls = c.value if c is not None else None
        for part in parts[1:]:
            q = cls.props.get(part.lower()) if isinstance(cls, AhkObject) else None
            cls = q.value if q is not None and q.is_value else None
        if isinstance(cls, AhkClass) and cls.prototype is b:
            return cls
    return None


def v1obj_from(pairs):
    o = V1Obj()
    for k, v in pairs:
        o.native_item_set(v, [k])      # a "base" key sets the object's base, as obj.base := x does
    return o


def v1arr(items):
    o = V1Obj()
    for i, v in enumerate(items, 1):
        if v is not UNSET:
            o.data[(0, i)] = Prop(i, v)
    return o


def _register_base(r):
    from ..classes import method
    if "__v1_Base" in CLASSES:
        cls = CLASSES["__v1_Base"]
    else:
        cls = make_class("__v1_Base", CLASSES["Object"], factory=lambda proto: V1Obj(proto))
    r.v1_obj_proto = proto = cls.prototype
    r.globals["__v1_base"] = Cell("__v1_Base", cls, "const")
    r.globals["__v1_any"] = Cell("__v1_Any", CLASSES["Any"], "const")

    def M(name, fn):
        method(proto, name, fn)
    M("Insert", _insert)
    M("InsertAt", lambda this, pos, *vals: _insert_at(this, I(pos), list(vals)))
    M("Push", lambda this, *vals: _push(this, list(vals)))
    M("Pop", _pop)
    M("RemoveAt", lambda this, pos, n=UNSET: _remove_at(this, I(pos), n))
    M("Delete", lambda this, k, last=UNSET: _delete(this, k, last))
    M("Remove", _remove)
    M("MinIndex", lambda this: (this.int_keys() or [""])[0])
    M("MaxIndex", lambda this: (this.int_keys() or [""])[-1])
    M("Length", lambda this: max(this.int_keys() or [0], default=0) if (this.int_keys() or [0])[-1] > 0 else 0)
    M("Count", lambda this: len(this.data))
    M("HasKey", lambda this, k: int(_okey(k) in this.data))
    M("Clone", _clone)
    M("SetCapacity", lambda this, *a: 0)
    M("GetCapacity", lambda this, *a: len(this.data))
    M("GetAddress", lambda this, k: 0)
    M("_NewEnum", lambda this: _enum_obj(this))
    M("__Enum", lambda this, n=1: _enum_func(this))
    M("ToString", lambda this: "")


def _insert(this, *args):
    if not args:
        return ""
    if len(args) == 1:
        keys = this.int_keys()
        this.set((keys[-1] + 1) if keys else 1, args[0])
        return 1
    k = args[0]
    if type(k) is int or (type(k) is str and type(str_to_number(k)) is int and k.strip().lstrip("-").isdigit() and False):
        return _insert_at(this, k, list(args[1:]))
    this.set(k, args[1])
    return 1


def _insert_at(this, pos, vals):
    keys = [k for k in this.int_keys() if k >= pos]
    n = len(vals)
    for k in reversed(keys):
        p = this.data.pop((0, k))
        p.name = k + n
        this.data[(0, k + n)] = p
    for i, v in enumerate(vals):
        this.data[(0, pos + i)] = Prop(pos + i, v)
    return ""


def _push(this, vals):
    keys = this.int_keys()
    start = (keys[-1] + 1) if keys and keys[-1] > 0 else 1
    for i, v in enumerate(vals):
        this.data[(0, start + i)] = Prop(start + i, v)
    return start + len(vals) - 1


def _pop(this):
    keys = this.int_keys()
    if not keys:
        return ""
    return this.data.pop((0, keys[-1])).value


def _remove_at(this, pos, n=UNSET):
    cnt = 1 if n is UNSET else I(n)
    removed = None
    for k in range(pos, pos + cnt):
        p = this.data.pop((0, k), None)
        if removed is None and p is not None:
            removed = p.value
    for k in [k for k in this.int_keys() if k >= pos + cnt]:
        p = this.data.pop((0, k))
        p.name = k - cnt
        this.data[(0, k - cnt)] = p
    return removed if n is UNSET and removed is not None else ("" if n is UNSET else cnt)


def _delete(this, k, last=UNSET):
    if last is UNSET:
        p = this.data.pop(_okey(k), None)
        return p.value if p is not None else ""
    lo, hi = _okey(k), _okey(last)
    cnt = 0
    for key in list(this.data):
        if key[0] == lo[0] and lo[1] <= key[1] <= hi[1]:
            del this.data[key]
            cnt += 1
    return cnt


def _remove(this, k=UNSET, last=UNSET):
    if k is UNSET:
        return _pop(this)
    if type(k) is int and last is UNSET:
        p = this.data.pop((0, k), None)
        for kk in [x for x in this.int_keys() if x > k]:
            q = this.data.pop((0, kk))
            q.name = kk - 1
            this.data[(0, kk - 1)] = q
        return p.value if p is not None else ""
    if type(k) is int and type(last) is int:
        cnt = 0
        for kk in range(k, last + 1):
            if this.data.pop((0, kk), None) is not None:
                cnt += 1
        n = last - k + 1
        for kk in [x for x in this.int_keys() if x > last]:
            q = this.data.pop((0, kk))
            q.name = kk - n
            this.data[(0, kk - n)] = q
        return cnt
    return _delete(this, k, last)


def _clone(this):
    o = V1Obj(this.base)
    o.data = {k: Prop(p.name, p.value) for k, p in this.data.items()}
    return o


def _enum_items(this):
    if isinstance(this, V1Obj):
        return this.ordered()
    return []


def _enum_func(this):
    from ..classes import bif
    items = _enum_items(this)
    pos = [0]

    def nxt(k=UNSET, v=UNSET):
        if pos[0] >= len(items):
            return 0
        key, val = items[pos[0]]
        pos[0] += 1
        setref(k, key)
        setref(v, val)
        return 1
    return bif("Next", nxt)


def _enum_obj(this):
    o = V1Obj()
    f = _enum_func(this)
    from ..classes import method
    method(o, "Next", lambda self, k=UNSET, v=UNSET: f.call([k, v]))
    return o


@export("__v1_Object")
def _object(*args):
    if len(args) == 1 and isinstance(args[0], AhkObject):
        return args[0]
    return v1obj_from(zip(args[0::2], args[1::2]))


@export("__v1_Array")
def _array(*args):
    return v1arr(args)


def _as_obj(o):
    return o if isinstance(o, V1Obj) else None


def _objfn(name):
    def call(obj, *args):
        if isinstance(obj, V1Obj):
            return O.RT.call_method(obj, name, list(args))
        if isinstance(obj, AhkObject):
            return O.RT.call_method(obj, name, list(args))
        return ""
    return call


for _n in ("Insert", "InsertAt", "Push", "Pop", "Remove", "RemoveAt", "Delete", "MinIndex", "MaxIndex", "Length",
           "Count", "HasKey", "Clone", "GetCapacity", "SetCapacity", "GetAddress"):
    export("__v1_Obj" + _n)(_objfn(_n))


@export("__v1_ObjNewEnum")
def _objnewenum(obj):
    return _enum_obj(obj)


@export("__v1_ObjRawSet")
def _objrawset(obj, k, v):
    if isinstance(obj, V1Obj):
        obj.set(k, v)
    elif isinstance(obj, AhkObject):
        obj.define_value(S(k), v)
    return ""


@export("__v1_ObjRawGet")
def _objrawget(obj, k):
    if isinstance(obj, V1Obj):
        return obj.get(k)
    return ""


@export("__v1_ObjBindMethod")
def _objbind(obj, name=UNSET, *args):
    return B("ObjBindMethod", obj, name, *args)


@export("__v1_IsObject")
def _isobject(*vals):
    return int(all(isinstance(v, AhkObject) for v in vals)) if vals else 0


@export("__v1_Exception")
def _exception(msg="", what=UNSET, extra=UNSET):
    r = O.RT
    e = r.call(CLASSES["Error"], [msg] + ([what] if what is not UNSET else [UNSET]) + ([extra] if extra is not UNSET else []))
    if type(what) is int or (type(what) is str and what.lstrip("-").isdigit()):
        r.set_prop(e, "What", r.call_stack[-1].name if r.call_stack else "")
    return e


# ================================================================ strings in memory (VarSetCapacity & co.)

class V1StrBuf(AhkObject):
    """A v1 variable used as a raw buffer: bytes in native memory, read back as a UTF-16 string."""
    __slots__ = ("buf",)

    def __init__(self, size, fill=UNSET):
        from .buffer import BufferObj
        super().__init__(CLASSES["Buffer"].prototype)
        self.buf = BufferObj(size, fill)

    def find(self, name):
        return self.buf.find(name)

    @property
    def addr(self):
        return self.buf.addr

    @property
    def data(self):
        return self.buf.data

    def text(self):
        raw = bytes(self.buf.data)
        for i in range(0, len(raw) - 1, 2):
            if raw[i] == 0 and raw[i + 1] == 0:
                raw = raw[:i]
                break
        return raw.decode("utf-16-le", "replace")


def _strbuf_of(ref, create=True):
    v = ref.cell.value if type(ref) is VarRef else ref
    if isinstance(v, V1StrBuf):
        return v
    if not create:
        return None
    s = S(v) if not isinstance(v, AhkObject) else ""
    enc = s.encode("utf-16-le") + b"\0\0"
    b = V1StrBuf(len(enc))
    b.buf.data[:len(enc)] = enc
    if type(ref) is VarRef:
        ref.cell.value = b
    return b


@export("__v1_VarSetCapacity")
def _varsetcap(ref, size=UNSET, fill=UNSET):
    if size is UNSET:
        b = _strbuf_of(ref, False)
        return len(b.buf.data) - 2 if b else len(S(ref.cell.value if type(ref) is VarRef else ref)) * 2
    n = I(size)
    if n == -1:
        return len(S(ref.cell.value)) * 2 if type(ref) is VarRef else 0
    if n == 0:
        if type(ref) is VarRef:
            ref.cell.value = ""
        return 0
    b = V1StrBuf(n + 2, fill if fill is not UNSET else UNSET)
    if type(ref) is VarRef:
        ref.cell.value = b
    return n


@export("__v1_addr")
def _addr(ref):
    v = ref.cell.value if type(ref) is VarRef else ref
    if isinstance(v, V1StrBuf):
        return v.addr
    if isinstance(v, AhkObject):
        return O.RT.to_int(O.RT.get_prop(v, "Ptr")) if v.find("Ptr")[0] else id(v)
    if v is UNSET or v == "":
        return 0
    return _strbuf_of(ref).addr


@export("__v1_deref")
def _deref(addr):
    return B("NumGet", I(addr), "UChar")


def _target(src):
    """NumGet/NumPut target: a variable holding a buffer, or an address."""
    v = src.cell.value if type(src) is VarRef else src
    if isinstance(v, V1StrBuf):
        return v.buf
    if isinstance(v, AhkObject):
        return v
    n = str_to_number(v) if type(v) is str else v
    if type(n) in (int, float) and type(v) is not str or (type(v) is str and n is not None and int(n) > 0x10000):
        return int(n)
    return _strbuf_of(src).buf


@export("__v1_NumGet")
def _numget(src, offset=0, type_="UPtr"):
    if type(offset) is str and str_to_number(offset) is None:
        offset, type_ = 0, offset
    return B("NumGet", _target(src), N(offset), type_)


@export("__v1_NumPut")
def _numput(num, dest, offset=0, type_="UPtr"):
    if type(offset) is str and str_to_number(offset) is None:
        offset, type_ = 0, offset
    B("NumPut", type_, num, _target(dest), N(offset))
    t = _target(dest)
    base = t.addr if hasattr(t, "addr") else (t if type(t) is int else 0)
    from .buffer import TYPES
    return base + N(offset) + TYPES.get(S(type_).lower(), ("", 8))[1]


@export("__v1_StrGet")
def _strget(src, length=UNSET, enc=UNSET):
    v = src.cell.value if type(src) is VarRef else src
    if type(length) is str and str_to_number(length) is None:
        length, enc = UNSET, length
    return B("StrGet", _target(src) if not (type(v) in (int,) or (type(v) is str and str_to_number(v) is not None)) else I(v),
             length, enc if enc is not UNSET else "UTF-16")


@export("__v1_StrPut")
def _strput(s, target=UNSET, length=UNSET, enc=UNSET):
    if type(target) is str and str_to_number(target) is None and target != "":
        return B("StrPut", s, target)
    if type(length) is str and str_to_number(length) is None:
        length, enc = UNSET, length
    if target is UNSET:
        return B("StrPut", s, enc if enc is not UNSET else "UTF-16")
    t = _target(target)
    args = [s, t] + ([length] if length is not UNSET else []) + ([enc] if enc is not UNSET else [])
    return B("StrPut", *args)


@export("__v1_DllCall")
def _dllcall(fn, *args):
    args = list(args)
    refs = {}
    for i in range(1, len(args), 2):
        v = args[i]
        typ = S(args[i - 1]).lower().replace(" ", "")
        if type(v) is VarRef:
            refs[i] = (v, typ)
            cur = v.cell.value
            if typ.endswith("*") or typ.endswith("p"):
                args[i] = v
                if cur is UNSET or cur == "":
                    v.cell.value = 0
            elif typ in ("str", "wstr", "astr"):
                if isinstance(cur, V1StrBuf):
                    args[i] = cur.buf
                    args[i - 1] = "Ptr"
                else:
                    args[i] = S(cur)
            elif isinstance(cur, V1StrBuf):
                args[i] = cur.buf
            else:
                args[i] = cur if cur is not UNSET else ""
        elif isinstance(v, V1StrBuf):
            args[i] = v.buf
    if isinstance(fn, str) and "\\" in fn:
        fn = fn.split("\\")[-1] if fn.lower().split("\\")[0] in ("user32", "kernel32", "gdi32", "shell32") else fn
    try:
        r = B("DllCall", fn, *args)
        EL(0)
        return r
    except AhkThrow:
        EL(-4)
        return ""


# ================================================================ v1 versions of built-in functions

@export("__v1_InStr")
def _instr(h, n, cs=0, start=1, occ=1):
    h, n = S(h), S(n)
    start = I(start, 1)
    occ = I(occ, 1)
    case = to_bool(cs) if cs != "" else False
    hh, nn = (h, n) if case else (h.lower(), n.lower())
    if n == "":
        return 0
    if start < 1:
        # search right to left; 0 = from the end
        end = len(hh) + start
        pos = end + 1
        for _ in range(occ):
            pos = hh.rfind(nn, 0, max(pos - 1 + len(nn) - 1, 0))
            if pos < 0:
                return 0
        return pos + 1
    pos = start - 2
    for _ in range(occ):
        pos = hh.find(nn, pos + 1)
        if pos < 0:
            return 0
    return pos + 1


@export("__v1_SubStr")
def _substr(s, start, length=UNSET):
    s = S(s)
    st = I(start, 1)
    if st < 1:
        st = max(len(s) + st - 1, 0)
    else:
        st -= 1
    if length is UNSET or length == "":
        return s[st:]
    ln = I(length)
    if ln < 0:
        return s[st:len(s) + ln] if len(s) + ln > st else ""
    return s[st:st + ln]


@export("__v1_StrReplace")
def _strreplace(h, n, r="", count=UNSET, limit=-1):
    cs = "On" if O.RT.thread.settings.string_case_sense == "On" else "Off"
    return B("StrReplace", S(h), S(n), S(r), cs, count if type(count) is VarRef else UNSET, I(limit, -1))


@export("__v1_StrSplit")
def _strsplit(s, delims="", omit="", maxparts=-1):
    a = B("StrSplit", S(s), delims if isinstance(delims, AhkObject) else S(delims), S(omit), I(maxparts, -1))
    return v1arr(a.items)


@export("__v1_Trim")
def _trim(s, omit=" \t"):
    return S(s).strip(S(omit))


@export("__v1_LTrim")
def _ltrim(s, omit=" \t"):
    return S(s).lstrip(S(omit))


@export("__v1_RTrim")
def _rtrim(s, omit=" \t"):
    return S(s).rstrip(S(omit))


@export("__v1_StrLen")
def _strlen(s):
    return len(S(s))


def _num_or_blank(fn):
    def call(*args):
        vals = []
        for a in args:
            n = N(a, None)
            if n is None:
                return ""
            vals.append(n)
        try:
            return fn(*vals)
        except (ValueError, ZeroDivisionError, OverflowError):
            return ""
    return call


export("__v1_Abs")(_num_or_blank(abs))
export("__v1_Sqrt")(_num_or_blank(lambda x: math.sqrt(x) if x >= 0 else ""))
export("__v1_Ln")(_num_or_blank(lambda x: math.log(x) if x > 0 else ""))
export("__v1_Log")(_num_or_blank(lambda x: math.log10(x) if x > 0 else ""))
export("__v1_Exp")(_num_or_blank(math.exp))
export("__v1_Sin")(_num_or_blank(math.sin))
export("__v1_Cos")(_num_or_blank(math.cos))
export("__v1_Tan")(_num_or_blank(math.tan))
export("__v1_ASin")(_num_or_blank(lambda x: math.asin(x) if -1 <= x <= 1 else ""))
export("__v1_ACos")(_num_or_blank(lambda x: math.acos(x) if -1 <= x <= 1 else ""))
export("__v1_ATan")(_num_or_blank(math.atan))
export("__v1_Floor")(_num_or_blank(lambda x: int(math.floor(x))))
export("__v1_Ceil")(_num_or_blank(lambda x: int(math.ceil(x))))
export("__v1_Mod")(_num_or_blank(lambda a, b: "" if b == 0 else (math.fmod(a, b) if float in (type(a), type(b)) else
                                                               (abs(a) % abs(b)) * (1 if a >= 0 else -1))))


@export("__v1_Round")
def _round(x, n=0):
    v = N(x, None)
    if v is None:
        return ""
    d = I(n)
    m = 10 ** d
    # BIF_Round: halves round away from zero
    r = math.floor(v * m + 0.5) / m if v >= 0 else math.ceil(v * m - 0.5) / m
    if d > 0:
        return ("%." + str(d) + "f") % r
    return int(r)


@export("__v1_Max")
def _max(*vals):
    ns = [N(v, None) for v in vals]
    return "" if not ns or None in ns else max(ns)


@export("__v1_Min")
def _min(*vals):
    ns = [N(v, None) for v in vals]
    return "" if not ns or None in ns else min(ns)


@export("__v1_Chr")
def _chr(n):
    n = I(n)
    return chr(n) if 0 < n < 0x110000 else ""


@export("__v1_Format")
def _format(fmt, *args):
    return B("Format", fmt, *[a if not isinstance(a, AhkObject) else "" for a in args])


@export("__v1_FileExist")
def _fileexist(p):
    return quiet(B, "FileExist", S(p)) if S(p) else ""


@export("__v1_WinExist")
def _winexist(*args):
    return quiet(B, "WinExist", *U(*args)) or 0


@export("__v1_WinActive")
def _winactive(*args):
    return quiet(B, "WinActive", *U(*args)) or 0


@export("__v1_GetKeyStateFn")
def _getkeystate(key, mode=""):
    try:
        return B("GetKeyState", S(key), *U(mode))
    except AhkThrow:
        return ""


@export("__v1_FileOpen")
def _fileopen(name, flags, enc=UNSET):
    try:
        return B("FileOpen", name, flags, enc)
    except AhkThrow:
        return 0


@export("__v1_LoadPicture")
def _loadpicture(f, opts="", ref=UNSET):
    try:
        return B("LoadPicture", f, opts, ref)
    except AhkThrow:
        return 0


@export("__v1_RegExMatch")
def _regexmatch(h, needle, ref=UNSET, start=1):
    needle = S(needle)
    m = re.match(r'^([^()\\]*)\)', needle)
    opts = m[1] if m and re.fullmatch(r'[imsxADJUXPOSC`a-z\d]*', m[1]) else ""
    mode = "O" if "O" in opts else "P" if "P" in opts else ""
    if mode:
        needle = needle.replace(mode, "", 1) if needle.index(mode) < len(opts) + 1 else needle
    cell = Cell("m")
    try:
        pos = B("RegExMatch", S(h), needle, VarRef(cell), I(start, 1))
        EL(0)
    except AhkThrow as e:
        EL("Compile error")
        return ""
    if type(ref) is not VarRef:
        return pos
    mo = cell.value
    r = O.RT
    base = var_name(ref)
    if mode == "O":
        ref.cell.value = mo if pos else ""
        return pos
    if not pos or not isinstance(mo, AhkObject):
        ref.cell.value = ""
        if mode != "O":
            _clear_groups(base, needle)
        return 0
    count = r.to_int(r.get_prop(mo, "Count"))
    if mode == "P":
        ref.cell.value = r.call_method(mo, "Len", [0])
        if base:
            setvar(base + "Pos", r.call_method(mo, "Pos", [0]))
            setvar(base + "Len", r.call_method(mo, "Len", [0]))
        for i in range(1, count + 1):
            setvar(f"{base}Pos{i}", r.call_method(mo, "Pos", [i]))
            setvar(f"{base}Len{i}", r.call_method(mo, "Len", [i]))
            nm = S(r.call_method(mo, "Name", [i]))
            if nm:
                setvar(f"{base}Pos{nm}", r.call_method(mo, "Pos", [i]))
                setvar(f"{base}Len{nm}", r.call_method(mo, "Len", [i]))
        return pos
    ref.cell.value = r.get_item(mo, [0])
    for i in range(1, count + 1):
        val = r.get_item(mo, [i])
        setvar(f"{base}{i}", val)
        nm = S(r.call_method(mo, "Name", [i]))
        if nm:
            setvar(base + nm, val)
    return pos


def _clear_groups(base, needle):
    if not base:
        return
    n = len(re.findall(r'(?<!\\)\((?!\?)|\(\?P?<\w+>', needle))
    for i in range(1, n + 1):
        setvar(f"{base}{i}", "")


@export("__v1_RegExReplace")
def _regexreplace(h, needle, repl="", count=UNSET, limit=-1, start=1):
    try:
        r = B("RegExReplace", S(h), S(needle), S(repl), count if type(count) is VarRef else UNSET, I(limit, -1), I(start, 1))
        EL(0)
        return r
    except AhkThrow:
        EL("Compile error")
        return ""


@export("__v1_OnMessage")
def _onmessage(msg, fn=UNSET, maxthreads=1):
    if fn is UNSET:
        return ""
    f = callable_of(fn, labels_first=False) if fn != "" else None
    if f is None:
        return ""
    return B("OnMessage", msg, f, maxthreads)


@export("__v1_RegisterCallback")
def _registercallback(fn, opts="", count=UNSET, event=UNSET):
    f = callable_of(fn, labels_first=False)
    return B("CallbackCreate", f, S(opts), count)


@export("__v1_OnExitFunc")
def _onexitfunc(fn, add=1):
    f = callable_of(fn, labels_first=False)
    return B("OnExit", f, add)


@export("__v1_OnClipboardChange")
def _onclip(fn, add=1):
    f = callable_of(fn, labels_first=False)
    return B("OnClipboardChange", f, add)


@export("__v1_Hotstring")
def _hotstring(s, repl=UNSET, onoff=UNSET):
    if repl is not UNSET and not isinstance(repl, AhkObject):
        f = callable_of(repl)
        if f is not None and S(s).startswith(":") and "x" in S(s).split(":")[1].lower():
            repl = f
        elif f is not None and find_label(repl):
            repl = f
    return B("Hotstring", s, repl, onoff)


@export("__v1_ComObjCreate")
def _comobjcreate(clsid, iid=UNSET):
    return O.RT.call(O.RT.globals["comobject"].value, [clsid, iid])


@export("__v1_ComObject")
def _comobject(*args):
    if len(args) >= 2:
        return O.RT.call(O.RT.globals["comvalue"].value, list(args[:3]))
    return O.RT.call(O.RT.globals["comobject"].value, list(args))


@export("__v1_ComObjActive")
def _comobjactive(*args):
    if len(args) >= 2 or (args and type(args[0]) is int):
        return _comobject(*args)
    return B("ComObjActive", *args)


@export("__v1_ComObjError")
def _comobjerror(enable=UNSET):
    return 1


@export("__v1_ComObjMissing")
def _comobjmissing():
    return O.RT.call(O.RT.globals["comvalue"].value, [0xA, 0x80020004])


@export("__v1_MenuGetHandle")
def _menugethandle(name):
    return O.RT.v1_gui.menu_handle(S(name))


@export("__v1_MenuGetName")
def _menugetname(h):
    return O.RT.v1_gui.menu_name(h)


# ================================================================ legacy If

def _v1num(v):
    if type(v) in (int, float):
        return v
    if type(v) is str:
        return str_to_number(v.strip())
    return None


@export("__v1_cmp")
def _cmp(a, op, b):
    na, nb = _v1num(a), _v1num(b)
    if na is not None and nb is not None and not (type(a) is str and a.strip() == "") and not (type(b) is str and b.strip() == ""):
        x, y = na, nb
    else:
        x, y = S(a), S(b)
        if O.RT.thread.settings.string_case_sense != "On":
            x, y = x.lower(), y.lower()
    if op == "=":
        return int(x == y)
    if op in ("<>", "!="):
        return int(x != y)
    if op == ">":
        return int(x > y)
    if op == "<":
        return int(x < y)
    if op == ">=":
        return int(x >= y)
    return int(x <= y)


@export("__v1_between")
def _between(v, lo, hi):
    return int(_cmp(v, ">=", lo) and _cmp(v, "<=", hi))


def _list(s):
    items = []
    buf = ""
    s = S(s)
    i = 0
    while i < len(s):
        if s[i] == "," and s[i + 1:i + 2] == ",":
            buf += ","
            i += 2
            continue
        if s[i] == ",":
            items.append(buf)
            buf = ""
        else:
            buf += s[i]
        i += 1
    items.append(buf)
    return items


@export("__v1_in")
def _in(v, lst):
    v = S(v)
    cs = O.RT.thread.settings.string_case_sense == "On"
    return int(any((x == v) if cs else (x.lower() == v.lower()) for x in _list(lst)))


@export("__v1_contains")
def _contains(v, lst, single=0):
    v = S(v)
    cs = O.RT.thread.settings.string_case_sense == "On"
    items = [S(lst)] if single else _list(lst)
    return int(any((x in v) if cs else (x.lower() in v.lower()) for x in items if x != "" or single))


@export("__v1_is")
def _is(v, typ):
    t = S(typ).strip().lower()
    s = v if type(v) is str else S(v)
    if t == "integer":
        return int(type(v) is int or re.fullmatch(r'\s*[-+]?(0x[\da-f]+|\d+)\s*', s, re.I) is not None)
    if t == "float":
        return int(type(v) is float or re.fullmatch(r'\s*[-+]?(\d*\.\d+|\d+\.\d*)(e[-+]?\d+)?\s*', s, re.I) is not None)
    if t == "number":
        return int(_is(v, "integer") or _is(v, "float"))
    if t == "digit":
        return int(s.isdigit() or s == "")
    if t == "xdigit":
        return int(re.fullmatch(r'(0x)?[\da-f]*', s, re.I) is not None)
    if t == "alpha":
        return int(s.isalpha() or s == "")
    if t == "upper":
        return int(s == "" or (s.isalpha() and s.isupper()))
    if t == "lower":
        return int(s == "" or (s.isalpha() and s.islower()))
    if t == "alnum":
        return int(s.isalnum() or s == "")
    if t == "space":
        return int(s == "" or s.isspace())
    if t == "time":
        return quiet(B, "IsTime", s) or 0
    return 0


@export("__v1_msgresult")
def _msgresult():
    return O.RT.v1_state.msg_result


# ================================================================ commands: variables and strings

@export("__v1_setenv")
def _setenv(ref, value=""):
    return out(ref, value)


@export("__v1_envadd")
def _envadd(ref, value, units=UNSET):
    cur = ref.cell.value if type(ref) is VarRef else ""
    if units is not UNSET and S(units).strip():
        return out(ref, _datemath(cur, N(value), S(units)))
    n = _v1num(cur) if cur is not UNSET else None
    out(ref, (n or 0) + N(value) if True else "")
    return ""


__v1_EnvAdd = export("__v1_EnvAdd")(_envadd)


@export("__v1_envsub")
def _envsub(ref, value, units=UNSET):
    cur = ref.cell.value if type(ref) is VarRef else ""
    if units is not UNSET and S(units).strip():
        try:
            return out(ref, B("DateDiff", S(cur) or B("FormatTime", UNSET, "yyyyMMddHHmmss"),
                              S(value) or B("FormatTime", UNSET, "yyyyMMddHHmmss"), S(units)))
        except AhkThrow:
            return out(ref, "")
    n = _v1num(cur) if cur is not UNSET else None
    out(ref, (n or 0) - N(value))
    return ""


export("__v1_EnvSub")(_envsub)


def _datemath(cur, n, units):
    try:
        base = S(cur) if S(cur) else time.strftime("%Y%m%d%H%M%S")
        return B("DateAdd", base, n, units)
    except AhkThrow:
        return ""


@export("__v1_envmult")
def _envmult(ref, value):
    out(ref, (_v1num(ref.cell.value) or 0) * N(value))


@export("__v1_envdiv")
def _envdiv(ref, value):
    d = N(value)
    cur = _v1num(ref.cell.value) or 0
    out(ref, "" if d == 0 else (cur // d if type(cur) is int and type(d) is int else cur / d))


@export("__v1_envget")
def _envget(ref, name):
    out(ref, os.environ.get(S(name), ""))


@export("__v1_envset")
def _envset(name, value=""):
    os.environ[S(name)] = S(value)
    EL(0)


@export("__v1_envupdate")
def _envupdate():
    EL(0)


@export("__v1_autotrim")
def _autotrim(v):
    O.RT.v1_autotrim = onoff(v, 1) == 1


@export("__v1_stringcasesense")
def _scs(v):
    s = S(v).strip().lower()
    O.RT.thread.settings.string_case_sense = "On" if s in ("on", "1") else "Locale" if s == "locale" else "Off"


@export("__v1_setformat")
def _setformat(kind, fmt=""):
    k = S(kind).lower()
    r = O.RT
    if k.startswith("float"):
        r.v1_float_fmt = S(fmt) or "0.6"
    elif k.startswith("integer"):
        f = S(fmt) or "D"
        r.v1_int_fmt = f
        r.v1_hex = f.lower().startswith("h")


def _sv(ref):
    v = ref.cell.value if type(ref) is VarRef else ref
    return "" if v is UNSET else S(v)


@export("__v1_stringlen")
def _stringlen(ref, s):
    out(ref, len(S(s)))


@export("__v1_stringleft")
def _stringleft(ref, s, n):
    k = I(n)
    out(ref, S(s)[:max(k, 0)])


@export("__v1_stringright")
def _stringright(ref, s, n):
    k = I(n)
    out(ref, S(s)[-k:] if k > 0 else "")


@export("__v1_stringtrimleft")
def _stringtrimleft(ref, s, n):
    out(ref, S(s)[max(I(n), 0):])


@export("__v1_stringtrimright")
def _stringtrimright(ref, s, n):
    k = max(I(n), 0)
    out(ref, S(s)[:-k] if k else S(s))


@export("__v1_stringmid")
def _stringmid(ref, s, start, count=UNSET, l=""):
    s = S(s)
    st = I(start, 1)
    cnt = I(count, len(s)) if count is not UNSET and count != "" else len(s)
    if S(l).upper().startswith("L"):
        end = st
        begin = max(end - cnt, 0)
        if st < 1:
            return out(ref, "")
        return out(ref, s[begin:end])
    if st < 1:
        cnt += st - 1
        st = 1
    out(ref, s[st - 1:st - 1 + max(cnt, 0)] if cnt > 0 else "")


@export("__v1_stringlower")
def _stringlower(ref, s, t=""):
    out(ref, S(s).title() if S(t).upper() == "T" else S(s).lower())


@export("__v1_stringupper")
def _stringupper(ref, s, t=""):
    out(ref, S(s).title() if S(t).upper() == "T" else S(s).upper())


@export("__v1_stringreplace")
def _stringreplace(ref, s, search, repl="", all_=""):
    s, search, repl = S(s), S(search), S(repl)
    mode = S(all_).strip().lower()
    cs = O.RT.thread.settings.string_case_sense == "On"
    if search == "":
        EL(1)
        return out(ref, s)
    flags = 0 if cs else re.I
    pat = re.compile(re.escape(search), flags)
    limit = 0 if mode in ("1", "a", "all") or mode.startswith("useerrorlevel") else 1
    result, n = pat.subn(lambda m: repl, s, count=limit)
    out(ref, result)
    if mode.startswith("useerrorlevel"):
        EL(n)
    else:
        EL(0 if n else 1)


@export("__v1_stringgetpos")
def _stringgetpos(ref, s, search, side="", offset=0):
    s, search = S(s), S(search)
    cs = O.RT.thread.settings.string_case_sense == "On"
    hs, ns = (s, search) if cs else (s.lower(), search.lower())
    side = S(side).strip().upper()
    off = I(offset)
    occ = 1
    right = False
    if side:
        right = side[0] == "R" or side == "1"
        num = side[1:] if side[0] in "LR" else ""
        if num.isdigit():
            occ = int(num)
    pos = -1
    if right:
        end = len(hs) - off
        for _ in range(occ):
            pos = hs.rfind(ns, 0, end)
            if pos < 0:
                break
            end = pos + len(ns) - 1
    else:
        start = off
        for _ in range(occ):
            pos = hs.find(ns, start)
            if pos < 0:
                break
            start = pos + 1
    out(ref, pos)
    EL(0 if pos >= 0 else 1)


@export("__v1_stringsplit")
def _stringsplit(ref, s, delims="", omit=""):
    base = var_name(ref)
    s, delims, omit = S(s), S(delims), S(omit)
    if delims:
        parts = re.split("[" + re.escape(delims) + "]", s)
    else:
        parts = list(s)
    parts = [p.strip(omit) if omit else p for p in parts]
    setvar(base + "0", len(parts))
    for i, p in enumerate(parts, 1):
        setvar(f"{base}{i}", p)


@export("__v1_sort")
def _sort(ref, opts=""):
    o = S(opts)
    fm = re.search(r'\bF\s+(\S+)', o, re.I)
    cb = UNSET
    if fm:
        cb = lookup_func(fm[1]) or UNSET
        o = o[:fm.start()] + o[fm.end():]
        if cb is not UNSET and not getattr(cb, "is_variadic", lambda: False)() and cb.max_params() < 3:
            fn = cb
            cb = O.BuiltinFunc("SortCallback", lambda a, b, off=0: fn.call([a, b]), 2, 3)   # v1 omits Offset
    out(ref, B("Sort", _sv(ref), o, cb))


@export("__v1_transform")
def _transform(ref, cmd, v1="", v2=""):
    c = S(cmd).lower()
    a, b = N(v1, None), N(v2, None)
    try:
        if c == "unicode":
            r = B("A_Clipboard") if False else (O.RT.bivars["a_clipboard"][0]() if v1 == "" else S(v1))
        elif c == "asc":
            r = ord(S(v1)[0]) if S(v1) else 0
        elif c == "chr":
            r = chr(I(v1))
        elif c == "deref":
            r = re.sub(r'%(\w+)%', lambda m: S(_cell(m[1]).value) if _cell(m[1]).value is not UNSET else "", S(v1))
        elif c in ("html",):
            import html
            r = html.escape(S(v1), quote=False).replace("\n", "<br>\n")
        elif c == "mod":
            r = _arith("//", a, b) if False else math.fmod(a, b) if float in (type(a), type(b)) else a % b
        elif c == "pow":
            r = a ** b
        elif c == "exp":
            r = math.exp(a)
        elif c == "sqrt":
            r = math.sqrt(a)
        elif c == "log":
            r = math.log10(a)
        elif c == "ln":
            r = math.log(a)
        elif c == "round":
            r = _round(a, v2 if v2 != "" else 0)
        elif c == "ceil":
            r = int(math.ceil(a))
        elif c == "floor":
            r = int(math.floor(a))
        elif c == "abs":
            r = abs(a)
        elif c in ("sin", "cos", "tan", "asin", "acos", "atan"):
            r = getattr(math, c)(a)
        elif c == "bitnot":
            r = ~int(a) & 0xFFFFFFFF if 0 <= a <= 0xFFFFFFFF else ~int(a)
        elif c == "bitand":
            r = int(a) & int(b)
        elif c == "bitor":
            r = int(a) | int(b)
        elif c == "bitxor":
            r = int(a) ^ int(b)
        elif c == "bitshiftleft":
            r = int(a) << int(b)
        elif c == "bitshiftright":
            r = int(a) >> int(b)
        else:
            r = ""
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        r = ""
    out(ref, r)


@export("__v1_formattime")
def _formattime(ref, ts="", fmt=""):
    try:
        out(ref, B("FormatTime", *U(ts), S(fmt)))
    except AhkThrow:
        out(ref, "")


@export("__v1_random")
def _random(ref=UNSET, lo=UNSET, hi=UNSET):
    if type(ref) is not VarRef or ref == "":
        if hi is not UNSET or lo is not UNSET:
            B("RandomSeed", I(lo)) if "randomseed" in O.RT.builtins else None
        return
    a = N(lo, 0) if lo != "" else 0
    b = N(hi, 2147483647) if hi != "" else 2147483647
    if a > b:
        a, b = b, a
    out(ref, B("Random", a, b))


# ================================================================ commands: control flow & settings

@export("__v1_exitapp")
def _exitapp(code=0):
    return B("ExitApp", I(code))


@export("__v1_reload")
def _reload():
    return B("Reload")


@export("__v1_sleep")
def _sleep(ms=0):
    return B("Sleep", I(ms))


@export("__v1_pause")
def _pause(state="", underlying=0):
    v = onoff(state, -1) if S(state) else -1
    return B("Pause", v)


@export("__v1_suspend")
def _suspend(state=""):
    s = S(state).lower()
    v = {"on": 1, "off": 0, "toggle": -1, "permit": None, "": -1}.get(s, -1)
    if v is None:
        return
    return B("Suspend", v)


@export("__v1_critical")
def _critical(v="On"):
    s = S(v).strip()
    if s.lower() == "off":
        return B("Critical", "Off")
    if s.lower() in ("on", ""):
        return B("Critical", "On")
    return B("Critical", I(s))


@export("__v1_thread")
def _thread(sub, a="", b=""):
    return quiet(B, "Thread", sub, *U(a, b))


@export("__v1_setbatchlines")
def _setbatchlines(v):
    O.RT.v1_state.batchlines = S(v)


@export("__v1_sendmode")
def _sendmode(m):
    return quiet(B, "SendMode", S(m) or "Event")


@export("__v1_sendlevel")
def _sendlevel(n):
    return B("SendLevel", I(n))


@export("__v1_setkeydelay")
def _setkeydelay(d="", p="", play=""):
    return B("SetKeyDelay", *U(d, p, play))


@export("__v1_setmousedelay")
def _setmousedelay(d="", play=""):
    return B("SetMouseDelay", *U(d, play))


@export("__v1_setwindelay")
def _setwindelay(d):
    return B("SetWinDelay", I(d))


@export("__v1_setcontroldelay")
def _setcontroldelay(d):
    return B("SetControlDelay", I(d))


@export("__v1_setdefaultmousespeed")
def _setdms(s):
    return B("SetDefaultMouseSpeed", I(s))


@export("__v1_coordmode")
def _coordmode(target, mode="Screen"):
    m = S(mode) or "Screen"
    return quiet(B, "CoordMode", S(target), m)


@export("__v1_settitlematchmode")
def _settmm(m):
    s = S(m)
    return quiet(B, "SetTitleMatchMode", I(s) if s.isdigit() else s)


@export("__v1_detecthiddenwindows")
def _dhw(v):
    return B("DetectHiddenWindows", onoff(v, 0))


@export("__v1_detecthiddentext")
def _dht(v):
    return B("DetectHiddenText", onoff(v, 1))


@export("__v1_setworkingdir")
def _setworkingdir(d):
    try:
        B("SetWorkingDir", S(d))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_setregview")
def _setregview(v):
    return quiet(B, "SetRegView", S(v))


@export("__v1_setstorecapslockmode")
def _sscm(v):
    return B("SetStoreCapsLockMode", onoff(v, 1))


def _lockstate(name):
    def f(state=""):
        s = S(state).strip()
        return B(name, s if s else UNSET)
    return f


export("__v1_setcapslockstate")(_lockstate("SetCapsLockState"))
export("__v1_setnumlockstate")(_lockstate("SetNumLockState"))
export("__v1_setscrolllockstate")(_lockstate("SetScrollLockState"))


@export("__v1_listlines")
def _listlines(v=""):
    return B("ListLines", *([onoff(v, 1)] if S(v) else []))


@export("__v1_listvars")
def _listvars():
    return B("ListVars")


@export("__v1_listhotkeys")
def _listhotkeys():
    return B("ListHotkeys")


@export("__v1_keyhistory")
def _keyhistory():
    return B("KeyHistory")


@export("__v1_edit")
def _edit():
    return B("Edit")


@export("__v1_outputdebug")
def _outputdebug(t):
    return B("OutputDebug", S(t))


@export("__v1_settimer")
def _settimer(label="", period="", priority=0):
    r = O.RT
    st = r.v1_state
    if not hasattr(st, "timers"):
        st.timers = {}
    name = S(label) if not isinstance(label, AhkObject) else label
    if name == "":
        name = st.this_label
    key = name.lower() if isinstance(name, str) else id(name)
    fn = st.timers.get(key)
    if fn is None:
        fn = callable_of(name)
        if fn is None:
            throw("Error", "Target label does not exist.", S(name))
        st.timers[key] = fn
    p = S(period).strip().lower() if not isinstance(period, (int, float)) else period
    if p == "off":
        return B("SetTimer", fn, 0)
    if p == "delete":
        st.timers.pop(key, None)
        return B("SetTimer", fn, 0)
    if p == "on" or p == "":
        return B("SetTimer", fn, UNSET, I(priority))
    return B("SetTimer", fn, N(p, 250), I(priority))


@export("__v1_onexit")
def _onexit(label="", add=""):
    r = O.RT
    st = r.v1_state
    old = st.exit_label
    if old is not None:
        quiet(B, "OnExit", old, 0)
        st.exit_label = None
    if S(label):
        lbl = S(label)

        def handler(reason=UNSET, code=UNSET):
            st.exit_reason = S(reason)
            r.v1_state.exiting = True
            gosub(lbl)
            return 1    # a v1 OnExit label must call ExitApp itself
        from ..classes import bif
        f = bif("OnExit", handler)
        st.exit_label = f
        B("OnExit", f)


@export("__v1_hotkey")
def _hotkey(key, label="", options=""):
    k = S(key)
    kl = k.lower()
    if kl.startswith("ifwin"):
        fn = {"ifwinactive": "HotIfWinActive", "ifwinexist": "HotIfWinExist",
              "ifwinnotactive": "HotIfWinNotActive", "ifwinnotexist": "HotIfWinNotExist"}.get(kl, "HotIfWinActive")
        return B(fn, *U(label, options)) if S(label) or S(options) else B("HotIf")
    if kl == "if":
        return B("HotIf", *U(label))
    lab = label if isinstance(label, AhkObject) else S(label)
    action = UNSET
    if isinstance(lab, AhkObject):
        action = lab
    elif lab:
        low = lab.lower()
        if low in ("on", "off", "toggle", "altTab".lower(), "shiftalttab", "alttabmenu", "alttabandmenu",
                   "alttabmenudismiss"):
            action = lab
        else:
            action = callable_of(lab)
            if action is None:
                EL(1)
                throw("Error", "Target label does not exist.", lab)
    try:
        B("Hotkey", k, action, S(options))
        EL(0)
    except AhkThrow:
        EL(1)
        raise


# ================================================================ commands: keyboard and mouse

def _send(name):
    def f(keys=""):
        return B(name, S(keys))
    return f


for _n, _t in (("send", "Send"), ("sendinput", "SendInput"), ("sendevent", "SendEvent"), ("sendplay", "SendPlay"),
               ("sendraw", "SendText")):
    export("__v1_" + _n)(_send(_t))


@export("__v1_click")
def _click(opts=""):
    return B("Click", S(opts)) if S(opts) else B("Click")


@export("__v1_mouseclick")
def _mouseclick(btn="Left", x="", y="", count="", speed="", du="", rel=""):
    return B("MouseClick", *U(S(btn) or "Left", x, y, count, speed, du, rel))


@export("__v1_mouseclickdrag")
def _mouseclickdrag(btn, x1, y1, x2, y2, speed="", rel=""):
    return B("MouseClickDrag", S(btn) or "Left", *U(x1, y1), x2, y2, *U(speed, rel))


@export("__v1_mousemove")
def _mousemove(x, y, speed="", rel=""):
    return B("MouseMove", x, y, *U(speed, rel))


@export("__v1_mousegetpos")
def _mousegetpos(ox=UNSET, oy=UNSET, ow=UNSET, oc=UNSET, flag=0):
    return B("MouseGetPos", ox, oy, ow, oc, I(flag))


@export("__v1_keywait")
def _keywait(key, opts=""):
    r = B("KeyWait", S(key), S(opts))
    EL(0 if r else 1)


@export("__v1_getkeystate")
def _getkeystate_cmd(ref, key, mode=""):
    try:
        v = B("GetKeyState", S(key), *U(mode))
        out(ref, ("D" if v else "U") if type(v) is int else v)    # joystick axes etc. give a number
    except AhkThrow:
        out(ref, "")


@export("__v1_blockinput")
def _blockinput(v):
    return quiet(B, "BlockInput", S(v))


@export("__v1_input")
def _input(ref=UNSET, opts="", endkeys="", matchlist=""):
    r = O.RT
    st = r.v1_state
    prev = getattr(st, "input_hook", None)
    if prev is not None:
        quiet(r.call_method, prev, "Stop", [])
    if type(ref) is not VarRef:
        EL(1 if prev is not None else 0)
        return
    ih = B("InputHook", S(opts), S(endkeys), S(matchlist))
    st.input_hook = ih
    r.call_method(ih, "Start", [])
    r.call_method(ih, "Wait", [])
    st.input_hook = None
    out(ref, r.get_prop(ih, "Input"))
    reason = S(r.get_prop(ih, "EndReason"))
    if reason == "EndKey":
        EL("EndKey:" + S(r.get_prop(ih, "EndKey")))
    elif reason == "Match":
        EL("Match")
    elif reason == "Timeout":
        EL("Timeout")
    elif reason == "Max":
        EL("Max")
    elif reason == "Stopped":
        EL("NewInput")
    else:
        EL(reason)


# ================================================================ commands: windows

def _win(name, el=False):
    def f(*args):
        try:
            B(name, *U(*args))
            if el:
                EL(0)
        except AhkThrow:
            if el:
                EL(1)
        return ""
    return f


for _n in ("WinActivate", "WinActivateBottom", "WinHide", "WinShow", "WinMaximize", "WinMinimize", "WinRestore"):
    export("__v1_" + _n.lower())(_win(_n))


def _winclose(name):
    def f(title="", text="", secs="", xt="", xx=""):
        try:
            B(name, *U(title, text, secs, xt, xx))
            EL(0)
        except AhkThrow:
            EL(1)
    return f


export("__v1_winclose")(_winclose("WinClose"))
export("__v1_winkill")(_winclose("WinKill"))


def _winwait(name):
    def f(title="", text="", secs="", xt="", xx=""):
        try:
            r = B(name, *U(title, text, secs, xt, xx))
            EL(0 if r else 1)
        except AhkThrow:
            EL(1)
    return f


for _n in ("WinWait", "WinWaitActive", "WinWaitClose", "WinWaitNotActive"):
    export("__v1_" + _n.lower())(_winwait(_n))


@export("__v1_winminimizeall")
def _wma():
    return B("WinMinimizeAll")


@export("__v1_winminimizeallundo")
def _wmau():
    return B("WinMinimizeAllUndo")


@export("__v1_winmove")
def _winmove(title="", text="", x="", y="", w="", h="", xt="", xx=""):
    if x == "" and y == "" and w == "" and h == "" and xt == "" and xx == "" and S(title) and _v1num(title) is not None:
        return quiet(B, "WinMove", title, text)       # WinMove, X, Y (last found window)
    return quiet(B, "WinMove", *U(x, y, w, h, title, text, xt, xx))


@export("__v1_winsettitle")
def _winsettitle(title="", text="", new=UNSET, xt="", xx=""):
    if new is UNSET:
        return quiet(B, "WinSetTitle", title)
    return quiet(B, "WinSetTitle", new, *U(title, text, xt, xx))


@export("__v1_wingettitle")
def _wingettitle(ref, *args):
    out(ref, quiet(B, "WinGetTitle", *U(*args)))


@export("__v1_wingetclass")
def _wingetclass(ref, *args):
    out(ref, quiet(B, "WinGetClass", *U(*args)))


@export("__v1_wingettext")
def _wingettext(ref, *args):
    try:
        out(ref, B("WinGetText", *U(*args)))
        EL(0)
    except AhkThrow:
        out(ref, "")
        EL(1)


@export("__v1_wingetpos")
def _wingetpos(x=UNSET, y=UNSET, w=UNSET, h=UNSET, *args):
    try:
        B("WinGetPos", x, y, w, h, *U(*args))
    except AhkThrow:
        for ref in (x, y, w, h):
            out(ref, "")


@export("__v1_wingetactivetitle")
def _wgat(ref):
    out(ref, quiet(B, "WinGetTitle", "A"))


@export("__v1_wingetactivestats")
def _wgas(t=UNSET, w=UNSET, h=UNSET, x=UNSET, y=UNSET):
    out(t, quiet(B, "WinGetTitle", "A"))
    try:
        B("WinGetPos", x, y, w, h, "A")
    except AhkThrow:
        pass


@export("__v1_winget")
def _winget(ref, cmd="", *args):
    c = S(cmd).strip().lower()
    a = U(*args)
    try:
        if c in ("", "id"):
            v = B("WinGetID", *a)
        elif c == "idlast":
            v = B("WinGetIDLast", *a)
        elif c == "pid":
            v = B("WinGetPID", *a)
        elif c == "processname":
            v = B("WinGetProcessName", *a)
        elif c == "processpath":
            v = B("WinGetProcessPath", *a)
        elif c == "count":
            v = B("WinGetCount", *a)
        elif c == "list":
            lst = B("WinGetList", *a).items
            base = var_name(ref)
            for i, h in enumerate(lst, 1):
                setvar(f"{base}{i}", h)
            v = len(lst)
        elif c == "minmax":
            v = B("WinGetMinMax", *a)
        elif c in ("controllist", "controllisthwnd"):
            lst = B("WinGetControls" if c == "controllist" else "WinGetControlsHwnd", *a).items
            v = "\n".join(S(x) for x in lst)
        elif c == "style":
            v = "0x%08X" % B("WinGetStyle", *a)
        elif c == "exstyle":
            v = "0x%08X" % B("WinGetExStyle", *a)
        elif c == "transparent":
            v = B("WinGetTransparent", *a)
        elif c == "transcolor":
            v = B("WinGetTransColor", *a)
        else:
            v = ""
        out(ref, v)
        EL(0)
    except AhkThrow:
        out(ref, "" if c not in ("count", "list") else 0)
        EL(1)


@export("__v1_winset")
def _winset(attr, value="", *args):
    a = S(attr).strip().lower()
    w = U(*args)
    v = S(value)
    try:
        if a == "alwaysontop":
            B("WinSetAlwaysOnTop", {"on": 1, "off": 0, "toggle": -1, "": -1}.get(v.lower(), -1), *w)
        elif a == "bottom":
            B("WinMoveBottom", *w)
        elif a == "top":
            B("WinMoveTop", *w)
        elif a == "disable":
            B("WinSetEnabled", 0, *w)
        elif a == "enable":
            B("WinSetEnabled", 1, *w)
        elif a == "redraw":
            B("WinRedraw", *w)
        elif a == "style":
            B("WinSetStyle", v, *w)
        elif a == "exstyle":
            B("WinSetExStyle", v, *w)
        elif a == "region":
            B("WinSetRegion", *U(value), *w)
        elif a == "transparent":
            B("WinSetTransparent", v if v.lower() == "off" else I(v), *w)
        elif a == "transcolor":
            B("WinSetTransColor", v, *w)
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_winmenuselectitem")
def _wmsi(*args):
    try:
        B("MenuSelect", *U(*args))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_groupadd")
def _groupadd(name, title="", text="", label="", xt="", xx=""):
    return quiet(B, "GroupAdd", name, *U(title, text, xt, xx))


@export("__v1_groupactivate")
def _groupactivate(name, mode=""):
    try:
        B("GroupActivate", name, S(mode))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_groupdeactivate")
def _groupdeactivate(name, mode=""):
    return quiet(B, "GroupDeactivate", name, S(mode))


@export("__v1_groupclose")
def _groupclose(name, mode=""):
    return quiet(B, "GroupClose", name, S(mode))


@export("__v1_statusbargettext")
def _sbgt(ref, part="", *args):
    try:
        out(ref, B("StatusBarGetText", *U(part), *U(*args)))
        EL(0)
    except AhkThrow:
        out(ref, "")
        EL(1)


@export("__v1_statusbarwait")
def _sbw(*args):
    try:
        r = B("StatusBarWait", *U(*args))
        EL(0 if r else 1)
    except AhkThrow:
        EL(2)


# ================================================================ commands: controls

def _ctl(name):
    def f(*args):
        try:
            B(name, *U(*args))
            EL(0)
        except AhkThrow:
            EL(1)
    return f


@export("__v1_controlclick")
def _controlclick(ctrl="", title="", text="", btn="", count="", opts="", xt="", xx=""):
    try:
        B("ControlClick", *U(ctrl, title, text, btn, count, opts, xt, xx))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_controlfocus")
def _controlfocus(ctrl="", *args):
    try:
        B("ControlFocus", *U(ctrl, *args))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_controlsend")
def _controlsend(ctrl="", keys="", *args):
    try:
        B("ControlSend", S(keys), *U(ctrl, *args))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_controlsendraw")
def _controlsendraw(ctrl="", keys="", *args):
    try:
        B("ControlSendText", S(keys), *U(ctrl, *args))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_controlsettext")
def _controlsettext(ctrl="", text="", *args):
    try:
        B("ControlSetText", S(text), *U(ctrl, *args))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_controlgettext")
def _controlgettext(ref, ctrl="", *args):
    try:
        out(ref, B("ControlGetText", *U(ctrl, *args)))
        EL(0)
    except AhkThrow:
        out(ref, "")
        EL(1)


@export("__v1_controlgetfocus")
def _controlgetfocus(ref, *args):
    try:
        h = B("ControlGetFocus", *U(*args))
        out(ref, B("ControlGetClassNN", h) if h else "")
        EL(0)
    except AhkThrow:
        out(ref, "")
        EL(1)


@export("__v1_controlgetpos")
def _controlgetpos(x=UNSET, y=UNSET, w=UNSET, h=UNSET, ctrl="", *args):
    try:
        B("ControlGetPos", x, y, w, h, *U(ctrl, *args))
    except AhkThrow:
        for ref in (x, y, w, h):
            out(ref, "")


@export("__v1_controlmove")
def _controlmove(ctrl="", x="", y="", w="", h="", *args):
    try:
        B("ControlMove", *U(x, y, w, h, ctrl, *args))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_control")
def _control(cmd, value="", ctrl="", *args):
    c = S(cmd).strip().lower()
    w = U(ctrl, *args)
    v = value
    try:
        if c == "check":
            B("ControlSetChecked", 1, *w)
        elif c == "uncheck":
            B("ControlSetChecked", 0, *w)
        elif c == "enable":
            B("ControlSetEnabled", 1, *w)
        elif c == "disable":
            B("ControlSetEnabled", 0, *w)
        elif c == "show":
            B("ControlShow", *w)
        elif c == "hide":
            B("ControlHide", *w)
        elif c == "style":
            B("ControlSetStyle", S(v), *w)
        elif c == "exstyle":
            B("ControlSetExStyle", S(v), *w)
        elif c == "showdropdown":
            B("ControlShowDropDown", *w)
        elif c == "hidedropdown":
            B("ControlHideDropDown", *w)
        elif c == "tableft":
            B("ControlSend", "{Ctrl down}" + "{Shift down}{Tab}{Shift up}" * max(I(v, 1), 1) + "{Ctrl up}", *w)
        elif c == "tabright":
            B("ControlSend", "{Ctrl down}" + "{Tab}" * max(I(v, 1), 1) + "{Ctrl up}", *w)
        elif c == "add":
            B("ControlAddItem", S(v), *w)
        elif c == "delete":
            B("ControlDeleteItem", I(v), *w)
        elif c == "choose":
            B("ControlChooseIndex", I(v), *w)
        elif c == "choosestring":
            B("ControlChooseString", S(v), *w)
        elif c == "editpaste":
            B("EditPaste", S(v), *w)
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_controlget")
def _controlget(ref, cmd, value="", ctrl="", *args):
    c = S(cmd).strip().lower()
    w = U(ctrl, *args)
    try:
        if c == "checked":
            v = B("ControlGetChecked", *w)
        elif c == "enabled":
            v = B("ControlGetEnabled", *w)
        elif c == "visible":
            v = B("ControlGetVisible", *w)
        elif c == "tab":
            v = B("ControlGetIndex", *w)
        elif c == "findstring":
            v = B("ControlFindItem", S(value), *w)
        elif c == "choice":
            v = B("ControlGetChoice", *w)
        elif c == "list":
            items = B("ControlGetItems", *w)
            v = "\n".join(S(x) for x in items.items)
        elif c == "linecount":
            v = B("EditGetLineCount", *w)
        elif c == "currentline":
            v = B("EditGetCurrentLine", *w)
        elif c == "currentcol":
            v = B("EditGetCurrentCol", *w)
        elif c == "line":
            v = B("EditGetLine", I(value), *w)
        elif c == "selected":
            v = B("EditGetSelectedText", *w)
        elif c == "style":
            v = "0x%08X" % B("ControlGetStyle", *w)
        elif c == "exstyle":
            v = "0x%08X" % B("ControlGetExStyle", *w)
        elif c == "hwnd":
            v = B("ControlGetHwnd", *w)
        else:
            v = ""
        out(ref, v)
        EL(0)
    except AhkThrow:
        out(ref, "")
        EL(1)


@export("__v1_postmessage")
def _postmessage(msg, wp="", lp="", ctrl="", *args):
    try:
        B("PostMessage", msg, *U(wp, lp, ctrl, *args))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_sendmessage")
def _sendmessage(msg, wp="", lp="", ctrl="", title="", text="", xt="", xx="", timeout=""):
    try:
        r = B("SendMessage", msg, *U(wp, lp, ctrl, title, text, xt, xx, timeout))
        EL(r)
    except AhkThrow:
        EL("FAIL")


# ================================================================ commands: files

@export("__v1_fileappend")
def _fileappend(text="", path="", enc=""):
    p = S(path)
    if p == "":
        p = getattr(O.RT.thread.loop, "out_file", None) or ""
        if not p:
            EL(1)
            return
    try:
        if isinstance(text, V1StrBuf):
            text = text.text()
        B("FileAppend", S(text), p, *U(enc))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_fileread")
def _fileread(ref, path):
    p = S(path)
    opts = ""
    while p.startswith("*"):
        m = re.match(r'\*(\S+)\s+', p)
        if not m:
            break
        opts += " " + m[1]
        p = p[m.end():]
    try:
        out(ref, B("FileRead", p, opts.strip().replace("t", "`n") if False else opts.strip()))
        EL(0)
    except AhkThrow:
        out(ref, "")
        EL(1)


@export("__v1_filereadline")
def _filereadline(ref, path, n):
    try:
        with open(O.RT.call(O.RT.builtins["fileexist"], [S(path)]) and _host(S(path)), "r", encoding="utf-8-sig",
                  errors="replace", newline="") as fh:
            for i, line in enumerate(fh, 1):
                if i == I(n):
                    out(ref, line.rstrip("\r\n"))
                    EL(0)
                    return
        EL(1)
    except (OSError, TypeError):
        EL(1)


def _host(p):
    from .files import host_path
    return host_path(p)


def _file_el(name, *, count=False):
    def f(*args):
        try:
            B(name, *U(*args))
            EL(0)
        except AhkThrow as e:
            EL(_extra_count(e) if count else 1)
    return f


def _extra_count(e):
    try:
        return O.RT.to_int(O.RT.get_prop(e.value, "Extra"))
    except Exception:
        return 1


export("__v1_filecopy")(_file_el("FileCopy", count=True))
export("__v1_filemove")(_file_el("FileMove", count=True))
export("__v1_filedelete")(_file_el("FileDelete", count=True))
export("__v1_filerecycle")(_file_el("FileRecycle"))
export("__v1_filerecycleempty")(_file_el("FileRecycleEmpty"))
export("__v1_filecreatedir")(_file_el("DirCreate"))
export("__v1_filecopydir")(_file_el("DirCopy"))
export("__v1_fileinstall")(_file_el("FileInstall"))
export("__v1_filesetattrib")(_file_el("FileSetAttrib", count=True))
export("__v1_filecreateshortcut")(_file_el("FileCreateShortcut"))


@export("__v1_filesettime")
def _filesettime(ts="", pat="", which="M", folders="", recurse=""):
    mode = {"0": "F", "1": "FD", "2": "D"}.get(S(folders) or "0", "F") + ("R" if S(recurse) == "1" else "")
    try:
        B("FileSetTime", *U(ts), S(pat) or UNSET, S(which) or "M", mode)
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_filemovedir")
def _filemovedir(src, dst, flag=""):
    try:
        B("DirMove", src, dst, *U(flag))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_fileremovedir")
def _fileremovedir(d, recurse=""):
    try:
        B("DirDelete", d, I(recurse))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_fileencoding")
def _fileencoding(e=""):
    return B("FileEncoding", S(e) or "CP0")


def _fileget(name, post=None):
    def f(ref, *args):
        try:
            v = B(name, *U(*args))
            out(ref, post(v) if post else v)
            EL(0)
        except AhkThrow:
            out(ref, "")
            EL(1)
    return f


export("__v1_filegetattrib")(_fileget("FileGetAttrib"))
export("__v1_filegettime")(_fileget("FileGetTime"))
export("__v1_filegetversion")(_fileget("FileGetVersion"))
export("__v1_drivespacefree")(_fileget("DriveGetSpaceFree"))


@export("__v1_filegetsize")
def _filegetsize(ref, path="", units=""):
    try:
        out(ref, B("FileGetSize", *U(path), S(units)))
        EL(0)
    except AhkThrow:
        out(ref, "")
        EL(1)


@export("__v1_filegetshortcut")
def _filegetshortcut(link, *refs):
    try:
        B("FileGetShortcut", link, *refs)
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_fileselectfile")
def _fileselectfile(ref, opts="", root="", title="", filt=""):
    o = S(opts)
    m = re.match(r'([MS]?)(\d*)', o, re.I)
    try:
        r = O.RT
        v = B("FileSelect", o, S(root), S(title), S(filt))
        if isinstance(v, AhkArray):
            items = [S(x) for x in v.items]
            if items:
                d = os.path.dirname(items[0])
                v = d + "\n" + "\n".join(os.path.basename(x) for x in items)
            else:
                v = ""
        out(ref, v)
        EL(0 if S(v) else 1)
    except AhkThrow:
        out(ref, "")
        EL(1)


@export("__v1_fileselectfolder")
def _fileselectfolder(ref, start="", opts=1, prompt=""):
    try:
        v = B("DirSelect", S(start), I(opts, 1), S(prompt))
        out(ref, v)
        EL(0 if v else 1)
    except AhkThrow:
        out(ref, "")
        EL(1)


@export("__v1_splitpath")
def _splitpath(path, *refs):
    return B("SplitPath", S(path), *refs)


@export("__v1_iniread")
def _iniread(ref, path, section="", key="", default="ERROR"):
    try:
        args = [S(path)] + ([S(section)] if S(section) else []) + ([S(key)] if S(key) else [])
        if len(args) == 3:
            args.append(S(default) if default != "" else "ERROR")
        out(ref, B("IniRead", *args))
    except AhkThrow:
        out(ref, S(default) if default != "" else "ERROR")


@export("__v1_iniwrite")
def _iniwrite(value, path, section, key=""):
    try:
        B("IniWrite", value, path, section, *U(key))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_inidelete")
def _inidelete(path, section, key=""):
    try:
        B("IniDelete", path, section, *U(key))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_urldownloadtofile")
def _download(url, path):
    try:
        B("Download", url, path)
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_drive")
def _drive(cmd, a="", b=""):
    c = S(cmd).lower()
    m = {"label": "DriveSetLabel", "lock": "DriveLock", "unlock": "DriveUnlock", "eject": "DriveEject"}
    try:
        if c == "eject" and S(b) == "1":
            B("DriveRetract", *U(a))
        elif c in m:
            B(m[c], *U(a, b)) if c == "label" else B(m[c], *U(a))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_driveget")
def _driveget(ref, cmd, value=""):
    c = S(cmd).lower()
    names = {"list": "DriveGetList", "capacity": "DriveGetCapacity", "filesystem": "DriveGetFileSystem",
             "label": "DriveGetLabel", "serial": "DriveGetSerial", "type": "DriveGetType", "status": "DriveGetStatus",
             "statuscd": "DriveGetStatusCD", "fs": "DriveGetFileSystem", "cap": "DriveGetCapacity"}
    try:
        out(ref, B(names[c], *U(value)) if c in names else "")
        EL(0)
    except (AhkThrow, KeyError):
        out(ref, "")
        EL(1)


# ================================================================ commands: registry

def _regkey(args):
    """New (KeyName, ValueName) or old (RootKey, SubKey, ValueName) syntax -> (key, valuename)."""
    a = [S(x) for x in args]
    roots = ("hkey_", "hklm", "hkcu", "hkcr", "hku", "hkcc")
    if len(a) >= 2 and a[0].lower().startswith(roots) and "\\" not in a[0] and len(a) >= 3:
        return a[0] + ("\\" + a[1] if a[1] else ""), a[2]
    if len(a) >= 2 and a[0].lower().startswith(roots) and "\\" not in a[0] and a[1] and len(a) == 2 and False:
        return a[0] + "\\" + a[1], ""
    return a[0] if a else "", a[1] if len(a) > 1 else ""


@export("__v1_regread")
def _regread(ref, *args):
    key, name = _regkey([x for x in args])
    try:
        out(ref, B("RegRead", key, *U(name)))
        EL(0)
    except AhkThrow:
        out(ref, "")
        EL(1)


@export("__v1_regwrite")
def _regwrite(vtype, *args):
    a = [S(x) for x in args]
    roots = ("hkey_", "hklm", "hkcu", "hkcr", "hku", "hkcc")
    if a and "\\" not in a[0] and a[0].lower().startswith(roots) and len(a) >= 3:
        key = a[0] + ("\\" + a[1] if a[1] else "")
        name, value = (a[2] if len(a) > 2 else ""), (a[3] if len(a) > 3 else "")
    else:
        key, name, value = (a + ["", "", ""])[:3]
    try:
        B("RegWrite", value, S(vtype), key, *U(name))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_regdelete")
def _regdelete(*args):
    key, name = _regkey([x for x in args])
    try:
        if len([x for x in args if S(x)]) <= 1 or (len(args) >= 2 and not S(name) and len(args) == 2):
            B("RegDeleteKey", key)
        else:
            B("RegDelete", key, *U(name))
        EL(0)
    except AhkThrow:
        EL(1)


# ================================================================ commands: processes, system

@export("__v1_run")
def _run(target, wd="", opts="", pid=UNSET):
    try:
        B("Run", S(target), S(wd), S(opts), pid)
        EL(0)
    except AhkThrow:
        EL("ERROR")
        if "useerrorlevel" not in S(opts).lower():
            raise


@export("__v1_runwait")
def _runwait(target, wd="", opts="", pid=UNSET):
    try:
        code = B("RunWait", S(target), S(wd), S(opts).replace("UseErrorLevel", "").strip(), pid)
        EL(code)
        return code
    except AhkThrow:
        EL("ERROR")
        if "useerrorlevel" not in S(opts).lower():
            raise


@export("__v1_runas")
def _runas(*args):
    return quiet(B, "RunAs", *U(*args))


@export("__v1_process")
def _process(cmd, pid="", value=""):
    c = S(cmd).lower()
    try:
        if c == "exist":
            EL(B("ProcessExist", *U(pid)))
        elif c == "close":
            EL(B("ProcessClose", S(pid)))
        elif c == "wait":
            EL(B("ProcessWait", S(pid), *U(value)))
        elif c == "waitclose":
            EL(B("ProcessWaitClose", S(pid), *U(value)))
        elif c == "priority":
            EL(B("ProcessSetPriority", S(value), *U(pid)))
        else:
            EL(0)
    except AhkThrow:
        EL(0)


@export("__v1_shutdown")
def _shutdown(code):
    return B("Shutdown", I(code))


@export("__v1_sysget")
def _sysget(ref, sub, value=""):
    s = S(sub).strip().lower()
    try:
        if s == "monitorcount":
            v = B("MonitorGetCount")
        elif s == "monitorprimary":
            v = B("MonitorGetPrimary")
        elif s == "monitorname":
            v = B("MonitorGetName", *U(value))
        elif s in ("monitor", "monitorworkarea"):
            cells = [Cell() for _ in range(4)]
            B("MonitorGet" if s == "monitor" else "MonitorGetWorkArea", *U(value), *[VarRef(c) for c in cells])
            base = var_name(ref)
            for suffix, c in zip(("Left", "Top", "Right", "Bottom"), cells):
                setvar(base + suffix, c.value)
            return
        else:
            v = B("SysGet", I(s))
        out(ref, v)
    except AhkThrow:
        out(ref, "")


@export("__v1_soundbeep")
def _soundbeep(f="", d=""):
    return B("SoundBeep", *U(f, d))


@export("__v1_soundplay")
def _soundplay(f, wait=""):
    try:
        B("SoundPlay", S(f), *U(wait))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_soundget")
def _soundget(ref, comp="", ctype="", dev=""):
    t = S(ctype).lower() or "volume"
    try:
        if t in ("mute", "onoff"):
            out(ref, "On" if B("SoundGetMute", *U(comp, dev)) else "Off")
        else:
            out(ref, B("SoundGetVolume", *U(comp, dev)))
        EL(0)
    except AhkThrow:
        out(ref, "")
        EL(1)


@export("__v1_soundset")
def _soundset(value, comp="", ctype="", dev=""):
    t = S(ctype).lower() or "volume"
    try:
        if t in ("mute", "onoff"):
            B("SoundSetMute", {"1": 1, "0": 0, "-1": -1, "+1": -1}.get(S(value), I(value)), *U(comp, dev))
        else:
            B("SoundSetVolume", value, *U(comp, dev))
        EL(0)
    except AhkThrow:
        EL(1)


@export("__v1_soundgetwavevolume")
def _sgwv(ref, dev=""):
    _soundget(ref, "", "volume", dev)


@export("__v1_soundsetwavevolume")
def _sswv(value, dev=""):
    _soundset(value, "", "volume", dev)


# ================================================================ commands: screen

@export("__v1_pixelgetcolor")
def _pixelgetcolor(ref, x, y, mode=""):
    try:
        c = B("PixelGetColor", x, y, S(mode).replace("RGB", "").strip() if False else "")
        n = int(S(c), 16) if S(c).lower().startswith("0x") else I(c)
        if "rgb" not in S(mode).lower():
            n = ((n & 0xFF) << 16) | (n & 0xFF00) | ((n >> 16) & 0xFF)
        out(ref, "0x%06X" % n)
        EL(0)
    except AhkThrow:
        out(ref, "")
        EL(1)


@export("__v1_pixelsearch")
def _pixelsearch(ox, oy, x1, y1, x2, y2, color, var=0, mode=""):
    try:
        n = I(color)
        if "rgb" not in S(mode).lower():
            n = ((n & 0xFF) << 16) | (n & 0xFF00) | ((n >> 16) & 0xFF)
        found = B("PixelSearch", ox, oy, x1, y1, x2, y2, n, I(var))
        EL(0 if found else 1)
    except AhkThrow:
        EL(2)


@export("__v1_imagesearch")
def _imagesearch(ox, oy, x1, y1, x2, y2, image):
    try:
        found = B("ImageSearch", ox, oy, x1, y1, x2, y2, S(image))
        EL(0 if found else 1)
    except AhkThrow:
        EL(2)


# ================================================================ commands: dialogs

@export("__v1_MsgBox")
def _msgbox(opts=UNSET, title=UNSET, text=UNSET, timeout=UNSET):
    r = O.RT
    o = I(opts, 0)
    t = UNSET if text is UNSET else S(text)
    if opts is UNSET and title is UNSET and text is UNSET:
        t = "Press OK to continue."
    optstr = str(o) + (" T" + S(timeout) if timeout is not UNSET and S(timeout) != "" else "")
    res = B("MsgBox", t if t is not UNSET else "", title if title is not UNSET and S(title) != "" else UNSET, optstr)
    r.v1_state.msg_result = res
    return ""


@export("__v1_inputbox")
def _inputbox(ref, title="", prompt="", hide="", w="", h="", x="", y="", locale="", timeout="", default=""):
    opts = []
    if S(hide).lower() == "hide":
        opts.append("Password")
    for k, v in (("w", w), ("h", h), ("x", x), ("y", y), ("t", timeout)):
        if S(v) != "":
            opts.append(k + S(v))
    o = B("InputBox", S(prompt), S(title) or UNSET, " ".join(opts), S(default))
    r = O.RT
    out(ref, r.get_prop(o, "Value"))
    res = S(r.get_prop(o, "Result"))
    EL(0 if res == "OK" else 2 if res == "Timeout" else 1)


@export("__v1_tooltip")
def _tooltip(text="", x="", y="", which=1):
    return B("ToolTip", *([S(text)] if S(text) != "" else [UNSET]), *U(x, y), I(which, 1))


@export("__v1_traytip")
def _traytip(title="", text="", secs="", opts=0):
    if S(title) == "" and S(text) == "":
        return B("TrayTip")
    return B("TrayTip", S(text) or " ", S(title), I(opts))


@export("__v1_splashtexton")
def _splashtexton(w=200, h=0, title="", text=""):
    O.RT.v1_gui.splash_text(I(w, 200), I(h, 0), S(title), S(text))


@export("__v1_splashtextoff")
def _splashtextoff():
    O.RT.v1_gui.splash_off()


@export("__v1_progress")
def _progress(p1="", sub="", main="", title="", font=""):
    O.RT.v1_gui.progress(S(p1), S(sub), S(main), S(title), S(font), image=False)


@export("__v1_splashimage")
def _splashimage(img="", opts="", sub="", main="", title="", font=""):
    O.RT.v1_gui.progress(S(opts) if S(img).lower() != "off" else "Off", S(sub), S(main), S(title), S(font),
                         image=S(img))


@export("__v1_clipwait")
def _clipwait(secs="", any_=""):
    r = B("ClipWait", *U(secs, any_))
    EL(0 if r else 1)
