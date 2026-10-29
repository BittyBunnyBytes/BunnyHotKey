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
                "picture": "Picture", "pic": "Picture", "link": "Link", "statusbar": "StatusBar", "tab": "Tab",
                "tab2": "Tab", "tab3": "Tab", "updown": "UpDown", "hotkey": "Hotkey", "datetime": "DateTime",
                "monthcal": "MonthCal", "treeview": "TreeView", "activex": "ActiveX", "custom": "Custom"}
CLASS_OF = {"Picture": "Pic", "Text": "Text", "Edit": "Edit", "Button": "Button", "CheckBox": "CheckBox",
            "Radio": "Radio", "DDL": "DDL", "ComboBox": "ComboBox", "ListBox": "ListBox", "ListView": "ListView",
            "Slider": "Slider", "Progress": "Progress", "GroupBox": "GroupBox", "Link": "Link",
            "StatusBar": "StatusBar", "Tab": "Tab", "UpDown": "UpDown", "Hotkey": "Hotkey", "DateTime": "DateTime",
            "MonthCal": "MonthCal", "TreeView": "TreeView"}
# Win32 window classes, for ClassNN ("Edit1", "Button2") and ahk_class-style lookups (script_gui.cpp)
WIN32_CLASS = {"Text": "Static", "Picture": "Static", "Edit": "Edit", "Button": "Button", "CheckBox": "Button",
               "Radio": "Button", "GroupBox": "Button", "DDL": "ComboBox", "ComboBox": "ComboBox",
               "ListBox": "ListBox", "ListView": "SysListView32", "Slider": "msctls_trackbar32",
               "Progress": "msctls_progress32", "Link": "SysLink", "StatusBar": "msctls_statusbar32",
               "Tab": "SysTabControl32", "UpDown": "msctls_updown32", "Hotkey": "msctls_hotkey32",
               "DateTime": "SysDateTimePick32", "MonthCal": "SysMonthCal32", "TreeView": "SysTreeView32"}
# the 16 HTML colour names AutoHotkey accepts (script_gui.cpp ColorNameToBGR)
COLOR_NAMES = {"black": "000000", "silver": "C0C0C0", "gray": "808080", "white": "FFFFFF", "maroon": "800000",
               "red": "FF0000", "purple": "800080", "fuchsia": "FF00FF", "green": "008000", "lime": "00FF00",
               "olive": "808000", "yellow": "FFFF00", "navy": "000080", "blue": "0000FF", "teal": "008080",
               "aqua": "00FFFF"}
MARGIN_X, MARGIN_Y = 10, 6
LINE_H = 18
TAB_HEADER = 26


def rt():
    return O.RT


def S(v):
    return O.RT.to_str(v)


def parse_color(s):
    """AutoHotkey colour (name, RRGGBB, 0xRRGGBB) -> '#rrggbb'; '' for Default; None if not a colour."""
    s = str(s).strip().lower()
    if s in ("", "default"):
        return ""
    if s in COLOR_NAMES:
        return "#" + COLOR_NAMES[s].lower()
    m = re.fullmatch(r"(?:0x)?([0-9a-f]{1,6})", s)
    return "#%06x" % int(m.group(1), 16) if m else None


def parse_font(opts, name, base=None):
    """Gui.SetFont options -> font dict (s12 w700 bold italic underline strike norm cRed q3)."""
    f = dict(base or {})
    for tok in S(opts).split():
        t = tok.lower()
        if t == "norm":
            f = {k: v for k, v in f.items() if k in ("name", "size", "color")}
            f.pop("weight", None)
        elif t == "bold":
            f["weight"] = 700
        elif t in ("italic", "underline", "strike"):
            f[t] = True
        elif re.fullmatch(r"s\d+(\.\d+)?", t):
            f["size"] = float(t[1:]) if "." in t else int(t[1:])
        elif re.fullmatch(r"w\d+", t):
            f["weight"] = int(t[1:])
        elif t.startswith("c") and parse_color(t[1:]) is not None:
            f["color"] = parse_color(t[1:])
    if name is not UNSET and S(name) != "":
        f["name"] = S(name)
    return f


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
                 "destroyed", "names", "xid", "font", "bg", "tab", "tab_counts", "menubar", "lastfound", "ctl_color",
                 "dpi_scale", "owner")

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
        self.font = {}
        self.bg = ""
        self.ctl_color = ""
        self.tab = None              # (Tab control, page) that new controls go into
        self.tab_counts = {}
        self.menubar = None
        self.lastfound = False
        self.dpi_scale = True
        self.owner = None


class CtrlObj(AhkObject):
    __slots__ = ("cid", "gui", "ctype", "name", "events", "x", "y", "w", "h", "rows", "altsubmit", "group",
                 "enabled", "visible", "tab", "buddy", "multi", "readonly", "password", "sized", "font",
                 "dtformat", "imagelist", "color", "bg", "header")

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
        self.enabled = True
        self.visible = True
        self.tab = None
        self.buddy = None
        self.multi = False
        self.readonly = False
        self.password = False
        self.sized = (False, False)
        self.font = None
        self.dtformat = ""
        self.imagelist = {}
        self.color = ""
        self.bg = ""
        self.header = TAB_HEADER


def _srv():
    return Server.get()


def _live(this):
    if this.destroyed:
        throw("Error", "Gui has no window.")


def gui_new(this, options="", title=UNSET, event_obj=UNSET):
    this.wid = next(_win_ids)
    this.title = S(title) if title is not UNSET else rt().bivars["a_scriptname"][0]()
    this.event_obj = event_obj if event_obj is not UNSET else None
    this.xid = _srv().call("new", win=this.wid, title=this.title, resize=False) or 0
    GUIS[this.wid] = this
    if this.xid:
        from .ipc import claim_window
        claim_window(this.xid)
    rt().gui_count = getattr(rt(), "gui_count", 0) + 1
    if S(options):
        gui_opt(this, options)
    return ""


