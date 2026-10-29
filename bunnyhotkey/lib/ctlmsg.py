"""Win32 control messages (EM_/LB_/CB_/PBM_/TBM_/UDM_/HKM_/SB_/LVM_/TVM_) for this script's own Gui controls.

window._builtin_message calls handle() for messages it doesn't know.  Return values follow Win32: LB_ERR/CB_ERR
are -1, "previous value" messages return the old value, and so on.  Edit offsets count characters of the text as
ControlGetText returns it (lines end in `n here).
"""
from __future__ import annotations

import struct

ERR = -1                                    # LB_ERR, CB_ERR

# Per-control state the GTK side doesn't keep: Edit text limit and cue banner, progress step, StatusBar part edges.
_STATE: dict[int, dict] = {}


def _st(c):
    return _STATE.setdefault(c.cid, {})


def _srv():
    from .guiobj import _srv as s
    return s()


def _q(c, what):
    return _srv().call("query", ctrl=c.cid, what=what)


def _signed(v):
    v &= 0xFFFFFFFFFFFFFFFF
    return v - (1 << 64) if v & (1 << 63) else v


def _s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def _lo(v):
    return v & 0xFFFF


def _hi(v):
    return (v >> 16) & 0xFFFF


def _s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def _long(lo, hi):
    return (lo & 0xFFFF) | ((hi & 0xFFFF) << 16)


def _text(c):
    from .guiobj import ctrl_get
    v = ctrl_get(c, "Text")
    return v if isinstance(v, str) else ""


def _str_arg(lp):
    if not lp:
        return ""
    from .buffer import StrGet
    return StrGet(lp)


def _put(lp, s):
    from .buffer import resolve
    data, idx = resolve(lp)
    raw = s.encode("utf-16-le") + b"\0\0"
    data[idx:idx + len(raw)] = raw


def _put_u32(ptr, v):
    if ptr:
        from .buffer import resolve
        data, idx = resolve(ptr)
        struct.pack_into("<I", data, idx, v & 0xFFFFFFFF)


def handle(c, msg, wp, lp):
    """-> (handled, result)."""
    t = c.ctype
    if msg == 0x0D:                                                     # WM_GETTEXT
        return True, _get_text(c, wp, lp)
    if msg == 0x0B:                                                     # WM_SETREDRAW: GTK redraws by itself
        return True, 0
    fn = _scintilla if c.custom == "scintilla" and msg >= 2000 else _BY_TYPE.get(t)
    if fn is not None:
        r = fn(c, msg, wp, lp)
        if r is not None:
            return True, r
    return False, 0


def _get_text(c, wp, lp):
    n = wp & 0xFFFFFFFF
    if not n or not lp:
        return 0
    s = (_text(c) if c.ctype != "StatusBar" else _sb_get(c, 0))[:n - 1]
    _put(lp, s)
    return len(s)


# ---------------------------------------------------------------- Edit
def _lines(c):
    return _q(c, "lines")


def _line_starts(lines):
    starts, pos = [], 0
    for ln in lines:
        starts.append(pos)
        pos += len(ln) + 1
    return starts


def _line_of(lines, ch):
    starts = _line_starts(lines)
    i = 0
    for k, s in enumerate(starts):
        if s <= ch:
            i = k
    return i


class _GtkEdit:
    """The text operations EM_ messages need, for one of this script's Edit controls."""

    def __init__(self, c):
        self.c = c

    def text(self):
        return _text(self.c)

    def lines(self):
        return _q(self.c, "lines")

    def sel(self):
        return tuple(_q(self.c, "sel"))

    def caret_line(self):
        return _q(self.c, "caret")[0] - 1

    def set_sel(self, start, end):
        _srv().call("editsel", ctrl=self.c.cid, start=start, end=end)

    def replace_sel(self, s):
        _srv().call("paste", ctrl=self.c.cid, text=s)


class _ForeignEdit(_GtkEdit):
    """The same for another program's text control (AT-SPI Text/EditableText)."""

    def __init__(self, f):
        self.f = f

    def text(self):
        return self.f.text()

    def lines(self):
        return self.f.lines()

    def sel(self):
        return self.f.sel()

    def caret_line(self):
        return self.f.caret()[0] - 1

    def set_sel(self, start, end):
        self.f.set_sel(start, len(self.f.text()) if end == -1 else end)

    def replace_sel(self, s):
        self.f.replace_sel(s)


def _edit(c, msg, wp, lp):
    r = _edit_text(_GtkEdit(c), msg, wp, lp)
    if r is not None:
        return r
    return _edit_gui(c, msg, wp, lp)


