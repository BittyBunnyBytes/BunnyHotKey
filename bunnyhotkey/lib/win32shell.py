"""Win32 API for DllCall that AutoHotkey's own UX scripts (Dash, New Script, Launch/Editor settings) use:
version resources of PE files (version.dll), shell32/shlwapi lookups mapped to the desktop's applications,
dialog control IDs and a few shell notifications.  Struct layouts are the 64-bit Windows SDK's."""
from __future__ import annotations

import os
import re
import shlex
import shutil
import struct
import subprocess

from .dllcall import EMU, I, _arg, _fail, _null, _put_str, _write_out
from .win32emu import _alloc, _ptr, _read, _str_arg, _write

ERROR_FILE_NOT_FOUND, ERROR_INVALID_PARAMETER, ERROR_RESOURCE_TYPE_NOT_FOUND = 2, 87, 1813
S_OK, S_FALSE, E_POINTER = 0, 1, 0x80004003
HRESULT_NO_ASSOCIATION = 0x80070483                     # HRESULT_FROM_WIN32(ERROR_NO_ASSOCIATION)


# ---------------------------------------------------------------- version.dll: VS_VERSIONINFO of PE files
def _pe_version_resource(path):
    """The raw VS_VERSIONINFO block of a PE file (RT_VERSION resource), or None."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    if data[:2] != b"MZ" or len(data) < 0x40:
        return None
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        return None
    nsect, opt_size = struct.unpack_from("<H", data, pe + 6)[0], struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    dirs = opt + (112 if magic == 0x20B else 96)
    if struct.unpack_from("<I", data, dirs - 4)[0] < 3:   # NumberOfRvaAndSizes: no resource directory
        return None
    rsrc_rva = struct.unpack_from("<I", data, dirs + 2 * 8)[0]
    sections = [struct.unpack_from("<IIII", data, opt + opt_size + 40 * i + 8) for i in range(nsect)]

    def off(rva):
        for vsize, va, rawsize, rawptr in sections:
            if va <= rva < va + max(vsize, rawsize):
                return rawptr + rva - va
        return None

    base = off(rsrc_rva)
    if not rsrc_rva or base is None:
        return None

    def entries(d):
        named, ids = struct.unpack_from("<HH", data, base + d + 12)
        return [struct.unpack_from("<II", data, base + d + 16 + 8 * i) for i in range(named + ids)]

    def first_child(d, want=None):
        for name, target in entries(d):
            if want is None or (not name & 0x80000000 and name == want):
                return target
        return None

    t = first_child(0, 16)                                  # RT_VERSION
    if t is None or not t & 0x80000000:
        return None
    n = first_child(t & 0x7FFFFFFF)
    if n is None or not n & 0x80000000:
        return None
    lang = first_child(n & 0x7FFFFFFF)
    if lang is None or lang & 0x80000000:
        return None
    rva, size = struct.unpack_from("<II", data, base + lang)
    o = off(rva)
    return data[o:o + size] if o is not None else None


def _installed_ahk_exe():
    from ..prefix import installed_versions
    from .strings import VerCompare
    best = None
    for ver, info in installed_versions().items():
        exe = os.path.join(info.get("path", ""), "AutoHotkey64.exe")
        if os.path.isfile(exe) and (best is None or VerCompare(ver, best[0]) > 0):
            best = (ver, exe)
    return best[1] if best else None


def _version_block(name):
    from .files import host_path
    path = host_path(name)
    if not os.path.isfile(path):
        return _fail(ERROR_FILE_NOT_FOUND, None)
    if os.path.realpath(path) == os.path.realpath(_program_path()):
        path = _installed_ahk_exe() or path             # BHK stands in for the newest installed AutoHotkey
    raw = _pe_version_resource(path)
    if not raw:
        return _fail(ERROR_RESOURCE_TYPE_NOT_FOUND, None)
    return raw


def _get_file_version_info_size(p):
    raw = _version_block(_str_arg(_arg(p, 0)))
    if not _null(_arg(p, 1)):
        _write_out(_arg(p, 1), "I", 0)
    return len(raw) if raw else 0


def _get_file_version_info(p):
    raw = _version_block(_str_arg(_arg(p, 0)))
    if not raw:
        return 0
    n = min(I(_arg(p, 2)) & 0xFFFFFFFF, len(raw))
    _write(_ptr(_arg(p, 3)), raw[:n])
    return 1


def _align4(n):
    return (n + 3) & ~3


def _node(addr, at):
    """(length, value length, type, key, value offset) of the VS_VERSIONINFO node at addr+at."""
    length, vlen, typ = struct.unpack("<HHH", _read(addr + at, 6))
    key, k = b"", at + 6
    while True:
        ch = _read(addr + k, 2)
        k += 2
        if ch == b"\0\0":
            break
        key += ch
    return length, vlen, typ, key.decode("utf-16-le", "replace"), _align4(k)


def _ver_query_value(p):
    addr, sub = _ptr(_arg(p, 0)), _str_arg(_arg(p, 1))
    if not addr:
        return 0
    at = 0
    length, vlen, typ, _key, val = _node(addr, at)
    for part in [x for x in sub.split("\\") if x]:
        end = at + length
        child = _align4(val + (vlen * 2 if typ == 1 else vlen))
        while child < end:
            clen, cvlen, ctyp, ckey, cval = _node(addr, child)
            if clen == 0:
                child = end
                break
            if ckey.lower() == part.lower():
                at, length, vlen, typ, val = child, clen, cvlen, ctyp, cval
                break
            child = _align4(child + clen)
        if child >= end:
            return 0
    if not vlen:
        return 0
    _write_out(_arg(p, 2), "Q", addr + val)
    _write_out(_arg(p, 3), "I", vlen)                      # WCHARs (incl. NUL) for text, bytes for binary
    return 1


EMU.update({
    "getfileversioninfosize": _get_file_version_info_size, "getfileversioninfosizeex": lambda p: (
        _get_file_version_info_size(p[1:])),
    "getfileversioninfo": _get_file_version_info, "getfileversioninfoex": lambda p: _get_file_version_info(p[1:]),
    "verqueryvalue": _ver_query_value,
})


# ---------------------------------------------------------------- shell32: CommandLineToArgvW
def split_command_line(cmd):
    """Windows' argv rules: the program name ends at the next quote/space; then 2n backslashes + quote = n and a
    quote toggle, 2n+1 + quote = n and a literal quote, "" inside quotes = a literal quote."""
    args, i, n = [], 0, len(cmd)
    if cmd.startswith('"'):
        j = cmd.find('"', 1)
        j = n if j < 0 else j
        args.append(cmd[1:j])
        i = j + 1
    else:
        m = re.match(r"[^ \t]*", cmd)
        args.append(m.group(0))
        i = m.end()
    while True:
        while i < n and cmd[i] in " \t":
            i += 1
        if i >= n:
            break
        cur, quoted = [], False
        while i < n and (quoted or cmd[i] not in " \t"):
            if cmd[i] == "\\":
                j = i
                while j < n and cmd[j] == "\\":
                    j += 1
                if j < n and cmd[j] == '"':
                    cur.append("\\" * ((j - i) // 2))
                    if (j - i) % 2:
                        cur.append('"')
                        i = j + 1
                    else:
                        i = j
                else:
                    cur.append(cmd[i:j])
                    i = j
                continue
            if cmd[i] == '"':
                if quoted and i + 1 < n and cmd[i + 1] == '"':
                    cur.append('"')
                    i += 2
                    continue
                quoted = not quoted
                i += 1
                continue
            cur.append(cmd[i])
            i += 1
        args.append("".join(cur))
    return args


def _command_line_to_argv(p):
    cmd = _str_arg(_arg(p, 0))
    args = split_command_line(cmd) if cmd.strip() else [_program_path()]
    raw = [a.encode("utf-16-le") + b"\0\0" for a in args]
    mem = _alloc(8 * len(args) + sum(len(r) for r in raw), True)     # one block: LocalFree frees it all
    s = mem + 8 * len(args)
    for i, r in enumerate(raw):
        _write(mem + 8 * i, struct.pack("<Q", s))
        _write(s, r)
        s += len(r)
    _write_out(_arg(p, 1), "i", len(args))
    return mem


def _program_path():
    from .. import objects as O
    return O.RT.bivars["a_ahkpath"][0]()


# ---------------------------------------------------------------- applications: .desktop entries for exe names
def _desktop_dirs():
    home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return [home] + (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")


def _desktop_entry(desktop_id):
    for d in _desktop_dirs():
        path = os.path.join(d, "applications", desktop_id)
        if os.path.isfile(path):
            entry, section = {}, ""
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        line = line.strip()
                        if line.startswith("["):
                            section = line
                        elif section == "[Desktop Entry]" and "=" in line:
                            k, v = line.split("=", 1)
                            entry.setdefault(k.strip(), v.strip())
            except OSError:
                return None
            return entry
    return None


def _mime_default(mime):
    if not shutil.which("xdg-mime"):
        return None
    try:
        app = subprocess.run(["xdg-mime", "query", "default", mime], capture_output=True, text=True,
                             timeout=5).stdout.strip().split(";")[0]
    except (OSError, subprocess.SubprocessError):
        return None
    if not app or app == "bunnyhotkey.desktop":
        return None
    return _desktop_entry(app)


def _exec_argv(entry):
    try:
        argv = shlex.split(entry.get("Exec", ""))
    except ValueError:
        return []
    return [a for a in argv if not re.fullmatch(r"%[a-zA-Z]", a)]


def _app_for(assoc, by_exe):
    """{name, exe, cmd} of the desktop application standing in for a Windows exe name, ProgId or extension."""
    a = assoc.strip().strip('"')
    low = os.path.basename(a.replace("\\", "/")).lower()
    entry = None
    if by_exe:
        stem = low[:-4] if low.endswith(".exe") else low
        if stem in ("notepad", "wordpad", "write"):
            entry = _mime_default("text/plain")             # the desktop's text editor plays Notepad
        if entry is None:
            exe = _resolve_exe(a)
            if exe is None:
                return None
            return {"name": os.path.basename(exe), "exe": exe, "cmd": f'"{exe}" "%1"'}
    else:
        mime = {".txt": "text/plain", ".ahk": "text/plain", ".ini": "text/plain", ".log": "text/plain",
                "txtfile": "text/plain"}.get(low)
        entry = _mime_default(mime) if mime else None
    if entry is None:
        return None
    argv = _exec_argv(entry)
    exe = shutil.which(argv[0]) if argv else None
    if exe is None:
        return None
    cmd = " ".join(f'"{x}"' if " " in x or x == exe else x for x in [exe] + argv[1:]) + ' "%1"'
    return {"name": entry.get("Name") or os.path.basename(exe), "exe": exe, "cmd": cmd}


def _resolve_exe(name):
    """An executable file for a Windows program name: a path, a PATH program, or BHK's Windows-program map."""
    from .files import host_path
    from .process import _TRANSLATE, _first_available
    n = name.strip().strip('"')
    hp = host_path(n)
    for cand in (hp, hp[:-4] if hp.lower().endswith(".exe") else None):
        if cand and os.path.isfile(cand) and (os.access(cand, os.X_OK) or cand.lower().endswith(".exe")):
            return cand
    if "/" in n or "\\" in n:
        return None
    low = n.lower()
    if low in _TRANSLATE:
        exe = _first_available(_TRANSLATE[low])
        return shutil.which(exe) if exe else None
    return shutil.which(low[:-4] if low.endswith(".exe") else n)


