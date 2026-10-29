"""GTK3 Gui server process for Bunny Hot Key.

Protocol: one JSON object per line.
  stdin  {"id": n, "op": "...", ...}      requests from the script process
  stdout {"reply": n, "value": ...}       answers
         {"event": "Click", "ctrl": c, ...} control/window events ("args": [...] = extra event parameters)
Windows use Gtk.Fixed so AutoHotkey's absolute x/y/w/h layout carries over.  Controls inside a Tab are siblings
in the same Gtk.Fixed and are shown/hidden as pages change, the way Win32 tab controls work.
"""
import datetime as dt
import itertools
import json
import os
import re
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

ICON = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets",
                    "bunnyhotkey-64.png")
wins = {}
ctrls = {}
tips = {}
menus = {}
out_lock = threading.Lock()
_providers = {}
_tv_ids = itertools.count(1)
quiet = False          # set while the script changes a control, so selection-type events don't fire


def emit(obj):
    with out_lock:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


def ev(cid, name, *args, always=False):
    """Control event.  Programmatic changes don't raise selection events (like Win32 CBN_SELCHANGE etc.)."""
    if quiet and not always:
        return
    msg = {"event": name, "ctrl": cid}
    if args:
        msg["args"] = list(args)
    emit(msg)


class Win:
    def __init__(self, wid, title, resizable):
        self.id = wid
        self.w = Gtk.Window(title=title)
        self.w.set_resizable(resizable)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.fixed = Gtk.Fixed()
        self.box.pack_end(self.fixed, True, True, 0)
        self.w.add(self.box)
        self.menubar = None
        self.w.connect("delete-event", self.on_close)
        self.w.connect("key-press-event", self.on_key)
        self.w.connect("configure-event", self.on_size)
        self.w.connect("window-state-event", self.on_state)
        self.w.connect("button-press-event", self.on_button)
        self.w.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.radio_group = None
        self.min_state = 0
        self.last_size = None

    def chrome_h(self, preferred=False):
        """Height of the menu bar and status bar around the client area."""
        h = 0
        for ch in self.box.get_children():
            if ch is not self.fixed and ch.get_visible():
                h += ch.get_preferred_height()[1] if preferred else ch.get_allocated_height()
        return h

    def menu_h(self):
        return self.chrome_h()

    def on_button(self, _w, e):
        if e.button == 3 and e.type == Gdk.EventType.BUTTON_PRESS:
            x, y = self.fixed.translate_coordinates(self.w, 0, 0) or (0, 0)
            emit({"event": "ContextMenu", "win": self.id, "ctrl": 0, "args": [0, 1, int(e.x) - x, int(e.y) - y]})
        return False

    def enable_drop(self):
        self.w.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.w.drag_dest_add_uri_targets()
        self.w.connect("drag-data-received", self.on_drop)

    def on_drop(self, _w, _ctx, x, y, data, _info, _time):
        files = [GLib.filename_from_uri(u)[0] for u in data.get_uris() if u.startswith("file://")]
        if files:
            emit({"event": "DropFiles", "win": self.id, "ctrl": 0, "files": files, "x": int(x),
                  "y": int(y) - self.chrome_h()})

    def on_close(self, *_):
        emit({"event": "Close", "win": self.id})
        return True        # the script decides (default: hide)

    def on_key(self, _w, e):
        if e.keyval == 0xFF1B:
            emit({"event": "Escape", "win": self.id})
        return False

    def on_size(self, _w, e):
        size = (e.width, e.height - self.menu_h())
        if size != self.last_size:
            self.last_size = size
            emit({"event": "Size", "win": self.id, "w": size[0], "h": size[1], "state": self.min_state})
        return False

    def on_state(self, _w, e):
        s = e.new_window_state
        self.min_state = -1 if s & Gdk.WindowState.ICONIFIED else 1 if s & Gdk.WindowState.MAXIMIZED else 0
        if e.changed_mask & (Gdk.WindowState.ICONIFIED | Gdk.WindowState.MAXIMIZED):
            w, h = self.w.get_size()
            emit({"event": "Size", "win": self.id, "w": w, "h": h - self.menu_h(), "state": self.min_state})
        return False


def set_client_size(win, w, h):
    """Gui.Show("w h") / Gui.Move: the client area gets exactly this size.  A non-resizable GTK window sizes itself
    to its content and ignores resize(), so the size is requested on the client area instead."""
    w = int(w or win.fixed.get_allocated_width() or 1)
    h = int(h or max(win.fixed.get_allocated_height(), 1))
    if win.w.get_resizable():
        win.fixed.set_size_request(-1, -1)
        win.w.resize(w, h + win.chrome_h(True))
    else:
        win.fixed.set_size_request(w, h)
        win.w.resize(1, 1)       # shrink to the new request if it got smaller


# ---------------------------------------------------------------- styling (SetFont, BackColor, c/Background options)
def set_css(widget, rules):
    ctx = widget.get_style_context()
    old = _providers.pop(id(widget), None)
    if old is not None:
        ctx.remove_provider(old)
    if rules:
        prov = Gtk.CssProvider()
        prov.load_from_data(("* {" + rules + "}").encode())
        ctx.add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        _providers[id(widget)] = prov


def font_css(f):
    r = []
    if not f:
        return ""
    if f.get("name"):
        r.append('font-family: "%s";' % f["name"].replace('"', ""))
    if f.get("size"):
        r.append("font-size: %spt;" % f["size"])
    if f.get("weight"):
        r.append("font-weight: %d;" % int(f["weight"]))
    if f.get("italic"):
        r.append("font-style: italic;")
    deco = [n for k, n in (("underline", "underline"), ("strike", "line-through")) if f.get(k)]
    if deco:
        r.append("text-decoration-line: %s;" % " ".join(deco))
    if f.get("color"):
        r.append("color: %s;" % f["color"])
    return " ".join(r)


def style_targets(c):
    out = [c["w"]]
    for k in ("tree", "tv", "label"):
        if k in c and c[k] is not c["w"]:
            out.append(c[k])
    if c["type"] == "ComboBox":
        out.append(c["w"].get_child())
    out.extend(c.get("fields", []))
    return out


def apply_style(c):
    rules = font_css(c.get("font"))
    if c.get("color"):
        rules += " color: %s;" % c["color"]
    if c.get("bg"):
        rules += " background-color: %s; background-image: none;" % c["bg"]
    for w in style_targets(c):
        set_css(w, rules)


# ---------------------------------------------------------------- tabs and visibility
def effective_visible(c):
    if not c.get("uv", True):
        return False
    t = c.get("tab")
    if t:
        tc = ctrls.get(t[0])
        if tc is not None:
            return effective_visible(tc) and tc["w"].get_current_page() == t[1] - 1
    return True


def sync_win(win_id):
    for c in ctrls.values():
        if c["win"] == win_id:
            vis = effective_visible(c)
            if c["w"].get_visible() != vis:
                c["w"].set_visible(vis)


def tab_add_page(c, label):
    page = Gtk.Box()
    page.show()
    c["w"].append_page(page, Gtk.Label(label=label.replace("&", "")))


# ---------------------------------------------------------------- DateTime / MonthCal helpers
def parse_stamp(s, default=None):
    s = re.sub(r"\D", "", str(s or ""))
    if len(s) < 4:
        return default
    s = (s + "0101000000"[len(s) - 4:]) if len(s) < 14 else s[:14]
    try:
        return dt.datetime(int(s[0:4]), int(s[4:6]), int(s[6:8]), int(s[8:10]), int(s[10:12]), int(s[12:14]))
    except ValueError:
        return default


def stamp(d):
    return d.strftime("%Y%m%d%H%M%S")


_FMT_TOKENS = [("dddd", "%A"), ("ddd", "%a"), ("dd", lambda d: "%02d" % d.day), ("d", lambda d: str(d.day)),
               ("MMMM", "%B"), ("MMM", "%b"), ("MM", lambda d: "%02d" % d.month), ("M", lambda d: str(d.month)),
               ("yyyy", lambda d: "%04d" % d.year), ("yy", lambda d: "%02d" % (d.year % 100)),
               ("y", lambda d: str(d.year % 100)), ("gg", lambda d: "A.D."),
               ("hh", lambda d: "%02d" % ((d.hour % 12) or 12)), ("h", lambda d: str((d.hour % 12) or 12)),
               ("HH", lambda d: "%02d" % d.hour), ("H", lambda d: str(d.hour)), ("mm", lambda d: "%02d" % d.minute),
               ("m", lambda d: str(d.minute)), ("ss", lambda d: "%02d" % d.second), ("s", lambda d: str(d.second)),
               ("tt", lambda d: "AM" if d.hour < 12 else "PM"), ("t", lambda d: "A" if d.hour < 12 else "P")]
NAMED_FMT = {"shortdate": "M/d/yyyy", "longdate": "dddd, MMMM d, yyyy", "time": "h:mm:ss tt", "": "M/d/yyyy"}


def fmt_ahk(fmt, d):
    """AutoHotkey date format pictures (the same tokens FormatTime uses)."""
    fmt = NAMED_FMT.get(fmt.lower(), fmt)
    out, i = [], 0
    while i < len(fmt):
        if fmt[i] == "'":
            j = fmt.find("'", i + 1)
            if j < 0:
                out.append(fmt[i + 1:])
                break
            out.append(fmt[i + 1:j] if j > i + 1 else "'")
            i = j + 1
            continue
        for tok, f in _FMT_TOKENS:
            if fmt.startswith(tok, i):
                out.append(d.strftime(f) if isinstance(f, str) else f(d))
                i += len(tok)
                break
        else:
            out.append(fmt[i])
            i += 1
    return "".join(out)


def dt_show(c):
    if c.get("dt") is None:
        c["w"].set_text("")
    else:
        c["w"].set_text(fmt_ahk(c.get("fmt", ""), c["dt"]))


def dt_clamp(c, d):
    lo, hi = c.get("range") or (None, None)
    if lo and d < lo:
        d = lo
    if hi and d > hi:
        d = hi
    return d


def dt_set(c, d, notify=False):
    if d is not None:
        d = dt_clamp(c, d)
    if d != c.get("dt"):
        c["dt"] = d
        dt_show(c)
        if notify:
            ev(c["cid"], "Change", 0, always=True)


def dt_parse_time(c):
    """Time-format DateTime: read back what the user typed (h:mm[:ss] [AM|PM])."""
    m = re.match(r"\s*(\d{1,2})(?::(\d{1,2}))?(?::(\d{1,2}))?\s*([ap])?", c["w"].get_text(), re.I)
    base = c.get("dt") or dt.datetime.now().replace(microsecond=0)
    if not m:
        dt_show(c)
        return
    h, mi, s = int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)
    if m.group(4):
        h = h % 12 + (12 if m.group(4).lower() == "p" else 0)
    try:
        dt_set(c, base.replace(hour=h, minute=mi, second=s), notify=True)
    except ValueError:
        pass
    dt_show(c)


