"""File built-ins (lib/file.cpp, TextIO.cpp) with Windows -> Linux path translation.

Like Wine, drive letters map into the BHK prefix (C: -> prefix/drive_c, Z: -> /),
and the user's shell folders (Desktop, Documents, ...) map to the real XDG dirs.
Backslashes are accepted everywhere; lookups fall back to case-insensitive
matching because Windows paths are case-insensitive.
"""
from __future__ import annotations

import codecs
import fnmatch
import glob
import os
import shutil
import stat
import sys
import time

from .. import objects as O
from ..objects import AhkObject, CLASSES, throw
from ..values import UNSET
from . import export, setref


def rt():
    return O.RT


def S(v):
    return O.RT.to_str(v)


# ---------------------------------------------------------------- paths
def prefix_dir() -> str:
    from ..prefix import prefix_root
    return prefix_root()


def _xdg(name, fallback):
    try:
        import subprocess
        out = subprocess.run(["xdg-user-dir", name], capture_output=True, text=True, timeout=2).stdout.strip()
        if out:
            return out
    except (OSError, Exception):
        pass
    return os.path.join(os.path.expanduser("~"), fallback)


_SHELL_CACHE = {}


def shell_folder(name: str) -> str:
    if name not in _SHELL_CACHE:
        home = os.path.expanduser("~")
        _SHELL_CACHE[name] = {
            "desktop": lambda: _xdg("DESKTOP", "Desktop"),
            "documents": lambda: _xdg("DOCUMENTS", "Documents"),
            "downloads": lambda: _xdg("DOWNLOAD", "Downloads"),
            "pictures": lambda: _xdg("PICTURES", "Pictures"),
            "music": lambda: _xdg("MUSIC", "Music"),
            "videos": lambda: _xdg("VIDEOS", "Videos"),
            "appdata": lambda: os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"),
            "localappdata": lambda: os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share"),
            "temp": lambda: os.environ.get("TMPDIR") or "/tmp",
            "home": lambda: home,
            "startup": lambda: os.path.join(home, ".config", "autostart"),
            "startmenu": lambda: os.path.join(home, ".local", "share", "applications"),
            "programs": lambda: os.path.join(home, ".local", "share", "applications"),
        }[name]()
    return _SHELL_CACHE[name]


def _user_map(rest_parts):
    """Map C:\\Users\\<name>\\<Folder> to real directories."""
    if len(rest_parts) >= 2 and rest_parts[0].lower() == "users":
        tail = rest_parts[2:]
        if not tail:
            return shell_folder("home")
        first = tail[0].lower()
        mapping = {"desktop": "desktop", "documents": "documents", "downloads": "downloads", "pictures": "pictures",
                   "music": "music", "videos": "videos"}
        if first in mapping:
            return os.path.join(shell_folder(mapping[first]), *tail[1:])
        if first == "appdata" and len(tail) >= 2:
            sub = tail[1].lower()
            if sub == "roaming":
                return os.path.join(shell_folder("appdata"), *tail[2:])
            if sub == "local":
                if len(tail) >= 3 and tail[2].lower() == "temp":
                    return os.path.join(shell_folder("temp"), *tail[3:])
                return os.path.join(shell_folder("localappdata"), *tail[2:])
        return os.path.join(shell_folder("home"), *tail)
    return None


def host_path(p: str) -> str:
    """Translate a script path (Windows or Linux style) to a host path."""
    if not p:
        return p
    if p.startswith("\\\\?\\"):
        p = p[4:]
    if len(p) >= 2 and p[1] == ":" and p[0].isalpha():
        drive = p[0].lower()
        rest = p[2:].replace("\\", "/").lstrip("/")
        parts = [x for x in rest.split("/") if x]
        if drive == "z":
            return _ci("/" + "/".join(parts))
        if drive == "c":
            mapped = _user_map(parts)
            if mapped is not None:
                return _ci(mapped)
            if parts and parts[0].lower() == "windows" and len(parts) >= 2 and parts[1].lower() == "temp":
                return _ci(os.path.join(shell_folder("temp"), *parts[2:]))
        root = os.path.join(prefix_dir(), f"drive_{drive}")
        return _ci(os.path.join(root, *parts))
    q = p.replace("\\", "/")
    if not q.startswith("/") and not q.startswith("~"):
        q = os.path.join(os.getcwd(), q)
    return _ci(os.path.expanduser(q))


