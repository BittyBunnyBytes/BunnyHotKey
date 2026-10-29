"""AutoHotkey v1 Gui, GuiControl(Get), Menu, Progress/Splash and LV_/TV_/SB_ functions on BHK's v2 Gui objects.

v1 windows are named ("1", "MyGui", or a HWND), controls are found by their
associated variable, ClassNN, text or HWND, g-labels and GuiClose-style labels
run as v1 subroutines with A_Gui* set, and Submit stores into global variables.
"""
from __future__ import annotations

import re

from .. import objects as O
from ..errors import AhkThrow
from ..objects import AhkArray, AhkObject, CLASSES, Cell, VarRef, throw
from ..values import UNSET, str_to_number
from . import export
from .v1 import B, EL, I, S, U, callable_of, find_label, gosub, lookup_func, out, setvar, var_name, LabelFunc


def R():
    return O.RT


def P(obj, name):
    return R().get_prop(obj, name)


def SETP(obj, name, v):
    return R().set_prop(obj, name, v)


def M(obj, name, *args):
    return R().call_method(obj, name, list(args))


VALUE_TYPES = {"checkbox", "radio", "slider", "progress", "updown", "datetime", "monthcal", "hotkey", "picture"}
LIST_TYPES = {"ddl", "dropdownlist", "combobox", "listbox", "tab", "tab2", "tab3"}


class Ctl:
    __slots__ = ("obj", "type", "var", "glabel", "altsubmit", "radio_group", "gui")

    def __init__(self, gui, obj, typ, var, glabel, altsubmit):
        self.gui = gui
        self.obj = obj
        self.type = typ.lower()
        self.var = var
        self.glabel = glabel
        self.altsubmit = altsubmit
        self.radio_group = None


class Win:
    def __init__(self, name, obj):
        self.name = name
        self.obj = obj
        self.ctls: list[Ctl] = []
        self.label_prefix = "Gui" if name == "1" else name + "Gui"
        self.default_lv = None
        self.default_tv = None
        self.last_tab = None
        self.delimiter = "|"
        self.radio_start = None
        self.prev_type = None
        self.shown = False


