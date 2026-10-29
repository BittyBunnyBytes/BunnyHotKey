"""Date/time built-ins: FormatTime, DateAdd, DateDiff (lib/vars.cpp, util.cpp YYYYMMDD helpers)."""
from __future__ import annotations

import calendar
import datetime as dt
import re
import time

from .. import objects as O
from ..objects import throw
from ..values import UNSET
from . import export


def S(v):
    return O.RT.to_str(v)


def parse_timestamp(s: str) -> dt.datetime:
    s = s.strip()
    if not s:
        return dt.datetime.now()
    if not s.isdigit() or len(s) > 14 or len(s) < 4:
        raise ValueError(s)
    s = s.ljust(14, "0")
    y, mo, d = int(s[0:4]), int(s[4:6]) or 1, int(s[6:8]) or 1
    if len(s.rstrip("0")) <= 4:
        pass
    return dt.datetime(y, mo if mo else 1, d if d else 1, int(s[8:10]), int(s[10:12]), int(s[12:14]))


def _ts(v) -> dt.datetime:
    try:
        raw = S(v)
        if len(raw) in (4, 6):
            raw = raw + ("0101" if len(raw) == 4 else "01")
        return parse_timestamp(raw)
    except ValueError:
        throw("ValueError", "Invalid value.", S(v))


def stamp(d: dt.datetime) -> str:
    return d.strftime("%Y%m%d%H%M%S")


@export()
def DateAdd(datetime_, time_, units):
    d = _ts(datetime_)
    n = O.RT.to_num(time_)
    u = S(units).lower()[:1]
    sec = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(u)
    if sec is None:
        throw("ValueError", "Invalid value.", S(units))
    return stamp(d + dt.timedelta(seconds=n * sec))


@export()
def DateDiff(a, b, units):
    d1 = _ts(a)
    d2 = _ts(b)
    u = S(units).lower()[:1]
    delta = (d1 - d2).total_seconds()
    if u == "s":
        return int(delta)
    if u == "m":
        return int(delta // 60) if delta >= 0 else -int(-delta // 60)
    if u == "h":
        return int(delta / 3600)
    if u == "d":
        return (d1.date() - d2.date()).days
    throw("ValueError", "Invalid value.", S(units))


_LONG_DATE = "dddd, MMMM d, yyyy"
_SHORT_DATE = "M/d/yyyy"
_TIME = "h:mm tt"


def format_time(d: dt.datetime, fmt: str) -> str:
    if fmt == "":
        return format_time(d, _TIME + " dddd, MMMM d, yyyy")
    low = fmt.lower()
    if low == "shortdate":
        return format_time(d, _SHORT_DATE)
    if low == "longdate":
        return format_time(d, _LONG_DATE)
    if low == "time":
        return format_time(d, _TIME)
    if low == "yearmonth":
        return format_time(d, "MMMM yyyy")
    if low == "yday":
        return str(d.timetuple().tm_yday)
    if low == "yday0":
        return "%03d" % d.timetuple().tm_yday
    if low == "wday":
        return str((d.weekday() + 1) % 7 + 1)
    if low == "yweek":
        y, w, _ = d.isocalendar()
        return "%04d%02d" % (y, w)
    out = []
    i = 0
    tokens = [("dddd", lambda: d.strftime("%A")), ("ddd", lambda: d.strftime("%a")), ("dd", lambda: "%02d" % d.day),
              ("d", lambda: str(d.day)), ("MMMM", lambda: d.strftime("%B")), ("MMM", lambda: d.strftime("%b")),
              ("MM", lambda: "%02d" % d.month), ("M", lambda: str(d.month)), ("yyyy", lambda: "%04d" % d.year),
              ("yy", lambda: "%02d" % (d.year % 100)), ("y", lambda: str(d.year % 100)), ("gg", lambda: "A.D."),
              ("hh", lambda: "%02d" % ((d.hour % 12) or 12)), ("h", lambda: str((d.hour % 12) or 12)),
              ("HH", lambda: "%02d" % d.hour), ("H", lambda: str(d.hour)), ("mm", lambda: "%02d" % d.minute),
              ("m", lambda: str(d.minute)), ("ss", lambda: "%02d" % d.second), ("s", lambda: str(d.second)),
              ("tt", lambda: "AM" if d.hour < 12 else "PM"), ("t", lambda: "A" if d.hour < 12 else "P")]
    while i < len(fmt):
        if fmt[i] == "'":
            j = fmt.find("'", i + 1)
            if j < 0:
                out.append(fmt[i + 1:])
                break
            out.append(fmt[i + 1:j] if j > i + 1 else "'")
            i = j + 1
            continue
        for tok, fn in tokens:
            if fmt.startswith(tok, i):
                out.append(fn())
                i += len(tok)
                break
        else:
            out.append(fmt[i])
            i += 1
    return "".join(out)


@export()
def FormatTime(yyyymmdd=UNSET, fmt=""):
    if yyyymmdd is UNSET or S(yyyymmdd).strip() == "":
        d = dt.datetime.now()
    else:
        raw = S(yyyymmdd).split()[0] if S(yyyymmdd).split() else ""
        try:
            d = parse_timestamp(raw.ljust(4, "0") if raw else "")
        except ValueError:
            d = dt.datetime.now()
    return format_time(d, S(fmt))


def a_now(utc=False):
    d = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) if utc else dt.datetime.now()
    return stamp(d)