def dt_popup(c):
    pop = Gtk.Popover(relative_to=c["w"])
    cal = Gtk.Calendar()
    d = c.get("dt") or dt.datetime.now()
    cal.select_month(d.month - 1, d.year)
    cal.select_day(d.day)

    def picked(_cal):
        y, m0, day = cal.get_date()
        base = c.get("dt") or dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        dt_set(c, base.replace(year=y, month=m0 + 1, day=day), notify=True)
        pop.popdown()
    cal.connect("day-selected-double-click", picked)
    cal.connect("day-selected", lambda _c: picked(_c) if not c.get("_moving") else None)
    cal.connect("month-changed", lambda _c: c.__setitem__("_moving", True) or
                GLib.idle_add(lambda: c.__setitem__("_moving", False)))
    pop.add(cal)
    cal.show()
    pop.popup()


def cal_pick(c, initial=False):
    if c.get("setting"):
        return            # the script set the value; keep its range
    w = c["w"]
    y, m0, d = w.get_date()
    day = dt.datetime(y, m0 + 1, d)
    shift = False
    if not initial:
        ok, state = Gtk.get_current_event_state()
        shift = bool(ok and state & Gdk.ModifierType.SHIFT_MASK)
    rng = c.get("range")
    if shift and rng and rng[0]:
        anchor = c.get("anchor", rng[0])
        c["range"] = sorted([anchor, day])
    elif not (initial and rng):
        c["anchor"] = day
        c["range"] = [day, day]
    cal_mark(c)


def cal_mark(c):
    w = c["w"]
    w.clear_marks()
    lo, hi = c.get("range") or (None, None)
    if not lo:
        return
    y, m0, _ = w.get_date()
    for dd in range(1, 32):
        try:
            day = dt.datetime(y, m0 + 1, dd)
        except ValueError:
            break
        if lo <= day <= hi:
            w.mark_day(dd)


def cal_value(cal):
    y, m0, d = cal.get_date()
    return "%04d%02d%02d" % (y, m0 + 1, d)


def cal_set(cal, v):
    d = parse_stamp(str(v).split("-")[0])
    if d:
        cal.select_month(d.month - 1, d.year)
        cal.select_day(d.day)


# ---------------------------------------------------------------- Hotkey control
HK_NAMES = {"Return": "Enter", "KP_Enter": "NumpadEnter", "BackSpace": "Backspace", "Delete": "Delete",
            "Insert": "Insert", "Home": "Home", "End": "End", "Prior": "PgUp", "Page_Up": "PgUp", "Next": "PgDn",
            "Page_Down": "PgDn", "Up": "Up", "Down": "Down", "Left": "Left", "Right": "Right", "space": "Space",
            "Escape": "Escape", "Pause": "Pause", "Print": "PrintScreen", "Scroll_Lock": "ScrollLock",
            "Caps_Lock": "CapsLock", "Num_Lock": "NumLock", "Menu": "AppsKey", "KP_Add": "NumpadAdd",
            "KP_Subtract": "NumpadSub", "KP_Multiply": "NumpadMult", "KP_Divide": "NumpadDiv",
            "KP_Decimal": "NumpadDot", "KP_Delete": "NumpadDel", "KP_Insert": "NumpadIns", "KP_Home": "NumpadHome",
            "KP_End": "NumpadEnd", "KP_Up": "NumpadUp", "KP_Down": "NumpadDown", "KP_Left": "NumpadLeft",
            "KP_Right": "NumpadRight", "KP_Prior": "NumpadPgUp", "KP_Next": "NumpadPgDn"}
HK_MODS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R", "Super_L", "Super_R",
           "ISO_Level3_Shift"}


def hk_split(hk):
    mods = ""
    while hk[:1] in ("+", "^", "!") and len(hk) > 1:
        mods += hk[0]
        hk = hk[1:]
    return mods, hk


def hk_display(hk):
    if not hk:
        return "None"
    mods, key = hk_split(hk)
    parts = [n for m, n in (("^", "Ctrl"), ("+", "Shift"), ("!", "Alt")) if m in mods]
    return " + ".join(parts + [key.upper() if len(key) == 1 else key])


def hk_key(c, _w, e):
    name = Gdk.keyval_name(e.keyval) or ""
    if name in ("Tab", "ISO_Left_Tab"):
        return False
    st = e.state
    mods = ("+" if st & Gdk.ModifierType.SHIFT_MASK else "") + ("^" if st & Gdk.ModifierType.CONTROL_MASK else "") + \
        ("!" if st & Gdk.ModifierType.MOD1_MASK else "")
    if name in HK_MODS:
        c["w"].set_text(hk_display(mods + " ").rstrip(" ") + " + " if mods else "None")
        return True
    if not mods and name in ("BackSpace", "Delete"):
        c["hk"] = ""
    else:
        ok, kv, *_ = Gdk.Keymap.get_default().translate_keyboard_state(e.hardware_keycode, 0, e.group)
        base = Gdk.keyval_name(kv) if ok else name
        if base in HK_NAMES:
            key = HK_NAMES[base]
        elif re.fullmatch(r"F\d{1,2}", base or ""):
            key = base
        elif base and base.startswith("KP_") and base[3:].isdigit():
            key = "Numpad" + base[3:]
        else:
            ch = chr(Gdk.keyval_to_unicode(kv if ok else e.keyval) or 0)
            key = ch.lower() if ch.isprintable() and ch.strip() else (base or "")
        c["hk"] = mods + key
    c["w"].set_text(hk_display(c["hk"]))
    ev(c["cid"], "Change", 0, always=True)
    return True


# ---------------------------------------------------------------- ListView
def lv_opts(s):
    o = {}
    for tok in str(s or "").split():
        t = tok.lower()
        neg = t.startswith("-")
        t = t.lstrip("+-")
        m = re.fullmatch(r"(check|select|focus|vis|col|icon)(\d*)", t)
        if m:
            name, num = m.group(1), m.group(2)
            if name == "col":
                o["col"] = int(num or 1)
            elif name == "icon":
                o["icon"] = int(num or 0)
            else:
                o[name] = (int(num) != 0 if num else True) and not neg
    return o


def lv_ncols(c):
    return len(c["cols"])


def lv_add_column(c, i):
    tree = c["tree"]
    rend = Gtk.CellRendererText()
    col = Gtk.TreeViewColumn(c["cols"][i], rend, text=i)
    col.set_resizable(True)
    col.set_clickable(not c.get("nosort"))
    col.connect("clicked", lambda _col, i=i: lv_col_click(c, i))
    if c["colw"][i]:
        col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        col.set_fixed_width(c["colw"][i])
    if c["coltype"][i] in ("Integer", "Float"):
        rend.set_property("xalign", 1.0)
    if i == 0:
        pix = Gtk.CellRendererPixbuf()
        col.pack_start(pix, False)
        col.reorder(pix, 0)
        col.set_cell_data_func(pix, lambda _c, cell, model, it, _d: cell.set_property(
            "pixbuf", icon_for(c, model[it][lv_ncols(c) + 1])))
    pos = i + (1 if c.get("checked") else 0)
    tree.insert_column(col, pos)


def lv_build(c, rows=None):
    """(Re)create the store and columns, e.g. after InsertCol/DeleteCol."""
    n = lv_ncols(c)
    keep = lv_selected(c) if "store" in c else []
    store = Gtk.ListStore(*([str] * n), bool, int)
    for r in rows or []:
        store.append([str(x) for x in (r[0] + [""] * n)[:n]] + [bool(r[1]), r[2] if len(r) > 2 else 1])
    tree = c["tree"]
    for col in tree.get_columns():
        tree.remove_column(col)
    tree.set_model(store)
    c["store"] = store
    if c.get("checked"):
        tog = Gtk.CellRendererToggle()
        tog.connect("toggled", lambda _r, path: lv_toggle(c, int(path)))
        tree.append_column(Gtk.TreeViewColumn("", tog, active=n))
    for i in range(n):
        lv_add_column(c, i)
    for r in keep:
        if r < len(store):
            tree.get_selection().select_path(Gtk.TreePath(r))


def lv_rows(c):
    n = lv_ncols(c)
    return [([row[i] for i in range(n)], row[n], row[n + 1]) for row in c["store"]]


def lv_toggle(c, r):
    it = c["store"].get_iter(Gtk.TreePath(r))
    n = lv_ncols(c)
    v = not c["store"][it][n]
    c["store"].set_value(it, n, v)
    ev(c["cid"], "ItemCheck", r + 1, int(v), always=True)


def lv_sort(c, i, desc=None):
    t = c["coltype"][i]
    if desc is None:
        desc = c.get("sortcol") == i and not c.get("sortdesc")
    c["sortcol"], c["sortdesc"] = i, desc

    def key(row):
        v = row[0][i]
        if t in ("Integer", "Float"):
            try:
                return (0, float(v.replace(",", "")))
            except ValueError:
                return (1, 0.0)
        if t == "Logical":
            return [(0, int(p)) if p.isdigit() else (1, p.lower()) for p in re.split(r"(\d+)", v)]
        return v.lower() if not c["casesens"][i] else v
    rows = sorted(lv_rows(c), key=key, reverse=desc)
    c["store"].clear()
    n = lv_ncols(c)
    for r in rows:
        c["store"].append(r[0] + [r[1], r[2]])
    del n


def lv_col_click(c, i):
    if not c.get("nosort"):
        lv_sort(c, i)
    ev(c["cid"], "ColClick", i + 1, always=True)


def lv_apply(c, r, o):
    """Row options for Add/Insert/Modify: Check, Select, Focus, Vis."""
    tree, store = c["tree"], c["store"]
    path = Gtk.TreePath(r)
    sel = tree.get_selection()
    if "check" in o:
        store.set_value(store.get_iter(path), lv_ncols(c), o["check"])
    if "icon" in o:
        store.set_value(store.get_iter(path), lv_ncols(c) + 1, o["icon"])
    if "select" in o:
        if o["select"]:
            sel.select_path(path)
        else:
            sel.unselect_path(path)
    if o.get("focus"):
        tree.set_cursor(path, None, False)
        if o.get("select") is not False:
            sel.select_path(path)
    if o.get("vis"):
        tree.scroll_to_cell(path, None, False, 0, 0)


def lv_selected(c):
    model, paths = c["tree"].get_selection().get_selected_rows()
    return sorted(p.get_indices()[0] for p in paths)


def lv_sel_changed(c):
    now = set(lv_selected(c))
    before = c.get("prevsel", set())
    c["prevsel"] = now
    for r in sorted(before - now):
        ev(c["cid"], "ItemSelect", r + 1, 0)
    for r in sorted(now - before):
        ev(c["cid"], "ItemSelect", r + 1, 1)


def lv_click(c, e, double=False):
    if e.button != 1:
        if e.button == 3:
            hit = c["tree"].get_path_at_pos(int(e.x), int(e.y))
            emit({"event": "ContextMenu", "win": c["win"], "ctrl": c["cid"],
                  "args": [hit[0].get_indices()[0] + 1 if hit else 0, 1, int(e.x), int(e.y)]})
        return False
    hit = c["tree"].get_path_at_pos(int(e.x), int(e.y))
    ev(c["cid"], "Click", hit[0].get_indices()[0] + 1 if hit else 0, always=True)
    return False


