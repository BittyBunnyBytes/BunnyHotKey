"""A_Clipboard via the X11 CLIPBOARD selection (own owner process) or wl-copy/wl-paste on Wayland."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

from .. import objects as O

_owner_proc = None
_last_set = None
_change_funcs = []


def _wayland():
    return bool(os.environ.get("WAYLAND_DISPLAY")) and shutil.which("wl-paste") is not None


def get_text() -> str:
    if _wayland():
        try:
            return subprocess.run(["wl-paste", "-n"], capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            return ""
    for tool in (["xclip", "-o", "-selection", "clipboard"], ["xsel", "-ob"]):
        if shutil.which(tool[0]):
            try:
                return subprocess.run(tool, capture_output=True, text=True, timeout=2).stdout
            except (OSError, subprocess.SubprocessError):
                return ""
    from .. import xclip
    try:
        return xclip.read_clipboard()
    except OSError:
        return _last_set or ""


def set_text(s: str):
    global _owner_proc, _last_set
    _last_set = s
    if _wayland() and shutil.which("wl-copy"):
        subprocess.run(["wl-copy"], input=s.encode(), timeout=2)
        _notify()
        return
    if _owner_proc is not None and _owner_proc.poll() is None:
        _owner_proc.kill()
    # a helper process owns the selection so the text survives after the script exits (like xclip)
    # -I keeps the script's folder and PYTHONPATH off sys.path, so BHK's own folder is added explicitly
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    boot = ("import sys, runpy; sys.path.insert(0, sys.argv.pop(1)); "
            "runpy.run_module('bunnyhotkey.xclip', run_name='__main__', alter_sys=True)")
    _owner_proc = subprocess.Popen([sys.executable, "-I", "-c", boot, root, "--own"],
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   cwd=root, start_new_session=True)   # never hold the script's output pipe open
    _owner_proc.stdin.write(s.encode("utf-8"))
    _owner_proc.stdin.close()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            if get_text() == s:
                break
        except Exception:
            break
        time.sleep(0.01)
    _notify()


def _notify():
    rt = O.RT
    for fn in list(_change_funcs):
        rt.post(lambda fn=fn: rt.call(fn, [1]))


def on_change(fn, add):
    if fn in _change_funcs:
        _change_funcs.remove(fn)
    if add > 0:
        _change_funcs.append(fn)
    elif add < 0:
        _change_funcs.insert(0, fn)


def clip_wait(timeout, any_type):
    rt = O.RT
    end = None if timeout is None else time.monotonic() + timeout
    while True:
        if get_text():
            return 1
        if end is not None and time.monotonic() >= end:
            return 0
        rt.sleep(50)
