"""Compiler (AST -> Python closures) and the core runtime (calls, properties, operators).

Execution model mirrors AutoHotkey: one script thread of control with
pseudo-threads.  Hotkeys, timers and GUI events are queued and run as new
threads that interrupt the current one at statement boundaries (or while it
sleeps), exactly where AutoHotkey checks its message queue.
"""
from __future__ import annotations

import math
import os
import re
import sys
import threading
import time

from . import ast as A
from . import objects as O
from .errors import (AhkSyntaxError, AhkThrow, BreakEx, ContinueEx, ExitAppEx, ExitThread, GotoEx,
                     ReturnEx)
from .objects import (AhkArray, AhkClass, AhkMap, AhkObject, BoundFunc, BuiltinFunc, Cell, CLASSES,
                      FuncBase, VarRef, new_error, throw, type_error_msg, value_text)
from .values import UNSET, fmt_float, str_to_number, to_bool, type_name, wrap

VERSION = "2.0.31"


# ====================================================================== functions

class UserFunc(FuncBase):
    __slots__ = ("fdef", "free", "outer_this", "owner")
    native_type = "Func"

    def __init__(self, fdef: "CompiledFunc", free=(), owner=None):
        super().__init__(CLASSES["Closure" if fdef.is_closure else "Func"].prototype)
        self.fdef = fdef
        self.free = free
        self.owner = owner

    @property
    def name(self):
        return self.fdef.name

    def type_name(self):
        return "Closure" if self.fdef.is_closure else "Func"

    def call(self, args):
        return self.fdef.invoke(self, args)

    def min_params(self):
        return self.fdef.min_params

    def max_params(self):
        return self.fdef.max_params

    def is_variadic(self):
        return self.fdef.variadic

    def is_byref(self, i):
        p = self.fdef.params
        return 0 <= i < len(p) and p[i].byref

    def is_optional(self, i):
        p = self.fdef.params
        return 0 <= i < len(p) and p[i].optional or i >= len(p) and self.fdef.variadic


class Frame:
    __slots__ = ("cells", "free", "func", "this", "args")

    def __init__(self, cells, free, func):
        self.cells = cells
        self.free = free
        self.func = func


class CParam:
    __slots__ = ("name", "byref", "optional", "default", "slot", "variadic")

    def __init__(self, name, byref, optional, default, slot, variadic):
        self.name = name
        self.byref = byref
        self.optional = optional
        self.default = default
        self.slot = slot
        self.variadic = variadic


class CompiledFunc:
    def __init__(self, rt, name):
        self.rt = rt
        self.name = name
        self.params: list[CParam] = []
        self.variadic_slot = None
        self.nlocals = 0
        self.local_names: list[str] = []
        self.body = None
        self.min_params = 0
        self.max_params = 0
        self.variadic = False
        self.is_closure = False
        self.nested_inits = []        # (slot, CompiledFunc, capture list) created at entry
        self.file = ""
        self.line = 0
        self.statics: dict[str, Cell] = {}
        self.static_inits_done: set = set()
        self.is_method = False

    def invoke(self, fobj: UserFunc, args):
        rt = self.rt
        n = len(args)
        params = self.params
        np = len(params)
        if n > np and not self.variadic:
            while n > np and args[n - 1] is UNSET:
                n -= 1
            if n > np:
                throw("Error", "Too many parameters passed to function.", self.name, what=self.name)
        cells = [Cell(nm) for nm in self.local_names]
        frame = Frame(cells, fobj.free, fobj)
        for i, p in enumerate(params):
            v = args[i] if i < n else UNSET
            if v is UNSET:
                if not p.optional:
                    throw("Error", "Missing a required parameter.", p.name, what=self.name)
                if p.default is not None:
                    cells[p.slot].value = p.default(frame)
                continue
            if p.byref and type(v) is VarRef:
                cells[p.slot] = v.cell
            else:
                cells[p.slot].value = v
        if self.variadic_slot is not None:
            rest = args[np:n] if n > np else []
            cells[self.variadic_slot].value = AhkArray(None, rest)
        for slot, cf, caps in self.nested_inits:
            free = [cells[idx] if kind == "l" else frame.free[idx] for kind, idx in caps]
            cells[slot].value = UserFunc(cf, free)
        rt.depth += 1
        if rt.depth > 1500:
            rt.depth = 0
            throw("Error", "Recursion limit exceeded.")
        rt.call_stack.append(self)
        try:
            self.body(frame)
        except ReturnEx as r:
            return r.value
        finally:
            rt.call_stack.pop()
            rt.depth -= 1
        return ""


