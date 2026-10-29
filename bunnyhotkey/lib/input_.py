"""Keyboard/mouse built-ins: Send*, Click, Mouse*, GetKeyState, KeyWait, Hotkey(), Hotstring(), InputHook.

Send syntax follows SendKeys() in keyboard_mouse.cpp.  Output goes to the active
input backend (X11/XTest or evdev/uinput).
"""
from __future__ import annotations

import re
import time

from .. import keys as K
from .. import objects as O
from ..objects import AhkObject, CLASSES, FuncBase, throw
from ..values import UNSET, to_bool
from . import export, setref


def rt():
    return O.RT


def S(v):
    return O.RT.to_str(v)


def backend():
    b = rt().backend
    if b is None:
        from ..backends import get_backend
        b = get_backend(rt())
    return b


MOD_ORDER = ("ctrl", "shift", "alt", "win")
MOD_PREFIX = {"^": "ctrl", "+": "shift", "!": "alt", "#": "win"}


# ---------------------------------------------------------------- Send
class Sender:
    def __init__(self, mode, blind=False):
        r = rt()
        st = r.thread.settings
        self.b = backend()
        self.mode = mode or st.send_mode
        if self.mode in ("Event",):
            self.delay = st.key_delay
            self.duration = st.key_duration
        elif self.mode == "Play":
            self.delay = st.key_delay_play
            self.duration = st.key_duration_play
        else:
            self.delay = -1
            self.duration = -1
        self.blind = blind
        self.released: list[int] = []
        self.held: set[int] = set()     # keys this Send pressed with {down}

    def pause(self, ms):
        if ms is not None and ms >= 0:
            if ms == 0:
                rt().sleep(-1) if False else None
            else:
                rt().sleep(ms)

    def begin(self):
        if not self.blind:
            for code in self.b.logical_modifiers():
                self.b.key(code, False)
                self.released.append(code)
            self.b.flush()

    def end(self):
        # restore modifiers the user is still physically holding
        for code in self.released:
            if self.b.key_state(code, physical=True):
                self.b.key(code, True)
        self.b.flush()

    def tap(self, code, mods=(), count=1):
        for _ in range(count):
            for m in mods:
                self.b.key(K.MOD_LEFT[m], True)
            self.b.key(code, True)
            self.pause(self.duration)
            self.b.key(code, False)
            for m in reversed(mods):
                self.b.key(K.MOD_LEFT[m], False)
            self.b.flush()
            self.pause(self.delay)

    def char(self, ch, mods=(), count=1):
        if ch == "\n" or ch == "\r":
            return self.tap(28, mods, count)
        if ch == "\t":
            return self.tap(15, mods, count)
        hit = K.char_to_code(ch)
        if hit is None:
            for _ in range(count):
                self.b.text(ch)
                self.pause(self.delay)
            return
        code, shift = hit
        m = list(mods)
        if shift and "shift" not in m:
            m.append("shift")
        self.tap(code, m, count)

    def text(self, s):
        i = 0
        while i < len(s):
            c = s[i]
            if c == "\r" and i + 1 < len(s) and s[i + 1] == "\n":
                i += 1
                c = "\n"
            self.char(c)
            i += 1


def _parse_brace(content):
    """{Name}, {Name N}, {Name down|up|DownR|DownTemp}"""
    if content in ("{", "}") or len(content) == 1:
        return content, "tap", 1
    m = re.match(r"^(\S+?)(?:\s+(.*))?$", content.strip(), re.S)
    name = m.group(1)
    arg = (m.group(2) or "").strip()
    if not arg:
        return name, "tap", 1
    al = arg.lower()
    if al in ("down", "downr", "downtemp"):
        return name, "down", 1
    if al == "up":
        return name, "up", 1
    try:
        return name, "tap", int(arg)
    except ValueError:
        return content, "tap", 1


