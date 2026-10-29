"""X11 backend: hotkeys via synchronous passive grabs, observation via XInput2 raw events, output via XTest.

Mapping to AutoHotkey's design (hook.cpp / hotkey.cpp):
  * A hotkey without ~ is a passive grab in GrabModeSync.  When it triggers, the
    HookEngine decides (including #HotIf criteria) whether to consume it
    (XAllowEvents AsyncKeyboard) or hand it to the focused app (ReplayKeyboard).
  * ~hotkeys, hotstrings, InputHook, A_PriorKey, GetKeyState("P") use XI2 raw
    events, which X delivers for every physical device regardless of grabs.
  * XTest is the SendInput equivalent; injected events are told apart from
    physical ones by the XTEST slave device id.
  * A bare modifier hotkey (LWin::, RCtrl::) grabs the key, and while it is unconditional the keycode is taken
    out of the modifier map (backends/modmap.py), so Win+E reaches the app as a plain "e", as on Windows.
  * Sent input is tagged with its SendLevel, so hook hotkeys, hotstrings and InputHooks apply AutoHotkey's
    SendLevel/#InputLevel/MinSendLevel rules, while RegisterHotkey-style hotkeys see any sent input.
"""
from __future__ import annotations

import ctypes
import os
import select
import threading
import time

from .. import keys as K
from .. import xlib
from ..xlib import byref

MOD_MASK = {"ctrl": xlib.ControlMask, "shift": xlib.ShiftMask, "alt": xlib.Mod1Mask, "win": xlib.Mod4Mask}
LOCK_COMBOS = (0, xlib.LockMask, xlib.Mod2Mask, xlib.LockMask | xlib.Mod2Mask)
BUTTON_OF = {"LButton": 1, "MButton": 2, "RButton": 3, "XButton1": 8, "XButton2": 9}
WHEEL_OF = {"WheelUp": 4, "WheelDown": 5, "WheelLeft": 6, "WheelRight": 7}
CODE_OF_BUTTON = {1: 0x110, 2: 0x112, 3: 0x111, 8: 0x113, 9: 0x114}


class _XIDeviceInfo(ctypes.Structure):
    _fields_ = [("deviceid", ctypes.c_int), ("name", ctypes.c_char_p), ("use", ctypes.c_int),
                ("attachment", ctypes.c_int), ("enabled", ctypes.c_int), ("num_classes", ctypes.c_int),
                ("classes", ctypes.c_void_p)]


