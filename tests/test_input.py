"""Input-engine tests on the null backend: Send parsing, hotkey matching, hotstrings.

Run: python3 tests/test_input.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bunnyhotkey.loader import Program  # noqa: E402

failures = 0


def check(name, got, want):
    global failures
    if got == want:
        print(f"PASS {name}")
    else:
        failures += 1
        print(f"FAIL {name}: got {got!r} want {want!r}")


prog = Program("*", [], {"backend": "null", "gui_errors": False})
rt = prog.rt
from bunnyhotkey.backends import get_backend  # noqa: E402
from bunnyhotkey.lib.input_ import do_send  # noqa: E402

b = get_backend(rt)

# --- Send syntax ---
b.log.clear()
do_send("^c")
check("Send ^c", [e for e in b.log if e[0] == "key"], [("key", 29, True), ("key", 46, True), ("key", 46, False),
                                                      ("key", 29, False)])
b.log.clear()
do_send("A")
check("Send A uses shift", [e[1] for e in b.log if e[0] == "key" and e[2]], [42, 30])
b.log.clear()
do_send("{Enter 2}")
check("Send {Enter 2}", sum(1 for e in b.log if e == ("key", 28, True)), 2)
b.log.clear()
do_send("{Shift down}x{Shift up}")
check("Send {Shift down}", [e for e in b.log if e[0] == "key"][0], ("key", 42, True))
b.log.clear()
do_send("{Text}^!", )
check("Send {Text} literal", [e[1] for e in b.log if e[0] == "key" and e[2]], [42, 7, 42, 2])

# --- hotkey matching (HookEngine) ---
from bunnyhotkey.hotmgr import HotManager  # noqa: E402
from bunnyhotkey.objects import BuiltinFunc  # noqa: E402

mgr = HotManager(rt)
rt.hotmgr = mgr
fired = []
mgr.add_hotkey("^j", BuiltinFunc("cb", lambda name: fired.append(name), 1, 1), None)
mgr.add_hotkey("~F5", BuiltinFunc("cb2", lambda name: fired.append(name), 1, 1), None)
eng = mgr.engine
check("^j suppressed", (eng.on_event(29, True), eng.on_event(36, True))[1], True)
eng.on_event(36, False), eng.on_event(29, False)
check("plain j passes", eng.on_event(36, True), False)
eng.on_event(36, False)
check("~F5 not suppressed", eng.on_event(63, True), False)
eng.on_event(63, False)
rt.check_interrupts()
check("hotkeys fired", fired, ["^j", "~F5"])

# --- hotstrings ---
sent = []
import bunnyhotkey.lib.input_ as inp  # noqa: E402
real = inp.do_send
inp.do_send = lambda keys, **kw: sent.append(keys)
hs = mgr.hotstrings
hs.add("", "btw", "by the way", None, None)
hs.add("*", "@@", "me@example.com", None, None)
for ch in "say btw ":
    hs.on_char(ch, False)
rt.check_interrupts()
check("btw replaced", sent, ["{BS 4}", "by the way", " "])
sent.clear()
for ch in "Btw.":
    hs.on_char(ch, False)
rt.check_interrupts()
check("case conformity", sent[1], "By the way")
sent.clear()
for ch in "x@@":
    hs.on_char(ch, False)
rt.check_interrupts()
check("no trigger inside a word without ?", sent, [])
sent.clear()
hs.reset()
for ch in " @@":
    hs.on_char(ch, False)
rt.check_interrupts()
check("* option", sent, ["{BS 2}", "me@example.com"])
inp.do_send = real

print(f"{'all passed' if not failures else f'{failures} failed'}")
sys.exit(1 if failures else 0)
