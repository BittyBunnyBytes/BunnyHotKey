"""The tray icon (script_menu.cpp / Script::CreateTrayIcon): standard menu, tooltip, state icons.

Shown once the script becomes persistent (hotkeys, timers, Gui, Persistent()),
unless #NoTrayIcon or A_IconHidden.  The GTK side (gtkgui_helper.Tray) uses
XApp.StatusIcon on Cinnamon/XFCE/MATE, a plain XEmbed StatusIcon on other
X11 trays, or AppIndicator where only StatusNotifier trays exist.
"""
from __future__ import annotations

import os
import subprocess
import sys

from .. import objects as O

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ICONS = {"normal": "bunnyhotkey-64.png", "suspend": "bunnyhotkey-suspend-64.png", "pause": "bunnyhotkey-pause-64.png"}
HELP_URL = "https://www.autohotkey.com/docs/v2/"

_menu = None
_shown = False


def rt():
    return O.RT


def menu():
    global _menu
    if _menu is None:
        from .guiobj import MenuObj
        _menu = MenuObj()
        add_standard_items(_menu)
        _menu.default = "&Open"
        _menu.on_change = refresh
    return _menu


def _open_main():
    r = rt()
    lines = [f"Script: {r.script_path}", f"Bunny Hot Key, AutoHotkey {getattr(r, 'ahk_version', '2.0')} compatible", ""]
    if r.hotkeys is not None and r.hotkeys.hotkeys:
        lines.append("Hotkeys:")
        for hk in r.hotkeys.hotkeys:
            state = "on" if any(v.enabled for v in hk.variants) else "off"
            lines.append(f"  {hk.name}  ({state})")
    if r.hotstrings is not None and r.hotstrings.items:
        lines.append("")
        lines.append("Hotstrings:")
        for h in r.hotstrings.items:
            lines.append(f"  :{''.join(_opts(h))}:{h.trigger}")
    if r.timers:
        lines.append("")
        lines.append(f"Timers: {sum(1 for t in r.timers if t.enabled)} enabled")
    from .guiobj import _srv
    _srv().call("info", title=f"{os.path.basename(r.script_path)} - Bunny Hot Key", text="\n".join(lines))


def _opts(h):
    from ..hotmgr import _opt_letters
    return _opt_letters(h)


def _xdg_open(target):
    subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def _window_spy():
    subprocess.Popen([sys.executable, "-m", "bunnyhotkey", "windowspy"], cwd=ROOT, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _reload():
    from ..errors import ReloadEx
    raise ReloadEx()


def _suspend():
    rt().builtins["suspend"].call([-1])


def _pause():
    r = rt()
    r.paused = not r.paused
    refresh()


def _exit():
    from ..errors import ExitAppEx
    raise ExitAppEx(0)


STANDARD = [("&Open", _open_main), ("&Help", lambda: _xdg_open(HELP_URL)), ("", None),
            ("&Window Spy", _window_spy), ("&Reload Script", _reload),
            ("&Edit Script", lambda: _edit_script()), ("", None),
            ("&Suspend Hotkeys", _suspend), ("&Pause Script", _pause), ("E&xit", _exit)]


def add_standard_items(m):
    from .guiobj import MenuItem
    for name, fn in STANDARD:
        item = MenuItem(name, None, fn)
        if name in ("&Suspend Hotkeys", "&Pause Script"):
            item.checked = False
        m.items.append(item)


def _sync_checks(m):
    r = rt()
    for it in m.items:
        if it.builtin is _suspend:
            it.checked = bool(r.suspended)
        elif it.builtin is _pause:
            it.checked = bool(r.paused)


def _icon_path():
    r = rt()
    custom = getattr(r, "tray_icon", "")
    if custom and not (r.suspended or r.paused):
        from .files import host_path
        p = host_path(custom)
        if os.path.exists(p):
            return p
    state = "pause" if r.paused else "suspend" if r.suspended else "normal"
    return os.path.join(ROOT, "assets", ICONS[state])


def _tip():
    r = rt()
    tip = getattr(r, "icon_tip", "")
    return tip or os.path.basename(r.script_path)


def enabled() -> bool:
    r = rt()
    if r.directives.get("NoTrayIcon") or r.options.get("no_tray"):
        return False
    from . import gtkdlg
    return gtkdlg.available()


def show():
    global _shown
    if not enabled():
        return None
    m = menu()
    _sync_checks(m)
    from .guiobj import _srv, menu_tree
    kind = _srv().call("tray", icon=_icon_path(), tip=_tip(), items=menu_tree(m), click_count=m.click_count,
                       visible=not getattr(rt(), "icon_hidden", False))
    _shown = True
    return kind


def refresh():
    if _shown:
        show()


AHK_NOTIFYICON = 0x404          # WM_USER + 4: uCallbackMessage and uID of the tray icon (script.cpp)
WM_LBUTTONDOWN, WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x201, 0x203, 0x205


def on_mouse(lp):
    """A click on the icon, in the script thread.  OnMessage(0x404) handlers see it first (wParam 1028, lParam the
    mouse message) and a non-blank return stops the default action; then MainWindowProc's AHK_NOTIFYICON case:
    the default item on a double-click (or single click with ClickCount 1), the menu on right-button-up."""
    from .flow import message_handlers
    r = rt()
    for fn in message_handlers(AHK_NOTIFYICON):
        res = r.call(fn, [AHK_NOTIFYICON, lp, AHK_NOTIFYICON, getattr(r, "script_hwnd", 0)])
        if res != "" and res is not None:
            return
    m = menu()
    if lp == WM_LBUTTONDOWN and m.click_count != 1:
        return
    if lp in (WM_LBUTTONDOWN, WM_LBUTTONDBLCLK):
        if m.default:
            it = m.find_item(m.default, required=False)
            if it is not None:
                m.activate(m.items.index(it))
    elif lp == WM_RBUTTONUP:
        _sync_checks(m)
        from .guiobj import _srv, menu_tree
        _srv().call("tray", items=menu_tree(m), popup=True)


def on_event(msg):
    m = menu()
    if msg["event"] == "TrayMouse":
        rt().post(lambda: on_mouse(int(msg["msg"])))
    elif msg["event"] == "TrayItem":
        m.activate(msg["index"])
    elif msg["event"] == "TrayDefault" and m.default:
        it = m.find_item(m.default, required=False)
        if it is not None:
            m.activate(m.items.index(it))


def _edit_script():
    from .process import edit_file
    edit_file(rt().script_path)