class X11Backend:
    name = "x11"
    can_suppress = False      # hotstring keystrokes cannot be suppressed on X11

    def __init__(self, rt):
        self.rt = rt
        self.ev = None             # event-thread display
        self.inj = None            # injection display (any thread, locked)
        self.inj_lock = threading.RLock()
        self.thread = None
        self.running = False
        self.wake_r, self.wake_w = os.pipe()
        self.grabbed_keys: dict[tuple, bool] = {}     # (keycode, mods) -> True
        self.grabbed_codes: set[int] = set()
        self.grabbed_buttons: dict[tuple, bool] = {}
        self.phys_down: set[int] = set()
        self.last_input = time.monotonic()
        self.xtest_ids: set[int] = set()
        import collections
        self.sent = collections.deque()          # injected key events awaiting their raw/grabbed echo
        self.sent_down: set[int] = set()         # keys the script is holding down via XTest
        from .modmap import ModifierBlock
        self.modblock = ModifierBlock()
        self.mod_released: set[int] = set()      # suppressed modifiers whose keyboard grab was let go
        self.hs_fed: set[int] = set()            # grabbed end-char keys already fed to the hotstring recognizer
        self.end_codes: set[int] = set()
        self.xi_opcode = None
        self.need_refresh = threading.Event()
        self.spare_keycode = None
        self.shift = False

    # ------------------------------------------------------------ lifecycle
    def start(self):
        self.inj = xlib.Display()
        self.ev = xlib.Display()
        x = self.ev.x
        try:
            x.XkbSetDetectableAutoRepeat.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            x.XkbSetDetectableAutoRepeat(self.ev.dpy, 1, None)
        except AttributeError:
            pass
        self._setup_xi2()
        self.running = True
        self.thread = threading.Thread(target=self._loop, name="bhk-x11", daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        os.write(self.wake_w, b"q")
        if self.thread:
            self.thread.join(1.0)
        if self.modblock.removed:
            try:
                self.modblock.restore(xlib.Display())
            except OSError:
                pass

    def refresh(self):
        self.need_refresh.set()
        try:
            os.write(self.wake_w, b"r")
        except OSError:
            pass

    # ------------------------------------------------------------ XI2
    def _setup_xi2(self):
        d = self.ev
        op = ctypes.c_int()
        ev_ = ctypes.c_int()
        err = ctypes.c_int()
        if not d.x.XQueryExtension(d.dpy, b"XInputExtension", byref(op), byref(ev_), byref(err)):
            return
        xi = xlib.Xi()
        if xi is None:
            return
        self.xi_opcode = op.value
        try:
            xi.XIQueryDevice.restype = ctypes.POINTER(_XIDeviceInfo)
            xi.XIQueryDevice.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
            n = ctypes.c_int()
            info = xi.XIQueryDevice(d.dpy, xlib.XIAllDevices, byref(n))
            for i in range(n.value):
                nm = (info[i].name or b"").decode(errors="replace")
                if "XTEST" in nm.upper():
                    self.xtest_ids.add(info[i].deviceid)
        except AttributeError:
            pass
        mask_bytes = (ctypes.c_ubyte * 4)()
        for bit in (xlib.XI_RawKeyPress, xlib.XI_RawKeyRelease, xlib.XI_RawButtonPress, xlib.XI_RawButtonRelease):
            mask_bytes[bit >> 3] |= 1 << (bit & 7)
        m = xlib.XIEventMask(xlib.XIAllMasterDevices, 4, ctypes.cast(mask_bytes, ctypes.POINTER(ctypes.c_ubyte)))
        xi.XISelectEvents(d.dpy, d.root, byref(m), 1)
        d.flush()

    # ------------------------------------------------------------ grabs
    def _apply_grabs(self):
        d = self.ev
        x = d.x
        hk_engine = self.rt.hotkeys
        want_keys: dict[tuple, bool] = {}
        want_buttons: dict[tuple, bool] = {}
        codes = set()
        block: set[int] = set()
        if hk_engine is not None:
            for hk in tuple(hk_engine.hotkeys):
                sp = hk.spec
                if not any(v.enabled for v in hk.variants):
                    continue
                if sp.passthrough:
                    continue
                bare_mod = sp.key.kind == "key" and sp.prefix is None and not sp.mods and \
                    (K.MOD_KEYS.get(sp.key.code) or sp.key.neutral)
                if bare_mod:
                    # LWin:: etc.: grab under any modifier state; unconditional ones also leave the modifier map
                    masks = [xlib.AnyModifier]
                    if not sp.up and all(v.criterion is None for v in hk.variants if v.enabled):
                        if sp.key.neutral:
                            block |= {K.MOD_LEFT[sp.key.neutral] + 8, K.MOD_RIGHT[sp.key.neutral] + 8}
                        else:
                            block.add(sp.key.code + 8)
                else:
                    masks = [xlib.AnyModifier] if sp.wildcard or sp.prefix is not None else \
                        [sum(MOD_MASK[m] for m in sp.mods) | lk for lk in LOCK_COMBOS]
                if sp.key.kind == "key":
                    kc = sp.key.code + 8
                    if sp.key.neutral:
                        kcs = [K.MOD_LEFT[sp.key.neutral] + 8, K.MOD_RIGHT[sp.key.neutral] + 8]
                    else:
                        kcs = [kc]
                    for kc in kcs:
                        for mk in masks:
                            want_keys[(kc, mk)] = True
                        codes.add(kc - 8)
                else:
                    btn = BUTTON_OF.get(sp.key.name) or WHEEL_OF.get(sp.key.name)
                    if btn:
                        for mk in masks:
                            want_buttons[(btn, mk)] = True
        for key in list(self.grabbed_keys):
            if key not in want_keys and not (key[1] == xlib.AnyModifier and
                                             key[0] - 8 in getattr(self, "end_codes", set())):
                x.XUngrabKey(d.dpy, key[0], key[1], d.root)
                del self.grabbed_keys[key]
        for key in want_keys:
            if key not in self.grabbed_keys:
                x.XGrabKey(d.dpy, key[0], key[1], d.root, 1, xlib.GrabModeAsync, xlib.GrabModeSync)
                self.grabbed_keys[key] = True
        for key in list(self.grabbed_buttons):
            if key not in want_buttons:
                x.XUngrabButton(d.dpy, key[0], key[1], d.root)
                del self.grabbed_buttons[key]
        for key in want_buttons:
            if key not in self.grabbed_buttons:
                x.XGrabButton(d.dpy, key[0], key[1], d.root, 1, xlib.ButtonPressMask | xlib.ButtonReleaseMask,
                              xlib.GrabModeSync, xlib.GrabModeAsync, 0, 0)
                self.grabbed_buttons[key] = True
        # hotstring end characters: grabbed so a hotstring can swallow its end key (Enter, Tab, Space...) as the
        # hook does on Windows; replayed to the app otherwise
        end_codes = set()
        hs = self.rt.hotstrings
        if hs is not None and any(h.enabled and not h.asterisk for h in hs.items):
            from .. import layout
            for ch in set(hs.end_chars) | {" ", "\n", "\t"}:
                k = layout.char_to_key(ch) if ch not in " \n\t" else None
                kc = {" ": 57, "\n": 28, "\t": 15}.get(ch) or (k[0] if k else None)
                if kc and kc + 8 not in {kk for kk, _ in want_keys}:
                    end_codes.add(kc)
            if 28 in end_codes:
                end_codes.add(96)          # NumpadEnter
        if hs is not None:
            # "*" hotstrings fire on their last character, which the hook swallows: grab just those keys
            from .. import layout
            for h in hs.items:
                if h.enabled and h.asterisk and h.trigger and h.backspace:
                    for ch in {h.trigger[-1], h.trigger[-1].lower(), h.trigger[-1].upper()}:
                        k = layout.char_to_key(ch)
                        if k and k[0] + 8 not in {kk for kk, _ in want_keys}:
                            end_codes.add(k[0])
        for kc in end_codes:
            key = (kc + 8, xlib.AnyModifier)
            if key not in self.grabbed_keys:
                x.XGrabKey(d.dpy, key[0], key[1], d.root, 1, xlib.GrabModeAsync, xlib.GrabModeSync)
                self.grabbed_keys[key] = True
        for key in list(self.grabbed_keys):
            if key[1] == xlib.AnyModifier and key[0] - 8 in getattr(self, "end_codes", set()) and \
                    key[0] - 8 not in end_codes and key not in want_keys:
                x.XUngrabKey(d.dpy, key[0], key[1], d.root)
                del self.grabbed_keys[key]
        self.end_codes = end_codes
        codes |= end_codes
        self.grabbed_codes = codes
        d.flush()
        try:
            self.modblock.apply(d, block)
        except Exception as e:      # never break hotkeys over the modifier map
            import sys
            print(f"bhk x11 backend: modifier map: {e!r}", file=sys.stderr)

    # ------------------------------------------------------------ event loop
    def _loop(self):
        d = self.ev
        x = d.x
        fd = x.XConnectionNumber(d.dpy)
        ev = xlib.XEvent()
        self._apply_grabs()
        while self.running:
            if self.need_refresh.is_set():
                self.need_refresh.clear()
                self._apply_grabs()
            if not x.XPending(d.dpy):
                r, _, _ = select.select([fd, self.wake_r], [], [], 0.5)
                if self.wake_r in r:
                    os.read(self.wake_r, 64)
                continue
            x.XNextEvent(d.dpy, byref(ev))
            t = ev.type
            try:
                if t == xlib.KeyPress or t == xlib.KeyRelease:
                    self._on_grabbed_key(ev.xkey, t == xlib.KeyPress)
                elif t == xlib.ButtonPress or t == xlib.ButtonRelease:
                    self._on_grabbed_button(ev.xbutton, t == xlib.ButtonPress)
                elif t == xlib.GenericEvent and ev.xcookie.extension == self.xi_opcode:
                    if x.XGetEventData(d.dpy, byref(ev.xcookie)):
                        try:
                            raw = ctypes.cast(ev.xcookie.data, ctypes.POINTER(xlib.XIRawEvent)).contents
                            self._on_raw(ev.xcookie.evtype, raw)
                        finally:
                            x.XFreeEventData(d.dpy, byref(ev.xcookie))
            except Exception as e:     # never leave the keyboard frozen
                import sys
                print(f"bhk x11 backend: {e!r}", file=sys.stderr)
                if t in (xlib.KeyPress, xlib.KeyRelease):
                    x.XAllowEvents(d.dpy, xlib.ReplayKeyboard, xlib.CurrentTime)
                elif t in (xlib.ButtonPress, xlib.ButtonRelease):
                    x.XAllowEvents(d.dpy, xlib.ReplayPointer, xlib.CurrentTime)
                d.flush()

    def _on_grabbed_key(self, kev, down):
        d = self.ev
        code = kev.keycode - 8
        engine = self.rt.hotkeys
        level = self.sent_level(code, down, 5)
        suppress = engine.on_event(code, down, level=level) if engine is not None else False
        if down and not suppress and code in getattr(self, "end_codes", ()):
            hs = self.rt.hotstrings
            ch = self._char_for(code, level)
            if hs is not None and ch:
                suppress = hs.on_char(ch, True, level)
                self.hs_fed.add(code)
        if down and suppress and K.MOD_KEYS.get(code):
            # a suppressed bare modifier: swallow it, then let go of the keyboard so keys pressed while it is
            # held reach the focused app (the hook only blocks the modifier itself on Windows)
            d.x.XAllowEvents(d.dpy, xlib.AsyncKeyboard, kev.time)
            d.x.XUngrabKeyboard(d.dpy, kev.time)
            self.mod_released.add(code)
        elif down:
            d.x.XAllowEvents(d.dpy, xlib.AsyncKeyboard if suppress else xlib.ReplayKeyboard, kev.time)
        else:
            d.x.XAllowEvents(d.dpy, xlib.AsyncKeyboard, kev.time)
            if not suppress and code not in engine.suppressed_down:
                pass
        d.flush()

    def _on_grabbed_button(self, bev, down):
        d = self.ev
        btn = bev.keycode
        engine = self.rt.hotkeys
        if btn in (4, 5, 6, 7):
            suppress = engine.on_event(btn, True, kind="wheel") if down else True
        else:
            code = CODE_OF_BUTTON.get(btn, 0)
            suppress = engine.on_event(code, down, kind="mouse")
        d.x.XAllowEvents(d.dpy, xlib.AsyncPointer if suppress else xlib.ReplayPointer, bev.time)
        d.flush()

    def _on_raw(self, evtype, raw):
        if raw.sourceid in self.xtest_ids:
            # input this script sent: only SendLevel > 0 reaches ~hotkeys, hotstrings and InputHooks
            if evtype in (xlib.XI_RawKeyPress, xlib.XI_RawKeyRelease):
                code = raw.detail - 8
                down = evtype == xlib.XI_RawKeyPress
                level = self.sent_level(code, down, 4)
                (self.sent_down.add if down else self.sent_down.discard)(code)
                engine = self.rt.hotkeys
                if not down and code in self.mod_released and engine is not None:
                    self.mod_released.discard(code)
                    engine.on_event(code, False, level=level)
                    return
                if level and engine is not None and code not in self.grabbed_codes:
                    engine.on_event(code, down, level=level)
                if level and down:
                    self._typed(code, code in self.grabbed_codes, level)
            return
        self.last_input = time.monotonic()
        engine = self.rt.hotkeys
        if evtype in (xlib.XI_RawKeyPress, xlib.XI_RawKeyRelease):
            code = raw.detail - 8
            down = evtype == xlib.XI_RawKeyPress
            repeat = bool(raw.flags & (1 << 16))
            (self.phys_down.add if down else self.phys_down.discard)(code)
            grabbed = code in self.grabbed_codes
            if engine is not None and not grabbed:
                engine.on_event(code, down, repeat=repeat)
            elif engine is not None and not down and code in self.mod_released:
                self.mod_released.discard(code)  # its release went to the app after the grab was let go
                engine.on_event(code, False)
            elif engine is not None and not down:
                engine.down.pop(code, None)      # a replayed grabbed key's release went to the app
            if down:
                self._typed(code, grabbed)
        else:
            btn = raw.detail
            down = evtype == xlib.XI_RawButtonPress
            if btn in (4, 5, 6, 7):
                if down and engine is not None and not any(b == btn for b, _ in self.grabbed_buttons):
                    engine.on_event(btn, True, kind="wheel")
                return
            code = CODE_OF_BUTTON.get(btn)
            if code is None:
                return
            (self.phys_down.add if down else self.phys_down.discard)(code)
            if engine is not None and not any(b == btn for b, _ in self.grabbed_buttons):
                engine.on_event(code, down, kind="mouse")
            if down:
                hs = self.rt.hotstrings
                if hs is not None and hs.mouse_reset:
                    hs.reset()

    def _char_for(self, code, level=None):
        """The character a key press produces with the current modifiers ("" for none)."""
        held = self.phys_down | self.sent_down if level else self.phys_down
        if any(c in held for c in (29, 97, 56, 125, 126)):
            return ""
        if code == 14:
            return "\b"
        if code in (28, 96):
            return "\n"
        if code == 15:
            return "\t"
        from .. import layout
        shift = any(c in held for c in (42, 54))
        ch = layout.code_to_char(code, shift) or (K._US_BY_CODE.get(code, "") if not shift else "")
        if self.toggle_state("CapsLock") and ch.isalpha():
            ch = ch.swapcase()
        return ch

    def _typed(self, code, grabbed, level=None):
        """Feed the hotstring recognizer / InputHooks with the character this key produced (level: SendLevel of
        sent input, None for physical)."""
        rt = self.rt
        k = K.from_code(code)
        name = k.name if k else ""
        held = self.phys_down | self.sent_down if level else self.phys_down
        shift = any(c in held for c in (42, 54))
        ctrl_alt = any(c in held for c in (29, 97, 56, 125, 126))
        hs = rt.hotstrings
        if code == 14:
            ch = "\b"
        elif code in (28, 96):
            ch = "\n"
        elif code == 15:
            ch = "\t"
        elif ctrl_alt:
            ch = ""
        else:
            from .. import layout
            ch = layout.code_to_char(code, shift) or (K._US_BY_CODE.get(code, "") if not shift else "")
            caps = self.toggle_state("CapsLock")
            if caps and ch.isalpha():
                ch = ch.swapcase()
        from ..lib.input_ import input_hook_char, _ACTIVE_HOOKS
        if _ACTIVE_HOOKS:
            input_hook_char(ch if ch not in ("\b",) else "", name, level)
        if hs is None:
            return
        if code in (103, 108, 105, 106, 102, 107, 104, 109) or ctrl_alt and not ch:
            hs.reset()
            return
        if code in self.hs_fed:
            self.hs_fed.discard(code)      # the grab path already gave this key to the hotstring recognizer
        elif ch and not grabbed:
            hs.on_char(ch, False, level)

    # ------------------------------------------------------------ output
    def _x(self):
        return self.inj

    def key(self, code, down):
        t = xlib.Xtst()
        try:
            level = self.rt.thread.settings.send_level
        except AttributeError:
            level = 0
        with self.inj_lock:
            self.sent.append([code, bool(down), level, time.monotonic(), False, False])
            t.XTestFakeKeyEvent(self.inj.dpy, code + 8, 1 if down else 0, 0)

    def sent_level(self, code, down, path):
        """SendLevel of a key event this process injected (None if it is physical input).  path is 4 for the
        raw-event stream and 5 for grabbed core events; each injected event shows up once on each."""
        now = time.monotonic()
        with self.inj_lock:
            while self.sent and now - self.sent[0][3] > 2.0:
                self.sent.popleft()
            for e in self.sent:
                if e[0] == code and e[1] == down and not e[path]:
                    e[path] = True
                    return e[2]
        return None

    def tap(self, code):
        self.key(code, True)
        self.key(code, False)
        self.flush()

    def flush(self):
        with self.inj_lock:
            self.inj.x.XFlush(self.inj.dpy)

    def text(self, s):
        """Type characters that have no key on the current layout (temporary keymap entry)."""
        for ch in s:
            ks = ord(ch) if ord(ch) < 0x100 else 0x01000000 | ord(ch)
            with self.inj_lock:
                d = self.inj
                kc = self._spare(d)
                if kc is None:
                    continue
                arr = (ctypes.c_ulong * 2)(ks, ks)
                d.x.XChangeKeyboardMapping(d.dpy, kc, 2, arr, 1)
                d.x.XSync(d.dpy, 0)
                t = xlib.Xtst()
                t.XTestFakeKeyEvent(d.dpy, kc, 1, 0)
                t.XTestFakeKeyEvent(d.dpy, kc, 0, 0)
                d.x.XSync(d.dpy, 0)
                time.sleep(0.01)
                zero = (ctypes.c_ulong * 2)(0, 0)
                d.x.XChangeKeyboardMapping(d.dpy, kc, 2, zero, 1)
                d.x.XSync(d.dpy, 0)

    def _spare(self, d):
        if self.spare_keycode is not None:
            return self.spare_keycode
        lo = ctypes.c_int()
        hi = ctypes.c_int()
        d.x.XDisplayKeycodes(d.dpy, byref(lo), byref(hi))
        per = ctypes.c_int()
        n = hi.value - lo.value + 1
        syms = d.x.XGetKeyboardMapping(d.dpy, lo.value, n, byref(per))
        try:
            for i in range(n - 1, -1, -1):
                if all(syms[i * per.value + j] == 0 for j in range(per.value)):
                    self.spare_keycode = lo.value + i
                    break
        finally:
            d.x.XFree(syms)
        return self.spare_keycode

    def button(self, name, down):
        btn = BUTTON_OF.get(name)
        if not btn:
            return
        t = xlib.Xtst()
        with self.inj_lock:
            t.XTestFakeButtonEvent(self.inj.dpy, btn, 1 if down else 0, 0)

    def wheel(self, name, n):
        btn = WHEEL_OF.get(name)
        t = xlib.Xtst()
        with self.inj_lock:
            for _ in range(max(int(n), 1)):
                t.XTestFakeButtonEvent(self.inj.dpy, btn, 1, 0)
                t.XTestFakeButtonEvent(self.inj.dpy, btn, 0, 0)
            self.inj.x.XFlush(self.inj.dpy)

    def move(self, x, y):
        t = xlib.Xtst()
        with self.inj_lock:
            t.XTestFakeMotionEvent(self.inj.dpy, -1, int(x), int(y), 0)

    def _query_pointer(self):
        d = self.inj
        root = xlib.Window()
        child = xlib.Window()
        rx = ctypes.c_int()
        ry = ctypes.c_int()
        wx = ctypes.c_int()
        wy = ctypes.c_int()
        mask = ctypes.c_uint()
        with self.inj_lock:
            d.x.XQueryPointer(d.dpy, d.root, byref(root), byref(child), byref(rx), byref(ry), byref(wx), byref(wy),
                              byref(mask))
        return rx.value, ry.value, child.value, mask.value

    def mouse_pos(self):
        x, y, _, _ = self._query_pointer()
        return x, y

    def window_under_mouse(self):
        from ..lib.window import _dpy, client_list, geometry, is_visible
        x, y, _, _ = self._query_pointer()
        d = _dpy()
        for w in client_list(d):
            if not is_visible(d, w):
                continue
            gx, gy, gw, gh = geometry(d, w)
            if gx <= x < gx + gw and gy <= y < gy + gh:
                return w
        return 0

    def key_state(self, code, physical=False):
        if physical:
            return code in self.phys_down
        if code >= 0x110:
            _, _, _, mask = self._query_pointer()
            bit = {0x110: 1 << 8, 0x112: 1 << 9, 0x111: 1 << 10}.get(code, 0)
            return bool(mask & bit) if bit else code in self.phys_down
        keys = (ctypes.c_char * 32)()
        with self.inj_lock:
            self.inj.x.XQueryKeymap(self.inj.dpy, keys)
        kc = code + 8
        return bool(keys[kc >> 3][0] & (1 << (kc & 7))) if isinstance(keys[kc >> 3], bytes) else bool(ord(keys[kc >> 3]) & (1 << (kc & 7)))

    def logical_modifiers(self):
        return [c for c in (29, 97, 42, 54, 56, 100, 125, 126) if self.key_state(c)]

    def toggle_state(self, name):
        _, _, _, mask = self._query_pointer()
        n = name.lower()
        if n == "capslock":
            return bool(mask & xlib.LockMask)
        if n == "numlock":
            return bool(mask & xlib.Mod2Mask)
        if n == "scrolllock":
            try:
                d = self.inj
                st = ctypes.c_uint()
                d.x.XkbGetIndicatorState.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint)]
                with self.inj_lock:
                    d.x.XkbGetIndicatorState(d.dpy, 0x100, byref(st))
                return bool(st.value & 4)
            except AttributeError:
                return False
        return False

    def idle_ms(self):
        return int((time.monotonic() - self.last_input) * 1000)
