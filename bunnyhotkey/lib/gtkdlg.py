"""MsgBox and InputBox windows using GTK3 (PyGObject), run in a helper process.

The helper keeps GTK out of the script process: BHK starts it, sends a JSON
request on stdin and reads the answer from stdout, while the script thread keeps
running other pseudo-threads.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gtkdlg_helper.py")


def available() -> bool:
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return False
    r = subprocess.run([sys.executable, "-c", "import gi; gi.require_version('Gtk','3.0')"], capture_output=True)
    return r.returncode == 0 and os.path.exists(HELPER)


def ask(request: dict):
    from .. import objects as O
    rt = O.RT
    p = subprocess.Popen([sys.executable, "-I", HELPER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True)
    p.stdin.write(json.dumps(request))
    p.stdin.close()
    while p.poll() is None:
        rt.sleep(30)
    try:
        return json.loads(p.stdout.read() or "{}")
    except ValueError:
        return {}
