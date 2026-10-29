"""Key names (globaldata.cpp g_key_to_vk / g_key_to_sc) mapped to Linux input codes.

Every key is identified internally by its Linux evdev code (input-event-codes.h);
X11 keycodes are evdev + 8, so the same table serves both backends.  Windows VK
and SC values are kept so GetKeyVK/GetKeySC/vkNN/scNNN behave like AutoHotkey.
"""
from __future__ import annotations

# name -> (evdev code, VK, SC)
_TABLE = [
    ("Escape", 1, 0x1B, 0x01), ("Esc", 1, 0x1B, 0x01),
    ("Backspace", 14, 0x08, 0x0E), ("BS", 14, 0x08, 0x0E),
    ("Tab", 15, 0x09, 0x0F), ("Enter", 28, 0x0D, 0x1C), ("Space", 57, 0x20, 0x39),
    ("LControl", 29, 0xA2, 0x1D), ("LCtrl", 29, 0xA2, 0x1D),
    ("RControl", 97, 0xA3, 0x11D), ("RCtrl", 97, 0xA3, 0x11D),
    ("LShift", 42, 0xA0, 0x2A), ("RShift", 54, 0xA1, 0x136),
    ("LAlt", 56, 0xA4, 0x38), ("RAlt", 100, 0xA5, 0x138),
    ("LWin", 125, 0x5B, 0x15B), ("RWin", 126, 0x5C, 0x15C),
    ("AppsKey", 127, 0x5D, 0x15D),
    ("CapsLock", 58, 0x14, 0x3A), ("NumLock", 69, 0x90, 0x145), ("ScrollLock", 70, 0x91, 0x46),
    ("PrintScreen", 99, 0x2C, 0x137), ("Pause", 119, 0x13, 0x45), ("CtrlBreak", 119, 0x03, 0x146),
    ("Insert", 110, 0x2D, 0x152), ("Ins", 110, 0x2D, 0x152),
    ("Delete", 111, 0x2E, 0x153), ("Del", 111, 0x2E, 0x153),
    ("Home", 102, 0x24, 0x147), ("End", 107, 0x23, 0x14F),
    ("PgUp", 104, 0x21, 0x149), ("PgDn", 109, 0x22, 0x151),
    ("Up", 103, 0x26, 0x148), ("Down", 108, 0x28, 0x150),
    ("Left", 105, 0x25, 0x14B), ("Right", 106, 0x27, 0x14D),
    ("Numpad0", 82, 0x60, 0x52), ("Numpad1", 79, 0x61, 0x4F), ("Numpad2", 80, 0x62, 0x50),
    ("Numpad3", 81, 0x63, 0x51), ("Numpad4", 75, 0x64, 0x4B), ("Numpad5", 76, 0x65, 0x4C),
    ("Numpad6", 77, 0x66, 0x4D), ("Numpad7", 71, 0x67, 0x47), ("Numpad8", 72, 0x68, 0x48),
    ("Numpad9", 73, 0x69, 0x49),
    ("NumpadIns", 82, 0x2D, 0x52), ("NumpadEnd", 79, 0x23, 0x4F), ("NumpadDown", 80, 0x28, 0x50),
    ("NumpadPgDn", 81, 0x22, 0x51), ("NumpadLeft", 75, 0x25, 0x4B), ("NumpadClear", 76, 0x0C, 0x4C),
    ("NumpadRight", 77, 0x27, 0x4D), ("NumpadHome", 71, 0x24, 0x47), ("NumpadUp", 72, 0x26, 0x48),
    ("NumpadPgUp", 73, 0x21, 0x49), ("NumpadDot", 83, 0x6E, 0x53), ("NumpadDel", 83, 0x2E, 0x53),
    ("NumpadDiv", 98, 0x6F, 0x135), ("NumpadMult", 55, 0x6A, 0x37), ("NumpadAdd", 78, 0x6B, 0x4E),
    ("NumpadSub", 74, 0x6D, 0x4A), ("NumpadEnter", 96, 0x0D, 0x11C),
    ("Help", 138, 0x2F, 0), ("Sleep", 142, 0x5F, 0),
    ("Browser_Back", 158, 0xA6, 0x16A), ("Browser_Forward", 159, 0xA7, 0x169),
    ("Browser_Refresh", 173, 0xA8, 0x167), ("Browser_Stop", 128, 0xA9, 0x168),
    ("Browser_Search", 217, 0xAA, 0x165), ("Browser_Favorites", 156, 0xAB, 0x166),
    ("Browser_Home", 172, 0xAC, 0x132),
    ("Volume_Mute", 113, 0xAD, 0x120), ("Volume_Down", 114, 0xAE, 0x12E), ("Volume_Up", 115, 0xAF, 0x130),
    ("Media_Next", 163, 0xB0, 0x119), ("Media_Prev", 165, 0xB1, 0x110),
    ("Media_Stop", 166, 0xB2, 0x124), ("Media_Play_Pause", 164, 0xB3, 0x122),
    ("Launch_Mail", 155, 0xB4, 0x16C), ("Launch_Media", 226, 0xB5, 0x16D),
    ("Launch_App1", 157, 0xB6, 0x16B), ("Launch_App2", 140, 0xB7, 0x121),
]
for _i in range(1, 11):
    _TABLE.append((f"F{_i}", 58 + _i, 0x6F + _i, 0x3A + _i))