def _ci(path: str) -> str:
    """Case-insensitive resolution of a path whose exact case doesn't exist."""
    if os.path.exists(path) or not path.startswith("/"):
        return path
    parts = path.split("/")
    cur = "/"
    for i, part in enumerate(parts[1:], 1):
        if part in ("", "."):
            continue
        cand = os.path.join(cur, part)
        if os.path.exists(cand):
            cur = cand
            continue
        try:
            low = part.lower()
            match = next((e for e in os.listdir(cur) if e.lower() == low), None)
        except OSError:
            match = None
        if match is None:
            return os.path.join(cur, *[x for x in parts[i:] if x])
        cur = os.path.join(cur, match)
    return cur


def ahk_path(p: str) -> str:
    return p


# ---------------------------------------------------------------- encodings
def _codec(enc: str):
    e = (enc or "").strip().upper()
    if e in ("", "CP0", "UTF-8-RAW", "UTF-8"):
        return "utf-8", e == "UTF-8"
    if e in ("UTF-16", "UTF-16-RAW"):
        return "utf-16-le", e == "UTF-16"
    if e.startswith("CP"):
        num = e[2:]
        return {"65001": "utf-8", "1200": "utf-16-le", "1252": "cp1252", "437": "cp437", "850": "cp850",
                "936": "gbk", "932": "shift_jis", "1251": "cp1251"}.get(num, "cp" + num), False
    return e.lower(), False


def decode_file(data: bytes, enc: str) -> str:
    if data.startswith(codecs.BOM_UTF8):
        return data[3:].decode("utf-8", "replace")
    if data.startswith(codecs.BOM_UTF16_LE):
        return data[2:].decode("utf-16-le", "replace")
    codec, _ = _codec(enc)
    try:
        return data.decode(codec)
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


def parse_enc_options(opts: str, default: str):
    enc = default
    eol = None
    for word in opts.split():
        w = word.lower()
        if w == "`n" or w == "\n":
            eol = "\r\n"
        elif w.startswith("utf") or w.startswith("cp"):
            enc = word
    if "`n" in opts or "\n" in opts:
        eol = "\r\n"
    return enc, eol


# ---------------------------------------------------------------- simple functions
def _os_error(e: OSError, extra=""):
    err = O.new_error("OSError", e.strerror or str(e), extra)
    err.define_value("Number", {2: 2, 3: 3, 5: 5, 17: 183, 13: 5, 39: 145}.get(e.errno or 0, e.errno or 0))
    from ..errors import AhkThrow
    raise AhkThrow(err)


@export()
def FileRead(filename, options=""):
    path = host_path(S(filename))
    opts = S(options)
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        _os_error(e, S(filename))
    if "raw" in opts.lower().split():
        from .buffer import BufferObj
        b = BufferObj(len(data))
        b.data[:] = data
        return b
    m = None
    import re
    m = re.search(r"m(\d+)", opts, re.I)
    if m:
        data = data[:int(m.group(1))]
    enc, _ = parse_enc_options(opts, rt().thread.settings.file_encoding)
    text = decode_file(data, enc)
    if "`n" in opts or "\n" in opts.split():
        text = text.replace("\r\n", "\n")
    return text