class V1Gui:
    def __init__(self, rt):
        self.rt = rt
        self.wins: dict[str, Win] = {}
        self.default = "1"
        self.menus: dict[str, AhkObject] = {}
        self.menu_items: dict[str, list] = {}
        self.splash = {}

    # ------------------------------------------------------------ windows
    def default_name(self):
        th = self.rt.thread
        d = getattr(th.settings, "default_gui", None)
        return d if isinstance(d, str) and d else self.default

    def set_default(self, name):
        self.default = name
        self.rt.thread.settings.default_gui = name

    def default_ctrl_name(self, kind):
        w = self.wins.get(self.default_name().lower())
        if not w:
            return ""
        c = w.default_lv if kind == "ListView" else w.default_tv
        return c.var if c else ""

    def win(self, name=None, create=True):
        name = name or self.default_name()
        key = str(name).lower()
        w = self.wins.get(key)
        if w is None:
            # a HWND?
            n = str_to_number(str(name)) if isinstance(name, str) else name
            if type(n) is int:
                for ww in self.wins.values():
                    if R().to_int(P(ww.obj, "Hwnd")) == n:
                        return ww
            if not create:
                return None
            obj = R().call(CLASSES["Gui"], ["", R().bivars["a_scriptname"][0]()])
            w = Win(str(name), obj)
            self.wins[key] = w
            self._wire_window(w)
        return w

    def _wire_window(self, w):
        g = w.obj
        from ..classes import bif

        def ev(kind):
            def handler(*args):
                return self.window_event(w, kind, args)
            return bif("Gui" + kind, handler)
        for kind in ("Close", "Escape", "Size", "ContextMenu", "DropFiles"):
            M(g, "OnEvent", kind, ev(kind))

    def window_event(self, w, kind, args):
        target = callable_of(w.label_prefix + kind)
        if target is None:
            return 0
        st = self.rt.v1_state
        ge = {"gui": w.name, "guicontrol": "", "guievent": "", "eventinfo": 0}
        if kind == "Size" and len(args) >= 4:
            mm = R().to_int(args[1])
            ge.update(eventinfo={0: 0, -1: 1, 1: 2}.get(mm, 0), guiwidth=args[2], guiheight=args[3])
        elif kind == "ContextMenu" and len(args) >= 2:
            c = self.ctl_by_obj(w, args[1])
            ge.update(guicontrol=(c.var or S(P(args[1], "Text"))) if c else "", eventinfo=args[2] if len(args) > 2 else 0,
                      guix=args[4] if len(args) > 4 else "", guiy=args[5] if len(args) > 5 else "",
                      guievent="RightClick" if len(args) > 3 and args[3] else "Normal")
        elif kind == "DropFiles" and len(args) >= 3:
            files = [S(x) for x in args[2].items] if isinstance(args[2], AhkArray) else []
            ge.update(guievent="\n".join(files), eventinfo=len(files),
                      guix=args[3] if len(args) > 3 else "", guiy=args[4] if len(args) > 4 else "")
        self._run(target, ge, w, [P(w.obj, "Hwnd")])
        return 1

    def _run(self, target, ge, w, fargs):
        st = self.rt.v1_state
        prev = st.gui_event
        st.gui_event = ge
        self.set_default(w.name)
        try:
            if isinstance(target, LabelFunc):
                target.call([])
            else:
                f = target
                n = f.max_params() if hasattr(f, "max_params") else len(fargs)
                R().call(f, fargs[:n] if not f.is_variadic() else fargs)
        finally:
            st.gui_event = prev

    def ctl_by_obj(self, w, obj):
        for c in w.ctls:
            if c.obj is obj:
                return c
        return None

    def find_ctl(self, w, cid):
        cid_s = S(cid).strip()
        low = cid_s.lower()
        n = str_to_number(cid_s)
        for c in w.ctls:
            if c.var and c.var.lower() == low:
                return c
        if type(n) is int:
            for c in w.ctls:
                if R().to_int(P(c.obj, "Hwnd")) == n:
                    return c
        for c in w.ctls:
            try:
                if S(P(c.obj, "ClassNN")).lower() == low:
                    return c
            except AhkThrow:
                pass
        for c in w.ctls:
            try:
                if S(P(c.obj, "Text")).replace("&", "").lower() == low.replace("&", ""):
                    return c
            except AhkThrow:
                pass
        return None

    # ------------------------------------------------------------ Gui command
    def gui(self, sub, v1="", v2="", v3=""):
        sub = S(sub).strip()
        name = None
        m = re.match(r'^([^:\s]+):(.*)$', sub)
        if m and not sub.startswith(("+", "-")):
            name, sub = m[1], m[2].strip()
        elif m and re.match(r'^[+-]', m[2] or "") is not None and False:
            pass
        m2 = re.match(r'^([^:\s+-][^:\s]*):([+-].*)$', S(sub))
        if m2:
            name, sub = m2[1], m2[2]
        low = sub.lower()
        if low == "new":
            return self.gui_new(name, S(v1), S(v2))
        if low == "destroy":
            w = self.win(name, create=False)
            if w:
                quiet_call(M, w.obj, "Destroy")
                self.wins.pop(w.name.lower(), None)
            return
        w = self.win(name)
        g = w.obj
        if low == "add":
            return self.add(w, S(v1), S(v2), v3)
        if low == "show":
            return self.show(w, S(v1), v2)
        if low == "submit":
            return self.submit(w, S(v1).lower() != "nohide")
        if low in ("cancel", "hide"):
            return quiet_call(M, g, "Hide")
        if low == "font":
            return M(g, "SetFont", S(v1), *([S(v2)] if S(v2) else []))
        if low == "color":
            if S(v1) != "":
                SETP(g, "BackColor", S(v1))
            if S(v2) != "":
                w.ctl_color = S(v2)
            return
        if low == "margin":
            if S(v1) != "":
                SETP(g, "MarginX", I(v1))
            if S(v2) != "":
                SETP(g, "MarginY", I(v2))
            return
        if low == "menu":
            mb = self.menu_obj(S(v1)) if S(v1) else ""
            return SETP(g, "MenuBar", mb)
        if low in ("minimize", "maximize", "restore", "flash"):
            return quiet_call(M, g, low.capitalize(), *([] if low != "flash" else U(v1)))
        if low == "default":
            return self.set_default(w.name)
        if low == "tab":
            if w.last_tab is None:
                return
            if S(v1) == "":
                return M(w.last_tab.obj, "UseTab")
            return M(w.last_tab.obj, "UseTab", I(v1) if str_to_number(S(v1)) is not None else S(v1),
                     *([1] if S(v2).lower() == "exact" else []))
        if low == "listview":
            c = self.find_ctl(w, v1)
            if c:
                w.default_lv = c
            return
        if low == "treeview":
            c = self.find_ctl(w, v1)
            if c:
                w.default_tv = c
            return
        if low.startswith(("+", "-")) or low == "":
            return self.options(w, sub + ((" " + S(v1)) if S(v1) else ""))
        throw("Error", "Invalid Gui sub-command.", sub)

    def gui_new(self, name, opts, title):
        r = R()
        obj = r.call(CLASSES["Gui"], ["", title or r.bivars["a_scriptname"][0]()])
        if not name:
            name = str(r.to_int(P(obj, "Hwnd")))
        old = self.wins.get(name.lower())
        if old:
            quiet_call(M, old.obj, "Destroy")
        w = Win(name, obj)
        if name.isdigit() and len(name) > 3:
            w.label_prefix = "Gui"
        self.wins[name.lower()] = w
        self._wire_window(w)
        if opts:
            self.options(w, opts)
        self.set_default(name)

    def options(self, w, opts):
        rest = []
        for o in opts.split():
            lo = o.lower()
            if lo.startswith("+label") or lo.startswith("label"):
                w.label_prefix = o[o.lower().index("label") + 5:] or "Gui"
            elif lo.startswith(("+hwnd", "hwnd")):
                setvar(o[o.lower().index("hwnd") + 4:], P(w.obj, "Hwnd"))
            elif lo in ("+lastfound", "lastfound"):
                self.rt.thread.settings.last_found = R().to_int(P(w.obj, "Hwnd"))
            elif lo in ("+lastfoundexist", "lastfoundexist"):
                self.rt.thread.settings.last_found = R().to_int(P(w.obj, "Hwnd"))
            elif lo.startswith(("+delimiter", "delimiter")):
                d = o[o.lower().index("delimiter") + 9:]
                w.delimiter = {"space": " ", "tab": "\t"}.get(d.lower(), d or "|")
            elif lo.startswith(("+owner", "owner")) and len(lo.lstrip("+")) > 5:
                ow = self.win(o[o.lower().index("owner") + 5:], create=False)
                rest.append("+Owner" + (S(P(ow.obj, "Hwnd")) if ow else ""))
            elif lo in ("+owndialogs", "owndialogs", "-owndialogs"):
                pass
            else:
                rest.append(o)
        if rest:
            quiet_call(M, w.obj, "Opt", " ".join(rest))

    def add(self, w, ctype, opts, text):
        t = ctype.strip().lower()
        if t in ("pic",):
            t = "picture"
        var = glabel = hwndvar = None
        altsubmit = False
        keep = []
        group = False
        for o in opts.split():
            lo = o.lower()
            if lo.startswith("v") and len(o) > 1 and re.fullmatch(r'v[\w#@$]+', o, re.I):
                var = o[1:]
                keep.append("v" + var)
            elif lo.startswith("g") and len(o) > 1 and not lo.startswith(("gray",)) and re.fullmatch(r'g\S+', o, re.I) \
                    and lo not in ("group",):
                glabel = o[1:]
            elif lo.startswith("hwnd") and len(o) > 4:
                hwndvar = o[4:]
            elif lo in ("altsubmit", "+altsubmit"):
                altsubmit = True
                keep.append(o)
            elif lo in ("group", "+group"):
                group = True
                keep.append(o)
            else:
                keep.append(o)
        txt = text if isinstance(text, AhkObject) else S(text)
        if t in LIST_TYPES and isinstance(txt, str):
            d = w.delimiter
            items = txt.split(d) if txt else []
            choose = None
            clean = []
            i = 0
            while i < len(items):
                it = items[i]
                if it == "" and clean and choose is None:
                    choose = len(clean)
                    i += 1
                    continue
                if it != "" or i < len(items) - 1:
                    clean.append(it)
                i += 1
            clean = [c for c in clean if c != ""] if choose is not None or True else clean
            if choose is not None and not any(k.lower().startswith("choose") for k in keep):
                keep.append(f"Choose{choose}")
            txt = AhkArray(None, clean)
        r = R()
        try:
            obj = M(w.obj, "Add", ctype, " ".join(keep), *([txt] if txt != "" else []))
        except AhkThrow:
            raise
        c = Ctl(w, obj, t, var, glabel, altsubmit)
        if t == "radio":
            if group or w.prev_type != "radio" or w.radio_start is None:
                w.radio_start = c
            c.radio_group = w.radio_start
        w.prev_type = t
        w.ctls.append(c)
        if t == "listview":
            w.default_lv = c
        elif t == "treeview":
            w.default_tv = c
        elif t in ("tab", "tab2", "tab3"):
            w.last_tab = c
        elif t == "statusbar":
            w.statusbar = c
        if hwndvar:
            setvar(hwndvar, P(obj, "Hwnd"))
        self._wire_ctl(c)
        return ""

    def _wire_ctl(self, c):
        target_name = c.glabel
        if not target_name and c.type == "button":
            txt = re.sub(r'[\s&\r\n`]', "", S(P(c.obj, "Text")))
            auto = ("Button" if c.gui.name == "1" else c.gui.name + "Button") + txt
            if callable_of(auto) is not None:
                target_name = auto
        if not target_name:
            return
        from ..classes import bif

        def mk(kind):
            def handler(ctrl=UNSET, info=UNSET, *rest):
                target = callable_of(target_name)
                if target is None:
                    return ""
                ev = {"Click": "Normal", "DoubleClick": "DoubleClick", "Change": "Normal", "ColClick": "ColClick",
                      "ItemSelect": "S" if c.type == "treeview" else "I", "ContextMenu": "RightClick",
                      "ItemCheck": "I", "ItemEdit": "e"}.get(kind, "Normal")
                einfo = info if info is not UNSET and not isinstance(info, AhkObject) else 0
                if kind == "Click" and c.type in ("button", "checkbox", "radio", "text", "picture", "link", "groupbox"):
                    einfo = 0
                ge = {"gui": c.gui.name, "guicontrol": c.var or S(P(c.obj, "Text")), "guievent": ev, "eventinfo": einfo}
                self._run(target, ge, c.gui, [P(c.obj, "Hwnd"), ev, einfo, ""])
                return ""
            return bif("v1" + kind, handler)
        t = c.type
        kinds = {"button": ["Click"], "checkbox": ["Click"], "radio": ["Click"], "text": ["Click", "DoubleClick"],
                 "picture": ["Click", "DoubleClick"], "link": ["Click"], "listbox": ["Change", "DoubleClick"],
                 "listview": ["Click", "DoubleClick", "ColClick", "ContextMenu"],
                 "treeview": ["ItemSelect", "Click", "DoubleClick", "ContextMenu"]}.get(t, ["Change"])
        for k in kinds:
            try:
                M(c.obj, "OnEvent", k, mk(k))
            except AhkThrow:
                pass

    def show(self, w, opts, title):
        if title is not UNSET and S(title) != "":
            SETP(w.obj, "Title", S(title))
        w.shown = True
        return M(w.obj, "Show", opts)

    def ctl_value(self, c):
        t = c.type
        try:
            if t in LIST_TYPES and not c.altsubmit:
                return P(c.obj, "Text")
            if t == "radio":
                return P(c.obj, "Value")
            if t in ("listview", "treeview"):
                return ""
            v = P(c.obj, "Value")
            if t in LIST_TYPES and v == 0:
                return ""
            return v
        except AhkThrow:
            return ""

    def submit(self, w, hide=True):
        groups = {}
        for c in w.ctls:
            if c.type == "radio":
                groups.setdefault(id(c.radio_group), []).append(c)
        for c in w.ctls:
            if not c.var:
                continue
            if c.type == "radio":
                members = groups.get(id(c.radio_group), [c])
                if c is members[0] and not any(m.var for m in members[1:]) and len(members) > 1:
                    sel = 0
                    for i, m in enumerate(members, 1):
                        if R().to_int(P(m.obj, "Value")):
                            sel = i
                    setvar(c.var, sel)
                    continue
            setvar(c.var, self.ctl_value(c))
        if hide:
            quiet_call(M, w.obj, "Hide")

    # ------------------------------------------------------------ GuiControl
    def guicontrol(self, sub, cid, value=""):
        sub = S(sub).strip()
        name = None
        m = re.match(r'^([^:\s]+):(.*)$', sub)
        if m:
            name, sub = m[1], m[2].strip()
        w = self.win(name, create=False)
        if w is None:
            EL(1)
            return
        c = self.find_ctl(w, cid)
        if c is None:
            EL(1)
            return
        EL(0)
        low = sub.lower()
        o = c.obj
        v = value
        try:
            if low in ("", "text"):
                return self.set_contents(c, v, text_mode=low == "text")
            if low in ("move", "movedraw"):
                pos = {k.lower(): I(n) for k, n in re.findall(r'([xywh])\s*(-?\d+)', S(v), re.I)}
                M(o, "Move", *[pos.get(k, UNSET) for k in "xywh"])
                return
            if low == "focus":
                return M(o, "Focus")
            if low in ("disable", "enable"):
                SETP(o, "Enabled", int(low == "enable"))
                return
            if low in ("hide", "show"):
                SETP(o, "Visible", int(low == "show"))
                return
            if low in ("choose", "choosestring"):
                if low == "choose":
                    M(o, "Choose", I(v))
                else:
                    M(o, "Choose", S(v))
                return
            if low == "font":
                return
            if low.startswith(("+", "-")):
                opts = []
                for op in sub.split():
                    ol = op.lower()
                    if ol.startswith(("+g", "-g")) and len(ol) > 2:
                        c.glabel = op[2:] if op[0] == "+" else None
                        self._wire_ctl(c)
                    elif ol == "-g":
                        c.glabel = None
                    elif ol in ("+altsubmit", "-altsubmit"):
                        c.altsubmit = op[0] == "+"
                    else:
                        opts.append(op)
                if opts:
                    M(o, "Opt", " ".join(opts))
                return
            if low.startswith("enable") or low.startswith("disable"):
                SETP(o, "Enabled", int(low.startswith("enable") and low[-1] != "0" or low == "disable0"))
                return
            if low.startswith("show") or low.startswith("hide"):
                SETP(o, "Visible", int(low.startswith("show") and low[-1] != "0" or low == "hide0"))
                return
        except AhkThrow:
            EL(1)

    def set_contents(self, c, v, text_mode=False):
        o = c.obj
        t = c.type
        sv = S(v)
        if t in LIST_TYPES:
            d = c.gui.delimiter
            if text_mode and t == "combobox":
                SETP(o, "Text", sv)
                return
            replace = sv.startswith(d)
            if replace:
                sv = sv[1:]
                M(o, "Delete")
            items = sv.split(d) if sv else []
            choose = None
            clean = []
            for i, it in enumerate(items):
                if it == "" and clean:
                    choose = len(clean) + (c.count_offset if hasattr(c, "count_offset") else 0)
                    continue
                if it != "":
                    clean.append(it)
            if clean:
                M(o, "Add", AhkArray(None, clean))
            if choose is not None:
                M(o, "Choose", choose)
            return
        if t in ("progress", "slider", "updown") and re.match(r'^[+-]\d', sv):
            SETP(o, "Value", R().to_int(P(o, "Value")) + I(sv))
            return
        if t in ("checkbox", "radio") and not text_mode and sv in ("0", "1", "-1"):
            SETP(o, "Value", I(sv))
            return
        if t in ("checkbox", "radio", "button", "groupbox", "text", "link") or text_mode:
            SETP(o, "Text", sv)
            return
        if t in ("listview", "treeview"):
            return
        SETP(o, "Value", v)

    def guicontrolget(self, ref, sub="", cid="", value=""):
        sub = S(sub).strip()
        name = None
        m = re.match(r'^([^:\s]+):(.*)$', sub)
        if m:
            name, sub = m[1], m[2].strip()
        w = self.win(name, create=False)
        low = sub.lower()
        if w is None:
            EL(1)
            return
        if low in ("focus", "focusv"):
            try:
                fc = P(w.obj, "FocusedCtrl")
            except AhkThrow:
                fc = ""
            c = self.ctl_by_obj(w, fc) if isinstance(fc, AhkObject) else None
            out(ref, (c.var or "") if low == "focusv" and c else S(P(fc, "ClassNN")) if isinstance(fc, AhkObject) else "")
            EL(0 if c or isinstance(fc, AhkObject) else 1)
            return
        c = self.find_ctl(w, cid if S(cid) else var_name(ref))
        if c is None:
            EL(1)
            return
        EL(0)
        o = c.obj
        if low == "":
            out(ref, P(o, "Text") if S(value).lower() == "text" else self.ctl_value(c))
        elif low == "pos":
            cells = [Cell() for _ in range(4)]
            M(o, "GetPos", *[VarRef(x) for x in cells])
            base = var_name(ref)
            for suffix, x in zip("XYWH", cells):
                setvar(base + suffix, x.value)
        elif low == "enabled":
            out(ref, P(o, "Enabled"))
        elif low == "visible":
            out(ref, P(o, "Visible"))
        elif low == "hwnd":
            out(ref, P(o, "Hwnd"))
        elif low == "name":
            out(ref, c.var or "")
        else:
            EL(1)

    # ------------------------------------------------------------ ListView / TreeView / StatusBar
    def lv(self):
        w = self.wins.get(self.default_name().lower())
        if w is None or w.default_lv is None:
            return None
        return w.default_lv.obj

    def tv(self):
        w = self.wins.get(self.default_name().lower())
        if w is None or w.default_tv is None:
            return None
        return w.default_tv.obj

    def sb(self):
        w = self.wins.get(self.default_name().lower())
        c = getattr(w, "statusbar", None) if w else None
        return c.obj if c else None

    # ------------------------------------------------------------ menus
    def menu_obj(self, name, create=True):
        key = name.lower()
        if key == "tray":
            return R().bivars["a_traymenu"][0]()
        m = self.menus.get(key)
        if m is None and create:
            m = R().call(CLASSES["Menu"], [])
            self.menus[key] = m
            self.menu_items[key] = []
        return m

    def menu_handle(self, name):
        m = self.menu_obj(name, create=False)
        return P(m, "Handle") if m is not None else ""

    def menu_name(self, h):
        for k, m in self.menus.items():
            if S(P(m, "Handle")) == S(h):
                return k
        return ""

    def menu_cb(self, menu_name, label):
        from ..classes import bif
        gui = self

        def handler(item=UNSET, pos=UNSET, menu=UNSET):
            st = gui.rt.v1_state
            prev = dict(st.menu)
            st.menu = {"name": menu_name, "item": S(item), "pos": S(pos)}
            try:
                target = callable_of(label)
                if target is None:
                    throw("Error", "Target label does not exist.", label)
                if isinstance(target, LabelFunc):
                    target.call([])
                else:
                    n = target.max_params()
                    R().call(target, [item, pos, menu_name][:n] if not target.is_variadic() else [item, pos, menu_name])
            finally:
                st.menu = prev
            return ""
        return bif("v1Menu", handler)

    def menu(self, name, sub, v1="", v2="", v3="", v4=""):
        name = S(name)
        sub = S(sub).strip().lower()
        key = name.lower()
        m = self.menu_obj(name)
        items = self.menu_items.setdefault(key, [])
        r = R()
        try:
            if sub == "add":
                item = S(v1)
                if item == "":
                    M(m, "Add")
                    items.append(("", None, ""))
                    return
                target = S(v2) if not isinstance(v2, AhkObject) else v2
                if isinstance(target, str) and target.startswith(":"):
                    cb = self.menu_obj(target[1:])
                elif isinstance(target, AhkObject):
                    cb = target
                else:
                    cb = self.menu_cb(name, target or item)
                M(m, "Add", item, cb, S(v3))
                items.append((item, cb, S(v3)))
            elif sub == "insert":
                before, item, target = S(v1), S(v2), S(v3)
                if item == "":
                    M(m, "Insert", before)
                    return
                cb = self.menu_obj(target[1:]) if target.startswith(":") else self.menu_cb(name, target or item)
                M(m, "Insert", before, item, cb, S(v4))
            elif sub == "delete":
                if S(v1) == "":
                    M(m, "Delete")
                    items.clear()
                else:
                    M(m, "Delete", S(v1))
            elif sub == "deleteall":
                M(m, "Delete")
                items.clear()
            elif sub == "rename":
                M(m, "Rename", S(v1), S(v2))
            elif sub in ("check", "uncheck", "togglecheck", "enable", "disable", "toggleenable"):
                M(m, {"check": "Check", "uncheck": "Uncheck", "togglecheck": "ToggleCheck", "enable": "Enable",
                      "disable": "Disable", "toggleenable": "ToggleEnable"}[sub], S(v1))
            elif sub == "default":
                SETP(m, "Default", S(v1))
            elif sub == "nodefault":
                SETP(m, "Default", "")
            elif sub == "standard":
                M(m, "AddStandard")
            elif sub == "nostandard":
                M(m, "Delete")
                for it, cb, opts in items:
                    if it == "":
                        M(m, "Add")
                    else:
                        M(m, "Add", it, cb, opts)
            elif sub == "icon":
                if key == "tray":
                    if S(v1) == "":
                        r.bivars["a_iconhidden"][1](0)
                    else:
                        B("TraySetIcon", S(v1), *U(v2), *([1] if S(v3) == "1" else []))
                else:
                    M(m, "SetIcon", S(v1), S(v2), *U(v3))
            elif sub == "noicon":
                if key == "tray":
                    r.bivars["a_iconhidden"][1](1)
                else:
                    M(m, "SetIcon", S(v1), "")
            elif sub == "tip":
                r.bivars["a_icontip"][1](S(v1))
            elif sub == "show":
                M(m, "Show", *U(v1, v2))
            elif sub == "color":
                M(m, "SetColor", S(v1), int(S(v2).lower() != "single"))
            elif sub == "click":
                SETP(m, "ClickCount", I(v1, 2))
            elif sub in ("mainwindow", "nomainwindow", "useerrorlevel"):
                pass
            else:
                throw("Error", "Invalid Menu sub-command.", sub)
            EL(0)
        except AhkThrow:
            EL(1)
            raise

    # ------------------------------------------------------------ Progress / SplashText / SplashImage
    def splash_text(self, w, h, title, text):
        self.splash_off()
        g = R().call(CLASSES["Gui"], ["+AlwaysOnTop -SysMenu +Owner", title])
        M(g, "Add", "Text", f"Center w{max(w - 20, 10)}", text)
        M(g, "Show", f"w{w}" + (f" h{h}" if h else "") + " NoActivate")
        self.splash["text"] = g

    def splash_off(self):
        g = self.splash.pop("text", None)
        if g is not None:
            quiet_call(M, g, "Destroy")

    def progress(self, p1, sub, main, title, font, image=False):
        key = "image" if image else "progress"
        cur = self.splash.get(key)
        if p1.lower() == "off":
            if cur:
                quiet_call(M, cur["gui"], "Destroy")
                self.splash.pop(key, None)
            return
        if cur and str_to_number(p1) is not None and not sub and not main:
            if not image:
                SETP(cur["bar"], "Value", I(p1))
            return
        if cur and p1 == "" and (sub or main):
            if sub:
                SETP(cur["sub"], "Text", sub)
            if main:
                SETP(cur["main"], "Text", main)
            return
        if cur:
            quiet_call(M, cur["gui"], "Destroy")
        g = R().call(CLASSES["Gui"], ["+AlwaysOnTop -SysMenu", title or R().bivars["a_scriptname"][0]()])
        mn = M(g, "Add", "Text", "w260 Center", main)
        bar = None
        if image and image not in ("", "Off"):
            quiet_call(M, g, "Add", "Picture", "w260 h-1", image)
        elif not image:
            bar = M(g, "Add", "Progress", "w260 h20")
            val = re.search(r'\bP(\d+)', p1, re.I)
            if str_to_number(p1) is not None:
                SETP(bar, "Value", I(p1))
            elif val:
                SETP(bar, "Value", int(val[1]))
        sb = M(g, "Add", "Text", "w260 Center", sub)
        M(g, "Show", "NoActivate")
        self.splash[key] = {"gui": g, "bar": bar, "sub": sb, "main": mn}