# ====================================================================== scopes

class Scope:
    def __init__(self, kind, parent=None, fdef=None, is_method=False):
        self.kind = kind            # 'global' | 'func'
        self.parent = parent
        self.locals: dict[str, int] = {}
        self.local_names: list[str] = []
        self.declared_global: set[str] = set()
        self.declared_local: set[str] = set()
        self.statics: dict[str, Cell] = {}
        self.assume_global = False
        self.assume_static = False
        self.captures: dict[str, int] = {}
        self.capture_list: list[tuple[str, int]] = []
        self.cf: CompiledFunc | None = None
        self.is_method = is_method
        self.labels: set[str] = set()

    def add_local(self, name):
        key = name.lower()
        if key not in self.locals:
            self.locals[key] = len(self.local_names)
            self.local_names.append(name)
        return self.locals[key]

    def capture(self, key):
        """Resolve `key` in an enclosing function; returns a free index or None."""
        if key in self.captures:
            return self.captures[key]
        p = self.parent
        if p is None or p.kind != "func":
            return None
        if key in p.locals and key not in p.declared_global:
            src = ("l", p.locals[key])
        elif key in p.statics:
            return None
        else:
            idx = p.capture(key)
            if idx is None:
                return None
            src = ("f", idx)
        i = len(self.capture_list)
        self.capture_list.append(src)
        self.captures[key] = i
        return i


def _assigned_names(stmts, out: set, declared: dict):
    """Collect names assigned in a function body (making them local), excluding nested functions."""
    def visit_expr(e):
        if e is None:
            return
        if isinstance(e, tuple):
            for x in e:
                visit_expr(x)
            return
        if isinstance(e, A.Assign):
            if isinstance(e.target, A.Var):
                out.add(e.target.name.lower())
            visit_expr(e.target)
            visit_expr(e.value)
            return
        if isinstance(e, A.IncDec):
            if isinstance(e.target, A.Var):
                out.add(e.target.name.lower())
            visit_expr(e.target)
            return
        if isinstance(e, A.Ref):
            if isinstance(e.target, A.Var):
                out.add(e.target.name.lower())
            return
        if isinstance(e, A.FuncExpr):
            return
        if isinstance(e, A.Node):
            for f in e.fields:
                v = getattr(e, f)
                if isinstance(v, list):
                    for x in v:
                        visit_expr(x)
                elif isinstance(v, (A.Node, tuple)):
                    visit_expr(v)

    def visit(s):
        if s is None:
            return
        if isinstance(s, A.FuncDef):
            if s.name:
                out.add(s.name.lower())
            return
        if isinstance(s, A.ClassDef):
            return
        if isinstance(s, A.Decl):
            for name, init in s.items:
                declared.setdefault(s.kind, set()).add(name.lower())
                visit_expr(init[1] if isinstance(init, tuple) else init)
            if not s.items:
                declared.setdefault("assume_" + s.kind, True)
            return
        if isinstance(s, A.For):
            for v in s.vars:
                if v:
                    out.add(v.lower())
            visit_expr(s.iterable)
            visit(s.body)
            visit_expr(s.until)
            return
        if isinstance(s, A.Try):
            visit(s.body)
            for classes, var, body in s.catches:
                if var:
                    out.add(var.lower())
                visit(body)
            visit(s.orelse)
            visit(s.final)
            return
        if isinstance(s, A.Block):
            for x in s.body:
                visit(x)
            return
        if isinstance(s, A.If):
            visit_expr(s.cond); visit(s.then); visit(s.orelse)
            return
        if isinstance(s, (A.While,)):
            visit_expr(s.cond); visit(s.body); visit_expr(s.until)
            return
        if isinstance(s, A.Loop):
            for a in s.args:
                visit_expr(a)
            visit(s.body); visit_expr(s.until)
            return
        if isinstance(s, A.Switch):
            visit_expr(s.subject)
            for exprs, body in s.cases:
                for e in exprs:
                    visit_expr(e)
                visit(body)
            visit(s.default)
            return
        if isinstance(s, (A.HotkeyDef, A.HotstringDef)):
            return
        if isinstance(s, A.ExprStmt):
            visit_expr(s.expr)
            return
        if isinstance(s, (A.Return, A.Throw)):
            visit_expr(s.expr)
            return

    for s in stmts:
        visit(s)


