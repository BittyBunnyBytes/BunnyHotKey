"""Script loading and the program lifecycle (Script::LoadFromFile, AutoExecSection, ExitApp)."""
from __future__ import annotations

import hashlib
import os
import re
import signal
import sys
import threading

from . import ast as A
from . import objects as O
from .errors import AhkSyntaxError, AhkThrow, ExitAppEx, ExitThread, ReloadEx, ReturnEx
from .lexer import LogicalLine, SourceReader, unescape
from .objects import BuiltinFunc, CLASSES, Cell
from .values import UNSET


class Loader:
    def __init__(self, rt):
        self.rt = rt
        self.include_dir = None

    # ------------------------------------------------------------ includes
    def read_file(self, path) -> list[LogicalLine]:
        rt = self.rt
        if path == "*":
            text = sys.stdin.read()
        else:
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
            except OSError as e:
                raise AhkSyntaxError(f"Script file not found.", path, 0, str(e))
            from .lib.files import decode_file
            text = decode_file(data, "UTF-8")
        real = os.path.realpath(path) if path != "*" else "*"
        rt.included.add(real.lower())
        rt.files.append(path)
        lines = SourceReader(text, path).logical_lines()
        out: list[LogicalLine] = []
        saved_dir = self.include_dir
        self.include_dir = os.path.dirname(os.path.abspath(path)) if path != "*" else os.getcwd()
        for ll in lines:
            m = re.match(r"#(Include|IncludeAgain)\s+(.*)$", ll.text, re.I)
            if m:
                again = m.group(1).lower() == "includeagain"
                out.extend(self.include(m.group(2).strip(), again, ll))
                continue
            out.append(ll)
        self.include_dir = saved_dir
        return out

    def _expand_vars(self, s, ll):
        rt = self.rt

        def sub(m):
            name = m.group(1).lower()
            if name == "a_linefile":
                return ll.file
            if name in rt.bivars:
                try:
                    return str(rt.bivars[name][0]())
                except Exception:
                    return m.group(0)
            return m.group(0)
        return re.sub(r"%(A_\w+)%", sub, s, flags=re.I)

    def include(self, spec, again, ll) -> list[LogicalLine]:
        from .prefix import lib_dirs
        ignore = False
        if spec.lower().startswith("*i"):
            ignore = True
            spec = spec[2:].strip()
        spec = spec.strip("\"'")
        spec = self._expand_vars(spec, ll)
        if spec.startswith("<") and spec.endswith(">"):
            name = spec[1:-1]
            cands = []
            for d in lib_dirs(os.path.dirname(self.rt.script_path) if self.rt.script_path != "*" else os.getcwd()):
                cands.append(os.path.join(d, name + ".ahk"))
                if "_" in name:
                    cands.append(os.path.join(d, name.split("_")[0] + ".ahk"))
            path = next((c for c in cands if os.path.isfile(c)), None)
            if path is None:
                path = next((self._ci(c) for c in cands if self._ci(c)), None)
            if path is None:
                if ignore:
                    return []
                raise AhkSyntaxError("Script library not found.", ll.file, ll.line, spec)
        else:
            from .lib.files import host_path
            p = spec.replace("\\", "/")
            if not os.path.isabs(p) and not (len(spec) > 1 and spec[1] == ":"):
                p = os.path.join(self.include_dir or os.getcwd(), p)
            else:
                p = host_path(spec)
            p = os.path.normpath(p.replace("\\", "/"))   # "%A_LineFile%\..\x" -> the file's folder
            p = self._ci(p) or p
            if os.path.isdir(p):
                self.include_dir = p
                return []
            path = p
            if not os.path.isfile(path):
                if ignore:
                    return []
                raise AhkSyntaxError("#Include file cannot be opened.", ll.file, ll.line, spec)
        real = os.path.realpath(path).lower()
        if real in self.rt.included and not again:
            return []
        return self.read_file(path)

    @staticmethod
    def _ci(path):
        from .lib.files import _ci
        p = _ci(path)
        return p if os.path.exists(p) else None

    # ------------------------------------------------------------ load
    def load(self, path):
        from .parser import parse_lines
        from .compiler import Compiler
        lines = self.read_file(path)
        self.pre_directives(lines)
        stmts = parse_lines(lines, path)
        comp = Compiler(self.rt)
        auto, hot = comp.compile_program(stmts)
        self.rt.label_table = {}
        return auto, hot

    def pre_directives(self, lines):
        """Directives that must be known before anything runs (#Requires, #SingleInstance, ...)."""
        rt = self.rt
        for ll in lines:
            t = ll.text
            if not t.startswith("#"):
                continue
            m = re.match(r"#(\w+)\s*,?\s*(.*)$", t)
            if not m:
                continue
            name, arg = m.group(1).lower(), m.group(2).strip()
            if name == "requires":
                self.requires(arg, ll)
            elif name == "singleinstance":
                rt.directives["SingleInstance"] = arg or "Force"
                rt.singleinstance_set = True
            elif name == "errorstdout":
                rt.directives["ErrorStdOut"] = arg or "UTF-8"
            elif name == "notrayicon":
                rt.directives["NoTrayIcon"] = True
            elif name == "warn":
                rt.directives["Warn"] = True
            elif name == "maxthreads":
                rt.directives["MaxThreads"] = int(arg or 10)
            elif name == "hotiftimeout":
                rt.directives["HotIfTimeout"] = int(arg or 1000)
            elif name == "usehook":
                rt.directives["UseHook"] = arg != "0"
            elif name == "clipboardtimeout":
                rt.directives["ClipboardTimeout"] = int(arg or 1000)
            elif name == "winactivateforce":
                rt.directives["WinActivateForce"] = True

    def requires(self, arg, ll):
        rt = self.rt
        m = re.match(r'"?AutoHotkey\s+(.*?)"?\s*(?:;.*)?$', arg, re.I)
        if not m:
            return     # #Requires for other things (e.g. a library) is ignored
        spec = m.group(1).strip()
        parts = spec.split()
        ver = parts[0]
        vm = re.match(r"(>=|<=|>|<|=)?v?(\d[\w.\-+]*)", ver)
        if not vm:
            return
        op, v = vm.group(1) or "", vm.group(2)
        if v.startswith("1"):
            raise AhkSyntaxError(
                "This script requires AutoHotkey v1, which Bunny Hot Key does not run. "
                "Run it with the real AutoHotkey v1 under Wine, or convert it to v2.", ll.file, ll.line, arg)
        from .prefix import installed_versions
        from .lib.process import ver_compare
        from .runtime import VERSION
        inst = sorted(installed_versions().keys(), key=lambda x: [int(p) if p.isdigit() else 0 for p in re.split(r"[.\-]", x)])
        choose = None
        for cand in reversed(inst + [VERSION]):
            c = ver_compare(cand, v)
            if (op in ("", ">=") and c >= 0 and (op == ">=" or cand.startswith(v) or c >= 0)) or (op == ">" and c > 0) \
                    or (op == "<" and c < 0) or (op == "<=" and c <= 0) or (op == "=" and c == 0):
                choose = cand
                break
        if choose is None:
            raise AhkSyntaxError(f"This script requires AutoHotkey {ver}.", ll.file, ll.line, arg)
        rt.ahk_version = choose
        if "64-bit" in spec or "32-bit" in spec:
            pass


