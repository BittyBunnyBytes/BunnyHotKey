"""Math built-ins (lib/math.cpp)."""
from __future__ import annotations

import math
import random as _random

from .. import objects as O
from ..objects import throw, type_error_msg
from ..values import UNSET, wrap
from . import export


def N(v):
    return O.RT.to_num(v)


def _f(fn):
    def g(x):
        return float(fn(float(N(x))))
    return g


@export()
def Abs(n):
    v = N(n)
    return wrap(abs(v)) if type(v) is int else abs(v)


@export()
def Ceil(n):
    v = N(n)
    return int(math.ceil(v)) if type(v) is float else v


@export()
def Floor(n):
    v = N(n)
    return int(math.floor(v)) if type(v) is float else v


@export()
def Round(n, places=0):
    v = float(N(n))
    p = O.RT.to_int(places)
    m = 10.0 ** p
    v = (math.floor(v * m + 0.5) if v >= 0.0 else math.ceil(v * m - 0.5)) / m
    if p > 0:
        return ("%." + str(p) + "f") % v
    return wrap(int(v))


@export()
def Mod(a, b):
    x, y = N(a), N(b)
    if type(x) is int and type(y) is int:
        if y == 0:
            throw("ZeroDivisionError", "Divide by zero.")
        r = abs(x) % abs(y)
        return -r if x < 0 else r
    if float(y) == 0.0:
        throw("ZeroDivisionError", "Divide by zero.")
    return math.fmod(float(x), float(y))


@export()
def Max(*nums):
    if not nums:
        throw("Error", "Too few parameters passed to function.")
    vals = [N(x) for x in nums]
    best = vals[0]
    for v in vals[1:]:
        if v > best:
            best = v
    return best


@export()
def Min(*nums):
    if not nums:
        throw("Error", "Too few parameters passed to function.")
    vals = [N(x) for x in nums]
    best = vals[0]
    for v in vals[1:]:
        if v < best:
            best = v
    return best


@export()
def Sqrt(n):
    v = float(N(n))
    if v < 0:
        throw("ValueError", "Invalid value.", str(n))
    return math.sqrt(v)


@export()
def Exp(n):
    return math.exp(float(N(n)))


@export()
def Log(n):
    v = float(N(n))
    if v <= 0:
        throw("ValueError", "Invalid value.", str(n))
    return math.log10(v)


@export()
def Ln(n):
    v = float(N(n))
    if v <= 0:
        throw("ValueError", "Invalid value.", str(n))
    return math.log(v)


for _name, _fn in (("Sin", math.sin), ("Cos", math.cos), ("Tan", math.tan)):
    export(_name)(_f(_fn))


def _domain(fn, lo, hi):
    def g(x):
        v = float(N(x))
        if v < lo or v > hi:
            throw("ValueError", "Invalid value.", str(x))
        return fn(v)
    return g


export("ASin")(_domain(math.asin, -1, 1))
export("ACos")(_domain(math.acos, -1, 1))
export("ATan")(_f(math.atan))


@export()
def ATan2(y, x):
    return math.atan2(float(N(y)), float(N(x)))


@export()
def Random(a=UNSET, b=UNSET):
    if a is UNSET and b is UNSET:
        return _random.random()
    lo = N(a) if a is not UNSET else 0
    hi = N(b) if b is not UNSET else 0
    if lo > hi:
        lo, hi = hi, lo
    if type(lo) is int and type(hi) is int:
        return _random.randint(lo, hi)
    return _random.uniform(float(lo), float(hi))


@export()
def RandomSeed(n):
    _random.seed(N(n))
    return ""
