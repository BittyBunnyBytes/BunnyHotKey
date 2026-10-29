"""GTK3 Gui server process for Bunny Hot Key.

Protocol: one JSON object per line.
  stdin  {"id": n, "op": "...", ...}      requests from the script process
  stdout {"reply": n, "value": ...}       answers
         {"event": "Click", "ctrl": c, ...} control/window events
Windows use Gtk.Fixed so AutoHotkey's absolute x/y/w/h layout carries over.
"""
import json
import os
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

ICON = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets",
                    "bunnyhotkey-64.png")
wins = {}
ctrls = {}
tips = {}
menus = {}
out_lock = threading.Lock()


def emit(obj):
    with out_lock:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


class Win:
    def __init__(self, wid, title, resizable):
        self.id = wid
        self.w = Gtk.Window(title=title)
        self.w.set_resizable(resizable)
        self.fixed = Gtk.Fixed()
        self.w.add(self.fixed)
        self.w.connect("delete-event", self.on_close)
        self.w.connect("key-press-event", self.on_key)
        self.w.connect("configure-event", self.on_size)
        self.radio_group = None

    def on_close(self, *_):
        emit({"event": "Close", "win": self.id})
        return True        # the script decides (default: hide)

    def on_key(self, _w, ev):
        if ev.keyval == 0xFF1B:
            emit({"event": "Escape", "win": self.id})
        return False

    def on_size(self, _w, ev):
        emit({"event": "Size", "win": self.id, "w": ev.width, "h": ev.height})
        return False


def text_of(c):
    w = c["w"]
    t = c["type"]
    if t == "Edit":
        if isinstance(w, Gtk.ScrolledWindow):
            buf = w.get_child().get_buffer()
            return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        return w.get_text()
    if t in ("Text", "Link", "StatusBar"):
        return c["label"].get_text() if "label" in c else w.get_text()
    if t in ("Button", "CheckBox", "Radio"):
        return w.get_label() or ""
    if t in ("DDL", "ComboBox"):
        if t == "ComboBox":
            return w.get_child().get_text()
        return w.get_active_text() or ""
    if t == "ListBox":
        sel = c["tree"].get_selection().get_selected()
        return sel[0][sel[1]][0] if sel[1] else ""
    if t == "GroupBox":
        return w.get_label() or ""
    return ""


def value_of(c):
    w = c["w"]
    t = c["type"]
    if t in ("CheckBox", "Radio"):
        return 1 if w.get_active() else 0
    if t == "DDL" or t == "ComboBox":
        return w.get_active() + 1
    if t == "ListBox":
        sel = c["tree"].get_selection().get_selected()
        return int(str(sel[0].get_path(sel[1]))) + 1 if sel[1] else 0
    if t == "Slider":
        return int(w.get_value())
    if t == "Progress":
        return int(round(w.get_fraction() * 100))
    if t == "ListView":
        sel = c["tree"].get_selection().get_selected()
        return int(str(sel[0].get_path(sel[1]))) + 1 if sel[1] else 0
    return text_of(c)


def set_value(c, v):
    w = c["w"]
    t = c["type"]
    if t in ("CheckBox", "Radio"):
        w.set_active(bool(int(v or 0)))
    elif t in ("DDL", "ComboBox"):
        w.set_active(int(v) - 1)
    elif t == "ListBox":
        if int(v) > 0:
            c["tree"].get_selection().select_path(Gtk.TreePath(int(v) - 1))
    elif t == "Slider":
        w.set_value(float(v))
    elif t == "Progress":
        w.set_fraction(max(0.0, min(float(v), 100.0)) / 100.0)
    else:
        set_text(c, str(v))


