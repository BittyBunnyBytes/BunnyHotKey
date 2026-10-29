"""The running object table: RegisterActiveObject / GetActiveObject / ComObjActive across Bunny Hot Key processes.

On Windows a script publishes an object with DllCall("oleaut32\\RegisterActiveObject", "Ptr", ObjPtr(obj), ...)
(Lexikos's ObjRegisterActive) and another script gets it with ComObjActive(CLSID), then calls its members across
the process boundary.  Here the table is a directory of entries ($XDG_RUNTIME_DIR/bunnyhotkey/rot/<CLSID>) naming
the owning process and object, and member calls travel over the owning script's IPC socket (ipc.py).  Objects
passed either way are exported by reference, so callbacks into the caller work too.
"""
from __future__ import annotations

import atexit
import itertools
import json
import os
import select
import socket
import threading

from .. import objects as O
from ..objects import AhkObject, throw
from .com import ComDispatch, Impl, com_error

_lock = threading.RLock()
_exports: dict[int, object] = {}            # id -> object exported to other processes
_export_ids: dict[int, int] = {}            # id(object) -> export id
_ids = itertools.count(1)
_cookies: dict[int, str] = {}               # RegisterActiveObject cookie -> table key
_cookie_ids = itertools.count(1)
_local: dict[str, object] = {}              # key -> object, for this process's registrations

PROGID_CLSID = {"scripting.dictionary": "{EE09B103-97E0-11CF-978F-00A02463E06F}",
                "wscript.shell": "{72C24DD5-D70A-438B-8A42-98424B88AFB8}",
                "scripting.filesystemobject": "{0D43FE01-F093-11CF-8940-00A0C9054228}",
                "shell.application": "{13709620-C279-11CE-A49E-444553540000}",
                "winhttp.winhttprequest.5.1": "{2087C2F4-2CEF-4953-A8AB-66779B670495}",
                "sapi.spvoice": "{96749377-3391-11D2-9EE3-00C04F797396}",
                "adodb.stream": "{00000566-0000-0010-8000-00AA006D2EA4}"}


def table_dir():
    from .ipc import sock_dir
    d = os.path.join(sock_dir(), "rot")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def key_of(name) -> str:
    """CLSIDFromString rules: a {GUID} as is, a ProgID through the class table (else by name)."""
    s = str(name).strip()
    if s.startswith("{"):
        from .comnative import guid_bytes, guid_str
        try:
            return guid_str(guid_bytes(s))
        except ValueError:
            pass
    return PROGID_CLSID.get(s.lower(), s.upper())


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


# ---------------------------------------------------------------- registering
def register(obj, name) -> int:
    """RegisterActiveObject: publish obj under a CLSID; returns the cookie for RevokeActiveObject."""
    key = key_of(name)
    eid = export(obj)
    path = os.path.join(table_dir(), _fname(key))
    with open(path + ".tmp", "w") as f:
        json.dump({"pid": os.getpid(), "id": eid, "key": key}, f)
    os.replace(path + ".tmp", path)
    from . import ipc
    ipc.start_server()
    with _lock:
        _local[key] = obj
        cookie = next(_cookie_ids)
        _cookies[cookie] = key
    return cookie


def revoke(cookie) -> bool:
    with _lock:
        key = _cookies.pop(cookie, None)
        if key is None:
            return False
        _local.pop(key, None)
    _remove_entry(key)
    return True


def _fname(key):
    return "".join(ch if ch.isalnum() or ch in "-{}._" else "_" for ch in key)


def _remove_entry(key):
    path = os.path.join(table_dir(), _fname(key))
    try:
        with open(path) as f:
            if json.load(f).get("pid") != os.getpid():
                return
        os.unlink(path)
    except (OSError, ValueError):
        pass


@atexit.register
def _cleanup():
    for key in list(_local):
        _remove_entry(key)


def get_active(name):
    """ComObjActive / GetActiveObject: the registered object (a proxy when another process owns it)."""
    key = key_of(name)
    with _lock:
        obj = _local.get(key)
    if obj is not None:
        return obj
    path = os.path.join(table_dir(), _fname(key))
    try:
        with open(path) as f:
            ent = json.load(f)
    except (OSError, ValueError):
        ent = None
    if not ent or not _alive(int(ent["pid"])):
        if ent:
            try:
                os.unlink(path)
            except OSError:
                pass
        com_error(0x800401E3, "Operation unavailable", str(name))
    return ComDispatch(RemoteImpl(int(ent["pid"]), int(ent["id"])))


# ---------------------------------------------------------------- marshalling
def export(obj) -> int:
    with _lock:
        eid = _export_ids.get(id(obj))
        if eid is None or _exports.get(eid) is not obj:
            eid = next(_ids)
            _exports[eid] = obj
            _export_ids[id(obj)] = eid
        return eid