@export()
def FileAppend(text, filename=UNSET, options=""):
    r = rt()
    opts = S(options)
    if filename is UNSET or filename == "":
        out = r.thread.loop.out_file
        if not out:
            throw("Error", "Missing a required parameter.") if False else None
            return ""
        path = out
    else:
        fn = S(filename)
        if fn in ("*", "**"):
            stream = sys.stdout if fn == "*" else sys.stderr
            s = S(text) if not isinstance(text, AhkObject) else ""
            if "`n" in opts:
                s = s.replace("\n", "\r\n")
            stream.write(s)
            stream.flush()
            return ""
        path = host_path(fn)
    enc, eol = parse_enc_options(opts, r.thread.settings.file_encoding)
    codec, bom = _codec(enc)
    if isinstance(text, AhkObject):
        from .buffer import BufferObj
        if isinstance(text, BufferObj):
            data = bytes(text.data)
        else:
            throw("TypeError", O.type_error_msg("String", text))
    else:
        s = S(text)
        if eol:
            s = s.replace("\r\n", "\n").replace("\n", "\r\n")
        new = not os.path.exists(path) or os.path.getsize(path) == 0
        data = s.encode(codec, "replace")
        if bom and new:
            data = (codecs.BOM_UTF8 if codec == "utf-8" else codecs.BOM_UTF16_LE) + data
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True) if False else None
        with open(path, "ab") as fh:
            fh.write(data)
    except OSError as e:
        _os_error(e, path)
    return ""


@export()
def FileDelete(pattern):
    hp = host_path(S(pattern))
    matches = _glob(hp)
    if not matches:
        throw("OSError", "The system cannot find the file specified.", S(pattern))
    failed = 0
    for m in matches:
        try:
            if os.path.isfile(m) or os.path.islink(m):
                os.remove(m)
        except OSError:
            failed += 1
    if failed:
        throw("OSError", f"{failed} files could not be deleted.", S(pattern))
    return ""


def _glob(hp):
    if any(c in hp for c in "*?"):
        d, pat = os.path.split(hp)
        try:
            return [os.path.join(d, n) for n in os.listdir(d or ".") if fnmatch.fnmatch(n.lower(), pat.lower().replace("*.*", "*"))]
        except OSError:
            return []
    return [hp] if os.path.lexists(hp) else []


def _copy_move(src, dst, overwrite, move):
    hs = host_path(S(src))
    hd = host_path(S(dst))
    ow = rt().to_int(overwrite) if overwrite != "" else 0
    files = [f for f in _glob(hs) if os.path.isfile(f)]
    if not files:
        throw("OSError", "The system cannot find the file specified.", S(src))
    failed = 0
    dst_is_dir = os.path.isdir(hd)
    for f in files:
        target = os.path.join(hd, os.path.basename(f)) if dst_is_dir else hd
        if any(c in os.path.basename(hd) for c in "*?") and not dst_is_dir:
            name, ext = os.path.splitext(os.path.basename(f))
            pat = os.path.basename(hd)
            pn, pe = os.path.splitext(pat)
            target = os.path.join(os.path.dirname(hd), (name if pn == "*" else pn) + (ext if pe in (".*", "") and pn == "*" or pe == ".*" else pe))
        try:
            if os.path.exists(target) and not ow:
                failed += 1
                continue
            if move:
                shutil.move(f, target)
            else:
                shutil.copy2(f, target)
        except OSError:
            failed += 1
    if failed:
        throw("Error", f"{failed} files could not be {'moved' if move else 'copied'}.", str(failed))
    return ""


@export()
def FileCopy(src, dst, overwrite=0):
    return _copy_move(src, dst, overwrite, False)


@export()
def FileMove(src, dst, overwrite=0):
    return _copy_move(src, dst, overwrite, True)


def attrib_string(path) -> str:
    try:
        st = os.lstat(path)
    except OSError:
        return ""
    a = ""
    if not os.access(path, os.W_OK):
        a += "R"
    if os.path.basename(path).startswith("."):
        a += "H"
    if stat.S_ISDIR(st.st_mode):
        a += "D"
    else:
        a += "A"
    if stat.S_ISLNK(st.st_mode):
        a += "L"
    return a.replace("A", "A") if a else "N"


