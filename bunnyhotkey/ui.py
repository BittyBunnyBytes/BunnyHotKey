"""Error reporting (Script::ShowError / PrintErrorStdOut)."""
from __future__ import annotations

import sys


def format_stderr(file, line, msg, extra):
    s = f"{file} ({line}) : ==> {msg}\n"
    if extra:
        s += f"     Specifically: {extra}\n"
    return s


def show_error(rt, kind, msg, extra, file, line):
    text = format_stderr(file, line, msg, extra)
    if rt.directives.get("ErrorStdOut") is not None or not rt.options.get("gui_errors", True):
        sys.stderr.write(text)
        sys.stderr.flush()
        return
    sys.stderr.write(text)
    sys.stderr.flush()
    body = f"{kind}: {msg}\n\n"
    if extra:
        body += f"Specifically: {extra[:80]}\n\n"
    body += f"\tLine: {line}\n\tFile: {file}\n\nThe current thread will exit."
    try:
        from .lib.gui import show_dialog
        show_dialog(body, rt.bivars["a_scriptname"][0](), ["OK"], "error")
    except Exception:
        pass