def quiet_call(fn, *args):
    try:
        return fn(*args)
    except AhkThrow:
        return ""


def setup(rt):
    rt.v1_gui = V1Gui(rt)


def G():
    return R().v1_gui


# ================================================================ commands

@export("__v1_gui")
def _gui(sub="", v1="", v2="", v3=""):
    return G().gui(sub, v1, v2, v3)


@export("__v1_guicontrol")
def _guicontrol(sub="", cid="", value=""):
    return G().guicontrol(sub, cid, value)


@export("__v1_guicontrolget")
def _guicontrolget(ref, sub="", cid="", value=""):
    return G().guicontrolget(ref, sub, cid, value)


@export("__v1_menu")
def _menu(name, sub, v1="", v2="", v3="", v4=""):
    return G().menu(name, sub, v1, v2, v3, v4)


def _lvcall(method, *args):
    lv = G().lv()
    if lv is None:
        return 0
    try:
        return M(lv, method, *args)
    except AhkThrow:
        return 0


@export("__v1_LV_Add")
def _lv_add(opts="", *fields):
    return _lvcall("Add", S(opts), *fields)


@export("__v1_LV_Insert")
def _lv_insert(row, opts="", *fields):
    return _lvcall("Insert", I(row), S(opts), *fields)


@export("__v1_LV_Modify")
def _lv_modify(row, opts="", *fields):
    r = _lvcall("Modify", I(row), S(opts), *fields)
    return 1 if r != 0 else 0


