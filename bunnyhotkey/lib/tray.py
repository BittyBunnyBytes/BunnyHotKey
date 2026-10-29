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
            ("&Edit Script", lambda: _xdg_open(rt().script_path)), ("", None),
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
    from .guiobj import _srv
    kind = _srv().call("tray", icon=_icon_path(), tip=_tip(), items=m.wire(), click_count=m.click_count,
                       visible=not getattr(rt(), "icon_hidden", False))
    _shown = True
    return kind


def refresh():
    if _shown:
        show()


def on_event(msg):
    m = menu()
    if msg["event"] == "TrayItem":
        m.activate(msg["index"])
    elif msg["event"] == "TrayDefault" and m.default:
        it = m.find_item(m.default, required=False)
        if it is not None:
            m.activate(m.items.index(it))
