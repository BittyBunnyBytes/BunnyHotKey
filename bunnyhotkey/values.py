"""AHK v2 value semantics: pure numbers vs strings, conversions, operators.

Values are Python str / int / float / AhkObject.  Integers are 64-bit signed and
wrap like __int64.  Ported from util.cpp (IsNumeric, FTOA) and the operator
switch in script_expression.cpp (ExpandExpression).
"""
from __future__ import annotations

import math
import re

INT_MIN = -(1 << 63)
INT_MAX = (1 << 63) - 1
_MASK = (1 << 64) - 1


class _UnsetType:
    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self):
        return "unset"

    def __bool__(self):
        return False


UNSET = _UnsetType()      # an omitted parameter / unset item


def wrap(i: int) -> int:
    if INT_MIN <= i <= INT_MAX:
        return i
    i &= _MASK
    return i - (1 << 64) if i > INT_MAX else i


def fmt_float(f: float) -> str:
    """FTOA: %.17g, plus '.0' when no '.'/'e' and the result is a plain number."""
    if math.isinf(f):
        return "inf" if f > 0 else "-inf"
    if math.isnan(f):
        return "nan" if math.copysign(1, f) > 0 else "-nan(ind)"
    s = "%.17g" % f
    if "." not in s and "e" not in s:
        s += ".0"
    elif "e" in s:
        # MSVC prints a 3-digit exponent? No: UCRT prints at least 2 digits, like C99.
        mant, _, exp = s.partition("e")
        sign = exp[0] if exp[0] in "+-" else "+"
        digits = exp.lstrip("+-")
        s = f"{mant}e{sign}{digits.zfill(2)}"
    return s


_ws = " \t"
_HEX_RE = re.compile(r"[ \t]*([+-]?)0[xX]([0-9a-fA-F]+)[ \t]*\Z")
_INT_RE = re.compile(r"[ \t]*([+-]?)(\d+)[ \t]*\Z")
_FLOAT_RE = re.compile(r"[ \t]*[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?[ \t]*\Z")


def str_to_number(s: str, allow_blank=False):
    """IsNumeric + conversion: return int/float for a numeric string, else None."""
    m = _INT_RE.match(s)
    if m:
        v = int(m.group(2))
        if m.group(1) == "-":
            v = -v
        if INT_MIN <= v <= INT_MAX:
            return v
        return _strtoi64_overflow(v)
    m = _HEX_RE.match(s)
    if m:
        v = int(m.group(2), 16)
        v = wrap(v) if v <= _MASK else (-1 if m.group(1) == "-" else INT_MAX)
        if m.group(1) == "-":
            v = wrap(-v)
        return v
    m = _FLOAT_RE.match(s)
    if m:
        if "." not in m.group(0) and not m.group(2):
            return None
        try:
            return float(s.strip(_ws))
        except ValueError:
            return None
    if allow_blank and not s.strip(_ws):
        return 0
    return None


def _strtoi64_overflow(v):
    # _tcstoi64 saturates on overflow
    return INT_MAX if v > 0 else INT_MIN


def is_number(v) -> bool:
    return type(v) is int or type(v) is float


def to_number_or_none(v):
    """Numeric value of v (number or numeric string), else None."""
    t = type(v)
    if t is int or t is float:
        return v
    if t is str:
        return str_to_number(v)
    return None


def num_kind(v):
    """Returns (number, is_pure) or (None, False)."""
    t = type(v)
    if t is int or t is float:
        return v, True
    if t is str:
        n = str_to_number(v)
        return n, False
    return None, False


def type_name(v) -> str:
    t = type(v)
    if t is str:
        return "String"
    if t is int:
        return "Integer"
    if t is float:
        return "Float"
    if v is UNSET:
        return "unset"
    from .objects import AhkObject
    if isinstance(v, AhkObject):
        return v.type_name()
    return "Object"


def to_bool(v) -> bool:
    t = type(v)
    if t is int:
        return v != 0
    if t is float:
        return v != 0.0
    if t is str:
        if v == "":
            return False
        n = str_to_number(v)
        if n is None:
            return True
        return n != 0
    return v is not UNSET


__all__ = ["UNSET", "wrap", "fmt_float", "str_to_number", "to_bool", "type_name", "is_number"]
