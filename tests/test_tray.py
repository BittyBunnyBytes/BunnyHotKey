"""Tray menu logic (no display needed): standard items, custom items, Suspend/Pause state and icons."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bunnyhotkey.loader import Program  # noqa: E402

failures = 0


def check(name, got, want):
    global failures
    ok = got == want
    failures += not ok
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f": got {got!r} want {want!r}"))


prog = Program("*", [], {"backend": "null", "gui_errors": False})
rt = prog.rt
from bunnyhotkey.lib import tray  # noqa: E402
from bunnyhotkey.objects import BuiltinFunc  # noqa: E402

m = tray.menu()
check("standard items", [it.name for it in m.items],
      ["&Open", "&Help", "", "&Window Spy", "&Reload Script", "&Edit Script", "", "&Suspend Hotkeys",
       "&Pause Script", "E&xit"])
check("default item", m.default, "&Open")
ran = []
rt.builtins["suspend"]  # Suspend exists
m.items.append(__import__("bunnyhotkey.lib.guiobj", fromlist=["MenuItem"]).MenuItem(
    "Custom", BuiltinFunc("cb", lambda *a: ran.append(a[0]), 0, 3)))
tray.on_event({"event": "TrayItem", "index": len(m.items) - 1})
rt.check_interrupts()
check("custom item callback", ran, ["Custom"])
tray.on_event({"event": "TrayItem", "index": 7})
rt.check_interrupts()
tray._sync_checks(m)
check("suspend toggles", (rt.suspended, m.items[7].checked), (True, True))
check("suspend icon", os.path.basename(tray._icon_path()), "bunnyhotkey-suspend-64.png")
tray.on_event({"event": "TrayItem", "index": 8})
rt.check_interrupts()
check("pause icon wins", os.path.basename(tray._icon_path()), "bunnyhotkey-pause-64.png")
rt.icon_tip = "My tip"
check("A_IconTip", tray._tip(), "My tip")
w = m.wire()
check("wire format", (w[0]["default"], w[7]["checked"], w[2]["label"]), (True, True, ""))
print("all passed" if not failures else f"{failures} failed")
sys.exit(1 if failures else 0)