@export()
def FileExist(pattern):
    for m in _glob(host_path(S(pattern))):
        return attrib_string(m) or "N"
    return ""


@export()
def DirExist(pattern):
    for m in _glob(host_path(S(pattern))):
        if os.path.isdir(m):
            return attrib_string(m)
    return ""


@export()
def FileGetAttrib(filename=UNSET):
    path = _loop_or(filename)
    if not os.path.lexists(path):
        throw("OSError", "The system cannot find the file specified.", path)
    return attrib_string(path)


@export()
def FileSetAttrib(attrs, pattern=UNSET, mode=""):
    path = _loop_or(pattern)
    a = S(attrs).upper()
    try:
        st = os.stat(path)
        mode_bits = st.st_mode
        if "+R" in a:
            os.chmod(path, mode_bits & ~0o222)
        elif "-R" in a:
            os.chmod(path, mode_bits | 0o200)
    except OSError as e:
        _os_error(e, path)
    return ""


def _loop_or(filename):
    if filename is UNSET or filename == "":
        info = rt().thread.loop.file
        if info is None:
            throw("ValueError", "Invalid value.")
        return info.path
    return host_path(S(filename))


@export()
def FileGetSize(filename=UNSET, units=""):
    path = _loop_or(filename)
    try:
        n = os.path.getsize(path)
    except OSError as e:
        _os_error(e, path)
    u = S(units).upper()[:1]
    return n // 1024 if u == "K" else n // (1024 * 1024) if u == "M" else n


def _fmt_time(t):
    return time.strftime("%Y%m%d%H%M%S", time.localtime(t))


@export()
def FileGetTime(filename=UNSET, which="M"):
    path = _loop_or(filename)
    try:
        st = os.stat(path)
    except OSError as e:
        _os_error(e, path)
    w = S(which).upper()[:1] or "M"
    t = {"M": st.st_mtime, "C": getattr(st, "st_birthtime", st.st_ctime), "A": st.st_atime}.get(w, st.st_mtime)
    return _fmt_time(t)


@export()
def FileSetTime(yyyymmdd="", filename=UNSET, which="M", mode=""):
    from .datetime_ import parse_timestamp
    path = _loop_or(filename)
    d = parse_timestamp(S(yyyymmdd)) if S(yyyymmdd) else None
    t = time.mktime(d.timetuple()) if d else time.time()
    st = os.stat(path)
    w = S(which).upper()[:1] or "M"
    os.utime(path, (t if w == "A" else st.st_atime, t if w == "M" else st.st_mtime))
    return ""


@export()
def FileGetVersion(filename=UNSET):
    return ""


@export()
def FileRecycle(pattern):
    for m in _glob(host_path(S(pattern))):
        import subprocess
        if shutil.which("gio"):
            subprocess.run(["gio", "trash", m])
        else:
            trash = os.path.join(shell_folder("localappdata"), "Trash", "files")
            os.makedirs(trash, exist_ok=True)
            shutil.move(m, trash)
    return ""


@export()
def FileRecycleEmpty(drive=""):
    import subprocess
    if shutil.which("gio"):
        subprocess.run(["gio", "trash", "--empty"])
    return ""


@export()
def FileCreateShortcut(target, link, workdir="", args="", desc="", icon="", key="", iconnum="", runstate=""):
    lp = host_path(S(link))
    if lp.lower().endswith(".lnk"):
        lp = lp[:-4] + ".desktop"
    tp = host_path(S(target))
    with open(lp, "w") as fh:
        fh.write(f"[Desktop Entry]\nType=Application\nName={os.path.basename(lp)[:-8]}\nExec=\"{tp}\" {S(args)}\n"
                 f"Path={host_path(S(workdir)) if S(workdir) else ''}\nComment={S(desc)}\nIcon={host_path(S(icon)) if S(icon) else ''}\n")
    os.chmod(lp, 0o755)
    return ""


