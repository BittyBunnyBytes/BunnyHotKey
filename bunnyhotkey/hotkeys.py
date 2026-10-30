"""Hotkey syntax (Hotkey::TextInterpret) and the shared matching engine (hook.cpp).

Both backends feed raw key/button events into HookEngine.on_event(), which decides,
like LowLevelKeybdProc, whether the event triggers a hotkey and whether it must be
suppressed.  The X11 backend can only suppress keys it grabbed; the evdev backend
suppresses anything (true hook semantics).
"""
from __future__ import annotations

import re
import threading
import collections
import time
from dataclasses import dataclass, field

from . import keys as K

MOD_CHARS = {"^": "ctrl", "+": "shift", "!": "alt", "#": "win"}
# KeyHistory: the most recent physical events (#KeyHistory N sets the size; AutoHotkey's default is 40)
KEY_HISTORY: collections.deque = collections.deque(maxlen=40)


@dataclass
class HotkeySpec:
    text: str
    key: K.Key
    prefix: K.Key | None = None       # for "a & b"
    mods: dict = field(default_factory=dict)   # mod -> 'L' | 'R' | '' (either)
    wildcard: bool = False
    passthrough: bool = False          # ~
    prefix_passthrough: bool = False   # ~a & b
    use_hook: bool = False             # $
    up: bool = False

    @property
    def ident(self) -> str:
        """Identity used by Hotkey() to find an existing hotkey (case-insensitive name)."""
        return self.text.lower()


def _split_key(text: str):
    return text


def parse_hotkey(text: str) -> HotkeySpec | None:
    """Parse a hotkey name such as '^!a', '~LButton & WheelUp', '*F1 up', '<#Space'."""
    raw = text
    s = text
    if " & " in s or "\t&\t" in s:
        left, right = re.split(r"\s+&\s+", s, maxsplit=1)
        pfx_pass = left.startswith("~")
        left = left.lstrip("~")
        right_spec = _parse_single(right)
        pk = K.lookup(left.strip())
        if right_spec is None or pk is None or right_spec.mods:
            return None
        right_spec.text = raw
        right_spec.prefix = pk
        right_spec.prefix_passthrough = pfx_pass
        right_spec.passthrough = right_spec.passthrough or pfx_pass and False
        return right_spec
    spec = _parse_single(s)
    if spec:
        spec.text = raw
    return spec


def _parse_single(s: str) -> HotkeySpec | None:
    mods: dict = {}
    wildcard = passthrough = use_hook = False
    i = 0
    side = ""
    s = s.strip(" \t")
    up = False
    m = re.search(r"\s+up$", s, re.I)
    if m and len(s) > m.end() - m.start():
        up = True
        s = s[:m.start()]
    while i < len(s) - 1:
        c = s[i]
        if c in "<>":
            side = "L" if c == "<" else "R"
        elif c in MOD_CHARS:
            mods[MOD_CHARS[c]] = side
            side = ""
        elif c == "*":
            wildcard = True
        elif c == "~":
            passthrough = True
        elif c == "$":
            use_hook = True
        else:
            break
        i += 1
    name = s[i:]
    key = K.lookup(name)
    if key is None:
        return None
    return HotkeySpec(s, key, None, mods, wildcard, passthrough, False, use_hook, up)


def looks_like_hotkey(text: str) -> bool:
    if not text or text.strip() != text and not text.endswith(" "):
        pass
    try:
        return parse_hotkey(text) is not None
    except Exception:
        return False


# ---------------------------------------------------------------- matching engine

class Variant:
    """One #HotIf variant of a hotkey (Hotkey::mFirstVariant chain)."""

    def __init__(self, callback, criterion, max_threads=1, input_level=0, suspend_exempt=False):
        self.callback = callback
        self.criterion = criterion      # None or callable() -> bool, evaluated in the script thread
        self.enabled = True
        self.max_threads = max_threads
        self.running = 0
        self.input_level = input_level
        self.suspend_exempt = suspend_exempt


class Hotkey:
    def __init__(self, spec: HotkeySpec):
        self.spec = spec
        self.name = spec.text
        self.variants: list[Variant] = []


def _mods_match(spec: HotkeySpec, state: dict[str, set]) -> bool:
    """state: mod -> set of sides currently down ({'L','R'})."""
    for mod in ("ctrl", "shift", "alt", "win"):
        want = spec.mods.get(mod)
        have = state.get(mod, set())
        if want is None:
            if have and not spec.wildcard:
                # A key that is itself this modifier (e.g. "LCtrl up") doesn't count.
                if spec.key.kind == "key" and K.MOD_KEYS.get(spec.key.code) == mod:
                    continue
                return False
        elif want == "":
            if not have:
                return False
        elif want not in have:
            return False
    return True