# ====================================================================== thread state

class ThreadSettings:
    """Per-thread settings (global_struct): copied from the auto-execute defaults."""
    __slots__ = ("title_match_mode", "title_match_speed", "detect_hidden_windows", "detect_hidden_text",
                 "send_mode", "key_delay", "key_duration", "key_delay_play", "key_duration_play",
                 "mouse_delay", "mouse_delay_play", "default_mouse_speed", "coord_mode", "string_case_sense",
                 "win_delay", "control_delay", "send_level", "store_capslock", "critical", "priority",
                 "last_found", "reg_view", "file_encoding", "thread_interruptible", "peek_frequency",
                 "allow_timers", "default_gui", "list_lines")

    def __init__(self):
        self.title_match_mode = 2
        self.title_match_speed = "Fast"
        self.detect_hidden_windows = False
        self.detect_hidden_text = True
        self.send_mode = "Input"
        self.key_delay = 10
        self.key_duration = -1
        self.key_delay_play = -1
        self.key_duration_play = -1
        self.mouse_delay = 10
        self.mouse_delay_play = -1
        self.default_mouse_speed = 2
        self.coord_mode = {"ToolTip": "Client", "Pixel": "Client", "Mouse": "Client", "Caret": "Client", "Menu": "Client"}
        self.string_case_sense = "Off"
        self.win_delay = 100
        self.control_delay = 20
        self.send_level = 0
        self.store_capslock = True
        self.critical = 0
        self.priority = 0
        self.last_found = 0
        self.reg_view = 64
        self.file_encoding = "CP0"        # AutoHotkey default (g.Encoding = CP_ACP): no BOM; UTF-8 on Linux
        self.thread_interruptible = True
        self.peek_frequency = 5
        self.allow_timers = True
        self.default_gui = None
        self.list_lines = 1

    def copy(self):
        n = ThreadSettings()
        for k in self.__slots__:
            v = getattr(self, k)
            setattr(n, k, dict(v) if isinstance(v, dict) else v)
        return n


class LoopInfo:
    __slots__ = ("index", "field", "read_line", "file", "reg", "out_file")

    def __init__(self):
        self.index = 0
        self.field = UNSET
        self.read_line = UNSET
        self.file = None
        self.reg = None
        self.out_file = None


class ScriptThread:
    __slots__ = ("settings", "loop", "event_info", "hotkey", "priority", "start", "name", "is_critical")

    def __init__(self, settings, name=""):
        self.settings = settings
        self.loop = LoopInfo()
        self.event_info = 0
        self.hotkey = ""
        self.priority = 0
        self.start = time.monotonic()
        self.name = name
        self.is_critical = False


# ====================================================================== runtime

