"""Source reading for AutoHotkey v2 scripts.

Mirrors Script::GetLine / GetLineContinuation / IsSOLContExpr / BalanceExpr in
script.cpp: physical lines are trimmed, comments removed, continuation sections
folded in, and lines are merged by enclosure or by leading/trailing operators.
The result is a list of logical lines that the tokenizer and parser consume.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import AhkSyntaxError

ESC = "`"
EXPR_CORE = "<>=/|^,?:"
CONT_LINE_SYMBOLS = EXPR_CORE + ".+-*&!~"
LINE_PARENT_WORDS = {"if", "else", "loop", "while", "for", "try", "catch", "finally", "switch"}
CONTROL_WORDS = {"if", "else", "loop", "while", "for", "try", "catch", "finally", "switch", "until",
                 "return", "break", "continue", "goto", "throw", "global", "local", "static", "class", "case", "default"}
WORD_OPERATORS = {"and", "or", "not", "is", "in", "contains", "as"}
HOTSTRING_OPT_CHARS = set("?*- \t")


@dataclass
class LogicalLine:
    text: str
    line: int          # physical line number of the first line
    file: str


def _is_ident_char(c: str) -> bool:
    return c.isalnum() or c == "_" or ord(c) > 0x7F


def _strip_comment(s: str, literal_escapes: bool = False) -> str:
    """Remove a ;comment that is preceded by whitespace (GetLine)."""
    start = 0
    while True:
        i = s.find(";", start)
        if i < 0:
            return s
        if i == 0:
            return ""
        prev = s[i - 1]
        if prev in " \t ":
            return s[:i - 1].rstrip(" \t ")
        if not literal_escapes:
            p = i - 1
            n = 0
            while p >= 0 and s[p] == ESC:
                n += 1
                p -= 1
            if n % 2 == 1:   # `; -> ;  (escaped comment flag)
                s = s[:i - 1] + s[i:]
                start = i
                continue
        start = i + 1


_CONT_OPT_RE = re.compile(r"\S+")


def _find_text_delim(s: str, pos: int, q: str) -> int:
    """Index of the closing quote q at or after pos (honouring ` escapes), or len(s)."""
    i = pos
    while i < len(s):
        c = s[i]
        if c == ESC:
            i += 2
            continue
        if c == q:
            return i
        i += 1
    return len(s)


def balance_expr(s: str, balance: int, expect: list[str]) -> tuple[int, str | None]:
    """Track ([{ nesting outside of quoted strings. Returns (balance, open_quote)."""
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c in "\"'":
            j = _find_text_delim(s, i + 1, c)
            if j >= n:
                return balance, c
            i = j + 1
            continue
        if c in "([{":
            expect.append({"(": ")", "[": "]", "{": "}"}[c])
            balance += 1
        elif c in ")]}":
            if balance <= 0:
                return -1, None
            expect.pop()
            balance -= 1
        i += 1
    return balance, None


def _ends_with_operator(buf: str) -> bool:
    if not buf:
        return False
    c = buf[-1]
    if c == ".":
        return len(buf) > 1 and buf[-2] in " \t"
    if c in CONT_LINE_SYMBOLS + "+-" and not (c in "+-" and len(buf) > 1 and buf[-2] == c):
        return True
    j = len(buf)
    while j > 0 and _is_ident_char(buf[j - 1]):
        j -= 1
    if j > 0 and buf[j - 1] == ".":
        return False
    return buf[j:].lower() in ("or", "and", "is", "not", "in", "contains")


def _first_word(s: str) -> str:
    m = re.match(r"[\w\u0080-￿]+", s)
    return m.group(0).lower() if m else ""


def _colon_matches_ternary(buf: str) -> bool:
    """True if the trailing ':' pairs with an unmatched '?' (so it's a ternary)."""
    depth = 0
    i = 0
    q = 0
    while i < len(buf) - 1:
        c = buf[i]
        if c in "\"'":
            i = _find_text_delim(buf, i + 1, c) + 1
            continue
        if c == "?" and not (i + 1 < len(buf) and buf[i + 1] == "?"):
            q += 1
        elif c == "?" and i + 1 < len(buf) and buf[i + 1] == "?":
            i += 2
            continue
        elif c == ":" and i + 1 < len(buf) and buf[i + 1] == "=":
            i += 2
            continue
        elif c == ":" and q:
            q -= 1
        i += 1
    return q > 0


def is_sol_cont_expr(nxt: str) -> bool:
    """IsSOLContExpr: does this line start with a continuation operator?"""
    if not nxt:
        return False
    c0 = nxt[0].upper()
    if c0 in "AOIC":
        m = re.match(r"([A-Za-z]+)([ \t])", nxt)
        if m and m.group(1).lower() in ("and", "or", "is", "in", "contains", "as"):
            return True
        return False
    if nxt[0] in ":+-" and len(nxt) > 1 and nxt[1] == nxt[0]:
        return False
    if nxt[0] not in CONT_LINE_SYMBOLS:
        return False
    if "::" not in nxt:
        return True
    if nxt[0] == ":":
        i = 1
        while i < len(nxt) and nxt[i] != ":":
            if not (nxt[i].isalnum() or nxt[i] in HOTSTRING_OPT_CHARS):
                break
            i += 1
        if i < len(nxt) and nxt[i] == ":":
            return False      # almost certainly a hotstring
    from .hotkeys import looks_like_hotkey
    if looks_like_hotkey(nxt[:nxt.index("::")]):
        return False
    return True


def _convert_space_escapes(s: str) -> str:
    return s.replace("`s", " ").replace("`t", "\t")


class SourceReader:
    """Produces logical lines from a file's text."""

    def __init__(self, text: str, filename: str):
        if text.startswith("﻿"):
            text = text[1:]
        self.lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.filename = filename
        self.pos = 0          # index of next physical line
        self.in_comment = False

    # -- physical line reading (GetLine) --
    def _raw(self) -> tuple[str | None, int]:
        if self.pos >= len(self.lines):
            return None, self.pos
        s = self.lines[self.pos]
        self.pos += 1
        return s, self.pos

    def _next_code_line(self) -> tuple[str | None, int]:
        """Next non-blank, non-comment line (trimmed, comment stripped), handling /* */."""
        while True:
            raw, ln = self._raw()
            if raw is None:
                return None, ln
            s = raw.strip(" \t")
            if self.in_comment:
                if s.startswith("*/"):
                    self.in_comment = False
                    s = s[2:].lstrip(" \t")
                    s = _strip_comment(s)
                    if not s:
                        continue
                    return s, ln
                if s.endswith("*/"):
                    self.in_comment = False
                continue
            if s.startswith("/*"):
                self.in_comment = True
                if s.endswith("*/") and len(s) >= 4:
                    self.in_comment = False
                continue
            if s.startswith(";"):
                continue
            s = _strip_comment(s)
            if not s:
                continue
            return s, ln

    def _peek_code_line(self):
        save = (self.pos, self.in_comment)
        s, ln = self._next_code_line()
        self.pos, self.in_comment = save
        return s

    def _maybe_continuation_section(self, buf: str, quote_state: list) -> tuple[str, bool]:
        """If the next code line starts a continuation section, fold it into buf."""
        save = (self.pos, self.in_comment)
        nxt, ln = self._next_code_line()
        if nxt is None or not nxt.startswith("(") or nxt[1:2] == ":":
            self.pos, self.in_comment = save
            return buf, False
        # parse options
        join = "\n"
        ltrim = None
        rtrim = True
        comments = False
        literal_escapes = False
        if "(" in nxt[1:] or ")" in nxt[1:]:
            self.pos, self.in_comment = save   # (expr) at line start: not a continuation section
            return buf, False
        for opt in _CONT_OPT_RE.findall(nxt[1:]):
            lo = opt.lower()
            if lo.startswith("join"):
                join = _convert_space_escapes(opt[4:])
            elif lo.startswith("ltrim"):
                ltrim = opt[5:6] != "0"
            elif lo.startswith("rtrim"):
                rtrim = opt[5:6] != "0"
            elif "comments".startswith(lo) and lo:
                comments = True
            elif opt == ESC:
                literal_escapes = True
            elif "(" in opt or ")" in opt:
                self.pos, self.in_comment = save
                return buf, False
            else:
                raise AhkSyntaxError(f'Invalid option. Specifically: {opt}', self.filename, ln)
        # does the section start inside a quoted string?
        qpos, qchar = quote_state
        while True:
            if qchar:
                qpos = _find_text_delim(buf, qpos, qchar)
                if qpos >= len(buf):
                    break
                qpos += 1
            while qpos < len(buf) and buf[qpos] not in "\"'":
                qpos += 1
            if qpos >= len(buf):
                qchar = ""
                break
            qchar = buf[qpos]
            qpos += 1
        quote_state[0], quote_state[1] = qpos, qchar
        literal_quotes = bool(qchar)

        content: list[str] = []
        indent_char = ""
        indent_level = 0
        first = True
        tail = None
        while True:
            raw, ln2 = self._raw()
            if raw is None:
                raise AhkSyntaxError('Missing ")"', self.filename, ln)
            st = raw.lstrip(" \t")
            if comments and st.startswith(";"):
                continue
            if st.startswith(")"):
                tail = _strip_comment(st.rstrip(" \t"))[1:]
                break
            if comments:
                raw = _strip_comment(raw)
            cp = raw
            if ltrim is None:
                if first:
                    indent_char = cp[:1] if cp[:1] in (" ", "\t") else ""
                    indent_level = 0
                    if indent_char:
                        while indent_level < len(cp) and cp[indent_level] == indent_char:
                            indent_level += 1
                if indent_level and cp[:indent_level] == indent_char * indent_level:
                    cp = cp[indent_level:]
            elif ltrim:
                cp = cp.lstrip(" \t")
            if rtrim:
                cp = cp.rstrip(" \t")
            if first and not qchar and buf and _is_ident_char(buf[-1]):
                buf += " "
            if literal_escapes or literal_quotes:
                out = []
                i = 0
                while i < len(cp):
                    ch = cp[i]
                    if ch == ESC:
                        out.append(ESC)
                        if not literal_escapes:
                            i += 1
                            if i >= len(cp):
                                out.append("")
                                break
                            out.append(cp[i])
                            i += 1
                            continue
                    elif ch == qchar and literal_quotes:
                        out.append(ESC)
                    out.append(ch)
                    i += 1
                cp = "".join(out)
            content.append(cp)
            first = False
        buf += join.join(content) + tail
        return buf, True

    def logical_lines(self) -> list[LogicalLine]:
        out: list[LogicalLine] = []
        while True:
            s, ln = self._next_code_line()
            if s is None:
                break
            buf = s
            quote_state = [0, ""]
            while True:
                buf, had = self._maybe_continuation_section(buf, quote_state)
                if not had:
                    break
            if self._is_special_line(buf):
                out.append(LogicalLine(buf, ln, self.filename))
                continue
            buf = self._merge_continuation(buf, ln)
            out.append(LogicalLine(buf, ln, self.filename))
        return out

    @staticmethod
    def _is_special_line(buf: str) -> bool:
        if classify_hot_line(buf) is not None:
            return True
        return buf.startswith("#") and re.match(r"#\w+", buf) is not None

    def _merge_continuation(self, buf: str, ln: int) -> str:
        expect: list[str] = []
        body = re.sub(r"^[{}\s]+", "", buf)
        if buf.startswith("{") and not body:
            return buf
        balance, open_quote = balance_expr(body, 0, expect)
        if open_quote:
            raise AhkSyntaxError(f"Missing {open_quote}", self.filename, ln)
        if balance < 0:
            raise AhkSyntaxError("Unexpected closing bracket", self.filename, ln)
        first_word = _first_word(re.sub(r"^[}\s]+", "", buf))
        while True:
            nxt = self._peek_code_line()
            if balance == 0:
                if nxt is None:
                    return buf
                if buf.endswith(":"):
                    if not _colon_matches_ternary(buf):
                        return buf
                elif _ends_with_operator(buf):
                    if _first_word(nxt) in CONTROL_WORDS:
                        return buf
                elif not is_sol_cont_expr(nxt):
                    return buf
            if balance == 1 and buf.endswith("{") and len(buf) >= 2:
                cp = buf[:-1].rstrip(" \t")
                if cp.endswith(")") or cp.endswith("]") or (first_word in LINE_PARENT_WORDS and not _ends_with_operator(cp)) \
                        or (re.fullmatch(r"(static\s+)?[\w\u0080-\uffff]+", cp, re.I)
                            and cp.lower() not in ("return", "throw", "until", "case", "global", "local", "static")) \
                        or first_word == "class":
                    return buf
            if nxt is None:
                raise AhkSyntaxError(f'Missing "{expect[-1] if expect else ")"}"', self.filename, ln)
            nxt, _ = self._next_code_line()
            balance, open_quote = balance_expr(nxt, balance, expect)
            buf = buf + " " + nxt
            quote_state = [0, ""]
            while True:
                buf, had = self._maybe_continuation_section(buf, quote_state)
                if not had:
                    break
            if open_quote:
                raise AhkSyntaxError(f"Missing {open_quote}", self.filename, ln)
            if balance < 0:
                raise AhkSyntaxError("Unexpected closing bracket", self.filename, ln)


HOTSTRING_RE = re.compile(r"^:([^:]*):(.+?)::(.*)$", re.S)


def classify_hot_line(buf: str):
    """Return ('hotstring', opts, trigger, rest) / ('hotkey', keys, rest) / None."""
    if buf.startswith(":") and not buf.startswith(":="):
        # hotstring: :options:trigger::replacement  (trigger may contain `:: escapes? no - first :: after trigger)
        m = re.match(r"^:([^:]*):", buf)
        if m and all(c.isalnum() or c in HOTSTRING_OPT_CHARS for c in m.group(1)):
            rest = buf[m.end():]
            # trigger ends at the first "::" (a trigger may start with ':' only if escaped as "`:")
            idx = _find_unescaped(rest, "::")
            if idx > 0:
                return ("hotstring", m.group(1), rest[:idx], rest[idx + 2:])
    if "::" in buf:
        from .hotkeys import looks_like_hotkey
        # The hotkey flag is the first "::" (a key like ":" is written as "`:::"? rare)
        idx = buf.find("::")
        if idx == 0:
            return None
        # handle keys that are ':' themselves e.g. "+:::"
        while idx >= 0:
            keys = buf[:idx]
            if looks_like_hotkey(keys):
                return ("hotkey", keys, buf[idx + 2:].lstrip(" \t"))
            idx = buf.find("::", idx + 1)
            if idx > 40:
                break
    return None


