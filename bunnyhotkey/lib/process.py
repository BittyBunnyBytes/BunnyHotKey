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
from ..errors import AhkThrow
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
        if low.startswith("explorer") and args and re.match(r"/(select|root|e),", args[0], re.I):
            # explorer /select,"file": the file manager with the item selected (FileManager1), else its folder
            item = host_path(args[0].split(",", 1)[1].strip('"'))
            if args[0].lower().startswith("/select") and shutil.which("gdbus"):
                return ["gdbus", "call", "--session", "--dest", "org.freedesktop.FileManager1", "--object-path",
                        "/org/freedesktop/FileManager1", "--method", "org.freedesktop.FileManager1.ShowItems",
                        "['" + _file_uri(item) + "']", ""]
            return [exe, os.path.dirname(item) if args[0].lower().startswith("/select") else item]
        if low.startswith("cmd") and args and args[0].lower() in ("/c", "/k"):
            return ["sh", "-c", " ".join(args[1:])]
        return [exe] + [host_path(a) if ("\\" in a or a[1:3] == ":\\") else a for a in args]
    hp = host_path(prog)
    if _is_ahk_exe(hp, low):
        import sys
        return [sys.executable, "-m", "bunnyhotkey"] + args     # Run A_AhkPath ' "script.ahk"'
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


def _file_uri(path):
    from urllib.parse import quote
    return "file://" + quote(os.path.abspath(path))


def _is_ahk_exe(hp, low):
    """A_AhkPath (BHK's own entry point) or an AutoHotkey executable named by a script."""
    main = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "__main__.py")
    if os.path.exists(hp) and os.path.realpath(hp) == os.path.realpath(main):
        return True
    base = os.path.basename(low.replace("\\", "/"))
    if base not in ("autohotkey.exe", "autohotkey64.exe", "autohotkey32.exe", "autohotkeyu64.exe", "autohotkeyu32.exe"):
        return False
    from ..prefix import ahk_dir
    # a name alone, or one of the official executables BHK installed into its prefix (the Dash's launch settings)
    return not os.path.isfile(hp) or os.path.realpath(hp).startswith(os.path.realpath(ahk_dir()) + os.sep)


_SYSTEM_VERBS = ("find", "explore", "open", "edit", "print", "properties")


def _verb(target):
    """script.cpp Run: "*Verb target", or a leading system verb (IS_VERB: find, explore, open, edit...)."""
    m = re.match(r"^\*(\w+)\s+(.*)$", target)
    if m:
        return m.group(1).lower(), m.group(2)
    m = re.match(r"^(\w+)[ \t]+(.*)$", target)
    if m and m.group(1).lower() in _SYSTEM_VERBS:
        return m.group(1).lower(), m.group(2)
    return None, target


