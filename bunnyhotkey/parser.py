"""Parser: logical lines -> AST.

Precedences follow sPrecedence[] in Line::ExpressionToPostfix (script.cpp);
odd values are right-associative there and here.
"""
from __future__ import annotations

import re

from . import ast as A
from .errors import AhkSyntaxError
from .lexer import LogicalLine, Tok, classify_hot_line, tokenize

ASSIGN_OPS = {":=", "+=", "-=", "*=", "/=", "//=", ".=", "|=", "&=", "^=", ">>=", "<<=", ">>>=", "??="}
BINARY = {
    "||": (17, True), "&&": (21, True), "??": (15, True),
    "=": (30, False), "==": (30, False), "!=": (30, False), "!==": (30, False),
    "<": (34, False), ">": (34, False), "<=": (34, False), ">=": (34, False),
    "~=": (36, False),
    "|": (42, False), "^": (46, False), "&": (50, False),
    "<<": (54, False), ">>": (54, False), ">>>": (54, False),
    "+": (58, False), "-": (58, False),
    "*": (62, False), "/": (62, False), "//": (62, False),
    "**": (73, True),
}
WORD_BINARY = {"and": ("&&", 21, True), "or": ("||", 17, True), "is": ("is", 28, False)}
CONCAT_BP = 38
KEYWORDS = {"if", "else", "while", "loop", "for", "try", "catch", "finally", "throw", "return", "break",
            "continue", "goto", "switch", "case", "default", "global", "local", "static", "class", "until"}
END_STMT_OPS = {")", "]", "}", ":"}


