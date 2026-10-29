"""COM automation objects, emulated (the Wine approach): ComObject("ProgID") returns a Python implementation of the
common Windows automation classes scripts rely on, with COM's dispatch rules (case-insensitive member names,
properties with parameters, default members, enumeration).

Emulated: WinHttp.WinHttpRequest.5.1, MSXML2.XMLHTTP / ServerXMLHTTP, Scripting.Dictionary, WScript.Shell
(+ WshExec, WshShortcut), Scripting.FileSystemObject (+ File, Folder, TextStream), ADODB.Stream, SAPI.SpVoice,
Shell.Application (+ Folder, FolderItem) and WMI through ComObjGet("winmgmts:") (Win32_Process,
Win32_OperatingSystem, Win32_ComputerSystem, Win32_Processor, Win32_LogicalDisk, Win32_BIOS,
Win32_NetworkAdapterConfiguration).  ComValue, ComObjArray, ComObjType, ComObjValue, ComObjFlags and ComObjConnect
work with them.  ComCall, ComObjQuery, ComObjFromPtr and ComObjActive need real COM vtables or the running-object
table and stay Windows-only.
"""
from __future__ import annotations

import datetime as dt
import fnmatch
import os
import re
import shutil
import subprocess
import threading
import time

from .. import objects as O
from ..objects import AhkArray, AhkObject, CLASSES, throw
from ..values import UNSET
from . import export

VT_EMPTY, VT_I4, VT_BSTR, VT_DISPATCH, VT_BOOL, VT_VARIANT, VT_UI1, VT_ARRAY = 0, 3, 8, 9, 11, 12, 17, 0x2000


def rt():
    return O.RT


def S(v):
    return O.RT.to_str(v)


def com_error(code, msg, member=""):
    """COM failures surface as OSError with AutoHotkey's "(0x80...) message" text."""
    throw("OSError", f"(0x{code & 0xFFFFFFFF:08X}) {msg}", member)


# ---------------------------------------------------------------- dispatch plumbing
class ComDispatch(AhkObject):
    """An AutoHotkey ComObject wrapping a Python implementation."""
    __slots__ = ("impl", "flags", "sink")

    def __init__(self, impl):
        super().__init__(CLASSES["ComObject"].prototype)
        self.impl = impl
        self.flags = 0
        self.sink = None
        impl.owner = self


class Impl:
    """Base for emulated classes.  Members: m_<name>(*args) methods, p_<name>(*params) property getters,
    s_<name>(value, *params) setters, all looked up case-insensitively."""
    progid = ""
    iface = "IDispatch"
    default = None          # default member name (obj[x], obj(x))
    owner = None

    def _find(self, prefix, name):
        attr = prefix + name.lower()
        return getattr(self, attr, None)

    def get(self, name, params):
        f = self._find("p_", name)
        if f is not None:
            return f(*params)
        m = self._find("m_", name)
        if m is not None:
            return m(*params)
        com_error(0x80020006, "Unknown name.", name)

    def set(self, name, params, value):
        f = self._find("s_", name)
        if f is None:
            com_error(0x80020006, "Unknown name.", name)
        f(value, *params)
        return value

    def call(self, name, args):
        m = self._find("m_", name)
        if m is not None:
            return m(*args)
        f = self._find("p_", name)
        if f is not None:
            return f(*args)
        com_error(0x80020006, "Unknown name.", name)

    def enum(self):
        com_error(0x80020003, "Member not found.", "_NewEnum")

    def fire(self, event, *args):
        """Raise an event to a ComObjConnect sink (object with methods, or function-name prefix)."""
        owner = self.owner
        if owner is None or owner.sink is None:
            return
        sink, r = owner.sink, rt()
        if isinstance(sink, str):
            fn = r.globals.get((sink + event).lower())
            fn = fn.value if fn is not None else None
            if fn is not None:
                r.post(lambda: r.call(fn, [*args, owner]))
        else:
            try:
                has = r.call_method(sink, "HasMethod", [event])
            except Exception:
                has = 0
            if has:
                r.post(lambda: r.call_method(sink, event, [*args, owner]))


def wrap(v):
    """Python values -> AutoHotkey values (Impl -> ComObject, lists -> SAFEARRAY)."""
    if isinstance(v, Impl):
        return v.owner if v.owner is not None else ComDispatch(v)
    if isinstance(v, bool):
        return -1 if v else 0          # VARIANT_BOOL
    if isinstance(v, (list, tuple)):
        return SafeArray(VT_VARIANT, [wrap(x) for x in v])
    if v is None:
        return ""
    return v


def _proto_setup():
    from ..classes import method, prop
    cv = CLASSES["ComValue"]
    co = CLASSES["ComObject"]
    ca = CLASSES["ComObjArray"]
    # AutoHotkey v2: ComObject and ComObjArray extend ComValue, whose base is Any
    for c in (co, ca):
        c.prototype.base = cv.prototype
        c.base = cv
    p = co.prototype
    if p.own("__Call") is not None:
        return
    method(p, "__Get", lambda this, name, params: wrap(this.impl.get(S(name), list(params.items))))
    method(p, "__Set", lambda this, name, params, value: this.impl.set(S(name), list(params.items), value))
    method(p, "__Call", lambda this, name, args: wrap(this.impl.call(S(name), list(args.items))))
    prop(p, "__Item", get=lambda this, *k: wrap(this.impl.get(this.impl.default or "Item", list(k))),
         set=lambda this, v, *k: this.impl.set(this.impl.default or "Item", list(k), v))
    method(p, "__Enum", lambda this, n=1: _enumerator(this.impl.enum(), n))
    method(p, "Call", lambda this, *a: wrap(this.impl.call(this.impl.default or "Item", list(a))))
    prop(p, "Ptr", get=lambda this: id(this))
    vp = cv.prototype
    prop(vp, "Value", get=lambda this: getattr(this, "_value", ""),
         set=lambda this, v: (setattr(this, "_value", v), v)[1]) if vp.own("Value") is None else None
    ap = ca.prototype
    if ap.own("MaxIndex") is None:
        method(ap, "MaxIndex", lambda this, dim=1: len(this.items) - 1)
        method(ap, "MinIndex", lambda this, dim=1: 0)
        method(ap, "Clone", lambda this: SafeArray(this.vt, list(this.items)))
        prop(ap, "__Item", get=lambda this, i: this.items[_index(this, i)],
             set=lambda this, v, i: this.items.__setitem__(_index(this, i), v))
        method(ap, "__Enum", lambda this, n=1: _enumerator(iter(this.items), n))


def _index(arr, i):
    i = rt().to_int(i)
    if not 0 <= i < len(arr.items):
        com_error(0x8002000B, "Invalid index.")
    return i


def _enumerator(it, n):
    from .core import Enumerator
    it = iter(it)

    def gen():
        for v in it:
            v = wrap(v)
            yield (v,) if n <= 1 else (v, "")
    return Enumerator(gen(), n)


class SafeArray(AhkObject):
    """ComObjArray: a SAFEARRAY (one dimension), 0-based."""
    __slots__ = ("vt", "items")

    def __init__(self, vt, items):
        super().__init__(CLASSES["ComObjArray"].prototype)
        self.vt = vt
        self.items = list(items)


class ComValueObj(AhkObject):
    __slots__ = ("vt", "val", "flags", "_value")

    def __init__(self, vt, val, flags=0):
        super().__init__(CLASSES["ComValue"].prototype)
        self.vt, self.val, self.flags = vt, val, flags
        self._value = val


def _bytes_of(v):
    from .buffer import BufferObj
    if isinstance(v, SafeArray):
        return bytes(int(x) & 255 for x in v.items)
    if isinstance(v, BufferObj):
        return bytes(v.data)
    if isinstance(v, bytes):
        return v
    return S(v).encode("utf-8")