def editor_command(path):
    r"""argv that opens `path` for editing, as the "edit" verb of .ahk files does on Windows:
    1. the edit command AutoHotkey's Dash saves (Editor settings: HKCR\AutoHotkeyScript\shell\edit\command),
    2. the desktop's default text editor (the text/plain handler, via gtk-launch),
    3. a common graphical editor, 4. $VISUAL / $EDITOR in a terminal, 5. xdg-open."""
    from .files import host_path
    from . import registry
    try:
        cmd = S(registry.RegRead("HKCR\\AutoHotkeyScript\\shell\\edit\\command", "", ""))
    except Exception:
        cmd = ""
    if cmd.strip():
        if "%1" in cmd or "%l" in cmd.lower():
            cmd = re.sub(r'"?%[1lL]"?', lambda _m: '"' + path + '"', cmd)
        else:
            cmd += ' "' + path + '"'
        try:
            return _in_terminal(translate_command(cmd))
        except AhkThrow:
            pass
    if shutil.which("xdg-mime") and shutil.which("gtk-launch"):
        try:
            app = subprocess.run(["xdg-mime", "query", "default", "text/plain"], capture_output=True,
                                 text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            app = ""
        if app and app != "bunnyhotkey.desktop":
            return ["gtk-launch", app[:-8] if app.endswith(".desktop") else app, path]
    for exe in ("mousepad", "gedit", "gnome-text-editor", "xed", "pluma", "kate", "kwrite", "featherpad",
                "geany", "code", "subl"):
        if shutil.which(exe):
            return [exe, path]
    ed = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if ed:
        return _in_terminal(shlex.split(ed) + [path], force=True)
    return ["xdg-open", host_path(path)]


_TERMINAL_EDITORS = {"micro", "nano", "vim", "vi", "nvim", "emacs", "hx", "helix", "kak", "ne", "joe", "mcedit",
                     "jed", "pico", "ed"}


def _in_terminal(argv, force=False):
    """Terminal editors (nano, micro, vim...) need a terminal window to show up in."""
    if not force and os.path.basename(argv[0]) not in _TERMINAL_EDITORS:
        return argv
    for term in ("x-terminal-emulator", "xfce4-terminal", "kitty", "alacritty", "foot", "konsole",
                 "gnome-terminal", "xterm"):
        if shutil.which(term):
            if term in ("gnome-terminal", "kitty", "alacritty", "foot"):
                return [term, "--"] + argv if term == "gnome-terminal" else [term] + (["-e"] if term == "alacritty" else []) + argv
            return [term, "-e", " ".join(shlex.quote(a) for a in argv)]
    return argv


def edit_file(path):
    subprocess.Popen(editor_command(path), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return ""


def _current_user():
    import getpass
    try:
        return getpass.getuser()
    except Exception:
        return ""


class _SuProcess:
    """A program started through su on a pseudo-terminal (RunAs with a password), with the parts of
    subprocess.Popen that Run/RunWait use."""

    def __init__(self, pid, fd):
        self.pid, self.fd, self.returncode = pid, fd, None
        import threading
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self):
        while True:
            try:
                if not os.read(self.fd, 4096):
                    break
            except OSError:
                break

    def poll(self):
        if self.returncode is None:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.returncode = os.waitstatus_to_exitcode(status)
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            _, status = os.waitpid(self.pid, 0)
            self.returncode = os.waitstatus_to_exitcode(status)
        return self.returncode


def _su_spawn(user, password, argv, cwd, target):
    import pty
    import shlex
    import time as _t
    cmd = shlex.join(argv)
    if cwd:
        cmd = f"cd {shlex.quote(cwd)} && {cmd}"
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.execvp("su", ["su", user, "-c", cmd])
        finally:
            os._exit(127)
    buf = b""
    end = _t.monotonic() + 5
    while _t.monotonic() < end and b":" not in buf:          # wait for su's password prompt
        try:
            buf += os.read(fd, 256)
        except OSError:
            break
    os.write(fd, password.encode() + b"\n")
    # authenticated once su starts the program as its child; a wrong password makes su fail (after PAM's delay)
    ok, out = False, b""
    end = _t.monotonic() + 8
    while _t.monotonic() < end:
        try:
            with open(f"/proc/{pid}/task/{pid}/children") as fh:
                if fh.read().strip():
                    ok = True
                    break
        except OSError:
            pass
        wpid, status = os.waitpid(pid, os.WNOHANG)
        if wpid:
            code = os.waitstatus_to_exitcode(status)
            ok = code == 0 and b"failure" not in out.lower()
            p = _SuProcess.__new__(_SuProcess)
            p.pid, p.fd, p.returncode = pid, fd, code
            if ok:
                return p
            break
        import select
        if select.select([fd], [], [], 0.05)[0]:
            try:
                out += os.read(fd, 1024)
            except OSError:
                pass
    if not ok:
        err = O.new_error("OSError", "The user name or password is incorrect.", target)
        from ..errors import AhkThrow
        raise AhkThrow(err)
    return _SuProcess(pid, fd)


def _spawn(target, workdir, options):
    verb, target = _verb(S(target))
    argv = translate_command(target)
    if verb in ("runas",):
        argv = ["pkexec"] + argv
    elif verb in ("edit",):
        argv = editor_command(host_path(target.strip().strip('"')))
    elif verb in ("open", "explore", "find", "print", "properties") and len(argv) == 1:
        argv = ["xdg-open", argv[0]]
    cwd = host_path(S(workdir)) if S(workdir) else None
    opts = S(options).lower()
    stdout = subprocess.DEVNULL if "hide" in opts else None
    ra = getattr(O.RT, "run_as", None)
    if ra and ra[0] and ra[0] != _current_user():
        if len(ra) > 2 and ra[2]:
            return _su_spawn(ra[0], ra[2], argv, cwd, S(target))
        argv = ["pkexec", "--user", ra[0]] + argv
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


def _reap():
    """Collect exited children started by Run so they don't linger as zombies."""
    for pid, p in list(_CHILDREN.items()):
        try:
            if p.poll() is not None:
                del _CHILDREN[pid]
        except Exception:
            del _CHILDREN[pid]


def _alive(pid):
    """A process exists unless it is gone or only a zombie (exited, not yet reaped by its parent)."""
    try:
        with open(f"/proc/{pid}/stat") as fh:
            st = fh.read()
    except OSError:
        return False
    return st[st.rfind(")") + 2:][:1] not in ("Z", "X")


def _pid_of(name_or_pid):
    s = S(name_or_pid) if name_or_pid not in (UNSET, "") else ""
    if s == "":
        return 0
    _reap()
    if s.isdigit():
        pid = int(s)
        return pid if _alive(pid) else 0
    low = s.lower()
    low_noext = low[:-4] if low.endswith(".exe") else low
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/comm") as fh:
                comm = fh.read().strip().lower()
            if (comm == low or comm == low_noext) and _alive(d):
                return int(d)
            exe = os.path.basename(os.readlink(f"/proc/{d}/exe")).lower()
            if (exe == low or exe == low_noext) and _alive(d):
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
