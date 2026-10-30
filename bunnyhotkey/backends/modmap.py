"""Taking modifier keys out of X's modifier map while a bare-modifier hotkey (LWin::, RCtrl::) suppresses them.

On Windows, AutoHotkey's hook swallows the key, so the system never considers the modifier held: LWin::Return makes
Win+E type a plain "e".  On X11 the server tracks modifier state itself, so a grab alone would still deliver E with
Mod4 set.  Removing the keycode from the modifier map while the hotkey is active gives the Windows behaviour.  The
change is session-wide, so it is undone when the hotkey goes away or the script exits, and a watchdog process
restores it if the script dies without cleaning up.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time

from .. import xlib


class XModifierKeymap(ctypes.Structure):
    _fields_ = [("max_keypermod", ctypes.c_int), ("modifiermap", ctypes.POINTER(ctypes.c_ubyte))]


def _setup(x):
    x.XGetModifierMapping.restype = ctypes.POINTER(XModifierKeymap)
    x.XGetModifierMapping.argtypes = [ctypes.c_void_p]
    x.XSetModifierMapping.restype = ctypes.c_int
    x.XSetModifierMapping.argtypes = [ctypes.c_void_p, ctypes.POINTER(XModifierKeymap)]
    x.XNewModifiermap.restype = ctypes.POINTER(XModifierKeymap)
    x.XNewModifiermap.argtypes = [ctypes.c_int]
    x.XFreeModifiermap.argtypes = [ctypes.POINTER(XModifierKeymap)]


def get_map(d):
    """[8 lists of keycodes] for Shift, Lock, Control, Mod1..Mod5."""
    _setup(d.x)
    p = d.x.XGetModifierMapping(d.dpy)
    m = p.contents
    n = m.max_keypermod
    out = [[m.modifiermap[i * n + j] for j in range(n) if m.modifiermap[i * n + j]] for i in range(8)]
    d.x.XFreeModifiermap(p)
    return out


def set_map(d, mods, tries=40):
    _setup(d.x)
    n = max(1, max(len(k) for k in mods))
    p = d.x.XNewModifiermap(n)
    m = p.contents
    for i in range(8):
        for j in range(n):
            m.modifiermap[i * n + j] = mods[i][j] if j < len(mods[i]) else 0
    try:
        for _ in range(tries):
            r = d.x.XSetModifierMapping(d.dpy, p)
            if r == 0:          # MappingSuccess
                d.x.XFlush(d.dpy)
                return True
            time.sleep(0.05)    # MappingBusy: a key being changed is held down
        return False
    finally:
        d.x.XFreeModifiermap(p)


class ModifierBlock:
    """Keycodes currently taken out of the modifier map by this process."""

    def __init__(self):
        self.removed: dict[int, list[int]] = {}     # modifier index -> keycodes
        self.watchdog = None

    def apply(self, d, keycodes: set[int]):
        """Make exactly `keycodes` (plus nothing else) removed from the modifier map."""
        want = set(keycodes)
        have = {kc for kcs in self.removed.values() for kc in kcs}
        if want == have:
            return
        mods = get_map(d)
        for i, kcs in self.removed.items():          # restore the ones no longer wanted
            for kc in kcs:
                if kc not in want and kc not in mods[i]:
                    mods[i].append(kc)
        removed: dict[int, list[int]] = {}
        for i in range(8):
            keep = []
            for kc in mods[i]:
                if kc in want:
                    removed.setdefault(i, []).append(kc)
                else:
                    keep.append(kc)
            mods[i] = keep
        for i, kcs in self.removed.items():          # still-wanted ones that were already out of the map
            for kc in kcs:
                if kc in want and kc not in removed.get(i, []):
                    removed.setdefault(i, []).append(kc)
        if set_map(d, mods):
            self.removed = removed
            self._watch()

    def restore(self, d):
        if not self.removed:
            self._unwatch()
            return
        restore_into(d, self.removed)
        self.removed = {}
        self._unwatch()

    def _watch(self):
        """A process that restores the map if this one dies without calling restore()."""
        self._unwatch()
        if not self.removed:
            return
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        # the restore code is imported before waiting, so it still works if BHK's folder is moved or deleted
        # (bhk update / uninstall) while the script runs
        code = ("import sys, json; sys.path.insert(0, sys.argv[1])\n"
                "from bunnyhotkey.backends.modmap import restore_standalone\n"
                "line = sys.stdin.readline()\n"
                "if line.strip() != 'done':\n"
                "    restore_standalone(json.loads(sys.argv[2]))\n")
        try:
            self.watchdog = subprocess.Popen([sys.executable, "-I", "-c", code, root, json.dumps(self.removed)],
                                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            self.watchdog = None

    def _unwatch(self):
        w, self.watchdog = self.watchdog, None
        if w is not None:
            try:
                w.stdin.write(b"done\n")
                w.stdin.close()
            except OSError:
                pass


def restore_into(d, removed):
    mods = get_map(d)
    changed = False
    for i, kcs in removed.items():
        for kc in kcs:
            if kc not in mods[int(i)]:
                mods[int(i)].append(kc)
                changed = True
    if changed:
        set_map(d, mods, tries=200)


def restore_standalone(removed):
    d = xlib.Display()
    restore_into(d, removed)