def lv_op(c, req):
    do = req["do"]
    store = c["store"]
    n = lv_ncols(c)
    if do in ("add", "insert"):
        o = lv_opts(req.get("opts"))
        start = o.get("col", 1) - 1
        fields = [""] * start + [str(f) for f in req.get("fields", [])]
        row = (fields + [""] * n)[:n] + [False, 1]
        r = req.get("row", 0)
        if do == "insert" and 1 <= r <= len(store):
            store.insert(r - 1, row)
            idx = r - 1
        else:
            store.append(row)
            idx = len(store) - 1
        lv_apply(c, idx, o)
        return idx + 1
    if do == "modify":
        o = lv_opts(req.get("opts"))
        r = req.get("row", 0)
        targets = range(len(store)) if r == 0 else [r - 1]
        start = o.get("col", 1) - 1
        for idx in targets:
            if not 0 <= idx < len(store):
                return 0
            it = store.get_iter(Gtk.TreePath(idx))
            for i, f in enumerate(req.get("fields", [])):
                if start + i < n:
                    store.set_value(it, start + i, str(f))
            lv_apply(c, idx, o)
        return 1
    if do == "delete":
        r = req.get("row", 0)
        if r:
            if not 1 <= r <= len(store):
                return 0
            store.remove(store.get_iter(Gtk.TreePath(r - 1)))
        else:
            store.clear()
        return 1
    if do == "gettext":
        r, col = req["row"], req["col"]
        if not 1 <= col <= n:
            return None
        if r == 0:
            return c["cols"][col - 1]
        return store[r - 1][col - 1] if 1 <= r <= len(store) else None
    if do == "count":
        m = (req.get("mode") or "").lower()
        if m.startswith("s"):
            return len(lv_selected(c))
        if m.startswith("col"):
            return n
        return len(store)
    if do == "getnext":
        start = req.get("start", 0)
        m = (req.get("mode") or "").lower()
        if m.startswith("f"):
            path, _ = c["tree"].get_cursor()
            r = path.get_indices()[0] + 1 if path else 0
            return r if r > start else 0
        if m.startswith("c"):
            for i in range(max(start, 0), len(store)):
                if store[i][n]:
                    return i + 1
            return 0
        for r in lv_selected(c):
            if r + 1 > start:
                return r + 1
        return 0
    if do in ("modifycol", "insertcol"):
        col = req.get("col", 0)
        o = str(req.get("opts") or "")
        title = req.get("title")
        if do == "insertcol":
            pos = col - 1 if 1 <= col <= n else n
            rows = lv_rows(c)
            for k in ("cols", "colw", "coltype", "casesens"):
                c[k].insert(pos, {"cols": title or "", "colw": 0, "coltype": "Text", "casesens": False}[k])
            for r in rows:
                r[0].insert(pos, "")
            lv_build(c, rows)
            col = pos + 1
            n += 1
        if not 1 <= col <= n:
            if do == "modifycol" and col == 0 and not o and title is None:
                for tc in c["tree"].get_columns():
                    tc.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
                return 1
            return 0
        i = col - 1
        tcol = c["tree"].get_columns()[i + (1 if c.get("checked") else 0)]
        sort = None
        for tok in o.split():
            t = tok.lower()
            if t.isdigit():
                c["colw"][i] = int(t)
                tcol.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
                tcol.set_fixed_width(int(t))
            elif t in ("auto", "autohdr"):
                c["colw"][i] = 0
                tcol.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
            elif t in ("integer", "float", "text", "logical"):
                c["coltype"][i] = t.capitalize()
                tcol.get_cells()[0].set_property("xalign", 1.0 if t in ("integer", "float") else 0.0)
            elif t == "case":
                c["casesens"][i] = True
            elif t == "nosort":
                tcol.set_clickable(False)
            elif t in ("sort", "sortdesc"):
                sort = t == "sortdesc"
            elif t == "right":
                tcol.get_cells()[0].set_property("xalign", 1.0)
            elif t == "center":
                tcol.get_cells()[0].set_property("xalign", 0.5)
            elif t == "left":
                tcol.get_cells()[0].set_property("xalign", 0.0)
        if title is not None:
            c["cols"][i] = str(title)
            tcol.set_title(str(title))
        if sort is not None:
            lv_sort(c, i, sort)
        return col if do == "insertcol" else 1
    if do == "deletecol":
        col = req.get("col", 0)
        if not 1 <= col <= n:
            return 0
        rows = lv_rows(c)
        for k in ("cols", "colw", "coltype", "casesens"):
            del c[k][col - 1]
        for r in rows:
            del r[0][col - 1]
        lv_build(c, rows)
        return 1
    if do == "colwidth":
        cols = c["tree"].get_columns()
        i = int(req["col"]) - 1 + (1 if c.get("checked") else 0)
        if not 0 <= i < len(cols):
            return 0
        if req.get("width") is not None:
            cols[i].set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            cols[i].set_fixed_width(max(int(req["width"]), 1))
            return 1
        return cols[i].get_width() or cols[i].get_fixed_width()
    if do == "ensurevisible":
        r = int(req["row"]) - 1
        if not 0 <= r < len(store):
            return 0
        c["tree"].scroll_to_cell(Gtk.TreePath(r), None, False, 0.0, 0.0)
        return 1
    if do == "content":
        o = (req.get("opts") or "").lower().split()
        if "count" in o:
            if "selected" in o:
                return len(lv_selected(c))
            if "focused" in o:
                return 1 if c["tree"].get_cursor()[0] else 0
            if "col" in o:
                return n
            return len(store)
        cols = None
        for t in o:
            if t.startswith("col") and t[3:].isdigit():
                cols = [int(t[3:]) - 1]
        rows = range(len(store))
        if "selected" in o:
            rows = lv_selected(c)
        elif "focused" in o:
            p = c["tree"].get_cursor()[0]
            rows = [p.get_indices()[0]] if p else []
        return "\n".join("\t".join(store[r][i] for i in (cols or range(n)) if i < n) for r in rows)
    raise ValueError(f"unknown ListView action {do}")


# ---------------------------------------------------------------- TreeView
def tv_iter(c, item):
    ref = c["ids"].get(item)
    if ref is None or not ref.valid():
        return None
    return c["store"].get_iter(ref.get_path())


def tv_id(c, it):
    return c["store"][it][2] if it is not None else 0


def tv_dfs(store, it=None):
    child = store.iter_children(it)
    while child is not None:
        yield child
        yield from tv_dfs(store, child)
        child = store.iter_next(child)


def tv_apply(c, it, o, name=None):
    store, tree = c["store"], c["tree"]
    if name is not None:
        store.set_value(it, 0, name)
    path = store.get_path(it)
    for tok in str(o or "").split():
        t = tok.lower()
        neg = t.startswith("-")
        t = t.lstrip("+-")
        m = re.fullmatch(r"(expand|check|bold|select|vis|visfirst|icon)(\d*)", t)
        if not m:
            continue
        if m.group(1) == "icon":
            store.set_value(it, 4, int(m.group(2) or 0))
            continue
        key, num = m.group(1), m.group(2)
        on = (int(num) != 0 if num else True) and not neg
        if key == "expand":
            item = store[it][2]
            if on:
                c.setdefault("want_open", set()).add(item)
                tree.expand_to_path(path)
            else:
                c.get("want_open", set()).discard(item)
                tree.collapse_row(path)
        elif key == "check":
            store.set_value(it, 1, on)
        elif key == "bold":
            store.set_value(it, 3, Pango.Weight.BOLD if on else Pango.Weight.NORMAL)
        elif key == "select" and on:
            if path.get_depth() > 1:
                parent = path.copy()
                parent.up()
                tree.expand_to_path(parent)
            tree.get_selection().select_path(path)
            tree.set_cursor(path, None, False)
        elif key in ("vis", "visfirst") and on:
            tree.scroll_to_cell(path, None, key == "visfirst", 0, 0)


def tv_op(c, req):
    do = req["do"]
    store = c["store"]
    if do == "expand":
        it = tv_iter(c, req["item"])
        if it is None:
            return 0
        path = store.get_path(it)
        tree = c["tree"]
        how = req.get("how", "expand")
        if how == "toggle":
            how = "collapse" if tree.row_expanded(path) else "expand"
        if how == "collapse":
            return int(tree.collapse_row(path))
        if not store.iter_has_child(it):
            return 0
        tree.expand_row(path, False)
        return 1
    if do == "add":
        parent = tv_iter(c, req.get("parent", 0)) if req.get("parent") else None
        if req.get("parent") and parent is None:
            return 0
        name = str(req.get("name", ""))
        o = str(req.get("opts") or "")
        toks = o.lower().split()
        row = [name, False, next(_tv_ids), Pango.Weight.NORMAL, 1]
        if "first" in toks:
            it = store.prepend(parent, row)
        elif "sort" in toks:
            sib = store.iter_children(parent)
            while sib is not None and store[sib][0].lower() <= name.lower():
                sib = store.iter_next(sib)
            it = store.insert_before(parent, sib, row) if sib is not None else store.append(parent, row)
        else:
            after = next((tv_iter(c, int(t)) for t in toks if t.isdigit()), None)
            it = store.insert_after(parent, after, row) if after is not None else store.append(parent, row)
        c["ids"][row[2]] = Gtk.TreeRowReference.new(store, store.get_path(it))
        if parent is not None and store[parent][2] in c.get("want_open", ()):
            c["tree"].expand_row(store.get_path(parent), False)     # Expand set before the item had children
        tv_apply(c, it, o)
        return row[2]
    if do == "modify":
        it = tv_iter(c, req["item"])
        if it is None:
            return 0
        if req.get("opts") is None and req.get("name") is None:
            tv_apply(c, it, "Select")
        else:
            tv_apply(c, it, req.get("opts"), req.get("name"))
        return req["item"]
    if do == "delete":
        if not req.get("item"):
            store.clear()
            c["ids"].clear()
            return 1
        it = tv_iter(c, req["item"])
        if it is None:
            return 0
        gone = [store[x][2] for x in tv_dfs(store, it)] + [req["item"]]
        store.remove(it)
        for g in gone:
            c["ids"].pop(g, None)
        return 1
    if do == "selection":
        model, it = c["tree"].get_selection().get_selected()
        return tv_id(c, it)
    if do == "count":
        return sum(1 for _ in tv_dfs(store))
    it = tv_iter(c, req.get("item", 0)) if req.get("item") else None
    if req.get("item") and it is None:
        return 0
    if do == "parent":
        return tv_id(c, store.iter_parent(it)) if it is not None else 0
    if do == "child":
        return tv_id(c, store.iter_children(it))
    if do == "prev":
        return tv_id(c, store.iter_previous(it)) if it is not None else 0
    if do == "next":
        m = (req.get("mode") or "").lower()
        if not m:
            return tv_id(c, store.iter_next(it) if it is not None else store.get_iter_first())
        seen = it is None
        for x in tv_dfs(store):
            if seen and (m.startswith("f") or store[x][1]):
                return store[x][2]
            if not seen and store[x][2] == req["item"]:
                seen = True
        return 0
    if do == "gettext":
        return store[it][0] if it is not None else None
    if do == "get":
        attr = (req.get("attr") or "").lower()
        if attr.startswith("e"):
            return req["item"] if c["tree"].row_expanded(store.get_path(it)) else 0
        if attr.startswith("c"):
            return req["item"] if store[it][1] else 0
        if attr.startswith("b"):
            return req["item"] if store[it][3] == Pango.Weight.BOLD else 0
        return 0
    raise ValueError(f"unknown TreeView action {do}")


def tv_item_at(c, e):
    hit = c["tree"].get_path_at_pos(int(e.x), int(e.y))
    return c["store"][c["store"].get_iter(hit[0])][2] if hit else 0