def set_text(c, s):
    w = c["w"]
    t = c["type"]
    if t == "Edit":
        if isinstance(w, Gtk.ScrolledWindow):
            w.get_child().get_buffer().set_text(s)
        else:
            w.set_text(s)
    elif t in ("Text", "StatusBar"):
        w.set_text(s)
    elif t == "Link":
        w.set_markup(s.replace("<a ", "<a ").replace("&", "&amp;") if "<a" in s else GLib.markup_escape_text(s))
    elif t in ("Button", "CheckBox", "Radio", "GroupBox"):
        w.set_label(s)
    elif t == "ComboBox":
        w.get_child().set_text(s)
    elif t == "DDL":
        model = w.get_model()
        for i, row in enumerate(model):
            if row[0] == s:
                w.set_active(i)


def make(win, cid, t, opts):
    text = opts.get("text", "")
    items = opts.get("items", [])
    c = {"type": t, "win": win.id}
    if t == "Text":
        w = Gtk.Label(label=text, xalign=0, yalign=0)
        w.set_line_wrap(bool(opts.get("w")))   # AHK sizes an unwidthed Text to fit its contents
        if opts.get("center"):
            w.set_justify(Gtk.Justification.CENTER)
            w.set_xalign(0.5)
    elif t == "Link":
        w = Gtk.Label(xalign=0)
        w.set_markup(text)
        w.connect("activate-link", lambda _w, uri: emit({"event": "Click", "ctrl": cid, "uri": uri}) or False)
    elif t == "Edit":
        if opts.get("multi"):
            tv = Gtk.TextView()
            tv.get_buffer().set_text(text)
            tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            tv.set_editable(not opts.get("readonly"))
            w = Gtk.ScrolledWindow()
            w.add(tv)
            tv.get_buffer().connect("changed", lambda *_: emit({"event": "Change", "ctrl": cid}))
        else:
            w = Gtk.Entry(text=text)
            w.set_visibility(not opts.get("password"))
            w.set_editable(not opts.get("readonly"))
            w.connect("changed", lambda *_: emit({"event": "Change", "ctrl": cid}))
    elif t == "Button":
        w = Gtk.Button(label=text.replace("&", "_"), use_underline=True)
        w.connect("clicked", lambda *_: emit({"event": "Click", "ctrl": cid}))
        if opts.get("default"):
            w.set_can_default(True)
            GLib.idle_add(lambda: (w.grab_default(), False)[1])
    elif t == "CheckBox":
        w = Gtk.CheckButton(label=text.replace("&", "_"), use_underline=True)
        w.set_active(bool(opts.get("checked")))
        w.connect("toggled", lambda *_: emit({"event": "Click", "ctrl": cid}))
    elif t == "Radio":
        if opts.get("group") or win.radio_group is None:
            win.radio_group = None
        w = Gtk.RadioButton.new_with_mnemonic_from_widget(win.radio_group, text.replace("&", "_"))
        if win.radio_group is None:
            win.radio_group = w
        w.set_active(bool(opts.get("checked")))
        w.connect("toggled", lambda b: b.get_active() and emit({"event": "Click", "ctrl": cid}))
    elif t in ("DDL", "ComboBox"):
        w = Gtk.ComboBoxText.new_with_entry() if t == "ComboBox" else Gtk.ComboBoxText()
        for it in items:
            w.append_text(it)
        if opts.get("choose"):
            w.set_active(int(opts["choose"]) - 1)
        w.connect("changed", lambda *_: emit({"event": "Change", "ctrl": cid}))
    elif t in ("ListBox", "ListView"):
        cols = opts.get("columns") or [""]
        store = Gtk.ListStore(*([str] * len(cols)))
        if t == "ListBox":
            for it in items:
                store.append([it])
        tree = Gtk.TreeView(model=store)
        tree.set_headers_visible(t == "ListView")
        for i, title in enumerate(cols):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i)
            col.set_resizable(True)
            tree.append_column(col)
        tree.get_selection().connect("changed", lambda *_: emit({"event": "Change", "ctrl": cid}))
        tree.connect("row-activated", lambda _t, path, _c: emit({"event": "DoubleClick", "ctrl": cid,
                                                                  "row": int(str(path)) + 1}))
        if opts.get("choose"):
            tree.get_selection().select_path(Gtk.TreePath(int(opts["choose"]) - 1))
        w = Gtk.ScrolledWindow()
        w.add(tree)
        c["tree"] = tree
        c["store"] = store
    elif t == "Slider":
        lo, hi = opts.get("range", [0, 100])
        w = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
        w.set_value(float(text or lo))
        w.connect("value-changed", lambda *_: emit({"event": "Change", "ctrl": cid}))
    elif t == "Progress":
        w = Gtk.ProgressBar()
        w.set_fraction(float(text or 0) / 100.0)
    elif t == "GroupBox":
        w = Gtk.Frame(label=text)
    elif t == "Picture":
        w = Gtk.Image.new_from_file(text) if os.path.exists(text) else Gtk.Image()
    elif t == "StatusBar":
        w = Gtk.Label(label=text, xalign=0)
    else:
        w = Gtk.Label(label=text)
    c["w"] = w
    ctrls[cid] = c
    win.fixed.put(w, int(opts.get("x", 0)), int(opts.get("y", 0)))
    if opts.get("w") or opts.get("h"):
        w.set_size_request(int(opts.get("w") or -1), int(opts.get("h") or -1))
    w.show_all()
    if opts.get("hidden"):
        w.hide()
    if opts.get("disabled"):
        w.set_sensitive(False)
    pw = w.get_preferred_size()[1]
    return {"w": pw.width, "h": pw.height}