@export(byref=(1, 2, 3, 4, 5, 6, 7))
def FileGetShortcut(link, target=UNSET, dir_=UNSET, args=UNSET, desc=UNSET, icon=UNSET, iconnum=UNSET, runstate=UNSET):
    lp = host_path(S(link))
    if lp.lower().endswith(".lnk") and not os.path.exists(lp):
        lp = lp[:-4] + ".desktop"
    vals = {}
    try:
        with open(lp) as fh:
            for line in fh:
                k, _, v = line.partition("=")
                vals[k.strip()] = v.strip()
    except OSError as e:
        _os_error(e, lp)
    exe = vals.get("Exec", "")
    import shlex
    try:
        parts = shlex.split(exe)
    except ValueError:
        parts = exe.split()
    setref(target, parts[0] if parts else "")
    setref(args, " ".join(parts[1:]))
    setref(dir_, vals.get("Path", ""))
    setref(desc, vals.get("Comment", ""))
    setref(icon, vals.get("Icon", ""))
    setref(iconnum, 1)
    setref(runstate, 1)
    return ""


@export()
def DirCreate(path):
    try:
        os.makedirs(host_path(S(path)), exist_ok=True)
    except OSError as e:
        _os_error(e, S(path))
    return ""


@export()
def DirDelete(path, recurse=0):
    hp = host_path(S(path))
    try:
        if rt().to_int(recurse) if recurse != "" else 0:
            shutil.rmtree(hp)
        else:
            os.rmdir(hp)
    except OSError as e:
        _os_error(e, S(path))
    return ""


@export()
def DirCopy(src, dst, overwrite=0):
    hs, hd = host_path(S(src)), host_path(S(dst))
    try:
        shutil.copytree(hs, hd, dirs_exist_ok=bool(rt().to_int(overwrite) if overwrite != "" else 0))
    except (OSError, shutil.Error) as e:
        throw("OSError", str(e), S(src))
    return ""


@export()
def DirMove(src, dst, flag=0):
    hs, hd = host_path(S(src)), host_path(S(dst))
    f = S(flag).upper()
    try:
        if f == "R":
            os.rename(hs, hd)
        elif os.path.isdir(hd) and f in ("1", "2"):
            shutil.move(hs, os.path.join(hd, os.path.basename(hs)) if f == "1" else hd)
        else:
            if os.path.exists(hd):
                throw("OSError", "Cannot create a file when that file already exists.", S(dst))
            shutil.move(hs, hd)
    except OSError as e:
        _os_error(e, S(src))
    return ""


@export()
def DirSelect(start="", options=1, prompt=""):
    from .gui import file_dialog
    return file_dialog("dir", S(start), S(prompt))


@export()
def FileSelect(options=0, root="", title="", filter_=""):
    from .gui import file_dialog
    o = S(options).upper()
    kind = "save" if "S" in o else "dir" if "D" in o else "multi" if "M" in o else "open"
    return file_dialog(kind, S(root), S(title), S(filter_))


@export(byref=(1, 2, 3, 4, 5))
def SplitPath(path, name=UNSET, dir_=UNSET, ext=UNSET, name_no_ext=UNSET, drive=UNSET):
    p = S(path)
    if "://" in p:
        scheme, _, rest = p.partition("://")
        host, _, tail = rest.partition("/")
        drv = scheme + "://" + host
        dpart = p.rsplit("/", 1)
        setref(name, dpart[-1] if "/" in rest else "")
        setref(dir_, dpart[0] if "/" in rest else p)
        setref(drive, drv)
        nm = dpart[-1] if "/" in rest else ""
    else:
        idx = max(p.rfind("\\"), p.rfind("/"))
        nm = p[idx + 1:]
        d = p[:idx] if idx >= 0 else ""
        setref(name, nm)
        setref(dir_, d)
        if len(p) >= 2 and p[1] == ":":
            setref(drive, p[:2])
        elif p.startswith("\\\\"):
            parts = p[2:].split("\\")
            setref(drive, "\\\\" + "\\".join(parts[:2]))
        else:
            setref(drive, "/" if p.startswith("/") else "")
    dot = nm.rfind(".")
    setref(ext, nm[dot + 1:] if dot >= 0 else "")
    setref(name_no_ext, nm[:dot] if dot >= 0 else nm)
    return ""


