"""RegExMatch / RegExReplace (lib/regex.cpp) on libpcre16 (pcre16.py), or on Python's re with a PCRE
translation layer when that library isn't installed."""
from __future__ import annotations

import re

from .. import objects as O
from ..objects import AhkObject, CLASSES, throw
from ..values import UNSET
from . import export, setref

_cache: dict[str, tuple] = {}
# options before ")": letters, and the newline options `n, `r, `r`n and `a (real control characters in the needle,
# or a literal backtick and letter)
_OPT_RE = re.compile("^([imsxADJUXPSC\n\r\x07]*(?:`[nra][imsxADJUXPSC\n\r\x07]*)*)\\)")
POSIX = {"alpha": "a-zA-Z", "digit": "0-9", "alnum": "a-zA-Z0-9", "upper": "A-Z", "lower": "a-z",
         "space": r"\s", "blank": r" \t", "punct": r"!-/:-@\[-`{-~", "xdigit": "0-9A-Fa-f",
         "word": r"\w", "cntrl": r"\x00-\x1f\x7f", "print": r"\x20-\x7e", "graph": r"\x21-\x7e"}


def S(v):
    return O.RT.to_str(v)


def _translate(pat: str, ungreedy: bool) -> str:
    out = []
    i = 0
    n = len(pat)
    in_class = False
    while i < n:
        c = pat[i]
        if c == "\\" and i + 1 < n:
            d = pat[i + 1]
            if d == "Q":
                j = pat.find("\\E", i + 2)
                lit = pat[i + 2:] if j < 0 else pat[i + 2:j]
                out.append(re.escape(lit))
                i = n if j < 0 else j + 2
                continue
            if d == "E":
                i += 2
                continue
            if d == "x" and i + 2 < n and pat[i + 2] == "{":
                j = pat.find("}", i + 3)
                out.append("\\U%08x" % int(pat[i + 3:j], 16))
                i = j + 1
                continue
            if d == "h":
                out.append("[ \\t\\xa0]" if not in_class else " \\t\\xa0")
                i += 2
                continue
            if d == "H":
                out.append("[^ \\t\\xa0]")
                i += 2
                continue
            if d == "R":
                out.append("(?:\\r\\n|\\n|\\r|\\x0b|\\x0c|\\x85)")
                i += 2
                continue
            if d == "z":
                out.append("\\Z")
                i += 2
                continue
            if d == "Z":
                out.append("(?=\\n?\\Z)")
                i += 2
                continue
            if d == "g" and i + 2 < n:
                m = re.match(r"\\g\{?(-?\w+)\}?", pat[i:])
                if m:
                    ref = m.group(1)
                    out.append(f"\\{ref}" if ref.isdigit() else f"(?P={ref})")
                    i += m.end()
                    continue
            if d == "k" and i + 2 < n and pat[i + 2] in "<{'":
                close = {"<": ">", "{": "}", "'": "'"}[pat[i + 2]]
                j = pat.find(close, i + 3)
                out.append(f"(?P={pat[i + 3:j]})")
                i = j + 1
                continue
            if d == "p" or d == "P":
                m = re.match(r"\\[pP]\{?\^?(\w+)\}?", pat[i:])
                if m:
                    neg = d == "P"
                    prop = m.group(1)
                    cls = {"L": "a-zA-Z\\u00c0-\\u024f\\u0370-\\u03ff\\u0400-\\u04ff", "Lu": "A-Z", "Ll": "a-z",
                           "N": "0-9", "Nd": "0-9", "P": "!-/:-@\\[-`{-~", "Z": "\\s", "Zs": " "}.get(prop, "\\w")
                    out.append(("[^" if neg else "[") + cls + "]" if not in_class else cls)
                    i += m.end()
                    continue
            out.append(pat[i:i + 2])
            i += 2
            continue
        if in_class:
            if c == "[" and pat.startswith("[:", i):
                j = pat.find(":]", i)
                if j > 0:
                    name = pat[i + 2:j]
                    neg = name.startswith("^")
                    out.append(POSIX.get(name.lstrip("^"), ""))
                    i = j + 2
                    continue
            if c == "]":
                in_class = False
            out.append(c)
            i += 1
            continue
        if c == "[":
            in_class = True
            out.append(c)
            i += 1
            if i < n and pat[i] == "^":
                out.append("^")
                i += 1
            if i < n and pat[i] == "]":
                out.append("\\]")
                i += 1
            continue
        if c == "(" and pat.startswith("(?<", i) and i + 3 < n and pat[i + 3] not in "=!":
            out.append("(?P<")
            i += 3
            continue
        if c == "(" and pat.startswith("(?'", i):
            j = pat.find("'", i + 3)
            out.append("(?P<" + pat[i + 3:j] + ">")
            i = j + 1
            continue
        if c == "(" and pat.startswith("(?P>", i):
            raise re.error("recursion is not supported")
        if ungreedy and c in "*+?}" and not (c == "?" and out and out[-1] == "("):
            # U) inverts greediness
            out.append(c)
            i += 1
            if i < n and pat[i] == "?":
                i += 1          # lazy -> greedy
            elif i < n and pat[i] == "+":
                out.append("+")
                i += 1
            else:
                out.append("?")
            continue
        out.append(c)
        i += 1
    return "".join(out)


