"""bhk - Bunny Hot Key command line.

  bhk --ahk-version=auto|1|2 SCRIPT.ahk  select script syntax (default: auto)
  bhk SCRIPT.ahk [args...]       run a script (AutoHotkey switches /ErrorStdOut /force /restart /Validate work too)
  bhk install [VERSION|FILE]     install an official AutoHotkey v2 release into the BHK prefix (default: latest)
  bhk versions                   list installed AutoHotkey versions
  bhk uninstall VERSION          remove an installed AutoHotkey version
  bhk update                     update Bunny Hot Key itself from GitHub
  bhk uninstall [--purge] [--yes]  uninstall Bunny Hot Key (stops running scripts, removes everything it set up)
  bhk dash | windowspy | launcher  run AutoHotkey's own UX scripts from the newest install
  bhk new NAME                   create a new script from AutoHotkey's template
  bhk setup-desktop              install into ~/.local/share/BunnyHotKey/app, register .ahk files, icon, menu entry
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
        elif al == "ahk-version" or al.startswith("ahk-version="):
            version = a.split("=", 1)[1] if "=" in a else (argv.pop(0) if argv else "")
            if version not in ("auto", "1", "2"):
                print("bhk: --ahk-version must be auto, 1, or 2", file=sys.stderr)
                return 2
            options["ahk_version"] = version
        elif al.startswith("backend"):
            options["backend"] = a.split("=", 1)[1] if "=" in a else argv.pop(0)
        elif al == "no-tray":
            options["no_tray"] = True
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
        if sys.stdin.isatty() or not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            print(__doc__)
            return 0
        # started from the menu/desktop icon without a script: AutoHotkey shows its Dash
        from . import manager
        return manager.launch_dash()
    cmd = argv[0]
    if cmd in ("install", "versions", "list", "uninstall", "dash", "windowspy", "launcher", "new", "setup-desktop",
               "doctor", "update") and not os.path.exists(cmd):
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
        _cleanup(prog)
        return int(e.code or 0)
    except BaseException:
        _cleanup(prog)       # a crash still lets go of held keys/buttons and restores the modifier map
        raise


def _cleanup(prog):
    try:
        prog.shutdown()
    except Exception:
        pass


if __name__ == "__main__":
    import threading
    threading.stack_size(64 * 1024 * 1024)
    result = {}

    def run():
        try:
            result["code"] = main()
        except SystemExit as e:      # sys.exit()/SystemExit("message") inside the thread
            if isinstance(e.code, str):
                print(e.code, file=sys.stderr)
            result["code"] = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    t = threading.Thread(target=run, name="bhk-script")
    t.start()
    t.join()
    sys.exit(result.get("code", 1))