def gui_opt(this, options):
    """Gui.Opt / Gui() options (script_gui.cpp GuiType::ParseOptions)."""
    _live(this)
    kw = {}
    for tok in S(options).split():
        t = tok.lower()
        on = not t.startswith("-")
        t = t.lstrip("+-")
        if t == "alwaysontop":
            kw["ontop"] = on
        elif t == "caption":
            kw["caption"] = on
        elif t == "border":
            kw["border"] = on
        elif t == "toolwindow":
            kw["toolwindow"] = on
        elif t == "resize":
            kw["resize"] = on
        elif t == "sysmenu":
            kw["sysmenu"] = on
        elif t == "disabled":
            kw["disabled"] = on
        elif t == "lastfound":
            this.lastfound = True
            if this.xid:
                rt().thread.settings.last_found = this.xid
        elif t.startswith("owner"):
            rest = tok.lstrip("+-")[5:]
            owner = None
            if on:
                h = rt().to_int(rest) if rest else 0
                owner = next((g for g in GUIS.values() if h and (g.xid == h or g.wid == h)), None)
            this.owner = owner
            kw["owner"] = owner.wid if owner else 0
        elif t.startswith("minsize") or t.startswith("maxsize"):
            m = re.fullmatch(r"(\d*)x?(\d*)", t[7:])
            w, h = (int(m.group(1) or 0), int(m.group(2) or 0)) if m else (0, 0)
            if not w and not h:
                pos = _srv().call("getpos", win=this.wid, client=True)
                w, h = pos[2], pos[3]
            kw[t[:7]] = [w, h] if on else None
        elif t.startswith("background"):
            c = parse_color(tok.lstrip("+-")[10:])
            if c is not None:
                this.bg = c if on else ""
                kw["bg"] = this.bg
        elif t == "dpiscale":
            this.dpi_scale = on
        elif t.startswith("label") or t in ("minimizebox", "maximizebox", "theme", "parent") or t.startswith("e0x") \
                or t.startswith("0x") or t.startswith("delimiter") or t == "owndialogs":
            pass          # no X11 equivalent; accepted as AutoHotkey does
    if kw:
        _srv().call("gopt", win=this.wid, **kw)
    return ""


def gui_setfont(this, opts="", name=UNSET):
    this.font = parse_font(opts, name, this.font if "norm" not in S(opts).lower().split() else {})
    return ""


def _flag_color(flags, key, raw):
    c = parse_color(raw)
    if c is not None:
        flags[key] = c
        return True
    return False


def _parse_pos(gui, opts, ctype=""):
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
        m = re.fullmatch(r"r(\d+(?:\.\d+)?)", tl)
        if m:
            rows = float(m.group(1))
            continue
        if tl.startswith("v") and len(tok) > 1 and not tl.startswith("vertical") and not tl.startswith("vscroll"):
            flags["name"] = tok[1:]
            continue
        neg = tl.startswith("-")
        word = tl.lstrip("+-")
        m = re.fullmatch(r"choose(.+)", word)
        if m and not neg:
            if ctype in ("DateTime", "MonthCal"):
                if m.group(1) == "none":
                    flags["choosenone"] = True
                else:
                    flags["choosedt"] = m.group(1)
            elif m.group(1).isdigit():
                flags["choose"] = int(m.group(1))
            continue
        m = re.fullmatch(r"range(-?\d+)-(-?\d+)", word)
        if m:
            if ctype in ("DateTime", "MonthCal"):
                flags["dtrange"] = [m.group(1), m.group(2)]
            else:
                flags["range"] = [int(m.group(1)), int(m.group(2))]
            continue
        m = re.fullmatch(r"range(\d*)-(\d*)", word)
        if m and ctype in ("DateTime", "MonthCal"):
            flags["dtrange"] = [m.group(1) or None, m.group(2) or None]
            continue
        m = re.fullmatch(r"checked(-?\d)?", word)
        if m:
            flags["checked"] = False if neg else (int(m.group(1)) if m.group(1) else True)
            if flags["checked"] == 0:
                flags["checked"] = False
            continue
        m = re.fullmatch(r"(limit|line|page|tickinterval|thick)(\d*)", word)
        if m:
            flags[m.group(1)] = int(m.group(2)) if m.group(2) else (not neg)
            continue
        if word.startswith("background") and not neg:
            _flag_color(flags, "bg", word[10:])
            continue
        if word.startswith("c") and len(word) > 1 and word not in ("center", "checked", "check3", "case") \
                and not word.startswith(("choose", "choosenone")) and _flag_color(flags, "color", word[1:]):
            continue
        if word == "hdr":
            flags["hdr_off"] = neg
            continue
        if word in ("section", "hidden", "disabled", "default", "readonly", "password", "multi", "center", "right",
                    "left", "group", "wrap", "vertical", "invert", "tooltip", "number", "lowercase", "uppercase",
                    "grid", "nosort", "nosorthdr", "lines", "buttons", "wanttab", "wantreturn", "check3", "vscroll",
                    "hscroll", "smooth", "altsubmit", "notab", "border", "sort", "16", "0x80", "8"):
            flags[word] = not neg
            if word == "check3" and not neg:
                flags["check3"] = True
        elif word.startswith("password"):
            flags["password"] = not neg
    if x is None and y is None:
        x = prev.x if prev is not None else gui.mx
        y = py + ph + gui.my if prev is not None else gui.my
    elif x is None:
        x = (px + pw + gui.mx) if prev is not None else gui.mx
    elif y is None:
        y = py if prev is not None and x != gui.mx else (py + ph + gui.my if prev else gui.my)
    if rows and h is None:
        h = int(rows * LINE_H + 8)
    return x, y, w, h, flags


def _has_pos(opts):
    return re.search(r"(?:^|\s)\+?[xy](?:m|p|s|\+|-)?-?\d*(?=\s|$)", opts.lower()) is not None and \
        re.search(r"(?:^|\s)\+?[xy](?:m|p|s|[+-]\d|\d)", opts.lower()) is not None


