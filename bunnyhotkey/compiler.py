"""AST -> Python closures.

Scoping follows AutoHotkey v2: functions are assume-local; a name that is only
read (never assigned) in a function resolves to a global if one exists; nested
functions capture enclosing locals as closures; `static` cells persist.
"""
from __future__ import annotations

import time

import re

from . import ast as A
from . import objects as O
from .errors import (AhkSyntaxError, AhkThrow, BreakEx, ContinueEx, ExitThread, GotoEx, ReturnEx)
from .objects import (AhkArray, AhkClass, AhkMap, AhkObject, Cell, CLASSES, FuncBase, VarRef, new_error,
                      throw, type_error_msg, value_text)
from .runtime import (CompiledFunc, CParam, LoopInfo, Scope, UserFunc, _assigned_names, arith, compare,
                      concat)
from .values import UNSET, str_to_number, to_bool, type_name, wrap

ARITH = {"+", "-", "*", "/", "//", "**", "|", "^", "&", "<<", ">>", ">>>"}
CMP = {"=", "==", "!=", "!==", "<", ">", "<=", ">="}


class Home:
    """Holds the object a method was defined on (for `super`)."""
    __slots__ = ("obj",)

    def __init__(self):
        self.obj = None


class Compiler:
    def __init__(self, rt):
        self.rt = rt
        self.gscope = Scope("global")
        self.class_defs = []
        self.pending_bases = []
        self.hot_items = []       # (kind, node, ctx, compiled) in source order
        self.directive_items = []
        # AutoHotkey v1: functions live in their own namespace, so variables may share their names.
        self.v1 = getattr(rt, "script_version", "2") == "1"
        self.builtin_consts = {k for k, c in rt.globals.items() if c.scope == "const" and not k.startswith("__v1_")}

    # ================================================================== program
    def compile_program(self, stmts: list[A.Node]):
        rt = self.rt
        top = []
        funcs = []
        classes = []
        hot = []
        self._flatten(stmts, top, funcs, classes, hot)
        # global names: assigned at top level, declared global anywhere, functions, classes
        gnames: set[str] = set()
        _assigned_names(top, gnames, {})
        for fd in funcs:
            self._collect_global_decls(fd.body.body, gnames)
        for h in hot:
            if getattr(h, "body", None) is not None:
                self._collect_global_decls(h.body.body, gnames)
        for cd in classes:
            self._collect_class_global_decls(cd, gnames)
        for n in gnames:
            self._gcell(n)
        # functions first (hoisted)
        compiled = []
        for fd in funcs:
            key = fd.name.lower()
            if key in rt.consts:
                raise AhkSyntaxError("Duplicate function definition.", fd.file, fd.line, fd.name)
            cf = CompiledFunc(rt, fd.name)
            if self.v1:
                if key in rt.v1_funcs:
                    raise AhkSyntaxError("Duplicate function definition.", fd.file, fd.line, fd.name)
                rt.v1_funcs[key] = Cell(fd.name, UserFunc(cf), "const")
                compiled.append((fd, cf))
                continue
            cell = self._gcell(fd.name)
            cell.value = UserFunc(cf)
            cell.scope = "const"
            rt.consts.add(key)
            compiled.append((fd, cf))
        for cd in classes:
            self._declare_class(cd)
        for fd, cf in compiled:
            self.compile_func(fd, cf, None)
        for cd, cls in self.class_defs:
            self._build_class(cd, cls)
        self._resolve_bases()
        auto = self.compile_block(top, self.gscope, top_level=True)
        hotdefs = []
        for item in hot:
            hotdefs.append(self._compile_hot(item))
        return auto, hotdefs

    def _flatten(self, stmts, top, funcs, classes, hot):
        for s in stmts:
            if isinstance(s, A.FuncDef):
                funcs.append(s)
            elif isinstance(s, A.ClassDef):
                classes.append(s)
            elif isinstance(s, (A.HotkeyDef, A.HotstringDef)):
                hot.append(s)
            elif isinstance(s, A.Directive):
                hot.append(s)
            elif isinstance(s, A.Block) and s.body and all(isinstance(x, (A.HotstringDef, A.HotkeyDef)) for x in s.body):
                hot.extend(s.body)
            else:
                top.append(s)

    def _collect_global_decls(self, stmts, out):
        def walk(s):
            if isinstance(s, A.Decl) and s.kind == "global":
                for name, _ in s.items:
                    out.add(name.lower())
            if isinstance(s, A.FuncDef):
                walk(s.body)
                return
            if isinstance(s, A.Node):
                for f in s.fields:
                    v = getattr(s, f)
                    if isinstance(v, list):
                        for x in v:
                            if isinstance(x, A.Node):
                                walk(x)
                            elif isinstance(x, tuple):
                                for y in x:
                                    if isinstance(y, A.Node):
                                        walk(y)
                    elif isinstance(v, A.Node):
                        walk(v)
        for s in stmts:
            walk(s)

    def _collect_class_global_decls(self, cd, out):
        for m in cd.members:
            if isinstance(m, A.FuncDef):
                self._collect_global_decls(m.body.body, out)
            elif isinstance(m, A.PropDef):
                for fd in (m.getter, m.setter):
                    if fd:
                        self._collect_global_decls(fd.body.body, out)
            elif isinstance(m, A.ClassDef):
                self._collect_class_global_decls(m, out)

    def _gcell(self, name) -> Cell:
        key = name.lower()
        if self.v1 and key in self.builtin_consts:
            c = self.rt.v1_shadow.get(key)
            if c is None:
                c = self.rt.v1_shadow[key] = Cell(name, UNSET, "global")
            return c
        c = self.rt.globals.get(key)
        if c is None:
            c = Cell(name, UNSET, "global")
            self.rt.globals[key] = c
        return c

    # ================================================================== functions
    def compile_func(self, fd: A.FuncDef, cf: CompiledFunc, parent: Scope | None, is_method=False, home=None):
        scope = Scope("func", parent, fd, is_method)
        scope.cf = cf
        scope.home = home
        cf.file = fd.file
        cf.line = fd.line
        cf.is_method = is_method
        params = []
        if is_method:
            params.append(A.Param("this", False, None, False, False))
        params.extend(fd.params)
        # locals: params, assigned names, declared locals; minus declared globals
        assigned: set[str] = set()
        declared: dict = {}
        _assigned_names(fd.body.body, assigned, declared)
        scope.declared_global = declared.get("global", set())
        scope.assume_global = bool(declared.get("assume_global"))
        scope.assume_static = bool(declared.get("assume_static"))
        for p in params:
            if p.name:
                scope.add_local(p.name)
        for name in declared.get("static", set()):
            scope.statics[name] = cf.statics.setdefault(name, Cell(name, UNSET, "static"))
        for name in declared.get("local", set()):
            scope.declared_local.add(name)
            scope.add_local(name)
        for name in assigned:
            if name in scope.declared_global or name in scope.statics:
                continue
            if scope.assume_global and name not in scope.declared_local:
                scope.declared_global.add(name)
                self._gcell(name)
                continue
            if scope.assume_static and name not in scope.declared_local and name not in scope.locals:
                scope.statics[name] = cf.statics.setdefault(name, Cell(name, UNSET, "static"))
                continue
            if name.startswith("a_") and name in self.rt.bivars:
                continue
            scope.add_local(name)
        for g in scope.declared_global:
            self._gcell(g)
        # parameters
        np = 0
        minp = 0
        for p in params:
            if p.variadic:
                cf.variadic = True
                if p.name:
                    cf.variadic_slot = scope.locals[p.name.lower()]
                continue
            default = self.compile_expr(p.default, scope) if p.default is not None else None
            cp = CParam(p.name, p.byref, p.optional, default, scope.locals[p.name.lower()], False)
            cf.params.append(cp)
            np += 1
            if not p.optional:
                minp = np
        cf.min_params = minp
        cf.max_params = np
        # nested functions (named) are local constants created at entry
        for s in self._direct_funcdefs(fd.body.body):
            slot = scope.add_local(s.name)
            sub = CompiledFunc(self.rt, s.name)
            cf.nested_inits.append((slot, sub, None))
        body = self.compile_block(fd.body.body, scope, func_body=True)
        if self.v1:
            cf.dyn_find = self.dyn_resolver(scope)
            cf.assume_global = scope.assume_global
        cf.nlocals = len(scope.local_names)
        cf.local_names = list(scope.local_names)
        cf.body = body
        cf.is_closure = bool(scope.capture_list)
        cf.capture_list = scope.capture_list
        return scope

    def _direct_funcdefs(self, stmts):
        out = []
        for s in stmts:
            if isinstance(s, A.FuncDef):
                out.append(s)
        return out

    # ================================================================== name resolution
    def resolve(self, name: str, scope: Scope):
        if self.v1:
            return self.resolve_v1(name, scope)
        key = name.lower()
        rt = self.rt
        if key.startswith("a_") and key in rt.bivars:
            return ("bivar", key)
        if scope.kind == "global":
            if key in rt.globals:
                return ("global", rt.globals[key])
            if key in rt.builtins:
                return ("const", rt.builtins[key])
            return ("global", self._gcell(name))
        if key in scope.declared_global:
            return ("global", self._gcell(name))
        if key in scope.statics:
            return ("static", scope.statics[key])
        if key in scope.locals:
            return ("local", scope.locals[key])
        idx = scope.capture(key)
        if idx is not None:
            return ("free", idx)
        if key in rt.globals:
            return ("global", rt.globals[key])
        if key in rt.builtins:
            return ("const", rt.builtins[key])
        if scope.assume_global:
            return ("global", self._gcell(name))
        return ("local", scope.add_local(name))

    def resolve_v1(self, name, scope):
        """v1 scoping: functions see globals only when declared (or super-global / assume-global)."""
        key = name.lower()
        rt = self.rt
        if key in rt.bivars and (key.startswith("a_") or key in rt.v1_bivar_names):
            return ("bivar", key)
        if scope.kind == "global":
            return ("global", self._gcell(name))
        if key in scope.declared_global:
            return ("global", self._gcell(name))
        if key in scope.statics:
            return ("static", scope.statics[key])
        if key in scope.locals:
            return ("local", scope.locals[key])
        idx = scope.capture(key)
        if idx is not None:
            return ("free", idx)
        if key in rt.v1_superglobals or scope.assume_global:
            return ("global", self._gcell(name))
        c = rt.globals.get(key)
        if c is not None and c.scope == "const" and key not in self.builtin_consts:
            return ("global", c)       # class names are super-global in v1
        if key in ("this", "super"):
            return ("local", scope.add_local(name))
        return ("local", scope.add_local(name))

    def var_getter(self, name, scope, maybe=False):
        kind, ref = self.resolve(name, scope)
        rt = self.rt
        if kind == "local":
            i = ref
            if maybe:
                return lambda f: f.cells[i].value
            def g(f):
                c = f.cells[i]
                v = c.value
                if v is UNSET and getattr(rt, "script_version", "2") == "1":
                    return ""
                if v is UNSET:
                    rt.unset_error(c)
                return v
            return g
        if kind == "free":
            i = ref
            if maybe:
                return lambda f: f.free[i].value
            def g(f):
                c = f.free[i]
                v = c.value
                if v is UNSET and getattr(rt, "script_version", "2") == "1":
                    return ""
                if v is UNSET:
                    rt.unset_error(c)
                return v
            return g
        if kind in ("global", "static"):
            cell = ref
            if maybe:
                def gm(f):
                    v = cell.value
                    if isinstance(v, AhkClass):
                        rt.class_ref(v)
                    return v
                return gm
            def g(f):
                v = cell.value
                if v is UNSET and getattr(rt, "script_version", "2") == "1":
                    return ""
                if v is UNSET:
                    rt.unset_error(cell)
                if type(v) is AhkClass:
                    rt.class_ref(v)
                return v
            return g
        if kind == "const":
            val = ref
            return lambda f: val
        if kind == "bivar":
            getter = rt.bivars[ref][0]
            return lambda f: getter()
        raise AssertionError(kind)

    def var_setter(self, name, scope):
        kind, ref = self.resolve(name, scope)
        rt = self.rt
        if kind == "local":
            i = ref
            def s(f, v):
                f.cells[i].value = v
            return s
        if kind == "free":
            i = ref
            def s(f, v):
                f.free[i].value = v
            return s
        if kind in ("global", "static"):
            cell = ref
            if cell.scope == "const":
                def ro(f, v):
                    throw("Error", "This variable is read-only.", name)
                return ro
            def s(f, v):
                cell.value = v
            return s
        if kind == "bivar":
            setter = rt.bivars[ref][1]
            if setter is None:
                def ro(f, v):
                    throw("Error", "This variable is read-only.", name)
                return ro
            def s(f, v):
                setter(v)
            return s
        def ro(f, v):
            throw("Error", "This variable is read-only.", name)
        return ro

    def var_cell(self, name, scope):
        """Accessor returning the Cell (for &var)."""
        kind, ref = self.resolve(name, scope)
        if kind == "local":
            i = ref
            return lambda f: f.cells[i]
        if kind == "free":
            i = ref
            return lambda f: f.free[i]
        if kind in ("global", "static"):
            cell = ref
            return lambda f: cell
        rt = self.rt
        if kind == "bivar":
            getter, setter = rt.bivars[ref]
            def mk(f):
                c = _BivarCell(getter, setter, name)
                return c
            return mk
        val = ref
        return lambda f: Cell(name, val)

    def dyn_resolver(self, scope):
        """Runtime lookup of a variable by name for %expr% references."""
        rt = self.rt
        local_map = scope.locals if scope.kind == "func" else None
        captures = scope.captures if scope.kind == "func" else None
        v1 = self.v1
        compiler = self

        def find(f, name):
            key = name.lower()
            if not key:
                throw("Error", "This dynamic variable is blank.")
            if key.startswith("a_") and key in rt.bivars:
                getter, setter = rt.bivars[key]
                return _BivarCell(getter, setter, name)
            if local_map is not None:
                if key in scope.declared_global:
                    return rt.globals.get(key) or self._gcell(name)
                if key in scope.statics:
                    return scope.statics[key]
                if key in local_map:
                    return f.cells[local_map[key]]
                if key in captures:
                    return f.free[captures[key]]
            if v1:
                dyn = getattr(f, "dyn", None) if f is not None else None
                if dyn and key in dyn:
                    return dyn[key]
                c = compiler._gcell(name) if key in rt.globals or key in rt.v1_shadow else None
                if local_map is not None and not scope.assume_global and key not in rt.v1_superglobals:
                    return c if c is not None and c.value is not UNSET else None
                return c
            c = rt.globals.get(key)
            if c is not None:
                return c
            if key in rt.builtins:
                return Cell(name, rt.builtins[key], "const")
            throw("Error", "Variable not found.", name) if False else None
            return None
        find.create = lambda f, name: compiler._v1_create(f, name, scope)
        return find

    def _v1_create(self, f, name, scope):
        """A v1 dynamic reference to a variable that doesn't exist yet creates it."""
        if scope.kind == "func" and not scope.assume_global and f is not None:
            if f.dyn is None:
                f.dyn = {}
            c = f.dyn[name.lower()] = Cell(name, UNSET, "local")
            return c
        return self._gcell(name)

    # ================================================================== expressions
    def compile_expr(self, e: A.Node, scope: Scope):
        m = getattr(self, "e_" + type(e).__name__)
        return m(e, scope)

    def e_Num(self, e, scope):
        v = e.value
        return lambda f: v

    def e_Str(self, e, scope):
        v = e.value
        return lambda f: v

    def e_Var(self, e, scope):
        return self.var_getter(e.name, scope)

    def e_This(self, e, scope):
        return self.var_getter("this", scope)

    def e_Unset(self, e, scope):
        return lambda f: UNSET

    def e_Super(self, e, scope):
        raise AhkSyntaxError('"super" is valid only in a method', e.file, e.line)

    def e_DynVar(self, e, scope):
        name_fn = self._dyn_name(e.parts, scope)
        find = self.dyn_resolver(scope)
        rt = self.rt

        if self.v1:
            noenv = rt.v1_noenv

            def g1(f):
                name = name_fn(f)
                c = find(f, name)
                v = c.value if c is not None else UNSET
                if v is UNSET:
                    if not noenv:
                        import os
                        return os.environ.get(name, "")
                    return ""
                return v
            return g1

        def g(f):
            name = name_fn(f)
            c = find(f, name)
            if c is None:
                if scope.kind == "global" or True:
                    throw("UnsetError", "This variable has not been assigned a value.", name) if False else None
                throw("Error", "Variable not found.", name) if False else None
                c = None
            if c is None:
                throw("UnsetError", "This global variable has not been assigned a value.", name)
            v = c.value
            if v is UNSET:
                rt.unset_error(c)
            return v
        return g

    def _dyn_name(self, parts, scope):
        fns = []
        for p in parts:
            if isinstance(p, str):
                fns.append(lambda f, p=p: p)
            else:
                ev = self.compile_expr(p, scope)
                rt = self.rt
                fns.append(lambda f, ev=ev: rt.to_str(ev(f)))
        if len(fns) == 1:
            return fns[0]
        return lambda f: "".join(fn(f) for fn in fns)

    def e_Member(self, e, scope):
        rt = self.rt
        if isinstance(e.obj, A.Super):
            return self._super_get(e, scope)
        obj = self.compile_expr(e.obj, scope)
        if e.dyn is not None:
            nm = self.compile_expr(e.dyn, scope)
            return lambda f: rt.get_prop(obj(f), rt.to_str(nm(f)))
        name = e.name
        get_prop = rt.get_prop
        return lambda f: get_prop(obj(f), name)

    def _home(self, scope):
        s = scope
        while s is not None and getattr(s, "home", None) is None:
            s = s.parent
        if s is None:
            raise AhkSyntaxError('"super" is valid only in a method')
        return s.home

    def _super_get(self, e, scope):
        rt = self.rt
        home = self._home(scope)
        this = self.var_getter("this", scope)
        name = e.name
        return lambda f: rt.get_prop(None, name, start=home.obj.base, this=this(f))

    def e_Index(self, e, scope):
        rt = self.rt
        args = self.compile_args(e.args, scope, getattr(e, "variadic", False))
        if isinstance(e.obj, A.Member) and not isinstance(e.obj.obj, A.Super):
            # obj.prop[args] passes args to the property (AHK semantics)
            base = self.compile_expr(e.obj.obj, scope)
            nmf = self._member_name(e.obj, scope)
            return lambda f: rt.get_prop(base(f), nmf(f), args(f))
        obj = self.compile_expr(e.obj, scope)
        return lambda f: rt.get_item(obj(f), args(f))

    def _member_name(self, m, scope):
        rt = self.rt
        if m.dyn is None:
            n = m.name
            return lambda f: n
        ev = self.compile_expr(m.dyn, scope)
        return lambda f: rt.to_str(ev(f))

    def compile_args(self, args, scope, variadic):
        rt = self.rt
        fns = []
        for a in args:
            if a is None:
                fns.append(None)
            elif isinstance(a, A.Maybe):
                fns.append(self._maybe(a.expr, scope))
            else:
                fns.append(self.compile_expr(a, scope))
        n = len(fns)
        if variadic:
            last = fns[-1]
            head = fns[:-1]

            def ev(f):
                out = [UNSET if fn is None else fn(f) for fn in head]
                v = last(f)
                if type(v) is AhkArray:
                    out.extend(v.items)
                else:
                    for t in rt.enumerate(v, 1):
                        out.append(t[0])
                return out
            return ev
        if n == 0:
            return lambda f: []
        if n == 1 and fns[0] is not None:
            a0 = fns[0]
            return lambda f: [a0(f)]
        if n == 2 and fns[0] is not None and fns[1] is not None:
            a0, a1 = fns
            return lambda f: [a0(f), a1(f)]
        return lambda f: [UNSET if fn is None else fn(f) for fn in fns]

    def _maybe(self, e, scope):
        if isinstance(e, A.Var):
            return self.var_getter(e.name, scope, maybe=True)
        inner = self.compile_expr(e, scope)

        def m(f):
            try:
                return inner(f)
            except AhkThrow as ex:
                v = ex.value
                if isinstance(v, AhkObject) and v.has_base(CLASSES["UnsetError"].prototype):
                    return UNSET
                raise
        return m

    def e_Maybe(self, e, scope):
        return self._maybe(e.expr, scope)

    def e_Call(self, e, scope):
        rt = self.rt
        args = self.compile_args(e.args, scope, e.variadic)
        if self.v1 and isinstance(e.func, A.Var):
            key = e.func.name.lower()
            cell = rt.v1_funcs.get(key)
            if cell is not None:
                return lambda f: cell.value.call(args(f))
            if key in rt.builtins:
                call = rt.builtins[key].call
                return lambda f: call(args(f))
            c = rt.globals.get(key)
            if c is not None and c.scope == "const":
                return lambda f: rt.call(c.value, args(f))
            name = e.func.name

            def late(f):
                return rt.call(rt.v1_lookup_func(name, True), args(f))
            return late
        if isinstance(e.func, A.Var):
            kind, ref = self.resolve(e.func.name, scope)
            if kind == "const":
                fn = ref
                call = fn.call
                return lambda f: call(args(f))
            if kind == "global" and ref.scope == "const":
                cell = ref
                return lambda f: rt.call(cell.value, args(f))
        if isinstance(e.func, A.Super):
            home = self._home(scope)
            this = self.var_getter("this", scope)
            return lambda f: rt.call_method(None, "Call", args(f), start=home.obj.base, this=this(f))
        fn = self.compile_expr(e.func, scope)
        call = rt.call
        return lambda f: call(fn(f), args(f))

    def e_MethodCall(self, e, scope):
        rt = self.rt
        args = self.compile_args(e.args, scope, e.variadic)
        if isinstance(e.obj, A.Super):
            home = self._home(scope)
            this = self.var_getter("this", scope)
            name = e.name
            return lambda f: rt.call_method(None, name, args(f), start=home.obj.base, this=this(f))
        obj = self.compile_expr(e.obj, scope)
        if e.dyn is not None:
            nm = self.compile_expr(e.dyn, scope)
            return lambda f: rt.call_method(obj(f), rt.to_str(nm(f)), args(f))
        name = e.name
        cm = rt.call_method
        return lambda f: cm(obj(f), name, args(f))

    def e_Unary(self, e, scope):
        rt = self.rt
        x = self.compile_expr(e.operand, scope)
        op = e.op
        if op == "!":
            return lambda f: 0 if to_bool(x(f)) else 1
        if op == "-":
            def neg(f):
                v = x(f)
                t = type(v)
                if t is int:
                    return wrap(-v)
                if t is float:
                    return -v
                n = rt.to_num(v)
                return wrap(-n) if type(n) is int else -n
            return neg
        if op == "+":
            return lambda f: rt.to_num(x(f))
        if op == "~":
            def bitnot(f):
                v = rt.to_num(x(f))
                if type(v) is not int:
                    throw("TypeError", type_error_msg("Integer", v), value_text(v))
                return ~v
            return bitnot
        raise AssertionError(op)

    def e_Binary(self, e, scope):
        rt = self.rt
        a = self.compile_expr(e.left, scope)
        b = self.compile_expr(e.right, scope)
        op = e.op
        if op == ".":
            def cat(f):
                x = a(f)
                y = b(f)
                if type(x) is str and type(y) is str:
                    return x + y
                return concat(rt, x, y)
            return cat
        if op == "+":
            def add(f):
                x = a(f)
                y = b(f)
                if type(x) is int and type(y) is int:
                    r = x + y
                    if -9223372036854775808 <= r <= 9223372036854775807:
                        return r
                return arith(rt, "+", x, y)
            return add
        if op in ARITH:
            return lambda f: arith(rt, op, a(f), b(f))
        if op in CMP:
            if op in ("<", ">", "<=", ">="):
                def rel(f):
                    x = a(f)
                    y = b(f)
                    if type(x) is int and type(y) is int:
                        if op == "<":
                            return int(x < y)
                        if op == ">":
                            return int(x > y)
                        if op == "<=":
                            return int(x <= y)
                        return int(x >= y)
                    return compare(rt, op, x, y)
                return rel
            return lambda f: compare(rt, op, a(f), b(f))
        if op == "~=":
            from .lib.regex import regex_match_pos
            return lambda f: regex_match_pos(rt, a(f), b(f))
        if op == "is":
            def is_(f):
                x = a(f)
                c = b(f)
                if not isinstance(c, AhkObject):
                    throw("TypeError", type_error_msg("Class", c), value_text(c))
                p = c.own("Prototype")
                if p is None or not isinstance(p.value, AhkObject):
                    throw("TypeError", type_error_msg("Class", c), value_text(c))
                proto = p.value
                if isinstance(x, AhkObject):
                    return int(x.has_base(proto))
                base = rt.base_of(x)
                return int(base is proto or base.has_base(proto))
            return is_
        raise AssertionError(op)

    def e_Logical(self, e, scope):
        b = self.compile_expr(e.right, scope)
        op = e.op
        if op == "??":
            if isinstance(e.left, A.Var):
                a = self.var_getter(e.left.name, scope, maybe=True)
            else:
                a = self._maybe(e.left, scope)

            def coalesce(f):
                v = a(f)
                return b(f) if v is UNSET else v
            return coalesce
        a = self.compile_expr(e.left, scope)
        if op == "&&":
            def and_(f):
                v = a(f)
                if not to_bool(v):
                    return v
                return b(f)
            return and_

        def or_(f):
            v = a(f)
            if to_bool(v):
                return v
            return b(f)
        return or_

    def e_Ternary(self, e, scope):
        c = self.compile_expr(e.cond, scope)
        a = self.compile_expr(e.a, scope)
        b = self.compile_expr(e.b, scope)
        return lambda f: a(f) if to_bool(c(f)) else b(f)

    def e_Comma(self, e, scope):
        fns = [self.compile_expr(x, scope) for x in e.exprs]

        def seq(f):
            v = ""
            for fn in fns:
                v = fn(f)
            return v
        return seq

    def e_IsSetExpr(self, e, scope):
        t = e.target
        if isinstance(t, A.Var):
            g = self.var_getter(t.name, scope, maybe=True)
            return lambda f: 0 if g(f) is UNSET else 1
        if isinstance(t, A.DynVar):
            find = self.dyn_resolver(scope)
            nm = self._dyn_name(t.parts, scope)

            def dg(f):
                c = find(f, nm(f))
                return 0 if c is None or c.value is UNSET else 1
            return dg
        inner = self._maybe(t, scope)
        return lambda f: 0 if inner(f) is UNSET else 1

    def e_Ref(self, e, scope):
        t = e.target
        if isinstance(t, A.Maybe) and isinstance(t.expr, (A.Var, A.DynVar)):
            t = t.expr      # `&var?`: the reference overrides the maybe-read (script.cpp SYM_REF -> VARREF_REF)
        if isinstance(t, A.Assign) and isinstance(t.target, (A.Var, A.DynVar)):
            assign = self.compile_expr(t, scope)
            ref = self.e_Ref(A.Ref(t.target, line=e.line, file=e.file), scope)

            def ref_after_assign(f):
                assign(f)
                return ref(f)
            return ref_after_assign
        if isinstance(t, A.Var):
            cg = self.var_cell(t.name, scope)
            return lambda f: VarRef(cg(f))
        if isinstance(t, A.DynVar):
            find = self.dyn_resolver(scope)
            nm = self._dyn_name(t.parts, scope)

            def dref(f):
                name = nm(f)
                c = find(f, name)
                if c is None:
                    c = find.create(f, name) if self.v1 else self._gcell(name)
                return VarRef(c)
            return dref
        raise AhkSyntaxError("Invalid use of &", e.file, e.line)

    def e_ArrayLit(self, e, scope):
        rt = self.rt
        fns = []
        for it in e.items:
            if it is None:
                fns.append(None)
            elif isinstance(it, tuple) and it[0] == "spread":
                inner = self.compile_expr(it[1], scope)
                fns.append(("spread", inner))
            elif isinstance(it, A.Maybe):
                fns.append(self._maybe(it.expr, scope))
            else:
                fns.append(self.compile_expr(it, scope))

        def arr(f):
            items = []
            for fn in fns:
                if fn is None:
                    items.append(UNSET)
                elif type(fn) is tuple:
                    v = fn[1](f)
                    items.extend(t[0] for t in rt.enumerate(v, 1))
                else:
                    items.append(fn(f))
            return AhkArray(None, items)
        return arr

    def e_ObjLit(self, e, scope):
        rt = self.rt
        pairs = []
        for k, v in e.pairs:
            kf = (lambda f, k=k: k) if isinstance(k, str) else (lambda f, ev=self.compile_expr(k, scope): rt.to_str(ev(f)))
            pairs.append((kf, self.compile_expr(v, scope)))

        def obj(f):
            o = AhkObject(CLASSES["Object"].prototype)
            for kf, vf in pairs:
                name = kf(f)
                val = vf(f)
                rt.set_prop(o, name, val)
            return o
        return obj

    def e_FuncExpr(self, e, scope):
        fd = e.func
        cf = CompiledFunc(self.rt, fd.name)
        sub = self.compile_func(fd, cf, scope if scope.kind == "func" else None, is_method=False)
        caps = sub.capture_list
        rt = self.rt

        def mk(f):
            free = [f.cells[idx] if kind == "l" else f.free[idx] for kind, idx in caps]
            return UserFunc(cf, free)
        if scope.kind != "func":
            uf_static = UserFunc(cf, [])
            return lambda f: uf_static if not caps else mk(f)
        return mk

    def e_Assign(self, e, scope):
        rt = self.rt
        op = e.op
        t = e.target
        val = self.compile_expr(e.value, scope)
        binop = op[:-1] if op != ":=" else None
        # target accessors
        if isinstance(t, A.Var):
            setter = self.var_setter(t.name, scope)
            if op == ":=":
                def assign(f):
                    v = val(f)
                    setter(f, v)
                    return v
                return assign
            if op == "??=":
                getter = self.var_getter(t.name, scope, maybe=True)

                def qassign(f):
                    cur = getter(f)
                    if cur is not UNSET:
                        return cur
                    v = val(f)
                    setter(f, v)
                    return v
                return qassign
            getter = self.var_getter(t.name, scope)
            return self._compound(getter, setter, val, binop)
        if isinstance(t, A.DynVar):
            find = self.dyn_resolver(scope)
            nm = self._dyn_name(t.parts, scope)
            compiler = self

            def cellf(f):
                name = nm(f)
                c = find(f, name)
                if c is None and compiler.v1:
                    return find.create(f, name)
                if c is None:
                    if scope.kind == "global":
                        c = compiler._gcell(name)
                    else:
                        throw("Error", "Variable not found.", name) if False else None
                        c = compiler._gcell(name)
                return c
            if op == ":=":
                def dassign(f):
                    c = cellf(f)
                    v = val(f)
                    c.value = v
                    return v
                return dassign

            def dcompound(f):
                c = cellf(f)
                cur = c.value
                if cur is UNSET and binop != "??":
                    rt.unset_error(c)
                v = self._apply(binop, cur, val(f)) if binop != "??" else (cur if cur is not UNSET else val(f))
                c.value = v
                return v
            return dcompound
        if isinstance(t, A.Member):
            if isinstance(t.obj, A.Super):
                home = self._home(scope)
                this = self.var_getter("this", scope)
                name = t.name

                def sset(f):
                    v = val(f)
                    rt.set_prop(None, name, v, start=home.obj.base, this=this(f))
                    return v
                return sset
            obj = self.compile_expr(t.obj, scope)
            nmf = (lambda f, n=t.name: n) if t.dyn is None else (lambda f, ev=self.compile_expr(t.dyn, scope): rt.to_str(ev(f)))
            if op == ":=":
                def mset(f):
                    o = obj(f)
                    n = nmf(f)
                    v = val(f)
                    rt.set_prop(o, n, v)
                    return v
                return mset

            def mcomp(f):
                o = obj(f)
                n = nmf(f)
                if binop == "??":
                    try:
                        cur = rt.get_prop(o, n)
                    except AhkThrow:
                        cur = UNSET
                    if cur is not UNSET:
                        return cur
                    v = val(f)
                else:
                    cur = rt.get_prop(o, n)
                    v = self._apply(binop, cur, val(f))
                rt.set_prop(o, n, v)
                return v
            return mcomp
        if isinstance(t, A.Index) and isinstance(t.obj, A.Member) and not isinstance(t.obj.obj, A.Super):
            base = self.compile_expr(t.obj.obj, scope)
            nmf = self._member_name(t.obj, scope)
            args = self.compile_args(t.args, scope, False)

            def pset(f):
                o = base(f)
                n = nmf(f)
                a = args(f)
                if op == ":=":
                    v = val(f)
                else:
                    v = self._apply(binop, rt.get_prop(o, n, a), val(f))
                rt.set_prop(o, n, v, a)
                return v
            return pset
        if isinstance(t, A.Index):
            obj = self.compile_expr(t.obj, scope)
            args = self.compile_args(t.args, scope, False)
            if op == ":=":
                def iset(f):
                    o = obj(f)
                    a = args(f)
                    v = val(f)
                    rt.set_item(o, v, a)
                    return v
                return iset

            def icomp(f):
                o = obj(f)
                a = args(f)
                if binop == "??":
                    try:
                        cur = rt.get_item(o, a)
                    except AhkThrow:
                        cur = UNSET
                    if cur is not UNSET:
                        return cur
                    v = val(f)
                else:
                    v = self._apply(binop, rt.get_item(o, a), val(f))
                rt.set_item(o, v, a)
                return v
            return icomp
        raise AhkSyntaxError("Invalid assignment target", e.file, e.line)

    def _apply(self, binop, cur, rhs):
        rt = self.rt
        if binop == ".":
            return concat(rt, cur, rhs)
        return arith(rt, binop, cur, rhs)

    def _compound(self, getter, setter, val, binop):
        rt = self.rt
        if binop == ".":
            def cc(f):
                cur = getter(f)
                v = concat(rt, cur, val(f))
                setter(f, v)
                return v
            return cc

        def comp(f):
            cur = getter(f)
            v = arith(rt, binop, cur, val(f))
            setter(f, v)
            return v
        return comp

    def e_IncDec(self, e, scope):
        rt = self.rt
        delta = 1 if e.op == "++" else -1
        prefix = e.prefix
        t = e.target
        if isinstance(t, A.Var):
            getter = self.var_getter(t.name, scope)
            setter = self.var_setter(t.name, scope)
        elif isinstance(t, A.Member):
            obj = self.compile_expr(t.obj, scope)
            name = t.name
            holder = {}

            def getter(f):
                o = obj(f)
                holder["o"] = o
                return rt.get_prop(o, name)

            def setter(f, v):
                rt.set_prop(holder["o"], name, v)
        elif isinstance(t, A.Index):
            obj = self.compile_expr(t.obj, scope)
            args = self.compile_args(t.args, scope, False)
            holder = {}

            def getter(f):
                o = obj(f)
                a = args(f)
                holder["o"], holder["a"] = o, a
                return rt.get_item(o, a)

            def setter(f, v):
                rt.set_item(holder["o"], v, holder["a"])
        elif isinstance(t, A.DynVar):
            find = self.dyn_resolver(scope)
            nm = self._dyn_name(t.parts, scope)
            holder = {}

            def getter(f):
                c = find(f, nm(f))
                holder["c"] = c
                if c is None or c.value is UNSET:
                    throw("UnsetError", "This variable has not been assigned a value.")
                return c.value

            def setter(f, v):
                holder["c"].value = v
        else:
            raise AhkSyntaxError("Invalid ++/-- target", e.file, e.line)

        def incdec(f):
            cur = getter(f)
            if type(cur) is int:
                new = wrap(cur + delta)
                old = cur
            else:
                old = rt.to_num(cur)
                new = arith(rt, "+", old, delta)
            setter(f, new)
            return new if prefix else old
        return incdec

    # ================================================================== statements
    def compile_block(self, stmts, scope, top_level=False, func_body=False):
        rt = self.rt
        compiled = []
        labels = {}
        pending_label = None
        for s in stmts:
            if isinstance(s, A.Label):
                labels[s.name.lower()] = len(compiled)
                pending_label = s.name
                continue
            if isinstance(s, (A.FuncDef,)) and scope.kind == "func":
                self._compile_nested_def(s, scope)
                pending_label = None
                continue
            if isinstance(s, (A.While, A.Loop, A.For)) and pending_label:
                s.label = pending_label
            pending_label = None
            fn = self.compile_stmt(s, scope)
            if fn is not None:
                compiled.append(fn)
        if labels and self.v1:
            items = compiled
            if top_level:
                rt.v1_block = (items, labels)
                rt.v1_block_labels = labels
            stack = rt.v1_local_labels

            def run_v1_labels(f):
                entry = (items, labels, f)
                stack.append(entry)
                try:
                    rt.v1_run_from(items, labels, 0, f, catch_return=False)
                finally:
                    stack.pop()
            return run_v1_labels
        if labels:
            items = compiled

            def run_labels(f):
                i = 0
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
            return run_labels
        if not compiled:
            return lambda f: None
        if len(compiled) == 1:
            return compiled[0]
        items = tuple(compiled)

        def run(f):
            for s in items:
                s(f)
        return run

    def _compile_nested_def(self, s, scope):
        cf = None
        for slot, sub, caps in scope.cf.nested_inits:
            if sub.name.lower() == s.name.lower() and sub.body is None:
                cf = sub
                break
        if cf is None:
            return
        subscope = self.compile_func(s, cf, scope)
        for i, (slot, sub, caps) in enumerate(scope.cf.nested_inits):
            if sub is cf:
                scope.cf.nested_inits[i] = (slot, sub, subscope.capture_list)

    def compile_stmt(self, s, scope):
        m = getattr(self, "s_" + type(s).__name__, None)
        if m is None:
            raise AhkSyntaxError(f"Unsupported statement {type(s).__name__}", s.file, s.line)
        fn = m(s, scope)
        if fn is None:
            return None
        rt = self.rt
        line = s.line
        file = s.file or rt.file

        log = rt.line_log
        mono = time.monotonic

        def stmt(f):
            rt.line = line
            rt.file = file
            if rt.thread.settings.list_lines:
                log.append((file, line, mono()))
            if rt.pending:
                rt.check_interrupts()
            fn(f)
        return stmt

    def s_ExprStmt(self, s, scope):
        ev = self.compile_expr(s.expr, scope)
        return ev

    def s_Block(self, s, scope):
        return self.compile_block(s.body, scope)

    def s_Nop(self, s, scope):
        return None

    def s_Label(self, s, scope):
        return None

    def s_FuncDef(self, s, scope):
        return None

    def s_ClassDef(self, s, scope):
        raise AhkSyntaxError("Classes must be defined at the top level or inside another class.", s.file, s.line)

    def s_Directive(self, s, scope):
        return None

    def s_If(self, s, scope):
        c = self.compile_expr(s.cond, scope)
        then = self.compile_body(s.then, scope)
        orelse = self.compile_body(s.orelse, scope) if s.orelse is not None else None
        if orelse is None:
            def if_(f):
                if to_bool(c(f)):
                    then(f)
            return if_

        def ifelse(f):
            if to_bool(c(f)):
                then(f)
            else:
                orelse(f)
        return ifelse

    def compile_body(self, s, scope):
        if isinstance(s, A.Block):
            return self.compile_block(s.body, scope)
        return self.compile_stmt(s, scope)

    def _loop_runner(self, s, scope, iterate):
        """Common loop machinery: A_Index, Break/Continue (with labels), Until."""
        rt = self.rt
        body = self.compile_body(s.body, scope)
        until = self.compile_expr(s.until, scope) if s.until is not None else None
        label = s.label.lower() if s.label else None
        orelse = self.compile_body(s.orelse, scope) if getattr(s, "orelse", None) is not None else None

        def run(f):
            th = rt.thread
            saved = th.loop
            li = LoopInfo()
            li.field = saved.field
            li.read_line = saved.read_line
            li.file = saved.file
            li.reg = saved.reg
            li.out_file = saved.out_file
            th.loop = li
            iterations = 0
            try:
                for _ in iterate(f, li):
                    iterations += 1
                    try:
                        body(f)
                    except BreakEx as b:
                        if b.label is None or b.label.lower() == label:
                            break
                        raise
                    except ContinueEx as c:
                        if not (c.label is None or c.label.lower() == label):
                            raise
                    if until is not None and to_bool(until(f)):
                        break
            finally:
                th.loop = saved
            if iterations == 0 and orelse is not None:
                orelse(f)
        return run

    def s_While(self, s, scope):
        cond = self.compile_expr(s.cond, scope)

        def iterate(f, li):
            i = 1
            while True:
                li.index = i
                if not to_bool(cond(f)):
                    return
                yield i
                i += 1
        return self._loop_runner(s, scope, iterate)

    def s_Loop(self, s, scope):
        rt = self.rt
        kind = s.kind
        args = [self.compile_expr(a, scope) if a is not None else None for a in s.args]
        from .lib import loops
        if kind == "count":
            cnt = args[0] if args else None

            def iterate(f, li):
                if cnt is None:
                    i = 1
                    while True:
                        li.index = i
                        yield i
                        i += 1
                else:
                    n = rt.to_int(cnt(f)) if True else 0
                    for i in range(1, n + 1):
                        li.index = i
                        yield i
            return self._loop_runner(s, scope, iterate)
        iterate = loops.make_iterator(rt, kind, args)
        return self._loop_runner(s, scope, iterate)

    def s_For(self, s, scope):
        rt = self.rt
        it = self.compile_expr(s.iterable, scope)
        n = len(s.vars)
        setters = [self.var_setter(v, scope) if v else None for v in s.vars]
        cells = [self.var_cell(v, scope) if v else None for v in s.vars]

        def iterate(f, li):
            obj = it(f)
            backups = [(c(f), c(f).value) if c else None for c in cells]
            try:
                i = 1
                for vals in rt.enumerate(obj, n):
                    li.index = i
                    for j, st in enumerate(setters):
                        if st is not None and j < len(vals):
                            st(f, vals[j])
                    yield i
                    i += 1
            finally:
                for b in backups:
                    if b is not None:
                        b[0].value = b[1]
        return self._loop_runner(s, scope, iterate)

    def s_Try(self, s, scope):
        rt = self.rt
        body = self.compile_body(s.body, scope)
        catches = []
        for classes, var, cbody in s.catches:
            cls_fns = [self.compile_expr(c, scope) for c in classes]
            setter = self.var_setter(var, scope) if var else None
            catches.append((cls_fns, setter, self.compile_body(cbody, scope)))
        orelse = self.compile_body(s.orelse, scope) if s.orelse is not None else None
        final = self.compile_body(s.final, scope) if s.final is not None else None
        bare_try = not s.catches and s.final is None
        err_proto = lambda: CLASSES["Error"].prototype

        def matches(f, value, cls_fns):
            if not cls_fns:
                return isinstance(value, AhkObject) and value.has_base(err_proto())
            for cf in cls_fns:
                c = cf(f)
                p = c.own("Prototype") if isinstance(c, AhkObject) else None
                if p is None:
                    throw("TypeError", "Invalid class.")
                proto = p.value
                if isinstance(value, AhkObject):
                    if value.has_base(proto):
                        return True
                else:
                    b = rt.base_of(value)
                    if b is proto or b.has_base(proto):
                        return True
            return False

        def run(f):
            try:
                try:
                    body(f)
                except AhkThrow as ex:
                    value = ex.value
                    for cls_fns, setter, cbody in catches:
                        if matches(f, value, cls_fns):
                            if setter:
                                setter(f, value)
                            cbody(f)
                            break
                    else:
                        if bare_try and isinstance(value, AhkObject) and value.has_base(err_proto()):
                            return
                        raise
                    return
                except (RecursionError, OSError, ValueError, KeyError, IndexError, AttributeError, TypeError) as ex:
                    err = new_error("Error", f"{type(ex).__name__}: {ex}")
                    for cls_fns, setter, cbody in catches:
                        if matches(f, err, cls_fns):
                            if setter:
                                setter(f, err)
                            cbody(f)
                            break
                    else:
                        if bare_try:
                            return
                        raise AhkThrow(err)
                    return
                if orelse is not None:
                    orelse(f)
            finally:
                if final is not None:
                    final(f)
        return run

    def s_Throw(self, s, scope):
        rt = self.rt
        if s.expr is None:
            def throw_default(f):
                raise AhkThrow(new_error("Error", "An exception was thrown."))
            return throw_default
        ev = self.compile_expr(s.expr, scope)

        def throw_(f):
            raise AhkThrow(ev(f))
        return throw_

    def s_Return(self, s, scope):
        if s.expr is None:
            def ret(f):
                raise ReturnEx("")
            return ret
        ev = self.compile_expr(s.expr, scope)

        def retv(f):
            raise ReturnEx(ev(f))
        return retv

    def s_Break(self, s, scope):
        label = s.label

        def brk(f):
            raise BreakEx(label)
        return brk

    def s_Continue(self, s, scope):
        label = s.label

        def cont(f):
            raise ContinueEx(label)
        return cont

    def s_Goto(self, s, scope):
        rt = self.rt
        if isinstance(s.label, str):
            label = s.label

            def goto(f):
                raise GotoEx(label)
            return goto
        ev = self.compile_expr(s.label, scope)

        def goto_dyn(f):
            raise GotoEx(rt.to_str(ev(f)))
        return goto_dyn

    def s_Switch(self, s, scope):
        rt = self.rt
        subject = self.compile_expr(s.subject, scope) if s.subject is not None else None
        casesense = self.compile_expr(s.casesense, scope) if s.casesense is not None else None
        cases = [([self.compile_expr(x, scope) for x in exprs], self.compile_body(body, scope)) for exprs, body in s.cases]
        default = self.compile_body(s.default, scope) if s.default is not None else None

        def eq(sv, cv, mode):
            if mode is None:
                if isinstance(sv, AhkObject) or isinstance(cv, AhkObject):
                    return sv is cv
                if not (type(sv) is str and type(cv) is str):
                    ns = sv if type(sv) is not str else str_to_number(sv)
                    nc = cv if type(cv) is not str else str_to_number(cv)
                    if ns is not None and nc is not None:
                        return ns == nc
                return rt.to_str(sv) == rt.to_str(cv)
            a, b = rt.to_str(sv), rt.to_str(cv)
            if mode == "on":
                return a == b
            return a.lower() == b.lower()

        def run(f):
            if subject is None:
                for exprs, body in cases:
                    for x in exprs:
                        if to_bool(x(f)):
                            body(f)
                            return
                if default:
                    default(f)
                return
            sv = subject(f)
            mode = None
            if casesense is not None:
                cs = casesense(f)
                cs_s = rt.to_str(cs).lower() if not isinstance(cs, (int, float)) else ("on" if cs else "off")
                mode = "on" if cs_s in ("on", "1") else "off"
                if isinstance(sv, AhkObject):
                    throw("TypeError", type_error_msg("String", sv))
            for exprs, body in cases:
                for x in exprs:
                    if eq(sv, x(f), mode):
                        body(f)
                        return
            if default:
                default(f)
        return run

    def s_Decl(self, s, scope):
        rt = self.rt
        fns = []
        for name, init in s.items:
            if init is None:
                continue
            if isinstance(init, tuple) and init[0] == "compound":
                fns.append(self.compile_expr(init[1], scope))
                continue
            ev = self.compile_expr(init, scope)
            if s.kind == "static" and scope.kind == "func":
                cell = scope.statics[name.lower()]
                done = [False]

                def sinit(f, cell=cell, ev=ev, done=done):
                    if not done[0]:
                        done[0] = True
                        cell.value = ev(f)
                fns.append(sinit)
            else:
                setter = self.var_setter(name, scope)
                fns.append(lambda f, setter=setter, ev=ev: setter(f, ev(f)))
        if not fns:
            return None
        if len(fns) == 1:
            return fns[0]

        def run(f):
            for fn in fns:
                fn(f)
        return run

    def s_HotkeyDef(self, s, scope):
        raise AhkSyntaxError("Hotkeys and hotstrings must be defined at the top level.", s.file, s.line)

    s_HotstringDef = s_HotkeyDef

    # ================================================================== hotkeys
    def _compile_hot(self, node):
        if isinstance(node, A.Directive):
            if node.name.lower() == "hotif" and node.expr is not None:
                cf = CompiledFunc(self.rt, "")
                fd = A.FuncDef("", [A.Param("ThisHotkey", False, None, True, False)],
                               A.Block([A.Return(node.expr, line=node.line, file=node.file)]), False, True, False, "hotif",
                               line=node.line, file=node.file)
                self.compile_func(fd, cf, None)
                return ("directive", node, UserFunc(cf))
            return ("directive", node, None)
        if node.body is None:
            return ("hot", node, None)
        cf = CompiledFunc(self.rt, getattr(node, "keys", [""])[0] if isinstance(node, A.HotkeyDef) else ":" + node.options + ":" + node.trigger)
        fd = A.FuncDef(cf.name, [A.Param("ThisHotkey", False, None, True, False)], node.body, False, False, False, "hotkey",
                       line=node.line, file=node.file)
        self.compile_func(fd, cf, None)
        return ("hot", node, UserFunc(cf))

    # ================================================================== classes
    def _declare_class(self, cd, outer: AhkClass | None = None):
        rt = self.rt
        full = cd.name if outer is None else f"{outer.name}.{cd.name}"
        proto = AhkObject(None)
        proto.define_value("__Class", full)
        cls = AhkClass(full, None, proto)
        if outer is None:
            key = cd.name.lower()
            if key in rt.consts:
                raise AhkSyntaxError("Duplicate class definition.", cd.file, cd.line, cd.name)
            cell = self._gcell(cd.name)
            cell.value = cls
            cell.scope = "const"
            rt.consts.add(key)
        self.class_defs.append((cd, cls))
        self.pending_bases.append((cd, cls, outer))
        cd._cls = cls
        for m in cd.members:
            if isinstance(m, A.ClassDef):
                sub = self._declare_class(m, cls)
                cls.define_value(m.name, sub)
        return cls

    def _resolve_bases(self):
        rt = self.rt
        for cd, cls, outer in self.pending_bases:
            if cd.extends:
                first = cd.extends[0].lower()
                cell = rt.globals.get(first)
                parent = cell.value if cell is not None and isinstance(cell.value, AhkClass) else CLASSES.get(cd.extends[0])
                if parent is None:
                    for n, c in CLASSES.items():
                        if n.lower() == first:
                            parent = c
                            break
                for part in cd.extends[1:]:
                    p = parent.own(part) if parent else None
                    parent = p.value if p else None
                if not isinstance(parent, AhkClass):
                    raise AhkSyntaxError("Unknown class.", cd.file, cd.line, ".".join(cd.extends))
            else:
                parent = CLASSES["Object"]
            cls.base = parent
            cls.prototype.base = parent.prototype
        # lazy static initialization, base classes first
        for cd, cls, outer in self.pending_bases:
            self._register_class_init(cd, cls)

    def _register_class_init(self, cd, cls):
        rt = self.rt
        static_init = getattr(cd, "_static_init", None)

        def init():
            parent = cls.base
            if isinstance(parent, AhkClass):
                rt.class_ref(parent)
            if static_init is not None:
                static_init.call([cls])
            # static __New
            p = cls.own("__New")
            if p is not None and p.call is not None:
                rt.call(p.call, [cls])
            for m in cd.members:
                if isinstance(m, A.ClassDef):
                    rt.class_ref(m._cls)
        rt.class_inits[id(cls)] = init

    def _build_class(self, cd: A.ClassDef, cls: AhkClass):
        rt = self.rt
        proto = cls.prototype
        inst_vars = []
        static_vars = []
        for m in cd.members:
            if isinstance(m, A.FuncDef):
                target = cls if m.is_static else proto
                home = Home()
                home.obj = target
                cf = CompiledFunc(rt, f"{cls.name}.{'' if not m.is_static else ''}{m.name}" if not m.is_static else f"{cls.name}.{m.name}")
                cf.name = f"{cls.name}.Prototype.{m.name}" if not m.is_static else f"{cls.name}.{m.name}"
                self.compile_func(m, cf, None, is_method=True, home=home)
                target.define_method(m.name, UserFunc(cf))
            elif isinstance(m, A.PropDef):
                target = cls if m.is_static else proto
                home = Home()
                home.obj = target
                g = s = None
                if m.getter is not None:
                    cf = CompiledFunc(rt, f"{cls.name}.Prototype.{m.name}.Get" if not m.is_static else f"{cls.name}.{m.name}.Get")
                    self.compile_func(m.getter, cf, None, is_method=True, home=home)
                    g = UserFunc(cf)
                if m.setter is not None:
                    cf = CompiledFunc(rt, f"{cls.name}.Prototype.{m.name}.Set" if not m.is_static else f"{cls.name}.{m.name}.Set")
                    self.compile_func(m.setter, cf, None, is_method=True, home=home)
                    s = UserFunc(cf)
                target.define_prop(m.name, get=g, set=s)
            elif isinstance(m, A.ClassVar):
                (static_vars if m.is_static else inst_vars).append(m)
        if inst_vars:
            home = Home()
            home.obj = proto
            stmts = [A.ExprStmt(A.MethodCall(A.Super(), "__Init", None, [], False, line=cd.line, file=cd.file), line=cd.line, file=cd.file)]
            stmts += [self._var_init_stmt(v) for v in inst_vars]
            fd = A.FuncDef("__Init", [], A.Block(stmts), False, False, True, "init", line=cd.line, file=cd.file)
            cf = CompiledFunc(rt, f"{cls.name}.Prototype.__Init")
            self.compile_func(fd, cf, None, is_method=True, home=home)
            proto.define_method("__Init", UserFunc(cf))
        if static_vars:
            home = Home()
            home.obj = cls
            stmts = [self._var_init_stmt(v) for v in static_vars]
            fd = A.FuncDef("__Init", [], A.Block(stmts), True, False, True, "init", line=cd.line, file=cd.file)
            cf = CompiledFunc(rt, f"{cls.name}.__Init")
            self.compile_func(fd, cf, None, is_method=True, home=home)
            cd._static_init = UserFunc(cf)

    def _var_init_stmt(self, v: A.ClassVar):
        loc = {"line": v.line, "file": v.file}
        parts = v.name.split(".")
        target = A.This(**loc)
        for p in parts[:-1]:
            target = A.Member(target, p, None, **loc)
        target = A.Member(target, parts[-1], None, **loc)
        value = v.value if v.value is not None else A.Str("", **loc)
        return A.ExprStmt(A.Assign(":=", target, value, **loc), **loc)


class _BivarCell:
    """A Cell-like view of a built-in variable (for &A_Var or dynamic access)."""
    __slots__ = ("getter", "setter", "name", "scope")

    def __init__(self, getter, setter, name):
        self.getter = getter
        self.setter = setter
        self.name = name
        self.scope = "builtin"

    @property
    def value(self):
        return self.getter()

    @value.setter
    def value(self, v):
        if self.setter is None:
            throw("Error", "This variable is read-only.", self.name)
        self.setter(v)
