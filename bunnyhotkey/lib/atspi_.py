"""Other programs' controls through AT-SPI, the Linux accessibility bus.

On Windows, Control* functions reach any program's child windows.  X11 has no such thing, but GTK, Qt (with
QT_ACCESSIBILITY=1), LibreOffice, Firefox and most desktop apps publish their widgets on AT-SPI.  This module maps
those widgets onto AutoHotkey's model: each control gets a Win32 class name by role (push button -> Button,
text -> Edit, table -> SysListView32...), a ClassNN by order within its class ("Edit1", "Button2"), and a stable
synthetic HWND, so ControlGetText("Edit1", "ahk_exe gedit") and friends behave as they do on Windows.
"""
from __future__ import annotations

import itertools
import threading

_ok = None
_lock = threading.RLock()
_hwnds: dict[int, "Foreign"] = {}
_by_key: dict[tuple, int] = {}
_ids = itertools.count(0x7E000001)

# AT-SPI role name -> Win32 class (script_gui.cpp names for the matching AutoHotkey controls)
ROLE_CLASS = {
    "push button": "Button", "button": "Button", "toggle button": "Button", "push button menu": "Button", "check box": "Button", "radio button": "Button",
    "text": "Edit", "password text": "Edit", "entry": "Edit", "spin button": "Edit", "editbar": "Edit",
    "label": "Static", "static": "Static", "image": "Static", "icon": "Static",
    "combo box": "ComboBox", "list": "ListBox", "list box": "ListBox",
    "table": "SysListView32", "tree table": "SysListView32", "tree": "SysTreeView32",
    "page tab list": "SysTabControl32", "slider": "msctls_trackbar32", "progress bar": "msctls_progress32",
    "status bar": "msctls_statusbar32", "link": "SysLink", "calendar": "SysMonthCal32",
    "date editor": "SysDateTimePick32", "scroll bar": "ScrollBar", "tool bar": "ToolbarWindow32",
    "menu bar": "Menu", "document web": "Internet Explorer_Server", "document frame": "Edit",
    "terminal": "Edit",
}
CHECKABLE = {"check box", "radio button", "toggle button"}
TEXTUAL = {"text", "password text", "entry", "spin button", "editbar", "document frame", "terminal"}


def Atspi():
    from gi.repository import Atspi as A
    return A


def available() -> bool:
    global _ok
    if _ok is None:
        try:
            import gi
            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi as A  # noqa: F401
            A.get_desktop(0).get_child_count()
            _ok = True
        except Exception:
            _ok = False
    return _ok


def _ifaces(acc):
    try:
        return set(acc.get_interfaces())
    except Exception:
        return set()


def window_accessible(xid, pid, title):
    """The AT-SPI frame for an X window: same process, matching title (else the only/first frame)."""
    if not available():
        return None
    A = Atspi()
    desk = A.get_desktop(0)
    frames = []
    for i in range(desk.get_child_count()):
        try:
            app = desk.get_child_at_index(i)
            if app is None or app.get_process_id() != pid:
                continue
            for j in range(app.get_child_count()):
                f = app.get_child_at_index(j)
                if f is not None:
                    frames.append(f)
        except Exception:
            continue
    for f in frames:
        try:
            if f.get_name() == title:
                return f
        except Exception:
            pass
    showing = [f for f in frames if _state(f, "SHOWING")]
    return (showing or frames or [None])[0]


def _state(acc, name):
    A = Atspi()
    try:
        return acc.get_state_set().contains(getattr(A.StateType, name))
    except Exception:
        return False