def gui_add(this, ctype, options="", text=UNSET):
    t = TYPE_ALIASES.get(S(ctype).lower())
    if t is None:
        throw("ValueError", "Invalid control type.", S(ctype))
    if t in ("ActiveX", "Custom"):
        throw("Error", f"{t} controls host Win32/COM components, which don't exist on Linux "
                       "(not supported by Bunny Hot Key).", S(ctype))
    _live(this)
    opts = S(options)
    # the first control on a tab page goes inside the tab's display area (script_gui.cpp GuiType::AddControl)
    tab = this.tab
    if tab is not None and t != "Tab" and not _has_pos(opts) and this.tab_counts.get((tab[0].cid, tab[1]), 0) == 0:
        opts = f"x{tab[0].x + this.mx} y{tab[0].y + tab[0].header + this.my} " + opts
    x, y, w, h, flags = _parse_pos(this, opts, t)
    ctrl = CtrlObj(this, t)
    send = {"x": x, "y": y, "w": w, "h": h}
    ctrl.sized = (w is not None, h is not None)
    items = []
    if isinstance(text, AhkArray):
        items = [S(i) for i in text.items]
        txt = ""
    else:
        txt = S(text) if text is not UNSET else ""
    if t == "ListView":
        send["columns"] = items or txt.split("|")
        items = []
    if t in ("DDL", "ComboBox", "ListBox", "Tab") and not items and txt:
        items = txt.split("|")
        txt = ""
    passthru = {k: v for k, v in flags.items() if k not in ("name", "altsubmit", "section")}
    send.update(text=txt, items=items, **passthru)
    ctrl.altsubmit = bool(flags.get("altsubmit"))
    ctrl.readonly = bool(flags.get("readonly"))
    ctrl.password = bool(flags.get("password"))
    ctrl.multi = bool(flags.get("multi") or flags.get("8")) and t == "ListBox"
    ctrl.enabled = not flags.get("disabled")
    ctrl.visible = not flags.get("hidden")
    if this.font:
        send["font"] = {k: v for k, v in this.font.items() if k != "color" or t != "StatusBar"}
        ctrl.font = dict(this.font)
    color = flags.get("color", this.font.get("color") if this.font and t != "StatusBar" else None)
    if color:
        send["color"] = color
        ctrl.color = color
    if "bg" in flags:
        ctrl.bg = flags["bg"]
    if tab is not None and t != "Tab":
        send["tab"] = [tab[0].cid, tab[1]]
        ctrl.tab = tab
        this.tab_counts[(tab[0].cid, tab[1])] = this.tab_counts.get((tab[0].cid, tab[1]), 0) + 1
    if t == "Radio":
        prev_radio = this.prev is not None and this.prev.ctype == "Radio"
        ctrl.group = this.prev.group if prev_radio and not flags.get("group") else ctrl.cid
        send["follows_radio"] = prev_radio
    if t == "Edit" and (flags.get("multi") or (rows_of(opts) or 1) > 1 or (h and h > 30)):
        send["multi"] = True
        if h is None:
            send["h"] = (int(rows_of(opts)) if rows_of(opts) else 3) * LINE_H + 8
    if t in ("ListBox", "ListView", "TreeView") and h is None:
        send["h"] = 5 * LINE_H + 8 if t == "ListBox" else 10 * LINE_H
    if t in ("Edit", "Hotkey", "DateTime") and w is None:
        send["w"] = 120 if t == "Edit" else (200 if t == "DateTime" else 140)
    if t in ("ListView", "TreeView") and w is None:
        send["w"] = 200
    if t == "Tab" and w is None:
        send["w"] = 200 + 2 * this.mx
    if t == "Tab" and h is None:
        send["h"] = 100 + TAB_HEADER
    if t == "UpDown":
        buddy = this.prev if this.prev is not None and this.prev.ctype == "Edit" and not flags.get("16") else None
        if buddy is not None:
            send["buddy"] = buddy.cid
            ctrl.buddy = buddy
            send.update(x=buddy.x, y=buddy.y, w=buddy.w, h=buddy.h)
            x, y, w, h = buddy.x, buddy.y, buddy.w, buddy.h
    if t == "DateTime":
        ctrl.dtformat = txt
    if t == "Picture" and re.match(r"\s*(?:hbitmap|hicon):", txt, re.I):
        from .gui import picture_path
        send["text"] = picture_path(txt)
    pref = _srv().call("add", win=this.wid, ctrl=ctrl.cid, type=t, opts=send)
    ctrl.x, ctrl.y = x, y
    ctrl.w = send.get("w") or pref["w"]
    ctrl.h = send.get("h") or pref["h"]
    if ctrl.buddy is not None:
        ctrl.w, ctrl.h = ctrl.buddy.w, ctrl.buddy.h
    if t == "Tab":
        ctrl.header = pref.get("header", TAB_HEADER)
    if t == "StatusBar":
        ctrl.x, ctrl.y, ctrl.w = 0, 0, 0
    if ctrl.bg:
        _srv().call("style", ctrl=ctrl.cid, bg=ctrl.bg)
    if flags.get("section"):
        this.section = (x, y)
    if "name" in flags:
        ctrl.name = flags["name"]
        this.names[ctrl.name.lower()] = ctrl
    this.ctrls.append(ctrl)
    if (t != "UpDown" or ctrl.buddy is None) and t != "StatusBar":
        this.prev = ctrl
    CTRLS[ctrl.cid] = ctrl
    if t == "Tab":
        this.tab = (ctrl, 1)      # later controls go on the first page until UseTab()
    return ctrl


def rows_of(opts):
    m = re.search(r"(?:^|\s)r(\d+(?:\.\d+)?)(?=\s|$)", opts.lower())
    return float(m.group(1)) if m else 0


def _fit_tab(tab):
    """A Tab without an explicit size grows to hold its controls (Tab3 behaviour)."""
    kids = [c for c in tab.gui.ctrls if c.tab is not None and c.tab[0] is tab]
    if not kids:
        return
    kw = {}
    if not tab.sized[0]:
        tab.w = max(c.x + c.w for c in kids) + tab.gui.mx - tab.x
        kw["w"] = tab.w
    if not tab.sized[1]:
        tab.h = max(c.y + c.h for c in kids) + tab.gui.my - tab.y
        kw["h"] = tab.h
    if kw:
        _srv().call("move", ctrl=tab.cid, **kw)