class Parser:
    def __init__(self, lines: list[LogicalLine] | None, filename: str = "", toks: list[Tok] | None = None):
        self.filename = filename
        if toks is not None:
            self.toks = toks
        else:
            self.toks = self._build_stream(lines or [])
        self.i = 0

    # ------------------------------------------------------------ token stream
    def _build_stream(self, lines: list[LogicalLine]) -> list[Tok]:
        out: list[Tok] = []
        for ll in lines:
            text = ll.text
            cls = None
            if text.startswith("#") and not text.lower().startswith("#hotif ") and ":: " not in text[:2]:
                m = re.match(r"#(\w+)(.*)$", text, re.S)
                hk = classify_hot_line(text)
                if m and not hk:
                    name = m.group(1)
                    args = m.group(2).strip(" \t")
                    if args.startswith(","):
                        args = args[1:].strip(" \t")
                    t = Tok("directive", (name, args), False)
                    self._stamp(t, ll)
                    out.append(t)
                    if name.lower() in ("hotif",):
                        sub = tokenize(args, ll.file, ll.line) if args else [Tok("end", None, False)]
                        for st in sub[:-1]:
                            self._stamp(st, ll)
                            out.append(st)
                    out.append(self._nl(ll))
                    continue
            if text.lower().startswith("#hotif") and (len(text) == 6 or text[6] in " \t"):
                args = text[6:].strip()
                t = Tok("directive", ("HotIf", args), False)
                self._stamp(t, ll)
                out.append(t)
                if args:
                    for st in tokenize(args, ll.file, ll.line)[:-1]:
                        self._stamp(st, ll)
                        out.append(st)
                out.append(self._nl(ll))
                continue
            cls = classify_hot_line(text)
            if cls and cls[0] == "hotstring":
                _, opts, trig, rest = cls
                t = Tok("hotstring", (opts, trig, rest), False)
                self._stamp(t, ll)
                out.append(t)
                if "x" in opts.lower().replace("*0", "").replace("?0", "") and rest.strip():
                    for st in tokenize(rest, ll.file, ll.line)[:-1]:
                        self._stamp(st, ll)
                        out.append(st)
                out.append(self._nl(ll))
                continue
            if cls and cls[0] == "hotkey":
                _, keys, rest = cls
                t = Tok("hotkey", (keys, rest), False)
                self._stamp(t, ll)
                out.append(t)
                from .keys import lookup
                if rest and not _is_remap(rest):
                    for st in tokenize(rest, ll.file, ll.line)[:-1]:
                        self._stamp(st, ll)
                        out.append(st)
                out.append(self._nl(ll))
                continue
            for st in tokenize(text, ll.file, ll.line)[:-1]:
                self._stamp(st, ll)
                out.append(st)
            out.append(self._nl(ll))
        end = Tok("end", None, False)
        end.line = lines[-1].line if lines else 0
        end.file = self.filename
        out.append(end)
        return out

    @staticmethod
    def _stamp(t: Tok, ll: LogicalLine):
        t.line = ll.line
        t.file = ll.file
        if t.kind == "deref":
            for p in t.val:
                if isinstance(p, list):
                    for s in p:
                        Parser._stamp(s, ll)

    @staticmethod
    def _nl(ll: LogicalLine) -> Tok:
        t = Tok("nl", None, False)
        t.line = ll.line
        t.file = ll.file
        return t

    # ------------------------------------------------------------ helpers
    def peek(self, k=0) -> Tok:
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else self.toks[-1]

    def next(self) -> Tok:
        t = self.toks[self.i]
        if self.i < len(self.toks) - 1:
            self.i += 1
        return t

    def is_op(self, v, k=0) -> bool:
        t = self.peek(k)
        return t.kind == "op" and t.val == v

    def is_word(self, w, k=0) -> bool:
        t = self.peek(k)
        return t.kind == "id" and t.val.lower() == w

    def expect_op(self, v):
        t = self.peek()
        if not (t.kind == "op" and t.val == v):
            self.error(f'Missing "{v}"', t)
        return self.next()

    def error(self, msg, t: Tok | None = None):
        t = t or self.peek()
        raise AhkSyntaxError(msg, getattr(t, "file", self.filename), getattr(t, "line", 0),
                             "" if t.val is None else str(t.val if not isinstance(t.val, tuple) else t.val[-1]))

    def at_eol(self, k=0) -> bool:
        return self.peek(k).kind in ("nl", "end")

    def skip_nl(self):
        while self.peek().kind == "nl":
            self.next()

    def L(self, t: Tok | None = None) -> dict:
        t = t or self.peek()
        return {"line": getattr(t, "line", 0), "file": getattr(t, "file", self.filename)}

    def brace_is_block(self, k=0) -> bool:
        """A '{' at the end of a line (OTB) or at statement start is a block."""
        return self.is_op("{", k) and self.peek(k + 1).kind in ("nl", "end")

    # ------------------------------------------------------------ program
    def parse_program(self) -> list[A.Node]:
        stmts = []
        while True:
            self.skip_nl()
            if self.peek().kind == "end":
                break
            if self.is_op("}"):
                self.error('Unexpected "}"')
            stmts.append(self.parse_statement(top=True))
        return stmts

    def parse_block(self) -> A.Block:
        t = self.expect_op("{")
        body = []
        while True:
            self.skip_nl()
            if self.is_op("}"):
                self.next()
                break
            if self.peek().kind == "end":
                self.error('Missing "}"', t)
            body.append(self.parse_statement())
        return A.Block(body, **self.L(t))

    def parse_body(self) -> A.Node:
        """Body of if/loop/etc: OTB block, block on next line, or single statement."""
        if self.is_op("{"):
            return self.parse_block()
        self.skip_nl()
        if self.is_op("{"):
            return self.parse_block()
        if self.peek().kind == "end":
            self.error("Missing statement")
        return self.parse_statement()

    def _peek_after_nl(self, word) -> bool:
        j = 0
        while self.peek(j).kind == "nl":
            j += 1
        return self.is_word(word, j)

    def _consume_to(self, word) -> bool:
        if self._peek_after_nl(word):
            self.skip_nl()
            return True
        return False

    # ------------------------------------------------------------ statements
    def parse_statement(self, top=False, in_class=False) -> A.Node:
        t = self.peek()
        loc = self.L(t)
        if t.kind == "op" and t.val == "{":
            return self.parse_block()
        if t.kind == "directive":
            return self.parse_directive()
        if t.kind == "hotkey":
            return self.parse_hotkey()
        if t.kind == "hotstring":
            return self.parse_hotstring()
        if t.kind == "id":
            w = t.val.lower()
            nxt = self.peek(1)
            # label
            if nxt.kind == "op" and nxt.val == ":" and not nxt.ws and self.at_eol(2) and w not in ("default",):
                self.next(); self.next()
                return A.Label(t.val, **loc)
            if w in KEYWORDS and not (nxt.kind == "op" and (nxt.val in ASSIGN_OPS or (nxt.val in ("(", "[", ".") and not nxt.ws)) and w not in ("if", "while", "loop", "for", "switch", "return", "throw", "try", "global", "local", "static")):
                return getattr(self, "st_" + w)()
            if w in ("if", "while", "for", "switch", "return", "throw", "try", "global", "local", "static", "loop") \
                    and not (nxt.kind == "op" and nxt.val in ASSIGN_OPS):
                return getattr(self, "st_" + w)()
            # function definition: Name(params) { / =>
            if nxt.kind == "op" and nxt.val == "(" and not nxt.ws:
                fd = self.try_funcdef(is_method=in_class)
                if fd is not None:
                    return fd
        expr_stmt = self.parse_expr_statement()
        return expr_stmt

    def try_funcdef(self, is_static=False, is_method=False):
        save = self.i
        name_t = self.next()
        j = self._match_paren(self.i)
        if j is None:
            self.i = save
            return None
        after = self.toks[j + 1] if j + 1 < len(self.toks) else self.toks[-1]
        k = j + 1
        is_arrow = after.kind == "op" and after.val == "=>"
        is_block = after.kind == "op" and after.val == "{"
        if not (is_arrow or is_block):
            # block on the next line
            kk = k
            while self.toks[kk].kind == "nl":
                kk += 1
            if kk != k and self.toks[kk].kind == "op" and self.toks[kk].val == "{":
                is_block = True
            else:
                self.i = save
                return None
        params = self.parse_params(")")
        return self._finish_func(name_t, params, is_static, is_method)

    def _finish_func(self, name_t, params, is_static, is_method, kind="method"):
        loc = self.L(name_t)
        if self.is_op("=>"):
            self.next()
            e = self.parse_expr(6)
            body = A.Block([A.Return(e, **loc)], **loc)
            return A.FuncDef(name_t.val, params, body, is_static, True, is_method, kind, **loc)
        self.skip_nl()
        body = self.parse_block()
        return A.FuncDef(name_t.val, params, body, is_static, False, is_method, kind, **loc)

    def _match_paren(self, j):
        """Given index of '(' or '[', return index of its matching close."""
        open_t = self.toks[j]
        if open_t.kind != "op" or open_t.val not in ("(", "["):
            return None
        depth = 0
        while j < len(self.toks):
            t = self.toks[j]
            if t.kind == "op" and t.val in ("(", "[", "{"):
                depth += 1
            elif t.kind == "op" and t.val in (")", "]", "}"):
                depth -= 1
                if depth == 0:
                    return j
            elif t.kind in ("nl", "end"):
                return None
            j += 1
        return None

    def parse_params(self, close) -> list[A.Param]:
        self.next()  # ( or [
        params = []
        while not self.is_op(close):
            t = self.peek()
            if t.kind == "op" and t.val == "*":
                self.next()
                params.append(A.Param("", False, None, True, True, **self.L(t)))
            else:
                byref = False
                if self.is_op("&"):
                    self.next()
                    byref = True
                nt = self.next()
                if nt.kind != "id":
                    self.error("Invalid parameter", nt)
                p = A.Param(nt.val, byref, None, False, False, **self.L(nt))
                if self.is_op("*"):
                    self.next()
                    p.variadic = True
                elif self.is_op(":=") or self.is_op("="):
                    self.next()
                    p.default = self.parse_expr(6)
                    p.optional = True
                elif self.is_op("?"):
                    self.next()
                    p.optional = True
                params.append(p)
            if self.is_op(","):
                self.next()
            elif not self.is_op(close):
                self.error(f'Missing "{close}"')
        self.next()
        return params

    def parse_expr_statement(self) -> A.Node:
        t = self.peek()
        loc = self.L(t)
        if t.kind == "id" and t.val.lower() not in WORD_BINARY and t.val.lower() != "not":
            # command-style call: Name args / obj.Method args
            j = 1
            while self.is_op(".", j) and not self.peek(j).ws and self.peek(j + 1).kind == "id" and not self.peek(j + 1).ws:
                j += 2
            nt = self.peek(j)
            if self._starts_command_args(nt, j):
                chain = [self.next().val]
                while len(chain) * 2 - 1 < j:
                    self.next()
                    chain.append(self.next().val)
                args, variadic = self.parse_command_args()
                if len(chain) == 1:
                    return A.ExprStmt(A.Call(A.Var(chain[0], **loc), args, variadic, **loc), **loc)
                obj = A.Var(chain[0], **loc)
                for name in chain[1:-1]:
                    obj = A.Member(obj, name, None, **loc)
                return A.ExprStmt(A.MethodCall(obj, chain[-1], None, args, variadic, **loc), **loc)
        e = self.parse_expr(0)
        if not (self.at_eol() or self.is_op("}")):
            self.error("Unexpected token")
        return A.ExprStmt(e, **loc)

    def _starts_command_args(self, nt: Tok, j: int) -> bool:
        if nt.kind in ("nl", "end"):
            return True
        if nt.kind == "op" and nt.val == "}":
            return True
        if nt.kind == "op" and nt.val == ",":
            return True
        if not nt.ws:
            return False
        if nt.kind in ("num", "str", "deref"):
            return True
        if nt.kind == "id":
            return nt.val.lower() not in ("and", "or", "is", "in", "contains", "as")
        if nt.kind == "op":
            v = nt.val
            if v in ASSIGN_OPS or v in ("=>", "?", "??", ":", ".", "||", "&&", "=", "==", "!=", "!==", "<", ">",
                                        "<=", ">=", "~=", "//", "**", "|", "^", "<<", ">>", ">>>", "/", "++", "--"):
                return False
            if v in ("(", "[", "{"):
                return True
            if v in ("-", "+", "*", "&", "!", "~"):
                after = self.peek(j + 1)
                return not after.ws and after.kind not in ("nl", "end")
            if v == "%":
                return True
        return False

    def parse_command_args(self):
        args = []
        variadic = False
        if self.at_eol() or self.is_op("}"):
            return args, variadic
        while True:
            if self.is_op(","):
                args.append(None)
                self.next()
                continue
            if self.at_eol() or self.is_op("}"):
                args.append(None)
                break
            e = self.parse_expr(6)
            if self.is_op("*") and (self.at_eol(1) or self.is_op("}", 1)):
                self.next()
                variadic = True
            args.append(e)
            if self.is_op(","):
                self.next()
                if self.at_eol():
                    args.append(None)
                    break
                continue
            break
        while args and args[-1] is None:
            args.pop()
        if not (self.at_eol() or self.is_op("}")):
            self.error("Unexpected token in argument list")
        return args, variadic

    # control flow
    def st_if(self):
        t = self.next()
        cond = self.parse_expr(0)
        then = self.parse_body()
        orelse = None
        if self._consume_to("else"):
            self.next()
            orelse = self.parse_body()
        return A.If(cond, then, orelse, **self.L(t))

    def st_else(self):
        self.error('ELSE with no matching IF')

    def st_until(self):
        self.error('UNTIL with no matching loop')

    def _until(self):
        if self._consume_to("until"):
            self.next()
            return self.parse_expr(0)
        return None

    def st_while(self):
        t = self.next()
        cond = self.parse_expr(0)
        body = self.parse_body()
        node = A.While(cond, body, self._until(), None, **self.L(t))
        node.orelse = self._loop_else()
        return node

    def st_loop(self):
        t = self.next()
        loc = self.L(t)
        kind = "count"
        args = []
        nt = self.peek()
        if nt.kind == "id" and nt.val.lower() in ("parse", "read", "files", "reg") and (
                self.peek(1).ws or self.is_op(",", 1)) and not (self.peek(1).kind == "op" and self.peek(1).val in ASSIGN_OPS):
            kind = nt.val.lower()
            self.next()
            if self.is_op(","):
                self.next()
            while not self.at_eol() and not self.brace_is_block():
                if self.is_op(","):
                    self.next()
                    args.append(None)
                    continue
                args.append(self.parse_expr(6))
                if self.is_op(","):
                    self.next()
                else:
                    break
        else:
            if not self.at_eol() and not self.brace_is_block():
                args.append(self.parse_expr(0))
        body = self.parse_body()
        node = A.Loop(kind, args, body, self._until(), None, **loc)
        node.orelse = self._loop_else()
        return node

    def st_for(self):
        t = self.next()
        paren = False
        if self.is_op("("):
            # for (a, b in x)
            paren = True
            self.next()
        names = []
        while True:
            if self.is_op(","):
                names.append(None)
                self.next()
                continue
            nt = self.next()
            if nt.kind != "id":
                self.error("Invalid for-loop variable", nt)
            if nt.val.lower() == "in":
                break
            names.append(nt.val)
            if self.is_op(","):
                self.next()
            elif self.is_word("in"):
                self.next()
                break
            else:
                self.error('Missing "in"')
        it = self.parse_expr(6)
        if paren:
            self.expect_op(")")
        body = self.parse_body()
        node = A.For(names, it, body, self._until(), None, **self.L(t))
        node.orelse = self._loop_else()
        return node

    def _loop_else(self):
        """v2: Loop/For/While ... Else runs the else body if the loop had zero iterations."""
        if self._consume_to("else"):
            self.next()
            return self.parse_body()
        return None

    def st_try(self):
        t = self.next()
        body = self._try_part_body()
        catches = []
        orelse = final = None
        while True:
            if self._consume_to("catch"):
                ct = self.next()
                classes = []
                var = None
                while not self.at_eol() and not self.is_op("{"):
                    if self.is_word("as"):
                        self.next()
                        var = self.next().val
                        break
                    e = self.parse_expr(6)
                    classes.append(e)
                    if self.is_op(","):
                        self.next()
                if len(classes) == 1 and var is None and isinstance(classes[0], A.Var) and not self.is_op("{") and False:
                    pass
                cbody = self._try_part_body()
                catches.append((classes, var, cbody))
                continue
            if self._consume_to("else"):
                self.next()
                orelse = self._try_part_body()
                continue
            if self._consume_to("finally"):
                self.next()
                final = self._try_part_body()
            break
        return A.Try(body, catches, orelse, final, **self.L(t))

    def _try_part_body(self):
        if self.is_op("{"):
            return self.parse_block()
        if not self.at_eol():
            return self.parse_statement()
        return self.parse_body()

    def st_catch(self):
        self.error("CATCH with no matching TRY")

    def st_finally(self):
        self.error("FINALLY with no matching TRY")

    def st_throw(self):
        t = self.next()
        e = None if self.at_eol() or self.is_op("}") else self.parse_expr(0)
        return A.Throw(e, **self.L(t))

    def st_return(self):
        t = self.next()
        e = None if self.at_eol() or self.is_op("}") else self.parse_expr(0)
        return A.Return(e, **self.L(t))

    def st_break(self):
        t = self.next()
        label = None
        if not self.at_eol() and not self.is_op("}"):
            lt = self.next()
            label = str(lt.val if lt.kind != "num" else lt.val[1])
        return A.Break(label, **self.L(t))

    def st_continue(self):
        t = self.next()
        label = None
        if not self.at_eol() and not self.is_op("}"):
            lt = self.next()
            label = str(lt.val if lt.kind != "num" else lt.val[1])
        return A.Continue(label, **self.L(t))

    def st_goto(self):
        t = self.next()
        if self.is_op("(") and not self.peek().ws:
            self.next()
            e = self.parse_expr(0)
            self.expect_op(")")
            return A.Goto(e, **self.L(t))
        lt = self.next()
        return A.Goto(lt.val if lt.kind == "id" else A.Str(lt.val), **self.L(t))

    def st_switch(self):
        t = self.next()
        subject = None
        casesense = None
        if not self.is_op("{"):
            if not self.at_eol():
                subject = self.parse_expr(6)
                if self.is_op(","):
                    self.next()
                    casesense = self.parse_expr(6)
        self.skip_nl()
        bt = self.expect_op("{")
        cases = []
        default = None
        while True:
            self.skip_nl()
            if self.is_op("}"):
                self.next()
                break
            if self.is_word("case"):
                self.next()
                exprs = [self.parse_expr(6)]
                while self.is_op(","):
                    self.next()
                    exprs.append(self.parse_expr(6))
                self.expect_op(":")
                body = self._case_body()
                cases.append((exprs, body))
            elif self.is_word("default"):
                self.next()
                self.expect_op(":")
                default = self._case_body()
            else:
                self.error("Expected case or default")
        return A.Switch(subject, casesense, cases, default, **self.L(t))

    def _case_body(self):
        stmts = []
        while True:
            if self.peek().kind == "nl":
                self.skip_nl()
            if self.is_op("}") or self.is_word("case") or self.is_word("default") and self.is_op(":", 1) \
                    or self.peek().kind == "end":
                break
            stmts.append(self.parse_statement())
        return A.Block(stmts)

    def st_case(self):
        self.error("Case without Switch")

    def st_default(self):
        return self.parse_expr_statement()

    def st_global(self):
        return self._decl("global")

    def st_local(self):
        return self._decl("local")

    def st_static(self):
        t = self.peek()
        nt = self.peek(1)
        if nt.kind == "id" and self.is_op("(", 2) and not self.peek(2).ws:
            self.next()
            fd = self.try_funcdef(is_static=True)
            if fd:
                return fd
        return self._decl("static")

    def _decl(self, kind):
        t = self.next()
        items = []
        while not self.at_eol() and not self.is_op("}"):
            nt = self.next()
            if nt.kind != "id":
                self.error("Invalid declaration", nt)
            init = None
            if self.is_op(":="):
                self.next()
                init = self.parse_expr(6)
            elif self.peek().kind == "op" and self.peek().val in ASSIGN_OPS:
                op_t = self.next()
                rhs = self.parse_expr(6)
                init = ("compound", A.Assign(op_t.val, A.Var(nt.val, **self.L(nt)), rhs, **self.L(op_t)))
            items.append((nt.val, init))
            if self.is_op(","):
                self.next()
            else:
                break
        return A.Decl(kind, items, **self.L(t))

    def st_class(self):
        t = self.next()
        nt = self.next()
        if nt.kind != "id":
            self.error("Invalid class name", nt)
        extends = None
        if self.is_word("extends"):
            self.next()
            parts = [self.next().val]
            while self.is_op("."):
                self.next()
                parts.append(self.next().val)
            extends = parts
        self.skip_nl()
        self.expect_op("{")
        members = []
        while True:
            self.skip_nl()
            if self.is_op("}"):
                self.next()
                break
            if self.peek().kind == "end":
                self.error('Missing "}"', t)
            members.extend(self.parse_class_member())
        return A.ClassDef(nt.val, extends, members, **self.L(t))

    def parse_class_member(self) -> list:
        if self.peek().kind == "directive":
            self.parse_directive()
            return []
        is_static = False
        if self.is_word("static") and self.peek(1).kind == "id":
            self.next()
            is_static = True
        t = self.peek()
        loc = self.L(t)
        if self.is_word("class") and self.peek(1).kind == "id":
            cd = self.st_class()
            cd.is_static = True
            return [cd]
        if t.kind != "id":
            self.error("Invalid class member")
        nt = self.peek(1)
        if nt.kind == "op" and nt.val == "(" and not nt.ws:
            fd = self.try_funcdef(is_static=is_static, is_method=True)
            if fd is None:
                self.error("Invalid method definition")
            return [fd]
        if nt.kind == "op" and nt.val == "[" and not nt.ws:
            self.next()
            params = self.parse_params("]")
            return [self._prop_body(t, params, is_static)]
        if nt.kind == "op" and nt.val == "=>":
            self.next()
            self.next()
            e = self.parse_expr(6)
            g = A.FuncDef("get", [], A.Block([A.Return(e, **loc)], **loc), is_static, True, True, "get", **loc)
            return [A.PropDef(t.val, [], g, None, is_static, **loc)]
        if nt.kind == "op" and nt.val == "{" or (nt.kind == "nl" and self._next_line_brace(1)):
            return [self._prop_body(self.next() and t, [], is_static)]
        # class variables: a := 1, b := 2
        out = []
        while True:
            nt = self.next()
            if nt.kind != "id":
                self.error("Invalid class variable", nt)
            name = nt.val
            while self.is_op(".") and not self.peek().ws:
                self.next()
                name += "." + self.next().val
            val = None
            if self.is_op(":="):
                self.next()
                val = self.parse_expr(6)
            out.append(A.ClassVar(name, val, is_static, **self.L(nt)))
            if self.is_op(","):
                self.next()
                continue
            break
        if not self.at_eol():
            self.error("Unexpected token in class body")
        return out

    def _next_line_brace(self, k):
        j = k
        while self.peek(j).kind == "nl":
            j += 1
        return self.is_op("{", j) and j != k

    def _prop_body(self, name_t, params, is_static):
        loc = self.L(name_t)
        if self.is_op("=>"):
            self.next()
            e = self.parse_expr(6)
            g = A.FuncDef("get", params, A.Block([A.Return(e, **loc)], **loc), is_static, True, True, "get", **loc)
            return A.PropDef(name_t.val, params, g, None, is_static, **loc)
        self.skip_nl()
        self.expect_op("{")
        getter = setter = None
        while True:
            self.skip_nl()
            if self.is_op("}"):
                self.next()
                break
            w = self.next()
            if w.kind != "id" or w.val.lower() not in ("get", "set"):
                self.error("Expected get or set", w)
            wl = w.val.lower()
            fparams = list(params)
            if wl == "set":
                fparams = [A.Param("value", False, None, False, False, **loc)] + fparams
            if self.is_op("=>"):
                self.next()
                e = self.parse_expr(6)
                body = A.Block([A.Return(e, **loc)], **loc)
            else:
                self.skip_nl()
                body = self.parse_block()
            fd = A.FuncDef(wl, fparams, body, is_static, False, True, wl, **self.L(w))
            if wl == "get":
                getter = fd
            else:
                setter = fd
        return A.PropDef(name_t.val, params, getter, setter, is_static, **loc)

    # directives / hotkeys
    def parse_directive(self):
        t = self.next()
        name, args = t.val
        expr = None
        if name.lower() == "hotif":
            if not self.at_eol():
                expr = self.parse_expr(0)
        if not self.at_eol():
            self.error("Unexpected token after directive")
        return A.Directive(name, args, expr, **self.L(t))

    def _hot_body(self, t, rest_has_tokens: bool):
        """Body for hotkey/hotstring: same-line statement, OTB block, or next-line block."""
        if rest_has_tokens:
            if self.brace_is_block():
                return self.parse_block()
            st = self.parse_statement()
            return A.Block([st], **self.L(t))
        self.skip_nl()
        if self.is_op("{"):
            return self.parse_block()
        return None

    def parse_hotkey(self):
        t = self.next()
        keys, rest = t.val
        loc = self.L(t)
        if rest and _is_remap(rest):
            return A.HotkeyDef([keys], None, rest.strip(), None, **loc)
        stack = [keys]
        if not rest:
            # stacked hotkeys/hotstrings share the next body
            while True:
                self.skip_nl()
                nt = self.peek()
                if nt.kind == "hotkey" and not nt.val[1]:
                    stack.append(nt.val[0])
                    self.next()
                    continue
                if nt.kind == "hotkey" and nt.val[1]:
                    # the next hotkey's same-line action applies to all stacked keys
                    self.next()
                    stack.append(nt.val[0])
                    if _is_remap(nt.val[1]):
                        return A.HotkeyDef(stack, None, nt.val[1].strip(), None, **loc)
                    body = self._hot_body(nt, True)
                    return A.HotkeyDef(stack, body, None, None, **loc)
                break
            body = self._hot_body(t, False)
            if body is None:
                self.error("Hotkey or hotstring is missing its opening brace", t)
            return A.HotkeyDef(stack, body, None, None, **loc)
        body = self._hot_body(t, True)
        return A.HotkeyDef(stack, body, None, None, **loc)

    def parse_hotstring(self):
        t = self.next()
        opts, trig, rest = t.val
        loc = self.L(t)
        execute = "x" in opts.lower()
        if execute:
            if rest.strip():
                body = self._hot_body(t, True)
                return A.HotstringDef(opts, trig, None, body, None, **loc)
        if rest:
            return A.HotstringDef(opts, trig, rest, None, None, **loc)
        self.skip_nl()
        if self.is_op("{"):
            body = self.parse_block()
            return A.HotstringDef(opts, trig, None, body, None, **loc)
        nt = self.peek()
        if nt.kind in ("hotstring", "hotkey"):
            # stacked: shares the next definition's action
            nxt = self.parse_statement()
            if isinstance(nxt, A.HotstringDef):
                h = A.HotstringDef(opts, trig, nxt.replacement, nxt.body, None, **loc)
                return A.Block([h, nxt])
            if isinstance(nxt, A.HotkeyDef):
                h = A.HotstringDef(opts, trig, None, nxt.body, None, **loc)
                return A.Block([h, nxt])
        return A.HotstringDef(opts, trig, "", None, None, **loc)

    # ------------------------------------------------------------ expressions
    def parse_expr(self, rbp=0) -> A.Node:
        left = self.parse_prefix()
        while True:
            t = self.peek()
            info = self.infix_bp(t)
            if info is None:
                break
            bp, right_assoc, kind = info
            if bp <= rbp:
                break
            left = self.parse_infix(left, t, bp, right_assoc, kind)
        return left

    def infix_bp(self, t: Tok):
        k = t.kind
        if k in ("nl", "end"):
            return None
        if k == "op":
            v = t.val
            if v == ",":
                return (6, False, "comma")
            if v in ASSIGN_OPS:
                return (7, True, "assign")
            if v == "?":
                nt = self.peek(1)
                if nt.kind in ("nl", "end") or (nt.kind == "op" and nt.val in (")", ",", "]", "}")):
                    return (86, False, "maybe")
                return (11, True, "ternary")
            if v == ".":
                # ExpressionToPostfix: a dot followed by a space concatenates; one followed directly by a
                # name is member access even after a space ("x\n    .Method()" continuation lines)
                nt = self.peek(1)
                if t.ws and (nt.ws or nt.kind not in ("id",) and not (nt.kind == "op" and nt.val == "%")):
                    return (CONCAT_BP, False, "concat_dot")
                return (86, False, "member")
            if v == "(":
                return (86, False, "call") if not t.ws else (CONCAT_BP, False, "autoconcat")
            if v == "[":
                return (86, False, "index") if not t.ws else (CONCAT_BP, False, "autoconcat")
            if v in ("++", "--"):
                if not t.ws:
                    return (82, False, "postfix")
                return None
            if v == "*" and self.peek(1).kind == "op" and self.peek(1).val in (")", "]"):
                return None     # variadic marker: f(args*), [args*]
            if v in BINARY:
                bp, ra = BINARY[v]
                return (bp, ra, "binary")
            if v == "!" and t.ws:
                return (CONCAT_BP, False, "autoconcat")
            if v == "{":
                if self.peek(1).kind in ("nl", "end"):
                    return None
                return None
            return None
        if k == "id":
            w = t.val.lower()
            if w in WORD_BINARY:
                op, bp, ra = WORD_BINARY[w]
                return (bp, ra, "word")
            if w in ("in", "contains", "as", "extends"):
                return None
            if t.ws:
                return (CONCAT_BP, False, "autoconcat")
            return None
        if k in ("num", "str", "deref"):
            return (CONCAT_BP, False, "autoconcat")
        return None

    def parse_infix(self, left, t, bp, right_assoc, kind):
        loc = self.L(t)
        if kind == "comma":
            exprs = [left]
            while self.is_op(","):
                self.next()
                if self.at_eol() or self.is_op(")"):
                    break
                exprs.append(self.parse_expr(6))
            return A.Comma(exprs, **loc)
        if kind == "assign":
            self.next()
            right = self.parse_expr(bp - 1)
            if isinstance(left, (A.Var, A.DynVar, A.Member, A.Index)):
                return A.Assign(t.val, left, right, **loc)
            # AHK binds the assignment to the nearest operand on its left: !x := y, a || b := c, &v := 0
            node = self._bind_rightmost(left, t.val, right, loc)
            if node is None:
                self.error("Invalid assignment", t)
            return node
        if kind == "ternary":
            self.next()
            a = self.parse_expr(6)
            self.expect_op(":")
            b = self.parse_expr(bp - 1)
            return A.Ternary(left, a, b, **loc)
        if kind == "maybe":
            self.next()
            return A.Maybe(left, **loc)
        if kind == "member":
            self.next()
            nt = self.next()
            if nt.kind == "id":
                name, dyn = nt.val, None
            elif nt.kind == "deref":
                name, dyn = None, self._deref_expr(nt)
            elif nt.kind == "num":
                name, dyn = nt.val[1], None
            else:
                self.error("Invalid member name", nt)
            if self.is_op("(") and not self.peek().ws:
                args, variadic = self.parse_call_args()
                return A.MethodCall(left, name, dyn, args, variadic, **loc)
            return A.Member(left, name, dyn, **loc)
        if kind == "call":
            args, variadic = self.parse_call_args()
            return A.Call(left, args, variadic, **loc)
        if kind == "index":
            self.next()
            args = []
            while not self.is_op("]"):
                if self.is_op(","):
                    args.append(None)
                    self.next()
                    continue
                args.append(self.parse_expr(6))
                variadic = False
                if self.is_op("*") and self.is_op("]", 1):
                    self.next()
                    variadic = True
                if self.is_op(","):
                    self.next()
                elif not self.is_op("]"):
                    self.error('Missing "]"')
            self.next()
            node = A.Index(left, args, **loc)
            node.variadic = locals().get("variadic", False)
            return node
        if kind == "postfix":
            self.next()
            return A.IncDec(t.val, left, False, **loc)
        if kind == "binary":
            self.next()
            right = self.parse_expr(bp - 1 if right_assoc else bp)
            if t.val in ("&&", "||", "??"):
                return A.Logical(t.val, left, right, **loc)
            return A.Binary(t.val, left, right, **loc)
        if kind == "word":
            self.next()
            op = WORD_BINARY[t.val.lower()][0]
            right = self.parse_expr(bp - 1 if right_assoc else bp)
            if op in ("&&", "||"):
                return A.Logical(op, left, right, **loc)
            return A.Binary(op, left, right, **loc)
        if kind == "concat_dot":
            self.next()
            right = self.parse_expr(bp)
            return A.Binary(".", left, right, **loc)
        if kind == "autoconcat":
            right = self.parse_expr(bp)
            return A.Binary(".", left, right, **loc)
        self.error("Unexpected operator", t)

    def _bind_rightmost(self, node, op, right, loc):
        lv = (A.Var, A.DynVar, A.Member, A.Index)
        if isinstance(node, lv):
            return A.Assign(op, node, right, **loc)
        for attr in ("right", "operand", "target", "b"):
            child = getattr(node, attr, None) if attr in node.fields else None
            if child is not None:
                new = self._bind_rightmost(child, op, right, loc)
                if new is None:
                    return None
                setattr(node, attr, new)
                return node
        return None

    def parse_call_args(self):
        self.expect_op("(")
        args = []
        variadic = False
        while not self.is_op(")"):
            self.skip_nl()
            if self.is_op(","):
                args.append(None)
                self.next()
                continue
            if self.is_op(")"):
                break
            e = self.parse_expr(6)
            if self.is_op("*") and self.is_op(")", 1):
                self.next()
                variadic = True
            args.append(e)
            if self.is_op(","):
                self.next()
                if self.is_op(")"):
                    args.append(None)
            elif not self.is_op(")"):
                self.error('Missing ")"')
        self.next()
        while args and args[-1] is None:
            args.pop()
        return args, variadic

    def _deref_expr(self, t: Tok) -> A.Node:
        parts = []
        for p in t.val:
            if isinstance(p, str):
                parts.append(p)
            else:
                sub = Parser(None, self.filename, toks=p)
                parts.append(sub.parse_expr(0))
        if len(parts) == 1 and not isinstance(parts[0], str):
            return parts[0]
        # concatenation of literal and expression fragments
        node = None
        for p in parts:
            n = A.Str(p, **self.L(t)) if isinstance(p, str) else p
            node = n if node is None else A.Binary(".", node, n, **self.L(t))
        return node

    def _is_arrow_params(self):
        """At '(' : is this '(params) =>' ?"""
        j = self._match_paren(self.i)
        if j is None:
            return False
        nt = self.toks[j + 1] if j + 1 < len(self.toks) else None
        return nt is not None and nt.kind == "op" and nt.val == "=>"

    def parse_prefix(self) -> A.Node:
        t = self.peek()
        loc = self.L(t)
        k = t.kind
        if k == "num":
            self.next()
            return A.Num(t.val[0], t.val[1], **loc)
        if k == "str":
            self.next()
            return A.Str(t.val, **loc)
        if k == "deref":
            self.next()
            parts = []
            for p in t.val:
                if isinstance(p, str):
                    parts.append(p)
                else:
                    parts.append(Parser(None, self.filename, toks=p).parse_expr(0))
            return A.DynVar(parts, **loc)
        if k == "id":
            w = t.val.lower()
            nt = self.peek(1)
            if nt.kind == "op" and nt.val == "=>":
                self.next(); self.next()
                body = self.parse_expr(6)
                p = A.Param(t.val, False, None, False, False, **loc)
                fd = A.FuncDef("", [p], A.Block([A.Return(body, **loc)], **loc), False, True, False, "arrow", **loc)
                return A.FuncExpr(fd, **loc)
            if w == "not":
                self.next()
                return A.Unary("!", self.parse_expr(25 - 1), **loc)
            if w == "true":
                self.next()
                return A.Num(1, "1", **loc)
            if w == "false":
                self.next()
                return A.Num(0, "0", **loc)
            if w == "unset":
                self.next()
                return A.Unset(**loc)
            if w == "this":
                self.next()
                return A.Var("this", **loc)
            if w == "super":
                self.next()
                return A.Super(**loc)
            if w == "isset" and nt.kind == "op" and nt.val == "(" and not nt.ws:
                self.next(); self.next()
                target = self.parse_expr(0)
                if isinstance(target, A.Maybe):
                    target = target.expr
                self.expect_op(")")
                return A.IsSetExpr(target, **loc)
            # named function expression: Name(params) => expr
            if nt.kind == "op" and nt.val == "(" and not nt.ws:
                j = self._match_paren(self.i + 1)
                if j is not None and j + 1 < len(self.toks) and self.toks[j + 1].kind == "op" and self.toks[j + 1].val == "=>":
                    self.next()
                    params = self.parse_params(")")
                    self.next()  # =>
                    body = self.parse_expr(6)
                    fd = A.FuncDef(t.val, params, A.Block([A.Return(body, **loc)], **loc), False, True, False, "arrow", **loc)
                    return A.FuncExpr(fd, **loc)
            self.next()
            return A.Var(t.val, **loc)
        if k == "op":
            v = t.val
            if v == "(":
                if self._is_arrow_params():
                    params = self.parse_params(")")
                    self.next()  # =>
                    body = self.parse_expr(6)
                    fd = A.FuncDef("", params, A.Block([A.Return(body, **loc)], **loc), False, True, False, "arrow", **loc)
                    return A.FuncExpr(fd, **loc)
                self.next()
                self.skip_nl()
                e = self.parse_expr(0)
                self.skip_nl()
                self.expect_op(")")
                return e
            if v == "[":
                self.next()
                items = []
                while not self.is_op("]"):
                    if self.is_op(","):
                        items.append(None)
                        self.next()
                        continue
                    items.append(self.parse_expr(6))
                    if self.is_op("*") and self.is_op("]", 1):
                        self.next()
                        items[-1] = ("spread", items[-1])
                    if self.is_op(","):
                        self.next()
                    elif not self.is_op("]"):
                        self.error('Missing "]"')
                self.next()
                return A.ArrayLit(items, **loc)
            if v == "{":
                self.next()
                pairs = []
                while not self.is_op("}"):
                    kt = self.next()
                    if kt.kind == "id":
                        key = kt.val
                    elif kt.kind == "num":
                        key = kt.val[1]
                    elif kt.kind == "str":
                        key = kt.val
                    elif kt.kind == "deref":
                        key = self._deref_expr(kt)
                    else:
                        self.error("Invalid object literal key", kt)
                    self.expect_op(":")
                    val = self.parse_expr(6)
                    pairs.append((key, val))
                    if self.is_op(","):
                        self.next()
                    elif not self.is_op("}"):
                        self.error('Missing "}"')
                self.next()
                return A.ObjLit(pairs, **loc)
            if v in ("-", "+", "!", "~"):
                self.next()
                operand = self.parse_expr(67)
                if v == "-" and isinstance(operand, A.Num) and not isinstance(operand.value, str):
                    return A.Num(-operand.value, "-" + operand.text, **loc) if self._num_tight(t) else A.Unary("-", operand, **loc)
                return A.Unary(v, operand, **loc)
            if v == "&":
                self.next()
                operand = self.parse_expr(67)
                return A.Ref(operand, **loc)
            if v in ("++", "--"):
                self.next()
                operand = self.parse_expr(77)
                return A.IncDec(v, operand, True, **loc)
            if v == "*":
                # stray * e.g. (*) => in params handled elsewhere
                pass
        self.error("Unexpected token", t)

    def _num_tight(self, minus_tok):
        nt = self.toks[self.i - 1]
        return True


def _is_remap(rest: str) -> bool:
    from .keys import lookup
    r = rest.strip()
    if not r or " " in r or "(" in r or '"' in r or "'" in r or r.startswith("{"):
        return False
    if r.lower() in ("return", "reload", "exitapp", "pause", "suspend"):
        return False
    rr = r.lstrip("^+!#<>*~$")
    return lookup(rr) is not None


def parse_lines(lines: list[LogicalLine], filename: str) -> list[A.Node]:
    return Parser(lines, filename).parse_program()
