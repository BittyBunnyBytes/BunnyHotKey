"""RegEx on the system's libpcre16 - PCRE 8.x in UTF-16, the engine AutoHotkey itself uses - so options, newline
conventions, \\R, callouts and the rest behave as in AutoHotkey (Python's re is the fallback when the library
isn't installed).  The compiled pattern and its matches
look like re's (search/match, group/start/end/span, groups/groupindex), so regex.py uses them unchanged.

AutoHotkey patches PCRE so that (?CName) and (?CNumber:Name) call a function by name; stock PCRE only has
numbered callouts, so each callout is renumbered into a table that remembers its number and name."""
from __future__ import annotations

import ctypes
import ctypes.util

from .. import objects as O
from ..objects import throw

PCRE_CASELESS, PCRE_MULTILINE, PCRE_DOTALL, PCRE_EXTENDED = 0x1, 0x2, 0x4, 0x8
PCRE_ANCHORED, PCRE_DOLLAR_ENDONLY, PCRE_EXTRA, PCRE_UNGREEDY = 0x10, 0x20, 0x40, 0x200
PCRE_UTF16, PCRE_NO_UTF16_CHECK, PCRE_AUTO_CALLOUT, PCRE_DUPNAMES = 0x800, 0x2000, 0x4000, 0x80000
PCRE_NEWLINE_CR, PCRE_NEWLINE_LF, PCRE_NEWLINE_CRLF = 0x100000, 0x200000, 0x300000
PCRE_NEWLINE_ANY, PCRE_NEWLINE_ANYCRLF, PCRE_BSR_ANYCRLF, PCRE_BSR_UNICODE = 0x400000, 0x500000, 0x800000, 0x1000000
PCRE_NO_AUTO_POSSESS = 0x20000
PCRE_INFO_CAPTURECOUNT, PCRE_INFO_NAMEENTRYSIZE, PCRE_INFO_NAMECOUNT, PCRE_INFO_NAMETABLE = 2, 7, 8, 9
PCRE_ERROR_NOMATCH, PCRE_ERROR_CALLOUT = -1, -9
AUTO_CALLOUT = 255

_OPTION_FLAGS = {"i": PCRE_CASELESS, "m": PCRE_MULTILINE, "s": PCRE_DOTALL, "x": PCRE_EXTENDED,
                 "A": PCRE_ANCHORED, "D": PCRE_DOLLAR_ENDONLY, "J": PCRE_DUPNAMES, "U": PCRE_UNGREEDY,
                 "X": PCRE_EXTRA, "C": PCRE_AUTO_CALLOUT}


class _CalloutBlock(ctypes.Structure):
    _fields_ = [("version", ctypes.c_int), ("callout_number", ctypes.c_int),
                ("offset_vector", ctypes.POINTER(ctypes.c_int)), ("subject", ctypes.c_void_p),
                ("subject_length", ctypes.c_int), ("start_match", ctypes.c_int),
                ("current_position", ctypes.c_int), ("capture_top", ctypes.c_int),
                ("capture_last", ctypes.c_int), ("callout_data", ctypes.c_void_p),
                ("pattern_position", ctypes.c_int), ("next_item_length", ctypes.c_int),
                ("mark", ctypes.c_void_p)]


_CALLOUT_FN = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(_CalloutBlock))
_LIB = {}


def available():
    return _lib() is not None


def _lib():
    if "lib" not in _LIB:
        name = ctypes.util.find_library("pcre16")
        lib = None
        if name:
            try:
                lib = ctypes.CDLL(name)
                lib.pcre16_compile.restype = ctypes.c_void_p
                lib.pcre16_compile.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p),
                                               ctypes.POINTER(ctypes.c_int), ctypes.c_void_p]
                lib.pcre16_exec.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_int]
                lib.pcre16_fullinfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
                _LIB["hook"] = _CALLOUT_FN(_callout)
                ctypes.c_void_p.in_dll(lib, "pcre16_callout").value = ctypes.cast(_LIB["hook"], ctypes.c_void_p).value
            except (OSError, AttributeError):
                lib = None
        _LIB["lib"] = lib
    return _LIB["lib"]


def _skip_escape(pat, i):
    """Index after the escape at pat[i] ("\\x", or a whole \\Q...\\E)."""
    if pat[i + 1:i + 2] == "Q":
        j = pat.find("\\E", i + 2)
        return len(pat) if j < 0 else j + 2
    return i + 2