def _edit_text(ed, msg, wp, lp):
    """EM_ messages that only need the text, the selection and the caret."""
    if msg == 0xB0:                                                     # EM_GETSEL
        s, e = ed.sel()
        _put_u32(wp, s)
        _put_u32(lp, e)
        return _long(s, e) if s <= 0xFFFF and e <= 0xFFFF else -1
    if msg == 0xB1:                                                     # EM_SETSEL
        s, e = _s32(wp), _s32(lp)
        if s == -1:
            ed.set_sel(-1, -1)
            return 0
        n = len(ed.text())
        e = n if e < 0 or e > n else e
        s = min(s, n)
        ed.set_sel(min(s, e), max(s, e))
        return 0
    if msg == 0xC2:                                                     # EM_REPLACESEL
        ed.replace_sel(_str_arg(lp))
        return 0
    if msg == 0xBA:                                                     # EM_GETLINECOUNT
        return len(ed.lines())
    if msg == 0xBB:                                                     # EM_LINEINDEX
        lines = ed.lines()
        i = _s32(wp)
        if i == -1:
            i = ed.caret_line()
        return _line_starts(lines)[i] if 0 <= i < len(lines) else -1
    if msg == 0xC1:                                                     # EM_LINELENGTH
        lines = ed.lines()
        i = _s32(wp)
        if i == -1:                                                     # unselected characters on the selected lines
            s, e = ed.sel()
            starts = _line_starts(lines)
            a, b = _line_of(lines, s), _line_of(lines, e)
            return (s - starts[a]) + (starts[b] + len(lines[b]) - e)
        n = sum(len(ln) + 1 for ln in lines) - 1
        if i > n:
            return 0
        return len(lines[_line_of(lines, i)])
    if msg == 0xC4:                                                     # EM_GETLINE (first WORD of lp = room)
        lines = ed.lines()
        i = wp & 0xFFFFFFFF
        if not lp or i >= len(lines):
            return 0
        from .buffer import resolve
        data, idx = resolve(lp)
        room = struct.unpack_from("<H", data, idx)[0]
        s = lines[i][:room]
        raw = s.encode("utf-16-le")
        data[idx:idx + len(raw)] = raw                                  # not NUL-terminated, as on Windows
        return len(s)
    if msg == 0xC9:                                                     # EM_LINEFROMCHAR
        lines = ed.lines()
        i = _s32(wp)
        if i == -1:
            i = ed.sel()[0]
        return _line_of(lines, i)
    return None


def _edit_gui(c, msg, wp, lp):
    if msg == 0xCF:                                                     # EM_SETREADONLY
        c.readonly = bool(wp)
        _srv().call("set", ctrl=c.cid, prop="ReadOnly", value=int(c.readonly))
        return 1
    if msg == 0xC5:                                                     # EM_LIMITTEXT / EM_SETLIMITTEXT
        _st(c)["limit"] = (wp & 0xFFFFFFFF) or 0x7FFFFFFE
        return 0
    if msg == 0xD5:                                                     # EM_GETLIMITTEXT
        return _st(c).get("limit", 30000)
    if msg == 0xCE:                                                     # EM_GETFIRSTVISIBLELINE
        return 0
    if msg == 0xB7:                                                     # EM_SCROLLCARET
        return 1
    if msg == 0x1501:                                                   # EM_SETCUEBANNER
        _st(c)["cue"] = _str_arg(lp)
        return 1
    if msg == 0x1502:                                                   # EM_GETCUEBANNER
        cue = _st(c).get("cue")
        if cue is None or not wp:
            return 0
        from .buffer import resolve
        n = lp & 0xFFFFFFFF
        data, idx = resolve(wp)
        raw = cue[:max(n - 1, 0)].encode("utf-16-le") + b"\0\0"
        data[idx:idx + len(raw)] = raw
        return 1
    if msg in (0xC6, 0xC7):                                             # EM_CANUNDO, EM_UNDO: no undo buffer
        return 0
    return None


# ---------------------------------------------------------------- ListBox / ComboBox
def _items(c):
    return _q(c, "items")


def _find(items, start, s, exact):
    """LB_FINDSTRING(EXACT): case-insensitive, starts after `start` and wraps; -1 searches from the top."""
    n = len(items)
    if not n:
        return ERR
    start = _s32(start)
    first = 0 if start < 0 or start >= n else start + 1
    low = s.lower()
    for k in range(n):
        i = (first + k) % n
        v = items[i].lower()
        if (v == low) if exact else v.startswith(low):
            return i
    return ERR


def _insert(c, at, s):
    items = _items(c)
    at = _s32(at)
    if at < 0 or at >= len(items):
        if at > len(items):
            return ERR
        _srv().call("items", ctrl=c.cid, add=[s])
        return len(items)
    _srv().call("items", ctrl=c.cid, insert={"at": at, "text": s})
    return at


def _delete(c, i):
    items = _items(c)
    i = _s32(i)
    if not 0 <= i < len(items):
        return ERR
    return _srv().call("items", ctrl=c.cid, delete=i + 1)