@export()
def FileEncoding(enc=""):
    e = S(enc)
    if e and _codec(e)[0] is None:
        throw("ValueError", "Invalid value.", e)
    rt().thread.settings.file_encoding = e or "CP0"
    return ""


@export()
def DriveGetFreeSpace(path):
    st = os.statvfs(host_path(S(path)))
    return st.f_bavail * st.f_frsize // (1024 * 1024)


@export()
def DriveGetCapacity(path):
    st = os.statvfs(host_path(S(path)))
    return st.f_blocks * st.f_frsize // (1024 * 1024)


@export()
def DriveGetList(type_=""):
    return "CZ"


@export()
def DriveGetType(path):
    return "Fixed"


@export()
def DriveGetStatus(path):
    return "Ready" if os.path.exists(host_path(S(path))) else "Invalid"


@export()
def DriveGetFileSystem(path):
    return "ext4"


@export()
def DriveGetLabel(path):
    return ""


@export()
def DriveGetSerial(path):
    return 0


@export()
def DriveEject(drive="", retract=0):
    import subprocess
    subprocess.run(["eject"] + (["-t"] if rt().to_int(retract) else []), capture_output=True)
    return ""


# ---------------------------------------------------------------- INI
def _ini_read_lines(path):
    try:
        with open(path, "rb") as fh:
            return decode_file(fh.read(), "UTF-8").splitlines()
    except OSError:
        return None


@export()
def IniRead(filename, section=UNSET, key=UNSET, default=UNSET):
    lines = _ini_read_lines(host_path(S(filename)))
    if section is UNSET:
        if lines is None:
            throw("OSError", "The system cannot find the file specified.", S(filename))
        return "\n".join(l.strip()[1:-1] for l in lines if l.strip().startswith("[") and l.strip().endswith("]"))
    sec = S(section).lower()
    cur = None
    out = []
    if lines is not None:
        for l in lines:
            st = l.strip()
            if st.startswith("[") and st.endswith("]"):
                cur = st[1:-1].strip().lower()
                continue
            if cur != sec:
                continue
            if key is UNSET:
                if st and not st.startswith(";"):
                    out.append(l.rstrip())
                continue
            k, eq, v = st.partition("=")
            if eq and k.strip().lower() == S(key).lower():
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                return v
    if key is UNSET:
        if lines is None or (not out and sec not in [l.strip()[1:-1].lower() for l in lines if l.strip().startswith("[")]):
            if default is not UNSET:
                return default
            throw("OSError", "The requested key, section or file was not found.", S(section))
        return "\n".join(out)
    if default is not UNSET:
        return default
    throw("OSError", "The requested key, section or file was not found.", S(key))


@export()
def IniWrite(value, filename, section, key=UNSET):
    path = host_path(S(filename))
    lines = _ini_read_lines(path) or []
    sec = S(section)
    out = []
    in_sec = False
    done = False
    found_sec = False
    for l in lines:
        st = l.strip()
        if st.startswith("[") and st.endswith("]"):
            if in_sec and not done:
                if key is UNSET:
                    out.extend(S(value).split("\n"))
                else:
                    out.append(f"{S(key)}={S(value)}")
                done = True
            in_sec = st[1:-1].strip().lower() == sec.lower()
            found_sec = found_sec or in_sec
            out.append(l)
            continue
        if in_sec and not done:
            if key is UNSET:
                continue
            k, eq, v = st.partition("=")
            if eq and k.strip().lower() == S(key).lower():
                out.append(f"{S(key)}={S(value)}")
                done = True
                continue
        out.append(l)
    if not done:
        if not found_sec:
            if out and out[-1].strip():
                pass
            out.append(f"[{sec}]")
        if key is UNSET:
            out.extend(S(value).split("\n"))
        else:
            out.append(f"{S(key)}={S(value)}")
    with open(path, "w", encoding="utf-8", newline="\r\n" if os.name == "nt" else "\n") as fh:
        fh.write("\n".join(out) + "\n")
    return ""


