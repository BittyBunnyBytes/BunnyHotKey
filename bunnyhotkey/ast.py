"""AST node types produced by the parser and consumed by the compiler."""
from __future__ import annotations


class Node:
    # no __slots__ here: nodes carry extra compiler annotations in __dict__
    fields: tuple = ()

    def __init__(self, *args, **kw):
        self.line = kw.pop("line", 0)
        self.file = kw.pop("file", "")
        for name, val in zip(self.fields, args):
            setattr(self, name, val)
        for name in self.fields[len(args):]:
            setattr(self, name, kw.pop(name, None))
        if kw:
            raise TypeError(f"{type(self).__name__}: unknown fields {list(kw)}")

    def __repr__(self):
        return f"{type(self).__name__}(" + ", ".join(f"{f}={getattr(self, f)!r}" for f in self.fields) + ")"


def _node(name, *fields):
    cls = type(name, (Node,), {"__slots__": fields, "fields": fields})
    globals()[name] = cls
    return cls


# expressions
_node("Num", "value", "text")
_node("Str", "value")
_node("Var", "name")
_node("DynVar", "parts")               # parts: list[str | Node]
_node("Member", "obj", "name", "dyn")   # dyn: Node for obj.%expr%
_node("Index", "obj", "args")
_node("Call", "func", "args", "variadic")
_node("MethodCall", "obj", "name", "dyn", "args", "variadic")
_node("Unary", "op", "operand")
_node("Binary", "op", "left", "right")
_node("Logical", "op", "left", "right")       # && || ??
_node("Assign", "op", "target", "value")
_node("Ternary", "cond", "a", "b")
_node("IncDec", "op", "target", "prefix")
_node("Ref", "target")
_node("ArrayLit", "items")
_node("ObjLit", "pairs")                 # pairs: list[(name:str | Node, value)]
_node("FuncExpr", "func")                # fat arrow / named function expression
_node("Comma", "exprs")
_node("Maybe", "expr")                   # var? (pass unset)
_node("Unset")
_node("This")
_node("Super")
_node("IsSetExpr", "target")

# statements
_node("ExprStmt", "expr")
_node("Block", "body")
_node("If", "cond", "then", "orelse")
_node("While", "cond", "body", "until", "label")
_node("Loop", "kind", "args", "body", "until", "label")   # kind: count/parse/read/files/reg
_node("For", "vars", "iterable", "body", "until", "label")
_node("Try", "body", "catches", "orelse", "final")       # catches: list[(classes, varname, body)]
_node("Throw", "expr")
_node("Return", "expr")
_node("Break", "label")
_node("Continue", "label")
_node("Goto", "label")
_node("Label", "name")
_node("Switch", "subject", "casesense", "cases", "default")   # cases: list[(exprs, body)]
_node("Decl", "kind", "items")          # kind: global/local/static; items: list[(name, init)]
_node("FuncDef", "name", "params", "body", "is_static", "is_arrow", "is_method", "kind")
_node("Param", "name", "byref", "default", "optional", "variadic")
_node("ClassDef", "name", "extends", "members")
_node("PropDef", "name", "params", "getter", "setter", "is_static")
_node("ClassVar", "name", "value", "is_static")
_node("HotkeyDef", "keys", "body", "remap", "directive_ctx")
_node("HotstringDef", "options", "trigger", "replacement", "body", "directive_ctx")
_node("Directive", "name", "args", "expr")
_node("Nop")
