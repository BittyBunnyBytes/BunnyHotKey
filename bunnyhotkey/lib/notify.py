"""Control notifications as Win32 delivers them: WM_COMMAND notification codes (BN_CLICKED, EN_CHANGE,
LBN_SELCHANGE...) and WM_NOTIFY codes (NM_CLICK, LVN_ITEMCHANGED, TVN_SELCHANGED...) for GuiCtrl.OnCommand,
GuiCtrl.OnNotify and OnMessage(0x111 / 0x4E) on the Gui window.

The GTK side reports AutoHotkey-level events (Click, Change, ItemSelect...); each is translated to the code the
matching Win32 control sends.  Order follows GuiWindowProc (script_gui.cpp): OnMessage monitors first, then
OnCommand callbacks (the named event still follows), or OnNotify callbacks (a non-blank return means handled, and
the named event is skipped).  OnNotify's lParam points to an NMHDR (with the NMLISTVIEW / NMTREEVIEW fields
scripts usually read).
"""
from __future__ import annotations

import struct

from .. import objects as O

WM_COMMAND, WM_NOTIFY, WM_HSCROLL, WM_VSCROLL = 0x111, 0x4E, 0x114, 0x115

# (control type, AutoHotkey event) -> WM_COMMAND notification code
COMMAND = {
    ("Button", "Click"): 0, ("CheckBox", "Click"): 0, ("Radio", "Click"): 0,          # BN_CLICKED
    ("Button", "DoubleClick"): 5, ("CheckBox", "DoubleClick"): 5, ("Radio", "DoubleClick"): 5,   # BN_DBLCLK
    ("Button", "Focus"): 6, ("CheckBox", "Focus"): 6, ("Radio", "Focus"): 6,          # BN_SETFOCUS
    ("Button", "LoseFocus"): 7, ("CheckBox", "LoseFocus"): 7, ("Radio", "LoseFocus"): 7,  # BN_KILLFOCUS
    ("Edit", "Change"): 0x300, ("Edit", "Focus"): 0x100, ("Edit", "LoseFocus"): 0x200,  # EN_*
    ("Hotkey", "Change"): 0x300,
    ("Text", "Click"): 0, ("Text", "DoubleClick"): 1,                                   # STN_CLICKED/DBLCLK
    ("Picture", "Click"): 0, ("Picture", "DoubleClick"): 1,
    ("ListBox", "Change"): 1, ("ListBox", "DoubleClick"): 2, ("ListBox", "Focus"): 4, ("ListBox", "LoseFocus"): 5,
    ("DDL", "Change"): 1, ("DDL", "DoubleClick"): 2, ("DDL", "Focus"): 3, ("DDL", "LoseFocus"): 4,
    ("ComboBox", "Change"): 1, ("ComboBox", "DoubleClick"): 2, ("ComboBox", "Focus"): 3,
    ("ComboBox", "LoseFocus"): 4,
}

NM_CLICK, NM_DBLCLK, NM_RCLICK, NM_SETFOCUS, NM_KILLFOCUS = -2, -3, -5, -7, -8
LVN_ITEMCHANGED, LVN_COLUMNCLICK, LVN_ENDLABELEDITW = -101, -108, -176
TVN_SELCHANGEDW, TVN_ITEMEXPANDEDW, TVN_ENDLABELEDITW = -451, -455, -460
NOTIFY = {
    ("ListView", "Click"): NM_CLICK, ("ListView", "DoubleClick"): NM_DBLCLK, ("ListView", "ContextMenu"): NM_RCLICK,
    ("ListView", "Focus"): NM_SETFOCUS, ("ListView", "LoseFocus"): NM_KILLFOCUS,
    ("ListView", "ItemSelect"): LVN_ITEMCHANGED, ("ListView", "ItemCheck"): LVN_ITEMCHANGED,
    ("ListView", "ItemFocus"): LVN_ITEMCHANGED, ("ListView", "ColClick"): LVN_COLUMNCLICK,
    ("ListView", "ItemEdit"): LVN_ENDLABELEDITW,
    ("TreeView", "Click"): NM_CLICK, ("TreeView", "DoubleClick"): NM_DBLCLK, ("TreeView", "ContextMenu"): NM_RCLICK,
    ("TreeView", "Focus"): NM_SETFOCUS, ("TreeView", "LoseFocus"): NM_KILLFOCUS,
    ("TreeView", "ItemSelect"): TVN_SELCHANGEDW, ("TreeView", "ItemExpand"): TVN_ITEMEXPANDEDW,
    ("TreeView", "ItemEdit"): TVN_ENDLABELEDITW,
    ("Tab", "Change"): -551,                    # TCN_SELCHANGE
    ("MonthCal", "Change"): -749,               # MCN_SELCHANGE
    ("DateTime", "Change"): -759,               # DTN_DATETIMECHANGE
    ("UpDown", "Change"): -722,                 # UDN_DELTAPOS
    ("Link", "Click"): NM_CLICK,
    ("StatusBar", "Click"): NM_CLICK, ("StatusBar", "DoubleClick"): NM_DBLCLK, ("StatusBar", "ContextMenu"): NM_RCLICK,
    ("IPAddress", "Change"): -860,              # IPN_FIELDCHANGED
}