@export()
def IniDelete(filename, section, key=UNSET):
    path = host_path(S(filename))
    lines = _ini_read_lines(path)
    if lines is None:
        throw("OSError", "The system cannot find the file specified.", S(filename))
    sec = S(section).lower()
    out = []
    in_sec = False
    for l in lines:
        st = l.strip()
        if st.startswith("[") and st.endswith("]"):
            in_sec = st[1:-1].strip().lower() == sec
            if in_sec and key is UNSET:
                continue
            out.append(l)
            continue
        if in_sec:
            if key is UNSET:
                continue
            k, eq, _ = st.partition("=")
            if eq and k.strip().lower() == S(key).lower():
                continue
        out.append(l)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    return ""


# ---------------------------------------------------------------- File object
class FileObj(AhkObject):
    __slots__ = ("fh", "codec", "path", "eol_in", "eol_out", "bom_len")

    def __init__(self, fh, codec, path, eol_in, eol_out, bom_len):
        super().__init__(CLASSES["File"].prototype)
        self.fh = fh
        self.codec = codec
        self.path = path
        self.eol_in = eol_in
        self.eol_out = eol_out
        self.bom_len = bom_len


def _file_setup():
    from ..classes import method, prop
    p = CLASSES["File"].prototype
    if p.own("Read") is not None:
        return
    method(p, "Read", lambda this, n=UNSET: _f_read(this, n))
    method(p, "Write", lambda this, s: _f_write(this, S(s)))
    method(p, "ReadLine", lambda this: _f_readline(this))
    method(p, "WriteLine", lambda this, s="": _f_write(this, S(s) + "\n"))
    method(p, "RawRead", lambda this, buf, n=UNSET: _f_rawread(this, buf, n))
    method(p, "RawWrite", lambda this, data, n=UNSET: _f_rawwrite(this, data, n))
    method(p, "Seek", lambda this, dist, origin=UNSET: _f_seek(this, dist, origin))
    method(p, "Close", lambda this: _f_close(this))
    for nm, fmt, size in (("Char", "b", 1), ("UChar", "B", 1), ("Short", "h", 2), ("UShort", "H", 2), ("Int", "i", 4),
                          ("UInt", "I", 4), ("Int64", "q", 8), ("Float", "f", 4), ("Double", "d", 8), ("Ptr", "q", 8),
                          ("UPtr", "Q", 8)):
        method(p, "Read" + nm, lambda this, fmt=fmt, size=size: _f_readnum(this, fmt, size))
        method(p, "Write" + nm, lambda this, v, fmt=fmt, size=size: _f_writenum(this, fmt, size, v))
    prop(p, "Pos", get=lambda this: this.fh.tell(), set=lambda this, v: this.fh.seek(rt().to_int(v)))
    prop(p, "Position", get=lambda this: this.fh.tell(), set=lambda this, v: this.fh.seek(rt().to_int(v)))
    prop(p, "Length", get=lambda this: _f_len(this), set=lambda this, v: this.fh.truncate(rt().to_int(v)) and v)
    prop(p, "AtEOF", get=lambda this: int(this.fh.tell() >= _f_len(this)))
    prop(p, "Encoding", get=lambda this: {"utf-8": "UTF-8", "utf-16-le": "UTF-16"}.get(this.codec, this.codec.upper()),
         set=lambda this, v: setattr(this, "codec", _codec(S(v))[0]))
    prop(p, "Handle", get=lambda this: this.fh.fileno())
    method(p, "__Delete", lambda this: _f_close(this))


def _f_len(f):
    cur = f.fh.tell()
    f.fh.seek(0, 2)
    n = f.fh.tell()
    f.fh.seek(cur)
    return n