def tab_usetab(this, value=0, exact=0):
    g = this.gui
    if value is UNSET or value == "" or value == 0:
        if g.tab is not None:
            _fit_tab(g.tab[0])
            g.prev = g.tab[0]
        g.tab = None
        return ""
    if isinstance(value, str) and not value.lstrip("-").isdigit():
        items = _srv().call("query", ctrl=this.cid, what="items")
        v = value.lower()
        idx = next((i for i, it in enumerate(items, 1)
                    if it.replace("&", "").lower() == v or (not to_bool(exact) and it.lower().startswith(v))), 0)
        if not idx:
            throw("ValueError", "Parameter #1 of Gui.Tab.Prototype.UseTab is invalid.", value)
    else:
        idx = rt().to_int(value)
    g.tab = (this, idx)
    return ""


def gui_show(this, options=""):
    _live(this)
    o = S(options).lower()
    words = o.split()
    for c in this.ctrls:
        if c.ctype == "Tab":
            _fit_tab(c)
    kw = {}
    for k in ("w", "h", "x", "y"):
        m = re.search(r"(?:^|\s)" + k + r"(-?\d+)", o)
        if m:
            kw[k] = int(m.group(1))
    auto = "autosize" in words or not this.shown
    laid = [c for c in this.ctrls if c.ctype != "StatusBar"]
    if "w" not in kw and laid and auto:
        kw["w"] = max(c.x + c.w for c in laid) + this.mx
    if "h" not in kw and laid and auto:
        kw["h"] = max(c.y + c.h for c in laid) + this.my
    if "hide" in words:
        return ""
    state = "min" if "minimize" in words else "max" if "maximize" in words else None
    center = "xcenter" in words or "ycenter" in words or "center" in words or ("x" not in kw and "y" not in kw
                                                                              and not this.shown)
    _srv().call("show", win=this.wid, center=center, state=state,
                activate=not ({"na", "noactivate", "minimize"} & set(words)), **kw)
    this.shown = True
    if this.xid:
        # wait (briefly) until the window manager lists the window, so Win* functions can find it
        from .window import _dpy, client_list
        import time
        d = _dpy()
        end = time.monotonic() + 1.0
        while d is not None and this.xid not in client_list(d) and time.monotonic() < end:
            time.sleep(0.02)
        if this.lastfound:
            rt().thread.settings.last_found = this.xid
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
        elif c.ctype in ("DDL", "ComboBox", "ListBox", "Tab") and not c.altsubmit:
            out.define_value(c.name, _wrap(ctrl_get(c, "Text")))
        elif c.ctype in ("ListView", "TreeView", "StatusBar", "Text", "Link", "GroupBox", "Button", "Progress",
                         "Picture"):          # TYPE_NO_SUBMIT in script_gui.cpp
            continue
        else:
            out.define_value(c.name, _wrap(ctrl_get(c, "Value")))
    if to_bool(hide):
        gui_hide(this)
    return out


def gui_hide(this):
    _live(this)
    _srv().call("hide", win=this.wid)
    this.shown = False
    return ""


def gui_destroy(this):
    if not this.destroyed:
        _srv().call("destroy", win=this.wid)
        this.destroyed = True
        GUIS.pop(this.wid, None)
        for c in this.ctrls:
            CTRLS.pop(c.cid, None)
        rt().gui_count = max(getattr(rt(), "gui_count", 1) - 1, 0)
    return ""


def gui_move(this, x=UNSET, y=UNSET, w=UNSET, h=UNSET):
    _live(this)
    kw = {k: rt().to_int(v) for k, v in (("x", x), ("y", y), ("w", w), ("h", h)) if v is not UNSET and v != ""}
    _srv().call("wmove", win=this.wid, **kw)
    return ""


def gui_state(this, state):
    _live(this)
    if state != "flash":
        this.shown = True
    _srv().call("wstate", win=this.wid, state=state)
    return ""


def _on_event(target, name, cb, add=1):
    if isinstance(target, GuiObj) and S(name).lower() == "dropfiles" and not target.destroyed:
        _srv().call("dropfiles", win=target.wid)     # the window accepts files once a DropFiles handler exists
    lst = target.events.setdefault(S(name).lower(), [])
    a = rt().to_int(add) if add is not UNSET else 1
    if cb in lst:
        lst.remove(cb)
    if a > 0:
        lst.append(cb)
    elif a < 0:
        lst.insert(0, cb)
    return ""


def _wrap(v):
    """Lists from the GTK side (multi-select ListBox) become Arrays."""
    if isinstance(v, list):
        return AhkArray(None, list(v))
    return v


def ctrl_get(c, prop):
    if c.gui.destroyed:
        throw("Error", "The control is destroyed.")
    return _wrap(_srv().call("get", ctrl=c.cid, prop=prop))


def ctrl_set(c, prop, v):
    if isinstance(v, AhkObject):
        throw("TypeError", O.type_error_msg("String", v))
    if c.gui.destroyed:
        throw("Error", "The control is destroyed.")
    if prop == "Value" and c.ctype in ("Text", "Link", "Button", "GroupBox", "StatusBar", "Edit", "ComboBox",
                                       "DateTime", "Hotkey", "Picture"):
        v = S(v)
        if c.ctype == "Picture":
            from .gui import picture_path
            v = picture_path(v)
    if prop == "Value" and c.ctype in ("DDL", "ListBox", "Tab", "Slider", "Progress", "UpDown", "CheckBox",
                                       "Radio") and not isinstance(v, (int, float)):
        v = rt().to_int(v) if S(v).strip().lstrip("-").isdigit() else v
    _srv().call("set", ctrl=c.cid, prop=prop, value=v)
    return v


def _b(v):
    return v if isinstance(v, bool) else bool(to_bool(v))


def ctrl_set_enabled(c, v):
    c.enabled = _b(v)
    _srv().call("set", ctrl=c.cid, prop="Enabled", value=int(c.enabled))
    if c.buddy is not None:
        c.buddy.enabled = c.enabled
    return v


