"""Active keyboard layout via libxkbcommon (the Linux counterpart of VkKeyScan/ToUnicode).

Builds char <-> (evdev code, shift) maps from the user's XKB layout so that Send,
hotstrings and single-character key names follow the real layout on X11 and Wayland.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import subprocess

_char_map: dict[str, tuple[int, bool]] | None = None
_code_map: dict[tuple[int, bool], str] = {}


class _RuleNames(ctypes.Structure):
    _fields_ = [("rules", ctypes.c_char_p), ("model", ctypes.c_char_p), ("layout", ctypes.c_char_p),
                ("variant", ctypes.c_char_p), ("options", ctypes.c_char_p)]


def _rmlvo() -> dict[str, str]:
    vals = {k: os.environ.get(f"XKB_DEFAULT_{k.upper()}", "") for k in ("rules", "model", "layout", "variant", "options")}
    if not vals["layout"] and os.environ.get("DISPLAY"):
        try:
            out = subprocess.run(["setxkbmap", "-query"], capture_output=True, text=True, timeout=3).stdout
            for line in out.splitlines():
                k, _, v = line.partition(":")
                k = k.strip()
                if k in vals and not vals[k]:
                    vals[k] = v.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return vals


def _build():
    global _char_map
    _char_map = {}
    lib_name = ctypes.util.find_library("xkbcommon")
    if not lib_name:
        return
    try:
        xkb = ctypes.CDLL(lib_name)
    except OSError:
        return
    xkb.xkb_context_new.restype = ctypes.c_void_p
    xkb.xkb_keymap_new_from_names.restype = ctypes.c_void_p
    xkb.xkb_keymap_new_from_names.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RuleNames), ctypes.c_int]
    xkb.xkb_keymap_key_get_syms_by_level.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                                     ctypes.c_uint32, ctypes.POINTER(ctypes.POINTER(ctypes.c_uint32))]
    xkb.xkb_keysym_to_utf32.restype = ctypes.c_uint32
    xkb.xkb_keysym_to_utf32.argtypes = [ctypes.c_uint32]
    ctx = xkb.xkb_context_new(0)
    if not ctx:
        return
    v = _rmlvo()
    names = _RuleNames(*(v[k].encode() or None for k in ("rules", "model", "layout", "variant", "options")))
    # only the first layout group matters for typing
    if names.layout and b"," in names.layout:
        names.layout = names.layout.split(b",")[0]
        if names.variant:
            names.variant = names.variant.split(b",")[0]
    keymap = xkb.xkb_keymap_new_from_names(ctypes.c_void_p(ctx), ctypes.byref(names), 0)
    if not keymap:
        return
    syms = ctypes.POINTER(ctypes.c_uint32)()
    for evcode in range(1, 248):
        for level in (0, 1):
            n = xkb.xkb_keymap_key_get_syms_by_level(ctypes.c_void_p(keymap), evcode + 8, 0, level, ctypes.byref(syms))
            if n < 1:
                continue
            cp = xkb.xkb_keysym_to_utf32(syms[0])
            if cp < 0x20 or cp == 0x7F:
                continue
            ch = chr(cp)
            # keypad keys also produce digits; prefer the main row
            if 71 <= evcode <= 83 or evcode in (55, 74, 78, 96, 98):
                continue
            _char_map.setdefault(ch, (evcode, bool(level)))
            _code_map.setdefault((evcode, bool(level)), ch)


def char_to_key(ch: str):
    if _char_map is None:
        _build()
    return _char_map.get(ch)


def code_to_char(code: int, shift: bool) -> str:
    if _char_map is None:
        _build()
    return _code_map.get((code, shift), "")