# ---------------------------------------------------------------- image lists (IL_Create/IL_Add, SetImageList)
def load_icon(path, size):
    from gi.repository import GdkPixbuf
    if path and os.path.exists(path) and not path.lower().endswith((".exe", ".dll", ".cpl", ".scr", ".ocx")):
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
        except GLib.Error:
            pass
    theme = Gtk.IconTheme.get_default()
    name = path if path and "/" not in path and theme.has_icon(path) else "application-x-executable"
    try:
        return theme.load_icon(name, size, 0)
    except GLib.Error:
        return None


def icon_for(c, n):
    pix = c.get("pix")
    return pix[n - 1] if pix and 1 <= n <= len(pix) else None


# ---------------------------------------------------------------- control values
def lb_selected(c):
    model, paths = c["tree"].get_selection().get_selected_rows()
    return [p.get_indices()[0] for p in paths]


def text_of(c):
    w = c["w"]
    t = c["type"]
    if t == "IPAddress":
        return ip_text(c)
    if t == "Edit":
        if "tv" in c:
            buf = c["tv"].get_buffer()
            return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        return w.get_text()
    if t in ("Text", "Link", "StatusBar"):
        return c["label"].get_text() if "label" in c else w.get_text()
    if t in ("Button", "CheckBox", "Radio"):
        return (w.get_label() or "").replace("_", "&") if w.get_use_underline() else (w.get_label() or "")
    if t == "DDL":
        return w.get_active_text() or ""
    if t == "ComboBox":
        return w.get_child().get_text()
    if t == "ListBox":
        sel = lb_selected(c)
        if c.get("multi"):
            return [c["store"][i][0] for i in sel]
        return c["store"][sel[0]][0] if sel else ""
    if t == "GroupBox":
        return w.get_label() or ""
    if t == "Tab":
        p = w.get_current_page()
        return w.get_tab_label_text(w.get_nth_page(p)) if p >= 0 else ""
    if t == "DateTime":
        return w.get_text()
    if t == "Hotkey":
        return c.get("hk", "")
    if t == "UpDown":
        return str(int(w.get_value()))
    if t == "MonthCal":
        return cal_value(w)
    if t == "TreeView":
        model, it = c["tree"].get_selection().get_selected()
        return c["store"][it][0] if it is not None else ""
    if t == "Slider":
        return str(int(w.get_value()))
    if t == "Progress":
        return str(int(round(w.get_fraction() * c.get("span", 100))) + c.get("lo", 0))
    return ""


def value_of(c):
    w = c["w"]
    t = c["type"]
    if t in ("CheckBox", "Radio"):
        if t == "CheckBox" and w.get_inconsistent():
            return -1
        return 1 if w.get_active() else 0
    if t in ("DDL", "ComboBox"):
        i = w.get_active()
        return i + 1 if i >= 0 else 0
    if t == "ListBox":
        sel = lb_selected(c)
        if c.get("multi"):
            return [i + 1 for i in sel]
        return sel[0] + 1 if sel else 0
    if t in ("Slider", "UpDown"):
        return int(w.get_value())
    if t == "Progress":
        return int(round(w.get_fraction() * c.get("span", 100))) + c.get("lo", 0)
    if t == "ListView":
        return ""
    if t == "Tab":
        return w.get_current_page() + 1
    if t == "DateTime":
        return stamp(c["dt"]) if c.get("dt") else ""
    if t == "MonthCal":
        if c.get("multi") and c.get("range") and c["range"][0]:
            lo, hi = c["range"]
            return lo.strftime("%Y%m%d") + "-" + hi.strftime("%Y%m%d")
        v = cal_value(w)
        return v + "-" + v if c.get("multi") else v
    if t == "TreeView":
        model, it = c["tree"].get_selection().get_selected()
        return tv_id(c, it)
    if t == "Hotkey":
        return c.get("hk", "")
    if t == "Picture":
        return c.get("file", "")
    return text_of(c)


def set_value(c, v):
    w = c["w"]
    t = c["type"]
    if t in ("CheckBox", "Radio"):
        n = int(v or 0)
        if t == "CheckBox":
            w.set_inconsistent(n == -1)
        w.set_active(n == 1)
    elif t in ("DDL", "ComboBox"):
        w.set_active(int(v) - 1)
        if int(v) == 0 and t == "ComboBox":
            w.get_child().set_text("")
    elif t == "ListBox":
        sel = c["tree"].get_selection()
        if not c.get("multi") or int(v) == 0:     # Multi: Choose(n) adds to the selection (LB_SETSEL)
            sel.unselect_all()
        if int(v) > 0:
            sel.select_path(Gtk.TreePath(int(v) - 1))
    elif t in ("Slider", "UpDown"):
        w.set_value(float(v))
    elif t == "Progress":
        f = (float(v) - c.get("lo", 0)) / (c.get("span", 100) or 1)
        w.set_fraction(max(0.0, min(f, 1.0)))
    elif t == "Tab":
        w.set_current_page(int(v) - 1)
        sync_win(c["win"])
    elif t == "DateTime":
        dt_set(c, parse_stamp(v) if str(v) else None)
    elif t == "MonthCal":
        sv = str(v)
        if c.get("multi") and "-" in sv:
            lo, hi = sv.split("-", 1)
            c["range"] = [parse_stamp(lo), parse_stamp(hi or lo)]
            c["anchor"] = c["range"][0]
            c["setting"] = True
            try:
                cal_set(w, lo)
            finally:
                c["setting"] = False
            cal_mark(c)
        else:
            cal_set(w, sv)
            if c.get("multi"):
                d = parse_stamp(sv)
                c["range"] = [d, d]
                cal_mark(c)
    elif t == "Hotkey":
        c["hk"] = str(v)
        w.set_text(hk_display(c["hk"]))
    elif t == "Picture":
        load_picture(c, str(v))
    else:
        set_text(c, str(v))


def set_text(c, s):
    w = c["w"]
    t = c["type"]
    if t == "IPAddress":
        ip_set(c, s)
    elif t == "Edit":
        if "tv" in c:
            c["tv"].get_buffer().set_text(s)
        else:
            w.set_text(s)
    elif t in ("Text", "StatusBar"):
        (c.get("label") or w).set_text(s)
    elif t == "Link":
        w.set_markup(link_markup(s))
    elif t in ("Button", "CheckBox", "Radio"):
        w.set_label(mnemonic(s))
    elif t == "GroupBox":
        w.set_label(s)
    elif t == "ComboBox":
        w.get_child().set_text(s)
    elif t in ("DDL", "ListBox", "Tab"):
        i = find_item(c, s, prefix=True)
        if i < 0:
            raise ValueError("Item not found: " + s)
        set_value(c, i + 1)
    elif t == "DateTime":
        c["fmt"] = s
        dt_show(c)
    elif t == "Picture":
        load_picture(c, s)


def mnemonic(s):
    """AutoHotkey '&x' mnemonics and '&&' literal ampersands -> GTK '_x' / '&'."""
    return s.replace("_", "__").replace("&&", "\0").replace("&", "_").replace("\0", "&")


def link_markup(s):
    parts = re.split(r"(<a\b[^>]*>.*?</a>)", s, flags=re.S | re.I)
    out = []
    for p in parts:
        m = re.fullmatch(r"<a\b([^>]*)>(.*?)</a>", p, flags=re.S | re.I)
        if m:
            href = re.search(r"""(?:href|id)\s*=\s*["']([^"']*)["']""", m.group(1), re.I)
            uri = href.group(1) if href else m.group(2)
            out.append('<a href="%s">%s</a>' % (GLib.markup_escape_text(uri or "#"), GLib.markup_escape_text(m.group(2))))
        else:
            out.append(GLib.markup_escape_text(p))
    return "".join(out)


def items_of(c):
    t = c["type"]
    if t in ("DDL", "ComboBox"):
        return [r[0] for r in c["w"].get_model()]
    if t == "ListBox":
        return [r[0] for r in c["store"]]
    if t == "Tab":
        nb = c["w"]
        return [nb.get_tab_label_text(nb.get_nth_page(i)) for i in range(nb.get_n_pages())]
    raise ValueError("The control type has no items.")


def find_item(c, s, prefix=False):
    s = s.lower()
    for i, it in enumerate(items_of(c)):
        il = it.lower()
        if il == s or (prefix and il.startswith(s)):
            return i
    return -1


def load_picture(c, path):
    c["file"] = path
    w = c.get("img") or c["w"]
    want_w, want_h = c.get("pw") or -1, c.get("ph") or -1
    if not os.path.exists(path):
        w.clear()
        return
    try:
        from gi.repository import GdkPixbuf
        if want_w > 0 or want_h > 0:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, want_w, want_h, want_w < 0 or want_h < 0)
        else:
            pb = GdkPixbuf.Pixbuf.new_from_file(path)
        w.set_from_pixbuf(pb)
    except GLib.Error:
        w.set_from_file(path)


def edit_buffer_info(c):
    """(text, caret offset, selection start, selection end) of an Edit."""
    if "tv" in c:
        buf = c["tv"].get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        caret = buf.get_iter_at_mark(buf.get_insert()).get_offset()
        b = buf.get_selection_bounds()
        s, e = (b[0].get_offset(), b[1].get_offset()) if b else (caret, caret)
    else:
        w = c["w"]
        text = w.get_text()
        caret = w.get_position()
        ok, s, e = (lambda r: (True, r[1], r[2]) if r[0] else (False, caret, caret))(w.get_selection_bounds())
    return text, caret, s, e


def query(c, what):
    t = c["type"]
    if what == "items":
        if t == "ListView":
            return ["\t".join(r[0]) for r in lv_rows(c)]
        return items_of(c)
    if what == "focused":
        return int(any(w.has_focus() for w in style_targets(c)))
    if t == "Edit":
        text, caret, s, e = edit_buffer_info(c)
        if what == "lines":
            return text.split("\n")
        if what == "caret":
            before = text[:caret]
            return [before.count("\n") + 1, caret - (before.rfind("\n") + 1) + 1]
        if what == "seltext":
            return text[s:e]
        if what == "sel":
            return [s, e]
    if what == "selected" and t == "ListBox":
        return lb_selected(c)
    if what == "range" and t in ("Slider", "UpDown"):
        adj = c["w"].get_adjustment()
        return [int(adj.get_lower()), int(adj.get_upper())]
    if what == "range" and t == "Progress":
        return [c.get("lo", 0), c.get("lo", 0) + c.get("span", 100)]
    if what == "top" and t == "ListBox":
        r = c["tree"].get_visible_range()
        return r[1].get_indices()[0] if r and r[0] else 0
    if what == "top" and t in ("DDL", "ComboBox"):
        return 0
    if what == "dropped" and t in ("DDL", "ComboBox"):
        return int(bool(c["w"].get_property("popup-shown")))
    raise ValueError(f"unsupported query {what} for {t}")


def ip_insert(entry, new, length, pos, c, i):
    """Digits only; a dot or a full field moves on to the next field, as the Win32 control does."""
    digits = "".join(ch for ch in new if ch.isdigit())
    if digits != new:
        entry.stop_emission_by_name("insert-text")
        if "." in new and i < 3:
            GLib.idle_add(lambda: c["fields"][i + 1].grab_focus() and False)
        if digits:
            GLib.idle_add(lambda: (entry.insert_text(digits, entry.get_position()), False)[1])
        return
    if len(entry.get_text()) + len(digits) >= 3 and i < 3 and not quiet:
        GLib.idle_add(lambda: (c["fields"][i + 1].grab_focus(), False)[1])