def ctrl_set_visible(c, v):
    c.visible = _b(v)
    _srv().call("set", ctrl=c.cid, prop="Visible", value=int(c.visible))
    return v


def ctrl_opt(c, options):
    """Gui.Control.Opt: +/-Disabled, +/-Hidden, +/-ReadOnly, cColor, BackgroundColor, +/-Default, etc."""
    style = {}
    for tok in S(options).split():
        t = tok.lower()
        on = not t.startswith("-")
        t = t.lstrip("+-")
        if t == "disabled":
            ctrl_set_enabled(c, not on)
        elif t == "hidden":
            ctrl_set_visible(c, not on)
        elif t == "readonly":
            c.readonly = on
            _srv().call("set", ctrl=c.cid, prop="ReadOnly", value=int(on))
        elif t.startswith("background"):
            col = parse_color(t[10:]) if on else ""
            if col is not None:
                c.bg = col
                style["bg"] = col
        elif t.startswith("c") and parse_color(t[1:]) is not None and t not in ("center", "checked"):
            c.color = parse_color(t[1:])
            style["color"] = c.color
        elif t.startswith("v") and len(t) > 1:
            c.gui.names.pop(c.name.lower(), None)
            c.name = tok.lstrip("+-")[1:]
            c.gui.names[c.name.lower()] = c
        elif t == "altsubmit":
            c.altsubmit = on
        elif t.startswith("range") and c.ctype in ("Slider", "Progress", "UpDown"):
            pass
    if style:
        _srv().call("style", ctrl=c.cid, **style)
    return ""


def ctrl_setfont(c, opts="", name=UNSET):
    c.font = parse_font(opts, name, c.font or c.gui.font)
    _srv().call("style", ctrl=c.cid, font=c.font)
    return ""


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
    if ev == "MenuClosed":
        return
    if ev in ("TrayItem", "TrayDefault"):
        from . import tray
        tray.on_event(msg)
        return
    if ev == "ContextMenu":
        g = GUIS.get(msg.get("win"))
        c = CTRLS.get(msg.get("ctrl", 0))
        if g is None:
            return
        target = c if c is not None and c.events.get("contextmenu") else g
        cbs = list(target.events.get("contextmenu", []))
        item, right, x, y = (msg.get("args", []) + [0, 1, 0, 0])[:4]
        for cb in cbs:
            fn = _resolve_cb(g, cb)
            if target is g:      # ContextMenu(GuiObj, GuiCtrlObj, Item, IsRightClick, X, Y)
                r.post(lambda fn=fn: fn([g, c if c is not None else "", item, right, x, y]))
            else:                # ContextMenu(GuiCtrlObj, Item, IsRightClick, X, Y)
                r.post(lambda fn=fn: fn([c, item, right, x, y]))
        return
    if ev == "DropFiles":
        g = GUIS.get(msg.get("win"))
        if g is None:
            return
        files = AhkArray(None, list(msg.get("files", [])))
        for cb in list(g.events.get("dropfiles", [])):
            fn = _resolve_cb(g, cb)
            r.post(lambda fn=fn: fn([g, "", files, msg.get("x", 0), msg.get("y", 0)]))
        return
    if "ctrl" in msg:
        c = CTRLS.get(msg["ctrl"])
        if c is None:
            return
        cbs = list(c.events.get(ev.lower(), []))
        if not cbs:
            return
        args = msg.get("args", [msg.get("row", 0)])
        if c.ctype == "Link" and ev == "Click":
            args = [args[0] if args and args[0] != 0 else "", args[0] if args else ""]
        for cb in cbs:
            fn = _resolve_cb(c.gui, cb)
            r.post(lambda fn=fn: fn([c, *args]))
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
            r.post(lambda fn=fn: fn([g, msg.get("state", 0), msg["w"], msg["h"]]))
        return
    for cb in cbs:
        fn = _resolve_cb(g, cb)
        r.post(lambda fn=fn: fn([g]))


def _lv_fields(args):
    return [S(a) for a in args]


def _lv(this, do, **kw):
    return _srv().call("lv", ctrl=this.cid, do=do, **kw)


def _tv(this, do, **kw):
    return _srv().call("tv", ctrl=this.cid, do=do, **kw)


def _opt_str(v):
    return S(v) if v is not UNSET else ""


def _list_delete(this, n=UNSET):
    if n is UNSET or n == "":
        _srv().call("items", ctrl=this.cid, clear=True)
    else:
        i = rt().to_int(n)
        count = len(_srv().call("query", ctrl=this.cid, what="items"))
        if not 1 <= i <= count:
            throw("ValueError", "Parameter #1 of Gui.List.Prototype.Delete is invalid.", n)
        _srv().call("items", ctrl=this.cid, delete=i)
    return ""


def _list_choose(this, v):
    if isinstance(v, (int, float)) or S(v).strip().isdigit():
        i = rt().to_int(v)
        count = len(_srv().call("query", ctrl=this.cid, what="items"))
        if not 0 <= i <= count:
            throw("ValueError", "Parameter #1 of Gui.List.Prototype.Choose is invalid.", v)
        ctrl_set(this, "Value", i)
    else:
        try:
            _srv().call("set", ctrl=this.cid, prop="Text", value=S(v))
        except Exception:
            throw("ValueError", "Parameter #1 of Gui.List.Prototype.Choose is invalid.", S(v))
    return ""


def _lv_getnext(this, start=0, mode=""):
    return _lv(this, "getnext", start=rt().to_int(start) if start not in (UNSET, "") else 0, mode=_opt_str(mode))


def _lv_gettext(this, row, col=1):
    v = _lv(this, "gettext", row=rt().to_int(row), col=rt().to_int(col) if col is not UNSET else 1)
    if v is None:
        throw("ValueError", "Parameter #1 of Gui.ListView.Prototype.GetText is invalid.", row)
    return v