def do_send(keys, mode=None, raw=False, text=False, blind=False):
    s = keys
    snd = Sender(mode, blind)
    # leading {Blind}
    if s.lower().startswith("{blind"):
        j = s.find("}")
        snd.blind = True
        s = s[j + 1:]
    snd.begin()
    try:
        if text:
            snd.text(s)
            return
        if raw:
            for c in s:
                snd.char(c)
            return
        mods: list[str] = []
        i = 0
        n = len(s)
        while i < n:
            c = s[i]
            if c in MOD_PREFIX and i + 1 < n:
                mods.append(MOD_PREFIX[c])
                i += 1
                continue
            if c == "{":
                j = s.find("}", i + 2 if s.startswith("{}", i) else i + 1)
                if j < 0:
                    snd.char("{", mods)
                    mods = []
                    i += 1
                    continue
                content = s[i + 1:j]
                i = j + 1
                low = content.lower()
                if low == "raw":
                    for ch in s[i:]:
                        snd.char(ch)
                    return
                if low == "text":
                    snd.text(s[i:])
                    return
                if low.startswith("click"):
                    click_cmd(content[5:])
                    mods = []
                    continue
                if low == "blind":
                    continue
                name, action, count = _parse_brace(content)
                if name.lower().startswith("u+") and len(name) > 2:
                    ch = chr(int(name[2:], 16))
                    snd.char(ch, mods, count) if K.char_to_code(ch) else [snd.b.text(ch) for _ in range(count)]
                    mods = []
                    continue
                if name.lower() == "asc":
                    snd.char(chr(count), mods)
                    mods = []
                    continue
                key = K.lookup(name)
                if key is None:
                    if len(name) == 1:
                        snd.char(name, mods, count)
                        mods = []
                        continue
                    throw("ValueError", "Invalid key name.", name) if False else None
                    mods = []
                    continue
                if key.kind == "mouse":
                    btn = key.name
                    if action == "down":
                        snd.b.button(btn, True)
                    elif action == "up":
                        snd.b.button(btn, False)
                    else:
                        for _ in range(count):
                            snd.b.button(btn, True)
                            snd.b.button(btn, False)
                    snd.b.flush()
                    mods = []
                    continue
                if key.kind == "wheel":
                    snd.b.wheel(key.name, count)
                    mods = []
                    continue
                if key.char and action == "tap":
                    snd.char(key.char, mods, count)
                    mods = []
                    continue
                if action == "down":
                    for m in mods:
                        snd.b.key(K.MOD_LEFT[m], True)
                    snd.b.key(key.code, True)
                    if K.MOD_KEYS.get(key.code) and key.code in snd.released:
                        snd.released.remove(key.code)
                    snd.b.flush()
                    snd.pause(snd.delay)
                elif action == "up":
                    snd.b.key(key.code, False)
                    for m in reversed(mods):
                        snd.b.key(K.MOD_LEFT[m], False)
                    snd.b.flush()
                    snd.pause(snd.delay)
                else:
                    snd.tap(key.code, mods, count)
                mods = []
                continue
            snd.char(c, mods)
            mods = []
            i += 1
    finally:
        snd.end()


@export()
def Send(keys):
    do_send(S(keys))
    return ""


@export()
def SendInput(keys):
    do_send(S(keys), mode="Input")
    return ""


@export()
def SendEvent(keys):
    do_send(S(keys), mode="Event")
    return ""


@export()
def SendPlay(keys):
    do_send(S(keys), mode="Play")
    return ""


@export()
def SendText(keys):
    do_send(S(keys), text=True)
    return ""


@export()
def SendRaw(keys):
    do_send(S(keys), raw=True)
    return ""


def send_to_window(win, keys, raw=False):
    from .window import _dpy, active_window, activate
    d = _dpy()
    prev = active_window(d) if d else 0
    if d and win and win != prev:
        activate(d, win)
        rt().sleep(30)
    if raw:
        do_send(keys, text=True)
    else:
        do_send(keys)
    if d and prev and win != prev:
        activate(d, prev)