@export("__v1_LV_Delete")
def _lv_delete(row=UNSET):
    r = _lvcall("Delete", *([I(row)] if row is not UNSET and row != "" else []))
    return 1 if r != 0 else 0


@export("__v1_LV_GetCount")
def _lv_getcount(kind=""):
    return _lvcall("GetCount", *([S(kind)] if S(kind) else []))


@export("__v1_LV_GetNext")
def _lv_getnext(start=0, kind=""):
    return _lvcall("GetNext", I(start), *([S(kind)] if S(kind) else []))


@export("__v1_LV_GetText")
def _lv_gettext(ref, row, col=1):
    lv = G().lv()
    if lv is None:
        out(ref, "")
        return 0
    try:
        out(ref, M(lv, "GetText", I(row), I(col, 1)))
        return 1
    except AhkThrow:
        out(ref, "")
        return 0


@export("__v1_LV_ModifyCol")
def _lv_modifycol(col=UNSET, opts="", title=UNSET):
    args = [] if col is UNSET or col == "" else [I(col), S(opts)] + ([S(title)] if title is not UNSET else [])
    r = _lvcall("ModifyCol", *args)
    return 1 if r != 0 else 0


@export("__v1_LV_InsertCol")
def _lv_insertcol(col, opts="", title=""):
    return _lvcall("InsertCol", I(col), S(opts), S(title))