class Runtime:
    def __init__(self, script_path: str, args: list[str], options=None):
        O.RT = self
        self.options = options or {}
        self.script_path = os.path.abspath(script_path) if script_path != "*" else "*"
        self.script_args = args
        self.globals: dict[str, Cell] = {}
        self.consts: set[str] = set()        # function/class names (read-only)
        self.builtins: dict[str, BuiltinFunc] = {}
        self.bivars: dict[str, tuple] = {}   # A_ variables: name -> (getter, setter)
        self.call_stack: list[CompiledFunc] = []
        self.depth = 0
        self.line = 0
        self.file = self.script_path
        self.pending = False
        self.lock = threading.RLock()
        self.events = []                     # queued thread starts
        self.sync_calls = []                 # calls that must run even while Critical (#HotIf evaluation)
        self.main_thread = threading.current_thread()
        self.event_cond = threading.Condition(self.lock)
        self.timers = []
        self.threads: list[ScriptThread] = []
        self.defaults = ThreadSettings()
        self.thread = ScriptThread(self.defaults, "auto-execute")
        self.threads.append(self.thread)
        self.class_inits: dict[int, tuple] = {}
        self.exit_code = 0
        self.persistent = False
        self.exiting = False
        self.on_exit_funcs: list = []
        self.on_error_funcs: list = []
        self.label_table = {}
        self.hotkeys = None
        self.hotstrings = None
        self.backend = None
        self.hotmgr = None
        self.initial_cwd = os.getcwd()
        self.args_array = None
        self.directives = {"ErrorStdOut": None, "MaxThreads": 10, "MaxThreadsPerHotkey": 1,
                           "MaxThreadsBuffer": False, "HotIfTimeout": 1000, "InputLevel": 0,
                           "UseHook": False, "SuspendExempt": False, "NoTrayIcon": False,
                           "Warn": False, "WinActivateForce": False, "SingleInstance": "Prompt",
                           "ClipboardTimeout": 1000}
        self.hotif_criterion = None
        self.files: list[str] = []
        self.included: set[str] = set()
        self.start_time = time.monotonic()
        self.this_hotkey = ""
        self.prior_hotkey = ""
        self.this_hotkey_time = 0.0
        self.prior_hotkey_time = 0.0
        self.end_char = ""
        self.prior_key = ""
        self.last_error = 0
        self.auto_exec_done = False
        self.pending_functions = []
        self.suspended = False
        self.paused = False

    # ------------------------------------------------------------ errors/locations
    def current_location(self):
        return self.file, self.line

    def current_what(self):
        return self.call_stack[-1].name if self.call_stack else ""

    def stack_text(self):
        parts = []
        for cf in reversed(self.call_stack):
            parts.append(f"{cf.file} ({cf.line}) : [{cf.name}]")
        parts.append(f"{self.file} ({self.line}) : [] ")
        return "\n".join(parts) + "\n"

    def unset_error(self, cell: Cell):
        kind = {"global": "global variable", "static": "static variable"}.get(cell.scope, "variable" if cell.scope == "local?" else "local variable")
        if cell.scope == "global":
            msg = "This global variable has not been assigned a value."
        else:
            msg = f"This {kind} has not been assigned a value."
            if cell.scope == "local" and cell.name.lower() in self.globals:
                msg += "\nA global declaration inside the function may be required."
        throw("UnsetError", msg, cell.name)

    # ------------------------------------------------------------ object protocol
    def base_of(self, v):
        t = type(v)
        if t is str:
            return CLASSES["String"].prototype
        if t is int:
            return CLASSES["Integer"].prototype
        if t is float:
            return CLASSES["Float"].prototype
        if isinstance(v, AhkObject):
            return v.base
        return CLASSES["Any"].prototype

    def find_prop(self, v, name):
        if isinstance(v, AhkObject):
            return v.find(name)
        b = self.base_of(v)
        return b.find(name) if b is not None else (None, None)

    def get_prop(self, obj, name, args=(), start=None, this=None):
        if this is None:
            this = obj
        p, owner = start.find(name) if start is not None else self.find_prop(obj, name)
        if p is not None:
            if p.is_value:
                v = p.value
                if args:
                    return self.get_item(v, list(args))
                return v
            if p.get is not None:
                return self.call(p.get, [this, *args])
            if p.call is not None:
                if args:
                    return self.call(p.call, [this, *args])
                return p.call
        meta = (start.find("__Get") if start is not None else self.find_prop(obj, "__Get"))[0]
        if meta is not None and meta.call is not None:
            return self.call(meta.call, [this, name, AhkArray(None, list(args))])
        throw("PropertyError", f'This value of type "{type_name(obj)}" has no property named "{name}".', name)

    def set_prop(self, obj, name, value, args=(), start=None, this=None):
        if this is None:
            this = obj
        p, owner = start.find(name) if start is not None else self.find_prop(obj, name)
        if p is not None:
            if p.is_value:
                if args:
                    return self.set_item(p.value, value, list(args))
                if not isinstance(this, AhkObject):
                    throw("PropertyError", f'This value of type "{type_name(obj)}" has no property named "{name}".', name)
                if owner is this:
                    p.value = value
                else:
                    this.define_value(name, value)
                return value
            if p.set is not None:
                self.call(p.set, [this, value, *args])
                return value
            if p.get is not None:
                throw("PropertyError", "Property is read-only.", name)
        meta = (start.find("__Set") if start is not None else self.find_prop(obj, "__Set"))[0]
        if meta is not None and meta.call is not None:
            self.call(meta.call, [this, name, AhkArray(None, list(args)), value])
            return value
        if not isinstance(this, AhkObject) or args:
            throw("PropertyError", f'This value of type "{type_name(obj)}" has no property named "{name}".', name)
        this.define_value(name, value)
        return value

    def call_method(self, obj, name, args, start=None, this=None):
        if this is None:
            this = obj
        p, owner = start.find(name) if start is not None else self.find_prop(obj, name)
        if p is not None:
            if p.call is not None:
                return self.call(p.call, [this, *args])
            if p.is_value:
                return self.call(p.value, [this, *args])
            if p.get is not None:
                return self.call(self.call(p.get, [this]), list(args))
        meta = (start.find("__Call") if start is not None else self.find_prop(obj, "__Call"))[0]
        if meta is not None and meta.call is not None:
            return self.call(meta.call, [this, name, AhkArray(None, list(args))])
        throw("MethodError", f'This value of type "{type_name(obj)}" has no method named "{name}".', name)

    def call(self, f, args):
        if isinstance(f, FuncBase):
            return f.call(args)
        if isinstance(f, AhkObject):
            return self.call_method(f, "Call", args)
        throw("MethodError", f'This value of type "{type_name(f)}" has no method named "Call".', "Call")

    def get_item(self, obj, args):
        if isinstance(obj, AhkObject):
            p, _ = obj.find("__Item")
            if p is not None and not p.is_value and type(p.get) is not _NativeItem:
                if p.get is not None:
                    return self.call(p.get, [obj, *args])
            r = obj.native_item_get(args)
            if r is not NotImplemented:
                return r
            if p is not None and p.is_value:
                return self.get_item(p.value, args)
        throw("PropertyError", f'This value of type "{type_name(obj)}" has no property named "__Item".', "__Item")

    def set_item(self, obj, value, args):
        if isinstance(obj, AhkObject):
            p, _ = obj.find("__Item")
            if p is not None and not p.is_value and type(p.set) is not _NativeItem:
                if p.set is not None:
                    self.call(p.set, [obj, value, *args])
                    return value
            r = obj.native_item_set(value, args)
            if r is not NotImplemented:
                return value
        throw("PropertyError", f'This value of type "{type_name(obj)}" has no property named "__Item".', "__Item")

    # ------------------------------------------------------------ enumeration
    def enumerate(self, obj, nvars):
        """Yields tuples of nvars values (the For-loop protocol)."""
        if type(obj) is AhkArray and obj.base is CLASSES["Array"].prototype:
            items = obj.items
            i = 0
            while i < len(items):
                v = items[i]
                if nvars <= 1:
                    yield (v,)
                else:
                    yield (i + 1, v)
                i += 1
            return
        if type(obj) is AhkMap and obj.base is CLASSES["Map"].prototype:
            for k, v in obj.sorted_items():
                yield (k, v) if nvars > 1 else (k,)
            return
        if isinstance(obj, FuncBase):
            enum = obj
        elif isinstance(obj, AhkObject) or True:
            enum = self.call_method(obj, "__Enum", [nvars])
        cells = [Cell("") for _ in range(max(nvars, 1))]
        refs = [VarRef(c) for c in cells]
        while True:
            r = self.call(enum, refs[:max(nvars, 1)])
            if not to_bool(r):
                return
            yield tuple(c.value for c in cells)

    # ------------------------------------------------------------ conversions
    def to_str(self, v) -> str:
        t = type(v)
        if t is str:
            return v
        if t is int:
            return str(v)
        if t is float:
            return fmt_float(v)
        if v is UNSET:
            throw("UnsetError", "Parameter has no value.")
        throw("TypeError", type_error_msg("String", v), value_text(v))

    def to_num(self, v):
        t = type(v)
        if t is int or t is float:
            return v
        if t is str:
            n = str_to_number(v)
            if n is not None:
                return n
        throw("TypeError", type_error_msg("Number", v), value_text(v))

    def to_int(self, v) -> int:
        t = type(v)
        if t is int:
            return v
        if t is float:
            return wrap(int(v)) if math.isfinite(v) else 0
        if t is str:
            n = str_to_number(v)
            if type(n) is int:
                return n
            if type(n) is float:
                return wrap(int(n))
        throw("TypeError", type_error_msg("Integer", v), value_text(v))

    # ------------------------------------------------------------ threads & interrupts
    def post(self, fn, priority=0, kind="event", tag=None):
        """Queue fn() to run as a new pseudo-thread at the next interruption point."""
        with self.lock:
            self.events.append((priority, fn, kind, tag))
            self.pending = True
            self.event_cond.notify_all()

    def post_sync(self, fn):
        with self.lock:
            self.sync_calls.append(fn)
            self.pending = True
            self.event_cond.notify_all()

    def _run_sync_calls(self):
        while self.sync_calls:
            with self.lock:
                calls, self.sync_calls = self.sync_calls, []
            for fn in calls:
                fn()

    def check_interrupts(self):
        """Run queued threads/timers that may interrupt the current thread."""
        if self.sync_calls:
            self._run_sync_calls()
        if self.thread.is_critical or not self.thread.settings.thread_interruptible:
            self._fire_due_timers(only_check=True)
            return
        self._fire_due_timers()
        while True:
            with self.lock:
                ev = None
                for i, (prio, fn, kind, tag) in enumerate(self.events):
                    if prio >= self.thread.priority:
                        ev = self.events.pop(i)
                        break
                self.pending = bool(self.events) or bool(self.timers) or bool(self.sync_calls)
            if ev is None:
                return
            self.run_thread(ev[1], ev[0], ev[2])

    def run_thread(self, fn, priority=0, name=""):
        if len(self.threads) > self.directives["MaxThreads"] + 1:
            return
        prev = self.thread
        th = ScriptThread(self.defaults.copy(), name)
        th.priority = priority
        self.thread = th
        self.threads.append(th)
        saved_line, saved_file = self.line, self.file
        saved_stack = self.call_stack
        self.call_stack = []
        saved_depth = self.depth
        self.depth = 0
        try:
            fn()
        except ExitThread:
            pass
        except ExitAppEx:
            raise
        except AhkThrow as e:
            self.unhandled(e.value)
        except RecursionError:
            self.unhandled(new_error("Error", "Recursion limit exceeded."))
        finally:
            self.threads.pop()
            self.thread = prev
            self.line, self.file = saved_line, saved_file
            self.call_stack = saved_stack
            self.depth = saved_depth

    def _fire_due_timers(self, only_check=False):
        if not self.timers or self.paused:
            return
        now = time.monotonic()
        for t in list(self.timers):
            if t.next_due <= now and not t.running and t.enabled:
                if only_check:
                    self.pending = True
                    return
                if t.priority < self.thread.priority:
                    continue
                if not self.thread.settings.allow_timers and False:
                    continue
                t.fire(self)

    def next_timer_due(self):
        due = [t.next_due for t in self.timers if t.enabled and not t.running]
        return min(due) if due else None

    def sleep(self, ms):
        """Sleep while processing events (MsgSleep)."""
        end = time.monotonic() + max(ms, 0) / 1000.0
        if ms < 0:
            self.check_interrupts()
            return
        while True:
            self.check_interrupts()
            now = time.monotonic()
            if now >= end:
                break
            wait = end - now
            nt = self.next_timer_due()
            if nt is not None:
                wait = min(wait, max(nt - now, 0.0005))
            with self.lock:
                if not self.events and not self.sync_calls:
                    self.event_cond.wait(min(wait, 0.25))
            if self.exiting:
                break

    def idle_loop(self):
        """After the auto-execute section: wait for events while the script is persistent."""
        while not self.exiting:
            if not self.is_persistent():
                break
            self.check_interrupts()
            nt = self.next_timer_due()
            wait = 0.5 if nt is None else max(nt - time.monotonic(), 0.0)
            with self.lock:
                if not self.events and not self.sync_calls and wait > 0:
                    self.event_cond.wait(min(wait, 0.5))

    def is_persistent(self):
        if self.persistent:
            return True
        if self.timers and any(t.enabled for t in self.timers):
            return True
        if self.hotkeys is not None and self.hotkeys.hotkeys:
            return True
        if self.hotstrings is not None and self.hotstrings.items:
            return True
        from .lib import guiobj
        if any(g.shown for g in guiobj.GUIS.values()):
            return True
        return bool(self.events)

    def unhandled(self, value):
        """Report an unhandled exception (Script::UnhandledException)."""
        for f in list(self.on_error_funcs):
            try:
                r = self.call(f, [value, "Exit"])
                if to_bool(r) and type(r) in (int, float) and r == -1:
                    return
                if to_bool(r):
                    return
            except AhkThrow:
                pass
        from . import ui
        if isinstance(value, AhkObject) and value.find("Message")[0] is not None:
            msg = value_text(self.get_prop(value, "Message")) if True else ""
            try:
                extra = value_text(self.get_prop(value, "Extra"))
            except AhkThrow:
                extra = ""
            try:
                line = self.get_prop(value, "Line")
                file = self.get_prop(value, "File")
            except AhkThrow:
                line, file = self.line, self.file
        else:
            msg = "Unhandled exception: " + (value_text(value) if not isinstance(value, AhkObject) else f"{type_name(value)} object")
            extra, line, file = "", self.line, self.file
        ui.show_error(self, "Error", msg, extra, file, line)

    # ------------------------------------------------------------ class init
    def prefix_root(self):
        from .prefix import prefix_root
        return prefix_root()

    def class_ref(self, cls):
        info = self.class_inits.pop(id(cls), None)
        if info is not None:
            info()
        return cls