def renumber_callouts(pat):
    """-> (pattern with only (?C<k>) callouts, {k: (callout number, function name)})."""
    out, table, i, n, in_class = [], {}, 0, len(pat), False
    while i < n:
        c = pat[i]
        if c == "\\" and i + 1 < n:
            j = _skip_escape(pat, i)
            out.append(pat[i:j])
            i = j
            continue
        if in_class:
            in_class = c != "]"
        elif c == "[":
            in_class = True
            if pat[i + 1:i + 2] == "]" or pat[i + 1:i + 3] == "^]":     # "[]...]" / "[^]...]"
                k = i + (3 if pat[i + 1] == "^" else 2)
                out.append(pat[i:k])
                i = k
                continue
        elif pat.startswith("(?C", i):
            end = pat.find(")", i)
            if end < 0:
                break                                       # PCRE reports the missing ')'
            arg = pat[i + 3:end]
            digits = len(arg) - len(arg.lstrip("0123456789"))
            if digits == len(arg):
                number, name = int(arg or 0), ""
            elif arg[digits] == ":":
                number, name = int(arg[:digits] or 0), arg[digits + 1:]
            else:
                number, name = 0, arg                       # (?C123Func) is Func with number 0, as in AutoHotkey
            if number > 255:
                out.append(pat[i:end + 1])                  # PCRE raises "number after (?C is > 255"
            else:
                k = len(table)
                if k >= AUTO_CALLOUT:
                    throw("Error", "Compile error: too many callouts.", pat)
                table[k] = (number, name)
                out.append(f"(?C{k})")
            i = end + 1
            continue
        out.append(c)
        i += 1
    out.append(pat[i:])
    return "".join(out), table


def _u16(s):
    return s.encode("utf-16-le", "surrogatepass")


class Pattern:
    """A compiled pattern with the parts of re.Pattern that regex.py uses."""

    def __init__(self, needle, pat, options, newline):
        lib = _lib()
        self.needle = needle
        pcre_pat, self.callouts = renumber_callouts(pat)
        # AutoHotkey's PCRE (8.30) predates automatic possessification, which would skip callouts on backtracking
        flags = PCRE_UTF16 | PCRE_NO_UTF16_CHECK | PCRE_BSR_ANYCRLF | PCRE_NO_AUTO_POSSESS
        for o in options:
            flags |= _OPTION_FLAGS.get(o, 0)
        if newline == "a":                                  # `a: any newline, and \R matches Unicode newlines too
            flags &= ~PCRE_BSR_ANYCRLF
        flags |= {"a": PCRE_NEWLINE_ANY | PCRE_BSR_UNICODE, "n": PCRE_NEWLINE_LF, "r": PCRE_NEWLINE_CR,
                  "rn": PCRE_NEWLINE_CRLF}.get(newline or "", PCRE_NEWLINE_ANYCRLF)     # AHK's default: ANYCRLF
        self.flags = flags
        self._buf = ctypes.create_string_buffer(_u16(pcre_pat) + b"\0\0")
        err, off = ctypes.c_char_p(), ctypes.c_int()
        self.code = lib.pcre16_compile(self._buf, flags, ctypes.byref(err), ctypes.byref(off), None)
        if not self.code:
            throw("Error", f"Compile error {off.value}: {(err.value or b'').decode()}", needle)
        cnt = ctypes.c_int()
        lib.pcre16_fullinfo(self.code, None, PCRE_INFO_CAPTURECOUNT, ctypes.byref(cnt))
        self.groups = cnt.value
        self.groupindex = {}
        size, count, table = ctypes.c_int(), ctypes.c_int(), ctypes.c_void_p()
        lib.pcre16_fullinfo(self.code, None, PCRE_INFO_NAMEENTRYSIZE, ctypes.byref(size))
        lib.pcre16_fullinfo(self.code, None, PCRE_INFO_NAMECOUNT, ctypes.byref(count))
        lib.pcre16_fullinfo(self.code, None, PCRE_INFO_NAMETABLE, ctypes.byref(table))
        for e in range(count.value):
            raw = ctypes.string_at(table.value + 2 * e * size.value, 2 * size.value)
            num = int.from_bytes(raw[:2], "little")
            name = raw[2:].decode("utf-16-le").split("\0")[0]
            self.groupindex.setdefault(name, num)

    def search(self, h, start=0):
        return self._exec(h, start, 0)

    def match(self, h, start=0):
        return self._exec(h, start, PCRE_ANCHORED)

    def _exec(self, h, start, flags):
        lib = _lib()
        subject = ctypes.create_string_buffer(_u16(h) + b"\0\0")
        n16 = len(subject) // 2 - 1
        to16 = _Offsets(h)
        ovec = (ctypes.c_int * (3 * (self.groups + 1)))()
        state = {"pattern": self, "h": h, "map": to16, "error": None}
        _ACTIVE.append(state)
        try:
            rc = lib.pcre16_exec(self.code, None, subject, n16, to16.to_u16(start), flags, ovec, len(ovec))
        finally:
            _ACTIVE.pop()
        if state["error"] is not None:
            raise state["error"]
        if rc == PCRE_ERROR_NOMATCH:
            return None
        if rc < 0:
            throw("Error", "PCRE execution error.", str(rc))    # ERR_PCRE_EXEC, the code as Extra
        spans = [(to16.from_u16(ovec[2 * g]), to16.from_u16(ovec[2 * g + 1])) if ovec[2 * g] >= 0 else (-1, -1)
                 for g in range(self.groups + 1)]
        return Match(self, h, spans)


