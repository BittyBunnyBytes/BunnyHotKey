"""Hotkey/hotstring registration and dispatch into script threads (hotkey.cpp, Hotstring class)."""
from __future__ import annotations

import re
import threading
import time

from . import keys as K
from .errors import AhkThrow
from .hotkeys import HookEngine, HotkeySpec, Variant, parse_hotkey
from .objects import AhkObject, FuncBase, throw
from .values import UNSET, to_bool

DEFAULT_END_CHARS = "-()[]{}:;'\"/\\,.?!\n \t"


class Criterion:
    """A #HotIf / HotIf() condition: a callable evaluated in the script thread."""

    def __init__(self, func, text="", kind="expr", wintitle="", wintext=""):
        self.func = func
        self.text = text
        self.kind = kind
        self.wintitle = wintitle
        self.wintext = wintext


class HotManager:
    def __init__(self, rt):
        self.rt = rt
        self.engine = HookEngine(self)
        self.hotstrings = HotstringEngine(self)
        rt.hotkeys = self.engine
        rt.hotstrings = self.hotstrings
        self.criteria: list[Criterion] = []
        self.current_criterion: Criterion | None = None    # for Hotkey()/Hotstring() functions
        self.sync_lock = threading.Lock()

    # ---- called from the hook (backend) thread ----
    def eval_criterion(self, crit: Criterion) -> bool:
        rt = self.rt
        if crit.kind in ("active", "notactive", "exist", "notexist"):
            # evaluated directly, like AHK's built-in criteria
            pass
        done = threading.Event()
        box = [False]

        def job():
            try:
                if crit.kind == "expr":
                    box[0] = to_bool(rt.call(crit.func, [getattr(rt, "pending_hotkey_name", "")]))
                else:
                    from .lib import window
                    fn = {"active": window.WinActive, "notactive": window.WinActive,
                          "exist": window.WinExist, "notexist": window.WinExist}[crit.kind]
                    v = bool(fn(crit.wintitle, crit.wintext))
                    box[0] = v if crit.kind in ("active", "exist") else not v
            except AhkThrow:
                box[0] = False
            except Exception:
                box[0] = False
            finally:
                done.set()
        if threading.current_thread() is rt.main_thread:
            job()
            return box[0]
        rt.post_sync(job)
        if not done.wait(rt.directives["HotIfTimeout"] / 1000.0):
            return False
        return box[0]

    def fire_hotkey(self, hk, variant: Variant):
        rt = self.rt
        if variant.running >= variant.max_threads:
            return
        name = hk.name

        def run():
            variant.running += 1
            rt.prior_hotkey, rt.prior_hotkey_time = rt.this_hotkey, rt.this_hotkey_time
            rt.this_hotkey, rt.this_hotkey_time = name, time.monotonic()
            try:
                rt.call(variant.callback, [name])
            finally:
                variant.running -= 1
        rt.post(run, priority=0, kind="hotkey", tag=name)

    def replay_key(self, code):
        if self.rt.backend is not None:
            self.rt.backend.tap(code)

    # ---- registration (script thread) ----
    def add_hotkey(self, keyname: str, callback, criterion=None, options="", from_script=False):
        spec = parse_hotkey(keyname)
        if spec is None:
            throw("ValueError", "Invalid hotkey.", keyname) if not from_script else throw("Error", "Invalid hotkey.", keyname)
        hk = self.engine.add(spec)
        if spec.passthrough and not hk.spec.passthrough:
            hk.spec.passthrough = True
        crit_func = criterion
        for v in hk.variants:
            if v.criterion is crit_func:
                if callback is not None:
                    v.callback = callback
                self._apply_opts(v, options)
                break
        else:
            if callback is None:
                throw("Error", "Nonexistent hotkey.", keyname)
            v = Variant(callback, crit_func, self.rt.directives["MaxThreadsPerHotkey"],
                        self.rt.directives["InputLevel"], self.rt.directives["SuspendExempt"])
            hk.variants.append(v)
            self._apply_opts(v, options)
        if self.rt.backend is not None:
            self.rt.backend.refresh()
        return hk, v

    def _apply_opts(self, v, options):
        o = options.upper() if isinstance(options, str) else ""
        i = 0
        while i < len(o):
            c = o[i]
            if o.startswith("ON", i):
                v.enabled = True
                i += 2
                continue
            if o.startswith("OFF", i):
                v.enabled = False
                i += 3
                continue
            if c == "T":
                m = re.match(r"T(\d+)", o[i:])
                if m:
                    v.max_threads = int(m.group(1))
                    i += m.end()
                    continue
            if c == "S":
                v.suspend_exempt = not o.startswith("S0", i)
            if c == "I":
                m = re.match(r"I(\d+)", o[i:])
                if m:
                    v.input_level = int(m.group(1))
                    i += m.end()
                    continue
            i += 1