def _f_read(f, n):
    data = f.fh.read() if n is UNSET else f.fh.read(rt().to_int(n) * (2 if f.codec == "utf-16-le" else 1))
    s = data.decode(f.codec, "replace")
    if f.eol_in:
        s = s.replace("\r\n", "\n")
    return s


def _f_readline(f):
    line = f.fh.readline()
    s = line.decode(f.codec, "replace")
    if s.endswith("\n"):
        s = s[:-1]
    if s.endswith("\r"):
        s = s[:-1]
    return s


def _f_write(f, s):
    if f.eol_out:
        s = s.replace("\n", "\r\n")
    data = s.encode(f.codec, "replace")
    f.fh.write(data)
    return len(data)


def _f_rawread(f, buf, n):
    from .buffer import BufferObj
    cnt = rt().to_int(n) if n is not UNSET else len(buf.data)
    data = f.fh.read(cnt)
    buf.data[:len(data)] = data
    return len(data)


def _f_rawwrite(f, data, n):
    from .buffer import BufferObj
    if isinstance(data, BufferObj):
        b = bytes(data.data[: rt().to_int(n) if n is not UNSET else len(data.data)])
    else:
        b = S(data).encode(f.codec)
        if n is not UNSET:
            b = b[:rt().to_int(n)]
    f.fh.write(b)
    return len(b)


def _f_seek(f, dist, origin):
    o = rt().to_int(origin) if origin is not UNSET else (2 if rt().to_int(dist) < 0 else 0)
    f.fh.seek(rt().to_int(dist), o)
    return 1


def _f_close(f):
    try:
        f.fh.close()
    except Exception:
        pass
    return ""


def _f_readnum(f, fmt, size):
    import struct
    data = f.fh.read(size)
    if len(data) < size:
        return ""
    return struct.unpack("<" + fmt, data)[0]


def _f_writenum(f, fmt, size, v):
    import struct
    n = rt().to_num(v)
    if fmt in "fd":
        n = float(n)
    else:
        n = int(n)
        if fmt.isupper():
            n &= (1 << (8 * size)) - 1
    f.fh.write(struct.pack("<" + fmt, n))
    return size


@export()
def FileOpen(filename, flags, encoding=UNSET):
    _file_setup()
    fn = S(filename)
    fl = S(flags) if not isinstance(flags, int) else {0: "r", 1: "w", 2: "a", 3: "rw"}.get(flags & 3, "r")
    fl_low = fl.lower()
    mode = "r"
    if fl_low.startswith("rw"):
        mode = "r+b"
    elif fl_low.startswith("r"):
        mode = "rb"
    elif fl_low.startswith("w"):
        mode = "w+b"
    elif fl_low.startswith("a"):
        mode = "a+b"
    eol_in = "`n" in fl or "\n" in fl
    eol_out = eol_in
    enc = S(encoding) if encoding is not UNSET else rt().thread.settings.file_encoding
    codec, bom = _codec(enc)
    if fn in ("*", "**"):
        stream = sys.stdin.buffer if mode == "rb" else (sys.stdout.buffer if fn == "*" else sys.stderr.buffer)
        return FileObj(stream, codec, fn, eol_in, eol_out, 0)
    path = host_path(fn)
    try:
        if mode == "r+b" and not os.path.exists(path):
            open(path, "wb").close()
        fh = open(path, mode)
    except OSError as e:
        rt().last_error = e.errno or 0
        _os_error(e, fn)
    bom_len = 0
    if mode in ("rb", "r+b"):
        head = fh.read(3)
        if head.startswith(codecs.BOM_UTF8):
            codec, bom_len = "utf-8", 3
        elif head.startswith(codecs.BOM_UTF16_LE):
            codec, bom_len = "utf-16-le", 2
        fh.seek(bom_len)
    elif mode == "w+b" and bom:
        fh.write(codecs.BOM_UTF8 if codec == "utf-8" else codecs.BOM_UTF16_LE)
    return FileObj(fh, codec, path, eol_in, eol_out, bom_len)
