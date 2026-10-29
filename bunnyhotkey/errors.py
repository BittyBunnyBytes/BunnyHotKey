"""Python-side exceptions used by the interpreter.

AHK values that are thrown (Error objects or anything else) travel inside
AhkThrow; control flow uses lightweight exceptions as in ExecUntil's result codes.
"""


class AhkSyntaxError(Exception):
    """Load-time error (the script does not start), like Script::ScriptError."""

    def __init__(self, msg, file="", line=0, text=""):
        super().__init__(msg)
        self.msg = msg
        self.file = file
        self.line = line
        self.text = text

    def __str__(self):
        loc = f"{self.file} ({self.line}) : ==> " if self.file else ""
        s = f"{loc}{self.msg}"
        if self.text:
            s += f"\n     Specifically: {self.text}"
        return s


class AhkThrow(Exception):
    """A value thrown by the script (usually an Error object)."""

    def __init__(self, value):
        super().__init__()
        self.value = value


class BreakEx(Exception):
    def __init__(self, label=None):
        self.label = label


class ContinueEx(Exception):
    def __init__(self, label=None):
        self.label = label


class ReturnEx(Exception):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class GotoEx(Exception):
    def __init__(self, label):
        self.label = label


class ExitThread(Exception):
    """Exit: ends the current thread."""


class ExitAppEx(Exception):
    def __init__(self, code=0):
        self.code = code


class ReloadEx(Exception):
    pass
