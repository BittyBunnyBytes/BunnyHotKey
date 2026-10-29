"""MsgBox / InputBox / ToolTip / TrayTip / file dialogs / Gui / Menu.

Dialog backends, best first: tkinter (full Gui support), zenity/kdialog/yad,
GTK3 helper processes (gtkdlg/guiobj), console.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import sys

from .. import objects as O
from ..objects import AhkObject, CLASSES, throw
from ..values import UNSET
from . import export, setref


def rt():
    return O.RT


def S(v):
    return O.RT.to_str(v)


def have_display():
    return bool(os.environ.get("DISPLAY"))


BUTTON_SETS = {0: ["OK"], 1: ["OK", "Cancel"], 2: ["Abort", "Retry", "Ignore"], 3: ["Yes", "No", "Cancel"],
               4: ["Yes", "No"], 5: ["Retry", "Cancel"], 6: ["Cancel", "TryAgain", "Continue"]}
NAMED_SETS = {"ok": 0, "o": 0, "okcancel": 1, "o/c": 1, "oc": 1, "abortretryignore": 2, "a/r/i": 2, "ari": 2,
              "yesnocancel": 3, "y/n/c": 3, "ync": 3, "yesno": 4, "y/n": 4, "yn": 4, "retrycancel": 5, "r/c": 5,
              "rc": 5, "canceltryagaincontinue": 6, "c/t/c": 6, "ctc": 6}


def parse_msgbox_options(opts):
    btn, icon, default, timeout, ontop = 0, "", 1, None, False
    if type(opts) in (int, float):
        n = int(opts)
        btn = n & 0xF
        icon = {16: "error", 32: "question", 48: "warning", 64: "info"}.get(n & 0xF0, "")
        default = ((n >> 8) & 0xF) + 1
        ontop = bool(n & 0x41000)
        return btn, icon, default, timeout, ontop
    for word in S(opts).split():
        w = word.lower()
        if w in NAMED_SETS:
            btn = NAMED_SETS[w]
        elif w.startswith("icon"):
            icon = {"iconx": "error", "icon?": "question", "icon!": "warning", "iconi": "info"}.get(w, "")
        elif w.startswith("default"):
            default = int(w[7:] or 1)
        elif re.fullmatch(r"t\d+(\.\d+)?", w):
            timeout = float(w[1:])
        elif w.isdigit():
            return parse_msgbox_options(int(w))
        elif w == "owner" or w.startswith("owner"):
            pass
    return btn, icon, default, timeout, ontop


@export()
def MsgBox(text=UNSET, title=UNSET, options=0):
    r = rt()
    if text is UNSET:
        text = "Press OK to continue." if title is UNSET else ""
    t = S(text) if not isinstance(text, AhkObject) else S(O.RT.call_method(text, "ToString", [])) if text.find("ToString")[0] else throw("TypeError", O.type_error_msg("String", text))
    ttl = S(title) if title is not UNSET else r.bivars["a_scriptname"][0]()
    btn, icon, default, timeout, ontop = parse_msgbox_options(options)
    buttons = BUTTON_SETS.get(btn, ["OK"])
    r.dialog_open = getattr(r, "dialog_open", 0) + 1
    try:
        return show_dialog(t, ttl, buttons, icon, default, timeout)
    finally:
        r.dialog_open -= 1


def show_dialog(text, title, buttons, icon="", default=1, timeout=None):
    """Runs a modal message dialog while the script keeps processing other threads."""
    r = rt()
    from . import gtkdlg
    if gtkdlg.available():
        return gtkdlg.ask({"kind": "message", "text": text, "title": title, "buttons": buttons, "icon": icon,
                           "default": default, "timeout": timeout}).get("button", buttons[0])
    if have_display():
        z = shutil.which("zenity")
        k = shutil.which("kdialog")
        if z or k:
            return _external_msgbox(z, k, text, title, buttons, icon, timeout)
    print(f"[{title}] {text}", file=sys.stderr)
    if len(buttons) == 1:
        return buttons[0]
    try:
        ans = input("/".join(buttons) + "? ")
    except EOFError:
        return buttons[-1]
    for b in buttons:
        if b.lower().startswith(ans.strip().lower()[:1]):
            return b
    return buttons[0]


def _run_waiting(argv, input_text=None):
    """Run a dialog process while the script thread keeps dispatching events."""
    r = rt()
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stdin=subprocess.PIPE if input_text is not None else None,
                         stderr=subprocess.DEVNULL, text=True)
    if input_text is not None:
        p.stdin.write(input_text)
        p.stdin.close()
    while p.poll() is None:
        r.sleep(30)
    return p.returncode, p.stdout.read()


def _external_msgbox(z, k, text, title, buttons, icon, timeout):
    if z:
        kind = {"error": "--error", "warning": "--warning", "question": "--question", "info": "--info"}.get(icon, "--info")
        argv = [z, "--title", title, "--text", text, "--no-markup"]
        if len(buttons) == 1:
            argv.insert(1, kind if kind != "--question" else "--info")
            argv += ["--ok-label", buttons[0]]
        else:
            argv.insert(1, "--question")
            argv += ["--ok-label", buttons[0], "--cancel-label", buttons[-1] if len(buttons) == 2 else buttons[1]]
            if len(buttons) == 3:
                argv += ["--extra-button", buttons[2]]
        if timeout:
            argv += ["--timeout", str(int(timeout))]
        code, out = _run_waiting(argv)
        if code == 5:
            return "Timeout"
        if out.strip() and out.strip() in buttons:
            return out.strip()
        return buttons[0] if code == 0 else (buttons[-1] if len(buttons) <= 2 else buttons[1])
    if len(buttons) == 1:
        code, _ = _run_waiting([k, "--title", title, "--msgbox", text])
        return buttons[0]
    if len(buttons) == 3:
        code, _ = _run_waiting([k, "--title", title, "--yesnocancel", text, "--yes-label", buttons[0], "--no-label", buttons[1], "--cancel-label", buttons[2]])
        return [buttons[0], buttons[1], buttons[2]][min(code, 2)]
    code, _ = _run_waiting([k, "--title", title, "--yesno", text, "--yes-label", buttons[0], "--no-label", buttons[1]])
    return buttons[0] if code == 0 else buttons[1]


class InputBoxResult(AhkObject):
    __slots__ = ()


@export()
def InputBox(prompt="", title=UNSET, options="", default=""):
    r = rt()
    ttl = S(title) if title is not UNSET else r.bivars["a_scriptname"][0]()
    opts = S(options)
    password = re.search(r"(^|\s)password", opts, re.I) is not None
    m = re.search(r"(?:^|\s)t(\d+(?:\.\d+)?)", opts, re.I)
    timeout = float(m.group(1)) if m else None
    value, result = _input_dialog(S(prompt), ttl, S(default), password, timeout)
    obj = AhkObject(CLASSES["Object"].prototype)
    obj.define_value("Value", value)
    obj.define_value("Result", result)
    return obj


def _input_dialog(prompt, title, default, password, timeout):
    from . import gtkdlg
    if gtkdlg.available():
        r = gtkdlg.ask({"kind": "entry", "prompt": prompt, "title": title, "default": default,
                        "password": password, "timeout": timeout})
        return r.get("value", ""), r.get("result", "Cancel")
    if have_display():
        z = shutil.which("zenity")
        k = shutil.which("kdialog")
        if z:
            argv = [z, "--entry", "--title", title, "--text", prompt, "--entry-text", default]
            if password:
                argv = [z, "--password", "--title", title]
            if timeout:
                argv += ["--timeout", str(int(timeout))]
            code, out = _run_waiting(argv)
            if code == 5:
                return out.rstrip("\n"), "Timeout"
            return out.rstrip("\n"), "OK" if code == 0 else "Cancel"
        if k:
            argv = [k, "--title", title, "--password" if password else "--inputbox", prompt] + ([] if password else [default])
            code, out = _run_waiting(argv)
            return out.rstrip("\n"), "OK" if code == 0 else "Cancel"
    try:
        v = input(f"[{title}] {prompt}: ")
        return v, "OK"
    except EOFError:
        return "", "Cancel"


_tooltips: dict[int, object] = {}


@export()
def ToolTip(text=UNSET, x=UNSET, y=UNSET, which=1):
    r = rt()
    n = r.to_int(which) if which != "" else 1
    t = S(text) if text is not UNSET else ""
    from . import gtkdlg
    if gtkdlg.available():
        from .guiobj import tooltip
        return tooltip(n, t, x, y) if t else (tooltip(n, t, x, y), "")[1]
    if t:
        print(f"[ToolTip] {t}", file=sys.stderr)
    return ""


_traytip = {"id": 0, "replaced": set()}
NIN_BALLOONSHOW, NIN_BALLOONHIDE, NIN_BALLOONTIMEOUT, NIN_BALLOONUSERCLICK = 0x402, 0x403, 0x404, 0x405


def _traytip_opts(options):
    """TrayTip options: a number (1 info, 2 warning, 3 error, 4 tray icon, 16 mute, 32 large icon) or words
    (Iconi, Icon!, Iconx, Mute)."""
    if type(options) is int:
        return options
    n = 0
    for w in S(options).lower().split():
        if w.lstrip("-").isdigit() or w.startswith("0x"):
            n |= int(w, 0)
        else:
            n |= {"iconi": 1, "icon!": 2, "iconx": 3, "mute": 16}.get(w, 0)
    return n


def _close_notification(nid):
    if nid and shutil.which("gdbus"):
        subprocess.Popen(["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
                          "--object-path", "/org/freedesktop/Notifications",
                          "--method", "org.freedesktop.Notifications.CloseNotification", str(nid)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _balloon_event(lp):
    """Balloon notifications reach OnMessage(0x404) as on Windows (lParam NIN_BALLOON*)."""
    from . import tray
    rt().post(lambda: tray.on_mouse(lp))


@export()
def TrayTip(text="", title="", options=0):
    """A desktop notification standing in for the tray balloon.  TrayTip() with no text hides it; showing, clicking,
    expiring and hiding are reported to OnMessage(0x404) handlers as NIN_BALLOONSHOW/USERCLICK/TIMEOUT/HIDE."""
    t, ttl = S(text), S(title)
    if not t and not ttl:
        nid = _traytip["id"]
        if nid:
            _traytip["replaced"].add(nid)
            _close_notification(nid)
            _traytip["id"] = 0
            _balloon_event(NIN_BALLOONHIDE)
        return ""
    if not shutil.which("notify-send"):
        print(f"[TrayTip] {ttl}: {t}", file=sys.stderr)
        return ""
    o = _traytip_opts(options)
    icon = {1: "dialog-information", 2: "dialog-warning", 3: "dialog-error"}.get(o & 3, "")
    if o & 4:
        from . import tray
        icon = tray._icon_path()
    argv = ["notify-send", "-a", rt().bivars["a_scriptname"][0](), "-p", "-w", "-A", "default=Open"]
    if icon:
        argv += ["-i", icon]
    if o & 16:
        argv += ["-h", "boolean:suppress-sound:true"]
    prev = _traytip["id"]
    if prev:
        _traytip["replaced"].add(prev)
        argv += ["-r", str(prev)]
    argv += [ttl or t, t if ttl else ""]
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError:
        return ""

    def watch():
        first = p.stdout.readline().strip()
        nid = int(first) if first.isdigit() else 0
        _traytip["id"] = nid
        _traytip["replaced"].discard(nid)
        _balloon_event(NIN_BALLOONSHOW)
        action = p.stdout.readline().strip()
        p.wait()
        if action == "default":
            _balloon_event(NIN_BALLOONUSERCLICK)
        elif nid not in _traytip["replaced"]:
            _balloon_event(NIN_BALLOONTIMEOUT)
        if _traytip["id"] == nid:
            _traytip["id"] = 0
    threading.Thread(target=watch, daemon=True).start()
    return ""


def file_dialog(kind, start="", title="", filt=""):
    from . import gtkdlg
    if gtkdlg.available():
        from .files import host_path as _hp
        res = gtkdlg.ask({"kind": "file", "mode": kind, "title": title or "Select",
                          "start": _hp(start) if start else os.getcwd()}).get("paths", [])
        if kind == "multi":
            return O.AhkArray(None, res)
        return res[0] if res else ""
    z = shutil.which("zenity")
    k = shutil.which("kdialog")
    from .files import host_path
    start_h = host_path(start) if start else os.getcwd()
    if z:
        argv = [z, "--file-selection", "--title", title or "Select"]
        if kind == "dir":
            argv.append("--directory")
        elif kind == "save":
            argv.append("--save")
        elif kind == "multi":
            argv += ["--multiple", "--separator", "\n"]
        argv += ["--filename", start_h + ("/" if os.path.isdir(start_h) else "")]
        code, out = _run_waiting(argv)
        res = out.rstrip("\n") if code == 0 else ""
        if kind == "multi":
            return O.AhkArray(None, res.split("\n") if res else [])
        return res
    if k:
        flag = {"dir": "--getexistingdirectory", "save": "--getsavefilename", "multi": "--getopenfilename"}.get(kind, "--getopenfilename")
        argv = [k, flag, start_h]
        if kind == "multi":
            argv += ["--multiple", "--separate-output"]
        code, out = _run_waiting(argv)
        res = out.rstrip("\n") if code == 0 else ""
        if kind == "multi":
            return O.AhkArray(None, res.split("\n") if res else [])
        return res
    throw("Error", "No file dialog available: install PyGObject with GTK 3 (python-gobject), zenity or kdialog.")


# ---------------------------------------------------------------- Gui
def tray_menu(r):
    from .guiobj import tray_menu
    return tray_menu()


@export("MenuFromHandle")
def MenuFromHandle(h):
    from .guiobj import MENUS
    return MENUS.get(rt().to_int(h), "")


@export()
def GuiFromHwnd(hwnd, recurse=0):
    from .guiobj import GUIS
    h = rt().to_int(hwnd)
    return next((g for g in GUIS.values() if g.xid == h or g.wid == h), "")


@export()
def GuiCtrlFromHwnd(hwnd):
    from .guiobj import CTRLS
    return CTRLS.get(rt().to_int(hwnd), "")


# Image lists and picture handles are kept script-side as file references; the GTK side loads the images when a
# ListView/TreeView uses the list (SetImageList) or a Picture shows a handle ("HBITMAP:*123").
ILS: dict[int, dict] = {}
PICTURES: dict[int, str] = {}
_handles = iter(range(0x10001, 1 << 30))


@export()
def IL_Create(initial=2, grow=5, large=0):
    from ..values import to_bool
    h = next(_handles)
    ILS[h] = {"large": bool(to_bool(large)) if large not in (UNSET, "") else False, "items": []}
    return h


def picture_path(spec):
    """File path for a Picture/IL_Add source: a file, or an HBITMAP:/HICON: handle from LoadPicture."""
    m = re.fullmatch(r"\s*(?:hbitmap|hicon):\*?(\d+)\s*", spec, re.I)
    if m:
        h = int(m.group(1))
        if h not in PICTURES:                               # a bitmap drawn with GDI through DllCall
            from .win32gdi import png_of
            return png_of(h) or ""
        return PICTURES[h]
    from .files import host_path
    return host_path(spec) if spec else ""


@export()
def IL_Add(il, filename, icon_number=1, resize=0):
    lst = ILS.get(rt().to_int(il))
    if lst is None:
        return 0
    src = S(filename)
    path = picture_path(src)
    themed = _themed_icon(src, rt().to_int(icon_number) if icon_number not in (UNSET, "") else 1)
    if themed:
        path = themed
    elif not path or not os.path.exists(path):
        # Windows icon resources (shell32.dll, ...) have no file here; a generic icon stands in for them
        if not re.search(r"\.(dll|exe|cpl|icl|ocx)$", src, re.I):
            return 0
        path = src
    lst["items"].append(path)
    if lst.get("users"):
        from .guiobj import refresh_imagelist
        refresh_imagelist(lst)
    return len(lst["items"])


# Icons of Windows system files -> the desktop's icon theme (freedesktop names); BHK's own icon for A_AhkPath
_WIN_ICONS = {("imageres.dll", -111): "document-new", ("imageres.dll", -99): "help-browser",
              ("imageres.dll", -116): "preferences-system", ("imageres.dll", -3): "folder",
              ("imageres.dll", -2): "text-x-generic", ("imageres.dll", -5): "drive-harddisk",
              ("shell32.dll", 4): "folder", ("shell32.dll", 1): "text-x-generic", ("shell32.dll", 3): "folder",
              ("shell32.dll", 24): "help-browser", ("shell32.dll", 22): "preferences-system",
              ("shell32.dll", 28): "system-shutdown", ("shell32.dll", 44): "starred",
              ("notepad.exe", 1): "accessories-text-editor", ("explorer.exe", 1): "system-file-manager",
              ("cmd.exe", 1): "utilities-terminal", ("mmc.exe", 1): "preferences-system"}


def _themed_icon(src, number):
    base = os.path.basename(src.replace("\\", "/")).lower()
    if src and os.path.realpath(src) == os.path.realpath(rt().bivars["a_ahkpath"][0]()):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(root, "assets", "bunnyhotkey-48.png")
    name = _WIN_ICONS.get((base, number))
    if name is None and base in ("imageres.dll", "shell32.dll", "notepad.exe", "explorer.exe"):
        name = "application-x-executable"
    return name


@export()
def IL_Destroy(il):
    return 1 if ILS.pop(rt().to_int(il), None) is not None else 0


@export(byref=(2,))
def LoadPicture(filename, options="", imagetype=UNSET):
    path = picture_path(S(filename))
    if not path or not os.path.exists(path):
        return 0
    h = next(_handles)
    PICTURES[h] = path
    setref(imagetype, 1 if path.lower().endswith((".ico", ".cur", ".ani")) else 0)
    return h


@export()
def TraySetIcon(file="", number=UNSET, freeze=UNSET):
    rt().tray_icon = S(file)
    rt().tray_icon_number = rt().to_int(number) if number not in (UNSET, "") else 1
    from . import tray
    tray.refresh()
    return ""