def ip_clamp(c, i):
    e = c["fields"][i]
    if e.get_text():
        lo, hi = c["ranges"][i]
        v = min(max(int(e.get_text()), lo), hi)
        if str(v) != e.get_text():
            e.set_text(str(v))


def ip_set(c, text):
    parts = str(text).split(".") if str(text) else []
    for i, e in enumerate(c["fields"]):
        e.set_text(parts[i].strip() if i < len(parts) else "")


def ip_text(c):
    return ".".join(e.get_text() or "0" for e in c["fields"])


def ip_op(c, req):
    """IPM_ messages: get (fields, None = blank), set, clear, blank, range, focus."""
    do = req["do"]
    f = c["fields"]
    if do == "get":
        return [int(e.get_text()) if e.get_text() else None for e in f]
    if do == "set":
        for e, v in zip(f, req["values"]):
            e.set_text(str(v))
        return True
    if do == "clear":
        for e in f:
            e.set_text("")
        return True
    if do == "blank":
        return int(not any(e.get_text() for e in f))
    if do == "range":
        c["ranges"][int(req["field"])] = [int(req["lo"]), int(req["hi"])]
        ip_clamp(c, int(req["field"]))
        return True
    if do == "focus":
        i = int(req["field"])
        if i > 3:
            i = next((k for k, e in enumerate(f) if not e.get_text()), 0)
        f[i].grab_focus()
        f[i].select_region(0, -1)
        return True
    raise ValueError(f"unknown ip op {do}")


def ctl_op(op, c, req):
    """Win32 control messages that need direct widget access (EM_SETSEL, LB_SETSEL, *_SETRANGE, LB_SETTOPINDEX)."""
    t = c["type"]
    if op == "editsel":
        start, end = int(req["start"]), int(req["end"])
        if "tv" in c:
            buf = c["tv"].get_buffer()
            n = buf.get_char_count()
            end = n if end < 0 or end > n else end
            if start < 0:
                ins = buf.get_iter_at_mark(buf.get_insert())
                buf.place_cursor(ins)
                return True
            buf.select_range(buf.get_iter_at_offset(end), buf.get_iter_at_offset(min(start, n)))
            c["tv"].scroll_mark_onscreen(buf.get_insert())
        else:
            w = c["w"]
            n = len(w.get_text())
            end = n if end < 0 or end > n else end
            if start < 0:
                w.select_region(w.get_position(), w.get_position())
                return True
            # select_region(start, end) leaves the cursor at end, as EM_SETSEL does
            w.select_region(min(start, n), end)
        return True
    if op == "lbsel":
        sel = c["tree"].get_selection()
        i, on = int(req["index"]), bool(req["on"])
        if i < 0:
            (sel.select_all if on else sel.unselect_all)()
        elif i < len(c["store"]):
            (sel.select_path if on else sel.unselect_path)(Gtk.TreePath(i))
        else:
            return False
        return True
    if op == "range":
        lo, hi = int(req["lo"]), int(req["hi"])
        if t in ("Slider", "UpDown"):
            adj = c["w"].get_adjustment()
            adj.set_lower(min(lo, hi))
            adj.set_upper(max(lo, hi))
            c["w"].set_value(min(max(c["w"].get_value(), min(lo, hi)), max(lo, hi)))
        elif t == "Progress":
            cur = value_of(c)
            c["lo"], c["span"] = lo, (hi - lo) or 1
            set_value(c, min(max(cur, lo), hi))
        return True
    if op == "lbtop":
        i = int(req["index"])
        if t == "ListBox" and 0 <= i < len(c["store"]):
            c["tree"].scroll_to_cell(Gtk.TreePath(i), None, True, 0.0, 0.0)
            return True
        return False
    raise ValueError(f"unknown op {op}")