def _lv_setimagelist(this, il, which=0):
    from .gui import ILS
    h = rt().to_int(il)
    lst = ILS.get(h)
    w = rt().to_int(which) if which not in (UNSET, "") else 0
    large = (lst["large"] if lst else False) if w == 0 else w == 1
    key = 1 if large else 2
    old = this.imagelist.get(key, 0)
    this.imagelist[key] = h
    if lst is not None:
        _srv().call("icons", ctrl=this.cid, paths=list(lst["items"]), large=large and this.ctype == "ListView")
    return old


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
                     ("AddPic", "Picture"), ("AddLink", "Link"), ("AddStatusBar", "StatusBar"), ("AddTab", "Tab"),
                     ("AddTab2", "Tab"), ("AddTab3", "Tab"), ("AddUpDown", "UpDown"), ("AddHotkey", "Hotkey"),
                     ("AddDateTime", "DateTime"), ("AddMonthCal", "MonthCal"), ("AddTreeView", "TreeView"),
                     ("AddActiveX", "ActiveX"), ("AddCustom", "Custom")):
        method(gp, alias, lambda this, opts="", text=UNSET, t=t: gui_add(this, t, opts, text))
    method(gp, "Show", lambda this, opts="": gui_show(this, opts))
    method(gp, "Hide", lambda this: gui_hide(this))
    method(gp, "Destroy", lambda this: gui_destroy(this))
    method(gp, "Submit", lambda this, hide=1: gui_submit(this, hide))
    method(gp, "OnEvent", lambda this, name, cb, add=1: _on_event(this, name, cb, add))
    method(gp, "SetFont", lambda this, opts="", name=UNSET: gui_setfont(this, opts, name))
    method(gp, "Opt", lambda this, o: gui_opt(this, o))
    method(gp, "Flash", lambda this, blink=1: gui_state(this, "flash"))
    method(gp, "Minimize", lambda this: gui_state(this, "min"))
    method(gp, "Maximize", lambda this: gui_state(this, "max"))
    method(gp, "Restore", lambda this: gui_state(this, "restore"))
    method(gp, "Move", lambda this, x=UNSET, y=UNSET, w=UNSET, h=UNSET: gui_move(this, x, y, w, h))
    method(gp, "GetPos", lambda this, *refs: _getpos(this, refs, False))
    method(gp, "GetClientPos", lambda this, *refs: _getpos(this, refs, True))
    method(gp, "__Enum", lambda this, n=1: _gui_enum(this, n))
    method(gp, "__Delete", lambda this: "")
    prop(gp, "Title", get=lambda this: this.title, set=lambda this, v: (_srv().call("title", win=this.wid, value=S(v)),
                                                                          setattr(this, "title", S(v)), v)[-1])
    prop(gp, "Hwnd", get=lambda this: this.xid or this.wid)
    prop(gp, "MarginX", get=lambda this: this.mx, set=lambda this, v: setattr(this, "mx", rt().to_int(v)))
    prop(gp, "MarginY", get=lambda this: this.my, set=lambda this, v: setattr(this, "my", rt().to_int(v)))
    prop(gp, "BackColor", get=lambda this: this.bg[1:].upper() if this.bg else "",
         set=lambda this, v: (gui_opt(this, "+Background" + (S(v) or "Default")), v)[-1])
    prop(gp, "FocusedCtrl", get=lambda this: CTRLS.get(_srv().call("focused", win=this.wid) or 0, ""))
    prop(gp, "MenuBar", get=lambda this: this.menubar or "", set=lambda this, v: set_menubar(this, v))
    prop(gp, "Name", get=lambda this: getattr(this, "_name", ""), set=lambda this, v: v)
    prop(gp, "__Item", get=lambda this, name: _gui_item(this, name))

    cp = CLASSES["Gui.Control"].prototype
    prop(cp, "Value", get=lambda this: _num(ctrl_get(this, "Value")), set=lambda this, v: ctrl_set(this, "Value", v))
    prop(cp, "Text", get=lambda this: ctrl_get(this, "Text"), set=lambda this, v: ctrl_set(this, "Text", S(v)))
    prop(cp, "Enabled", get=lambda this: int(this.enabled), set=lambda this, v: ctrl_set_enabled(this, v))
    prop(cp, "Visible", get=lambda this: int(this.visible), set=lambda this, v: ctrl_set_visible(this, v))
    prop(cp, "Focused", get=lambda this: _srv().call("query", ctrl=this.cid, what="focused"))
    prop(cp, "Name", get=lambda this: this.name, set=lambda this, v: setattr(this, "name", S(v)))
    prop(cp, "Hwnd", get=lambda this: this.cid)
    prop(cp, "Gui", get=lambda this: this.gui)
    prop(cp, "Type", get=lambda this: this.ctype)
    prop(cp, "ClassNN", get=lambda this: classnn(this))
    method(cp, "OnEvent", lambda this, name, cb, add=1: _on_event(this, name, cb, add))
    method(cp, "OnNotify", lambda this, *a: "")
    method(cp, "OnCommand", lambda this, *a: "")
    method(cp, "Focus", lambda this: _srv().call("focus", ctrl=this.cid) and "")
    method(cp, "Move", lambda this, x=UNSET, y=UNSET, w=UNSET, h=UNSET: _ctrl_move(this, x, y, w, h))
    method(cp, "GetPos", lambda this, *refs: _ctrl_getpos(this, refs))
    method(cp, "Opt", lambda this, o: ctrl_opt(this, o))
    method(cp, "SetFont", lambda this, opts="", name=UNSET: ctrl_setfont(this, opts, name))
    method(cp, "Redraw", lambda this: "")
    lp = CLASSES["Gui.List"].prototype
    method(lp, "Add", lambda this, items: _srv().call("items", ctrl=this.cid, add=[S(i) for i in items.items]) and "")
    method(lp, "Delete", lambda this, n=UNSET: _list_delete(this, n))
    method(lp, "Choose", lambda this, v: _list_choose(this, v))
    tb = CLASSES["Gui.Tab"].prototype
    method(tb, "UseTab", lambda this, v=0, exact=0: tab_usetab(this, v, exact))
    lv = CLASSES["Gui.ListView"].prototype
    method(lv, "Add", lambda this, opts="", *f: _lv(this, "add", opts=_opt_str(opts), fields=_lv_fields(f)))
    method(lv, "Insert", lambda this, row, opts="", *f: _lv(this, "insert", row=rt().to_int(row), opts=_opt_str(opts),
                                                            fields=_lv_fields(f)))
    method(lv, "Modify", lambda this, row, opts="", *f: _lv(this, "modify", row=rt().to_int(row), opts=_opt_str(opts),
                                                            fields=_lv_fields(f)))
    method(lv, "Delete", lambda this, row=0: _lv(this, "delete", row=rt().to_int(row) if row not in (UNSET, "") else 0))
    method(lv, "GetText", lambda this, row, col=1: _lv_gettext(this, row, col))
    method(lv, "GetCount", lambda this, mode="": _lv(this, "count", mode=_opt_str(mode)))
    method(lv, "GetNext", lambda this, start=0, mode="": _lv_getnext(this, start, mode))
    method(lv, "ModifyCol", lambda this, col=0, opts="", title=UNSET: _lv(
        this, "modifycol", col=rt().to_int(col) if col not in (UNSET, "") else 0, opts=_opt_str(opts),
        title=S(title) if title is not UNSET else None))
    method(lv, "InsertCol", lambda this, col=0, opts="", title="": _lv(
        this, "insertcol", col=rt().to_int(col) if col not in (UNSET, "") else 0, opts=_opt_str(opts),
        title=S(title) if title is not UNSET else ""))
    method(lv, "DeleteCol", lambda this, col: _lv(this, "deletecol", col=rt().to_int(col)))
    method(lv, "SetImageList", lambda this, il, which=0: _lv_setimagelist(this, il, which))
    tv = CLASSES["Gui.TreeView"].prototype
    method(tv, "Add", lambda this, name, parent=0, opts="": _tv(
        this, "add", name=S(name), parent=rt().to_int(parent) if parent not in (UNSET, "") else 0, opts=_opt_str(opts)))
    method(tv, "Modify", lambda this, item, opts=UNSET, name=UNSET: _tv(
        this, "modify", item=rt().to_int(item), opts=S(opts) if opts is not UNSET else None,
        name=S(name) if name is not UNSET else None))
    method(tv, "Delete", lambda this, item=0: _tv(this, "delete", item=rt().to_int(item) if item not in (UNSET, "")
                                                  else 0) and "")
    method(tv, "GetSelection", lambda this: _tv(this, "selection"))
    method(tv, "GetCount", lambda this: _tv(this, "count"))
    method(tv, "GetParent", lambda this, item: _tv(this, "parent", item=rt().to_int(item)))
    method(tv, "GetChild", lambda this, item: _tv(this, "child", item=rt().to_int(item)))
    method(tv, "GetPrev", lambda this, item: _tv(this, "prev", item=rt().to_int(item)))
    method(tv, "GetNext", lambda this, item=0, mode="": _tv(this, "next", item=rt().to_int(item) if item not in
                                                            (UNSET, "") else 0, mode=_opt_str(mode)))
    method(tv, "GetText", lambda this, item: _tv_gettext(this, item))
    method(tv, "Get", lambda this, item, attr: _tv(this, "get", item=rt().to_int(item), attr=S(attr)))
    method(tv, "SetImageList", lambda this, il, which=0: _lv_setimagelist(this, il, which))
    dtp = CLASSES["Gui.DateTime"].prototype
    method(dtp, "SetFormat", lambda this, fmt="": (setattr(this, "dtformat", S(fmt)),
                                                   _srv().call("set", ctrl=this.cid, prop="Text", value=S(fmt)), "")[-1])
    sb = CLASSES["Gui.StatusBar"].prototype
    method(sb, "SetText", lambda this, text, part=1, style=0: _sb_settext(this, text, part))
    method(sb, "SetParts", lambda this, *widths: _sb_setparts(this, widths))
    method(sb, "SetIcon", lambda this, *a: 1)