class HookEngine:
    """Decides hotkey firing/suppression from a stream of physical input events."""

    def __init__(self, runtime):
        self.rt = runtime
        self.hotkeys: list[Hotkey] = []
        self.lock = threading.RLock()
        self.down: dict[int, float] = {}         # physical keys/buttons currently down (evdev codes)
        self.suppressed_down: set[int] = set()   # codes whose down was suppressed -> suppress their up
        self.prefix_used: set[int] = set()       # prefix keys that were used in a combination
        self.prefix_down_fired: dict[int, Hotkey] = {}
        # key-up hotkey chosen when its down hotkey fired (AHK's hotkey_to_fire_upon_release): the release of a
        # remap like `#HotIf WinActive(...)` + `a::b` still fires after the window changed, or b would stay down
        self.fire_upon_release: dict[int, tuple] = {}
        self.suspended = False

    # --- registry ---
    def find(self, name: str) -> Hotkey | None:
        spec = parse_hotkey(name)
        if not spec:
            return None
        for hk in self.hotkeys:
            if _same(hk.spec, spec):
                return hk
        return None

    def add(self, spec: HotkeySpec) -> Hotkey:
        for hk in tuple(self.hotkeys):
            if _same(hk.spec, spec):
                return hk
        hk = Hotkey(spec)
        self.hotkeys = self.hotkeys + [hk]      # copy-on-write: the hook thread iterates snapshots
        return hk

    def prefixes(self) -> set[int]:
        return {hk.spec.prefix.code for hk in self.hotkeys if hk.spec.prefix is not None
                and any(v.enabled for v in hk.variants)}

    # --- modifier state helper ---
    def mod_state(self) -> dict[str, set]:
        st: dict[str, set] = {}
        for code in self.down:
            mod = K.MOD_KEYS.get(code)
            if mod and code in self.suppressed_down and self._bare_mod_hotkey(code):
                continue        # swallowed by its own hotkey, so not logically down (g_modifiersLR_logical)
            if mod:
                side = "L" if K.MOD_LEFT[mod] == code else "R"
                st.setdefault(mod, set()).add(side)
        return st

    # --- main entry ---
    def on_event(self, code: int, is_down: bool, kind: str = "key", repeat: bool = False, level=None) -> bool:
        """Process one event.  level is None for physical input, else the SendLevel of an event the script sent.
        Returns True if it must be suppressed."""
        self.event_level = level
        suppressed = self._on_event(code, is_down, kind, repeat)
        hist = globals()["KEY_HISTORY"]
        if hist.maxlen:
            hist.append((time.monotonic(), code, kind, is_down, bool(suppressed)))
        return suppressed

    def _on_event(self, code, is_down, kind, repeat):
        with self.lock:
            if kind == "wheel":
                return self._match_and_fire(code, True, kind)
            if is_down:
                was_down = code in self.down
                self.down.setdefault(code, time.monotonic())
                if was_down and not repeat:
                    repeat = True
                return self._on_down(code, kind, repeat)
            else:
                self.down.pop(code, None)
                return self._on_up(code, kind)

    def _candidates(self, code: int, kind: str, up: bool):
        for hk in tuple(self.hotkeys):
            sp = hk.spec
            if sp.up != up:
                continue
            if sp.key.kind == "wheel":
                if kind != "wheel" or sp.key.code != code:
                    continue
            elif kind == "wheel" or sp.key.code != code:
                if not (sp.key.neutral and K.MOD_KEYS.get(code) == sp.key.neutral):
                    continue
            yield hk

    def _active_variant(self, hk: Hotkey):
        for v in hk.variants:
            if not v.enabled:
                continue
            if self.suspended and not v.suspend_exempt:
                continue
            if v.criterion is None:
                continue
            if self.rt.eval_criterion(v.criterion):
                return v
        for v in hk.variants:
            if v.enabled and v.criterion is None and (not self.suspended or v.suspend_exempt):
                return v
        return None

    def _match_and_fire(self, code, is_down, kind, up=False) -> bool:
        state = self.mod_state()
        prefixes_down = [c for c in self.down if c != code and c in self.prefixes()]
        # combination hotkeys ("a & b") take priority when their prefix is held
        best = None
        for hk in self._candidates(code, kind, up):
            sp = hk.spec
            if sp.prefix is not None:
                if sp.prefix.code not in self.down or sp.prefix.code == code:
                    continue
            elif not _mods_match(sp, state):
                continue
            v = self._active_variant(hk)
            if v is None:
                continue
            if not self._level_ok(hk, v):
                continue
            rank = (sp.prefix is not None, len(sp.mods), not sp.wildcard)
            if best is None or rank > best[0]:
                best = (rank, hk, v)
        if best is None:
            return False
        _, hk, v = best
        if hk.spec.prefix is not None:
            self.prefix_used.add(hk.spec.prefix.code)
        if is_down and not up and kind != "wheel":
            pair = self._up_partner(hk, code, kind)
            if pair:
                self.fire_upon_release[code] = pair
        self.rt.fire_hotkey(hk, v)
        return not hk.spec.passthrough

    def _up_partner(self, hk, code, kind):
        """The key-up hotkey paired with down hotkey `hk` and its variant as of now, or None."""
        sp = hk.spec
        for uh in self._candidates(code, kind, True):
            u = uh.spec
            if (u.mods == sp.mods and u.wildcard == sp.wildcard and u.key.neutral == sp.key.neutral
                    and (u.prefix.code if u.prefix else None) == (sp.prefix.code if sp.prefix else None)):
                v = self._active_variant(uh)
                return (uh, v) if v is not None else None
        return None

    def uses_hook(self, hk: Hotkey, v: Variant) -> bool:
        """Whether AutoHotkey would implement this hotkey with the keyboard hook rather than RegisterHotkey
        (hotkey.cpp Hotkey::Perform/HK_KEYBD_HOOK selection)."""
        sp = hk.spec
        return bool(sp.use_hook or sp.wildcard or sp.passthrough or sp.up or sp.prefix is not None
                    or v.input_level > 0 or self.rt.rt.directives.get("UseHook") or sp.key.kind != "key"
                    or (K.MOD_KEYS.get(sp.key.code) and not sp.mods))

    def _level_ok(self, hk: Hotkey, v: Variant) -> bool:
        """Sent input triggers a hook hotkey only if its SendLevel exceeds the hotkey's #InputLevel; a
        RegisterHotkey hotkey is triggered by any input, which is why AutoHotkey has the $ prefix."""
        level = getattr(self, "event_level", None)
        if level is None:
            return True
        return not self.uses_hook(hk, v) or level > v.input_level

    def _bare_mod_hotkey(self, code) -> bool:
        return any(hk.spec.key.kind == "key" and hk.spec.prefix is None and not hk.spec.mods and not hk.spec.up
                   and (hk.spec.key.code == code or K.MOD_KEYS.get(code) == hk.spec.key.neutral)
                   for hk in self.hotkeys)

    def _on_down(self, code, kind, repeat) -> bool:
        prefixes = self.prefixes()
        if code in prefixes and not repeat:
            self.prefix_used.discard(code)
        suppress = self._match_and_fire(code, True, kind)
        if code in prefixes:
            # A prefix key's own function is suppressed (fires on release if unused),
            # unless every combination using it has the ~ prefix.
            pass_native = all(hk.spec.prefix_passthrough for hk in self.hotkeys
                              if hk.spec.prefix is not None and hk.spec.prefix.code == code)
            if not pass_native:
                suppress = True
        if suppress:
            self.suppressed_down.add(code)
        return suppress

    def _on_up(self, code, kind) -> bool:
        suppress = code in self.suppressed_down
        self.suppressed_down.discard(code)
        pending = self.fire_upon_release.pop(code, None)
        if pending and pending[1].enabled and pending[0] in self.hotkeys:
            self.rt.fire_hotkey(*pending)
            fired_up = not pending[0].spec.passthrough
        else:
            fired_up = self._match_and_fire(code, False, kind, up=True)
        if code in self.prefixes():
            if code not in self.prefix_used:
                # prefix used alone: fire its own non-combination hotkey on release, or replay it
                if not self._fire_plain_prefix(code):
                    pass_native = all(hk.spec.prefix_passthrough for hk in self.hotkeys
                                      if hk.spec.prefix is not None and hk.spec.prefix.code == code)
                    if not pass_native:
                        self.rt.replay_key(code)
            self.prefix_used.discard(code)
        return suppress or fired_up

    def _fire_plain_prefix(self, code) -> bool:
        # Plain hotkeys for a prefix key are deferred until release (AHK behaviour)
        return False


def _same(a: HotkeySpec, b: HotkeySpec) -> bool:
    return (a.key.code == b.key.code and a.key.kind == b.key.kind and a.mods == b.mods
            and a.up == b.up and a.wildcard == b.wildcard
            and (a.prefix.code if a.prefix else None) == (b.prefix.code if b.prefix else None)
            and a.key.neutral == b.key.neutral)
