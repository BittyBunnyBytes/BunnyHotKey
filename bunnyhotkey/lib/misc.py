"""Remaining built-ins from AutoHotkey's function table (lib/functions.h, g_act)."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import urllib.request

from .. import objects as O
from ..objects import AhkArray, throw
from ..values import UNSET
from . import export
from .files import host_path


def S(v):
    return O.RT.to_str(v)


@export()
def SetWorkingDir(dir_):
    try:
        os.chdir(host_path(S(dir_)))
    except OSError:
        throw("OSError", "The system cannot find the path specified.", S(dir_))
    return ""


@export()
def Download(url, filename):
    try:
        urllib.request.urlretrieve(S(url), host_path(S(filename)))
    except (OSError, ValueError) as e:
        throw("OSError", str(e), S(url))
    return ""


@export()
def FileInstall(source, dest, overwrite=0):
    src = host_path(S(source))
    if not os.path.isabs(src):
        src = os.path.join(os.path.dirname(O.RT.script_path), S(source))
    dst = host_path(S(dest))
    if os.path.exists(dst) and not (O.RT.to_int(overwrite) if overwrite != "" else 0):
        throw("OSError", "The file exists.", S(dest))
    shutil.copy2(src, dst)
    return ""


@export()
def DriveGetSpaceFree(path):
    from .files import DriveGetFreeSpace
    return DriveGetFreeSpace(path)


@export()
def DriveGetStatusCD(drive=""):
    return "not ready"


for _name in ("DriveLock", "DriveUnlock", "DriveRetract"):
    export(_name)(lambda drive="": "")


@export()
def DriveSetLabel(drive, label=""):
    return ""


@export()
def Edit():
    subprocess.Popen(["xdg-open", O.RT.script_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return ""


@export()
def EditPaste(text, control, t=UNSET, txt=UNSET, xt=UNSET, xx=UNSET):
    from .window import ControlEditPaste
    return ControlEditPaste(text, control, t, txt, xt, xx)


@export()
def RunAs(user="", password="", domain=""):
    O.RT.run_as = (S(user), S(domain))
    return ""


@export()
def SysGetIPAddresses():
    addrs = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in addrs and not ip.startswith("127."):
                addrs.append(ip)
    except OSError:
        pass
    if not addrs:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            addrs.append(s.getsockname()[0])
            s.close()
        except OSError:
            pass
    return AhkArray(None, addrs)


@export()
def ObjFromPtrAddRef(ptr):
    throw("Error", "Object pointers are not supported by Bunny Hot Key.", "ObjFromPtrAddRef")


for _name in ("ComObjConnect", "ComObjFlags", "ComObjFromPtr", "ComObjQuery", "ComObjType", "ComObjValue"):
    export(_name)((lambda n: lambda *a: throw("Error", "COM is Windows-only and not available in Bunny Hot Key.", n))(_name))
