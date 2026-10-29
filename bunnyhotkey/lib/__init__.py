"""Built-in function library.  Each module exposes functions decorated with @export."""
from __future__ import annotations

EXPORTS: list[tuple[str, object, tuple]] = []


def export(name=None, byref=()):
    def deco(fn):
        EXPORTS.append((name or fn.__name__, fn, byref))
        return fn
    return deco


def setref(ref, value):
    """Store into an output-variable parameter (&OutputVar) if one was passed."""
    from ..objects import VarRef
    if type(ref) is VarRef:
        ref.cell.value = value
    return value


def register_all(rt):
    from ..classes import bif
    from . import (buffer, clipboard, core, datetime_, dllcall, files, flow, gui, input_, loops, math_, misc, process,
                   regex, registry, sound, strings, vars_, window)
    for name, fn, byref in EXPORTS:
        rt.builtins[name.lower()] = bif(name, fn, byref)
    vars_.register_vars(rt)
