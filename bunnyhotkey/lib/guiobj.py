"""Gui / Gui.Control objects (lib/Gui.cpp) on top of the GTK server process (gtkgui_helper.py)."""
from __future__ import annotations

import itertools
import json
import os
import re
import subprocess
import sys
import threading

from .. import objects as O
from ..objects import AhkArray, AhkObject, CLASSES, throw
from ..values import UNSET, to_bool

HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gtkgui_helper.py")
TYPE_ALIASES = {"text": "Text", "edit": "Edit", "button": "Button", "checkbox": "CheckBox", "radio": "Radio",
                "dropdownlist": "DDL", "ddl": "DDL", "combobox": "ComboBox", "listbox": "ListBox",
                "listview": "ListView", "slider": "Slider", "progress": "Progress", "groupbox": "GroupBox",
                "picture": "Picture", "pic": "Picture", "link": "Link", "statusbar": "StatusBar"}
CLASS_OF = {"Picture": "Pic", "Text": "Text", "Edit": "Edit", "Button": "Button", "CheckBox": "CheckBox",
            "Radio": "Radio", "DDL": "DDL", "ComboBox": "ComboBox", "ListBox": "ListBox", "ListView": "ListView",
            "Slider": "Slider", "Progress": "Progress", "GroupBox": "GroupBox", "Link": "Link",
            "StatusBar": "StatusBar"}
MARGIN_X, MARGIN_Y = 10, 6
LINE_H = 18


def rt():
    return O.RT


def S(v):
    return O.RT.to_str(v)