@export("__v1_LV_DeleteCol")
def _lv_deletecol(col):
    r = _lvcall("DeleteCol", I(col))
    return 1 if r != 0 else 0


@export("__v1_LV_SetImageList")
def _lv_setimagelist(il, kind=UNSET):
    return _lvcall("SetImageList", il, *([kind] if kind is not UNSET else []))


def _tvcall(method, *args):
    tv = G().tv()
    if tv is None:
        return 0
    try:
        return M(tv, method, *args)
    except AhkThrow:
        return 0


@export("__v1_TV_Add")
def _tv_add(name, parent=0, opts=""):
    return _tvcall("Add", S(name), I(parent), S(opts))


@export("__v1_TV_Modify")
def _tv_modify(item, opts="", name=UNSET):
    return _tvcall("Modify", I(item), S(opts), *([S(name)] if name is not UNSET else []))


@export("__v1_TV_Delete")
def _tv_delete(item=UNSET):
    r = _tvcall("Delete", *([I(item)] if item is not UNSET and item != "" else []))
    return 1 if r != 0 else 0


@export("__v1_TV_GetSelection")
def _tv_getselection():
    return _tvcall("GetSelection")


@export("__v1_TV_GetCount")
def _tv_getcount():
    return _tvcall("GetCount")


@export("__v1_TV_GetParent")
def _tv_getparent(item):
    return _tvcall("GetParent", I(item))


