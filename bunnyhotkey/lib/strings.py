"""String built-ins (lib/string.cpp, lib/format.cpp)."""
from __future__ import annotations

import math
import re

from .. import objects as O
from ..objects import AhkArray, AhkObject, throw, type_error_msg
from ..values import UNSET, fmt_float, str_to_number, wrap
from . import export, setref


def rt():
    return O.RT


def S(v):
    return O.RT.to_str(v)


def I(v):
    return O.RT.to_int(v)


def _case_mode(cs):
    """CaseSense param -> 'on' | 'off' | 'locale'."""
    if cs is UNSET or cs == "":
        return "off"
    if type(cs) in (int, float):
        return "on" if cs else "off"
    s = S(cs).lower()
    if s in ("on", "1"):
        return "on"
    if s in ("off", "0"):
        return "off"
    if s == "locale":
        return "locale"
    throw("ValueError", "Invalid value.", S(cs))


def _fold(s, mode):
    if mode == "on":
        return s
    if mode == "locale":
        return s.casefold()
    return s.lower()


@export()
def StrLen(s):
    return len(S(s))


@export()
def StrLower(s):
    return S(s).lower()


@export()
def StrUpper(s):
    return S(s).upper()


@export()
def StrTitle(s):
    s = S(s)
    out = []
    prev_alpha = False
    for c in s:
        if c.isalpha():
            out.append(c.lower() if prev_alpha else c.upper())
            prev_alpha = True
        else:
            out.append(c)
            prev_alpha = False
    return "".join(out)


@export()
def SubStr(s, start, length=UNSET):
    s = S(s)
    start = I(start)
    L = len(s)
    if start == 0:
        start = 1
    if start < 0:
        start = L + start + 1
        if start < 1:
            start = 1
    i = start - 1
    if i >= L:
        return ""
    if length is UNSET or length == "":
        return s[i:]
    n = I(length)
    if n < 0:
        end = L + n
        return s[i:end] if end > i else ""
    return s[i:i + n]


@export()
def InStr(haystack, needle, casesense=UNSET, start=1, occurrence=1):
    h = S(haystack)
    n = S(needle)
    if n == "":
        throw("ValueError", "Invalid value.", "") if False else None
        return 0
    mode = _case_mode(casesense)
    hf, nf = _fold(h, mode), _fold(n, mode)
    start = I(start) if start != "" else 1
    occ = I(occurrence) if occurrence != "" else 1
    if occ < 1:
        throw("ValueError", "Invalid value.", str(occ))
    L = len(h)
    if start == 0:
        throw("ValueError", "Invalid value.", "0")
    if start > 0:
        pos = start - 1
        for _ in range(occ):
            i = hf.find(nf, pos)
            if i < 0:
                return 0
            pos = i + 1
        return i + 1
    # search right to left; start -1 = a match may begin at the last character
    limit = L + start          # highest 0-based index a match may start at
    i = -1
    for _ in range(occ):
        if limit < 0:
            return 0
        i = hf.rfind(nf, 0, limit + len(nf))
        if i < 0:
            return 0
        limit = i - 1
    return i + 1


@export(byref=(3,))
def StrReplace(haystack, needle, replace="", casesense=UNSET, outcount=UNSET, limit=-1):
    h = S(haystack)
    n = S(needle)
    r = S(replace)
    lim = I(limit) if limit != "" else -1
    mode = _case_mode(casesense)
    if n == "":
        setref(outcount, 0)
        return h
    count = 0
    if mode == "on":
        if lim < 0:
            count = h.count(n)
            res = h.replace(n, r)
        else:
            count = min(h.count(n), lim)
            res = h.replace(n, r, lim)
    else:
        hf = _fold(h, mode)
        nf = _fold(n, mode)
        out = []
        pos = 0
        while lim < 0 or count < lim:
            i = hf.find(nf, pos)
            if i < 0:
                break
            out.append(h[pos:i])
            out.append(r)
            pos = i + len(n)
            count += 1
        out.append(h[pos:])
        res = "".join(out)
    setref(outcount, count)
    return res