def _find_unescaped(s: str, pat: str) -> int:
    i = 0
    while i < len(s):
        if s[i] == ESC:
            i += 2
            continue
        if s.startswith(pat, i):
            return i
        i += 1
    return -1


# ---------------------------------------------------------------- tokenizer

@dataclass
class Tok:
    kind: str      # 'num' 'str' 'id' 'op' 'deref' 'end'
    val: object
    ws: bool       # whitespace precedes this token
    pos: int = 0

    def __repr__(self):
        return f"{self.kind}:{self.val!r}{'_' if self.ws else ''}"


OPERATORS = sorted("""
>>>= <<= >>= //= **= ??= !== >>> := += -= *= /= .= |= &= ^= == != <= >= << >> && || ?? ++ -- => ~= // **
+ - * / . , ( ) [ ] { } ? : ! ~ & | ^ < > = %
""".split(), key=len, reverse=True)

ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "a": "\a", "s": " ",
           "`": "`", '"': '"', "'": "'", ";": ";", ":": ":", "{": "{", "}": "}"}


def unescape(s: str) -> str:
    if ESC not in s:
        return s
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == ESC and i + 1 < len(s):
            nx = s[i + 1]
            out.append(ESCAPES.get(nx, nx))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


NUM_RE = re.compile(r"0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
IDENT_START = re.compile(r"[A-Za-z_\u0080-￿]")


def tokenize(src: str, filename: str = "", line: int = 0) -> list[Tok]:
    toks: list[Tok] = []
    i = 0
    n = len(src)
    ws = False
    while i < n:
        c = src[i]
        if c in " \t\n":
            ws = True
            i += 1
            continue
        start = i
        if c in "\"'":
            j = _find_text_delim(src, i + 1, c)
            if j >= n:
                raise AhkSyntaxError(f"Missing {c}", filename, line)
            toks.append(Tok("str", unescape(src[i + 1:j]), ws, start))
            i = j + 1
            ws = False
            continue
        prev = toks[-1] if toks else None
        after_dot = prev is not None and prev.kind == "op" and prev.val == "." and not ws
        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit() and not (prev and prev.kind in ("id", "num", "str") and not ws) and not after_dot):
            if after_dot:
                m = re.compile(r"\d+").match(src, i)
                toks.append(Tok("id", m.group(0), ws, start))
                i = m.end()
                ws = False
                continue
            m = NUM_RE.match(src, i)
            text = m.group(0)
            end = m.end()
            # "1." followed by identifier char => member access on integer, e.g. 1.Foo (rare); keep simple
            if end < n and _is_ident_char(src[end]) and not text.lower().startswith("0x"):
                # identifiers can start with digits in AHK? (e.g. 1abc is a valid var name) -> treat as id
                m2 = re.compile(r"[\w\u0080-￿]+").match(src, i)
                toks.append(Tok("id", m2.group(0), ws, start))
                i = m2.end()
                ws = False
                continue
            if text.lower().startswith("0x"):
                val = int(text, 16)
                if val >= 1 << 63:
                    val -= 1 << 64 if val < 1 << 64 else val
            elif any(ch in text for ch in ".eE"):
                if text.endswith("."):
                    # "1." alone is a float in AHK
                    pass
                val = float(text)
            else:
                val = int(text)
                if val >= 1 << 63:
                    val = float(text)
            toks.append(Tok("num", (val, text), ws, start))
            i = end
            ws = False
            continue
        if IDENT_START.match(c) or c == "%":
            # identifier possibly with %deref% parts (double-deref)
            parts: list = []
            j = i
            lit = []
            while j < n:
                ch = src[j]
                if _is_ident_char(ch):
                    lit.append(ch)
                    j += 1
                elif ch == "%":
                    k = src.find("%", j + 1)
                    if k < 0:
                        raise AhkSyntaxError('Missing "%"', filename, line)
                    if lit:
                        parts.append("".join(lit))
                        lit = []
                    parts.append(tokenize(src[j + 1:k], filename, line))
                    j = k + 1
                else:
                    break
            if lit:
                parts.append("".join(lit))
            if len(parts) == 1 and isinstance(parts[0], str):
                toks.append(Tok("id", parts[0], ws, start))
            else:
                toks.append(Tok("deref", parts, ws, start))
            i = j
            ws = False
            continue
        for op in OPERATORS:
            if src.startswith(op, i):
                toks.append(Tok("op", op, ws, start))
                i += len(op)
                break
        else:
            raise AhkSyntaxError(f'Unexpected character "{c}"', filename, line)
        ws = False
    toks.append(Tok("end", None, ws, n))
    return toks