def _put_item(c, i, lp):
    items = _items(c)
    i = _s32(i)
    if not 0 <= i < len(items):
        return ERR
    if lp:
        _put(lp, items[i])
    return len(items[i])


def _select_index(c, i):
    from .window import _gset
    _gset(c, "Value", i + 1, notify=False)


def _listbox(c, msg, wp, lp):
    if msg == 0x180:                                                    # LB_ADDSTRING
        return _insert(c, -1, _str_arg(lp))
    if msg == 0x181:                                                    # LB_INSERTSTRING
        return _insert(c, wp, _str_arg(lp))
    if msg == 0x182:                                                    # LB_DELETESTRING
        return _delete(c, wp)
    if msg == 0x184:                                                    # LB_RESETCONTENT
        _srv().call("items", ctrl=c.cid, clear=True)
        return 0
    if msg == 0x189:                                                    # LB_GETTEXT
        return _put_item(c, wp, lp)
    if msg == 0x18A:                                                    # LB_GETTEXTLEN
        return _put_item(c, wp, 0)
    if msg in (0x18F, 0x1A2):                                           # LB_FINDSTRING, LB_FINDSTRINGEXACT
        return _find(_items(c), wp, _str_arg(lp), msg == 0x1A2)
    if msg == 0x18C:                                                    # LB_SELECTSTRING
        if c.multi:
            return ERR
        i = _find(_items(c), wp, _str_arg(lp), False)
        if i != ERR:
            _select_index(c, i)
        return i
    if msg == 0x187:                                                    # LB_GETSEL
        i = _s32(wp)
        if not 0 <= i < len(_items(c)):
            return ERR
        return int(i in _q(c, "selected"))
    if msg == 0x185:                                                    # LB_SETSEL (multi-select only)
        if not c.multi:
            return ERR
        i = _s32(lp)
        if i != -1 and not 0 <= i < len(_items(c)):
            return ERR
        _srv().call("lbsel", ctrl=c.cid, index=i, on=bool(wp))
        return 0
    if msg == 0x190:                                                    # LB_GETSELCOUNT
        return len(_q(c, "selected")) if c.multi else ERR
    if msg == 0x191:                                                    # LB_GETSELITEMS
        if not c.multi:
            return ERR
        sel = _q(c, "selected")[:wp & 0xFFFFFFFF]
        if lp and sel:
            from .buffer import resolve
            data, idx = resolve(lp)
            struct.pack_into("<%di" % len(sel), data, idx, *sel)
        return len(sel)
    if msg == 0x18E:                                                    # LB_GETTOPINDEX
        return _q(c, "top")
    if msg == 0x197:                                                    # LB_SETTOPINDEX
        i = _s32(wp)
        if not 0 <= i < len(_items(c)):
            return ERR
        _srv().call("lbtop", ctrl=c.cid, index=i)
        return 0
    return None


def _combo(c, msg, wp, lp):
    if msg == 0x143:                                                    # CB_ADDSTRING
        return _insert(c, -1, _str_arg(lp))
    if msg == 0x14A:                                                    # CB_INSERTSTRING
        return _insert(c, wp, _str_arg(lp))
    if msg == 0x144:                                                    # CB_DELETESTRING
        return _delete(c, wp)
    if msg == 0x14B:                                                    # CB_RESETCONTENT
        _srv().call("items", ctrl=c.cid, clear=True)
        return 0
    if msg == 0x148:                                                    # CB_GETLBTEXT
        return _put_item(c, wp, lp)
    if msg == 0x149:                                                    # CB_GETLBTEXTLEN
        return _put_item(c, wp, 0)
    if msg in (0x14C, 0x158):                                           # CB_FINDSTRING, CB_FINDSTRINGEXACT
        return _find(_items(c), wp, _str_arg(lp), msg == 0x158)
    if msg == 0x14D:                                                    # CB_SELECTSTRING
        i = _find(_items(c), wp, _str_arg(lp), False)
        if i != ERR:
            _select_index(c, i)
        return i
    if msg == 0x14F:                                                    # CB_SHOWDROPDOWN
        _srv().call("dropdown", ctrl=c.cid, show=bool(wp))
        return 1
    if msg == 0x157:                                                    # CB_GETDROPPEDSTATE
        return _q(c, "dropped")
    if msg == 0x15B:                                                    # CB_GETTOPINDEX
        return _q(c, "top")
    if msg == 0x15C:                                                    # CB_SETTOPINDEX
        return 0 if 0 <= _s32(wp) < len(_items(c)) else ERR
    return None


# ---------------------------------------------------------------- Progress / Slider / UpDown
def _value(c):
    from .guiobj import ctrl_get
    v = ctrl_get(c, "Value")
    return int(v) if isinstance(v, (int, float)) else 0


