"""Control flow & settings built-ins: Sleep, SetTimer, Exit*, Critical, Thread, OnExit, Set*Mode..."""
from __future__ import annotations

import os
import sys
import time

from .. import objects as O
from ..errors import ExitAppEx, ExitThread, ReloadEx
from ..objects import AhkObject, FuncBase, throw
from ..values import UNSET, to_bool
from . import export


def rt():
    return O.RT


def S(v):
    return O.RT.to_str(v)


@export()
def Sleep(ms):
    rt().sleep(rt().to_int(ms) if not isinstance(ms, float) else int(ms))
    return ""


class Timer:
    __slots__ = ("fn", "period", "next_due", "enabled", "running", "priority", "once")

    def __init__(self, fn, period, priority):
        self.fn = fn
        self.set_period(period)
        self.enabled = True
        self.running = False
        self.priority = priority

    def set_period(self, period):
        self.once = period < 0
        self.period = abs(period) if period else 250
        self.next_due = time.monotonic() + self.period / 1000.0

    def fire(self, r):
        self.running = True
        if self.once:
            self.enabled = False
        try:
            r.run_thread(lambda: r.call(self.fn, []), self.priority, "timer")
        finally:
            self.running = False
            self.next_due = time.monotonic() + self.period / 1000.0
            if self.once and self in r.timers:
                r.timers.remove(self)


def _find_timer(fn):
    for t in rt().timers:
        if t.fn is fn:
            return t
    return None


@export()
def SetTimer(fn=UNSET, period=UNSET, priority=0):
    r = rt()
    if fn is UNSET:
        cur = getattr(r, "current_timer_fn", None)
        if cur is None:
            throw("ValueError", "Invalid value.")
        fn = cur
    if not isinstance(fn, AhkObject):
        throw("TypeError", O.type_error_msg("Object", fn))
    t = _find_timer(fn)
    prio = r.to_int(priority) if priority != "" else 0
    if period is UNSET:
        p = 250
        if t is not None:
            t.enabled = True
            t.priority = prio
            return ""
    else:
        p = r.to_int(period)
    if p == 0:
        if t is not None:
            t.enabled = False
            r.timers.remove(t)
        return ""
    if t is None:
        t = Timer(fn, p, prio)
        r.timers.append(t)
    else:
        t.set_period(p)
        t.enabled = True
        t.priority = prio
    r.pending = True
    return ""


@export()
def ExitApp(code=0):
    raise ExitAppEx(rt().to_int(code) if code != "" else 0)


@export()
def Exit(code=UNSET):
    r = rt()
    if code is not UNSET:
        r.exit_code = r.to_int(code)
    raise ExitThread()


@export()
def Reload():
    raise ReloadEx()


@export()
def Persistent(flag=1):
    r = rt()
    old = int(r.persistent)
    r.persistent = to_bool(flag)
    return old


@export()
def Critical(onoff=UNSET):
    r = rt()
    th = r.thread
    old = th.settings.critical if th.is_critical else 0
    if onoff is UNSET or (isinstance(onoff, str) and onoff.lower() == "on"):
        th.is_critical = True
        th.settings.critical = 16
    elif isinstance(onoff, str) and onoff.lower() == "off":
        th.is_critical = False
        th.settings.critical = 0
    else:
        v = r.to_int(onoff)
        th.is_critical = v != 0
        th.settings.critical = v
    if not th.is_critical:
        r.pending = True
    return old


@export()
def Thread(sub, v1=UNSET, v2=UNSET):
    r = rt()
    s = S(sub).lower()
    if s == "notimers":
        r.thread.settings.allow_timers = not to_bool(v1 if v1 is not UNSET else 1)
    elif s == "priority":
        r.thread.priority = r.to_int(v1)
    elif s == "interrupt":
        pass
    return ""


@export()
def Pause(newstate=UNSET):
    r = rt()
    if newstate is UNSET or S(newstate) in ("1", "On", "on"):
        r.paused = True
        # a paused thread waits here, still processing other threads (those that are not paused)
        while r.paused and not r.exiting:
            r.sleep(50)
    elif S(newstate) == "-1":
        r.paused = not r.paused
    else:
        r.paused = False
    from . import tray
    tray.refresh()
    return ""


@export()
def Suspend(mode=-1):
    r = rt()
    m = S(mode).lower()
    if m in ("-1", "toggle"):
        r.suspended = not r.suspended
    else:
        r.suspended = to_bool(mode) if m not in ("on", "off") else m == "on"
    if r.hotkeys is not None:
        r.hotkeys.suspended = r.suspended
    if r.hotstrings is not None:
        r.hotstrings.suspended = r.suspended
    if r.backend is not None:
        r.backend.refresh()
    from . import tray
    tray.refresh()
    return ""