def _find_executable(p):
    """FindExecutable(lpFile, lpDirectory, lpResult): > 32 on success."""
    name = _str_arg(_arg(p, 0))
    d = _str_arg(_arg(p, 1)) if not _null(_arg(p, 1)) else ""
    exe = None
    if d and not os.path.isabs(name.replace("\\", "/")):
        exe = _resolve_exe(os.path.join(d, name))
    exe = exe or _resolve_exe(name)
    if exe is None:
        from .files import host_path
        hp = host_path(name)
        if os.path.isfile(hp):                              # a document: the program that opens it
            mime = _mime_of(hp)
            app = _app_for(".txt", False) if mime == "text/plain" else None
            exe = app["exe"] if app else None
            if exe is None:
                return 31                                   # SE_ERR_NOASSOC
        else:
            return ERROR_FILE_NOT_FOUND
    _put_str(_arg(p, 2), exe[:259])
    return 42


def _mime_of(path):
    try:
        return subprocess.run(["xdg-mime", "query", "filetype", path], capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _assoc_query_string(p):
    """AssocQueryString(flags, str, pszAssoc, pszExtra, pszOut, pcchOut) -> HRESULT."""
    flags, what = I(_arg(p, 0)), I(_arg(p, 1))
    app = _app_for(_str_arg(_arg(p, 2)), bool(flags & 2))   # ASSOCF_INIT_BYEXENAME
    if app is None:
        return HRESULT_NO_ASSOCIATION
    s = {1: app["cmd"], 2: app["exe"], 4: app["name"]}.get(what)   # ASSOCSTR_COMMAND/EXECUTABLE/FRIENDLYAPPNAME
    if s is None:
        return HRESULT_NO_ASSOCIATION
    out, pcch = _arg(p, 4), _arg(p, 5)
    from ..objects import VarRef
    have = (I(pcch.cell.value) if isinstance(pcch, VarRef) else struct.unpack("<I", _read(_ptr(pcch), 4))[0]) \
        if not _null(pcch) else 0
    _write_out(pcch, "I", len(s) + 1)
    if _null(out):
        return S_FALSE
    if have < len(s) + 1:
        return E_POINTER
    _put_str(out, s)
    return S_OK


# ---------------------------------------------------------------- shell notifications
def _sh_add_to_recent_docs(p):
    """SHAddToRecentDocs(SHARD_PATHW = 3, path): the desktop's recent files (GTK's recently-used.xbel)."""
    if I(_arg(p, 0)) not in (2, 3) or _null(_arg(p, 1)):
        return 0
    from .files import host_path
    path = host_path(_str_arg(_arg(p, 1), I(_arg(p, 0)) == 3))
    if os.path.exists(path):
        from .guiobj import GUIS, _srv
        if GUIS:                                            # the GTK helper is running for this script's Gui
            _srv().call("recent", path=os.path.abspath(path))
    return 0


def _create_symbolic_link(p):
    from .files import host_path
    link, target = host_path(_str_arg(_arg(p, 0))), host_path(_str_arg(_arg(p, 1)))
    try:
        os.symlink(target, link, target_is_directory=bool(I(_arg(p, 2)) & 1))
    except OSError:
        return _fail(5)                                     # ERROR_ACCESS_DENIED
    return 1


# ---------------------------------------------------------------- dialog control IDs (a control's Hwnd is its ID)
def _get_dlg_item(p):
    from .guiobj import CTRLS, gui_for_window
    g, cid = gui_for_window(_ptr(_arg(p, 0))), I(_arg(p, 1)) & 0xFFFF
    c = CTRLS.get(cid)
    if g is None or c is None or c.gui is not g:
        return _fail(1421)                                  # ERROR_CONTROL_ID_NOT_FOUND
    return c.cid


def _get_dlg_ctrl_id(p):
    from .guiobj import CTRLS
    c = CTRLS.get(_ptr(_arg(p, 0)))
    return c.cid if c is not None else _fail(1400)          # ERROR_INVALID_WINDOW_HANDLE


EMU.update({
    "commandlinetoargvw": _command_line_to_argv, "commandlinetoargv": _command_line_to_argv,
    "findexecutable": _find_executable, "assocquerystring": _assoc_query_string,
    "shaddtorecentdocs": _sh_add_to_recent_docs,
    "shchangenotify": lambda p: 0,                          # desktop databases watch their own files
    "createsymboliclink": _create_symbolic_link,
    "getdlgitem": _get_dlg_item, "getdlgctrlid": _get_dlg_ctrl_id,
    "setwindowthemeattribute": lambda p: S_OK,              # non-client theming: GTK draws the frame
    "loadiconwithscaledown": lambda p: (_write_out(_arg(p, 4), "Q", 0), 0x80004001)[1],
})


def pe_string(path, key):
    """A StringFileInfo value (FileDescription, FileVersion, ...) of a PE file, or ""."""
    raw = _pe_version_resource(path)
    if not raw:
        return ""
    k = key.encode("utf-16-le") + b"\0\0"
    i = raw.find(k)
    if i < 6:
        return ""
    vlen = struct.unpack_from("<H", raw, i - 4)[0]
    v = _align4(i + len(k))
    return raw[v:v + 2 * vlen].decode("utf-16-le", "replace").split("\0")[0]