def _tv_gettext(this, item):
    v = _tv(this, "gettext", item=rt().to_int(item))
    if v is None:
        throw("ValueError", "Parameter #1 of Gui.TreeView.Prototype.GetText is invalid.", item)
    return v


# StatusBar parts: kept script-side and joined with tabs in one label (GTK has no multi-part status bar)
_SB_PARTS: dict[int, list] = {}


def _sb_parts(this):
    if this.cid not in _SB_PARTS:
        _SB_PARTS[this.cid] = [ctrl_get(this, "Text")]
    return _SB_PARTS[this.cid]


def _sb_settext(this, text, part=1):
    parts = _sb_parts(this)
    i = rt().to_int(part) if part not in (UNSET, "") else 1
    if not 1 <= i <= max(len(parts), 1):
        return 0
    parts[i - 1] = S(text)
    _srv().call("set", ctrl=this.cid, prop="Text", value="    ".join(parts) if len(parts) > 1 else parts[0])
    return 1


def _sb_setparts(this, widths):
    n = min(len(widths) + 1, 256)
    parts = _sb_parts(this)
    parts[:] = (parts + [""] * n)[:n]
    _srv().call("set", ctrl=this.cid, prop="Text", value="    ".join(parts))
    return this.cid


def sb_text(c, part=1):
    parts = _SB_PARTS.get(c.cid)
    if parts:
        return parts[part - 1] if 1 <= part <= len(parts) else ""
    return ctrl_get(c, "Text") if part == 1 else ""


def classnn(c):
    cls = WIN32_CLASS.get(c.ctype, c.ctype)
    n = sum(1 for o in c.gui.ctrls[:c.gui.ctrls.index(c) + 1] if WIN32_CLASS.get(o.ctype, o.ctype) == cls) \
        if c in c.gui.ctrls else 1
    return f"{cls}{n}"


def gui_for_window(xid):
    return next((g for g in GUIS.values() if not g.destroyed and xid and (g.xid == xid or g.wid == xid)), None)