@export()
def StrSplit(s, delims=UNSET, omit=UNSET, maxparts=-1):
    s = S(s)
    if isinstance(delims, AhkArray):
        dl = [S(d) for d in delims.items]
    elif delims is UNSET or delims == "":
        dl = []
    else:
        dl = [S(delims)]
    omit_chars = S(omit) if omit is not UNSET else ""
    maxp = I(maxparts) if maxparts != "" else -1
    if not dl:
        parts = list(s)
    else:
        dl = [d for d in dl if d]
        parts = []
        pos = 0
        while True:
            if maxp > 0 and len(parts) == maxp - 1:
                parts.append(s[pos:])
                break
            best = -1
            bl = 0
            for d in dl:
                i = s.find(d, pos)
                if i >= 0 and (best < 0 or i < best or (i == best and len(d) > bl)):
                    best, bl = i, len(d)
            if best < 0:
                parts.append(s[pos:])
                break
            parts.append(s[pos:best])
            pos = best + bl
    if omit_chars:
        parts = [p.strip(omit_chars) for p in parts]
    return AhkArray(None, parts)


@export()
def Trim(s, omit=" \t"):
    return S(s).strip(S(omit))


@export()
def LTrim(s, omit=" \t"):
    return S(s).lstrip(S(omit))


@export()
def RTrim(s, omit=" \t"):
    return S(s).rstrip(S(omit))


@export()
def StrCompare(a, b, casesense=UNSET):
    mode = _case_mode(casesense)
    x, y = _fold(S(a), mode), _fold(S(b), mode)
    return (x > y) - (x < y)


@export()
def Chr(n):
    n = I(n)
    if n < 0 or n > 0x10FFFF:
        throw("ValueError", "Invalid value.", str(n))
    return chr(n) if n else "\x00"


@export()
def Ord(s):
    s = S(s)
    return ord(s[0]) if s else 0


_STR_BUFS: dict[str, object] = {}


@export()
def StrPtr(s):
    """Address of a UTF-16 copy of the string, readable with StrGet/NumGet (Bunny Hot Key strings are Python
    strings, so writes through the pointer don't change the variable)."""
    from .buffer import BufferObj
    s = S(s)
    b = _STR_BUFS.get(s)
    if b is None:
        if len(_STR_BUFS) > 4096:
            _STR_BUFS.clear()
        raw = s.encode("utf-16-le") + b"\0\0"
        b = BufferObj(len(raw))
        b.data[:] = raw
        _STR_BUFS[s] = b
    return b.addr


@export()
def VerCompare(a, b):
    """VersionSatisfies(a, b, true) in util.cpp: b may start with <, >, <=, >= or = and then yields 0/1."""
    from .process import ver_compare
    a, b = S(a), S(b)
    m = re.match(r"(<?)(>?)(=?)", b)
    lt, gt, eq = bool(m[1]), bool(m[2]), bool(m[3])
    req = b[m.end():]
    result = ver_compare(a.lstrip("v")[:] if a.startswith("v") else a, req[1:] if req.startswith("v") else req)
    if not (lt or gt or eq):
        return result
    return int((lt, eq, gt)[result + 1])


# ---------------------------------------------------------------- Sort
@export()
def Sort(s, options="", callback=UNSET):
    s = S(s)
    opts = S(options)
    delim = "\n"
    m = re.search(r"D(.)", opts)
    if m:
        delim = m.group(1)
        if delim == "\\":
            delim = "\\"
    ol = opts.upper()
    numeric = "N" in re.sub(r"D.", "", ol)
    reverse = "R" in re.sub(r"D.", "", ol)
    unique = "U" in re.sub(r"D.", "", ol)
    casesense = re.search(r"(?<!D)C(?!L)", re.sub(r"D.", "", opts)) is not None
    random = "RANDOM" in ol
    pos_m = re.search(r"P(\d+)", opts, re.I)
    pstart = int(pos_m.group(1)) - 1 if pos_m else 0
    trailing = s.endswith(delim) if delim == "\n" else False
    items = s.split(delim)
    if delim == "\n":
        items = [x[:-1] if x.endswith("\r") else x for x in items]
    if trailing and items and items[-1] == "":
        items.pop()
    if random:
        import random as rnd
        rnd.shuffle(items)
    elif callback is not UNSET:
        import functools
        r = rt()

        def cmpf(a, b):
            res = r.call(callback, [a, b, 0])
            return int(r.to_num(res)) if res != "" else 0
        items.sort(key=functools.cmp_to_key(cmpf))
        if reverse:
            items.reverse()
    else:
        def key(x):
            x = x[pstart:]
            if numeric:
                n = str_to_number(x.split()[0] if x.split() else "")
                if n is None:
                    m2 = re.match(r"\s*[-+]?(\d+\.?\d*|\.\d+)", x)
                    n = float(m2.group(0)) if m2 else 0
                return (0, n, "")
            return (1, 0, x if casesense else x.lower())
        items.sort(key=key, reverse=reverse)
    if unique:
        out = []
        seen = set()
        for x in items:
            k = x if casesense else x.lower()
            if numeric:
                k = str_to_number(x) if str_to_number(x) is not None else k
            if out and k == (out[-1] if casesense else out[-1].lower()) or (numeric and k in seen):
                continue
            seen.add(k)
            out.append(x)
        items = out
    res = delim.join(items)
    if trailing:
        res += delim
    return res


