"""Input backends.

  x11   Hotkeys are passive grabs of exactly the keys a script defines; output via XTest.
  null  No input (headless / CI); Send is recorded but not delivered.

Wayland: a backend built on the xdg-desktop-portal GlobalShortcuts and
RemoteDesktop portals (user-approved by the compositor) is planned.  Until
then, scripts on Wayland run with the null backend, or X11 apps under XWayland.
"""
from __future__ import annotations

import os


def detect(rt) -> str:
    want = (rt.options.get("backend") or os.environ.get("BHK_BACKEND") or "auto").lower()
    if want != "auto":
        return want
    if os.environ.get("DISPLAY"):
        return "x11"
    return "null"


def get_backend(rt):
    if rt.backend is not None:
        return rt.backend
    kind = detect(rt)
    if kind == "x11":
        from .x11 import X11Backend
        b = X11Backend(rt)
    else:
        from .null import NullBackend
        b = NullBackend(rt)
    rt.backend = b
    b.start()
    return b