# ---------------------------------------------------------------- creating controls
def make(win, cid, t, opts):
    text = opts.get("text", "")
    items = opts.get("items", [])
    c = {"type": t, "win": win.id, "cid": cid, "uv": not opts.get("hidden"), "font": opts.get("font"),
         "color": opts.get("color"), "bg": opts.get("bg")}
    if opts.get("tab"):
        c["tab"] = opts["tab"]
    placed = False
    if t == "Text":
        w = Gtk.Label(label=text, xalign=0, yalign=0)
        w.set_line_wrap(bool(opts.get("w")))   # AHK sizes an unwidthed Text to fit its contents
        if opts.get("center"):
            w.set_justify(Gtk.Justification.CENTER)
            w.set_xalign(0.5)
        elif opts.get("right"):
            w.set_justify(Gtk.Justification.RIGHT)
            w.set_xalign(1.0)
        if c["bg"] or opts.get("events"):
            box = Gtk.EventBox()
            box.add(w)
            box.connect("button-press-event", lambda _b, e: ev(cid, "DoubleClick" if e.type == Gdk.EventType
                                                                ._2BUTTON_PRESS else "Click", 0, always=True)
                        if e.button == 1 and e.type in (Gdk.EventType.BUTTON_PRESS, Gdk.EventType._2BUTTON_PRESS)
                        else None)
            c["label"] = w
            w = box
    elif t == "Link":
        w = Gtk.Label(xalign=0)
        w.set_markup(link_markup(text))
        w.connect("activate-link", lambda _w, uri: ev(cid, "Click", uri if uri != "#" else "", always=True) or True)
    elif t == "Edit":
        if opts.get("multi"):
            tv = Gtk.TextView()
            tv.get_buffer().set_text(text)
            tv.set_wrap_mode(Gtk.WrapMode.NONE if opts.get("nowrap") else Gtk.WrapMode.WORD_CHAR)
            tv.set_editable(not opts.get("readonly"))
            w = Gtk.ScrolledWindow()
            w.set_shadow_type(Gtk.ShadowType.IN)
            w.add(tv)
            c["tv"] = tv
            tv.get_buffer().connect("changed", lambda *_: ev(cid, "Change", 0, always=True))
            tv.connect("focus-in-event", lambda *_: ev(cid, "Focus", 0, always=True) and False)
            tv.connect("focus-out-event", lambda *_: ev(cid, "LoseFocus", 0, always=True) and False)
        else:
            w = Gtk.Entry(text=text)
            w.set_activates_default(True)     # Enter in a single-line Edit presses the Default button (Win32 dialogs)
            w.set_visibility(not opts.get("password"))
            w.set_editable(not opts.get("readonly"))
            if opts.get("limit"):
                w.set_max_length(int(opts["limit"]))
            if opts.get("number"):
                w.connect("insert-text", lambda e, new, _n, _p: e.stop_emission_by_name("insert-text")
                          if not new.isdigit() else None)
            if opts.get("center"):
                w.set_alignment(0.5)
            elif opts.get("right"):
                w.set_alignment(1.0)
            w.connect("changed", lambda *_: ev(cid, "Change", 0, always=True))
            w.connect("focus-in-event", lambda *_: ev(cid, "Focus", 0, always=True) and False)
            w.connect("focus-out-event", lambda *_: ev(cid, "LoseFocus", 0, always=True) and False)
    elif t == "Button":
        w = Gtk.Button(label=mnemonic(text), use_underline=True)
        w.connect("clicked", lambda *_: ev(cid, "Click", 0, always=True))
        if opts.get("default"):
            w.set_can_default(True)
            GLib.idle_add(lambda: (w.grab_default(), False)[1])
    elif t == "CheckBox":
        w = Gtk.CheckButton(label=mnemonic(text), use_underline=True)
        chk = opts.get("checked")
        if chk == -1:
            w.set_inconsistent(True)
        w.set_active(chk == 1 or chk is True)
        w.connect("toggled", lambda b: (b.set_inconsistent(False), ev(cid, "Click", 0, always=True)))
    elif t == "Radio":
        if opts.get("group") or win.radio_group is None or not opts.get("follows_radio"):
            win.radio_group = None
        w = Gtk.RadioButton.new_with_mnemonic_from_widget(win.radio_group, mnemonic(text))
        if win.radio_group is None:
            win.radio_group = w
            # a GTK radio group always has one active button; AutoHotkey's can have none
            c["none"] = Gtk.RadioButton.new_from_widget(w)
            c["none"].set_active(True)
        w.set_active(bool(opts.get("checked")))
        w.connect("toggled", lambda b: b.get_active() and ev(cid, "Click", 0, always=True))
    elif t in ("DDL", "ComboBox"):
        w = Gtk.ComboBoxText.new_with_entry() if t == "ComboBox" else Gtk.ComboBoxText()
        for it in items:
            w.append_text(it)
        if opts.get("choose"):
            w.set_active(int(opts["choose"]) - 1)
        w.connect("changed", lambda *_: ev(cid, "Change", 0))
        if t == "ComboBox":
            w.get_child().connect("changed", lambda *_: w.get_active() < 0 and ev(cid, "Change", 0, always=True))
    elif t == "ListBox":
        store = Gtk.ListStore(str)
        for it in items:
            store.append([it])
        tree = Gtk.TreeView(model=store)
        tree.set_headers_visible(False)
        tree.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
        c["multi"] = bool(opts.get("multi") or opts.get("8"))
        if c["multi"]:
            tree.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        tree.get_selection().connect("changed", lambda *_: ev(cid, "Change", 0))
        tree.connect("row-activated", lambda _t, path, _c: ev(cid, "DoubleClick", path.get_indices()[0] + 1,
                                                               always=True))
        if opts.get("choose"):
            tree.get_selection().select_path(Gtk.TreePath(int(opts["choose"]) - 1))
        w = Gtk.ScrolledWindow()
        w.set_shadow_type(Gtk.ShadowType.IN)
        w.add(tree)
        c["tree"], c["store"] = tree, store
    elif t == "ListView":
        cols = opts.get("columns") or [""]
        tree = Gtk.TreeView()
        c.update(tree=tree, cols=list(cols), colw=[0] * len(cols), coltype=["Text"] * len(cols),
                 casesens=[False] * len(cols), checked=bool(opts.get("checked")), nosort=bool(opts.get("nosort")))
        lv_build(c)
        tree.set_headers_visible(not opts.get("hdr_off"))
        tree.set_grid_lines(Gtk.TreeViewGridLines.BOTH if opts.get("grid") else Gtk.TreeViewGridLines.NONE)
        sel = tree.get_selection()
        sel.set_mode(Gtk.SelectionMode.SINGLE if opts.get("multi") is False else Gtk.SelectionMode.MULTIPLE)
        sel.connect("changed", lambda *_: lv_sel_changed(c))
        tree.connect("row-activated", lambda _t, path, _c: ev(cid, "DoubleClick", path.get_indices()[0] + 1,
                                                               always=True))
        tree.connect("button-release-event", lambda _t, e: lv_click(c, e))
        tree.connect("button-press-event", lambda _t, e: e.button == 3 and lv_click(c, e))
        w = Gtk.ScrolledWindow()
        w.set_shadow_type(Gtk.ShadowType.IN)
        w.add(tree)
    elif t == "TreeView":
        store = Gtk.TreeStore(str, bool, int, int, int)      # text, checked, item ID, weight, icon
        tree = Gtk.TreeView(model=store)
        tree.set_headers_visible(False)
        col = Gtk.TreeViewColumn()
        pix = Gtk.CellRendererPixbuf()
        col.pack_start(pix, False)
        col.set_cell_data_func(pix, lambda _c, cell, model, it, _d: cell.set_property("pixbuf",
                                                                                       icon_for(c, model[it][4])))
        if opts.get("checked"):
            tog = Gtk.CellRendererToggle()

            def toggled(_r, path):
                it = store.get_iter(Gtk.TreePath.new_from_string(path))
                store.set_value(it, 1, not store[it][1])
                ev(cid, "ItemCheck", store[it][2], int(store[it][1]), always=True)
            tog.connect("toggled", toggled)
            col.pack_start(tog, False)
            col.add_attribute(tog, "active", 1)
        rend = Gtk.CellRendererText()
        col.pack_start(rend, True)
        col.add_attribute(rend, "text", 0)
        col.add_attribute(rend, "weight", 3)
        tree.append_column(col)
        tree.set_enable_tree_lines(opts.get("lines") is not False)
        tree.get_selection().connect("changed", lambda s: ev(cid, "ItemSelect", tv_id(c, s.get_selected()[1])))
        tree.connect("row-activated", lambda _t, path, _c: ev(cid, "DoubleClick", store[store.get_iter(path)][2],
                                                               always=True))
        tree.connect("row-expanded", lambda _t, it, _p: ev(cid, "ItemExpand", store[it][2], 1, always=True))
        tree.connect("row-collapsed", lambda _t, it, _p: ev(cid, "ItemExpand", store[it][2], 0, always=True))
        tree.connect("button-release-event", lambda _t, e: e.button == 1 and
                     ev(cid, "Click", tv_item_at(c, e), always=True) and False)
        w = Gtk.ScrolledWindow()
        w.set_shadow_type(Gtk.ShadowType.IN)
        w.add(tree)
        c.update(tree=tree, store=store, ids={})
    elif t == "Slider":
        lo, hi = opts.get("range", [0, 100])
        vert = bool(opts.get("vertical"))
        w = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL if vert else Gtk.Orientation.HORIZONTAL,
                                     min(lo, hi), max(lo, hi), 1)
        w.set_draw_value(bool(opts.get("tooltip")))
        w.set_inverted(vert and not opts.get("invert") or (not vert and bool(opts.get("invert"))))
        if opts.get("line"):
            w.get_adjustment().set_page_increment(int(opts["line"]))
        w.set_value(float(text or lo))
        w.connect("value-changed", lambda *_: ev(cid, "Change", 0, always=True))
    elif t == "Progress":
        lo, hi = opts.get("range", [0, 100])
        c["lo"], c["span"] = lo, (hi - lo) or 1
        w = Gtk.ProgressBar()
        if opts.get("vertical"):
            w.set_orientation(Gtk.Orientation.VERTICAL)
            w.set_inverted(True)
        w.set_fraction(max(0.0, min((float(text or lo) - lo) / c["span"], 1.0)))
    elif t == "IPAddress":
        # SysIPAddress32: four 0-255 fields separated by dots
        w = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        w.get_style_context().add_class("linked")
        fields = []
        for i in range(4):
            e = Gtk.Entry(width_chars=3, max_length=3, xalign=0.5)
            e.set_input_purpose(Gtk.InputPurpose.DIGITS)
            e.connect("insert-text", ip_insert, c, i)
            e.connect("changed", lambda _e, i=i: ev(cid, "Change", i))
            e.connect("focus-out-event", lambda _e, _v, i=i: ip_clamp(c, i) and False)
            fields.append(e)
            w.pack_start(e, True, True, 0)
            if i < 3:
                w.pack_start(Gtk.Label(label="."), False, False, 2)
        c["fields"] = fields
        c["ranges"] = [[0, 255] for _ in range(4)]
        ip_set(c, text)
    elif t == "GroupBox":
        w = Gtk.Frame(label=text)
    elif t == "Picture":
        w = Gtk.Image()
        c["img"] = w
        c["pw"], c["ph"] = opts.get("w"), opts.get("h")
        load_picture(c, text)
        box = Gtk.EventBox()
        box.add(w)
        box.connect("button-press-event", lambda _b, e: ev(cid, "DoubleClick" if e.type == Gdk.EventType
                                                            ._2BUTTON_PRESS else "Click", 0, always=True)
                    if e.button == 1 else None)
        c["img"] = w
        c["label"] = w
        w = box
    elif t == "StatusBar":
        # docked along the bottom edge of the window, like a Win32 status bar
        lbl = Gtk.Label(label=text, xalign=0)
        lbl.set_margin_start(6)
        lbl.set_margin_top(2)
        lbl.set_margin_bottom(2)
        parts = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        parts.pack_start(lbl, True, True, 0)
        w = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        w.pack_start(Gtk.Separator(), False, False, 0)
        w.pack_start(parts, False, False, 0)
        c["label"] = lbl
        c["parts"], c["partbox"] = [lbl], parts
        win.box.pack_end(w, False, False, 0)
        win.box.reorder_child(w, 0)
        placed = True
    elif t == "Tab":
        w = Gtk.Notebook()
        w.set_scrollable(True)
        c["w"] = w
        for it in items:
            tab_add_page(c, it)
        if opts.get("choose"):
            w.set_current_page(int(opts["choose"]) - 1)
        w.connect("switch-page", lambda _nb, _p, _n: GLib.idle_add(lambda: (sync_win(win.id),
                                                                              ev(cid, "Change", 0), False)[-1]))
    elif t == "UpDown":
        lo, hi = opts.get("range", [0, 100])
        b = ctrls.get(opts.get("buddy") or 0)
        if b is not None and b["type"] == "Edit" and isinstance(b["w"], Gtk.Entry):
            try:
                start = float(text) if text != "" else float(b["w"].get_text().replace(",", "") or lo)
            except ValueError:
                start = lo
        else:
            start = float(text or lo)
            b = None
        adj = Gtk.Adjustment(value=min(max(start, min(lo, hi)), max(lo, hi)), lower=min(lo, hi), upper=max(lo, hi),
                             step_increment=1 if lo <= hi else -1, page_increment=10)
        w = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=0)
        w.set_wrap(bool(opts.get("wrap")))
        if not opts.get("0x80"):
            # the buddy shows thousands separators unless UDS_NOTHOUSANDS (0x80) is given, as on Windows
            w.connect("output", lambda sp: (sp.set_text(f"{int(sp.get_adjustment().get_value()):,}"), True)[1])
            strip = lambda sp, *_: (sp.set_text(sp.get_text().replace(",", "")) if "," in sp.get_text() else None,
                                    False)[1]
            w.connect("activate", strip)
            w.connect("focus-out-event", strip)
            w.set_text(f"{int(adj.get_value()):,}")
        w.connect("value-changed", lambda *_: ev(cid, "Change", 0, always=True))
        if b is not None:
            old = b["w"]
            parent = old.get_parent()
            x, y = parent.child_get(old, "x", "y")
            sw, sh = old.get_size_request()
            w.set_editable(old.get_editable())
            parent.remove(old)
            parent.put(w, x, y)
            w.set_size_request(sw, sh)
            w.set_width_chars(1)
            w.connect("changed", lambda *_: ev(b["cid"], "Change", 0, always=True))
            b["w"] = w
            c["buddy"] = b["cid"]
            placed = True
    elif t == "Hotkey":
        w = Gtk.Entry()
        c["hk"] = text
        w.set_text(hk_display(text))
        w.connect("key-press-event", lambda _w, e: hk_key(c, _w, e))
        w.connect("button-press-event", lambda _w, e: (_w.grab_focus(), True)[1])
    elif t == "DateTime":
        w = Gtk.Entry()
        c["w"] = w
        c["fmt"] = text
        c["range"] = [parse_stamp(x) for x in opts.get("dtrange", [None, None])]
        c["dt"] = None if opts.get("choosenone") else (parse_stamp(opts.get("choosedt"))
                                                       or dt.datetime.now().replace(microsecond=0))
        if c["dt"] is not None:
            c["dt"] = dt_clamp(c, c["dt"])
        if text.lower() == "time":
            w.connect("activate", lambda *_: dt_parse_time(c))
            w.connect("focus-out-event", lambda *_: dt_parse_time(c) and False)
        else:
            w.set_editable(False)
            w.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "x-office-calendar")
            w.connect("icon-press", lambda *_: dt_popup(c))
            w.connect("button-press-event", lambda *_: dt_popup(c) and False)
        dt_show(c)
    elif t == "ActiveX":
        w = make_browser(c, text)
    elif t == "MonthCal":
        w = Gtk.Calendar()
        c["multi"] = bool(opts.get("multi"))
        if opts.get("choosedt"):
            cal_set(w, opts["choosedt"])
            if c["multi"] and "-" in str(opts["choosedt"]):
                lo, hi = str(opts["choosedt"]).split("-", 1)
                c["range"] = [parse_stamp(lo), parse_stamp(hi)]
        c["w"] = w
        if c["multi"]:
            # Multi: Shift+click extends the selection into a range, like the Win32 month calendar
            w.connect("day-selected", lambda *_: cal_pick(c))
            w.connect("month-changed", lambda *_: cal_mark(c))
            cal_pick(c, initial=True)
        w.connect("day-selected", lambda *_: ev(cid, "Change", 0))
    else:
        w = Gtk.Label(label=text)
    c["w"] = w
    ctrls[cid] = c
    if not placed:
        win.fixed.put(w, int(opts.get("x", 0)), int(opts.get("y", 0)))
        if opts.get("w") or opts.get("h"):
            w.set_size_request(int(opts.get("w") or -1), int(opts.get("h") or -1))
    apply_style(c)
    w.show_all()
    if not effective_visible(c):
        w.hide()
    if opts.get("disabled"):
        w.set_sensitive(False)
    pw = w.get_preferred_size()[1]
    res = {"w": pw.width, "h": pw.height}
    if t == "Tab":
        # height of the tab strip, so the first control on a page lands inside the display area
        probe = Gtk.Notebook()
        probe.append_page(Gtk.Box(), Gtk.Label(label="Tab"))
        probe.show_all()
        res["header"] = probe.get_preferred_size()[1].height
        probe.destroy()
    return res


# ---------------------------------------------------------------- ActiveX: the "Shell.Explorer" web browser
def _webkit():
    for ns, ver in (("WebKit2", "4.1"), ("WebKit2", "4.0")):
        try:
            gi.require_version(ns, ver)
            from gi.repository import WebKit2
            return WebKit2
        except (ValueError, ImportError):
            continue
    return None


def make_browser(c, text):
    """Gui.Add("ActiveX", , "Shell.Explorer" | URL | "mshtml:<html>") hosts WebKitGTK in place of Internet Explorer."""
    wk = _webkit()
    if wk is None:
        raise ValueError("The ActiveX web browser needs WebKitGTK (install webkit2gtk-4.1).")
    view = wk.WebView()
    c["web"] = view
    c["html_buf"] = None
    spec = text.strip()
    if spec.lower().startswith("mshtml:"):
        view.load_html(spec[7:], "about:blank")
    elif re.match(r"^[a-z][\w+.-]*:", spec) and not spec.lower().startswith("shell."):
        view.load_uri(spec)
    else:
        view.load_html("", "about:blank")
    sw = Gtk.ScrolledWindow()
    sw.add(view)
    return sw