def _set_value(c, v):
    from .window import _gset
    _gset(c, "Value", v, notify=False)


def _range(c):
    lo, hi = _q(c, "range")
    return int(lo), int(hi)


def _set_range(c, lo, hi):
    _srv().call("range", ctrl=c.cid, lo=lo, hi=hi)


def _progress(c, msg, wp, lp):
    if msg == 0x408:                                                    # PBM_GETPOS
        return _value(c)
    if msg == 0x402:                                                    # PBM_SETPOS
        old = _value(c)
        lo, hi = _range(c)
        _set_value(c, max(lo, min(_s32(wp), hi)))
        return old
    if msg == 0x403:                                                    # PBM_DELTAPOS
        old = _value(c)
        lo, hi = _range(c)
        _set_value(c, max(lo, min(old + _s32(wp), hi)))
        return old
    if msg in (0x401, 0x406):                                           # PBM_SETRANGE, PBM_SETRANGE32
        lo, hi = _range(c)
        if msg == 0x401:
            _set_range(c, _s16(_lo(lp)), _s16(_hi(lp)))
        else:
            _set_range(c, _s32(wp), _s32(lp))
        return _long(lo, hi)                                            # the previous range
    if msg == 0x407:                                                    # PBM_GETRANGE
        lo, hi = _range(c)
        if lp:
            from .buffer import resolve
            data, idx = resolve(lp)
            struct.pack_into("<ii", data, idx, lo, hi)
        return lo if wp else hi
    if msg == 0x404:                                                    # PBM_SETSTEP
        old = _st(c).get("step", 10)
        _st(c)["step"] = _s32(wp)
        return old
    if msg == 0x40D:                                                    # PBM_GETSTEP
        return _st(c).get("step", 10)
    if msg == 0x405:                                                    # PBM_STEPIT: wraps to the start past the end
        old = _value(c)
        lo, hi = _range(c)
        v = old + _st(c).get("step", 10)
        if v > hi:
            v = (v - lo) % (hi - lo) + lo if hi > lo else lo           # comctl32's wrap
        _set_value(c, v)
        return old
    return None


def _slider(c, msg, wp, lp):
    if msg == 0x400:                                                    # TBM_GETPOS
        return _value(c)
    if msg == 0x401:                                                    # TBM_GETRANGEMIN
        return _range(c)[0]
    if msg == 0x402:                                                    # TBM_GETRANGEMAX
        return _range(c)[1]
    if msg == 0x405:                                                    # TBM_SETPOS
        lo, hi = _range(c)
        _set_value(c, max(lo, min(_s32(lp), hi)))
        return 0
    if msg == 0x406:                                                    # TBM_SETRANGE
        _set_range(c, _s16(_lo(lp)), _s16(_hi(lp)))
        return 0
    if msg == 0x407:                                                    # TBM_SETRANGEMIN
        _set_range(c, _s32(lp), _range(c)[1])
        return 0
    if msg == 0x408:                                                    # TBM_SETRANGEMAX
        _set_range(c, _range(c)[0], _s32(lp))
        return 0
    return None


def _updown(c, msg, wp, lp):
    if msg in (0x472, 0x468):                                           # UDM_GETPOS32, UDM_GETPOS
        v = _value(c)
        if msg == 0x472:
            _put_u32(lp, 0)                                             # *pfError = FALSE
            return v
        return _long(v, 0)                                              # HIWORD 0 = no error
    if msg in (0x471, 0x467):                                           # UDM_SETPOS32, UDM_SETPOS
        old = _value(c)
        lo, hi = _range(c)
        v = _s32(lp) if msg == 0x471 else _s16(_lo(lp))
        _set_value(c, max(min(lo, hi), min(v, max(lo, hi))))
        return old
    if msg == 0x46F:                                                    # UDM_SETRANGE32 (wp lower, lp upper)
        _set_range(c, _s32(wp), _s32(lp))
        return 0
    if msg == 0x465:                                                    # UDM_SETRANGE: MAKELPARAM(upper, lower)
        _set_range(c, _s16(_hi(lp)), _s16(_lo(lp)))
        return 0
    if msg == 0x470:                                                    # UDM_GETRANGE32
        lo, hi = _range(c)
        _put_u32(wp, lo)
        _put_u32(lp, hi)
        return 0
    if msg == 0x466:                                                    # UDM_GETRANGE
        lo, hi = _range(c)
        return _long(hi, lo)
    return None


# ---------------------------------------------------------------- Hotkey
HOTKEYF = (("+", 1), ("^", 2), ("!", 4))


