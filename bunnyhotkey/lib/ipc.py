"""The script's hidden main window and window messages between Bunny Hot Key processes.

AutoHotkey gives every script a hidden main window (class "AutoHotkey", title "<script path> - AutoHotkey v2.0.31")
that other scripts find with DetectHiddenWindows + WinExist and send messages to: WM_COPYDATA for IPC, WM_COMMAND
65307 to exit a script, and so on (script.cpp, MainWindowProc).  BHK creates the same hidden X window, and carries
SendMessage/PostMessage between processes over a per-process Unix socket.  The target process is the window's
_NET_WM_PID, which BHK also sets on its Gui windows (they are drawn by the GTK helper process).
"""
from __future__ import annotations

import base64
import json
import os
import socket
import threading

from .. import objects as O
from ..objects import throw
from ..values import UNSET

WM_CLOSE, WM_COMMAND, WM_COPYDATA = 0x10, 0x111, 0x4A
# CommandIDs in script.h (ID_TRAY_*) and resource.h (ID_FILE_*, ID_VIEW_*)
ID_TRAY_OPEN, ID_TRAY_HELP, ID_TRAY_WINDOWSPY, ID_TRAY_RELOAD, ID_TRAY_EDIT, ID_TRAY_SUSPEND, ID_TRAY_PAUSE, \
    ID_TRAY_EXIT = range(65300, 65308)
ID_FILE_RELOAD, ID_FILE_EDIT, ID_FILE_WINDOWSPY, ID_FILE_PAUSE, ID_FILE_SUSPEND, ID_FILE_EXIT, ID_VIEW_LINES, \
    ID_VIEW_VARIABLES, ID_VIEW_HOTKEYS, ID_VIEW_KEYHISTORY = range(65400, 65410)

_main = {}          # display, window
_server = None


def rt():
    return O.RT


def sock_dir():
    base = os.environ.get("XDG_RUNTIME_DIR")
    d = os.path.join(base, "bunnyhotkey") if base else f"/tmp/bunnyhotkey-{os.getuid()}"
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def sock_path(pid):
    return os.path.join(sock_dir(), f"{pid}.sock")


# ---------------------------------------------------------------- hidden main window
def create_main_window():
    """Create the hidden main window (A_ScriptHwnd) and start listening for messages from other scripts."""
    from .. import xlib
    from ..runtime import VERSION
    r = rt()
    if _main or not xlib.available():
        return 0
    try:
        d = xlib.Display()          # its own connection: the window lives as long as the process
    except OSError:
        return 0
    x = d.x
    w = x.XCreateSimpleWindow(d.dpy, d.root, 0, 0, 1, 1, 0, 0, 0)
    title = f"{r.script_path} - AutoHotkey v{VERSION}"
    x.XStoreName(d.dpy, w, title.encode())
    set_utf8(d, w, "_NET_WM_NAME", title)
    cls = b"AutoHotkey\0AutoHotkey\0"
    x.XChangeProperty(d.dpy, w, d.atom("WM_CLASS"), d.atom("STRING"), 8, 0, cls, len(cls))
    set_pid(d, w)
    d.flush()
    _main.update(display=d, window=w)
    r.script_hwnd = w
    start_server()
    return w


def set_utf8(d, w, prop, text):
    raw = text.encode()
    d.x.XChangeProperty(d.dpy, w, d.atom(prop), d.atom("UTF8_STRING"), 8, 0, raw, len(raw))


def set_pid(d, w, pid=None):
    import ctypes
    buf = (ctypes.c_ulong * 1)(pid or os.getpid())
    d.x.XChangeProperty(d.dpy, w, d.atom("_NET_WM_PID"), 6, 32, 0, buf, 1)     # XA_CARDINAL


def claim_window(xid):
    """Mark one of this script's Gui windows (drawn by the helper process) as belonging to the script process,
    so WinGetPID/ahk_pid and cross-process messages see the script, as on Windows."""
    from .window import _dpy
    d = _dpy()
    if d is not None and xid:
        set_pid(d, xid)
        d.flush()


# ---------------------------------------------------------------- receiving
def start_server():
    global _server
    if _server is not None:
        return
    path = sock_path(os.getpid())
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(path)
    os.chmod(path, 0o600)
    s.listen(16)
    _server = s
    import atexit
    atexit.register(lambda: os.path.exists(path) and os.unlink(path))
    threading.Thread(target=_accept_loop, args=(s,), name="bhk-ipc", daemon=True).start()


def _accept_loop(s):
    while True:
        try:
            conn, _ = s.accept()
        except OSError:
            return
        threading.Thread(target=_serve, args=(conn,), daemon=True).start()


def _serve(conn):
    with conn:
        f = conn.makefile("rwb")
        line = f.readline()
        if not line:
            return
        req = json.loads(line)
        if "com" in req:
            _serve_com(f, req["com"])
            return
        done = threading.Event()
        box = {"result": 0}

        def run():
            try:
                box["result"] = receive(req)
            finally:
                done.set()
        rt().post(run)
        if req.get("sync"):
            done.wait(req.get("timeout", 5.0))
            res = box["result"]
            f.write((json.dumps({"result": res if isinstance(res, (int, float)) else str(res)}) + "\n").encode())
            f.flush()