@export("__v1_TV_GetChild")
def _tv_getchild(item):
    return _tvcall("GetChild", I(item))


@export("__v1_TV_GetPrev")
def _tv_getprev(item):
    return _tvcall("GetPrev", I(item))


@export("__v1_TV_GetNext")
def _tv_getnext(item=0, kind=""):
    return _tvcall("GetNext", I(item), *([S(kind)] if S(kind) else []))


@export("__v1_TV_GetText")
def _tv_gettext(ref, item):
    tv = G().tv()
    try:
        out(ref, M(tv, "GetText", I(item)))
        return I(item)
    except (AhkThrow, AttributeError):
        out(ref, "")
        return 0


@export("__v1_TV_Get")
def _tv_get(item, attr):
    return _tvcall("Get", I(item), S(attr))


@export("__v1_TV_SetImageList")
def _tv_setimagelist(il, kind=UNSET):
    return _tvcall("SetImageList", il, *([kind] if kind is not UNSET else []))


@export("__v1_SB_SetText")
def _sb_settext(text, part=1, style=0):
    sb = G().sb()
    if sb is None:
        return 0
    try:
        M(sb, "SetText", S(text), I(part, 1), I(style))
        return 1
    except AhkThrow:
        return 0


@export("__v1_SB_SetParts")
def _sb_setparts(*widths):
    sb = G().sb()
    if sb is None:
        return 0
    try:
        return M(sb, "SetParts", *widths)
    except AhkThrow:
        return 0


@export("__v1_SB_SetIcon")
def _sb_seticon(file, num=1, part=1):
    sb = G().sb()
    if sb is None:
        return 0
    try:
        return M(sb, "SetIcon", S(file), I(num, 1), I(part, 1))
    except AhkThrow:
        return 0