def handle(req):
    op = req["op"]
    if op == "new":
        win = Win(req["win"], req.get("title", ""), req.get("resize", False))
        wins[req["win"]] = win
        win.w.realize()
        try:
            gi.require_version("GdkX11", "3.0")
            from gi.repository import GdkX11  # noqa: F401
            return win.w.get_window().get_xid()
        except (ValueError, ImportError, AttributeError):
            return 0
    if op == "add":
        return make(wins[req["win"]], req["ctrl"], req["type"], req.get("opts", {}))
    if op == "show":
        win = wins[req["win"]]
        if req.get("w") or req.get("h"):
            win.w.resize(int(req.get("w") or 1), int(req.get("h") or 1))
        win.w.show_all()
        for cid, c in ctrls.items():
            if c["win"] == win.id and c.get("hidden_now"):
                c["w"].hide()
        if req.get("x") is not None or req.get("y") is not None:
            win.w.move(int(req.get("x") or 0), int(req.get("y") or 0))
        elif req.get("center", True):
            win.w.set_position(Gtk.WindowPosition.CENTER)
        win.w.present()
        return True
    if op == "hide":
        wins[req["win"]].w.hide()
        return True
    if op == "destroy":
        win = wins.pop(req["win"], None)
        if win:
            win.w.destroy()
        return True
    if op == "title":
        wins[req["win"]].w.set_title(req["value"])
        return True
    if op == "getpos":
        win = wins[req["win"]]
        x, y = win.w.get_position()
        w, h = win.w.get_size()
        return [x, y, w, h]
    if op == "get":
        c = ctrls[req["ctrl"]]
        return value_of(c) if req["prop"] == "Value" else text_of(c)
    if op == "set":
        c = ctrls[req["ctrl"]]
        if req["prop"] == "Value":
            set_value(c, req["value"])
        elif req["prop"] == "Text":
            set_text(c, str(req["value"]))
        elif req["prop"] == "Enabled":
            c["w"].set_sensitive(bool(req["value"]))
        elif req["prop"] == "Visible":
            c["w"].set_visible(bool(req["value"]))
        return True
    if op == "move":
        c = ctrls[req["ctrl"]]
        parent = c["w"].get_parent()
        x, y = parent.child_get(c["w"], "x", "y")
        parent.move(c["w"], int(req.get("x", x)), int(req.get("y", y)))
        if req.get("w") is not None or req.get("h") is not None:
            c["w"].set_size_request(int(req.get("w") or -1), int(req.get("h") or -1))
        return True
    if op == "focus":
        ctrls[req["ctrl"]]["w"].grab_focus()
        return True
    if op == "items":
        c = ctrls[req["ctrl"]]
        if c["type"] in ("DDL", "ComboBox"):
            if req.get("clear"):
                c["w"].remove_all()
            for it in req.get("add", []):
                c["w"].append_text(it)
        elif c["type"] == "ListBox":
            if req.get("clear"):
                c["store"].clear()
            for it in req.get("add", []):
                c["store"].append([it])
        return True
    if op == "lv_add":
        c = ctrls[req["ctrl"]]
        row = (req["fields"] + [""] * c["store"].get_n_columns())[:c["store"].get_n_columns()]
        c["store"].append([str(f) for f in row])
        return len(c["store"])
    if op == "lv_modify":
        c = ctrls[req["ctrl"]]
        it = c["store"].get_iter(Gtk.TreePath(req["row"] - 1))
        for i, f in enumerate(req["fields"][:c["store"].get_n_columns()]):
            c["store"].set_value(it, i, str(f))
        return 1
    if op == "lv_delete":
        c = ctrls[req["ctrl"]]
        if req.get("row"):
            c["store"].remove(c["store"].get_iter(Gtk.TreePath(req["row"] - 1)))
        else:
            c["store"].clear()
        return 1
    if op == "lv_gettext":
        c = ctrls[req["ctrl"]]
        if req["row"] == 0:
            return c["tree"].get_column(req["col"] - 1).get_title()
        return c["store"][req["row"] - 1][req["col"] - 1]
    if op == "lv_count":
        return len(ctrls[req["ctrl"]]["store"])
    if op == "tooltip":
        n = req["n"]
        old = tips.pop(n, None)
        if old:
            old.destroy()
        if req.get("text"):
            tw = Gtk.Window(type=Gtk.WindowType.POPUP)
            lbl = Gtk.Label(label=req["text"])
            lbl.set_margin_start(6)
            lbl.set_margin_end(6)
            lbl.set_margin_top(3)
            lbl.set_margin_bottom(3)
            tw.add(lbl)
            tw.move(int(req["x"]), int(req["y"]))
            tw.show_all()
            tips[n] = tw
        return True
    if op == "tray":
        return tray_op(req)
    if op == "info":
        w = Gtk.Window(title=req.get("title", ""))
        w.set_default_size(560, 380)
        tv = Gtk.TextView()
        tv.set_editable(False)
        tv.set_monospace(True)
        tv.get_buffer().set_text(req.get("text", ""))
        sw = Gtk.ScrolledWindow()
        sw.add(tv)
        w.add(sw)
        w.show_all()
        w.present()
        return True
    if op == "menu":
        m = Gtk.Menu()
        for i, label in enumerate(req["items"]):
            if label == "":
                m.append(Gtk.SeparatorMenuItem())
                continue
            item = Gtk.MenuItem(label=label.replace("&", "_"), use_underline=True)
            item.connect("activate", lambda _i, i=i: emit({"event": "MenuPick", "menu": req["menu"], "index": i}))
            m.append(item)
        m.show_all()
        m.popup_at_pointer(None)
        menus[req["menu"]] = m
        return True
    raise ValueError(f"unknown op {op}")


