"""Built-in classes (Object::CreateRootPrototypes / DefineClasses in script_object.cpp)."""
from __future__ import annotations

import inspect

from . import objects as O
from .errors import AhkThrow
from .objects import (AhkArray, AhkClass, AhkMap, AhkObject, BoundFunc, BuiltinFunc, CLASSES, FuncBase, Prop,
                      VarRef, make_class, new_error, throw, type_error_msg, value_text)
from .values import UNSET, fmt_float, str_to_number, to_bool, type_name, wrap


def _sig(fn):
    """(min, max, variadic) of a Python function (excluding nothing)."""
    sig = inspect.signature(fn)
    mn = mx = 0
    var = False
    for p in sig.parameters.values():
        if p.kind == p.VAR_POSITIONAL:
            var = True
            continue
        mx += 1
        if p.default is p.empty:
            mn = mx
    return mn, mx, var


def bif(name, fn, byref=()):
    mn, mx, var = _sig(fn)

    def wrapper(*args):
        # replace UNSET (omitted) args by Python defaults
        return fn(*args)
    f = BuiltinFunc(name, _defaults_adapter(fn), mn, mx, var, byref)
    return f


def _defaults_adapter(fn):
    sig = inspect.signature(fn)
    params = [p for p in sig.parameters.values() if p.kind != p.VAR_POSITIONAL]
    defaults = [p.default for p in params]
    has_var = any(p.kind == p.VAR_POSITIONAL for p in sig.parameters.values())
    n = len(params)

    def call(*args):
        if UNSET in args[:n]:
            args = list(args)
            for i in range(min(len(args), n)):
                if args[i] is UNSET and defaults[i] is not inspect.Parameter.empty:
                    args[i] = defaults[i]
        return fn(*args)
    return call


def method(obj, name, fn):
    obj.define_method(name, bif(name, fn))


def prop(obj, name, get=None, set=None):
    g = bif(name + ".Get", get) if get else None
    s = bif(name + ".Set", set) if set else None
    obj.define_prop(name, get=g, set=s)


