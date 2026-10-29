"""MsgBox / InputBox / ToolTip / TrayTip / file dialogs / Gui / Menu.

Dialog backends, best first: tkinter (full Gui support), zenity/kdialog/yad,
GTK3 helper processes (gtkdlg/guiobj), console.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
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
        tooltip(n, t, x, y)
        return ""
    if t:
        print(f"[ToolTip] {t}", file=sys.stderr)
    return ""


@export()
def TrayTip(text="", title="", options=0):
    t, ttl = S(text), S(title)
    if not t and not ttl:
        return ""
    if shutil.which("notify-send"):
        o = options if type(options) is int else 0
        icon = {1: "dialog-information", 2: "dialog-warning", 3: "dialog-error"}.get(o & 3, "")
        argv = ["notify-send", "-a", rt().bivars["a_scriptname"][0]()]
        if icon:
            argv += ["-i", icon]
        argv += [ttl or t, t if ttl else ""]
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print(f"[TrayTip] {ttl}: {t}", file=sys.stderr)
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
    throw("Error", "No file dialog available: install the tk package (sudo pacman -S tk) or zenity.")


# ---------------------------------------------------------------- Gui
def tray_menu(r):
    from .guiobj import tray_menu
    return tray_menu()


@export("MenuFromHandle")
def MenuFromHandle(h):
    return ""


@export()
def GuiFromHwnd(hwnd, recurse=0):
    from .guiobj import GUIS
    h = rt().to_int(hwnd)
    return next((g for g in GUIS.values() if g.xid == h or g.wid == h), "")


@export()
def GuiCtrlFromHwnd(hwnd):
    from .guiobj import CTRLS
    return CTRLS.get(rt().to_int(hwnd), "")


@export()
def IL_Create(*a):
    return 1


@export()
def IL_Add(*a):
    return 1


@export()
def IL_Destroy(*a):
    return 1


@export()
def LoadPicture(*a):
    return 0


@export()
def TraySetIcon(file="", number=UNSET, freeze=UNSET):
    rt().tray_icon = S(file)
    from . import tray
    tray.refresh()
    return ""