# ---------------------------------------------------------------- Format
_FMT_RE = re.compile(r"\{(\d*)(?::([^}]*))?\}|\{\{|\}\}")
_SPEC_RE = re.compile(r"([-+0 #]*)(\d*)(?:\.(\d+))?([hlIL]*)([diouxXeEfgGaAcCps]?)$")


@export()
def Format(fmt, *values):
    f = S(fmt)
    r = rt()
    out = []
    pos = 0
    auto = 0
    while True:
        i = f.find("{", pos)
        if i < 0:
            out.append(f[pos:])
            break
        out.append(f[pos:i])
        if f.startswith("{{", i) and False:
            pass
        m = re.compile(r"\{(\d*)(?::([^}]*))?\}").match(f, i)
        if not m:
            out.append("{")
            pos = i + 1
            continue
        idx_s, spec = m.group(1), m.group(2) or ""
        if idx_s:
            idx = int(idx_s)
            auto = idx
        else:
            auto += 1
            idx = auto
        v = values[idx - 1] if 0 < idx <= len(values) else ""
        if v is UNSET:
            v = ""
        out.append(_format_one(r, v, spec))
        pos = m.end()
    return "".join(out)


def _format_one(r, v, spec):
    if spec == "":
        return r.to_str(v)
    # custom case conversion suffix: U/L/T after type
    m = re.match(r"([-+0 #]*)(\d*)(?:\.(\d+))?([hlIL]*)([diouxXeEfgGaAcCpsULT]?)$", spec)
    if not m:
        return r.to_str(v)
    flags, width, prec, _len, typ = m.groups()
    if not typ and _len.endswith("L"):
        _len, typ = _len[:-1], "L"          # {:L} is the lowercase custom type, not a length modifier
    case = ""
    if typ in ("U", "L", "T"):
        case = typ
        typ = "s"
    if typ in ("", "s"):
        s = r.to_str(v)
        if prec:
            s = s[:int(prec)]
        if case == "U":
            s = s.upper()
        elif case == "L":
            s = s.lower()
        elif case == "T":
            s = StrTitle(s)
        return _pad(s, flags, width)
    if typ == "c":
        return _pad(chr(r.to_int(v)), flags, width)
    if typ in "dioxXuc":
        n = r.to_num(v)
        n = int(n) if type(n) is float else n
        if typ == "u" and n < 0:
            n &= 0xFFFFFFFFFFFFFFFF
        if typ in "xX" and n < 0:
            n &= 0xFFFFFFFFFFFFFFFF
        if typ == "o" and n < 0:
            n &= 0xFFFFFFFFFFFFFFFF
        pyt = {"i": "d", "u": "d"}.get(typ, typ)
        fmt = "%" + flags + width + ("." + prec if prec else "") + pyt
        return fmt % n
    if typ in "eEfgGaA":
        n = float(r.to_num(v))
        pyt = typ
        if typ in "aA":
            s = n.hex()
            return _pad(s if typ == "a" else s.upper(), flags, width)
        fmt = "%" + flags + width + ("." + prec if prec else "") + pyt
        s = fmt % n
        return s
    if typ == "p":
        n = r.to_int(v)
        return "%016X" % (n & 0xFFFFFFFFFFFFFFFF)
    return r.to_str(v)


def _pad(s, flags, width):
    if not width:
        return s
    w = int(width)
    if "-" in flags:
        return s.ljust(w)
    if "0" in flags:
        return s.rjust(w, "0")
    return s.rjust(w)