def _hotkey(c, msg, wp, lp):
    from .. import keys as K
    from .guiobj import ctrl_get, ctrl_set
    if msg == 0x402:                                                    # HKM_GETHOTKEY
        s = ctrl_get(c, "Value") or ""
        mods = 0
        while s[:1] in ("+", "^", "!") and len(s) > 1:
            mods |= dict(HOTKEYF)[s[0]]
            s = s[1:]
        k = K.lookup(s) if s else None
        return _long((k.vk & 0xFF) | (mods << 8), 0) if k is not None and k.vk else 0
    if msg == 0x401:                                                    # HKM_SETHOTKEY: LOBYTE vk, HIBYTE HOTKEYF_*
        vk, mods = wp & 0xFF, (wp >> 8) & 0xFF
        k = K.from_vk(vk) if vk else None
        if k is None:
            ctrl_set(c, "Value", "")
            return 0
        prefix = "".join(p for p, bit in HOTKEYF if mods & bit)
        ctrl_set(c, "Value", prefix + K.key_name(k))
        return 0
    return None


# ---------------------------------------------------------------- StatusBar
def _sb_get(c, part):
    return _srv().call("sb", ctrl=c.cid, do="get", part=part + 1) or ""


def _statusbar(c, msg, wp, lp):
    if msg == 0x40B:                                                    # SB_SETTEXT (LOBYTE wp = part)
        part = wp & 0xFF
        return int(bool(_srv().call("sb", ctrl=c.cid, do="text", part=part + 1, text=_str_arg(lp))))
    if msg in (0x40D, 0x40C):                                           # SB_GETTEXT, SB_GETTEXTLENGTH
        s = _sb_get(c, wp & 0xFF)
        if msg == 0x40D and lp:
            _put(lp, s)
        return _long(len(s), 0)
    if msg == 0x404:                                                    # SB_SETPARTS: right edges, -1 = to the end
        n = wp & 0xFFFFFFFF
        if not 1 <= n <= 256 or not lp:
            return 0
        from .buffer import resolve
        data, idx = resolve(lp)
        edges = list(struct.unpack_from("<%di" % n, data, idx))
        # the GTK side takes the widths of all parts but the last, which fills the rest of the bar
        widths = [max(e - p, 0) for p, e in zip([0] + edges, edges[:-1])]
        _srv().call("sb", ctrl=c.cid, do="parts", widths=widths)
        _st(c)["edges"] = edges
        return 1
    if msg == 0x406:                                                    # SB_GETPARTS
        edges = _st(c).get("edges", [-1])
        n = wp & 0xFFFFFFFF
        if lp and n:
            from .buffer import resolve
            data, idx = resolve(lp)
            k = min(n, len(edges))
            struct.pack_into("<%di" % k, data, idx, *edges[:k])
        return len(edges)
    return None


# ---------------------------------------------------------------- ListView
def _lv(c, do, **kw):
    return _srv().call("lv", ctrl=c.cid, do=do, **kw)


def _listview(c, msg, wp, lp):
    if msg == 0x1004:                                                   # LVM_GETITEMCOUNT
        return _lv(c, "count")
    if msg == 0x1032:                                                   # LVM_GETSELECTEDCOUNT
        return _lv(c, "count", mode="S")
    if msg == 0x1008:                                                   # LVM_DELETEITEM
        i = _s32(wp)
        return int(bool(_lv(c, "delete", row=i + 1))) if 0 <= i < _lv(c, "count") else 0
    if msg == 0x1009:                                                   # LVM_DELETEALLITEMS
        _lv(c, "delete", row=0)
        return 1
    if msg == 0x100C:                                                   # LVM_GETNEXTITEM
        start, flags = _s32(wp) + 1, lp & 0xFFFF                        # 1-based start; -1 -> search from the top
        if flags & 1:                                                   # LVNI_FOCUSED (optionally also SELECTED)
            r = _lv(c, "getnext", start=start, mode="F")
            if r and flags & 2 and _lv(c, "getnext", start=r - 1, mode="") != r:
                r = 0
            return r - 1 if r else -1
        if flags & 2:                                                   # LVNI_SELECTED
            r = _lv(c, "getnext", start=start, mode="")
            return r - 1 if r else -1
        return start if start < _lv(c, "count") else -1                 # LVNI_ALL: the next item
    if msg == 0x1013:                                                   # LVM_ENSUREVISIBLE
        return int(bool(_lv(c, "ensurevisible", row=_s32(wp) + 1)))
    if msg == 0x101D:                                                   # LVM_GETCOLUMNWIDTH
        col = _s32(wp) + 1
        if not 1 <= col <= _lv(c, "count", mode="Col"):
            return 0
        return _lv(c, "colwidth", col=col, width=None) or 0
    if msg == 0x101E:                                                   # LVM_SETCOLUMNWIDTH
        col, w = _s32(wp) + 1, _s16(_lo(lp))
        if not 1 <= col <= _lv(c, "count", mode="Col"):
            return 0
        if w in (-1, -2):                                               # LVSCW_AUTOSIZE, LVSCW_AUTOSIZE_USEHEADER
            _lv(c, "modifycol", col=col, opts="Auto" if w == -1 else "AutoHdr")
        else:
            _lv(c, "colwidth", col=col, width=w)
        return 1
    return None