class _NativeItem:
    pass


# ====================================================================== operators

def _num_operand(rt, v, op):
    t = type(v)
    if t is int or t is float:
        return v
    if t is str:
        n = str_to_number(v)
        if n is not None:
            return n
    throw("TypeError", type_error_msg("Number", v), value_text(v))


def arith(rt, op, a, b):
    x = _num_operand(rt, a, op)
    y = _num_operand(rt, b, op)
    tx, ty = type(x), type(y)
    if tx is int and ty is int:
        if op == "+":
            return wrap(x + y)
        if op == "-":
            return wrap(x - y)
        if op == "*":
            return wrap(x * y)
        if op == "/":
            if y == 0:
                throw("ZeroDivisionError", "Divide by zero.")
            return x / y
        if op == "//":
            if y == 0:
                throw("ZeroDivisionError", "Divide by zero.")
            q = abs(x) // abs(y)
            return wrap(q if (x >= 0) == (y >= 0) else -q)
        if op == "**":
            if x == 0 and y < 0:
                throw("ZeroDivisionError", "Divide by zero.")
            if x == 0 and y == 0:
                throw("ValueError", "Invalid value.")  # 0**0 undefined
            if y >= 0:
                return wrap(pow(x, y) if y < 4096 or abs(x) <= 1 else _pow_wrap(x, y))
            return float(x) ** y
        if op in ("|", "^", "&", "<<", ">>", ">>>"):
            if op == "|":
                return x | y
            if op == "^":
                return x ^ y
            if op == "&":
                return x & y
            if op == "<<":
                return wrap(x << (y & 63))
            if op == ">>":
                return x >> (y & 63)
            return wrap((x & 0xFFFFFFFFFFFFFFFF) >> (y & 63))
    # float path
    if op in ("|", "^", "&", "<<", ">>", ">>>", "//"):
        bad = a if tx is float else b
        throw("TypeError", type_error_msg("Integer", x if tx is float else y), value_text(x if tx is float else y))
    fx, fy = float(x), float(y)
    if op == "+":
        return fx + fy
    if op == "-":
        return fx - fy
    if op == "*":
        return fx * fy
    if op == "/":
        if fy == 0.0:
            throw("ZeroDivisionError", "Divide by zero.")
        return fx / fy
    if op == "**":
        if fx == 0.0 and fy < 0:
            throw("ZeroDivisionError", "Divide by zero.")
        if (fx < 0 and math.fmod(fy, 1.0) != 0.0) or (fx == 0.0 and fy == 0.0):
            throw("ValueError", "Invalid value.")
        try:
            return math.pow(fx, fy)
        except OverflowError:
            return math.inf
    raise AssertionError(op)