def click_window(win, button, count, pos):
    from .window import _dpy, geometry
    d = _dpy()
    x, y, w, h = geometry(d, win, client=True)
    px, py = (x + pos[0], y + pos[1]) if pos else (x + w // 2, y + h // 2)
    b = backend()
    ox, oy = b.mouse_pos()
    b.move(px, py)
    btn = {"left": "LButton", "l": "LButton", "right": "RButton", "r": "RButton", "middle": "MButton",
           "m": "MButton"}.get(button.lower(), "LButton")
    for _ in range(max(count, 1)):
        b.button(btn, True)
        b.button(btn, False)
    b.move(ox, oy)
    b.flush()


# ---------------------------------------------------------------- mouse
def _coord_to_screen(x, y, kind="Mouse"):
    from .window import _coord_origin
    ox, oy = _coord_origin(kind)
    return x + ox, y + oy


def _screen_to_coord(x, y, kind="Mouse"):
    from .window import _coord_origin
    ox, oy = _coord_origin(kind)
    return x - ox, y - oy


BUTTONS = {"left": "LButton", "l": "LButton", "right": "RButton", "r": "RButton", "middle": "MButton",
           "m": "MButton", "x1": "XButton1", "x2": "XButton2", "wheelup": "WheelUp", "wu": "WheelUp",
           "wheeldown": "WheelDown", "wd": "WheelDown", "wheelleft": "WheelLeft", "wl": "WheelLeft",
           "wheelright": "WheelRight", "wr": "WheelRight", "lbutton": "LButton", "rbutton": "RButton",
           "mbutton": "MButton", "xbutton1": "XButton1", "xbutton2": "XButton2"}


def _move(x, y, speed=None, relative=False):
    b = backend()
    r = rt()
    if relative:
        cx, cy = b.mouse_pos()
        tx, ty = cx + x, cy + y
    else:
        tx, ty = _coord_to_screen(x, y)
    sp = r.thread.settings.default_mouse_speed if speed is None else speed
    if sp > 0 and r.thread.settings.send_mode == "Event":
        cx, cy = b.mouse_pos()
        steps = max(1, int(max(abs(tx - cx), abs(ty - cy)) / max(32 - sp * 3, 4)))
        for i in range(1, steps + 1):
            b.move(cx + (tx - cx) * i // steps, cy + (ty - cy) * i // steps)
            b.flush()
            time.sleep(0.004)
    else:
        b.move(tx, ty)
    b.flush()


def click_cmd(opts: str):
    tokens = re.split(r"[\s,]+", opts.strip())
    nums = []
    button = "LButton"
    updown = None
    relative = False
    for t in tokens:
        if not t:
            continue
        tl = t.lower()
        if re.fullmatch(r"-?\d+", t):
            nums.append(int(t))
        elif tl in BUTTONS:
            button = BUTTONS[tl]
        elif tl in ("down", "d"):
            updown = "down"
        elif tl in ("up", "u"):
            updown = "up"
        elif tl in ("rel", "relative"):
            relative = True
    count = 1
    if len(nums) >= 2:
        _move(nums[0], nums[1], 0, relative)
        if len(nums) >= 3:
            count = nums[2]
    elif len(nums) == 1:
        count = nums[0]
    b = backend()
    st = rt().thread.settings
    if button.startswith("Wheel"):
        b.wheel(button, max(count, 1))
        b.flush()
        return
    if count == 0:
        return
    for _ in range(count):
        if updown != "up":
            b.button(button, True)
        if updown != "down":
            b.button(button, False)
        b.flush()
        if st.mouse_delay > 0 and st.send_mode == "Event":
            rt().sleep(st.mouse_delay)


@export()
def Click(*args):
    click_cmd(" ".join(S(a) for a in args if a is not UNSET))
    return ""


@export()
def MouseMove(x, y, speed=UNSET, relative=""):
    r = rt()
    _move(r.to_int(x), r.to_int(y), None if speed is UNSET else r.to_int(speed), S(relative).upper().startswith("R"))
    return ""


@export()
def MouseClick(button="Left", x=UNSET, y=UNSET, count=1, speed=UNSET, downup="", relative=""):
    r = rt()
    btn = BUTTONS.get(S(button).lower() or "left", "LButton")
    if x is not UNSET and y is not UNSET and x != "" and y != "":
        _move(r.to_int(x), r.to_int(y), None if speed is UNSET else r.to_int(speed), S(relative).upper().startswith("R"))
    du = S(downup).lower()
    b = backend()
    if btn.startswith("Wheel"):
        b.wheel(btn, r.to_int(count) if count != "" else 1)
        return ""
    for _ in range(r.to_int(count) if count != "" else 1):
        if du not in ("u", "up"):
            b.button(btn, True)
        if du not in ("d", "down"):
            b.button(btn, False)
        b.flush()
    return ""


@export()
def MouseClickDrag(button, x1, y1, x2, y2, speed=UNSET, relative=""):
    r = rt()
    btn = BUTTONS.get(S(button).lower(), "LButton")
    rel = S(relative).upper().startswith("R")
    sp = None if speed is UNSET else r.to_int(speed)
    b = backend()
    if x1 != "" and y1 != "":
        _move(r.to_int(x1), r.to_int(y1), sp, rel)
    b.button(btn, True)
    b.flush()
    time.sleep(0.01)
    _move(r.to_int(x2), r.to_int(y2), sp, rel)
    b.button(btn, False)
    b.flush()
    return ""


@export(byref=(0, 1, 2, 3))
def MouseGetPos(outx=UNSET, outy=UNSET, outwin=UNSET, outctrl=UNSET, flag=0):
    b = backend()
    x, y = b.mouse_pos()
    cx, cy = _screen_to_coord(x, y)
    setref(outx, cx)
    setref(outy, cy)
    if outwin is not UNSET:
        setref(outwin, b.window_under_mouse())
    setref(outctrl, "")
    return ""


# ---------------------------------------------------------------- key state
def _key(name):
    k = K.lookup(S(name))
    if k is None:
        throw("ValueError", "Invalid key name.", S(name))
    return k


@export()
def GetKeyState(keyname, mode=""):
    k = _key(keyname)
    m = S(mode).upper()
    b = backend()
    if m == "T":
        return int(b.toggle_state(k.name))
    if k.kind == "wheel":
        return 0
    if k.neutral:
        codes = (K.MOD_LEFT[k.neutral], K.MOD_RIGHT[k.neutral])
        return int(any(b.key_state(c, physical=(m == "P")) for c in codes))
    return int(b.key_state(k.code, physical=(m == "P")))


@export()
def KeyWait(keyname, options=""):
    k = _key(keyname)
    o = S(options).upper()
    want_down = "D" in o
    logical = "L" in o
    m = re.search(r"T(\d+(?:\.\d+)?)", o)
    end = time.monotonic() + float(m.group(1)) if m else None
    b = backend()
    codes = (K.MOD_LEFT[k.neutral], K.MOD_RIGHT[k.neutral]) if k.neutral else (k.code,)
    while True:
        down = any(b.key_state(c, physical=not logical) for c in codes)
        if down == want_down:
            return 1
        if end is not None and time.monotonic() >= end:
            return 0
        rt().sleep(10)


def _set_toggle(name, state):
    b = backend()
    s = S(state).lower() if state is not UNSET else ""
    cur = b.toggle_state(name)
    want = {"on": True, "alwayson": True, "1": True, "off": False, "alwaysoff": False, "0": False}.get(s, not cur)
    if want != cur:
        k = K.lookup(name)
        b.key(k.code, True)
        b.key(k.code, False)
        b.flush()
    return ""


@export()
def SetCapsLockState(state=UNSET):
    return _set_toggle("CapsLock", state)


@export()
def SetNumLockState(state=UNSET):
    return _set_toggle("NumLock", state)


@export()
def SetScrollLockState(state=UNSET):
    return _set_toggle("ScrollLock", state)


@export()
def BlockInput(mode):
    b = backend()
    if hasattr(b, "block_input"):
        b.block_input(S(mode).lower() in ("on", "1", "send", "mouse"))
    return ""


@export()
def GetKeyName(keyname):
    k = K.lookup(S(keyname))
    return K.key_name(k) if k else ""


@export()
def GetKeyVK(keyname):
    k = K.lookup(S(keyname))
    return k.vk if k else 0


@export()
def GetKeySC(keyname):
    k = K.lookup(S(keyname))
    return k.sc if k else 0


def time_idle():
    b = rt().backend
    if b is None:
        return 0
    return b.idle_ms()


# ---------------------------------------------------------------- Hotkey() / Hotstring() / HotIf
def mgr():
    r = rt()
    if r.hotmgr is None:
        from ..hotmgr import HotManager
        r.hotmgr = HotManager(r)
    return r.hotmgr


@export()
def Hotkey(keyname, action=UNSET, options=""):
    m = mgr()
    name = S(keyname)
    crit = m.current_criterion
    cb = None
    opts = S(options)
    if action is not UNSET:
        if isinstance(action, AhkObject):
            cb = action
        else:
            a = S(action).lower()
            if a in ("on", "off", "toggle"):
                hk = m.engine.find(name)
                if hk is None:
                    throw("Error", "Nonexistent hotkey.", name)
                for v in hk.variants:
                    if v.criterion is crit:
                        v.enabled = (a == "on") or (a == "toggle" and not v.enabled)
                        break
                else:
                    throw("Error", "Nonexistent hotkey variant (HotIf).", name)
                if r_backend():
                    r_backend().refresh()
                return ""
            if a in ("alttab", "shiftalttab", "alttabmenu", "alttabandmenu", "alttabmenudismiss"):
                cb = O.BuiltinFunc(a, lambda *x: do_send("{Alt down}{Tab}" if "shift" not in a else "{Alt down}+{Tab}"), 0, 1)
            else:
                # label/function name
                c = rt().globals.get(a)
                if c is None or not isinstance(c.value, AhkObject):
                    throw("ValueError", "Invalid value.", S(action))
                cb = c.value
    m.add_hotkey(name, cb, crit, opts)
    return ""


def r_backend():
    return rt().backend


@export()
def HotIf(criterion=UNSET):
    m = mgr()
    if criterion is UNSET or criterion == "":
        m.current_criterion = None
        return ""
    if isinstance(criterion, AhkObject):
        for c in m.criteria:
            if c.func is criterion:
                m.current_criterion = c
                return ""
        from ..hotmgr import Criterion
        c = Criterion(criterion, kind="expr")
        m.criteria.append(c)
        m.current_criterion = c
        return ""
    text = S(criterion)
    for c in m.criteria:
        if c.text == text:
            m.current_criterion = c
            return ""
    throw("ValueError", "Invalid value.", text)


def _hotifwin(kind, title, text):
    m = mgr()
    from ..hotmgr import Criterion
    if title is UNSET and text is UNSET:
        m.current_criterion = None
        return ""
    t = S(title) if title is not UNSET else ""
    x = S(text) if text is not UNSET else ""
    for c in m.criteria:
        if c.kind == kind and c.wintitle == t and c.wintext == x:
            m.current_criterion = c
            return ""
    c = Criterion(None, kind=kind, wintitle=t, wintext=x)
    m.criteria.append(c)
    m.current_criterion = c
    return ""


@export()
def HotIfWinActive(title=UNSET, text=UNSET):
    return _hotifwin("active", title, text)


@export()
def HotIfWinNotActive(title=UNSET, text=UNSET):
    return _hotifwin("notactive", title, text)


@export()
def HotIfWinExist(title=UNSET, text=UNSET):
    return _hotifwin("exist", title, text)


@export()
def HotIfWinNotExist(title=UNSET, text=UNSET):
    return _hotifwin("notexist", title, text)


@export()
def Hotstring(string, replacement=UNSET, onoff=UNSET):
    m = mgr()
    hs = m.hotstrings
    s = S(string)
    low = s.lower()
    if low == "endchars":
        old = hs.end_chars
        if replacement is not UNSET:
            hs.end_chars = S(replacement)
        return old
    if low == "mousereset":
        old = int(hs.mouse_reset)
        if replacement is not UNSET:
            hs.mouse_reset = to_bool(replacement)
        return old
    if low == "reset":
        hs.reset()
        return ""
    mm = re.match(r"^:([^:]*):(.*)$", s, re.S)
    if not mm:
        throw("ValueError", "Invalid value.", s)
    opts, trig = mm.group(1), mm.group(2)
    if trig == "":
        hs.default_opts = opts
        return ""
    cb = None
    repl = None
    if replacement is not UNSET:
        if isinstance(replacement, AhkObject):
            cb = replacement
        else:
            repl = S(replacement)
    existing = [h for h in hs.items if h.trigger == trig]
    if not existing and cb is None and repl is None:
        throw("Error", "Nonexistent hotstring.", s)
    h = hs.add(opts, trig, repl, cb, m.current_criterion)
    if onoff is not UNSET:
        v = S(onoff).lower()
        h.enabled = v in ("1", "on", "true") or (v in ("-1", "toggle") and not h.enabled)
    if rt().backend is not None:
        rt().backend.refresh()
    return ""


# ---------------------------------------------------------------- InputHook
class InputHookObj(AhkObject):
    __slots__ = ("opts", "end_keys", "match_list", "buf", "in_progress", "end_reason", "end_key", "match",
                 "max_len", "timeout", "visible", "case", "started", "callbacks", "done_evt", "min_send_level",
                 "end_mods")

    def __init__(self, options="", end_keys="", match_list=""):
        super().__init__(CLASSES["InputHook"].prototype)
        self.opts = options
        self.buf = ""
        self.in_progress = False
        self.end_reason = ""
        self.end_key = ""
        self.match = ""
        self.end_mods = ""
        self.callbacks = {}
        o = options
        mlen = re.search(r"L(\d+)", o)
        self.max_len = int(mlen.group(1)) if mlen else 1023
        tm = re.search(r"T(\d+(?:\.\d+)?)", o)
        self.timeout = float(tm.group(1)) if tm else 0
        self.visible = "V" in o
        self.case = "C" in o
        self.min_send_level = 1
        self.end_keys = []
        i = 0
        while i < len(end_keys):
            if end_keys[i] == "{":
                j = end_keys.find("}", i)
                k = K.lookup(end_keys[i + 1:j])
                if k:
                    self.end_keys.append(k.name.lower())
                i = j + 1
            else:
                self.end_keys.append(end_keys[i].lower())
                i += 1
        self.match_list = [x for x in match_list.split(",") if x] if match_list else []
        self.started = 0.0


_ACTIVE_HOOKS: list[InputHookObj] = []


def input_hook_char(ch: str, keyname: str, level=None) -> bool:
    """Feed typed text to active InputHooks (level: None = physical, else the SendLevel of sent input, which
    an InputHook collects only if it is at least its MinSendLevel); returns True if the key should be blocked."""
    block = False
    for ih in list(_ACTIVE_HOOKS):
        if not ih.in_progress:
            continue
        if level is not None and level < ih.min_send_level:
            continue
        if keyname.lower() in ih.end_keys or (ch and ch.lower() in ih.end_keys):
            _ih_end(ih, "EndKey", key=keyname)
            continue
        if ch:
            ih.buf += ch
            cb = ih.callbacks.get("onchar")
            if cb is not None:
                rt().post(lambda cb=cb, ih=ih, ch=ch: rt().call(cb, [ih, ch]))
            for m in ih.match_list:
                if (ih.buf.endswith(m) if ih.case else ih.buf.lower().endswith(m.lower())) and ("*" in ih.opts or ih.buf.lower() == m.lower()):
                    ih.match = m
                    _ih_end(ih, "Match")
                    break
            if ih.in_progress and len(ih.buf) >= ih.max_len:
                _ih_end(ih, "Max")
        if not ih.visible:
            block = True
    return block


def _ih_end(ih, reason, key=""):
    ih.in_progress = False
    ih.end_reason = reason
    ih.end_key = key
    if ih in _ACTIVE_HOOKS:
        _ACTIVE_HOOKS.remove(ih)
    cb = ih.callbacks.get("onend")
    if cb is not None:
        rt().post(lambda: rt().call(cb, [ih]))


def _ih_setup():
    from ..classes import method, prop
    p = CLASSES["InputHook"].prototype
    if p.own("Start") is not None:
        return
    method(p, "Start", lambda this: _ih_start(this))
    method(p, "Stop", lambda this: _ih_end(this, "Stopped") if this.in_progress else "")
    method(p, "Wait", lambda this, timeout=UNSET: _ih_wait(this, timeout))
    method(p, "KeyOpt", lambda this, keys, opts: "")
    prop(p, "Input", get=lambda this: this.buf)
    prop(p, "InProgress", get=lambda this: int(this.in_progress))
    prop(p, "EndReason", get=lambda this: this.end_reason)
    prop(p, "EndKey", get=lambda this: this.end_key)
    prop(p, "EndMods", get=lambda this: this.end_mods)
    prop(p, "Match", get=lambda this: this.match)
    for ev in ("OnChar", "OnEnd", "OnKeyDown", "OnKeyUp"):
        prop(p, ev, get=lambda this, e=ev.lower(): this.callbacks.get(e, ""),
             set=lambda this, v, e=ev.lower(): this.callbacks.__setitem__(e, v))
    for nm in ("BackspaceIsUndo", "CaseSensitive", "FindAnywhere", "MinSendLevel", "NotifyNonText", "Timeout",
               "VisibleNonText", "VisibleText"):
        prop(p, nm, get=lambda this, n=nm: getattr(this, "_" + n, 0), set=lambda this, v, n=nm: None)


def _ih_start(ih):
    ih.in_progress = True
    ih.buf = ""
    ih.started = time.monotonic()
    if ih not in _ACTIVE_HOOKS:
        _ACTIVE_HOOKS.append(ih)
    backend()
    if ih.timeout:
        def check():
            if ih.in_progress and time.monotonic() - ih.started >= ih.timeout:
                _ih_end(ih, "Timeout")
        from .flow import Timer
        t = Timer(O.BuiltinFunc("ih", lambda: check(), 0, 0), -int(ih.timeout * 1000), 0)
        rt().timers.append(t)
    return ""


def _ih_wait(ih, timeout):
    end = None if timeout is UNSET else time.monotonic() + float(rt().to_num(timeout))
    while ih.in_progress:
        if end is not None and time.monotonic() >= end:
            break
        rt().sleep(10)
    return ih.end_reason


@export()
def InputHook(options="", endkeys="", matchlist=""):
    _ih_setup()
    return InputHookObj(S(options), S(endkeys), S(matchlist))


@export()
def CaretGetPos(outx=UNSET, outy=UNSET):
    """The text caret of the focused control in the active window, from AT-SPI (works for GTK, Qt with
    accessibility, LibreOffice, Firefox...); coordinates follow CoordMode "Caret"."""
    pos = _caret_screen_pos()
    if pos is None:
        setref(outx, "")
        setref(outy, "")
        return 0
    from .window import _coord_origin
    ox, oy = _coord_origin("Caret")
    setref(outx, pos[0] - ox)
    setref(outy, pos[1] - oy)
    return 1


def _caret_screen_pos():
    from . import atspi_
    from .window import _dpy, _win_info, active_window
    if not atspi_.available():
        return None
    d = _dpy()
    win = active_window(d) if d is not None else 0
    if not win:
        return None
    root = atspi_.window_accessible(*_win_info(win))
    if root is None:
        return None
    A = atspi_.Atspi()
    stack = [root]
    seen = 0
    while stack and seen < 3000:
        acc = stack.pop()
        seen += 1
        if atspi_._state(acc, "FOCUSED") and "Text" in atspi_._ifaces(acc):
            try:
                off = A.Text.get_caret_offset(acc)
                n = A.Text.get_character_count(acc)
                r = A.Text.get_character_extents(acc, max(0, min(off, n - 1)) if n else 0, A.CoordType.SCREEN)
                if off >= n and n:          # caret after the last character
                    return r.x + r.width, r.y
                if r.width or r.height or n:
                    return r.x, r.y
                e = A.Component.get_extents(acc, A.CoordType.SCREEN)
                return e.x, e.y
            except Exception:
                return None
        stack.extend(atspi_._children(acc))
    return None