def marshal(v):
    if isinstance(v, ComDispatch) and isinstance(v.impl, RemoteImpl):
        return {"$ref": [v.impl.pid, v.impl.eid]}
    if isinstance(v, AhkObject):
        return {"$ref": [os.getpid(), export(v)]}
    if isinstance(v, (int, float, str)):
        return v
    return O.RT.to_str(v) if v is not None else ""


def unmarshal(v):
    if isinstance(v, dict) and "$ref" in v:
        pid, eid = v["$ref"]
        if pid == os.getpid():
            return _exports.get(eid, "")
        return ComDispatch(RemoteImpl(pid, eid))
    return v


# ---------------------------------------------------------------- calls between processes
class RemoteImpl(Impl):
    """An object living in another Bunny Hot Key process."""
    iface = "IDispatch"
    default = "\0value"

    def __init__(self, pid, eid):
        self.pid, self.eid = pid, eid

    def _req(self, op, name=None, args=(), value=None):
        return request(self.pid, {"op": op, "id": self.eid, "name": name,
                                  "args": [marshal(a) for a in args],
                                  "value": marshal(value) if value is not None else None})

    def _n(self, name):
        return None if name == self.default else name

    def get(self, name, params):
        return self._req("get", self._n(name), params)

    def set(self, name, params, value):
        self._req("set", self._n(name), params, value)
        return value

    def call(self, name, args):
        return self._req("call", self._n(name), args)

    def enum(self):
        return iter(self._req("enum") or [])


def request(pid, body, timeout=10.0):
    """Send one member call to pid and wait for the reply.  While waiting, calls coming the other way (callbacks
    into objects this process exported) still run, so the two scripts can't deadlock on each other."""
    from .ipc import sock_path
    path = sock_path(pid)
    if not os.path.exists(path):
        com_error(0x800706BA, "The RPC server is unavailable.")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(path)
        s.sendall((json.dumps({"com": body}) + "\n").encode())
        buf = b""
        r = O.RT
        waited = 0.0
        while b"\n" not in buf:
            ready, _, _ = select.select([s], [], [], 0.02)
            if ready:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
            else:
                waited += 0.02
                if r.sync_calls and threading.current_thread() is getattr(r, "main_thread", None):
                    r._run_sync_calls()
                if waited > timeout:
                    com_error(0x800705B4, "This operation returned because the timeout period expired.")
    except OSError:
        com_error(0x800706BA, "The RPC server is unavailable.")
    finally:
        s.close()
    if not buf:
        com_error(0x800706BE, "The remote procedure call failed.")
    reply = json.loads(buf.split(b"\n", 1)[0])
    if "error" in reply:
        throw(reply.get("type", "Error"), reply["error"], body.get("name") or "")
    return unmarshal(reply.get("result", ""))


def serve(body):
    """Run in the owning script: perform a member call another process asked for."""
    from .com import wrap
    r = O.RT
    obj = _exports.get(int(body["id"]))
    if obj is None:
        return {"error": "The object invoked has disconnected from its clients.", "type": "OSError"}
    op, name = body["op"], body.get("name")
    args = [unmarshal(a) for a in body.get("args") or []]
    try:
        if op == "release":
            with _lock:
                _exports.pop(int(body["id"]), None)
            return {"result": ""}
        if op == "enum":
            from ..objects import VarRef
            from ..values import Cell
            e = r.call_method(obj, "__Enum", [1])
            out = []
            while True:
                cell = Cell("")
                if not r.to_bool(r.call(e, [VarRef(cell)])):
                    break
                out.append(marshal(cell.value))
            return {"result": out}
        if isinstance(obj, ComDispatch):
            impl = obj.impl
            if op == "get":
                res = impl.get(name or impl.default or "Item", args)
            elif op == "set":
                res = impl.set(name or impl.default or "Item", args, unmarshal(body.get("value")))
            else:
                res = impl.call(name or impl.default or "Item", args)
            res = wrap(res)
        elif op == "get":
            res = r.get_prop(obj, name, args) if name else (r.get_item(obj, args) if args else obj)
        elif op == "set":
            v = unmarshal(body.get("value"))
            if name:
                r.set_prop(obj, name, v, args)
            else:
                r.set_item(obj, v, args)
            res = v
        else:
            res = r.call_method(obj, name, args) if name else r.call(obj, args)
        return {"result": marshal(res)}
    except Exception as e:      # script errors travel back as the same error type and message
        from ..errors import AhkThrow
        if isinstance(e, AhkThrow):
            err = e.value
            if isinstance(err, AhkObject):
                try:
                    return {"error": r.to_str(r.get_prop(err, "Message")), "type": type_name(err)}
                except Exception:
                    pass
            return {"error": r.to_str(err), "type": "Error"}
        return {"error": str(e), "type": "Error"}


def type_name(err):
    try:
        return O.RT.to_str(O.RT.get_prop(err, "__Class"))
    except Exception:
        return "Error"
