"""Loop Parse / Read / Files / Reg (script2.cpp PerformLoopParse, PerformLoopReadFile, PerformLoopFilePattern)."""
from __future__ import annotations

import fnmatch
import os

from .. import objects as O
from ..objects import throw
from ..values import UNSET


def make_iterator(rt, kind, args):
    if kind == "parse":
        return _parse(rt, args)
    if kind == "read":
        return _read(rt, args)
    if kind == "files":
        return _files(rt, args)
    if kind == "reg":
        return _reg(rt, args)
    raise ValueError(kind)


def _arg(args, i, f, default=""):
    if i < len(args) and args[i] is not None:
        return args[i](f)
    return default


def _parse(rt, args):
    def iterate(f, li):
        s = rt.to_str(_arg(args, 0, f))
        delims = rt.to_str(_arg(args, 1, f))
        omit = rt.to_str(_arg(args, 2, f))
        idx = 0
        if delims.lower() == "csv":
            fields = _csv_fields(s)
            for fld in fields:
                idx += 1
                li.index = idx
                li.field = fld.strip(omit) if omit else fld
                yield idx
            return
        if delims == "":
            for ch in s:
                if omit and ch in omit:
                    continue
                idx += 1
                li.index = idx
                li.field = ch
                yield idx
            return
        if s == "":
            return
        start = 0
        n = len(s)
        while True:
            j = start
            while j < n and s[j] not in delims:
                j += 1
            fld = s[start:j]
            if omit:
                fld = fld.strip(omit)
            idx += 1
            li.index = idx
            li.field = fld
            yield idx
            if j >= n:
                return
            start = j + 1
    return iterate


def _csv_fields(s):
    out = []
    i = 0
    n = len(s)
    while True:
        if i < n and s[i] == '"':
            i += 1
            buf = []
            while i < n:
                if s[i] == '"':
                    if i + 1 < n and s[i + 1] == '"':
                        buf.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(s[i])
                i += 1
            j = s.find(",", i)
            buf.append(s[i:j] if j >= 0 else s[i:])
            out.append("".join(buf))
            if j < 0:
                return out
            i = j + 1
        else:
            j = s.find(",", i)
            if j < 0:
                out.append(s[i:])
                return out
            out.append(s[i:j])
            i = j + 1


def _read(rt, args):
    from .files import host_path, decode_file

    def iterate(f, li):
        path = host_path(rt.to_str(_arg(args, 0, f)))
        out = _arg(args, 1, f, None)
        li.out_file = host_path(rt.to_str(out)) if out not in (None, "") else None
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            return
        text = decode_file(data, rt.thread.settings.file_encoding)
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        for idx, line in enumerate(lines, 1):
            if line.endswith("\r"):
                line = line[:-1]
            li.index = idx
            li.read_line = line
            yield idx
    return iterate


class FileInfo:
    __slots__ = ("path", "name", "dir", "is_dir", "pattern_dir", "st")

    def __init__(self, path, name, pattern_dir, is_dir):
        self.path = path
        self.name = name
        self.dir = os.path.dirname(path)
        self.is_dir = is_dir
        self.pattern_dir = pattern_dir
        try:
            self.st = os.stat(path)
        except OSError:
            self.st = None


def _files(rt, args):
    from .files import host_path, ahk_path

    def iterate(f, li):
        pattern = rt.to_str(_arg(args, 0, f))
        mode = rt.to_str(_arg(args, 1, f, "F")).upper() or "F"
        want_files = "F" in mode or ("D" not in mode)
        want_dirs = "D" in mode
        recurse = "R" in mode
        hp = host_path(pattern)
        base_dir, pat = os.path.split(hp)
        if not base_dir:
            base_dir = os.getcwd()
        if pat == "":
            pat = "*"
        orig_dir = os.path.dirname(pattern)
        idx = 0
        pat_l = pat.lower().replace("*.*", "*")

        def walk(d, rel_prefix):
            try:
                entries = sorted(os.listdir(d), key=str.lower)
            except OSError:
                return
            subdirs = []
            for name in entries:
                full = os.path.join(d, name)
                is_dir = os.path.isdir(full)
                if fnmatch.fnmatch(name.lower(), pat_l):
                    if (is_dir and want_dirs) or (not is_dir and want_files):
                        yield FileInfo(full, name, rel_prefix, is_dir)
                if is_dir and recurse and not os.path.islink(full):
                    subdirs.append((full, os.path.join(rel_prefix, name) if rel_prefix else name))
            for full, rel in subdirs:
                yield from walk(full, rel)

        for info in walk(base_dir, ""):
            idx += 1
            li.index = idx
            info.pattern_dir = os.path.join(orig_dir, info.pattern_dir) if info.pattern_dir else orig_dir
            li.file = info
            yield idx
    return iterate


def _reg(rt, args):
    from . import registry

    def iterate(f, li):
        key = rt.to_str(_arg(args, 0, f))
        mode = rt.to_str(_arg(args, 1, f, "V")).upper() or "V"
        idx = 0
        for item in registry.loop_items(key, mode):
            idx += 1
            li.index = idx
            li.reg = item
            yield idx
    return iterate