# ---------------------------------------------------------------- HTTP: WinHttpRequest and XMLHTTP
class WinHttpRequest(Impl):
    progid = "WinHttp.WinHttpRequest.5.1"
    iface = "IWinHttpRequest"

    def __init__(self, xml=False):
        self.xml = xml
        self.method, self.url, self.async_ = "GET", "", False
        self.headers = {}
        self.timeout = 30.0
        self.resp = None          # (status, reason, headers, body)
        self.ready = 0
        self.done = threading.Event()
        self.options = {6: True}  # WinHttpRequestOption_EnableRedirects
        self.handler = None       # XMLHTTP onreadystatechange
        self.error = None

    def m_open(self, method, url, async_=0):
        self.method, self.url = S(method).upper(), S(url)
        self.async_ = bool(rt().to_int(async_)) if async_ not in (UNSET, "") else False
        self.headers, self.resp, self.error = {}, None, None
        self.done.clear()
        self.ready = 1
        return ""

    def m_setrequestheader(self, name, value):
        self.headers[S(name)] = S(value)
        return ""

    def m_settimeouts(self, resolve=0, connect=60000, send=30000, receive=30000):
        vals = [rt().to_int(v) for v in (connect, send, receive) if v not in (UNSET, "")]
        self.timeout = max(vals) / 1000 if vals and max(vals) > 0 else None
        return ""

    def p_option(self, n):
        return self.options.get(rt().to_int(n), 0)

    def s_option(self, value, n):
        self.options[rt().to_int(n)] = value

    def m_setproxy(self, *a):
        return ""

    def m_setcredentials(self, user, password, flags=0):
        import base64
        self.headers["Authorization"] = "Basic " + base64.b64encode(f"{S(user)}:{S(password)}".encode()).decode()
        return ""

    def _perform(self, body):
        import ssl
        import urllib.error
        import urllib.request
        data = None if body in (UNSET, "") and self.method in ("GET", "HEAD") else _bytes_of(body if body is not UNSET else "")
        req = urllib.request.Request(self.url, data=data, method=self.method)
        req.add_header("User-Agent", "Mozilla/4.0 (compatible; Win32; WinHttp.WinHttpRequest.5)")
        for k, v in self.headers.items():
            req.add_header(k, v)
        ctx = None
        if self.options.get(4):      # WinHttpRequestOption_SslErrorIgnoreFlags
            ctx = ssl._create_unverified_context()
        handlers = [] if self.options.get(6, True) else [_NoRedirect()]
        opener = urllib.request.build_opener(*handlers, urllib.request.HTTPSHandler(context=ctx))
        try:
            with opener.open(req, timeout=self.timeout) as r:
                self.resp = (r.status, r.reason, dict(r.headers.items()), r.read())
        except urllib.error.HTTPError as e:
            self.resp = (e.code, e.reason, dict(e.headers.items()) if e.headers else {}, e.read() or b"")
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            if "timed out" in str(reason):
                self.error = (0x80072EE2, "The operation timed out")
            elif "Name or service not known" in str(reason) or "nodename" in str(reason) or \
                    "Temporary failure in name resolution" in str(reason):
                self.error = (0x80072EE7, "The server name or address could not be resolved")
            else:
                self.error = (0x80072EFD, f"A connection with the server could not be established ({reason})")
        self.ready = 4
        self.done.set()
        if self.resp is not None:
            self.fire("OnResponseStarted", self.resp[0])
            self.fire("OnResponseFinished")
        else:
            self.fire("OnError", self.error[0], self.error[1])
        if self.handler is not None:
            h = self.handler
            rt().post(lambda: rt().call(h, []))

    def m_send(self, body=UNSET):
        if not self.url:
            com_error(0x80072EF1, "The operation has been canceled")
        if self.async_:
            threading.Thread(target=self._perform, args=(body,), daemon=True).start()
            return ""
        self._perform(body)
        if self.error and not self.xml:
            com_error(*self.error)
        return ""

    def m_waitforresponse(self, timeout=-1):
        t = rt().to_num(timeout) if timeout not in (UNSET, "") else -1
        end = None if t < 0 else time.monotonic() + t
        while not self.done.is_set():
            if end is not None and time.monotonic() >= end:
                return 0
            rt().sleep(10)
        if self.error and not self.xml:
            com_error(*self.error)
        return -1

    def m_abort(self):
        self.done.set()
        return ""

    def _need(self):
        if self.resp is None:
            if self.error:
                com_error(*self.error)
            com_error(0x80072F0F if not self.xml else 0x8000000A,
                      "The data necessary to complete this operation is not yet available.")
        return self.resp

    def p_status(self):
        return self._need()[0]

    def p_statustext(self):
        return self._need()[1]

    def p_responsetext(self):
        status, reason, headers, body = self._need()
        ct = next((v for k, v in headers.items() if k.lower() == "content-type"), "")
        m = re.search(r"charset=([\w-]+)", ct, re.I)
        enc = m.group(1) if m else "utf-8"
        if body.startswith(b"\xef\xbb\xbf"):
            body, enc = body[3:], "utf-8"
        try:
            return body.decode(enc, "replace")
        except LookupError:
            return body.decode("utf-8", "replace")

    def p_responsebody(self):
        return SafeArray(VT_UI1, list(self._need()[3]))

    def p_responsestream(self):
        s = AdodbStream()
        s.data = bytearray(self._need()[3])
        s.type_ = 1
        s.opened = True
        return s

    def m_getresponseheader(self, name):
        want = S(name).lower()
        for k, v in self._need()[2].items():
            if k.lower() == want:
                return v
        com_error(0x80072F76, "The requested header could not be located")

    def m_getallresponseheaders(self):
        return "".join(f"{k}: {v}\r\n" for k, v in self._need()[2].items())

    # XMLHTTP spellings
    def p_readystate(self):
        return self.ready

    def p_onreadystatechange(self):
        return self.handler or ""

    def s_onreadystatechange(self, value):
        self.handler = value or None

    def p_responsexml(self):
        return ""