def _pow_wrap(x, y):
    r = 1
    base = x
    while y:
        if y & 1:
            r = wrap(r * base)
        base = wrap(base * base)
        y >>= 1
    return r


def compare(rt, op, a, b):
    """=, ==, !=, !==, <, >, <=, >= following ExpandExpression."""
    a_obj = isinstance(a, AhkObject)
    b_obj = isinstance(b, AhkObject)
    if op in ("=", "==", "!=", "!=="):
        if a_obj or b_obj:
            eq = a is b
            return int(eq if op in ("=", "==") else not eq)
        ta, tb = type(a), type(b)
        a_pure = ta is int or ta is float
        b_pure = tb is int or tb is float
        if a_pure or b_pure:
            na = a if a_pure else str_to_number(a)
            nb = b if b_pure else str_to_number(b)
            if na is not None and nb is not None:
                eq = na == nb
                return int(eq if op in ("=", "==") else not eq)
        sa = a if ta is str else rt.to_str(a)
        sb = b if tb is str else rt.to_str(b)
        if op in ("=", "!="):
            if rt.thread.settings.string_case_sense == "On" and False:
                eq = sa == sb
            else:
                eq = sa.lower() == sb.lower() if not (sa.isascii() and sb.isascii()) else sa.lower() == sb.lower()
            return int(eq if op == "=" else not eq)
        eq = sa == sb
        return int(eq if op == "==" else not eq)
    # relational
    if a_obj or b_obj:
        throw("TypeError", type_error_msg("Number", a if a_obj else b), value_text(a if a_obj else b))
    na = _num_operand(rt, a, op)
    nb = _num_operand(rt, b, op)
    if op == "<":
        return int(na < nb)
    if op == ">":
        return int(na > nb)
    if op == "<=":
        return int(na <= nb)
    return int(na >= nb)


def concat(rt, a, b):
    ta, tb = type(a), type(b)
    if ta is str and tb is str:
        return a + b
    return _cstr(rt, a) + _cstr(rt, b)


def _cstr(rt, v):
    t = type(v)
    if t is str:
        return v
    if t is int:
        return str(v)
    if t is float:
        return fmt_float(v)
    throw("TypeError", type_error_msg("String", v), value_text(v))