# ---------------------------------------------------------------- tray icon
class Tray:
    """AutoHotkey-style tray icon.  XApp.StatusIcon (Cinnamon/XFCE/MATE, SNI + XEmbed), else
    Gtk.StatusIcon (XEmbed trays), else AppIndicator3 (KDE/GNOME, menu only)."""

    def __init__(self):
        self.items = []
        self.menu = Gtk.Menu()
        self.kind = None
        self.icon = None
        self.click_count = 2
        self._last_click = 0
        try:
            gi.require_version("XApp", "1.0")
            from gi.repository import XApp
            self.icon = XApp.StatusIcon()
            self.icon.connect("activate", self._xapp_activate)
            self.icon.set_secondary_menu(self.menu)
            self.kind = "xapp"
        except (ValueError, ImportError):
            pass
        if self.icon is None:
            try:
                self.icon = Gtk.StatusIcon()
                self.icon.connect("button-press-event", self._gtk_press)
                self.icon.connect("popup-menu", self._gtk_popup)
                self.kind = "gtk"
            except (AttributeError, TypeError):
                self.icon = None
        if self.icon is None:
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3
            self.icon = AppIndicator3.Indicator.new("bunnyhotkey", "bunnyhotkey",
                                                     AppIndicator3.IndicatorCategory.APPLICATION_STATUS)
            self.icon.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            self.icon.set_menu(self.menu)
            self.kind = "appindicator"

    def _xapp_activate(self, _icon, button, _time):
        if button == 1:
            self._primary_click()

    def _gtk_press(self, _icon, ev):
        from gi.repository import Gdk
        if ev.button == 1:
            if ev.type == Gdk.EventType._2BUTTON_PRESS:
                if self.click_count == 2:
                    emit({"event": "TrayDefault"})
            elif ev.type == Gdk.EventType.BUTTON_PRESS and self.click_count == 1:
                emit({"event": "TrayDefault"})
        return False

    def _gtk_popup(self, icon, button, time):
        self.menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, time)

    def _primary_click(self):
        import time
        now = time.monotonic()
        if self.click_count == 1 or now - self._last_click < 0.45:
            emit({"event": "TrayDefault"})
            self._last_click = 0
        else:
            self._last_click = now

    def set_icon(self, path):
        if self.kind == "xapp":
            self.icon.set_icon_name(path)
        elif self.kind == "gtk":
            self.icon.set_from_file(path)
        else:
            self.icon.set_icon_full(path, "Bunny Hot Key")

    def set_tip(self, text):
        if self.kind in ("xapp", "gtk"):
            self.icon.set_tooltip_text(text)
        else:
            self.icon.set_title(text)

    def set_visible(self, v):
        if self.kind in ("xapp", "gtk"):
            self.icon.set_visible(v)
        else:
            from gi.repository import AppIndicator3
            self.icon.set_status(AppIndicator3.IndicatorStatus.ACTIVE if v else AppIndicator3.IndicatorStatus.PASSIVE)

    def set_items(self, items):
        for child in self.menu.get_children():
            self.menu.remove(child)
        for i, it in enumerate(items):
            label = it.get("label", "")
            if label == "":
                self.menu.append(Gtk.SeparatorMenuItem())
                continue
            if it.get("checked") is not None:
                mi = Gtk.CheckMenuItem(label=label.replace("&", "_"), use_underline=True)
                mi.set_active(bool(it["checked"]))
            else:
                mi = Gtk.MenuItem(label=label.replace("&", "_"), use_underline=True)
            if it.get("default"):
                child = mi.get_child()
                if isinstance(child, Gtk.Label):
                    child.set_markup("<b>" + GLib.markup_escape_text(child.get_text()) + "</b>")
            mi.set_sensitive(it.get("enabled", True))
            mi.connect("activate", lambda _m, i=i: emit({"event": "TrayItem", "index": i}))
            self.menu.append(mi)
        self.menu.show_all()


tray = None


def tray_op(req):
    global tray
    if tray is None:
        tray = Tray()
    if "icon" in req:
        tray.set_icon(req["icon"])
    if "tip" in req:
        tray.set_tip(req["tip"])
    if "items" in req:
        tray.set_items(req["items"])
    if "click_count" in req:
        tray.click_count = int(req["click_count"])
    if "visible" in req:
        tray.set_visible(bool(req["visible"]))
    return tray.kind


def on_line(source, _cond):
    line = source.readline()
    if not line:
        Gtk.main_quit()
        return False
    req = json.loads(line)
    try:
        emit({"reply": req["id"], "value": handle(req)})
    except Exception as e:
        emit({"reply": req["id"], "error": f"{type(e).__name__}: {e}"})
    return True


def main():
    if os.path.exists(ICON):
        Gtk.Window.set_default_icon_from_file(ICON)
    GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_HUP, on_line)
    Gtk.main()


if __name__ == "__main__":
    main()