class Program:
    """Runs a script from start to exit."""

    def __init__(self, path, args, options):
        from .runtime import Runtime
        from .classes import setup
        from .lib import register_all
        from .lib import core
        from .lib.input_ import _ih_setup
        self.rt = rt = Runtime(path, args, options)
        rt.lib_core = core
        setup(rt)
        register_all(rt)
        for name, cls in CLASSES.items():
            if "." in name:
                continue
            key = name.lower()
            c = Cell(name, cls, "const")
            rt.globals[key] = c
            rt.consts.add(key)
        rt.args_array = O.AhkArray(None, list(args))
        from .lib import guiobj
        guiobj.setup()
        from .lib import com
        com.setup_classes()
        self.loader = Loader(rt)

    def run(self) -> int:
        rt = self.rt
        try:
            auto, hot = self.loader.load(rt.script_path)
        except AhkSyntaxError as e:
            self.load_error(e)
            return 2
        if rt.options.get("validate"):
            return 0
        self.single_instance()
        from .lib import registry
        try:
            registry.seed_defaults()
        except OSError:
            pass
        try:
            self.register_hot(hot)
        except AhkThrow as e:
            rt.unhandled(e.value)
            return 2
        except AhkSyntaxError as e:
            self.load_error(e)
            return 2
        from .lib import ipc
        ipc.create_main_window()          # A_ScriptHwnd: hidden "AutoHotkey" window, messages from other scripts
        if getattr(rt, "want_hook", False):
            from .lib.flow import _install_hook
            _install_hook(1)          # #InstallKeybdHook / #InstallMouseHook
        if rt.hotmgr is not None and (rt.hotkeys.hotkeys or rt.hotstrings.items):
            from .backends import get_backend
            get_backend(rt).refresh()
        try:
            signal.signal(signal.SIGTERM, lambda *a: self._sigterm())
        except ValueError:
            pass
        code = 0
        reason = "Exit"
        try:
            try:
                auto(None)
            except ExitThread:
                pass
            except ReturnEx:
                pass
            except AhkThrow as e:
                rt.unhandled(e.value)
                if not rt.is_persistent():
                    code = 2
            rt.auto_exec_done = True
            rt.defaults = rt.thread.settings
            if rt.is_persistent():
                from .lib import tray
                try:
                    tray.show()
                except AhkThrow:
                    pass
            rt.idle_loop()
            code = rt.exit_code or code
        except ExitAppEx as e:
            code = e.code
            reason = "Exit"
        except ReloadEx:
            reason = "Reload"
            self.on_exit("Reload", 0)
            self.shutdown()
            os.execv(sys.executable, [sys.executable, "-m", "bunnyhotkey", *sys.argv[1:]])
        except KeyboardInterrupt:
            reason = "Close"
        self.on_exit(reason, code)
        self.shutdown()
        return code

    def _sigterm(self):
        self.rt.exiting = True
        raise ExitAppEx(0)

    def on_exit(self, reason, code):
        rt = self.rt
        for fn in list(reversed(rt.on_exit_funcs)):
            try:
                r = rt.call(fn, [reason, code])
                from .values import to_bool
                if to_bool(r) and reason not in ("Reload",):
                    pass
            except (AhkThrow, ExitThread, ExitAppEx):
                pass

    def shutdown(self):
        rt = self.rt
        rt.exiting = True
        if rt.backend is not None:
            try:
                rt.backend.stop()
            except Exception:
                pass
        self.release_instance()

    def load_error(self, e: AhkSyntaxError):
        from .ui import show_error
        sys.stderr.write(str(e) + "\n")
        if self.rt.options.get("gui_errors", True) and self.rt.directives.get("ErrorStdOut") is None:
            try:
                from .lib.gui import show_dialog
                body = f"Error: {e.msg}\n\n" + (f"Text:\t{e.text}\n" if e.text else "") + f"Line:\t{e.line}\nFile:\t{e.file}\n\nThe program will exit."
                show_dialog(body, os.path.basename(self.rt.script_path), ["OK"], "error")
            except Exception:
                pass

    # ------------------------------------------------------------ hotkeys
    def register_hot(self, hot):
        rt = self.rt
        from .hotmgr import Criterion, HotManager
        from .lib.input_ import do_send
        mgr = None
        crit = None
        crit_by_text = {}
        for kind, node, fn in hot:
            if kind == "directive":
                name = node.name.lower()
                if name == "hotif":
                    if fn is None:
                        crit = None
                    else:
                        if mgr is None:
                            mgr = rt.hotmgr or HotManager(rt)
                            rt.hotmgr = mgr
                        key = node.args.strip()
                        crit = crit_by_text.get(key)
                        if crit is None:
                            crit = Criterion(fn, key, "expr")
                            crit_by_text[key] = crit
                            mgr.criteria.append(crit)
                elif name == "maxthreadsperhotkey":
                    rt.directives["MaxThreadsPerHotkey"] = int(node.args or 1)
                elif name == "maxthreadsbuffer":
                    rt.directives["MaxThreadsBuffer"] = node.args.strip().lower() not in ("false", "0", "off")
                elif name == "inputlevel":
                    rt.directives["InputLevel"] = int(node.args or 0)
                elif name == "suspendexempt":
                    rt.directives["SuspendExempt"] = node.args.strip().lower() not in ("false", "0", "off")
                elif name == "hotstring":
                    if mgr is None:
                        mgr = rt.hotmgr or HotManager(rt)
                        rt.hotmgr = mgr
                    a = node.args.strip()
                    if a.lower().startswith("endchars"):
                        mgr.hotstrings.end_chars = unescape(a[8:].strip())
                    elif a.lower().startswith("nomouse"):
                        mgr.hotstrings.mouse_reset = False
                    else:
                        mgr.hotstrings.default_opts += a
                elif name in ("requires", "singleinstance", "errorstdout", "notrayicon", "warn", "maxthreads",
                              "hotiftimeout", "usehook", "clipboardtimeout", "winactivateforce", "installkeybdhook",
                              "installmousehook", "keyhistory", "dllload", "include", "includeagain", "persistent",
                              "scriptversion", "noenv", "maxhotkeysperinterval", "hotkeyinterval", "hotkeymodifiertimeout",
                              "menumaskkey", "allowsamelinecomments", "commentflag", "escapechar"):
                    if name == "persistent":
                        rt.persistent = True
                    elif name == "dllload":
                        from .lib.dllcall import dll_load
                        if not dll_load(str(node.args or "")):
                            raise AhkSyntaxError("Failed to load DLL.", node.file, node.line, str(node.args))
                    elif name in ("installkeybdhook", "installmousehook"):
                        rt.want_hook = True
                    elif name == "keyhistory":
                        from .lib.flow import set_key_history
                        set_key_history(int(str(node.args or "40").strip() or 40))
                    elif name == "maxhotkeysperinterval":
                        rt.max_hotkeys_per_interval = int(node.args or 70)
                else:
                    raise AhkSyntaxError("Unknown directive.", node.file, node.line, "#" + node.name)
                continue
            if mgr is None:
                mgr = rt.hotmgr or HotManager(rt)
                rt.hotmgr = mgr
            if isinstance(node, A.HotkeyDef):
                for keys in node.keys:
                    if node.remap:
                        self.add_remap(mgr, keys, node.remap, crit, node)
                    else:
                        try:
                            mgr.add_hotkey(keys, fn, crit, from_script=True)
                        except AhkThrow:
                            raise AhkSyntaxError("Invalid hotkey.", node.file, node.line, keys)
            elif isinstance(node, A.HotstringDef):
                opts = node.options
                trig = unescape(node.trigger)
                if fn is not None:
                    mgr.hotstrings.add(opts, trig, None, fn, crit)
                else:
                    repl = node.replacement or ""
                    repl = repl.lstrip(" \t")
                    mgr.hotstrings.add(opts, trig, unescape(repl), None, crit)

    def add_remap(self, mgr, src, dst, crit, node):
        from . import keys as K
        from .lib.input_ import do_send, backend
        d = dst.strip()
        dmods = ""
        while d and d[0] in "^+!#<>*~$" and len(d) > 1:
            dmods += d[0]
            d = d[1:]
        dk = K.lookup(d)
        if dk is None:
            raise AhkSyntaxError("Invalid key name.", node.file, node.line, dst)
        name = dk.name if dk.kind != "key" or not dk.char else dk.char
        src_clean = src.lstrip("*")
        if dk.kind == "mouse":
            down = lambda *a: (backend().button(dk.name, True), backend().flush(), "")[-1]
            up = lambda *a: (backend().button(dk.name, False), backend().flush(), "")[-1]
        else:
            down = lambda *a: (do_send("{Blind}" + dmods + "{" + name + " DownR}", mode="Input"), "")[-1]
            up = lambda *a: (do_send("{Blind}{" + name + " Up}", mode="Input"), "")[-1]
        mgr.add_hotkey("*" + src_clean, BuiltinFunc(src + "::" + dst, down, 0, 1), crit, from_script=True)
        mgr.add_hotkey("*" + src_clean + " up", BuiltinFunc(src + " up::" + dst, up, 0, 1), crit, from_script=True)

    # ------------------------------------------------------------ #SingleInstance
    def _lockfile(self):
        base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
        d = os.path.join(base, "bunnyhotkey")
        os.makedirs(d, exist_ok=True)
        h = hashlib.sha1(self.rt.script_path.lower().encode()).hexdigest()[:16]
        return os.path.join(d, h + ".pid")

    def single_instance(self):
        rt = self.rt
        if rt.script_path == "*":
            return
        mode = rt.directives["SingleInstance"].lower()
        lf = self._lockfile()
        if mode != "off":
            try:
                with open(lf) as fh:
                    old = int(fh.read().strip() or 0)
            except (OSError, ValueError):
                old = 0
            if old and old != os.getpid() and os.path.exists(f"/proc/{old}"):
                if mode == "ignore":
                    raise SystemExit(0)
                if mode == "prompt" and not getattr(rt, "singleinstance_set", False) and not rt.options.get("force"):
                    from .lib.gui import show_dialog
                    ans = show_dialog("An older instance of this script is already running.  Replace it with this instance?\n"
                                      "Note: To avoid this message, see #SingleInstance in the help file.",
                                      os.path.basename(rt.script_path), ["Yes", "No"], "question")
                    if ans != "Yes":
                        raise SystemExit(0)
                elif mode == "prompt":
                    from .lib.gui import show_dialog
                    ans = show_dialog("An older instance of this script is already running.  Replace it with this instance?",
                                      os.path.basename(rt.script_path), ["Yes", "No"], "question")
                    if ans != "Yes":
                        raise SystemExit(0)
                try:
                    os.kill(old, signal.SIGTERM)
                except OSError:
                    pass
        try:
            with open(lf, "w") as fh:
                fh.write(str(os.getpid()))
            self._lf = lf
        except OSError:
            self._lf = None

    def release_instance(self):
        lf = getattr(self, "_lf", None)
        if lf:
            try:
                with open(lf) as fh:
                    if fh.read().strip() == str(os.getpid()):
                        os.remove(lf)
            except OSError:
                pass