def compile_pattern(needle: str):
    hit = _cache.get(needle)
    if hit is not None:
        return hit
    flags = 0
    pat = needle
    m = _OPT_RE.match(needle)
    ungreedy = False
    anchored = False
    newline = None
    if m and m.group(1) is not None and ")" in needle[:m.end()]:
        opts = m.group(1)
        pat = needle[m.end():]
        k = 0
        while k < len(opts):
            o = opts[k]
            if o == "i":
                flags |= re.I
            elif o == "m":
                flags |= re.M
            elif o == "s":
                flags |= re.S
            elif o == "x":
                flags |= re.X
            elif o == "U":
                ungreedy = True
            elif o == "A":
                anchored = True
            elif o == "`" and k + 1 < len(opts):
                k += 1
                newline = opts[k]
            elif o in "\n\x07":
                newline = "n" if o == "\n" else "a"
            elif o == "\r":
                newline = "rn" if opts[k + 1:k + 2] == "\n" else "r"
                k += newline == "rn"
            k += 1
    from . import pcre16                                    # AutoHotkey's own engine when it's installed
    if pcre16.available():
        res = (pcre16.Pattern(needle, pat, m.group(1) if m else "", newline), False)
        _cache[needle] = res
        return res
    try:
        tr = _translate(pat, ungreedy)
        if anchored:
            tr = "(?:" + tr + ")"
        rx = re.compile(tr, flags)
    except re.error as e:
        throw("Error", f"Compile error {getattr(e, 'pos', 0) or 0}: {e.msg if hasattr(e, 'msg') else e}", needle)
    res = (rx, anchored)
    if len(_cache) > 200:
        _cache.clear()
    _cache[needle] = res
    return res


class MatchInfo(AhkObject):
    __slots__ = ("m",)

    def __init__(self, m):
        super().__init__(CLASSES["RegExMatchInfo"].prototype)
        self.m = m

    def group_index(self, key):
        r = O.RT
        if type(key) is int or (type(key) is str and key.isdigit()):
            return int(key)
        if type(key) is float:
            return int(key)
        name = r.to_str(key)
        if name in self.m.re.groupindex:
            return name
        for k in self.m.re.groupindex:
            if k.lower() == name.lower():
                return k
        throw("UnsetItemError", "Item has no value.", name) if False else None
        return name

    def value(self, key=0):
        g = self.group_index(key)
        try:
            v = self.m.group(g)
        except (IndexError, error_types()):
            throw("UnsetItemError", "Item has no value.", O.value_text(key)) if False else None
            return ""
        return v if v is not None else ""

    def pos(self, key=0):
        g = self.group_index(key)
        try:
            s = self.m.start(g)
        except (IndexError, error_types()):
            return 0
        return s + 1 if s >= 0 else 0

    def length(self, key=0):
        g = self.group_index(key)
        try:
            s, e = self.m.span(g)
        except (IndexError, error_types()):
            return 0
        return e - s if s >= 0 else 0

    def native_item_get(self, args):
        return self.value(args[0] if args else 0)

    def find(self, name):
        p, o = super().find(name)
        if p is None and name.lower() not in ("__get", "__call", "__set") and self.m is not None:
            for k in self.m.re.groupindex:
                if k.lower() == name.lower():
                    from ..objects import Prop
                    return Prop(k, self.value(k)), self
        return p, o


