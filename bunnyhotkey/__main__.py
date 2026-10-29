"""bhk - Bunny Hot Key command line.

  bhk SCRIPT.ahk [args...]       run a script (AutoHotkey switches /ErrorStdOut /force /restart /Validate work too)
  bhk install [VERSION|FILE]     install an official AutoHotkey v2 release into the BHK prefix (default: latest)
  bhk versions                   list installed AutoHotkey versions
  bhk uninstall VERSION          remove an installed version
  bhk dash | windowspy | launcher  run AutoHotkey's own UX scripts from the newest install
  bhk new NAME                   create a new script from AutoHotkey's template
  bhk setup-desktop              register .ahk files, the icon and menu entries with your desktop
  bhk doctor                     check X11/Wayland input permissions and optional tools
"""
from __future__ import annotations

import os
import sys


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    options = {}
    while argv and (argv[0].startswith("/") and not os.path.exists(argv[0]) or argv[0].startswith("--")):
        a = argv.pop(0)
        al = a.lower().lstrip("/-")
        if al in ("errorstdout",) or al.startswith("errorstdout"):
            options["errorstdout"] = True
            options["gui_errors"] = False
        elif al in ("force", "f"):
            options["force"] = True
        elif al in ("restart", "r"):
            options["force"] = True
        elif al in ("validate", "ilib", "check"):
            options["validate"] = True
            if al == "ilib" and argv:
                argv.pop(0)
        elif al.startswith("backend"):
            options["backend"] = a.split("=", 1)[1] if "=" in a else argv.pop(0)
        elif al in ("no-gui-errors", "console"):
            options["gui_errors"] = False
        elif al in ("version", "v"):
            from .runtime import VERSION
            print(f"Bunny Hot Key {__import__('bunnyhotkey').__version__} (AutoHotkey {VERSION} compatible)")
            return 0
        elif al in ("help", "h", "?"):
            print(__doc__)
            return 0
        elif al == "script":
            pass
        elif al == "cp65001" or al.startswith("cp"):
            pass
    if not argv:
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd in ("install", "versions", "list", "uninstall", "dash", "windowspy", "launcher", "new", "setup-desktop",
               "doctor") and not os.path.exists(cmd):
        from . import manager
        return manager.command(cmd, argv[1:], options)
    if cmd == "run":
        argv = argv[1:]
    script, args = argv[0], argv[1:]
    if script != "*" and not os.path.exists(script):
        from .lib.files import host_path
        hp = host_path(script)
        if os.path.exists(hp):
            script = hp
        elif os.path.exists(script + ".ahk"):
            script = script + ".ahk"
        else:
            print(f"bhk: script not found: {script}", file=sys.stderr)
            return 2
    if options.get("errorstdout"):
        options["gui_errors"] = False
    from .loader import Program
    sys.setrecursionlimit(20000)
    prog = Program(script, args, options)
    if options.get("errorstdout"):
        prog.rt.directives["ErrorStdOut"] = "UTF-8"
    try:
        return prog.run()
    except SystemExit as e:
        return int(e.code or 0)


if __name__ == "__main__":
    import threading
    threading.stack_size(64 * 1024 * 1024)
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("code", main()), name="bhk-script")
    t.start()
    t.join()
    sys.exit(result.get("code", 1))