# ====================================================================== hotstrings

class Hotstring:
    def __init__(self, trigger, replacement, callback, opts, criterion):
        self.trigger = trigger
        self.replacement = replacement      # str for auto-replace, None if callback
        self.callback = callback
        self.criterion = criterion
        self.enabled = True
        self.asterisk = False      # *  end char not required
        self.question = False      # ?  may trigger inside a word
        self.backspace = True      # B  (B0 disables)
        self.case = 0              # 0 = conform, 1 = C (case sensitive), 2 = C1 (no conformity)
        self.omit = False          # O  omit end char
        self.raw = False           # R
        self.text = False          # T
        self.execute = False       # X
        self.reset = False         # Z
        self.send_mode = None      # SI/SP/SE
        self.key_delay = None      # K
        self.priority = 0
        self.suspend_exempt = False
        self.input_level = 0
        self.apply(opts)
        self.running = 0

    def apply(self, opts: str):
        o = opts
        i = 0
        while i < len(o):
            c = o[i].upper()
            nxt = o[i + 1] if i + 1 < len(o) else ""
            off = nxt == "0"
            if c == "*":
                self.asterisk = not off
            elif c == "?":
                self.question = not off
            elif c == "B":
                self.backspace = not off
            elif c == "C":
                if nxt == "1":
                    self.case = 2
                    i += 1
                elif off:
                    self.case = 0
                else:
                    self.case = 1
            elif c == "O":
                self.omit = not off
            elif c == "R":
                self.raw = not off
            elif c == "T":
                self.text = not off
            elif c == "X":
                self.execute = not off
            elif c == "Z":
                self.reset = not off
            elif c == "S" and nxt.upper() in ("I", "P", "E"):
                self.send_mode = {"I": "Input", "P": "Play", "E": "Event"}[nxt.upper()]
                i += 1
            elif c == "S":
                self.suspend_exempt = not off
            elif c == "K" or c == "P":
                m = re.match(r"[KP](-?\d+)", o[i:], re.I)
                if m:
                    if c == "K":
                        self.key_delay = int(m.group(1))
                    else:
                        self.priority = int(m.group(1))
                    i += m.end()
                    continue
            if off and c in "*?BOROTXZS":
                i += 1
            i += 1