def web_op(c, req):
    view = c.get("web")
    if view is None:
        raise ValueError("Not a web browser control.")
    do = req["do"]
    if do == "navigate":
        view.load_uri(req["url"])
    elif do == "html":
        view.load_html(req["html"], req.get("base") or "about:blank")
    elif do == "back":
        view.go_back()
    elif do == "forward":
        view.go_forward()
    elif do == "refresh":
        view.reload()
    elif do == "stop":
        view.stop_loading()
    elif do == "url":
        return view.get_uri() or ""
    elif do == "title":
        return view.get_title() or ""
    elif do == "busy":
        return int(view.is_loading())
    elif do == "script":
        view.run_javascript(req["code"], None, None, None)
    return ""


# ---------------------------------------------------------------- menus (Menu.Show, Gui.MenuBar)
def build_menu(tree, shell):
    group = None
    for it in tree:
        if it["label"] == "":
            shell.append(Gtk.SeparatorMenuItem())
            group = None
            continue
        label = mnemonic(it["label"].split("\t")[0])
        if it.get("radio"):
            item = Gtk.RadioMenuItem.new_with_mnemonic_from_widget(group, label)
            group = item
            item.set_active(bool(it.get("checked")))
        elif it.get("checked") is not None:
            item = Gtk.CheckMenuItem.new_with_mnemonic(label)
            item.set_active(bool(it["checked"]))
        else:
            item = Gtk.MenuItem.new_with_mnemonic(label)
        if it.get("default"):
            item.get_child().set_markup("<b>%s</b>" % GLib.markup_escape_text(it["label"].replace("&", "")))
        if it.get("icon"):
            pix = load_icon(it["icon"], 16)
            if pix is not None:
                lbl = item.get_child()
                item.remove(lbl)
                box = Gtk.Box(spacing=6)
                box.pack_start(Gtk.Image.new_from_pixbuf(pix), False, False, 0)
                box.pack_start(lbl, True, True, 0)
                item.add(box)
        if it.get("color"):
            set_css(shell, "background-color: %s; background-image: none;" % it["color"])
        item.set_sensitive(it.get("enabled", True))
        if it.get("sub") is not None:
            sub = Gtk.Menu()
            build_menu(it["sub"], sub)
            item.set_submenu(sub)
        else:
            mid, idx = it["menu"], it["index"]
            item.connect("activate", lambda i, mid=mid, idx=idx:
                         (not isinstance(i, Gtk.CheckMenuItem) or not getattr(i, "_sync", False)) and
                         emit({"event": "MenuPick", "menu": mid, "index": idx}))
        shell.append(item)


_info_win = None