def find_ctrl(control, win_xid=0, mode=None):
    """Resolve the Control parameter of Control* functions to one of this script's Gui controls (or None)."""
    if isinstance(control, CtrlObj):
        return control
    if isinstance(control, AhkObject):
        return None
    if type(control) is int:
        return CTRLS.get(control)
    g = gui_for_window(win_xid)
    if g is None:
        return None
    s = S(control)
    sl = s.lower()
    for c in g.ctrls:
        if classnn(c).lower() == sl:
            return c
    from .window import _str_match
    if mode is None:
        mode = rt().thread.settings.title_match_mode
    for c in g.ctrls:
        try:
            txt = ctrl_get(c, "Text")
        except Exception:
            continue
        if isinstance(txt, str) and txt and _str_match(s, txt.replace("&", "") if c.ctype in ("Button", "CheckBox",
                                                                                             "Radio") else txt, mode):
            return c
    return None


def _num(v):
    return v


def _gui_item(this, name):
    if isinstance(name, int):
        c = CTRLS.get(name)
        if c is not None and c.gui is this:
            return c
    c = this.names.get(S(name).lower())
    if c is None:
        sl = S(name).lower()
        c = next((x for x in this.ctrls if classnn(x).lower() == sl), None)
    if c is None:
        throw("Error", "No such control.", S(name))
    return c


def _gui_enum(this, n):
    from .core import Enumerator

    def gen():
        for c in this.ctrls:
            yield (c.cid, c) if n > 1 else (c,)
    return Enumerator(gen(), n)


def _getpos(this, refs, client=False):
    from . import setref
    vals = _srv().call("getpos", win=this.wid, client=client)
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
    if "w" in kw or "h" in kw:
        this.sized = (this.sized[0] or "w" in kw, this.sized[1] or "h" in kw)
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
    __slots__ = ("name", "cb", "checked", "enabled", "builtin", "sub", "radio", "icon")

    def __init__(self, name, cb=None, builtin=None):
        self.name = name
        self.cb = cb
        self.sub = cb if isinstance(cb, MenuObj) else None      # Menu.Add(name, SubmenuObject)
        self.radio = False
        self.icon = ""
        self.checked = None        # None = not a check item
        self.enabled = True
        self.builtin = builtin     # python callable for standard tray items


class MenuObj(AhkObject):
    __slots__ = ("mid", "items", "default", "click_count", "on_change", "color")

    def __init__(self, proto=None):
        super().__init__(proto or CLASSES["Menu"].prototype)
        self.mid = next(_menu_ids)
        self.items: list[MenuItem] = []
        self.default = ""
        self.click_count = 2
        self.on_change = None
        self.color = ""
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
        for g in GUIS.values():
            if g.menubar is not None and not g.destroyed:
                _srv().call("menubar", win=g.wid, tree=menu_tree(g.menubar))

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
        if it.sub is not None:
            return
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
                existing.sub = cb if isinstance(cb, MenuObj) else None
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
        if ol in ("+radio", "radio"):
            item.radio = True
            item.checked = bool(item.checked)
        elif ol in ("-radio",):
            item.radio = False
        elif ol in ("+check", "check"):
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
    method(mp, "SetIcon", lambda this, name, file, num=1, width=UNSET: _menu_seticon(this, name, file))
    method(mp, "SetColor", lambda this, color="", apply_submenus=1: _menu_setcolor(this, color, apply_submenus))
    method(mp, "AddStandard", lambda this: _add_standard(this))
    method(mp, "Show", lambda this, x=UNSET, y=UNSET, wait=1: _menu_show(this, x, y))
    prop(mp, "Default", get=lambda this: this.default, set=lambda this, v: _menu_set_default(this, v))
    prop(mp, "ClickCount", get=lambda this: this.click_count, set=lambda this, v: _menu_set_clicks(this, v))
    prop(mp, "Handle", get=lambda this: this.mid)


def menu_tree(m, depth=0):
    """Nested item description for the GTK side (Menu.Show, Gui.MenuBar)."""
    dflt = m.default.replace("&", "").lower()
    out = []
    for i, it in enumerate(m.items):
        d = {"label": it.name, "checked": it.checked, "enabled": it.enabled, "radio": it.radio, "menu": m.mid,
             "index": i, "default": bool(dflt) and it.name.replace("&", "").lower() == dflt, "icon": it.icon,
             "color": m.color}
        if it.sub is not None and depth < 32:
            d["sub"] = menu_tree(it.sub, depth + 1)
        out.append(d)
    return out


def _menu_seticon(m, name, file):
    from .gui import picture_path
    it = m.find_item(name)
    src = S(file)
    it.icon = "" if src == "" else (picture_path(src) if not re.search(r"\.(dll|exe|cpl|icl)$", src, re.I) else src)
    m.changed()
    return ""


def _menu_setcolor(m, color="", apply_submenus=1):
    c = parse_color(S(color)) if color not in (UNSET, "") else ""
    if c is None:
        throw("ValueError", "Parameter #1 of Menu.Prototype.SetColor is invalid.", S(color))
    m.color = c
    if apply_submenus is UNSET or to_bool(apply_submenus):
        for it in m.items:
            if it.sub is not None:
                _menu_setcolor(it.sub, color, 1)
    m.changed()
    return ""


def _menu_show(m, x=UNSET, y=UNSET):
    kw = {}
    if x is not UNSET and y is not UNSET and x != "" and y != "":
        from .window import _coord_origin
        ox, oy = _coord_origin("Menu")
        kw = {"x": rt().to_int(x) + ox, "y": rt().to_int(y) + oy}
    _srv().call("menu", menu=m.mid, tree=menu_tree(m), **kw)
    return ""


def set_menubar(g, mb):
    if mb == "" or mb is UNSET or mb == 0:
        g.menubar = None
        _srv().call("menubar", win=g.wid, tree=None)
        return mb
    if not isinstance(mb, MenuObj):
        throw("TypeError", O.type_error_msg("MenuBar", mb))
    g.menubar = mb
    _srv().call("menubar", win=g.wid, tree=menu_tree(mb))
    return mb


def _add_standard(m):
    from . import tray
    tray.add_standard_items(m)
    m.changed()
    return ""


def tray_menu():
    from . import tray
    return tray.menu()