def setup(rt):
    O.RT = rt
    CLASSES.clear()
    # --- root prototypes ---
    any_proto = AhkObject(None)
    any_proto.define_value("__Class", "Any")
    obj_proto = AhkObject(any_proto)
    obj_proto.define_value("__Class", "Object")
    func_proto = AhkObject(obj_proto)
    func_proto.define_value("__Class", "Func")
    class_proto = AhkObject(obj_proto)
    class_proto.define_value("__Class", "Class")

    any_cls = AhkClass("Any", class_proto, any_proto)
    obj_cls = AhkClass("Object", any_cls, obj_proto, lambda proto: AhkObject(proto))
    func_cls = AhkClass("Func", obj_cls, func_proto)
    class_cls = AhkClass("Class", obj_cls, class_proto)
    for c in (any_cls, obj_cls, func_cls, class_cls):
        CLASSES[c.name] = c

    def sub(name, parent, factory=None):
        proto = AhkObject(parent.prototype)
        proto.define_value("__Class", name)
        c = AhkClass(name, parent, proto, factory)
        CLASSES[name] = c
        return c

    for name in ("BoundFunc", "Closure", "Enumerator"):
        sub(name, func_cls)
    prim = sub("Primitive", any_cls)
    num = sub("Number", prim)
    sub("Integer", num)
    sub("Float", num)
    sub("String", prim)
    sub("VarRef", any_cls)
    sub("ComValue", any_cls)
    arr_cls = sub("Array", obj_cls, lambda proto: AhkArray(proto))
    map_cls = sub("Map", obj_cls, lambda proto: AhkMap(proto))
    sub("Buffer", obj_cls)
    sub("ClipboardAll", CLASSES["Buffer"])
    err = sub("Error", obj_cls)
    for n in ("MemoryError", "OSError", "TargetError", "TimeoutError", "TypeError", "UnsetError", "ValueError",
              "ZeroDivisionError"):
        sub(n, err)
    sub("MemberError", CLASSES["UnsetError"])
    sub("PropertyError", CLASSES["MemberError"])
    sub("MethodError", CLASSES["MemberError"])
    sub("UnsetItemError", CLASSES["UnsetError"])
    sub("IndexError", CLASSES["ValueError"])
    for n in ("File", "Gui", "Menu", "InputHook", "RegExMatchInfo", "ComObject", "ComObjArray", "ComValueRef"):
        sub(n, obj_cls)
    sub("MenuBar", CLASSES["Menu"])
    gui = CLASSES["Gui"]
    ctrl = AhkClass("Gui.Control", obj_cls, AhkObject(obj_proto))
    ctrl.prototype.define_value("__Class", "Gui.Control")
    gui.define_value("Control", ctrl)
    CLASSES["Gui.Control"] = ctrl
    for cname in ("List", "ActiveX", "Button", "CheckBox", "ComboBox", "Custom", "DateTime", "DDL", "Edit", "GroupBox",
                  "Hotkey", "Link", "ListBox", "ListView", "MonthCal", "Pic", "Progress", "Radio", "Slider",
                  "StatusBar", "Tab", "Text", "TreeView", "UpDown"):
        parent = CLASSES["Gui.List"] if cname in ("ComboBox", "DDL", "ListBox", "Tab") and "Gui.List" in CLASSES else ctrl
        cp = AhkObject(parent.prototype)
        cp.define_value("__Class", "Gui." + cname)
        c = AhkClass("Gui." + cname, parent, cp)
        gui.define_value(cname, c)
        CLASSES["Gui." + cname] = c

    # --- Any ---
    lib = rt.lib_core
    method(any_proto, "GetMethod", lambda this, name=UNSET, pc=UNSET: lib.GetMethod(this, name, pc))
    method(any_proto, "HasBase", lambda this, b: lib.HasBase(this, b))
    method(any_proto, "HasMethod", lambda this, name=UNSET, pc=UNSET: lib.HasMethod(this, name, pc))
    method(any_proto, "HasProp", lambda this, name: lib.HasProp(this, name))
    prop(any_proto, "Base", get=lambda this: lib.ObjGetBase(this), set=lambda this, v: lib.ObjSetBase(this, v))
    any_proto.define_method("__Init", BuiltinFunc("__Init", lambda this: "", 1, 1))

    # --- Object ---
    method(obj_proto, "Clone", lambda this: lib.obj_clone(this))
    method(obj_proto, "DefineProp", lambda this, name, desc: lib.obj_define_prop(this, name, desc))
    method(obj_proto, "DeleteProp", lambda this, name: lib.obj_delete_prop(this, name))
    method(obj_proto, "GetOwnPropDesc", lambda this, name: lib.obj_get_own_prop_desc(this, name))
    method(obj_proto, "HasOwnProp", lambda this, name: int(isinstance(this, AhkObject) and this.own(rt.to_str(name)) is not None))
    method(obj_proto, "OwnProps", lambda this: lib.obj_own_props(this))
    # Object() / class Call
    method(class_proto, "Call", lambda this, *args: lib.construct(this, list(args)))

    # --- Func ---
    prop(func_proto, "Name", get=lambda this: this.name)
    prop(func_proto, "MinParams", get=lambda this: this.min_params())
    prop(func_proto, "MaxParams", get=lambda this: this.max_params())
    prop(func_proto, "IsVariadic", get=lambda this: int(this.is_variadic()))
    prop(func_proto, "IsBuiltIn", get=lambda this: int(this.is_builtin()))
    method(func_proto, "Bind", lambda this, *args: BoundFunc(this, list(args)))
    method(func_proto, "Call", lambda this, *args: rt.call(this, list(args)))
    method(func_proto, "IsByRef", lambda this, n=0: lib.func_is_byref(this, n))
    method(func_proto, "IsOptional", lambda this, n=0: lib.func_is_optional(this, n))

    # --- Array ---
    ap = arr_cls.prototype
    prop(ap, "Length", get=lambda this: len(this.items), set=lambda this, v: lib.arr_set_length(this, v))
    prop(ap, "Capacity", get=lambda this: max(this.capacity, len(this.items)), set=lambda this, v: lib.arr_set_capacity(this, v))
    method(ap, "__New", lambda this, *vals: this.items.extend(vals) or "")
    method(ap, "Push", lambda this, *vals: this.items.extend(vals) or "")
    method(ap, "Pop", lambda this: lib.arr_pop(this))
    method(ap, "InsertAt", lambda this, idx, *vals: lib.arr_insert(this, idx, vals))
    method(ap, "RemoveAt", lambda this, idx, length=UNSET: lib.arr_remove(this, idx, length))
    method(ap, "Delete", lambda this, idx: lib.arr_delete(this, idx))
    method(ap, "Has", lambda this, idx: lib.arr_has(this, idx))
    method(ap, "Get", lambda this, idx, default=UNSET: lib.arr_get(this, idx, default))
    method(ap, "Clone", lambda this: lib.arr_clone(this))
    method(ap, "__Enum", lambda this, n=1: lib.arr_enum(this, n))
    _native_item(ap)

    # --- Map ---
    mp = map_cls.prototype
    method(mp, "__New", lambda this, *kv: lib.map_set(this, *kv))
    method(mp, "Set", lambda this, *kv: lib.map_set(this, *kv))
    method(mp, "Get", lambda this, key, default=UNSET: lib.map_get(this, key, default))
    method(mp, "Has", lambda this, key: int(this.key(key) in this.data))
    method(mp, "Delete", lambda this, key: lib.map_delete(this, key))
    method(mp, "Clear", lambda this: this.data.clear() or "")
    method(mp, "Clone", lambda this: lib.map_clone(this))
    method(mp, "__Enum", lambda this, n=1: lib.map_enum(this, n))
    prop(mp, "Count", get=lambda this: len(this.data))
    prop(mp, "Capacity", get=lambda this: len(this.data), set=lambda this, v: v)
    prop(mp, "CaseSense", get=lambda this: this.casesense, set=lambda this, v: lib.map_set_casesense(this, v))
    _native_item(mp)

    # --- Error ---
    ep = err.prototype
    ep.define_value("Message", "")
    ep.define_value("What", "")
    ep.define_value("Extra", "")
    method(ep, "__New", lambda this, msg=UNSET, what=UNSET, extra=UNSET: lib.error_new(this, msg, what, extra))
    prop(ep, "Stack", get=lambda this: "")
    CLASSES["OSError"].prototype.define_value("Number", 0)

    # --- primitives: conversion functions are the class Call ---
    method(CLASSES["Integer"], "Call", lambda this, v: lib.Integer(v))
    method(CLASSES["Float"], "Call", lambda this, v: lib.Float(v))
    method(CLASSES["Number"], "Call", lambda this, v: lib.Number(v))
    method(CLASSES["String"], "Call", lambda this, v: lib.String(v))

    # --- VarRef ---
    vp = CLASSES["VarRef"].prototype
    prop(vp, "__Value", get=lambda this: this.cell.value, set=lambda this, v: setattr(this.cell, "value", v))

    # --- Buffer ---
    from .lib import buffer
    buffer.setup(rt, CLASSES["Buffer"])

    return CLASSES


def _native_item(proto):
    """Mark __Item as natively implemented so get_item uses native_item_get."""
    from .runtime import _NativeItem
    proto.define_prop("__Item", get=_NativeItem(), set=_NativeItem())