def _hwnd(c):
    """The Gui window's handle as the script sees it (Gui.Hwnd)."""
    return getattr(c.gui, "xid", 0) or c.gui.wid


def ctrl_id(c):
    """The control's ID (GetDlgCtrlID): AutoHotkey numbers a Gui's controls from 3 in creation order."""
    try:
        return c.gui.ctrls.index(c) + 3
    except ValueError:
        return 0


def _nmhdr(c, code, ev, args):
    """An NMHDR (hwndFrom, idFrom, code) plus the fields of the larger structure for that code."""
    from .buffer import BufferObj
    b = BufferObj(160)
    struct.pack_into("<QQi", b.data, 0, c.cid, ctrl_id(c), code)
    row = args[0] if args and isinstance(args[0], int) else 0
    if c.ctype == "ListView":
        # NMLISTVIEW / NMITEMACTIVATE: iItem (0-based), iSubItem, uNewState, uOldState, uChanged
        if code == LVN_ITEMCHANGED:
            on = bool(len(args) > 1 and args[1])
            if ev == "ItemSelect":
                new, old = (2, 0) if on else (0, 2)                     # LVIS_SELECTED
            elif ev == "ItemFocus":
                new, old = 1, 0                                         # LVIS_FOCUSED
            else:                                                       # state image 2 = checked, 1 = unchecked
                new, old = (0x2000, 0x1000) if on else (0x1000, 0x2000)
            struct.pack_into("<iiIII", b.data, 24, row - 1, 0, new, old, 8)    # uChanged = LVIF_STATE
        elif code == LVN_COLUMNCLICK:
            struct.pack_into("<ii", b.data, 24, -1, row - 1)
        else:
            struct.pack_into("<ii", b.data, 24, row - 1, 0)
    elif c.ctype == "TreeView" and code in (TVN_SELCHANGEDW, TVN_ITEMEXPANDEDW):
        # NMTREEVIEW: action, itemOld (TVITEMW at 32), itemNew (TVITEMW at 88; hItem at +8)
        action = 2 if code == TVN_ITEMEXPANDEDW and len(args) > 1 and args[1] else 1
        struct.pack_into("<I", b.data, 24, action)
        struct.pack_into("<Q", b.data, 96, row)
    return b


def deliver(c, ev, args):
    """Run Win32-style handlers for one control event.  Returns True when the named OnEvent callbacks must not run
    (an OnNotify callback or OnMessage monitor handled it)."""
    from .flow import message_handlers
    r = O.RT
    key = (c.ctype, ev)
    code = COMMAND.get(key)
    if code is not None:
        wp = (code & 0xFFFF) << 16 | ctrl_id(c)
        for fn in message_handlers(WM_COMMAND):
            res = r.call(fn, [wp, c.cid, WM_COMMAND, _hwnd(c)])
            if res != "" and res is not None:
                return True
        for cb in list(c.command_cbs.get(code, [])):
            _cb(c, cb)([c])
        return False
    code = NOTIFY.get(key)
    if code is not None:
        nm = _nmhdr(c, code, ev, args)
        for fn in message_handlers(WM_NOTIFY):
            res = r.call(fn, [ctrl_id(c), nm.addr, WM_NOTIFY, _hwnd(c)])
            if res != "" and res is not None:
                return True
        for cb in list(c.notify_cbs.get(code, [])):
            res = _cb(c, cb)([c, nm.addr])
            if res != "" and res is not None:
                return True
        return False
    if c.ctype == "Slider" and ev == "Change":
        # trackbars report through WM_HSCROLL/WM_VSCROLL to the parent: TB_THUMBPOSITION with the position
        msg = WM_VSCROLL if c.vertical else WM_HSCROLL
        try:
            pos = int(r.to_int(args[0])) if args and args[0] not in ("", 0) else 0
        except Exception:
            pos = 0
        for fn in message_handlers(msg):
            res = r.call(fn, [4 | (pos & 0xFFFF) << 16, c.cid, msg, _hwnd(c)])
            if res != "" and res is not None:
                return True
    return False


def wants(c, ev):
    """Whether delivering this event can matter (handlers exist), so idle controls cost nothing."""
    from .flow import message_handlers
    key = (c.ctype, ev)
    if key in COMMAND:
        return bool(c.command_cbs.get(COMMAND[key]) or message_handlers(WM_COMMAND))
    if key in NOTIFY:
        return bool(c.notify_cbs.get(NOTIFY[key]) or message_handlers(WM_NOTIFY))
    if c.ctype == "Slider":
        return bool(message_handlers(WM_HSCROLL) or message_handlers(WM_VSCROLL))
    return False


def _cb(c, cb):
    """A callback (function object or method name of the Gui's event sink) taking an argument list."""
    from .guiobj import _resolve_cb
    return _resolve_cb(c.gui, cb)


def register(c, kind, code, cb, add):
    """GuiCtrl.OnCommand / OnNotify(NotifyCode, Callback, AddRemove)."""
    r = O.RT
    table = c.command_cbs if kind == "command" else c.notify_cbs
    n = r.to_int(code)
    lst = table.setdefault(n, [])
    a = r.to_int(add) if add not in ("", None) else 1
    if cb in lst:
        lst.remove(cb)
    if a > 0:
        lst.append(cb)
    elif a < 0:
        lst.insert(0, cb)
    if not lst:
        table.pop(n, None)
    return ""