_TABLE += [("F11", 87, 0x7A, 0x57), ("F12", 88, 0x7B, 0x58)]
for _i in range(13, 25):
    _TABLE.append((f"F{_i}", 183 + _i - 13, 0x7C + _i - 13, 0x64 + _i - 13))

# Neutral modifiers: evdev code of the left key, but marked neutral for matching.
NEUTRAL = {"control": (29, 0x11), "ctrl": (29, 0x11), "shift": (42, 0x10), "alt": (56, 0x12)}

# US-layout character keys, used when no keyboard layout information is available.
US_CHARS = {
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
    "-": 12, "=": 13, "q": 16, "w": 17, "e": 18, "r": 19, "t": 20, "y": 21, "u": 22, "i": 23,
    "o": 24, "p": 25, "[": 26, "]": 27, "a": 30, "s": 31, "d": 32, "f": 33, "g": 34, "h": 35,
    "j": 36, "k": 37, "l": 38, ";": 39, "'": 40, "`": 41, "\\": 43, "z": 44, "x": 45, "c": 46,
    "v": 47, "b": 48, "n": 49, "m": 50, ",": 51, ".": 52, "/": 53, " ": 57,
}
US_SHIFTED = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
    "_": "-", "+": "=", "{": "[", "}": "]", ":": ";", '"': "'", "~": "`", "|": "\\", "<": ",",
    ">": ".", "?": "/",
}
_CHAR_VK = {";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0,
            "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE}

# Mouse buttons: name -> (evdev BTN code, X11 button number, VK)
MOUSE = {
    "lbutton": (0x110, 1, 0x01), "rbutton": (0x111, 3, 0x02), "mbutton": (0x112, 2, 0x04),
    "xbutton1": (0x113, 8, 0x05), "xbutton2": (0x114, 9, 0x06),
}
WHEEL = {"wheelup": (4, 0x9F), "wheeldown": (5, 0x9E), "wheelleft": (6, 0x9C), "wheelright": (7, 0x9D)}

BY_NAME: dict[str, tuple[int, int, int]] = {}
BY_CODE: dict[int, str] = {}
BY_VK: dict[int, str] = {}
for _name, _code, _vk, _sc in _TABLE:
    BY_NAME.setdefault(_name.lower(), (_code, _vk, _sc))
    BY_CODE.setdefault(_code, _name)
    BY_VK.setdefault(_vk, _name)
_US_BY_CODE = {v: k for k, v in US_CHARS.items()}

MOD_KEYS = {29: "ctrl", 97: "ctrl", 42: "shift", 54: "shift", 56: "alt", 100: "alt", 125: "win", 126: "win"}
MOD_SYMBOL = {"ctrl": "^", "shift": "+", "alt": "!", "win": "#"}
MOD_LEFT = {"ctrl": 29, "shift": 42, "alt": 56, "win": 125}
MOD_RIGHT = {"ctrl": 97, "shift": 54, "alt": 100, "win": 126}


class Key:
    """A resolved key: keyboard (code), mouse button, or wheel."""
    __slots__ = ("kind", "code", "vk", "sc", "name", "char", "neutral")

    def __init__(self, kind, code, vk=0, sc=0, name="", char="", neutral=None):
        self.kind = kind      # 'key' | 'mouse' | 'wheel'
        self.code = code      # evdev code (key/mouse) or X11 button (wheel)
        self.vk = vk
        self.sc = sc
        self.name = name
        self.char = char
        self.neutral = neutral   # 'ctrl'/'shift'/'alt' for Ctrl/Shift/Alt names

    def __repr__(self):
        return f"Key({self.name})"


def char_to_code(ch: str):
    """(evdev code, needs_shift) for a character on the active layout, else None."""
    from . import layout
    hit = layout.char_to_key(ch)
    if hit:
        return hit
    low = ch.lower()
    if low in US_CHARS:
        return US_CHARS[low], ch != low
    if ch in US_SHIFTED:
        return US_CHARS[US_SHIFTED[ch]], True
    return None


def lookup(name: str) -> Key | None:
    """Resolve an AHK key name (GetKeyName/TextToVK/TextToSC semantics)."""
    if not name:
        return None
    low = name.lower()
    if low in MOUSE:
        code, btn, vk = MOUSE[low]
        return Key("mouse", code, vk, 0, _canon_mouse(low))
    if low in WHEEL:
        btn, vk = WHEEL[low]
        return Key("wheel", btn, vk, 0, _canon_mouse(low))
    if low in NEUTRAL:
        code, vk = NEUTRAL[low]
        canon = {"control": "Ctrl", "ctrl": "Ctrl", "shift": "Shift", "alt": "Alt"}[low]
        return Key("key", code, vk, BY_NAME.get("l" + ("ctrl" if canon == "Ctrl" else canon.lower()), (0, 0, 0))[2],
                   canon, neutral={"Ctrl": "ctrl", "Shift": "shift", "Alt": "alt"}[canon])
    if low in ("win",):
        return Key("key", 125, 0x5B, 0x15B, "LWin", neutral="win")
    if low in BY_NAME:
        code, vk, sc = BY_NAME[low]
        return Key("key", code, vk, sc, BY_CODE.get(code, name) if low not in _KEEP_NAME else _KEEP_NAME[low])
    if low.startswith("vk") and len(low) >= 3:
        try:
            rest = low[2:]
            sc_part = None
            if "sc" in rest:
                rest, sc_part = rest.split("sc", 1)
            vk = int(rest, 16)
        except ValueError:
            vk = None
        if vk is not None:
            k = from_vk(vk)
            if k is not None:
                if sc_part:
                    k.sc = int(sc_part, 16)
                return k
    if low.startswith("sc") and len(low) >= 3:
        try:
            sc = int(low[2:], 16)
        except ValueError:
            sc = None
        if sc is not None:
            return from_sc(sc)
    if len(name) == 1:
        hit = char_to_code(name)
        if hit:
            code, _shift = hit
            vk = ord(name.upper()) if name.isalnum() and name.isascii() else _CHAR_VK.get(_US_BY_CODE.get(code, ""), 0)
            return Key("key", code, vk, code if code < 0x80 else 0, name.lower(), char=name.lower())
    return None


_KEEP_NAME = {"numpadins": "NumpadIns", "numpadend": "NumpadEnd", "numpaddown": "NumpadDown",
              "numpadpgdn": "NumpadPgDn", "numpadleft": "NumpadLeft", "numpadclear": "NumpadClear",
              "numpadright": "NumpadRight", "numpadhome": "NumpadHome", "numpadup": "NumpadUp",
              "numpadpgup": "NumpadPgUp", "numpaddel": "NumpadDel", "ctrlbreak": "CtrlBreak",
              "escape": "Escape", "esc": "Escape", "backspace": "Backspace", "bs": "Backspace",
              "del": "Delete", "ins": "Insert"}


def _canon_mouse(low):
    return {"lbutton": "LButton", "rbutton": "RButton", "mbutton": "MButton", "xbutton1": "XButton1",
            "xbutton2": "XButton2", "wheelup": "WheelUp", "wheeldown": "WheelDown",
            "wheelleft": "WheelLeft", "wheelright": "WheelRight"}[low]


def from_vk(vk: int) -> Key | None:
    if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
        return lookup(chr(vk).lower())
    for low, (code, bvk) in NEUTRAL.items():
        if bvk == vk:
            return lookup(low)
    for c, v in _CHAR_VK.items():
        if v == vk:
            return lookup(c)
    for low, (code, btn, mvk) in MOUSE.items():
        if mvk == vk:
            return lookup(low)
    for low, (btn, wvk) in WHEEL.items():
        if wvk == vk:
            return lookup(low)
    name = BY_VK.get(vk)
    if name:
        return lookup(name)
    return None


def from_sc(sc: int) -> Key | None:
    for name, code, vk, s in _TABLE:
        if s == sc:
            return lookup(name)
    if sc < 0x80 and sc in _US_BY_CODE:
        return lookup(_US_BY_CODE[sc])
    return None


def from_code(code: int) -> Key | None:
    """Key for an evdev code (used when reporting physical events)."""
    if code in BY_CODE:
        return lookup(BY_CODE[code])
    for low, (c, btn, vk) in MOUSE.items():
        if c == code:
            return lookup(low)
    from . import layout
    ch = layout.code_to_char(code, False)
    if ch:
        return lookup(ch)
    if code in _US_BY_CODE:
        return lookup(_US_BY_CODE[code])
    return None


def key_name(k: Key) -> str:
    """GetKeyName: canonical display name."""
    if k.kind != "key":
        return k.name
    if k.char:
        return k.char
    return k.name