# ---------------------------------------------------------------- TreeView
TVI_ROOT = -0x10000


def _tv(c, do, **kw):
    return _srv().call("tv", ctrl=c.cid, do=do, **kw)


def _treeview(c, msg, wp, lp):
    if msg == 0x1105:                                                   # TVM_GETCOUNT
        return _tv(c, "count")
    if msg == 0x1101:                                                   # TVM_DELETEITEM
        item = _signed(lp)
        return int(bool(_tv(c, "delete", item=0 if item in (0, TVI_ROOT) else item)))
    if msg == 0x1102:                                                   # TVM_EXPAND
        how = {1: "collapse", 2: "expand", 3: "toggle"}.get(wp & 0x3)
        return int(bool(_tv(c, "expand", item=_signed(lp), how=how))) if how and lp else 0
    if msg == 0x110B:                                                   # TVM_SELECTITEM
        if wp & 0xFF != 9:                                              # only TVGN_CARET
            return 0
        if not lp:
            return 1
        return int(bool(_tv(c, "modify", item=_signed(lp), opts=None, name=None)))
    if msg == 0x110A:                                                   # TVM_GETNEXTITEM
        code, item = wp & 0xFF, _signed(lp)
        if code == 0:                                                   # TVGN_ROOT
            return _tv(c, "next", item=0) or 0
        if code == 9:                                                   # TVGN_CARET
            return _tv(c, "selection") or 0
        if not item:
            return 0
        do = {1: "next", 2: "prev", 3: "parent", 4: "child"}.get(code)
        return (_tv(c, do, item=item) or 0) if do else 0
    return None


# ---------------------------------------------------------------- SysIPAddress32 (Custom control)
def _ipaddress(c, msg, wp, lp):
    ip = lambda do, **kw: _srv().call("ip", ctrl=c.cid, do=do, **kw)    # noqa: E731
    if msg == 0x464:                                                    # IPM_CLEARADDRESS
        ip("clear")
        return 0
    if msg == 0x465:                                                    # IPM_SETADDRESS
        v = lp & 0xFFFFFFFF
        ip("set", values=[v >> 24 & 255, v >> 16 & 255, v >> 8 & 255, v & 255])
        return 0
    if msg == 0x466:                                                    # IPM_GETADDRESS -> non-blank fields
        fields = ip("get")
        v = 0
        for f in fields:
            v = v << 8 | (f or 0)
        _put_u32(lp, v)
        return sum(1 for f in fields if f is not None)
    if msg == 0x467:                                                    # IPM_SETRANGE
        if not 0 <= wp <= 3:
            return 0
        ip("range", field=wp, lo=lp & 255, hi=lp >> 8 & 255)
        return 1
    if msg == 0x468:                                                    # IPM_SETFOCUS
        ip("focus", field=wp)
        return 0
    if msg == 0x469:                                                    # IPM_ISBLANK
        return ip("blank")
    return None


# ---------------------------------------------------------------- Scintilla (Custom control)
# Scintilla's API: char* text in UTF-8 and byte positions.
def _sci_bytes(c):
    return _text(c).encode("utf-8")


def _sci_chars(raw, pos):
    """Byte position -> character offset."""
    return len(raw[:max(pos, 0)].decode("utf-8", "ignore"))


def _sci_put(lp, raw, n=None):
    from .buffer import resolve
    data, idx = resolve(lp)
    raw = raw if n is None else raw[:max(n, 0)]
    data[idx:idx + len(raw) + 1] = raw + b"\0"
    return len(raw)


def _sci_str(lp, n=None):
    if not lp:
        return ""
    from .buffer import resolve
    data, idx = resolve(lp)
    if n is None or n < 0:
        end = idx
        while data[end]:
            end += 1
        n = end - idx
    return bytes(data[idx:idx + n]).decode("utf-8", "replace")