def _serve_com(f, body):
    """A member call on an object this script exported (rot.py).  Runs as a synchronous call in the script thread
    (post_sync), which a script waiting on its own remote call still services, so calls may nest both ways."""
    from . import rot
    done = threading.Event()
    box = {}

    def run():
        try:
            box["reply"] = rot.serve(body)
        except BaseException as e:      # noqa: BLE001 - the reply must always be written
            box["reply"] = {"error": str(e) or type(e).__name__, "type": "Error"}
        finally:
            done.set()
    rt().post_sync(run)
    done.wait(30.0)
    reply = box.get("reply", {"error": "Timeout.", "type": "TimeoutError"})
    try:
        f.write((json.dumps(reply) + "\n").encode())
        f.flush()
    except OSError:
        pass


def receive(req):
    """Run in the script thread: deliver a message that came from another process."""
    from .buffer import BufferObj
    from .flow import message_handlers
    from .guiobj import CTRLS
    r = rt()
    msg, wp, lp, hwnd = req["msg"], req["wp"], req["lp"], req["hwnd"]
    keep = []
    if msg == WM_COPYDATA and "data" in req:
        # rebuild COPYDATASTRUCT {ULONG_PTR dwData; DWORD cbData; PVOID lpData} in this process
        data = base64.b64decode(req["data"])
        payload = BufferObj(max(len(data), 1))
        payload.data[:len(data)] = data
        cds = BufferObj(24)
        cds.data[0:8] = int(req.get("dwdata", 0)).to_bytes(8, "little", signed=False)
        cds.data[8:12] = len(data).to_bytes(4, "little")
        cds.data[16:24] = payload.addr.to_bytes(8, "little")
        keep = [payload, cds]
        lp = cds.addr
    for fn in message_handlers(msg):
        res = r.call(fn, [wp, lp, msg, hwnd])
        if res != "" and res is not None:
            del keep
            return res
    del keep
    if hwnd == r.script_hwnd or hwnd in CTRLS:
        return main_window_default(msg, wp)
    return 0


def main_window_default(msg, wp):
    """What AutoHotkey's main window does with messages no OnMessage handler took (MainWindowProc)."""
    from . import tray
    if msg == WM_CLOSE:
        tray._exit()
    if msg != WM_COMMAND:
        return 0
    cmd = wp & 0xFFFF
    from .flow import KeyHistory, ListHotkeys, ListLines, ListVars
    actions = {ID_TRAY_OPEN: tray._open_main, ID_TRAY_WINDOWSPY: tray._window_spy,
               ID_FILE_WINDOWSPY: tray._window_spy, ID_TRAY_RELOAD: tray._reload, ID_FILE_RELOAD: tray._reload,
               ID_TRAY_EDIT: lambda: tray._xdg_open(rt().script_path),
               ID_FILE_EDIT: lambda: tray._xdg_open(rt().script_path),
               ID_TRAY_HELP: lambda: tray._xdg_open(tray.HELP_URL),
               ID_TRAY_SUSPEND: tray._suspend, ID_FILE_SUSPEND: tray._suspend,
               ID_TRAY_PAUSE: tray._pause, ID_FILE_PAUSE: tray._pause,
               ID_TRAY_EXIT: tray._exit, ID_FILE_EXIT: tray._exit,
               ID_VIEW_LINES: ListLines, ID_VIEW_VARIABLES: ListVars, ID_VIEW_HOTKEYS: ListHotkeys,
               ID_VIEW_KEYHISTORY: KeyHistory}
    fn = actions.get(cmd)
    if fn is not None:
        fn()
    return 0


# ---------------------------------------------------------------- sending
def send(pid, msg, wp, lp, hwnd, sync, timeout=5.0):
    """Deliver to another BHK process.  Returns (delivered, result)."""
    path = sock_path(pid)
    if pid == os.getpid() or not os.path.exists(path):
        return False, 0
    req = {"msg": msg, "wp": wp, "lp": lp, "hwnd": hwnd, "sync": sync, "timeout": timeout}
    if msg == WM_COPYDATA and lp:
        from .buffer import resolve
        buf, i = resolve(lp)
        dwdata = int.from_bytes(bytes(buf[i:i + 8]), "little")
        cb = int.from_bytes(bytes(buf[i + 8:i + 12]), "little")
        ptr = int.from_bytes(bytes(buf[i + 16:i + 24]), "little")
        data = b""
        if cb and ptr:
            dbuf, j = resolve(ptr)
            data = bytes(dbuf[j:j + cb])
        req.update(data=base64.b64encode(data).decode(), dwdata=dwdata)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(path)
        s.sendall((json.dumps(req) + "\n").encode())
        if not sync:
            return True, 0
        line = s.makefile("rb").readline()
    except socket.timeout:
        throw("TimeoutError", "Timeout.", "SendMessage")
    except OSError:
        return False, 0
    finally:
        s.close()
    if not line:
        throw("TimeoutError", "Timeout.", "SendMessage")
    res = json.loads(line).get("result", 0)
    return True, res