class HotstringEngine:
    def __init__(self, mgr: HotManager):
        self.mgr = mgr
        self.items: list[Hotstring] = []
        self.buffer = ""
        self.end_chars = DEFAULT_END_CHARS
        self.default_opts = ""
        self.mouse_reset = True
        self.suspended = False
        self.lock = threading.RLock()

    def add(self, opts, trigger, replacement, callback, criterion):
        for h in self.items:
            if h.trigger == trigger and h.criterion is criterion and _same_case_mode(h, opts):
                h.apply(opts)
                if replacement is not None or callback is not None:
                    h.replacement = replacement
                    h.callback = callback
                return h
        h = Hotstring(trigger, replacement, callback, self.default_opts + opts, criterion)
        h.input_level = self.mgr.rt.directives["InputLevel"]
        self.items = self.items + [h]
        return h

    def reset(self):
        self.buffer = ""

    def on_char(self, ch: str, can_suppress: bool, level=None) -> bool:
        """A character was typed (level: None = physical, else the SendLevel of sent input).
        Returns True if the keystroke should be suppressed."""
        if self.suspended and not any(h.suspend_exempt for h in self.items):
            return False
        if ch == "\b":
            self.buffer = self.buffer[:-1]
            return False
        self.buffer = (self.buffer + ch)[-100:]
        is_end = ch in self.end_chars
        for h in self.items:
            if not h.enabled or (self.suspended and not h.suspend_exempt):
                continue
            if level is not None and level <= h.input_level:
                continue          # sent input only reaches hotstrings with a lower #InputLevel
            trig = h.trigger
            if h.asterisk:
                typed = self.buffer
                if not _ends_with(typed, trig, h.case == 1):
                    continue
                before = typed[:-len(trig)]
                if not h.question and before and not _is_boundary(before[-1], self.end_chars):
                    continue
                end_char = ""
                typed_trigger = typed[-len(trig):]
            else:
                if not is_end:
                    continue
                typed = self.buffer[:-1]
                if not _ends_with(typed, trig, h.case == 1):
                    continue
                before = typed[:-len(trig)]
                if not h.question and before and not _is_boundary(before[-1], self.end_chars):
                    continue
                end_char = ch
                typed_trigger = typed[-len(trig):]
            if h.criterion is not None and not self.mgr.eval_criterion(h.criterion):
                continue
            # hook.cpp: the final key is suppressed if it would be backspaced over anyway
            suppress = can_suppress and (h.backspace or (h.omit and not h.asterisk))
            self._fire(h, typed_trigger, end_char, suppress)
            if h.replacement is not None:
                # the screen no longer matches the buffer; keep the end char, which may start another hotstring
                self.buffer = end_char
            elif h.backspace:
                self.buffer = self.buffer[:len(self.buffer) - len(h.trigger) - (1 if end_char else 0)]
            if h.reset:
                self.buffer = ""
            return suppress
        return False

    def _fire(self, h: Hotstring, typed_trigger, end_char, suppressed):
        rt = self.mgr.rt
        name = ":" + "".join(_opt_letters(h)) + ":" + h.trigger

        def run():
            rt.prior_hotkey, rt.prior_hotkey_time = rt.this_hotkey, rt.this_hotkey_time
            rt.this_hotkey, rt.this_hotkey_time = name, time.monotonic()
            rt.end_char = end_char
            from .lib.input_ import do_send
            if h.backspace:
                # the final keystroke (end char, or last trigger char for *) was suppressed when possible
                n = len(typed_trigger)
                if suppressed:
                    n -= 1 if not end_char else 0
                else:
                    n += 1 if end_char else 0
                if n > 0:
                    do_send("{BS " + str(n) + "}", mode=h.send_mode, blind=False)
            if h.callback is not None:
                rt.call(h.callback, [name])
                if not h.backspace or end_char and not h.omit and h.replacement is None:
                    pass
                return
            text = _conform(h, typed_trigger, h.replacement)
            if h.text:
                do_send(text, mode=h.send_mode, text=True)
            elif h.raw:
                do_send(text, mode=h.send_mode, raw=True)
            else:
                do_send(text, mode=h.send_mode)
            if end_char and not h.omit:
                do_send(end_char, mode=h.send_mode, text=True)
            elif not h.backspace and not end_char and suppressed:
                pass
        rt.post(run, priority=h.priority, kind="hotstring", tag=name)


def _same_case_mode(h, opts):
    return True


def _opt_letters(h):
    out = []
    if h.asterisk:
        out.append("*")
    if h.question:
        out.append("?")
    if not h.backspace:
        out.append("B0")
    if h.case == 1:
        out.append("C")
    elif h.case == 2:
        out.append("C1")
    if h.omit:
        out.append("O")
    if h.execute:
        out.append("X")
    return out


def _ends_with(typed, trig, case_sensitive):
    if len(typed) < len(trig):
        return False
    tail = typed[-len(trig):]
    return tail == trig if case_sensitive else tail.lower() == trig.lower()


def _is_boundary(c, end_chars):
    return c in end_chars or not c.isalnum()


def _conform(h, typed, repl):
    if h.case != 0 or not repl:
        return repl
    letters = [c for c in typed if c.isalpha()]
    if not letters:
        return repl
    if all(c.isupper() for c in letters) and (len(letters) > 1 or not any(c.isalpha() for c in h.trigger[1:])):
        if len(letters) > 1:
            return repl.upper()
    if typed[:1].isupper() and typed[:1].isalpha():
        # first letter capitalised
        for i, c in enumerate(repl):
            if c.isalpha():
                return repl[:i] + c.upper() + repl[i + 1:]
    return repl


def _replacement_preview(h, end_char):
    return ""