def _scintilla(c, msg, wp, lp):
    from .guiobj import ctrl_set, ctrl_opt
    ed = _GtkEdit(c)
    raw = _sci_bytes(c)
    text = raw.decode("utf-8")

    def sel_bytes():
        s, e = ed.sel()
        return len(text[:s].encode("utf-8")), len(text[:e].encode("utf-8"))

    def set_text(t):
        ctrl_set(c, "Text", t)
        st["modified"] = True
    st = _st(c)
    if msg == 2181:                                                     # SCI_SETTEXT
        set_text(_sci_str(lp))
        return 0
    if msg == 2182:                                                     # SCI_GETTEXT
        return _sci_put(lp, raw, wp - 1) if lp else len(raw)
    if msg in (2006, 2183):                                             # SCI_GETLENGTH / GETTEXTLENGTH
        return len(raw)
    if msg == 2282:                                                     # SCI_APPENDTEXT
        set_text(text + _sci_str(lp, wp))
        return 0
    if msg in (2001, 2003):                                             # SCI_ADDTEXT / SCI_INSERTTEXT
        add = _sci_str(lp, wp if msg == 2001 else None)
        if msg == 2001:
            pos = sel_bytes()[1]
        else:
            pos = len(raw) if _s32(wp) == -1 else _s32(wp)
        i = _sci_chars(raw, pos)
        set_text(text[:i] + add + text[i:])
        ed.set_sel(i + len(add), i + len(add)) if msg == 2001 else None
        return 0
    if msg == 2004:                                                     # SCI_CLEARALL
        set_text("")
        return 0
    if msg in (2008, 2145):                                             # SCI_GETCURRENTPOS / GETSELECTIONEND
        return sel_bytes()[1]
    if msg == 2143:                                                     # SCI_GETSELECTIONSTART
        return sel_bytes()[0]
    if msg == 2025:                                                     # SCI_GOTOPOS
        i = _sci_chars(raw, wp)
        ed.set_sel(i, i)
        return 0
    if msg == 2160:                                                     # SCI_SETSEL(anchor, caret)
        a = _sci_chars(raw, wp)
        b = len(text) if _s32(lp) == -1 else _sci_chars(raw, lp)
        ed.set_sel(min(a, b), max(a, b))
        return 0
    if msg == 2013:                                                     # SCI_SELECTALL
        ed.set_sel(0, -1)
        return 0
    if msg == 2161:                                                     # SCI_GETSELTEXT
        s, e = ed.sel()
        sel = text[s:e].encode("utf-8")
        return _sci_put(lp, sel) if lp else len(sel)
    if msg == 2170:                                                     # SCI_REPLACESEL
        ed.replace_sel(_sci_str(lp))
        st["modified"] = True
        return 0
    if msg == 2171:                                                     # SCI_SETREADONLY
        ctrl_opt(c, "+ReadOnly" if wp else "-ReadOnly")
        return 0
    if msg == 2140:                                                     # SCI_GETREADONLY
        return int(bool(c.readonly))
    if msg == 2154:                                                     # SCI_GETLINECOUNT
        return text.count("\n") + 1
    if msg == 2166:                                                     # SCI_LINEFROMPOSITION
        return text[:_sci_chars(raw, wp)].count("\n")
    if msg == 2167:                                                     # SCI_POSITIONFROMLINE
        lines = text.split("\n")
        if wp >= len(lines):
            return -1
        return len("\n".join(lines[:wp]).encode("utf-8")) + (1 if wp else 0)
    if msg == 2159:                                                     # SCI_GETMODIFY
        return int(bool(st.get("modified")))
    if msg == 2014:                                                     # SCI_SETSAVEPOINT
        st["modified"] = False
        return 0
    if msg in (2177, 2178, 2179, 2180):                                 # SCI_CUT / COPY / PASTE / CLEAR
        from .clipboard import get_text, set_text as clip_set
        s, e = ed.sel()
        if msg in (2177, 2178) and e > s:
            clip_set(text[s:e])
        if msg in (2177, 2180) and e > s:
            ed.replace_sel("")
        if msg == 2179:
            ed.replace_sel(get_text())
        return 0
    if msg in (2174, 2176, 2011, 2175, 2268, 2056, 2051, 2052, 2050, 4001, 4005, 2069, 2240, 2242, 2130):
        # CANUNDO / UNDO / REDO / EMPTYUNDOBUFFER / SETWRAPMODE / styling and lexer setup: no visible effect here
        return 0
    return None


_BY_TYPE = {"IPAddress": _ipaddress, "Edit": _edit, "ListBox": _listbox, "DDL": _combo, "ComboBox": _combo, "Progress": _progress,
            "Slider": _slider, "UpDown": _updown, "Hotkey": _hotkey, "StatusBar": _statusbar,
            "ListView": _listview, "TreeView": _treeview}


# ---------------------------------------------------------------- other programs' controls (AT-SPI)
# Message numbers of the list-like messages, LB_ and CB_ side by side.
_LIST_MSGS = {
    "count": (0x18B, 0x146), "cursel": (0x188, 0x147), "setcursel": (0x186, 0x14E), "text": (0x189, 0x148),
    "textlen": (0x18A, 0x149), "find": (0x18F, 0x14C), "findexact": (0x1A2, 0x158), "select": (0x18C, 0x14D),
}
_LIST_BY_MSG = {m: (op, i) for op, pair in _LIST_MSGS.items() for i, m in enumerate(pair)}
_LIST_ROLES = ({"list", "list box"}, {"combo box"})                     # roles answering LB_, CB_ messages