def error_types():
    return re.error


def _setup_matchinfo_proto():
    from ..classes import method, prop, _native_item
    p = CLASSES["RegExMatchInfo"].prototype
    if p.own("Pos") is not None:
        return
    method(p, "Pos", lambda this, n=0: this.pos(n))
    method(p, "Len", lambda this, n=0: this.length(n))
    method(p, "Value", lambda this, n=0: this.value(n))
    method(p, "Name", lambda this, n=0: _group_name(this, n))
    prop(p, "Count", get=lambda this: this.m.re.groups)
    prop(p, "Mark", get=lambda this: "")
    method(p, "__Enum", lambda this, n=1: _mi_enum(this, n))
    _native_item(p)
    # Pos/Len/Value also usable as properties: m.Pos, m.Pos[1]
    for nm, fn in (("Pos", lambda this, n=0: this.pos(n)), ("Len", lambda this, n=0: this.length(n)),
                   ("Value", lambda this, n=0: this.value(n)), ("Name", lambda this, n=0: _group_name(this, n))):
        from ..classes import bif
        pr = p.define_prop(nm, get=bif(nm, fn))


def _group_name(mi, n):
    idx = O.RT.to_int(n)
    for k, v in mi.m.re.groupindex.items():
        if v == idx:
            return k
    return ""


def _mi_enum(mi, n):
    from .core import Enumerator

    def gen():
        for i in range(mi.m.re.groups + 1):
            yield (i, mi.value(i)) if n > 1 else (mi.value(i),)
    return Enumerator(gen(), n)


def _search(rx, anchored, h, start):
    if anchored:
        return rx.match(h, start)
    return rx.search(h, start)


def _start_index(h, start):
    start = O.RT.to_int(start)
    if start == 0:
        start = 1
    if start < 0:
        start = max(len(h) + start + 1, 1)
    return start - 1


@export(byref=(2,))
def RegExMatch(haystack, needle, outvar=UNSET, start=1):
    _setup_matchinfo_proto()
    h = S(haystack)
    rx, anchored = compile_pattern(S(needle))
    i = _start_index(h, start)
    if i > len(h):
        setref(outvar, "")
        return 0
    m = _search(rx, anchored, h, i)
    if not m:
        setref(outvar, "")
        return 0
    setref(outvar, MatchInfo(m))
    return m.start() + 1


def regex_match_pos(rt, a, b):
    return RegExMatch(a, b)


_REPL_RE = re.compile(r"\$(?:\$|([ULT]?)(\d+)|([ULT]?)\{(\w+)\})")


def _expand(repl: str, m) -> str:
    def sub(mm):
        if mm.group(0) == "$$":
            return "$"
        case = mm.group(1) or mm.group(3) or ""
        ref = mm.group(2) if mm.group(2) is not None else mm.group(4)
        try:
            v = m.group(int(ref) if ref.isdigit() else ref)
        except (IndexError, re.error):
            v = ""
        v = v or ""
        if case == "U":
            v = v.upper()
        elif case == "L":
            v = v.lower()
        elif case == "T":
            v = v.title()
        return v
    if "$" not in repl:
        return repl
    return _REPL_RE.sub(sub, repl)


@export(byref=(3,))
def RegExReplace(haystack, needle, replacement="", outcount=UNSET, limit=-1, start=1):
    h = S(haystack)
    rx, anchored = compile_pattern(S(needle))
    repl = S(replacement)
    lim = O.RT.to_int(limit) if limit != "" else -1
    i = _start_index(h, start)
    out = [h[:i]]
    count = 0
    pos = i
    while lim < 0 or count < lim:
        m = _search(rx, anchored, h, pos) if pos <= len(h) else None
        if not m:
            break
        out.append(h[pos:m.start()])
        out.append(_expand(repl, m))
        count += 1
        if m.end() == m.start():
            if m.end() < len(h):
                out.append(h[m.end()])
            pos = m.end() + 1
        else:
            pos = m.end()
        if anchored:
            break
    if pos <= len(h):
        out.append(h[pos:])
    setref(outcount, count)
    return "".join(out)
