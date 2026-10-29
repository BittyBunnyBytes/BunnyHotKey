"""Run/RunWait/Process*/Env*/Shutdown (lib/process.cpp, script2.cpp ActionExec).

Windows programs are translated to Linux equivalents where one exists (notepad,
explorer, cmd, calc, URLs, documents via xdg-open); .exe files run through Wine
when it is installed.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import time

from .. import objects as O
from ..objects import throw
from ..values import UNSET
from . import export, setref
from .files import host_path


def S(v):
    return O.RT.to_str(v)


_TRANSLATE = {
    "notepad": ["gnome-text-editor", "kate", "gedit", "mousepad", "xed", "pluma", "kwrite", "featherpad", "xdg-open"],
    "notepad.exe": None,
    "explorer": ["xdg-open"],
    "explorer.exe": None,
    "calc": ["gnome-calculator", "kcalc", "galculator", "qalculate-gtk", "xcalc"],
    "calc.exe": None,
    "cmd": ["x-terminal-emulator", "konsole", "gnome-terminal", "xfce4-terminal", "alacritty", "kitty", "xterm"],
    "cmd.exe": None,
    "mspaint": ["kolourpaint", "pinta", "gimp"],
    "taskmgr": ["gnome-system-monitor", "plasma-systemmonitor", "ksysguard", "htop"],
    "control": ["systemsettings", "gnome-control-center", "xfce4-settings-manager"],
    "wordpad": ["libreoffice", "abiword"],
    "powershell": ["pwsh"],
}
for _k in list(_TRANSLATE):
    if _TRANSLATE[_k] is None:
        _TRANSLATE[_k] = _TRANSLATE[_k[:-4]]


def _first_available(cands):
    for c in cands:
        if shutil.which(c):
            return c
    return None


def translate_command(target: str) -> list[str]:
    """Turn an AHK Run target into an argv list for Linux."""
    t = target.strip()
    if re.match(r"^[a-z][a-z0-9+.-]*://", t, re.I) or t.lower().startswith("mailto:") or t.lower().startswith("www."):
        if t.lower().startswith("www."):
            t = "https://" + t
        return ["xdg-open", t]
    # split program and args (quoted program first)
    if t.startswith('"'):
        end = t.find('"', 1)
        prog, rest = t[1:end], t[end + 1:].strip()
    else:
        m = re.match(r"(\S+)\s*(.*)$", t, re.S)
        prog, rest = (m.group(1), m.group(2)) if m else (t, "")
        # a path with spaces, unquoted: take the longest existing prefix
        if " " in t and not os.path.exists(host_path(prog)):
            parts = t.split(" ")
            for i in range(len(parts), 0, -1):
                cand = " ".join(parts[:i])
                if os.path.exists(host_path(cand)):
                    prog, rest = cand, " ".join(parts[i:])
                    break
    low = os.path.basename(prog.replace("\\", "/")).lower()
    try:
        args = shlex.split(rest, posix=True) if rest else []
    except ValueError:
        args = rest.split()
    if low in _TRANSLATE:
        exe = _first_available(_TRANSLATE[low])
        if exe is None:
            throw("OSError", "The system cannot find the file specified.", target)
        if low.startswith("cmd") and args and args[0].lower() in ("/c", "/k"):
            return ["sh", "-c", " ".join(args[1:])]
        return [exe] + [host_path(a) if ("\\" in a or a[1:3] == ":\\") else a for a in args]
    hp = host_path(prog)
    if os.path.isdir(hp):
        return ["xdg-open", hp]
    if os.path.isfile(hp):
        if hp.lower().endswith((".exe", ".bat", ".cmd", ".msi", ".com")):
            if shutil.which("wine"):
                return ["wine", hp] + args
            throw("OSError", "Windows programs need Wine (sudo pacman -S wine).", target)
        if hp.lower().endswith(".ahk"):
            import sys
            return [sys.executable, "-m", "bunnyhotkey", hp] + args
        if os.access(hp, os.X_OK):
            return [hp] + args
        return ["xdg-open", hp]
    found = shutil.which(prog) or shutil.which(low[:-4] if low.endswith(".exe") else low)
    if found:
        return [found] + args
    throw("OSError", "The system cannot find the file specified.", target)


def _verb(target):
    m = re.match(r"^\*(\w+)\s+(.*)$", target)
    if m:
        return m.group(1).lower(), m.group(2)
    return None, target


def _spawn(target, workdir, options):
    verb, target = _verb(S(target))
    argv = translate_command(target)
    if verb in ("runas",):
        argv = ["pkexec"] + argv
    elif verb in ("edit",):
        argv = ["xdg-open"] + argv[-1:]
    cwd = host_path(S(workdir)) if S(workdir) else None
    opts = S(options).lower()
    stdout = subprocess.DEVNULL if "hide" in opts else None
    try:
        return subprocess.Popen(argv, cwd=cwd, stdout=stdout, stdin=subprocess.DEVNULL if "hide" in opts else None,
                                start_new_session=True)
    except OSError as e:
        err = O.new_error("OSError", e.strerror or str(e), S(target))
        from ..errors import AhkThrow
        raise AhkThrow(err)


@export(byref=(3,))
def Run(target, workdir="", options="", outpid=UNSET):
    p = _spawn(target, workdir, options)
    setref(outpid, p.pid)
    _CHILDREN[p.pid] = p
    return ""


_CHILDREN: dict[int, subprocess.Popen] = {}


@export(byref=(3,))
def RunWait(target, workdir="", options="", outpid=UNSET):
    p = _spawn(target, workdir, options)
    setref(outpid, p.pid)
    rt = O.RT
    while p.poll() is None:
        rt.sleep(20)
    return p.returncode


def _pid_of(name_or_pid):
    s = S(name_or_pid) if name_or_pid not in (UNSET, "") else ""
    if s == "":
        return 0
    if s.isdigit():
        pid = int(s)
        return pid if os.path.exists(f"/proc/{pid}") else 0
    low = s.lower()
    low_noext = low[:-4] if low.endswith(".exe") else low
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/comm") as fh:
                comm = fh.read().strip().lower()
            if comm == low or comm == low_noext:
                return int(d)
            exe = os.path.basename(os.readlink(f"/proc/{d}/exe")).lower()
            if exe == low or exe == low_noext:
                return int(d)
        except OSError:
            continue
    return 0


@export()
def ProcessExist(name=""):
    if name in (UNSET, ""):
        return os.getpid()
    return _pid_of(name)


@export()
def ProcessClose(name):
    pid = _pid_of(name)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return 0
    return pid


@export()
def ProcessWait(name, timeout=UNSET):
    rt = O.RT
    end = None if timeout is UNSET else time.monotonic() + float(rt.to_num(timeout))
    while True:
        pid = _pid_of(name)
        if pid:
            return pid
        if end is not None and time.monotonic() >= end:
            return 0
        rt.sleep(100)


@export()
def ProcessWaitClose(name, timeout=UNSET):
    rt = O.RT
    end = None if timeout is UNSET else time.monotonic() + float(rt.to_num(timeout))
    while True:
        pid = _pid_of(name)
        if not pid:
            return 0
        if end is not None and time.monotonic() >= end:
            return pid
        rt.sleep(100)


@export()
def ProcessSetPriority(level, name=""):
    pid = _pid_of(name) if name not in (UNSET, "") else os.getpid()
    lv = S(level).lower()[:1]
    nice = {"l": 19, "b": 10, "n": 0, "a": -5, "h": -10, "r": -20}.get(lv, 0)
    try:
        os.setpriority(os.PRIO_PROCESS, pid, nice)
    except OSError:
        pass
    return pid


@export()
def ProcessGetName(name=""):
    pid = _pid_of(name) if name not in (UNSET, "") else os.getpid()
    try:
        with open(f"/proc/{pid}/comm") as fh:
            return fh.read().strip()
    except OSError:
        throw("TargetError", "Target process not found.", S(name))


@export()
def ProcessGetPath(name=""):
    pid = _pid_of(name) if name not in (UNSET, "") else os.getpid()
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except OSError:
        throw("TargetError", "Target process not found.", S(name))


@export()
def ProcessGetParent(name=""):
    pid = _pid_of(name) if name not in (UNSET, "") else os.getpid()
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return int(fh.read().rsplit(")", 1)[1].split()[1])
    except OSError:
        return 0


@export()
def EnvGet(name):
    return os.environ.get(S(name), "")


@export()
def EnvSet(name, value=UNSET):
    if value is UNSET:
        os.environ.pop(S(name), None)
    else:
        os.environ[S(name)] = S(value)
    return ""


@export()
def Shutdown(code):
    c = O.RT.to_int(code)
    if c & 4:
        pass
    if c == 0:
        subprocess.Popen(["loginctl", "terminate-user", os.environ.get("USER", "")])
    elif c & 8 or c & 1:
        subprocess.Popen(["systemctl", "poweroff"])
    elif c & 2:
        subprocess.Popen(["systemctl", "reboot"])
    return ""


@export()
def ComObject(*a):
    throw("Error", "COM objects are Windows-only and not available in Bunny Hot Key.", "ComObject")


@export()
def ComObjActive(*a):
    throw("Error", "COM objects are Windows-only and not available in Bunny Hot Key.", "ComObjActive")


@export()
def ComObjGet(*a):
    throw("Error", "COM objects are Windows-only and not available in Bunny Hot Key.", "ComObjGet")


@export()
def ComCall(*a):
    throw("Error", "COM is Windows-only and not available in Bunny Hot Key.", "ComCall")


def ver_compare(a: str, b: str) -> int:
    def parts(v):
        main, _, pre = v.partition("-")
        main = main.split("+")[0]
        nums = []
        for p in main.split("."):
            try:
                nums.append(int(p))
            except ValueError:
                nums.append(0)
        return nums, pre
    (na, pa), (nb, pb) = parts(a.lstrip("v")), parts(b.lstrip("v"))
    for i in range(max(len(na), len(nb))):
        x = na[i] if i < len(na) else 0
        y = nb[i] if i < len(nb) else 0
        if x != y:
            return 1 if x > y else -1
    if pa and not pb:
        return -1
    if pb and not pa:
        return 1
    return (pa > pb) - (pa < pb)