@export()
def OnExit(fn, add=1):
    r = rt()
    a = r.to_int(add)
    if fn in r.on_exit_funcs:
        r.on_exit_funcs.remove(fn)
    if a > 0:
        r.on_exit_funcs.append(fn)
    elif a < 0:
        r.on_exit_funcs.insert(0, fn)
    return ""


@export()
def OnError(fn, add=1):
    r = rt()
    a = r.to_int(add)
    if fn in r.on_error_funcs:
        r.on_error_funcs.remove(fn)
    if a > 0:
        r.on_error_funcs.append(fn)
    elif a < 0:
        r.on_error_funcs.insert(0, fn)
    return ""


@export()
def OnMessage(msg, fn, max_threads=1):
    return ""


@export()
def OnClipboardChange(fn, add=1):
    from .clipboard import on_change
    on_change(fn, rt().to_int(add))
    return ""


@export()
def ListLines(mode=UNSET):
    return 0


@export()
def ListVars():
    return ""


@export()
def ListHotkeys():
    r = rt()
    if r.hotkeys:
        print("\n".join(hk.name for hk in r.hotkeys.hotkeys))
    return ""


@export()
def KeyHistory(n=UNSET):
    return ""


@export()
def OutputDebug(text):
    sys.stderr.write(S(text) + "\n")
    sys.stderr.flush()
    return ""


@export()
def InstallKeybdHook(install=1, force=0):
    return ""


@export()
def InstallMouseHook(install=1, force=0):
    return ""


# ---------------------------------------------------------------- per-thread settings
def _set(attr, value):
    setattr(rt().thread.settings, attr, value)
    return ""


@export()
def SetTitleMatchMode(mode):
    m = S(mode)
    if m.lower() in ("fast", "slow"):
        return _set("title_match_speed", m.capitalize())
    if m.lower() == "regex":
        return _set("title_match_mode", "RegEx")
    v = rt().to_int(mode)
    if v not in (1, 2, 3):
        throw("ValueError", "Invalid value.", m)
    return _set("title_match_mode", v)


@export()
def DetectHiddenWindows(mode):
    old = rt().thread.settings.detect_hidden_windows
    _set("detect_hidden_windows", _onoff(mode))
    return int(old)


@export()
def DetectHiddenText(mode):
    old = rt().thread.settings.detect_hidden_text
    _set("detect_hidden_text", _onoff(mode))
    return int(old)


def _onoff(v):
    if isinstance(v, str) and v.lower() in ("on", "off"):
        return v.lower() == "on"
    return to_bool(v)


@export()
def SendMode(mode):
    m = S(mode).lower()
    canon = {"event": "Event", "input": "Input", "inputthenplay": "InputThenPlay", "play": "Play"}.get(m)
    if canon is None:
        throw("ValueError", "Invalid value.", S(mode))
    return _set("send_mode", canon)


@export()
def SendLevel(level):
    return _set("send_level", rt().to_int(level))


@export()
def SetKeyDelay(delay=UNSET, duration=UNSET, play=""):
    s = rt().thread.settings
    if S(play).lower() == "play":
        if delay is not UNSET:
            s.key_delay_play = rt().to_int(delay)
        if duration is not UNSET:
            s.key_duration_play = rt().to_int(duration)
    else:
        if delay is not UNSET:
            s.key_delay = rt().to_int(delay)
        if duration is not UNSET:
            s.key_duration = rt().to_int(duration)
    return ""


@export()
def SetMouseDelay(delay, play=""):
    if S(play).lower() == "play":
        return _set("mouse_delay_play", rt().to_int(delay))
    return _set("mouse_delay", rt().to_int(delay))


@export()
def SetDefaultMouseSpeed(speed):
    return _set("default_mouse_speed", rt().to_int(speed))


@export()
def SetWinDelay(delay):
    return _set("win_delay", rt().to_int(delay))


@export()
def SetControlDelay(delay):
    return _set("control_delay", rt().to_int(delay))


@export()
def CoordMode(target, relative="Screen"):
    t = S(target).lower()
    canon = {"tooltip": "ToolTip", "pixel": "Pixel", "mouse": "Mouse", "caret": "Caret", "menu": "Menu"}.get(t)
    rel = {"screen": "Screen", "window": "Window", "client": "Client"}.get(S(relative).lower())
    if canon is None or rel is None:
        throw("ValueError", "Invalid value.", S(target))
    rt().thread.settings.coord_mode[canon] = rel
    return ""


@export()
def SetStoreCapsLockMode(mode):
    return _set("store_capslock", _onoff(mode))


@export()
def SetRegView(view):
    return _set("reg_view", S(view))


@export()
def StringCaseSense(mode):
    """v1 command kept for compatibility with v2-alpha scripts."""
    return _set("string_case_sense", S(mode))