class Server:
    _inst = None

    @classmethod
    def get(cls):
        if cls._inst is None:
            cls._inst = Server()
        return cls._inst

    def __init__(self):
        env = dict(os.environ, BHK_TRAY_NAME="Bunny Hot Key - " + os.path.basename(O.RT.script_path))
        self.p = subprocess.Popen([sys.executable, "-I", HELPER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env)
        self.ids = itertools.count(1)
        self.replies = {}
        self.cond = threading.Condition()
        threading.Thread(target=self._reader, name="bhk-gui", daemon=True).start()

    def _reader(self):
        for line in self.p.stdout:
            msg = json.loads(line)
            if "reply" in msg:
                with self.cond:
                    self.replies[msg["reply"]] = msg
                    self.cond.notify_all()
            else:
                dispatch_event(msg)

    def call(self, op, **kw):
        rid = next(self.ids)
        kw.update(id=rid, op=op)
        self.p.stdin.write(json.dumps(kw) + "\n")
        self.p.stdin.flush()
        with self.cond:
            while rid not in self.replies:
                self.cond.wait(5)
                if self.p.poll() is not None:
                    throw("Error", "The Gui server stopped.")
            msg = self.replies.pop(rid)
        if "error" in msg:
            throw("Error", msg["error"])
        return msg.get("value")


GUIS: dict[int, "GuiObj"] = {}
CTRLS: dict[int, "CtrlObj"] = {}
_win_ids = itertools.count(1)
_ctrl_ids = itertools.count(1)


class GuiObj(AhkObject):
    __slots__ = ("wid", "ctrls", "events", "event_obj", "prev", "section", "title", "shown", "mx", "my",
                 "destroyed", "names", "xid")

    def __init__(self, proto=None):
        super().__init__(proto or CLASSES["Gui"].prototype)
        self.wid = 0
        self.ctrls = []
        self.events = {}
        self.event_obj = None
        self.prev = None
        self.section = (MARGIN_X, MARGIN_Y)
        self.title = ""
        self.shown = False
        self.mx, self.my = MARGIN_X, MARGIN_Y
        self.destroyed = False
        self.names = {}
        self.xid = 0


class CtrlObj(AhkObject):
    __slots__ = ("cid", "gui", "ctype", "name", "events", "x", "y", "w", "h", "rows", "altsubmit", "group")

    def __init__(self, gui, ctype):
        super().__init__(CLASSES["Gui." + CLASS_OF.get(ctype, "Text")].prototype)
        self.cid = next(_ctrl_ids)
        self.gui = gui
        self.ctype = ctype
        self.name = ""
        self.events = {}
        self.rows = 0
        self.altsubmit = False
        self.group = 0


def _srv():
    return Server.get()


def gui_new(this, options="", title=UNSET, event_obj=UNSET):
    this.wid = next(_win_ids)
    this.title = S(title) if title is not UNSET else rt().bivars["a_scriptname"][0]()
    this.event_obj = event_obj if event_obj is not UNSET else None
    opts = S(options).lower()
    this.xid = _srv().call("new", win=this.wid, title=this.title,
                           resize="+resize" in opts or "resize" in opts.split()) or 0
    GUIS[this.wid] = this
    rt().gui_count = getattr(rt(), "gui_count", 0) + 1
    return ""


def _parse_pos(gui, opts):
    """AHK positioning options -> (x, y, w, h, flags dict)."""
    prev = gui.prev
    px, py, pw, ph = (prev.x, prev.y, prev.w, prev.h) if prev else (gui.mx, gui.my - 0, 0, 0)
    x = y = w = h = None
    rows = None
    flags = {}
    for tok in opts.split():
        tl = tok.lower()
        m = re.fullmatch(r"([xy])(m|p|s|\+|-)?(\+?-?\d+)?", tl)
        if m and (m.group(2) or m.group(3)):
            axis, mode, num = m.group(1), m.group(2) or "", m.group(3)
            n = int(num) if num else 0
            if mode == "m":
                v = (gui.mx if axis == "x" else gui.my) + n
            elif mode == "p":
                v = (px if axis == "x" else py) + n
            elif mode == "s":
                v = (gui.section[0] if axis == "x" else gui.section[1]) + n
            elif mode in ("+", "-") or (num and num.startswith("+")):
                base = (px + pw) if axis == "x" else (py + ph)
                v = base + (n if mode != "-" else -abs(n))
            else:
                v = n
            if axis == "x":
                x = v
            else:
                y = v
            continue
        m = re.fullmatch(r"([wh])(p)?([+-]?\d+)?", tl)
        if m and (m.group(2) or m.group(3)):
            n = int(m.group(3)) if m.group(3) else 0
            v = ((pw if m.group(1) == "w" else ph) + n) if m.group(2) else n
            if m.group(1) == "w":
                w = v
            else:
                h = v
            continue
        m = re.fullmatch(r"r(\d+)", tl)
        if m:
            rows = int(m.group(1))
            continue
        if tl.startswith("v") and len(tok) > 1 and not tl.startswith("vertical"):
            flags["name"] = tok[1:]
            continue
        m = re.fullmatch(r"choose(\d+)", tl)
        if m:
            flags["choose"] = int(m.group(1))
            continue
        m = re.fullmatch(r"range(-?\d+)-(-?\d+)", tl)
        if m:
            flags["range"] = [int(m.group(1)), int(m.group(2))]
            continue
        word = tl.lstrip("+")
        if word in ("section", "hidden", "disabled", "checked", "default", "readonly", "password", "multi",
                    "center", "group", "checked1"):
            flags[word.rstrip("1")] = True
        if word == "altsubmit":
            flags["altsubmit"] = True
        if word.startswith("password"):
            flags["password"] = True
    if x is None and y is None:
        x = prev.x if prev is not None else gui.mx
        y = py + ph + gui.my if prev is not None else gui.my
    elif x is None:
        x = (px + pw + gui.mx) if prev is not None else gui.mx
    elif y is None:
        y = py if prev is not None and x != gui.mx else (py + ph + gui.my if prev else gui.my)
    if rows and h is None:
        h = rows * LINE_H + 8
    return x, y, w, h, flags


def gui_add(this, ctype, options="", text=UNSET):
    t = TYPE_ALIASES.get(S(ctype).lower())
    if t is None:
        throw("ValueError", "Invalid control type.", S(ctype))
    if this.destroyed:
        throw("Error", "Gui has no window.")
    opts = S(options)
    x, y, w, h, flags = _parse_pos(this, opts)
    ctrl = CtrlObj(this, t)
    send = {"x": x, "y": y, "w": w, "h": h}
    items = []
    if isinstance(text, AhkArray):
        items = [S(i) for i in text.items]
        txt = ""
    else:
        txt = S(text) if text is not UNSET else ""
    if t == "ListView":
        send["columns"] = items or [txt]
        items = []
    send.update(text=txt, items=items, **{k: v for k, v in flags.items() if k not in ("name", "altsubmit")})
    ctrl.altsubmit = bool(flags.get("altsubmit"))
    if t == "Radio":
        prev_radio = this.prev is not None and this.prev.ctype == "Radio"
        ctrl.group = this.prev.group if prev_radio and not flags.get("group") else ctrl.cid
    if t == "Edit" and h is None and "r" in opts.lower().split() and False:
        pass
    if t == "Edit" and (flags.get("multi") or (h and h > 30)):
        send["multi"] = True
    if t in ("ListBox", "ListView") and h is None:
        send["h"] = 5 * LINE_H + 8 if t == "ListBox" else 10 * LINE_H
    if t == "Edit" and w is None:
        send["w"] = 120
    pref = _srv().call("add", win=this.wid, ctrl=ctrl.cid, type=t, opts=send)
    ctrl.x, ctrl.y = x, y
    ctrl.w = send.get("w") or pref["w"]
    ctrl.h = send.get("h") or pref["h"]
    if flags.get("section"):
        this.section = (x, y)
    if "name" in flags:
        ctrl.name = flags["name"]
        this.names[ctrl.name.lower()] = ctrl
    this.ctrls.append(ctrl)
    this.prev = ctrl
    CTRLS[ctrl.cid] = ctrl
    return ctrl


def gui_show(this, options=""):
    o = S(options).lower()
    kw = {}
    for k in ("w", "h", "x", "y"):
        m = re.search(r"(?:^|\s)" + k + r"(-?\d+)", o)
        if m:
            kw[k] = int(m.group(1))
    if "w" not in kw and this.ctrls:
        kw["w"] = max(c.x + c.w for c in this.ctrls) + this.mx
    if "h" not in kw and this.ctrls:
        kw["h"] = max(c.y + c.h for c in this.ctrls) + this.my
    if "hide" in o.split():
        return ""
    _srv().call("show", win=this.wid, center="x" not in kw and "y" not in kw, **kw)
    this.shown = True
    if this.xid:
        # wait (briefly) until the window manager lists the window, so Win* functions can find it
        from .window import _dpy, client_list
        import time
        d = _dpy()
        end = time.monotonic() + 1.0
        while d is not None and this.xid not in client_list(d) and time.monotonic() < end:
            time.sleep(0.02)
    return ""


def gui_submit(this, hide=1):
    out = AhkObject(CLASSES["Object"].prototype)
    for c in this.ctrls:
        if not c.name:
            continue
        if c.ctype == "Radio":
            members = [r for r in this.ctrls if r.ctype == "Radio" and r.group == c.group]
            if members[0] is c and not any(m.name for m in members[1:]):
                pos = 0
                for i, m in enumerate(members, 1):
                    if ctrl_get(m, "Value"):
                        pos = i
                out.define_value(c.name, pos)
            else:
                out.define_value(c.name, ctrl_get(c, "Value"))
        elif c.ctype in ("DDL", "ComboBox", "ListBox") and not c.altsubmit:
            out.define_value(c.name, ctrl_get(c, "Text"))
        else:
            out.define_value(c.name, ctrl_get(c, "Value"))
    if to_bool(hide):
        gui_hide(this)
    return out


def gui_hide(this):
    _srv().call("hide", win=this.wid)
    this.shown = False
    return ""


def gui_destroy(this):
    if not this.destroyed:
        _srv().call("destroy", win=this.wid)
        this.destroyed = True
        GUIS.pop(this.wid, None)
        rt().gui_count = max(getattr(rt(), "gui_count", 1) - 1, 0)
    return ""


def _on_event(target, name, cb, add=1):
    lst = target.events.setdefault(S(name).lower(), [])
    a = rt().to_int(add) if add is not UNSET else 1
    if cb in lst:
        lst.remove(cb)
    if a > 0:
        lst.append(cb)
    elif a < 0:
        lst.insert(0, cb)
    return ""


def ctrl_get(c, prop):
    v = _srv().call("get", ctrl=c.cid, prop=prop)
    return v


def ctrl_set(c, prop, v):
    if isinstance(v, AhkObject):
        throw("TypeError", O.type_error_msg("String", v))
    _srv().call("set", ctrl=c.cid, prop=prop, value=v if not isinstance(v, str) or prop != "Value" else v)
    return v


def _resolve_cb(owner_gui, cb):
    if isinstance(cb, str) and owner_gui is not None and owner_gui.event_obj is not None:
        return lambda args: rt().call_method(owner_gui.event_obj, cb, args)
    return lambda args: rt().call(cb, args)


def dispatch_event(msg):
    r = rt()
    ev = msg["event"]
    if ev == "MenuPick":
        m = MENUS.get(msg["menu"])
        if m is not None:
            m.activate(msg["index"])
        return
    if ev in ("TrayItem", "TrayDefault"):
        from . import tray
        tray.on_event(msg)
        return
    if "ctrl" in msg:
        c = CTRLS.get(msg["ctrl"])
        if c is None:
            return
        cbs = list(c.events.get(ev.lower(), []))
        if not cbs:
            return
        info = msg.get("row", 0)
        for cb in cbs:
            fn = _resolve_cb(c.gui, cb)
            r.post(lambda fn=fn: fn([c, info]))
        return
    g = GUIS.get(msg.get("win"))
    if g is None:
        return
    cbs = list(g.events.get(ev.lower(), []))
    if ev == "Close":
        def run_close():
            handled = False
            for cb in cbs:
                res = _resolve_cb(g, cb)([g])
                if to_bool(res):
                    handled = True
                    break
            if not handled and not g.destroyed:
                gui_hide(g)
        r.post(run_close)
        return
    if ev == "Size":
        for cb in cbs:
            fn = _resolve_cb(g, cb)
            r.post(lambda fn=fn: fn([g, 0, msg["w"], msg["h"]]))
        return
    for cb in cbs:
        fn = _resolve_cb(g, cb)
        r.post(lambda fn=fn: fn([g]))


def _lv_fields(args):
    return [S(a) for a in args]


def setup():
    from ..classes import method, prop
    menu_setup()
    gp = CLASSES["Gui"].prototype
    if gp.own("Add") is not None:
        return
    CLASSES["Gui"].factory = lambda proto: GuiObj(proto)
    method(gp, "__New", lambda this, options="", title=UNSET, eo=UNSET: gui_new(this, options, title, eo))
    method(gp, "Add", lambda this, t, opts="", text=UNSET: gui_add(this, t, opts, text))
    for alias, t in (("AddText", "Text"), ("AddEdit", "Edit"), ("AddButton", "Button"), ("AddCheckBox", "CheckBox"),
                     ("AddRadio", "Radio"), ("AddDropDownList", "DDL"), ("AddDDL", "DDL"), ("AddComboBox", "ComboBox"),
                     ("AddListBox", "ListBox"), ("AddListView", "ListView"), ("AddSlider", "Slider"),
                     ("AddProgress", "Progress"), ("AddGroupBox", "GroupBox"), ("AddPicture", "Picture"),
                     ("AddPic", "Picture"), ("AddLink", "Link"), ("AddStatusBar", "StatusBar")):
        method(gp, alias, lambda this, opts="", text=UNSET, t=t: gui_add(this, t, opts, text))
    method(gp, "Show", lambda this, opts="": gui_show(this, opts))
    method(gp, "Hide", lambda this: gui_hide(this))
    method(gp, "Destroy", lambda this: gui_destroy(this))
    method(gp, "Submit", lambda this, hide=1: gui_submit(this, hide))
    method(gp, "OnEvent", lambda this, name, cb, add=1: _on_event(this, name, cb, add))
    method(gp, "SetFont", lambda this, *a: "")
    method(gp, "Opt", lambda this, o: "")
    method(gp, "Flash", lambda this, *a: "")
    method(gp, "Minimize", lambda this: "")
    method(gp, "Maximize", lambda this: "")
    method(gp, "Restore", lambda this: gui_show(this))
    method(gp, "Move", lambda this, *a: "")
    method(gp, "GetPos", lambda this, *refs: _getpos(this, refs))
    method(gp, "GetClientPos", lambda this, *refs: _getpos(this, refs))
    method(gp, "__Enum", lambda this, n=1: _gui_enum(this, n))
    prop(gp, "Title", get=lambda this: this.title, set=lambda this, v: (_srv().call("title", win=this.wid, value=S(v)),
                                                                          setattr(this, "title", S(v)), v)[-1])
    prop(gp, "Hwnd", get=lambda this: this.xid or this.wid)
    prop(gp, "MarginX", get=lambda this: this.mx, set=lambda this, v: setattr(this, "mx", rt().to_int(v)))
    prop(gp, "MarginY", get=lambda this: this.my, set=lambda this, v: setattr(this, "my", rt().to_int(v)))
    prop(gp, "BackColor", get=lambda this: "", set=lambda this, v: v)
    prop(gp, "FocusedCtrl", get=lambda this: "")
    prop(gp, "__Item", get=lambda this, name: _gui_item(this, name))

    cp = CLASSES["Gui.Control"].prototype
    prop(cp, "Value", get=lambda this: _num(ctrl_get(this, "Value")), set=lambda this, v: ctrl_set(this, "Value", v))
    prop(cp, "Text", get=lambda this: ctrl_get(this, "Text"), set=lambda this, v: ctrl_set(this, "Text", S(v)))
    prop(cp, "Enabled", get=lambda this: 1, set=lambda this, v: ctrl_set(this, "Enabled", int(to_bool(v))))
    prop(cp, "Visible", get=lambda this: 1, set=lambda this, v: ctrl_set(this, "Visible", int(to_bool(v))))
    prop(cp, "Name", get=lambda this: this.name, set=lambda this, v: setattr(this, "name", S(v)))
    prop(cp, "Hwnd", get=lambda this: this.cid)
    prop(cp, "Gui", get=lambda this: this.gui)
    prop(cp, "Type", get=lambda this: this.ctype)
    prop(cp, "ClassNN", get=lambda this: f"{this.ctype}{this.cid}")
    method(cp, "OnEvent", lambda this, name, cb, add=1: _on_event(this, name, cb, add))
    method(cp, "Focus", lambda this: _srv().call("focus", ctrl=this.cid) and "")
    method(cp, "Move", lambda this, x=UNSET, y=UNSET, w=UNSET, h=UNSET: _ctrl_move(this, x, y, w, h))
    method(cp, "GetPos", lambda this, *refs: _ctrl_getpos(this, refs))
    method(cp, "Opt", lambda this, o: "")
    method(cp, "SetFont", lambda this, *a: "")
    method(cp, "Redraw", lambda this: "")
    lp = CLASSES["Gui.List"].prototype
    method(lp, "Add", lambda this, items: _srv().call("items", ctrl=this.cid, add=[S(i) for i in items.items]) and "")
    method(lp, "Delete", lambda this, n=UNSET: _srv().call("items", ctrl=this.cid, clear=True) and "")
    method(lp, "Choose", lambda this, v: ctrl_set(this, "Value" if not isinstance(v, str) else "Text", v) and "")
    lv = CLASSES["Gui.ListView"].prototype
    method(lv, "Add", lambda this, opts="", *f: _srv().call("lv_add", ctrl=this.cid, fields=_lv_fields(f)))
    method(lv, "Insert", lambda this, row, opts="", *f: _srv().call("lv_add", ctrl=this.cid, fields=_lv_fields(f)))
    method(lv, "Modify", lambda this, row, opts="", *f: _srv().call("lv_modify", ctrl=this.cid, row=rt().to_int(row),
                                                                     fields=_lv_fields(f)))
    method(lv, "Delete", lambda this, row=0: _srv().call("lv_delete", ctrl=this.cid, row=rt().to_int(row)))
    method(lv, "GetText", lambda this, row, col=1: _srv().call("lv_gettext", ctrl=this.cid, row=rt().to_int(row),
                                                               col=rt().to_int(col)))
    method(lv, "GetCount", lambda this, mode="": _srv().call("lv_count", ctrl=this.cid))
    method(lv, "GetNext", lambda this, start=0, mode="": _num(ctrl_get(this, "Value")) if
           _num(ctrl_get(this, "Value")) > rt().to_int(start) else 0)
    method(lv, "ModifyCol", lambda this, *a: 1)
    method(lv, "InsertCol", lambda this, *a: 1)
    method(lv, "DeleteCol", lambda this, *a: 1)
    method(lv, "SetImageList", lambda this, *a: 0)
    sb = CLASSES["Gui.StatusBar"].prototype
    method(sb, "SetText", lambda this, text, part=1, style=0: ctrl_set(this, "Text", S(text)) and 1)
    method(sb, "SetParts", lambda this, *a: 1)
    method(sb, "SetIcon", lambda this, *a: 1)


def _num(v):
    return v


def _gui_item(this, name):
    if isinstance(name, int):
        c = CTRLS.get(name)
        if c is not None and c.gui is this:
            return c
    c = this.names.get(S(name).lower())
    if c is None:
        throw("Error", "No such control.", S(name))
    return c


def _gui_enum(this, n):
    from .core import Enumerator

    def gen():
        for c in this.ctrls:
            yield (c.cid, c) if n > 1 else (c,)
    return Enumerator(gen(), n)


def _getpos(this, refs):
    from . import setref
    vals = _srv().call("getpos", win=this.wid)
    for ref, v in zip(refs, vals):
        setref(ref, v)
    return ""


def _ctrl_getpos(this, refs):
    from . import setref
    for ref, v in zip(refs, (this.x, this.y, this.w, this.h)):
        setref(ref, v)
    return ""


def _ctrl_move(this, x, y, w, h):
    kw = {}
    for k, v in (("x", x), ("y", y), ("w", w), ("h", h)):
        if v is not UNSET and v != "":
            kw[k] = rt().to_int(v)
            setattr(this, k, kw[k])
    _srv().call("move", ctrl=this.cid, **kw)
    return ""


def tooltip(n, text, x, y):
    from .input_ import backend
    if x is UNSET or y is UNSET:
        mx, my = backend().mouse_pos()
        x = mx + 16 if x is UNSET else rt().to_int(x)
        y = my + 16 if y is UNSET else rt().to_int(y)
    _srv().call("tooltip", n=n, text=text, x=int(x), y=int(y))


# ---------------------------------------------------------------- Menu (script_menu.cpp)
MENUS: dict[int, "MenuObj"] = {}
_menu_ids = itertools.count(1)


class MenuItem:
    __slots__ = ("name", "cb", "checked", "enabled", "builtin")

    def __init__(self, name, cb=None, builtin=None):
        self.name = name
        self.cb = cb
        self.checked = None        # None = not a check item
        self.enabled = True
        self.builtin = builtin     # python callable for standard tray items


class MenuObj(AhkObject):
    __slots__ = ("mid", "items", "default", "click_count", "on_change")

    def __init__(self, proto=None):
        super().__init__(proto or CLASSES["Menu"].prototype)
        self.mid = next(_menu_ids)
        self.items: list[MenuItem] = []
        self.default = ""
        self.click_count = 2
        self.on_change = None
        MENUS[self.mid] = self

    def find_item(self, name, required=True):
        if type(name) is int or (isinstance(name, str) and name.endswith("&") and name[:-1].isdigit()):
            i = int(str(name).rstrip("&")) - 1
            if 0 <= i < len(self.items):
                return self.items[i]
        else:
            key = S(name).replace("&", "").lower()
            for it in self.items:
                if it.name.replace("&", "").lower() == key:
                    return it
        if required:
            throw("Error", "Nonexistent menu item.", S(name))
        return None

    def changed(self):
        if self.on_change is not None:
            self.on_change()

    def wire(self):
        """Item list for the GTK side."""
        dflt = self.default.replace("&", "").lower()
        return [{"label": it.name, "checked": it.checked, "enabled": it.enabled,
                 "default": bool(dflt) and it.name.replace("&", "").lower() == dflt} for it in self.items]

    def activate(self, index):
        r = rt()
        if not (0 <= index < len(self.items)):
            return
        it = self.items[index]
        if it.builtin is not None:
            r.post(it.builtin)
        elif it.cb is not None:
            r.post(lambda: r.call(it.cb, [it.name, index + 1, self]))


def _menu_add(m, name=UNSET, cb=UNSET, opts="", before=None):
    if name is UNSET or S(name) == "":
        item = MenuItem("")
    else:
        existing = m.find_item(name, required=False)
        if existing is not None and before is None:
            if cb is not UNSET:
                existing.cb, existing.builtin = cb, None
            _menu_opts(existing, S(opts))
            m.changed()
            return ""
        if cb is UNSET:
            throw("Error", "Missing a required parameter.", S(name))
        item = MenuItem(S(name), cb)
        _menu_opts(item, S(opts))
    if before is not None:
        b = m.find_item(before)
        m.items.insert(m.items.index(b), item)
    else:
        m.items.append(item)
    m.changed()
    return ""


def _menu_opts(item, opts):
    for o in opts.split():
        ol = o.lower()
        if ol in ("+radio", "radio", "+check"):
            item.checked = bool(item.checked)


def _menu_delete(m, name=UNSET):
    if name is UNSET:
        m.items.clear()
        m.default = ""
    else:
        m.items.remove(m.find_item(name))
    m.changed()
    return ""


def _menu_set(m, name, attr, value):
    it = m.find_item(name)
    if value == "toggle":
        value = not bool(getattr(it, attr))
    setattr(it, attr, value)
    m.changed()
    return ""


def _menu_rename(m, old, new=""):
    it = m.find_item(old)
    if S(new) == "":
        it.name, it.cb, it.builtin = "", None, None
    else:
        it.name = S(new)
    m.changed()
    return ""


def _menu_set_default(m, v):
    m.default = "" if v == "" else (m.find_item(v).name if v is not UNSET else "")
    m.changed()
    return v


def _menu_set_clicks(m, v):
    m.click_count = 1 if rt().to_int(v) == 1 else 2
    m.changed()
    return v


def menu_setup():
    from ..classes import method, prop
    mp = CLASSES["Menu"].prototype
    if mp.own("Add") is not None:
        return
    CLASSES["Menu"].factory = lambda proto: MenuObj(proto)
    CLASSES["MenuBar"].factory = lambda proto: MenuObj(proto)
    method(mp, "Add", lambda this, name=UNSET, cb=UNSET, opts="": _menu_add(this, name, cb, opts))
    method(mp, "Insert", lambda this, before=UNSET, name=UNSET, cb=UNSET, opts="":
           _menu_add(this, name, cb, opts, before if before not in (UNSET, "") else None))
    method(mp, "Delete", lambda this, name=UNSET: _menu_delete(this, name))
    method(mp, "Rename", lambda this, old, new="": _menu_rename(this, old, new))
    method(mp, "Check", lambda this, name: _menu_set(this, name, "checked", True))
    method(mp, "Uncheck", lambda this, name: _menu_set(this, name, "checked", False))
    method(mp, "ToggleCheck", lambda this, name: _menu_set(this, name, "checked", "toggle"))
    method(mp, "Enable", lambda this, name: _menu_set(this, name, "enabled", True))
    method(mp, "Disable", lambda this, name: _menu_set(this, name, "enabled", False))
    method(mp, "ToggleEnable", lambda this, name: _menu_set(this, name, "enabled", "toggle"))
    method(mp, "SetIcon", lambda this, *a: "")
    method(mp, "SetColor", lambda this, *a: "")
    method(mp, "AddStandard", lambda this: _add_standard(this))
    method(mp, "Show", lambda this, x=UNSET, y=UNSET, wait=1:
           _srv().call("menu", menu=this.mid, items=[it.name for it in this.items]) and "")
    prop(mp, "Default", get=lambda this: this.default, set=lambda this, v: _menu_set_default(this, v))
    prop(mp, "ClickCount", get=lambda this: this.click_count, set=lambda this, v: _menu_set_clicks(this, v))
    prop(mp, "Handle", get=lambda this: this.mid)


def _add_standard(m):
    from . import tray
    tray.add_standard_items(m)
    m.changed()
    return ""


def tray_menu():
    from . import tray
    return tray.menu()