class _NoRedirect(__import__("urllib.request").request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


# ---------------------------------------------------------------- Scripting.Dictionary
class Dictionary(Impl):
    progid = "Scripting.Dictionary"
    iface = "IDictionary"
    default = "Item"

    def __init__(self):
        self.d = {}
        self.mode = 0          # CompareMode: 0 binary, 1 text

    def _k(self, key):
        if isinstance(key, str) and self.mode == 1:
            return ("s", key.lower())
        if isinstance(key, AhkObject):
            return ("o", id(key))
        if isinstance(key, float) and key.is_integer():
            key = int(key)
        return (type(key).__name__ if not isinstance(key, (int, float)) else "n", key)

    def m_add(self, key, item):
        k = self._k(key)
        if k in self.d:
            com_error(0x800A01C9, "This key is already associated with an element of this collection")
        self.d[k] = [key, item]
        return ""

    def p_item(self, key):
        k = self._k(key)
        if k not in self.d:
            self.d[k] = [key, ""]          # reading a missing key adds it, as in VBScript
        return self.d[k][1]

    def s_item(self, value, key):
        k = self._k(key)
        if k in self.d:
            self.d[k][1] = value
        else:
            self.d[k] = [key, value]

    def s_key(self, newkey, key):
        k = self._k(key)
        if k not in self.d:
            com_error(0x800A802B, "Element not found")
        entry = self.d.pop(k)
        entry[0] = newkey
        self.d[self._k(newkey)] = entry

    def m_exists(self, key):
        return -1 if self._k(key) in self.d else 0

    def m_remove(self, key):
        k = self._k(key)
        if k not in self.d:
            com_error(0x800A802B, "Element not found")
        del self.d[k]
        return ""

    def m_removeall(self):
        self.d.clear()
        return ""

    def p_count(self):
        return len(self.d)

    def m_keys(self):
        return SafeArray(VT_VARIANT, [e[0] for e in self.d.values()])

    def m_items(self):
        return SafeArray(VT_VARIANT, [e[1] for e in self.d.values()])

    def p_comparemode(self):
        return self.mode

    def s_comparemode(self, v):
        if self.d:
            com_error(0x800A0005, "Invalid procedure call or argument")
        self.mode = rt().to_int(v)

    def enum(self):
        return [e[0] for e in self.d.values()]


# ---------------------------------------------------------------- WScript.Shell
class WshShell(Impl):
    progid = "WScript.Shell"
    iface = "IWshShell3"

    def m_run(self, command, style=1, wait=0):
        from .process import translate_command
        argv = translate_command(S(command))
        p = subprocess.Popen(argv, start_new_session=True,
                             stdout=subprocess.DEVNULL if rt().to_int(style) == 0 else None)
        if wait not in (UNSET, "") and rt().to_int(wait):
            while p.poll() is None:
                rt().sleep(20)
            return p.returncode
        return 0

    def m_exec(self, command):
        return WshExec(S(command))

    def m_popup(self, text, secs=0, title="Windows Script Host", type_=0):
        from .gui import MsgBox
        opts = rt().to_int(type_) if type_ not in (UNSET, "") else 0
        t = rt().to_num(secs) if secs not in (UNSET, "") else 0
        o = str(opts) + (f" T{t}" if t and t > 0 else "")
        res = MsgBox(S(text), S(title) if title is not UNSET else "Windows Script Host", o)
        return {"OK": 1, "Cancel": 2, "Abort": 3, "Retry": 4, "Ignore": 5, "Yes": 6, "No": 7, "TryAgain": 10,
                "Continue": 11, "Timeout": -1}.get(S(res), 1)

    def m_expandenvironmentstrings(self, s):
        def rep(m):
            name = m.group(1)
            v = _WIN_ENV.get(name.upper())
            v = v() if callable(v) else v
            return v if v is not None else os.environ.get(name, os.environ.get(name.upper(), m.group(0)))
        return re.sub(r"%([^%]+)%", rep, S(s))

    def m_environment(self, kind="SYSTEM"):
        return WshEnvironment()

    def p_environment(self, kind="SYSTEM"):
        return WshEnvironment()

    def m_regread(self, name):
        from .registry import RegRead
        key, _, value = S(name).rpartition("\\")
        return RegRead(key, value)

    def m_regwrite(self, name, value, type_="REG_SZ"):
        from .registry import RegWrite
        key, _, vname = S(name).rpartition("\\")
        RegWrite(value, S(type_) if type_ is not UNSET else "REG_SZ", key, vname)
        return ""

    def m_regdelete(self, name):
        from .registry import RegDelete, RegDeleteKey
        s = S(name)
        if s.endswith("\\"):
            RegDeleteKey(s.rstrip("\\"))
        else:
            key, _, vname = s.rpartition("\\")
            RegDelete(key, vname)
        return ""

    def m_sendkeys(self, keys, wait=0):
        from .input_ import do_send
        do_send(_vb_keys(S(keys)))
        return ""

    def m_appactivate(self, title):
        from .window import WinActivate, find_window
        w = find_window(title, required=False)
        if w:
            WinActivate(f"ahk_id {w}")
            return -1
        return 0

    def m_createshortcut(self, path):
        return WshShortcut(S(path))

    def p_specialfolders(self, name=UNSET):
        if name is UNSET:
            return SpecialFolders()
        return SpecialFolders().get("Item", [name])

    def p_currentdirectory(self):
        return os.getcwd()

    def s_currentdirectory(self, v):
        from .files import host_path
        os.chdir(host_path(S(v)))

    def m_logevent(self, *a):
        return -1


_WIN_ENV = {"USERPROFILE": lambda: os.path.expanduser("~"), "HOMEPATH": lambda: os.path.expanduser("~"),
            "USERNAME": lambda: os.environ.get("USER", ""), "COMPUTERNAME": lambda: os.uname().nodename,
            "TEMP": lambda: _sf("temp"), "TMP": lambda: _sf("temp"), "APPDATA": lambda: _sf("appdata"),
            "LOCALAPPDATA": lambda: _sf("localappdata"), "SYSTEMROOT": "C:\\Windows", "WINDIR": "C:\\Windows",
            "PROGRAMFILES": "C:\\Program Files", "SYSTEMDRIVE": "C:", "OS": "Windows_NT",
            "PROCESSOR_ARCHITECTURE": "AMD64", "NUMBER_OF_PROCESSORS": lambda: str(os.cpu_count() or 1)}


def _sf(name):
    from .files import shell_folder
    try:
        return shell_folder(name)
    except Exception:
        return ""


def _vb_keys(s):
    """VBScript SendKeys syntax -> AutoHotkey Send syntax (% Alt, ^ Ctrl, + Shift, ~ Enter, {KEY n})."""
    out, i = [], 0
    names = {"BACKSPACE": "Backspace", "BS": "Backspace", "BKSP": "Backspace", "BREAK": "CtrlBreak",
             "CAPSLOCK": "CapsLock", "DELETE": "Delete", "DEL": "Delete", "DOWN": "Down", "END": "End",
             "ENTER": "Enter", "ESC": "Escape", "HELP": "Help", "HOME": "Home", "INSERT": "Insert", "INS": "Insert",
             "LEFT": "Left", "NUMLOCK": "NumLock", "PGDN": "PgDn", "PGUP": "PgUp", "PRTSC": "PrintScreen",
             "RIGHT": "Right", "SCROLLLOCK": "ScrollLock", "TAB": "Tab", "UP": "Up", "ADD": "NumpadAdd",
             "SUBTRACT": "NumpadSub", "MULTIPLY": "NumpadMult", "DIVIDE": "NumpadDiv"}
    while i < len(s):
        ch = s[i]
        if ch == "{":
            j = s.find("}", i + 2) if s[i + 1:i + 2] == "}" else s.find("}", i)
            body = s[i + 1:j]
            parts = body.split()
            key = parts[0] if parts else ""
            n = parts[1] if len(parts) > 1 else ""
            k = names.get(key.upper(), key if len(key) > 1 else key)
            out.append("{" + k + (" " + n if n else "") + "}")
            i = j + 1
        elif ch in "%^+":
            out.append({"%": "!", "^": "^", "+": "+"}[ch])
            i += 1
        elif ch == "~":
            out.append("{Enter}")
            i += 1
        elif ch in "!#":
            out.append("{" + ch + "}")
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


class WshEnvironment(Impl):
    default = "Item"

    def p_item(self, name):
        return os.environ.get(S(name), "")

    def s_item(self, value, name):
        os.environ[S(name)] = S(value)

    def m_remove(self, name):
        os.environ.pop(S(name), None)
        return ""

    def p_count(self):
        return len(os.environ)

    def enum(self):
        return [f"{k}={v}" for k, v in os.environ.items()]


class SpecialFolders(Impl):
    default = "Item"
    MAP = {"desktop": "desktop", "mydocuments": "documents", "favorites": "favorites", "fonts": "fonts",
           "nethood": "nethood", "printhood": "printhood", "programs": "programs", "recent": "recent",
           "sendto": "sendto", "startmenu": "startmenu", "startup": "startup", "templates": "templates",
           "appdata": "appdata", "allusersdesktop": "desktop", "allusersstartmenu": "startmenu",
           "allusersprograms": "programs", "allusersstartup": "startup"}

    def p_item(self, name):
        key = S(name).lower()
        return _sf(self.MAP.get(key, key)) if key in self.MAP else ""

    def p_count(self):
        return len(self.MAP)

    def enum(self):
        return [self.p_item(k) for k in self.MAP]


class _Pipe(Impl):
    def __init__(self, stream, write=False):
        self.stream = stream
        self.buf = b""
        self.eof = False

    def _fill(self):
        if self.eof or self.stream is None:
            return False
        chunk = self.stream.read1(65536) if hasattr(self.stream, "read1") else self.stream.read(65536)
        if not chunk:
            self.eof = True
            return False
        self.buf += chunk
        return True

    def m_readall(self):
        while self._fill():
            pass
        out, self.buf = self.buf, b""
        return _decode(out)

    def m_readline(self):
        while b"\n" not in self.buf and self._fill():
            pass
        line, sep, rest = self.buf.partition(b"\n")
        self.buf = rest
        return _decode(line).rstrip("\r")

    def m_read(self, n):
        n = rt().to_int(n)
        while len(self.buf) < n and self._fill():
            pass
        out, self.buf = self.buf[:n], self.buf[n:]
        return _decode(out)

    def p_atendofstream(self):
        if self.buf:
            return 0
        return 0 if self._fill() else -1

    def m_write(self, s):
        self.stream.write(S(s).encode())
        self.stream.flush()
        return ""

    def m_writeline(self, s=""):
        return self.m_write(S(s) + "\n")

    def m_close(self):
        if self.stream is not None:
            self.stream.close()
        return ""


def _decode(b):
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("latin-1")


class WshExec(Impl):
    iface = "IWshExec"

    def __init__(self, command):
        from .process import translate_command
        self.p = subprocess.Popen(translate_command(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, start_new_session=True)
        self.out, self.err, self.inp = _Pipe(self.p.stdout), _Pipe(self.p.stderr), _Pipe(self.p.stdin)

    def p_stdout(self):
        return self.out

    def p_stderr(self):
        return self.err

    def p_stdin(self):
        return self.inp

    def p_status(self):
        return 0 if self.p.poll() is None else 1

    def p_exitcode(self):
        return self.p.poll() or 0

    def p_processid(self):
        return self.p.pid

    def m_terminate(self):
        self.p.terminate()
        return ""


class WshShortcut(Impl):
    iface = "IWshShortcut"

    def __init__(self, path):
        self.path = path
        self.props = {"targetpath": "", "arguments": "", "workingdirectory": "", "description": "",
                      "iconlocation": "", "hotkey": "", "windowstyle": 1}

    def get(self, name, params):
        n = name.lower()
        if n in self.props:
            return self.props[n]
        if n == "fullname":
            return self.path
        return super().get(name, params)

    def set(self, name, params, value):
        n = name.lower()
        if n in self.props:
            self.props[n] = value
            return value
        return super().set(name, params, value)

    def m_save(self):
        from .files import FileCreateShortcut
        icon = S(self.props["iconlocation"]).split(",")[0]
        FileCreateShortcut(S(self.props["targetpath"]), self.path, S(self.props["workingdirectory"]),
                           S(self.props["arguments"]), S(self.props["description"]), icon)
        return ""


# ---------------------------------------------------------------- Scripting.FileSystemObject
def _hp(p):
    from .files import host_path
    return host_path(S(p))


class FileSystemObject(Impl):
    progid = "Scripting.FileSystemObject"
    iface = "IFileSystem3"

    def m_fileexists(self, p):
        return -1 if os.path.isfile(_hp(p)) else 0

    def m_folderexists(self, p):
        return -1 if os.path.isdir(_hp(p)) else 0

    def m_driveexists(self, p):
        from .files import DriveGetList
        return -1 if S(p)[:1].upper() in DriveGetList() else 0

    def m_getfilename(self, p):
        return re.split(r"[\\/]", S(p).rstrip("\\/"))[-1]

    def m_getbasename(self, p):
        name = self.m_getfilename(p)
        return name.rsplit(".", 1)[0] if "." in name else name

    def m_getextensionname(self, p):
        name = self.m_getfilename(p)
        return name.rsplit(".", 1)[1] if "." in name else ""

    def m_getparentfoldername(self, p):
        s = S(p).rstrip("\\/")
        i = max(s.rfind("\\"), s.rfind("/"))
        return s[:i] if i > 0 else ""

    def m_buildpath(self, a, b):
        a, b = S(a), S(b)
        sep = "/" if "/" in a and "\\" not in a else "\\"
        return a.rstrip("\\/") + sep + b.lstrip("\\/") if a else b

    def m_getabsolutepathname(self, p):
        return os.path.abspath(_hp(p))

    def m_gettempname(self):
        import random
        return "rad%05X.tmp" % random.randrange(16 ** 5)

    def m_getspecialfolder(self, n):
        return Folder(_sf({0: "windows", 1: "system", 2: "temp"}.get(rt().to_int(n), "temp")) or "/tmp")

    def m_createfolder(self, p):
        path = _hp(p)
        if os.path.exists(path):
            com_error(0x800A003A, "File already exists")
        os.makedirs(path)
        return Folder(path)

    def m_deletefile(self, p, force=0):
        import glob
        hits = glob.glob(_hp(p))
        if not hits:
            com_error(0x800A0035, "File not found")
        for h in hits:
            os.remove(h)
        return ""

    def m_deletefolder(self, p, force=0):
        import glob
        hits = glob.glob(_hp(p))
        if not hits:
            com_error(0x800A004C, "Path not found")
        for h in hits:
            shutil.rmtree(h)
        return ""

    def m_copyfile(self, src, dst, overwrite=-1):
        import glob
        d = _hp(dst)
        for h in glob.glob(_hp(src)) or [None]:
            if h is None:
                com_error(0x800A0035, "File not found")
            target = os.path.join(d, os.path.basename(h)) if os.path.isdir(d) or S(dst).endswith(("\\", "/")) else d
            if os.path.exists(target) and not rt().to_int(overwrite):
                com_error(0x800A003A, "File already exists")
            shutil.copy2(h, target)
        return ""

    def m_movefile(self, src, dst):
        import glob
        d = _hp(dst)
        for h in glob.glob(_hp(src)) or [None]:
            if h is None:
                com_error(0x800A0035, "File not found")
            shutil.move(h, os.path.join(d, os.path.basename(h)) if os.path.isdir(d) else d)
        return ""

    def m_copyfolder(self, src, dst, overwrite=-1):
        shutil.copytree(_hp(src), _hp(dst), dirs_exist_ok=bool(rt().to_int(overwrite)))
        return ""

    def m_movefolder(self, src, dst):
        shutil.move(_hp(src), _hp(dst))
        return ""

    def m_getfile(self, p):
        path = _hp(p)
        if not os.path.isfile(path):
            com_error(0x800A0035, "File not found")
        return File(path)

    def m_getfolder(self, p):
        path = _hp(p)
        if not os.path.isdir(path):
            com_error(0x800A004C, "Path not found")
        return Folder(path)

    def m_opentextfile(self, p, mode=1, create=0, fmt=0):
        path = _hp(p)
        mode = rt().to_int(mode) if mode not in (UNSET, "") else 1
        if not os.path.exists(path) and (mode == 1 or not rt().to_int(create or 0)):
            com_error(0x800A0035, "File not found")
        return TextStream(path, {1: "r", 2: "w", 8: "a"}.get(mode, "r"), rt().to_int(fmt or 0))

    def m_createtextfile(self, p, overwrite=-1, unicode_=0):
        path = _hp(p)
        if os.path.exists(path) and not rt().to_int(overwrite):
            com_error(0x800A003A, "File already exists")
        return TextStream(path, "w", -1 if rt().to_int(unicode_ or 0) else 0)


def _filetime(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%Y%m%d%H%M%S")


class File(Impl):
    iface = "IFile"

    def __init__(self, path):
        self.path = path

    def p_name(self):
        return os.path.basename(self.path)

    def p_path(self):
        return self.path

    def p_size(self):
        return os.path.getsize(self.path)

    def p_datelastmodified(self):
        return _filetime(os.path.getmtime(self.path))

    def p_datecreated(self):
        return _filetime(os.stat(self.path).st_ctime)

    def p_datelastaccessed(self):
        return _filetime(os.path.getatime(self.path))

    def p_parentfolder(self):
        return Folder(os.path.dirname(self.path))

    def p_type(self):
        ext = os.path.splitext(self.path)[1]
        return (ext[1:].upper() + " File") if ext else "File"

    def p_attributes(self):
        return 32 | (1 if not os.access(self.path, os.W_OK) else 0)

    def m_delete(self, force=0):
        os.remove(self.path)
        return ""

    def m_copy(self, dst, overwrite=-1):
        shutil.copy2(self.path, _hp(dst))
        return ""

    def m_move(self, dst):
        shutil.move(self.path, _hp(dst))
        return ""

    def m_openastextstream(self, mode=1, fmt=0):
        return TextStream(self.path, {1: "r", 2: "w", 8: "a"}.get(rt().to_int(mode or 1), "r"), rt().to_int(fmt or 0))


class Folder(File):
    iface = "IFolder"

    def p_size(self):
        total = 0
        for root, _, files in os.walk(self.path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total

    def p_files(self):
        return Collection([File(os.path.join(self.path, n)) for n in sorted(os.listdir(self.path))
                           if os.path.isfile(os.path.join(self.path, n))])

    def p_subfolders(self):
        return Collection([Folder(os.path.join(self.path, n)) for n in sorted(os.listdir(self.path))
                           if os.path.isdir(os.path.join(self.path, n))])

    def p_isrootfolder(self):
        return -1 if self.path == "/" else 0

    def p_type(self):
        return "File folder"

    def m_delete(self, force=0):
        shutil.rmtree(self.path)
        return ""

    def m_createtextfile(self, name, overwrite=-1, unicode_=0):
        return TextStream(os.path.join(self.path, S(name)), "w", -1 if rt().to_int(unicode_ or 0) else 0)


class Collection(Impl):
    default = "Item"

    def __init__(self, items):
        self.items = items

    def p_count(self):
        return len(self.items)

    def p_item(self, key):
        if isinstance(key, int):
            return self.items[key] if 0 <= key < len(self.items) else com_error(0x8002000B, "Invalid index.")
        for it in self.items:
            if getattr(it, "path", None) and os.path.basename(it.path) == S(key):
                return it
        com_error(0x800A0035, "File not found")

    def enum(self):
        return list(self.items)


class TextStream(Impl):
    iface = "ITextStream"

    def __init__(self, path, mode, fmt):
        enc = "utf-16" if fmt == -1 else "utf-8"
        self.fh = open(path, mode, encoding=enc, newline="")
        self.line = 1
        self.col = 1

    def m_readall(self):
        return self.fh.read()

    def m_readline(self):
        line = self.fh.readline()
        self.line += 1
        return line.rstrip("\r\n")

    def m_read(self, n):
        return self.fh.read(rt().to_int(n))

    def m_skipline(self):
        self.fh.readline()
        return ""

    def p_atendofstream(self):
        pos = self.fh.tell()
        ch = self.fh.read(1)
        self.fh.seek(pos)
        return 0 if ch else -1

    def p_atendofline(self):
        pos = self.fh.tell()
        ch = self.fh.read(1)
        self.fh.seek(pos)
        return -1 if ch in ("", "\n", "\r") else 0

    def p_line(self):
        return self.line

    def m_write(self, s):
        self.fh.write(S(s))
        return ""

    def m_writeline(self, s=""):
        self.fh.write(S(s) + "\r\n")
        return ""

    def m_writeblanklines(self, n):
        self.fh.write("\r\n" * rt().to_int(n))
        return ""

    def m_close(self):
        self.fh.close()
        return ""


# ---------------------------------------------------------------- ADODB.Stream
class AdodbStream(Impl):
    progid = "ADODB.Stream"
    iface = "_Stream"

    def __init__(self):
        self.data = bytearray()
        self.pos = 0
        self.type_ = 2           # adTypeText
        self.charset = "Unicode"
        self.opened = False

    def _codec(self):
        cs = self.charset.lower()
        return {"unicode": "utf-16-le", "utf-8": "utf-8", "ascii": "ascii", "us-ascii": "ascii",
                "iso-8859-1": "latin-1", "windows-1252": "cp1252", "_autodetect_all": "utf-8"}.get(cs, cs)

    def _bom(self):
        cs = self.charset.lower()
        return b"\xff\xfe" if cs == "unicode" else b"\xef\xbb\xbf" if cs == "utf-8" else b""

    def m_open(self, *a):
        self.opened, self.data, self.pos = True, bytearray(), 0
        return ""

    def m_close(self):
        self.opened = False
        return ""

    def p_type(self):
        return self.type_

    def s_type(self, v):
        self.type_ = rt().to_int(v)

    def p_charset(self):
        return self.charset

    def s_charset(self, v):
        self.charset = S(v)

    def p_position(self):
        return self.pos

    def s_position(self, v):
        self.pos = rt().to_int(v)

    def p_size(self):
        return len(self.data)

    def p_eos(self):
        return -1 if self.pos >= len(self.data) else 0

    def m_seteos(self):
        del self.data[self.pos:]
        return ""

    def _put(self, b):
        if self.pos == 0 and not self.data and self.type_ == 2:
            b = self._bom() + b         # ADODB writes a byte order mark for Unicode/UTF-8 text
        self.data[self.pos:self.pos + len(b)] = b
        self.pos += len(b)

    def m_writetext(self, s, opt=0):
        self._put((S(s) + ("\r\n" if rt().to_int(opt or 0) == 1 else "")).encode(self._codec()))
        return ""

    def m_write(self, buf):
        self._put(_bytes_of(buf))
        return ""

    def m_readtext(self, n=-1):
        raw = bytes(self.data[self.pos:])
        bom = self._bom()
        if self.pos == 0 and bom and raw.startswith(bom):
            raw = raw[len(bom):]
        text = raw.decode(self._codec(), "replace")
        n = rt().to_int(n) if n not in (UNSET, "") else -1
        if n >= 0:
            text = text[:n]
        self.pos = len(self.data) if n < 0 else self.pos + len(text.encode(self._codec()))
        return text

    def m_read(self, n=-1):
        n = rt().to_int(n) if n not in (UNSET, "") else -1
        chunk = self.data[self.pos:] if n < 0 else self.data[self.pos:self.pos + n]
        self.pos += len(chunk)
        return SafeArray(VT_UI1, list(chunk))

    def m_savetofile(self, path, opt=1):
        p = _hp(path)
        if os.path.exists(p) and rt().to_int(opt or 1) != 2:
            com_error(0x800A0BBC, "Write to file failed.")
        with open(p, "wb") as fh:
            fh.write(self.data)
        return ""

    def m_loadfromfile(self, path):
        with open(_hp(path), "rb") as fh:
            self.data = bytearray(fh.read())
        self.pos = 0
        return ""

    def m_copyto(self, dest, n=-1):
        n = rt().to_int(n) if n not in (UNSET, "") else -1
        chunk = self.data[self.pos:] if n < 0 else self.data[self.pos:self.pos + n]
        dest.impl._put(bytes(chunk))
        self.pos += len(chunk)
        return ""

    def m_flush(self):
        return ""


# ---------------------------------------------------------------- SAPI.SpVoice
class SpVoice(Impl):
    progid = "SAPI.SpVoice"
    iface = "ISpeechVoice"

    def __init__(self):
        self.rate, self.volume, self.proc = 0, 100, None

    def _argv(self, text):
        if shutil.which("spd-say"):
            return ["spd-say", "-w", "-r", str(self.rate * 10), "-i", str(self.volume * 2 - 100), text]
        for tool in ("espeak-ng", "espeak"):
            if shutil.which(tool):
                return [tool, "-s", str(175 + self.rate * 15), "-a", str(self.volume * 2), text]
        com_error(0x80045077, "No speech synthesizer found (install speech-dispatcher or espeak-ng).")

    def m_speak(self, text, flags=0):
        f = rt().to_int(flags) if flags not in (UNSET, "") else 0
        if f & 2 and self.proc is not None:          # SVSFPurgeBeforeSpeak
            self.proc.terminate()
        self.proc = subprocess.Popen(self._argv(S(text)), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not f & 1:                                 # SVSFlagsAsync
            while self.proc.poll() is None:
                rt().sleep(20)
        return 1

    def m_waituntildone(self, ms=-1):
        t = rt().to_num(ms) if ms not in (UNSET, "") else -1
        end = None if t < 0 else time.monotonic() + t / 1000
        while self.proc is not None and self.proc.poll() is None:
            if end is not None and time.monotonic() >= end:
                return 0
            rt().sleep(20)
        return -1

    def p_rate(self):
        return self.rate

    def s_rate(self, v):
        self.rate = max(-10, min(10, rt().to_int(v)))

    def p_volume(self):
        return self.volume

    def s_volume(self, v):
        self.volume = max(0, min(100, rt().to_int(v)))

    def m_getvoices(self, *a):
        return Collection([])

    def m_pause(self):
        return ""

    def m_resume(self):
        return ""


# ---------------------------------------------------------------- Shell.Application
class ShellApplication(Impl):
    progid = "Shell.Application"
    iface = "IShellDispatch6"

    def m_shellexecute(self, file, args="", directory="", verb="", show=1):
        from .process import Run
        target = S(file) + ((" " + S(args)) if args not in (UNSET, "") and S(args) else "")
        Run(("*" + S(verb) + " " if verb not in (UNSET, "") and S(verb) else "") + target,
            S(directory) if directory is not UNSET else "")
        return ""

    def m_open(self, d):
        subprocess.Popen(["xdg-open", _hp(d)], start_new_session=True, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return ""

    m_explore = m_open

    def m_minimizeall(self):
        from .window import WinMinimizeAll
        return WinMinimizeAll()

    def m_undominimizeall(self):
        from .window import WinMinimizeAllUndo
        return WinMinimizeAllUndo()

    def m_namespace(self, d):
        path = _hp(d) if not isinstance(d, int) else _sf({0: "desktop", 5: "documents", 16: "desktop"}.get(d, "desktop"))
        return ShellFolder(path) if os.path.isdir(path) else ""

    def m_windows(self):
        return Collection([])

    def m_filerun(self):
        return ""


class ShellFolder(Impl):
    iface = "Folder3"

    def __init__(self, path):
        self.path = path

    def p_title(self):
        return os.path.basename(self.path.rstrip("/")) or self.path

    def m_items(self):
        return Collection([FolderItem(os.path.join(self.path, n)) for n in sorted(os.listdir(self.path))])

    def p_self(self):
        return FolderItem(self.path)

    def m_parsename(self, name):
        p = os.path.join(self.path, S(name))
        return FolderItem(p) if os.path.exists(p) else ""

    def m_copyhere(self, item, opts=0):
        src = item.impl.path if isinstance(item, ComDispatch) else _hp(item)
        (shutil.copytree if os.path.isdir(src) else shutil.copy2)(src, os.path.join(self.path, os.path.basename(src)))
        return ""

    def m_movehere(self, item, opts=0):
        src = item.impl.path if isinstance(item, ComDispatch) else _hp(item)
        shutil.move(src, os.path.join(self.path, os.path.basename(src)))
        return ""

    def m_newfolder(self, name, opts=0):
        os.makedirs(os.path.join(self.path, S(name)), exist_ok=True)
        return ""


class FolderItem(Impl):
    iface = "FolderItem2"

    def __init__(self, path):
        self.path = path

    def p_name(self):
        return os.path.basename(self.path)

    def p_path(self):
        return self.path

    def p_isfolder(self):
        return -1 if os.path.isdir(self.path) else 0

    def p_size(self):
        return os.path.getsize(self.path) if os.path.isfile(self.path) else 0

    def p_modifydate(self):
        return _filetime(os.path.getmtime(self.path))

    def p_getfolder(self):
        return ShellFolder(self.path) if os.path.isdir(self.path) else ""

    def m_invokeverb(self, verb=""):
        subprocess.Popen(["xdg-open", self.path], start_new_session=True, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return ""


# ---------------------------------------------------------------- the ActiveX web browser (IWebBrowser2)
class WebBrowser(Impl):
    iface = "IWebBrowser2"

    def __init__(self, ctrl):
        self.ctrl = ctrl
        self.doc = HtmlDocument(self)

    def _op(self, do, **kw):
        from .guiobj import _srv
        return _srv().call("web", ctrl=self.ctrl.cid, do=do, **kw)

    def m_navigate(self, url, *a):
        u = S(url)
        if u.lower().startswith("about:") and u.lower() != "about:blank":
            self._op("html", html=u[6:])
        else:
            self._op("navigate", url=u if re.match(r"^[a-z][\w+.-]*:", u) else "file://" + _hp(u))
        return ""

    m_navigate2 = m_navigate

    def m_goback(self):
        return self._op("back")

    def m_goforward(self):
        return self._op("forward")

    def m_refresh(self, *a):
        return self._op("refresh")

    def m_stop(self):
        return self._op("stop")

    def p_locationurl(self):
        return self._op("url")

    def p_locationname(self):
        return self._op("title")

    def p_busy(self):
        return -1 if self._op("busy") else 0

    def p_readystate(self):
        return 3 if self._op("busy") else 4      # READYSTATE_INTERACTIVE / COMPLETE

    def p_document(self):
        return self.doc

    def p_silent(self):
        return -1

    def s_silent(self, v):
        pass


class HtmlDocument(Impl):
    """document.write/open/close and parentWindow.execScript, the parts of IHTMLDocument scripts use to fill
    the browser control."""
    iface = "IHTMLDocument2"

    def __init__(self, browser):
        self.browser, self.buf = browser, None

    def m_open(self, *a):
        self.buf = []
        return self

    def m_write(self, *parts):
        if self.buf is None:
            self.buf = []
        self.buf.extend(S(p) for p in parts)
        self.browser._op("html", html="".join(self.buf))
        return ""

    m_writeln = m_write

    def m_close(self):
        if self.buf is not None:
            self.browser._op("html", html="".join(self.buf))
        self.buf = None
        return ""

    def p_parentwindow(self):
        return self

    def m_execscript(self, code, lang="JavaScript"):
        self.browser._op("script", code=S(code))
        return ""

    def p_title(self):
        return self.browser._op("title")

    def p_url(self):
        return self.browser._op("url")


# ---------------------------------------------------------------- WMI (ComObjGet("winmgmts:"))
class WmiServices(Impl):
    iface = "ISWbemServicesEx"

    def m_execquery(self, wql, *a):
        return Collection([WmiObject(cls, row) for cls, row in wmi_query(S(wql))])

    def m_instancesof(self, cls, *a):
        return self.m_execquery(f"SELECT * FROM {S(cls)}")

    def m_get(self, path=""):
        m = re.match(r"(\w+)(?:\.(\w+)=['\"]?([^'\"]*)['\"]?)?", S(path))
        if not m:
            com_error(0x8004100E, "Invalid namespace")
        cls = m.group(1)
        q = f"SELECT * FROM {cls}" + (f" WHERE {m.group(2)}='{m.group(3)}'" if m.group(2) else "")
        rows = wmi_query(q)
        if not rows:
            com_error(0x80041002, "Not found")
        return WmiObject(*rows[0])

    def m_execnotificationquery(self, *a):
        com_error(0x80041010, "Invalid class (WMI event queries are not emulated)")


class WmiObject(Impl):
    iface = "ISWbemObjectEx"

    def __init__(self, cls, row):
        self.cls, self.row = cls, row

    def get(self, name, params):
        n = name.lower()
        for k, v in self.row.items():
            if k.lower() == n:
                return v
        if n == "path_":
            return self
        return super().get(name, params)

    def p_relpath(self):
        return self.cls


def _like(value, pattern):
    rx = "^" + re.escape(pattern).replace("%", ".*").replace("_", ".") + "$"
    return re.match(rx, str(value), re.I | re.S) is not None


def _wql_where(row, cond):
    """Evaluate a WQL WHERE clause: comparisons, LIKE, IS [NOT] NULL, AND/OR/NOT and parentheses."""
    toks = re.findall(r"'(?:[^']|'')*'|\"[^\"]*\"|<>|!=|<=|>=|[()=<>]|[\w.\\:%-]+", cond)
    pos = [0]

    def peek():
        return toks[pos[0]].upper() if pos[0] < len(toks) else ""

    def take():
        pos[0] += 1
        return toks[pos[0] - 1]

    def value(t):
        if t[:1] in "'\"":
            return t[1:-1].replace("''", "'")
        try:
            return int(t)
        except ValueError:
            try:
                return float(t)
            except ValueError:
                return t

    def field(name):
        for k, v in row.items():
            if k.lower() == name.lower():
                return v
        return None

    def cmp_(a, op, b):
        if a is None:
            return False
        if isinstance(b, str) and not isinstance(a, str):
            a = str(a)
        if isinstance(a, str) and isinstance(b, str):
            a, b = a.lower(), b.lower()
        return {"=": a == b, "<>": a != b, "!=": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]

    def atom():
        if peek() == "(":
            take()
            r = expr()
            take()
            return r
        if peek() == "NOT":
            take()
            return not atom()
        name = take()
        op = take().upper()
        if op == "LIKE":
            return _like(field(name) or "", value(take()))
        if op == "IS":
            neg = peek() == "NOT"
            if neg:
                take()
            take()                                  # NULL
            return (field(name) is None) != neg
        return cmp_(field(name), op, value(take()))

    def term():
        r = atom()
        while peek() == "AND":
            take()
            r = atom() and r
        return r

    def expr():
        r = term()
        while peek() == "OR":
            take()
            r = term() or r
        return r
    return expr()


def wmi_query(wql):
    m = re.match(r"\s*SELECT\s+(.+?)\s+FROM\s+(\w+)(?:\s+WHERE\s+(.+))?\s*$", wql, re.I | re.S)
    if not m:
        com_error(0x80041017, "Invalid query")
    fields, cls, where = m.group(1), m.group(2), m.group(3)
    provider = WMI_CLASSES.get(cls.lower())
    if provider is None:
        com_error(0x80041010, "Invalid class")
    rows = provider()
    if where:
        rows = [r for r in rows if _wql_where(r, where)]
    if fields.strip() != "*":
        keep = [f.strip().lower() for f in fields.split(",")]
        rows = [{k: v for k, v in r.items() if k.lower() in keep} for r in rows]
    return [(cls, r) for r in rows]


def _read(path, default=""):
    try:
        with open(path, errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return default


def _wmi_processes():
    out = []
    boot = time.time() - float(_read("/proc/uptime", "0 0").split()[0])
    hz = os.sysconf("SC_CLK_TCK")
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        stat = _read(f"/proc/{pid}/stat")
        if not stat:
            continue
        comm = stat[stat.find("(") + 1:stat.rfind(")")]
        rest = stat[stat.rfind(")") + 2:].split()
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            exe = ""
        cmd = _read(f"/proc/{pid}/cmdline").replace("\0", " ").strip()
        try:
            rss = int(rest[21]) * os.sysconf("SC_PAGE_SIZE")
            start = dt.datetime.fromtimestamp(boot + int(rest[19]) / hz).strftime("%Y%m%d%H%M%S.000000+000")
        except (IndexError, ValueError):
            rss, start = 0, ""
        name = os.path.basename(exe) if exe else comm
        out.append({"Name": name, "Caption": name, "ProcessId": int(pid), "Handle": pid,
                    "ParentProcessId": int(rest[1]) if len(rest) > 1 else 0, "ExecutablePath": exe,
                    "CommandLine": cmd, "WorkingSetSize": rss, "ThreadCount": int(rest[17]) if len(rest) > 17 else 0,
                    "Priority": int(rest[15]) if len(rest) > 15 else 0, "CreationDate": start})
    return out


def _os_release():
    info = {}
    for line in _read("/etc/os-release").splitlines():
        k, _, v = line.partition("=")
        info[k] = v.strip('"')
    return info


def _meminfo():
    m = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        try:
            m[k] = int(v.split()[0])
        except (ValueError, IndexError):
            pass
    return m


def _wmi_os():
    osr, mem = _os_release(), _meminfo()
    boot = time.time() - float(_read("/proc/uptime", "0 0").split()[0])
    return [{"Caption": osr.get("PRETTY_NAME", "Linux"), "Name": osr.get("NAME", "Linux"),
             "Version": os.uname().release, "BuildNumber": os.uname().version, "OSArchitecture": "64-bit",
             "CSName": os.uname().nodename, "TotalVisibleMemorySize": mem.get("MemTotal", 0),
             "FreePhysicalMemory": mem.get("MemAvailable", 0), "LastBootUpTime":
             dt.datetime.fromtimestamp(boot).strftime("%Y%m%d%H%M%S.000000+000"),
             "Manufacturer": osr.get("NAME", "Linux"), "SerialNumber": _read("/etc/machine-id")}]


def _wmi_computer():
    mem = _meminfo()
    return [{"Name": os.uname().nodename, "TotalPhysicalMemory": mem.get("MemTotal", 0) * 1024,
             "Manufacturer": _read("/sys/class/dmi/id/sys_vendor"), "Model": _read("/sys/class/dmi/id/product_name"),
             "NumberOfProcessors": 1, "NumberOfLogicalProcessors": os.cpu_count() or 1,
             "UserName": os.environ.get("USER", ""), "Domain": "WORKGROUP", "SystemType": "x64-based PC"}]


def _wmi_cpu():
    info = _read("/proc/cpuinfo")
    name = next((l.split(":", 1)[1].strip() for l in info.splitlines() if l.startswith("model name")), "")
    cores = {l.split(":", 1)[1].strip() for l in info.splitlines() if l.startswith("core id")}
    mhz = _read("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq", "0")
    load = 0
    try:
        load = int(min(100, os.getloadavg()[0] / (os.cpu_count() or 1) * 100))
    except OSError:
        pass
    return [{"Name": name, "NumberOfCores": len(cores) or os.cpu_count() or 1,
             "NumberOfLogicalProcessors": os.cpu_count() or 1, "MaxClockSpeed": int(mhz) // 1000 if mhz.isdigit() else 0,
             "LoadPercentage": load, "Manufacturer": next((l.split(":", 1)[1].strip() for l in info.splitlines()
                                                          if l.startswith("vendor_id")), ""), "DeviceID": "CPU0"}]


def _wmi_disks():
    from .files import DriveGetList
    rows = []
    for letter in DriveGetList():
        root = letter + ":\\"
        try:
            st = os.statvfs(_hp(root))
        except OSError:
            continue
        from .files import DriveGetFileSystem, DriveGetLabel, DriveGetType
        rows.append({"DeviceID": letter + ":", "Name": letter + ":", "FreeSpace": st.f_bavail * st.f_frsize,
                     "Size": st.f_blocks * st.f_frsize, "FileSystem": DriveGetFileSystem(root),
                     "VolumeName": DriveGetLabel(root),
                     "DriveType": {"Removable": 2, "Fixed": 3, "Network": 4, "CDROM": 5, "RAMDisk": 6}.get(
                         DriveGetType(root), 3)})
    return rows


def _wmi_bios():
    return [{"Manufacturer": _read("/sys/class/dmi/id/bios_vendor"), "SMBIOSBIOSVersion":
             _read("/sys/class/dmi/id/bios_version"), "Version": _read("/sys/class/dmi/id/bios_version"),
             "ReleaseDate": _read("/sys/class/dmi/id/bios_date"), "SerialNumber": _read("/sys/class/dmi/id/product_serial")}]


def _wmi_net():
    rows = []
    try:
        names = sorted(os.listdir("/sys/class/net"))
    except OSError:
        names = []
    from .misc import SysGetIPAddresses
    ips = [S(x) for x in SysGetIPAddresses().items]
    for i, n in enumerate(names):
        if n == "lo":
            continue
        rows.append({"Description": n, "Index": i, "MACAddress": _read(f"/sys/class/net/{n}/address").upper()
                     .replace(":", ":"), "IPEnabled": -1 if _read(f"/sys/class/net/{n}/operstate") == "up" else 0,
                     "IPAddress": SafeArray(VT_BSTR, ips) if _read(f"/sys/class/net/{n}/operstate") == "up" else ""})
    return rows


WMI_CLASSES = {"win32_process": _wmi_processes, "win32_operatingsystem": _wmi_os,
               "win32_computersystem": _wmi_computer, "win32_processor": _wmi_cpu,
               "win32_logicaldisk": _wmi_disks, "win32_bios": _wmi_bios,
               "win32_networkadapterconfiguration": _wmi_net}


# ---------------------------------------------------------------- the built-ins
PROGIDS = {"winhttp.winhttprequest.5.1": lambda: WinHttpRequest(),
           "winhttp.winhttprequest": lambda: WinHttpRequest(),
           "msxml2.xmlhttp": lambda: WinHttpRequest(xml=True), "msxml2.xmlhttp.3.0": lambda: WinHttpRequest(xml=True),
           "msxml2.xmlhttp.6.0": lambda: WinHttpRequest(xml=True), "microsoft.xmlhttp": lambda: WinHttpRequest(xml=True),
           "msxml2.serverxmlhttp": lambda: WinHttpRequest(xml=True),
           "msxml2.serverxmlhttp.6.0": lambda: WinHttpRequest(xml=True),
           "scripting.dictionary": Dictionary, "wscript.shell": WshShell,
           "scripting.filesystemobject": FileSystemObject, "adodb.stream": AdodbStream, "sapi.spvoice": SpVoice,
           "shell.application": ShellApplication,
           # CLSIDs scripts sometimes use instead of ProgIDs
           "{2087c2f4-2cef-4953-a8ab-66779b670495}": lambda: WinHttpRequest(),
           "{ee09b103-97e0-11cf-978f-00a02463e06f}": Dictionary,
           "{72c24dd5-d70a-438b-8a42-98424b88afb8}": WshShell,
           "{0d43fe01-f093-11cf-8940-00a0c9054228}": FileSystemObject,
           "{13709620-c279-11ce-a49e-444553540000}": ShellApplication}


def com_object(progid, iid=UNSET):
    _proto_setup()
    key = S(progid).strip().lower()
    factory = PROGIDS.get(key)
    if factory is None:
        com_error(0x800401F3, "Invalid class string", S(progid))
    return ComDispatch(factory())


@export("ComObjGet")
def ComObjGet(name):
    _proto_setup()
    s = S(name).strip()
    if s.lower().startswith("winmgmts:"):
        return ComDispatch(WmiServices())
    com_error(0x800401E4, "Invalid syntax", s)


@export("ComObjArray")
def ComObjArray(vt, *dims):
    _proto_setup()
    if not dims:
        throw("ValueError", "Too few parameters passed to function.", "ComObjArray")
    n = 1
    for d in dims:
        n *= rt().to_int(d)
    return SafeArray(rt().to_int(vt), [""] * n if rt().to_int(vt) != VT_UI1 else [0] * n)


@export("ComObjType")
def ComObjType(obj, info=UNSET):
    _proto_setup()
    if info is not UNSET and S(info):
        i = S(info).lower()
        if isinstance(obj, ComDispatch):
            if i == "name":
                return obj.impl.iface
            if i == "class":
                return type(obj.impl).__name__
            if i in ("iid", "clsid", "cliid"):
                return ""
        return ""
    if isinstance(obj, ComDispatch):
        return VT_DISPATCH
    if isinstance(obj, SafeArray):
        return VT_ARRAY | obj.vt
    if isinstance(obj, ComValueObj):
        return obj.vt
    return ""


@export("ComObjValue")
def ComObjValue(obj):
    if isinstance(obj, ComValueObj):
        return obj.val
    if isinstance(obj, (ComDispatch, SafeArray)):
        return id(obj)
    throw("TypeError", "Expected a ComValue.", "ComObjValue")


@export("ComObjFlags")
def ComObjFlags(obj, new=UNSET, mask=UNSET):
    if not isinstance(obj, (ComDispatch, ComValueObj)):
        throw("TypeError", "Expected a ComValue.", "ComObjFlags")
    old = obj.flags
    if new is not UNSET:
        n = rt().to_int(new)
        m = rt().to_int(mask) if mask is not UNSET else (n if n >= 0 else -n)
        obj.flags = (old & ~m) | (n & m) if n >= 0 else old & ~(-n)
    return old


@export("ComObjConnect")
def ComObjConnect(obj, sink=UNSET):
    """Event sink for an emulated COM object: an object with OnXxx methods or a function-name prefix."""
    if not isinstance(obj, ComDispatch):
        throw("TypeError", "Expected a ComObject.", "ComObjConnect")
    obj.sink = None if sink is UNSET or sink == "" else (S(sink) if isinstance(sink, str) else sink)
    return ""


@export("ComObjActive")
def ComObjActive(progid):
    com_error(0x800401E3, "Operation unavailable (the running object table is Windows-only)", S(progid))


@export("ComObjQuery")
def ComObjQuery(*a):
    throw("Error", "ComObjQuery needs real COM interface pointers (Windows-only, not available in Bunny Hot Key).")


@export("ComObjFromPtr")
def ComObjFromPtr(*a):
    throw("Error", "ComObjFromPtr needs a real COM interface pointer (Windows-only, not available in Bunny Hot Key).")


@export("ComCall")
def ComCall(*a):
    throw("Error", "ComCall calls COM vtables (Windows-only, not available in Bunny Hot Key).")


def setup_classes():
    """ComObject(ProgID), ComValue(VarType, Value) and ComObjArray(VarType, Count) as callable classes."""
    from ..classes import method
    _proto_setup()
    method(CLASSES["ComObject"], "Call", lambda this, progid, iid=UNSET: com_object(progid, iid))
    method(CLASSES["ComValue"], "Call", lambda this, vt, value="", flags=0:
           ComValueObj(rt().to_int(vt), value, rt().to_int(flags) if flags not in (UNSET, "") else 0))
    method(CLASSES["ComObjArray"], "Call", lambda this, vt, *dims: ComObjArray(vt, *dims))