def handle_foreign(f, msg, wp, lp):
    """A Win32 message to another program's control.  Anything that isn't mapped returns 0, as an unknown
    message to a real control does."""
    try:
        r = _foreign(f, msg, wp, lp)
    except Exception:
        return 0
    return 0 if r is None else r


def _foreign(f, msg, wp, lp):
    from .atspi_ import CHECKABLE, TEXTUAL
    role = f.role
    if msg == 0x0D:                                                     # WM_GETTEXT
        n = wp & 0xFFFFFFFF
        if not n or not lp:
            return 0
        s = f.text()[:n - 1]
        _put(lp, s)
        return len(s)
    if msg == 0x0E:                                                     # WM_GETTEXTLENGTH
        return len(f.text())
    if msg == 0x0C:                                                     # WM_SETTEXT
        return int(f.set_text(_str_arg(lp)))
    if f.cls == "Button":
        if msg == 0xF5:                                                 # BM_CLICK
            f.click()
            return 0
        if msg == 0xF0:                                                 # BM_GETCHECK
            return f.checked() if role in CHECKABLE else 0
        if msg == 0xF1 and role in CHECKABLE:                           # BM_SETCHECK
            f.set_checked(bool(wp))
            return 0
        return None
    hit = _LIST_BY_MSG.get(msg)
    if hit is not None and role in _LIST_ROLES[hit[1]]:
        return _foreign_list(f, hit[0], wp, lp)
    if role in ("slider", "progress bar", "spin button", "scroll bar") and f.has_value():
        r = _foreign_value(f, msg, wp, lp)
        if r is not None:
            return r
    if role in TEXTUAL:
        return _edit_text(_ForeignEdit(f), msg, wp, lp)
    if role == "page tab list":
        if msg == 0x1304:                                               # TCM_GETITEMCOUNT
            return len(f.item_nodes())
        if msg == 0x130B:                                               # TCM_GETCURSEL
            return f.index() - 1
        if msg == 0x130C:                                               # TCM_SETCURSEL -> the previous tab
            old = f.index() - 1
            i = _s32(wp)
            return old if 0 <= i < len(f.item_nodes()) and f.choose(i + 1) else -1
        return None
    if role in ("table", "tree table"):
        if msg == 0x1004:                                               # LVM_GETITEMCOUNT
            return f.n_rows()
        if msg == 0x1032:                                               # LVM_GETSELECTEDCOUNT
            return len(f.selected_rows())
        if msg == 0x100C:                                               # LVM_GETNEXTITEM
            start, flags = _s32(wp), lp & 0xFFFF
            if flags & 2:                                               # LVNI_SELECTED
                return next((r for r in f.selected_rows() if r > start), -1)
            if flags == 0:                                              # LVNI_ALL
                return start + 1 if start + 1 < f.n_rows() else -1
        return None
    return None


def _foreign_list(f, op, wp, lp):
    items = f.items()
    if op == "count":
        return len(items)
    if op == "cursel":
        return f.index() - 1
    i = _s32(wp)
    if op == "setcursel":
        return i if 0 <= i < len(items) and f.choose(i + 1) else ERR
    if op in ("text", "textlen"):
        if not 0 <= i < len(items):
            return ERR
        if op == "text" and lp:
            _put(lp, items[i])
        return len(items[i])
    s = _str_arg(lp)
    if op in ("find", "findexact"):
        return _find(items, wp, s, op == "findexact")
    if op == "select":
        k = _find(items, wp, s, False)
        return k if k != ERR and f.choose(k + 1) else ERR
    return None


def _foreign_value(f, msg, wp, lp):
    role = f.role
    if role == "slider":
        if msg == 0x400:                                                # TBM_GETPOS
            return int(f.value())
        if msg == 0x401:                                                # TBM_GETRANGEMIN
            return int(f.value_range()[0])
        if msg == 0x402:                                                # TBM_GETRANGEMAX
            return int(f.value_range()[1])
        if msg == 0x405:                                                # TBM_SETPOS
            f.set_value(_s32(lp))
            return 0
    if role == "progress bar" and msg == 0x408:                         # PBM_GETPOS
        lo, hi = f.value_range()
        v = f.value()
        return int(round(v * 100 if hi <= 1 else v))                    # GTK reports a fraction; Win32's range is 0-100
    if role in ("spin button", "scroll bar"):
        if msg == 0x472:                                                # UDM_GETPOS32
            _put_u32(lp, 0)
            return int(f.value())
        if msg == 0x471:                                                # UDM_SETPOS32 -> the previous position
            old = int(f.value())
            f.set_value(_s32(lp))
            return old
    return None