class Foreign:
    """One control of another program."""
    __slots__ = ("acc", "role", "cls", "nn", "win", "hwnd")

    def __init__(self, acc, role, cls, nn, win):
        self.acc, self.role, self.cls, self.nn, self.win = acc, role, cls, nn, win
        self.hwnd = 0

    # ---- identity
    @property
    def classnn(self):
        return f"{self.cls}{self.nn}"

    # ---- text
    def text(self):
        a = self.acc
        if self.role in TEXTUAL and "Text" in _ifaces(a):
            n = Atspi().Text.get_character_count(a)
            return Atspi().Text.get_text(a, 0, n) or ""
        if self.role == "combo box":
            return a.get_name() or ""
        if self.role == "status bar" and not a.get_name():
            return " ".join(Foreign(c, "", "", 0, self.win).text() for c in _children(a))
        return a.get_name() or ""

    def set_text(self, s):
        if "EditableText" in _ifaces(self.acc):
            return bool(Atspi().EditableText.set_text_contents(self.acc, s))
        return False

    def lines(self):
        return self.text().split("\n")

    def caret(self):
        A = Atspi()
        text = self.text()
        off = A.Text.get_caret_offset(self.acc) if "Text" in _ifaces(self.acc) else 0
        before = text[:max(off, 0)]
        return before.count("\n") + 1, len(before) - (before.rfind("\n") + 1) + 1

    def seltext(self):
        A = Atspi()
        if "Text" not in _ifaces(self.acc) or A.Text.get_n_selections(self.acc) < 1:
            return ""
        r = A.Text.get_selection(self.acc, 0)
        return A.Text.get_text(self.acc, r.start_offset, r.end_offset) or ""

    def insert(self, s):
        A = Atspi()
        if "EditableText" not in _ifaces(self.acc):
            return False
        off = A.Text.get_caret_offset(self.acc) if "Text" in _ifaces(self.acc) else len(self.text())
        return bool(A.EditableText.insert_text(self.acc, max(off, 0), s, len(s.encode("utf-8"))))

    # ---- state
    def checked(self):
        return int(_state(self.acc, "CHECKED") or _state(self.acc, "PRESSED"))

    def enabled(self):
        return int(_state(self.acc, "ENABLED") or _state(self.acc, "SENSITIVE"))

    def visible(self):
        return int(_state(self.acc, "SHOWING") and _state(self.acc, "VISIBLE"))

    def focused(self):
        return _state(self.acc, "FOCUSED")

    # ---- actions
    def do_action(self, *names):
        A = Atspi()
        a = self.acc
        if "Action" not in _ifaces(a):
            return False
        n = A.Action.get_n_actions(a)
        wanted = [x.lower() for x in names]
        for i in range(n):
            if A.Action.get_action_name(a, i).lower() in wanted:
                return bool(A.Action.do_action(a, i))
        return bool(n and A.Action.do_action(a, 0))

    def click(self):
        return self.do_action("click", "press", "activate", "toggle")

    def set_checked(self, on):
        if bool(self.checked()) != bool(on):
            self.do_action("toggle", "click", "press")

    def focus(self):
        try:
            return bool(Atspi().Component.grab_focus(self.acc))
        except Exception:
            return False

    def pos(self):
        """(x, y, w, h) relative to the window, as ControlGetPos reports."""
        A = Atspi()
        try:
            e = A.Component.get_extents(self.acc, A.CoordType.WINDOW)
            return e.x, e.y, e.width, e.height
        except Exception:
            return 0, 0, 0, 0

    # ---- lists
    def item_nodes(self):
        out = []
        for c in _descendants(self.acc, 3):
            r = c.get_role_name()
            if r in ("menu item", "list item", "check menu item", "radio menu item", "table cell", "page tab"):
                out.append(c)
        return out

    def items(self):
        if self.role in ("table", "tree table"):
            return ["\t".join(row) for row in self.table_rows()]
        return [n.get_name() or "" for n in self.item_nodes()]

    def index(self):
        names = self.items()
        cur = self.text()
        if self.role in ("list", "list box", "page tab list"):
            for i, n in enumerate(self.item_nodes(), 1):
                if _state(n, "SELECTED"):
                    return i
            return 0
        return names.index(cur) + 1 if cur in names else 0

    def choose(self, i):
        A = Atspi()
        nodes = self.item_nodes()
        if not 1 <= i <= len(nodes):
            return False
        if self.role == "combo box":
            node = nodes[i - 1]
            if "Action" in _ifaces(node):
                return bool(Foreign(node, "menu item", "", 0, self.win).do_action("click", "activate"))
        parent = nodes[i - 1].get_parent()
        if parent is not None and "Selection" in _ifaces(parent):
            return bool(A.Selection.select_child(parent, nodes[i - 1].get_index_in_parent()))
        return bool(Foreign(nodes[i - 1], "", "", 0, self.win).do_action("click", "activate", "select"))

    def table_rows(self, selected=False):
        A = Atspi()
        a = self.acc
        if "Table" not in _ifaces(a):
            return []
        nr, nc = A.Table.get_n_rows(a), A.Table.get_n_columns(a)
        rows = []
        for r in range(nr):
            if selected and not A.Table.is_row_selected(a, r):
                continue
            row = []
            for c in range(nc):
                cell = A.Table.get_accessible_at(a, r, c)
                row.append((cell.get_name() if cell is not None else "") or "")
            rows.append(row)
        return rows

    def n_columns(self):
        return Atspi().Table.get_n_columns(self.acc) if "Table" in _ifaces(self.acc) else 0


def _children(acc):
    out = []
    try:
        for i in range(acc.get_child_count()):
            c = acc.get_child_at_index(i)
            if c is not None:
                out.append(c)
    except Exception:
        pass
    return out


def _descendants(acc, depth):
    out = []
    for c in _children(acc):
        out.append(c)
        if depth > 1:
            out.extend(_descendants(c, depth - 1))
    return out


def controls(xid, pid, title, limit=2000):
    """Controls of another program's window, in tree order, as Foreign objects with ClassNN numbering."""
    root = window_accessible(xid, pid, title)
    if root is None:
        return []
    out, counts, stack = [], {}, list(reversed(_children(root)))
    while stack and len(out) < limit:
        acc = stack.pop()
        try:
            role = acc.get_role_name()
        except Exception:
            continue
        cls = ROLE_CLASS.get(role)
        if cls is not None:
            counts[cls] = counts.get(cls, 0) + 1
            f = Foreign(acc, role, cls, counts[cls], xid)
            key = (xid, f.classnn)
            with _lock:
                h = _by_key.get(key)
                if h is None:
                    h = next(_ids)
                    _by_key[key] = h
                f.hwnd = h
                _hwnds[h] = f
            out.append(f)
            if role in ("combo box", "table", "tree table", "tree", "list", "list box", "page tab list",
                        "menu bar", "status bar"):
                continue        # their items are reached through the control itself
        stack.extend(reversed(_children(acc)))
    return out


def by_hwnd(h):
    return _hwnds.get(h)


def find(xid, pid, title, control, mode, match):
    """Resolve a Control parameter (ClassNN or text) within another program's window."""
    s = str(control)
    sl = s.lower()
    cs = controls(xid, pid, title)
    for f in cs:
        if f.classnn.lower() == sl:
            return f
    for f in cs:
        try:
            t = f.acc.get_name() or (f.text() if f.role in TEXTUAL else "")
        except Exception:
            continue
        if t and match(s, t, mode):
            return f
    return None


def focused(xid, pid, title):
    for f in controls(xid, pid, title):
        if f.focused():
            return f
    return None