def handle(req):
    global quiet
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
        quiet = True
        try:
            return make(wins[req["win"]], req["ctrl"], req["type"], req.get("opts", {}))
        finally:
            quiet = False
    if op == "show":
        win = wins[req["win"]]
        if req.get("w") or req.get("h"):
            set_client_size(win, req.get("w"), req.get("h"))
        win.w.show_all()
        sync_win(win.id)
        if req.get("x") is not None or req.get("y") is not None:
            win.w.move(int(req.get("x") or 0), int(req.get("y") or 0))
        elif req.get("center", True):
            win.w.set_position(Gtk.WindowPosition.CENTER)
        if req.get("state") == "min":
            win.w.iconify()
        elif req.get("state") == "max":
            win.w.maximize()
        if req.get("activate", True):
            win.w.present()
        return True
    if op == "hide":
        wins[req["win"]].w.hide()
        return True
    if op == "destroy":
        win = wins.pop(req["win"], None)
        if win:
            for cid in [k for k, c in ctrls.items() if c["win"] == win.id]:
                del ctrls[cid]
            win.w.destroy()
        return True
    if op == "title":
        wins[req["win"]].w.set_title(req["value"])
        return True
    if op == "getpos":
        win = wins[req["win"]]
        x, y = win.w.get_position()
        w, h = win.w.get_size()
        if req.get("client"):
            return [x, y, w, h - win.menu_h()]
        return [x, y, w, h]
    if op == "gopt":
        win = wins[req["win"]]
        w = win.w
        if "ontop" in req:
            w.set_keep_above(bool(req["ontop"]))
        if "caption" in req:
            w.set_decorated(bool(req["caption"]))
        if "border" in req and not req["border"]:
            w.set_decorated(False)
        if "toolwindow" in req:
            w.set_skip_taskbar_hint(bool(req["toolwindow"]))
            w.set_type_hint(Gdk.WindowTypeHint.UTILITY if req["toolwindow"] else Gdk.WindowTypeHint.NORMAL)
        if "resize" in req:
            w.set_resizable(bool(req["resize"]))
        if "sysmenu" in req:
            w.set_deletable(bool(req["sysmenu"]))
        if "disabled" in req:
            win.box.set_sensitive(not req["disabled"])
        if "owner" in req:
            ow = wins.get(req["owner"] or 0)
            w.set_transient_for(ow.w if ow else None)
        if "minsize" in req or "maxsize" in req:
            geo = Gdk.Geometry()
            mask = 0
            if req.get("minsize"):
                geo.min_width, geo.min_height = req["minsize"]
                mask |= Gdk.WindowHints.MIN_SIZE
            if req.get("maxsize"):
                geo.max_width, geo.max_height = req["maxsize"]
                mask |= Gdk.WindowHints.MAX_SIZE
            w.set_geometry_hints(None, geo, Gdk.WindowHints(mask))
        if "bg" in req:
            set_css(w, "background-color: %s; background-image: none;" % req["bg"] if req["bg"] else "")
        if "opacity" in req:
            w.set_opacity(float(req["opacity"]))
        return True
    if op == "wstate":
        w = wins[req["win"]].w
        s = req["state"]
        if s == "min":
            w.iconify()
        elif s == "max":
            w.show()
            w.maximize()
        elif s == "restore":
            w.show()
            w.deiconify()
            w.unmaximize()
            w.present()
        elif s == "flash":
            w.set_urgency_hint(bool(req.get("on", True)))
        return True
    if op == "wmove":
        win = wins[req["win"]]
        x, y = win.w.get_position()
        cw, ch = win.w.get_size()
        if req.get("x") is not None or req.get("y") is not None:
            win.w.move(int(req.get("x", x) if req.get("x") is not None else x),
                       int(req.get("y", y) if req.get("y") is not None else y))
        if req.get("w") is not None or req.get("h") is not None:
            set_client_size(win, req.get("w") if req.get("w") is not None else cw,
                            req.get("h") if req.get("h") is not None else ch - win.chrome_h())
        return True
    if op == "caret":
        # caret of the focused text control, in the window's client coordinates (CaretGetPos)
        win = wins[req["win"]]
        f = win.w.get_focus()
        if isinstance(f, Gtk.TextView):
            buf = f.get_buffer()
            rect = f.get_iter_location(buf.get_iter_at_mark(buf.get_insert()))
            bx, by = f.buffer_to_window_coords(Gtk.TextWindowType.TEXT, rect.x, rect.y)
            tw = f.get_window(Gtk.TextWindowType.TEXT)
            ox, oy = tw.get_position() if tw is not None else (0, 0)
            r = f.translate_coordinates(win.box, bx + ox, by + oy)
            return [int(r[0]), int(r[1] + win.menu_h())] if r else None
        if isinstance(f, Gtk.Entry):
            lay = f.get_layout()
            lx, ly = f.get_layout_offsets()
            idx = f.text_index_to_layout_index(f.get_position())
            strong, _ = lay.get_cursor_pos(len(f.get_text()[:idx].encode("utf-8")) if idx else 0)
            r = f.translate_coordinates(win.box, lx + strong.x // Pango.SCALE, ly + strong.y // Pango.SCALE)
            return [int(r[0]), int(r[1] + win.menu_h())] if r else None
        return None
    if op == "focused":
        win = wins[req["win"]]
        f = win.w.get_focus()
        for cid, c in ctrls.items():
            if c["win"] == win.id and f is not None and any(t is f or t.is_ancestor(f) or f.is_ancestor(t) and False
                                                            for t in [c["w"]] + style_targets(c)):
                return cid
        if f is not None:
            for cid, c in ctrls.items():
                if c["win"] == win.id and f.is_ancestor(c["w"]):
                    return cid
        return 0
    if op == "dropfiles":
        win = wins[req["win"]]
        if not getattr(win, "_drop", False):
            win.enable_drop()
            win._drop = True
        return True
    if op == "menubar":
        win = wins[req["win"]]
        if win.menubar is not None:
            win.box.remove(win.menubar)
            win.menubar = None
        if req.get("tree") is not None:
            mb = Gtk.MenuBar()
            build_menu(req["tree"], mb)
            win.box.pack_start(mb, False, False, 0)
            mb.show_all()
            win.menubar = mb
        return True
    if op == "get":
        c = ctrls[req["ctrl"]]
        return value_of(c) if req["prop"] == "Value" else text_of(c)
    if op == "set":
        c = ctrls[req["ctrl"]]
        quiet = c["type"] not in ("Edit",) and not req.get("notify")
        try:
            if req["prop"] == "Value":
                set_value(c, req["value"])
            elif req["prop"] == "Text":
                set_text(c, str(req["value"]))
            elif req["prop"] == "Enabled":
                c["w"].set_sensitive(bool(req["value"]))
            elif req["prop"] == "Visible":
                c["uv"] = bool(req["value"])
                sync_win(c["win"])
            elif req["prop"] == "ReadOnly":
                (c.get("tv") or c["w"]).set_editable(not req["value"])
        finally:
            quiet = False
        return True
    if op == "style":
        c = ctrls[req["ctrl"]]
        for k in ("font", "color", "bg"):
            if k in req:
                c[k] = req[k]
        apply_style(c)
        return True
    if op == "query":
        return query(ctrls[req["ctrl"]], req["what"])
    if op == "icons":
        c = ctrls[req["ctrl"]]
        size = 32 if req.get("large") else 16
        c["pix"] = [load_icon(p, size) for p in req.get("paths", [])]
        (c.get("tree") or c["w"]).queue_draw()
        return len(c["pix"])
    if op == "move":
        c = ctrls[req["ctrl"]]
        parent = c["w"].get_parent()
        x, y = parent.child_get(c["w"], "x", "y")
        parent.move(c["w"], int(req.get("x", x)), int(req.get("y", y)))
        if req.get("w") is not None or req.get("h") is not None:
            cw, chh = c["w"].get_size_request()
            c["w"].set_size_request(int(req["w"]) if req.get("w") is not None else cw,
                                    int(req["h"]) if req.get("h") is not None else chh)
        if c["type"] == "Picture" and (req.get("w") or req.get("h")):
            c["pw"], c["ph"] = req.get("w") or c.get("pw"), req.get("h") or c.get("ph")
            load_picture(c, c.get("file", ""))
        return True
    if op == "focus":
        c = ctrls[req["ctrl"]]
        (c.get("tv") or c.get("tree") or c["w"]).grab_focus()
        return True
    if op == "click":
        c = ctrls[req["ctrl"]]
        if isinstance(c["w"], Gtk.Button):
            c["w"].clicked()
        return True
    if op == "web":
        return web_op(ctrls[req["ctrl"]], req)
    if op == "sb":
        c = ctrls[req["ctrl"]]
        if req["do"] == "parts":
            # SetParts(widths...): one label per part, the last one takes the remaining width
            box = c["partbox"]
            texts = [p.get_text() for p in c["parts"]]
            for ch in box.get_children():
                box.remove(ch)
            widths = list(req.get("widths", []))
            labels = []
            for i in range(len(widths) + 1):
                lbl = Gtk.Label(label=texts[i] if i < len(texts) else "", xalign=0)
                lbl.set_margin_start(6)
                lbl.set_margin_top(2)
                lbl.set_margin_bottom(2)
                lbl.set_ellipsize(Pango.EllipsizeMode.END)
                if i < len(widths):
                    lbl.set_size_request(int(widths[i]), -1)
                    box.pack_start(lbl, False, False, 0)
                    box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
                else:
                    box.pack_start(lbl, True, True, 0)
                labels.append(lbl)
            c["parts"] = labels
            c["label"] = labels[0]
            box.show_all()
            apply_style(c)
            return len(labels)
        if req["do"] == "text":
            i = int(req.get("part", 1)) - 1
            if not 0 <= i < len(c["parts"]):
                return 0
            c["parts"][i].set_text(req.get("text", ""))
            return 1
        if req["do"] == "get":
            i = int(req.get("part", 1)) - 1
            return c["parts"][i].get_text() if 0 <= i < len(c["parts"]) else ""
    if op == "dropdown":
        c = ctrls[req["ctrl"]]
        if req.get("show"):
            c["w"].popup()
        else:
            c["w"].popdown()
        return True
    if op == "paste":
        c = ctrls[req["ctrl"]]
        if "tv" in c:
            c["tv"].get_buffer().delete_selection(True, True)
            c["tv"].get_buffer().insert_at_cursor(req["text"])
        else:
            w = c["w"]
            w.delete_selection()
            pos = w.get_position()
            w.insert_text(req["text"], pos)
            w.set_position(pos + len(req["text"]))
        return True
    if op == "ip":
        quiet = True
        try:
            return ip_op(ctrls[req["ctrl"]], req)
        finally:
            quiet = False
    if op in ("editsel", "lbsel", "range", "lbtop"):
        quiet = True
        try:
            return ctl_op(op, ctrls[req["ctrl"]], req)
        finally:
            quiet = False
    if op == "items":
        c = ctrls[req["ctrl"]]
        quiet = True
        try:
            t = c["type"]
            if t in ("DDL", "ComboBox"):
                if req.get("clear"):
                    c["w"].remove_all()
                if req.get("delete"):
                    c["w"].remove(req["delete"] - 1)
                if "insert" in req:
                    c["w"].insert_text(int(req["insert"]["at"]), str(req["insert"]["text"]))
                for it in req.get("add", []):
                    c["w"].append_text(it)
                return len(c["w"].get_model())
            if t == "ListBox":
                if req.get("clear"):
                    c["store"].clear()
                if req.get("delete"):
                    c["store"].remove(c["store"].get_iter(Gtk.TreePath(req["delete"] - 1)))
                if "insert" in req:
                    c["store"].insert(int(req["insert"]["at"]), [str(req["insert"]["text"])])
                for it in req.get("add", []):
                    c["store"].append([it])
                return len(c["store"])
            if t == "Tab":
                nb = c["w"]
                if req.get("clear"):
                    while nb.get_n_pages():
                        nb.remove_page(-1)
                if req.get("delete"):
                    nb.remove_page(req["delete"] - 1)
                for it in req.get("add", []):
                    tab_add_page(c, it)
                sync_win(c["win"])
                return nb.get_n_pages()
        finally:
            quiet = False
        return 0
    if op == "lv":
        c = ctrls[req["ctrl"]]
        quiet = True
        try:
            r = lv_op(c, req)
            if req["do"] in ("add", "insert", "modify", "delete", "deletecol", "insertcol", "modifycol"):
                c["prevsel"] = set(lv_selected(c))
            return r
        finally:
            quiet = False
    if op == "tv":
        quiet = True
        try:
            return tv_op(ctrls[req["ctrl"]], req)
        finally:
            quiet = False
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
            gw = tw.get_window()
            return gw.get_xid() if gw is not None and hasattr(gw, "get_xid") else 0
        return 0
    if op == "tray":
        return tray_op(req)
    if op == "info":
        # the main window's ListVars/ListHotkeys/KeyHistory/ListLines view: one window, class "AutoHotkey"
        global _info_win
        w = _info_win
        if w is None:
            w = Gtk.Window()
            w.set_wmclass("AutoHotkey", "AutoHotkey")
            w.set_default_size(560, 380)
            tv = Gtk.TextView()
            tv.set_editable(False)
            tv.set_monospace(True)
            sw = Gtk.ScrolledWindow()
            sw.add(tv)
            w.add(sw)
            w.tv = tv
            w.connect("delete-event", lambda win, _e: win.hide() or True)
            _info_win = w
        w.set_title(req.get("title", ""))
        w.tv.get_buffer().set_text(req.get("text", ""))
        w.show_all()
        w.present()
        return True
    if op == "menu":
        m = Gtk.Menu()
        if req.get("tree") is not None:
            build_menu(req["tree"], m)
        else:
            for i, label in enumerate(req["items"]):
                if label == "":
                    m.append(Gtk.SeparatorMenuItem())
                    continue
                item = Gtk.MenuItem(label=mnemonic(label), use_underline=True)
                item.connect("activate", lambda _i, i=i: emit({"event": "MenuPick", "menu": req["menu"], "index": i}))
                m.append(item)
        m.show_all()
        if req.get("x") is not None and req.get("y") is not None:
            rect = Gdk.Rectangle()
            rect.x, rect.y, rect.width, rect.height = int(req["x"]), int(req["y"]), 1, 1
            seat_win = Gdk.get_default_root_window()
            m.popup_at_rect(seat_win, rect, Gdk.Gravity.NORTH_WEST, Gdk.Gravity.NORTH_WEST, None)
        else:
            m.popup_at_pointer(None)
        m.connect("deactivate", lambda *_: GLib.idle_add(lambda: emit({"event": "MenuClosed", "menu": req["menu"]})
                                                         and False))
        menus[req["menu"]] = m
        return True
    raise ValueError(f"unknown op {op}")


# ---------------------------------------------------------------- tray icon
class Tray:
    """AutoHotkey-style tray icon.  XApp.StatusIcon (Cinnamon/XFCE/MATE, SNI + XEmbed), else
    Gtk.StatusIcon (XEmbed trays), else AppIndicator3 (KDE/GNOME, menu only)."""

    # Win32 mouse messages the tray icon reports (AHK_NOTIFYICON lParam), by GDK button and kind
    MSGS = {1: (0x201, 0x202, 0x203), 3: (0x204, 0x205, 0x206), 2: (0x207, 0x208, 0x209)}

    def __init__(self):
        self.items = []
        self.menu = Gtk.Menu()
        self.kind = None
        self.icon = None
        self.click_count = 2
        self.last_press = (0, 0.0)          # button, time of the previous press (for double-clicks)
        self.where = None                   # last click (x, y, button, time, panel_position) for the menu
        self._last_move = 0.0
        try:
            gi.require_version("XApp", "1.0")
            from gi.repository import XApp
            self.icon = XApp.StatusIcon()
            self.icon.set_name(os.environ.get("BHK_TRAY_NAME", "Bunny Hot Key"))
            # no primary/secondary menu: every click goes to the script, which decides (AHK_NOTIFYICON)
            self.icon.connect("button-press-event", self._xapp_press)
            self.icon.connect("button-release-event", self._xapp_release)
            self.kind = "xapp"
        except (ValueError, ImportError):
            pass
        if self.icon is None:
            try:
                self.icon = Gtk.StatusIcon()
                self.icon.connect("button-press-event", self._gtk_press)
                self.icon.connect("button-release-event", self._gtk_release)
                self.icon.set_has_tooltip(True)
                self.icon.connect("query-tooltip", self._gtk_hover)
                self.kind = "gtk"
            except (AttributeError, TypeError):
                self.icon = None
        if self.icon is None:
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3
            self.icon = AppIndicator3.Indicator.new("bunnyhotkey", "bunnyhotkey",
                                                     AppIndicator3.IndicatorCategory.APPLICATION_STATUS)
            self.icon.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            self.icon.set_menu(self.menu)       # StatusNotifier trays open the menu themselves; clicks aren't reported
            self.kind = "appindicator"

    def _mouse(self, button, up):
        """Report a press or release as Windows does: DOWN, UP, DBLCLK (second press), UP."""
        import time
        msgs = self.MSGS.get(button)
        if msgs is None:
            return
        if up:
            emit({"event": "TrayMouse", "msg": msgs[1]})
            return
        now = time.monotonic()
        dbl_ms = Gtk.Settings.get_default().get_property("gtk-double-click-time") or 400
        prev_button, prev_time = self.last_press
        if prev_button == button and (now - prev_time) * 1000 <= dbl_ms:
            self.last_press = (0, 0.0)
            emit({"event": "TrayMouse", "msg": msgs[2]})
        else:
            self.last_press = (button, now)
            emit({"event": "TrayMouse", "msg": msgs[0]})

    def _xapp_press(self, _icon, x, y, button, t, pos):
        self.where = (x, y, button, t, pos)
        self._mouse(button, False)

    def _xapp_release(self, _icon, x, y, button, t, pos):
        self.where = (x, y, button, t, pos)
        self._mouse(button, True)

    def _gtk_press(self, _icon, ev):
        from gi.repository import Gdk
        if ev.type == Gdk.EventType.BUTTON_PRESS:        # GTK's own 2BUTTON/3BUTTON events are ignored
            self.where = (0, 0, ev.button, ev.time, 0)
            self._mouse(ev.button, False)
        return True

    def _gtk_release(self, _icon, ev):
        self.where = (0, 0, ev.button, ev.time, 0)
        self._mouse(ev.button, True)
        return True

    def _gtk_hover(self, *_):
        import time
        now = time.monotonic()
        if now - self._last_move > 0.2:                   # WM_MOUSEMOVE while the pointer is over the icon
            self._last_move = now
            emit({"event": "TrayMouse", "msg": 0x200})
        return False

    def popup(self):
        """Show the tray menu at the icon (Menu.Display(false) after WM_RBUTTONUP)."""
        if self.kind == "appindicator" or not self.menu.get_children():
            return
        x, y, button, t, pos = self.where or (0, 0, 3, Gtk.get_current_event_time(), 0)
        if self.kind == "xapp":
            self.icon.popup_menu(self.menu, x, y, button, t, pos)
        else:
            self.menu.popup(None, None, Gtk.StatusIcon.position_menu, self.icon, button, t)

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
        if items and "menu" in items[0]:
            # the full menu tree: submenus, radio items, icons and colours, like any other Menu
            build_menu(items, self.menu)
            self.menu.show_all()
            return
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
    if req.get("popup"):
        tray.popup()
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
        # our own ValueErrors carry a message meant for the script; anything else is reported with its type
        emit({"reply": req["id"], "error": str(e) if type(e) is ValueError else f"{type(e).__name__}: {e}"})
    return True


def main():
    GLib.set_prgname("bunnyhotkey")
    GLib.set_application_name("Bunny Hot Key")
    if os.path.exists(ICON):
        Gtk.Window.set_default_icon_from_file(ICON)
    GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_HUP, on_line)
    Gtk.main()


if __name__ == "__main__":
    main()
