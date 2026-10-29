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


_MSG_HANDLERS: dict[int, list] = {}


def message_handlers(msg):
    return list(_MSG_HANDLERS.get(msg, []))


@export()
def OnMessage(msg, fn, max_threads=1):
    """Register a handler for SendMessage/PostMessage to this script's windows (and Gui controls)."""
    m = rt().to_int(msg)
    n = rt().to_int(max_threads) if max_threads not in (UNSET, "") else 1
    lst = _MSG_HANDLERS.setdefault(m, [])
    if fn in lst:
        lst.remove(fn)
    if n > 0:
        lst.append(fn)
    elif n < 0:
        lst.insert(0, fn)
    if not lst:
        del _MSG_HANDLERS[m]
    return ""


@export()
def OnClipboardChange(fn, add=1):
    from .clipboard import on_change
    on_change(fn, rt().to_int(add))
    return ""


def _show_main(title, text):
    """AutoHotkey's main window views (ListVars, ListHotkeys, KeyHistory, ListLines)."""
    import os
    r = rt()
    name = os.path.basename(r.script_path)
    try:
        from .guiobj import _srv
        _srv().call("info", title=f"{name} - {title} - Bunny Hot Key", text=text)
    except Exception:
        sys.stderr.write(text + "\n")
    return ""


@export()
def ListLines(mode=UNSET):
    """Line logging on/off for the current thread; returns the previous setting.  Without a parameter, shows the
    last 400 executed lines (script2.cpp ListLines, script.cpp Line::LogToText)."""
    r = rt()
    old = int(r.thread.settings.list_lines)
    if mode is UNSET:
        _show_main("Lines most recently executed", line_log_text())
        return old
    if r.thread.settings.list_lines and r.line_log:
        r.line_log.pop()          # don't clutter the history with the ListLines line itself
    r.thread.settings.list_lines = 1 if to_bool(mode) else 0
    return old


_SRC_CACHE: dict[str, list] = {}


def line_log_text():
    r = rt()
    out = ["Script lines most recently executed (oldest first).  The seconds elapsed between a line and the one "
           "after it is in parentheses to the right (if not 0).  The bottommost line's elapsed time is the number "
           "of seconds since it executed.", ""]
    entries = list(r.line_log)
    last_file = None
    now = time.monotonic()
    for i, (file, line, t) in enumerate(entries):
        if file != last_file:
            out.append(f"---- {file}")
            last_file = file
        src = _SRC_CACHE.get(file)
        if src is None:
            try:
                with open(file, encoding="utf-8-sig", errors="replace") as fh:
                    src = fh.read().splitlines()
            except OSError:
                src = []
            _SRC_CACHE[file] = src
        text = src[line - 1].strip()[:200] if 0 < line <= len(src) else ""
        elapsed = (entries[i + 1][2] if i + 1 < len(entries) else now) - t
        out.append(f"{line:03d}: {text}" + (f" ({elapsed:.2f})" if elapsed >= 0.005 else ""))
    return "\n".join(out)


def _var_line(name, v):
    from ..values import type_name
    from ..objects import AhkObject
    if v is UNSET:
        return f"{name}: unset"
    if isinstance(v, AhkObject):
        return f"{name}: {type_name(v)} object"
    s = rt().to_str(v)
    shown = s if len(s) <= 1000 else s[:1000] + "..."
    if isinstance(v, str):
        return f"{name}[{len(s)} of {len(s)}]: {shown}"
    return f"{name}: {shown}"


@export()
def ListVars():
    r = rt()
    lines = ["Global Variables (alphabetical)", "-" * 50]
    for key in sorted(r.globals, key=str.lower):
        cell = r.globals[key]
        if cell.value is UNSET and not getattr(cell, "name", ""):
            continue
        lines.append(_var_line(cell.name or key, cell.value))
    return _show_main("Variables and their contents", "\n".join(lines))


@export()
def ListHotkeys():
    r = rt()
    lines = ["Type\tOff?\tLevel\tRunning\tName", "-" * 60]
    if r.hotkeys:
        for hk in r.hotkeys.hotkeys:
            off = "" if any(v.enabled for v in hk.variants) else "OFF"
            lines.append(f"k-hook\t{off}\t\t\t{hk.name}")
    if r.hotstrings is not None:
        for h in r.hotstrings.items:
            lines.append(f"hotstring\t\t\t\t:{h.options if hasattr(h, 'options') else ''}:{h.trigger}")
    return _show_main("Hotkeys and their methods", "\n".join(lines))


@export()
def KeyHistory(n=UNSET):
    from .. import hotkeys as H
    from .. import keys as K
    if n is not UNSET:
        set_key_history(rt().to_int(n))
        return ""
    KEY_HISTORY = H.KEY_HISTORY
    lines = ["Window: " + _active_title(), "Keys are shown oldest first.  Type: h = suppressed by a hotkey, "
             "s = sent by the script.", "", "SC\tType\tUp/Dn\tElapsed\tKey", "-" * 60]
    prev = None
    for t, code, kind, down, sup in list(KEY_HISTORY):
        k = K.from_code(code) if kind == "key" else None
        name = K.key_name(k) if k is not None else (kind if kind != "key" else f"sc{code:03X}")
        sc = f"{k.sc:03X}" if k is not None and k.sc else "000"
        lines.append(f"{sc}\t{'h' if sup else ''}\t{'d' if down else 'u'}\t{0 if prev is None else t - prev:.2f}"
                     f"\t{name}")
        prev = t
    return _show_main("Key history", "\n".join(lines))


def set_key_history(n):
    """KeyHistory N / #KeyHistory N: keep the last N events (0 disables logging, max 500)."""
    import collections
    from .. import hotkeys as H
    H.KEY_HISTORY = collections.deque(maxlen=max(0, min(n, 500)))


def _active_title():
    try:
        from .window import _dpy, active_window, title_of
        d = _dpy()
        return title_of(d, active_window(d)) or ""
    except Exception:
        return ""


@export()
def OutputDebug(text):
    sys.stderr.write(S(text) + "\n")
    sys.stderr.flush()
    return ""


def _install_hook(install):
    """Start watching physical input (XInput2 raw events on X11) even if the script has no hotkeys, so KeyHistory,
    GetKeyState(, "P") and A_TimeIdlePhysical see real input.  Like AutoHotkey's hooks, this doesn't by itself keep
    the script running."""
    if install is not UNSET and not to_bool(install):
        return ""
    r = rt()
    if getattr(r, "hotmgr", None) is None:
        from ..hotmgr import HotManager
        r.hotmgr = HotManager(r)
    from .input_ import backend
    backend()
    return ""


@export()
def InstallKeybdHook(install=1, force=0):
    return _install_hook(install)


@export()
def InstallMouseHook(install=1, force=0):
    return _install_hook(install)


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