class _Offsets:
    """UTF-16 offsets <-> str indexes (they differ only when the text has characters outside the BMP)."""

    def __init__(self, h):
        self.simple = all(ord(c) < 0x10000 for c in h)
        if not self.simple:
            self.u16 = [0]
            for c in h:
                self.u16.append(self.u16[-1] + (2 if ord(c) >= 0x10000 else 1))
            self.back = {u: i for i, u in enumerate(self.u16)}

    def to_u16(self, i):
        return i if self.simple else self.u16[min(i, len(self.u16) - 1)]

    def from_u16(self, u):
        return u if self.simple or u < 0 else self.back.get(u, u)


class Match:
    """The parts of re.Match that regex.py's MatchInfo and RegExReplace use."""

    def __init__(self, pattern, h, spans):
        self.re, self.string, self._spans = pattern, h, spans

    def _index(self, g):
        if isinstance(g, str):
            if g not in self.re.groupindex:
                raise IndexError(g)
            g = self.re.groupindex[g]
        if not 0 <= g < len(self._spans):
            raise IndexError(g)
        return g

    def span(self, g=0):
        return self._spans[self._index(g)]

    def start(self, g=0):
        return self.span(g)[0]

    def end(self, g=0):
        return self.span(g)[1]

    def group(self, g=0):
        s, e = self.span(g)
        return None if s < 0 else self.string[s:e]

    @property
    def lastindex(self):
        found = [g for g in range(1, len(self._spans)) if self._spans[g][0] >= 0]
        return found[-1] if found else None


_ACTIVE: list[dict] = []


def _callout(cbp):
    """pcre16_callout: calls the script's callout function (RegExCallout in regex.cpp)."""
    if not _ACTIVE:
        return 0
    st = _ACTIVE[-1]
    if st["error"] is not None:
        return PCRE_ERROR_CALLOUT
    cb = cbp.contents
    pat = st["pattern"]
    if cb.callout_number == AUTO_CALLOUT and cb.callout_number not in pat.callouts:
        number, name = AUTO_CALLOUT, ""
    else:
        number, name = pat.callouts.get(cb.callout_number, (cb.callout_number, ""))
    try:
        name = name or "pcre_callout"
        fn = _find_callout(name)
        if fn is None:
            throw("ValueError", "Invalid callout", name)
        to = st["map"]
        ov = cb.offset_vector
        spans = [(to.from_u16(cb.start_match), to.from_u16(cb.current_position))]
        for g in range(1, pat.groups + 1):
            if g < cb.capture_top and ov[2 * g] >= 0:
                spans.append((to.from_u16(ov[2 * g]), to.from_u16(ov[2 * g + 1])))
            else:
                spans.append((-1, -1))
        from .regex import MatchInfo, _setup_matchinfo_proto
        _setup_matchinfo_proto()
        mi = MatchInfo(Match(pat, st["h"], spans))
        r = O.RT.call(fn, [mi, number, to.from_u16(cb.start_match) + 1, st["h"], pat.needle])
        return int(O.RT.to_num(r)) if r not in ("", None) else 0
    except BaseException as e:                          # an exception or Exit in the callout ends the match
        st["error"] = e
        return PCRE_ERROR_CALLOUT


def _find_callout(name):
    """The callout function: the global variable or function of that name, looked up at each call (AHK also
    finds a local variable of the calling function first)."""
    cell = O.RT.globals.get(name.lower())
    v = getattr(cell, "value", None)
    return v if isinstance(v, O.AhkObject) else None
