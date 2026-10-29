"""Emulated registry (RegRead/RegWrite/RegDelete/Loop Reg) stored in the BHK prefix, like Wine's .reg files."""
from __future__ import annotations

import json
import os
import threading
import time

from .. import objects as O
from ..objects import throw
from ..values import UNSET
from . import export

ROOTS = {"HKEY_LOCAL_MACHINE": "HKLM", "HKLM": "HKLM", "HKEY_CURRENT_USER": "HKCU", "HKCU": "HKCU",
         "HKEY_CLASSES_ROOT": "HKCR", "HKCR": "HKCR", "HKEY_USERS": "HKU", "HKU": "HKU",
         "HKEY_CURRENT_CONFIG": "HKCC", "HKCC": "HKCC"}
_lock = threading.Lock()
_data = None


def _path():
    from ..prefix import prefix_root
    return os.path.join(prefix_root(), "registry.json")


def _load():
    global _data
    if _data is None:
        try:
            with open(_path()) as fh:
                _data = json.load(fh)
        except (OSError, ValueError):
            _data = {}
    return _data


def _save():
    tmp = _path() + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(_data, fh, indent=1, sort_keys=True)
    os.replace(tmp, _path())


def _split(key: str):
    k = key.replace("/", "\\").strip("\\")
    root, _, rest = k.partition("\\")
    r = ROOTS.get(root.upper())
    if r is None:
        throw("OSError", "The system cannot find the file specified.", key)
    if r == "HKCR":
        r, rest = "HKLM", "Software\\Classes" + ("\\" + rest if rest else "")
    return r, rest


def _node(key, create=False):
    d = _load()
    root, rest = _split(key)
    node = d.setdefault(root, {"keys": {}, "values": {}}) if create else d.get(root)
    if node is None:
        return None
    for part in [p for p in rest.split("\\") if p]:
        keys = node.setdefault("keys", {})
        match = next((k for k in keys if k.lower() == part.lower()), None)
        if match is None:
            if not create:
                return None
            keys[part] = {"keys": {}, "values": {}, "time": time.strftime("%Y%m%d%H%M%S")}
            match = part
        node = keys[match]
    return node


def seed_defaults():
    """Values real AHK installs/scripts commonly read."""
    with _lock:
        n = _node("HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced", True)
        n["values"].setdefault("Hidden", ["REG_DWORD", 2])
        n = _node("HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", True)
        n["values"].setdefault("ProductName", ["REG_SZ", "Windows 10 Pro (Bunny Hot Key)"])
        n["values"].setdefault("CurrentBuild", ["REG_SZ", "19045"])
        _save()


@export()
def RegRead(key=UNSET, value="", default=UNSET):
    r = O.RT
    k = r.to_str(key) if key is not UNSET else (r.thread.loop.reg or {}).get("Key", "")
    with _lock:
        node = _node(k)
        vals = (node or {}).get("values", {})
        name = r.to_str(value)
        hit = next((v for kk, v in vals.items() if kk.lower() == name.lower()), None)
    if hit is None:
        if default is not UNSET:
            return default
        throw("OSError", "The system cannot find the file specified.", k + ("\\" + name if name else ""))
    return hit[1]


@export()
def RegWrite(value, type_=UNSET, key=UNSET, name=""):
    r = O.RT
    t = r.to_str(type_) if type_ is not UNSET else "REG_SZ"
    k = r.to_str(key) if key is not UNSET else (r.thread.loop.reg or {}).get("Key", "")
    v = value if t.upper() not in ("REG_DWORD", "REG_QWORD") else r.to_int(value)
    with _lock:
        node = _node(k, True)
        vals = node.setdefault("values", {})
        nm = r.to_str(name)
        for kk in list(vals):
            if kk.lower() == nm.lower():
                del vals[kk]
        vals[nm] = [t.upper(), v]
        node["time"] = time.strftime("%Y%m%d%H%M%S")
        _save()
    return ""


@export()
def RegDelete(key=UNSET, name=UNSET):
    r = O.RT
    k = r.to_str(key) if key is not UNSET else (r.thread.loop.reg or {}).get("Key", "")
    with _lock:
        node = _node(k)
        if node is None:
            throw("OSError", "The system cannot find the file specified.", k)
        nm = r.to_str(name) if name is not UNSET else ""
        vals = node.get("values", {})
        found = [kk for kk in vals if kk.lower() == nm.lower()]
        if not found:
            throw("OSError", "The system cannot find the file specified.", nm)
        for kk in found:
            del vals[kk]
        _save()
    return ""


@export()
def RegDeleteKey(key=UNSET):
    r = O.RT
    k = r.to_str(key) if key is not UNSET else ""
    root, rest = _split(k)
    parent_path, _, leaf = rest.rpartition("\\")
    with _lock:
        parent = _node(root + ("\\" + parent_path if parent_path else ""))
        if parent is None:
            throw("OSError", "The system cannot find the file specified.", k)
        keys = parent.get("keys", {})
        for kk in list(keys):
            if kk.lower() == leaf.lower():
                del keys[kk]
                _save()
                return ""
    throw("OSError", "The system cannot find the file specified.", k)


@export()
def RegCreateKey(key=UNSET):
    with _lock:
        _node(O.RT.to_str(key), True)
        _save()
    return ""


def loop_items(key, mode):
    with _lock:
        node = _node(key)
    if node is None:
        return
    root, rest = _split(key)
    full = key.rstrip("\\")
    if "K" in mode:
        for name, sub in sorted(node.get("keys", {}).items(), key=lambda x: x[0].lower(), reverse=True):
            yield {"Name": name, "Type": "KEY", "Key": full, "TimeModified": sub.get("time", "")}
            if "R" in mode:
                yield from loop_items(full + "\\" + name, mode)
    if "V" in mode or "K" not in mode:
        for name, (t, v) in sorted(node.get("values", {}).items(), key=lambda x: x[0].lower(), reverse=True):
            yield {"Name": name, "Type": t, "Key": full, "TimeModified": node.get("time", "")}
    if "R" in mode and "K" not in mode:
        for name in node.get("keys", {}):
            yield from loop_items(full + "\\" + name, mode)
