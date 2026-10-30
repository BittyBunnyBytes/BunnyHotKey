"""setup-desktop / update / uninstall in a throwaway HOME: the program moves into $XDG_DATA_HOME/BunnyHotKey/app,
an old-style install (launcher pointing at a clone) is moved there by `bhk update`, `bhk uninstall --yes` leaves
nothing behind but the user's own files, BHK_PREFIX=$HOME or / deletes nothing, and running scripts are stopped.

Every bhk process runs with HOME, the XDG dirs and TMPDIR inside a scratch folder, without DISPLAY/WAYLAND/DBus,
and with a guard (sitecustomize) that refuses - and logs - any delete, rename, write or kill outside the sandbox,
so a broken uninstall can't reach the real home folder or the user's running scripts.  No network: `bhk update`
pulls from a local bare repo.  Run: python3 tests/test_install_cycle.py [--keep]"""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
KEEP = "--keep" in sys.argv

GUARD = r'''
import builtins, json, os, shutil, subprocess, sys
_S = os.path.realpath(os.environ["BHK_TEST_SCRATCH"])
_LOG = os.path.join(_S, "violations.jsonl")
_ROOTS = [os.path.join(_S, d) for d in ("home", "run", "tmp", "work")]
_raw_open, _raw_osopen, _raw_kill = builtins.open, os.open, os.kill


def _real(p):
    p = os.path.abspath(os.fsdecode(p))
    return os.path.join(os.path.realpath(os.path.dirname(p)), os.path.basename(p))


def _inside(p):
    """A strict descendant of the sandbox's home/run/tmp/work (HOME itself is not deletable)."""
    try:
        r = _real(p)
    except (TypeError, ValueError):
        return False
    return any(r.startswith(root + os.sep) for root in _ROOTS)


def _block(op, arg):
    try:
        with _raw_open(_LOG, "a") as fh:
            fh.write(json.dumps({"op": op, "arg": str(arg), "pid": os.getpid(), "argv": sys.argv}) + "\n")
    except OSError:
        pass
    raise PermissionError(f"install-cycle guard: {op} {arg} is outside the sandbox")


def _paths(name, fn, n=1):
    def wrapper(*a, **kw):
        if "dir_fd" not in kw or kw["dir_fd"] is None:     # dir_fd calls come from inside an already-checked rmtree
            for p in a[:n]:
                if not _inside(p):
                    _block(name, p)
        return fn(*a, **kw)
    return wrapper


for _name, _n in (("remove", 1), ("unlink", 1), ("rmdir", 1), ("removedirs", 1), ("rename", 2), ("replace", 2),
                  ("truncate", 1), ("chmod", 1)):
    setattr(os, _name, _paths("os." + _name, getattr(os, _name), _n))
_rmtree = shutil.rmtree


def _guarded_rmtree(path, *a, **kw):
    if not _inside(path):
        _block("shutil.rmtree", path)
    return _rmtree(path, *a, **kw)


shutil.rmtree = _guarded_rmtree
shutil.move = _paths("shutil.move", shutil.move, 2)
_WRITE = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def _ok_write(p):
    try:
        r = _real(p)
    except (TypeError, ValueError):
        return True                                       # fds
    return _inside(r) or r == _LOG or r.startswith(("/dev/", "/proc/"))


def _open(file, mode="r", *a, **kw):
    if any(c in mode for c in "wax+") and not isinstance(file, int) and not _ok_write(file):
        _block("open(" + mode + ")", file)
    return _raw_open(file, mode, *a, **kw)


def _osopen(path, flags, *a, **kw):
    if flags & _WRITE and kw.get("dir_fd") is None and not _ok_write(path):
        _block("os.open", path)
    return _raw_osopen(path, flags, *a, **kw)


builtins.open, os.open = _open, _osopen


def _ours(pid):
    """Only processes started inside this sandbox (they carry BHK_TEST_SCRATCH) may be signalled."""
    try:
        with _raw_open(f"/proc/{pid}/environ", "rb") as fh:
            return ("BHK_TEST_SCRATCH=" + _S).encode() in fh.read().split(b"\0")
    except OSError:
        return False


def _kill(pid, sig):
    if sig != 0 and not _ours(pid):
        _block("os.kill(%d)" % sig, pid)
    return _raw_kill(pid, sig)


os.kill = _kill
if hasattr(os, "killpg"):
    _raw_killpg = os.killpg
    os.killpg = lambda pg, sig: _block("os.killpg", pg) if sig and not _ours(pg) else _raw_killpg(pg, sig)
_Popen_init = subprocess.Popen.__init__


def _popen(self, args, *a, **kw):
    argv = [args] if isinstance(args, (str, bytes)) else list(args)
    tool = os.path.basename(os.fsdecode(argv[0])).split()[0] if argv else ""
    if tool in ("kill", "pkill", "killall"):
        _block("subprocess " + tool, argv)
    if tool in ("rm", "rmdir", "mv", "unlink", "shred", "find"):
        for p in argv[1:]:
            p = os.fsdecode(p)
            if not p.startswith("-") and (os.path.isabs(p) or p.startswith("~")) and not _inside(p):
                _block("subprocess " + tool, argv)
    return _Popen_init(self, args, *a, **kw)


subprocess.Popen.__init__ = _popen
import urllib.request


class _Tarball:
    status = 200

    def __init__(self, path):
        self.fh = _raw_open(path, "rb")
        self.read, self.readinto = self.fh.read, self.fh.readinto
        self.headers = {}

    def getcode(self):
        return 200

    def close(self):
        self.fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _urlopen(url, *a, **kw):
    u = url if isinstance(url, str) else url.full_url
    if u.startswith("https://codeload.github.com/") and os.environ.get("BHK_TEST_TARBALL"):
        return _Tarball(os.environ["BHK_TEST_TARBALL"])
    _block("network", u)


urllib.request.urlopen = _urlopen
urllib.request.urlretrieve = lambda url, *a, **kw: _block("network", url)
'''

DROP = ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS", "XDG_CURRENT_DESKTOP",
        "XDG_SESSION_DESKTOP", "DESKTOP_SESSION", "BHK_PREFIX", "PYTHONPATH", "PYTHONHOME", "XDG_DATA_DIRS",
        "XDG_CONFIG_DIRS", "GIT_DIR", "GIT_WORK_TREE")


class Sandbox:
    def __init__(self, base, name):
        self.s = os.path.realpath(os.path.join(base, name))
        self.home, self.run_dir, self.tmp = (os.path.join(self.s, d) for d in ("home", "run", "tmp"))
        self.data, self.config = os.path.join(self.home, ".local", "share"), os.path.join(self.home, ".config")
        self.clone = os.path.join(self.home, "clone")
        self.app = os.path.join(self.data, "BunnyHotKey", "app")
        self.launcher = os.path.join(self.home, ".local", "bin", "bhk")
        self.mimeapps = os.path.join(self.config, "mimeapps.list")
        for d in (self.home, self.tmp, os.path.join(self.s, "work"), os.path.join(self.s, "guard")):
            os.makedirs(d)
        os.makedirs(self.run_dir, mode=0o700)
        with open(os.path.join(self.s, "guard", "sitecustomize.py"), "w") as fh:
            fh.write(GUARD)
        subprocess.run(["rsync", "-a", REPO + "/", self.clone + "/"], check=True)
        # the copy carries the working tree's uncommitted edits: commit them so the clone is clean for `bhk update`
        self.git(self.clone, "add", "-A")
        self.git(self.clone, "commit", "-qm", "sandbox snapshot", "--allow-empty")
        self.bare = os.path.join(self.s, "work", "bare.git")
        self.git(self.s, "clone", "-q", "--bare", self.clone, self.bare)
        self.git(self.clone, "remote", "set-url", "origin", self.bare)
        self.git(self.clone, "fetch", "-q", "origin")
        self.git(self.clone, "branch", "-q", "--set-upstream-to=origin/main")

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if k not in DROP and not k.startswith("XDG_")}
        env.update(HOME=self.home, XDG_DATA_HOME=self.data, XDG_CONFIG_HOME=self.config,
                   XDG_CACHE_HOME=os.path.join(self.home, ".cache"), XDG_STATE_HOME=os.path.join(self.home, ".local", "state"),
                   XDG_RUNTIME_DIR=self.run_dir, TMPDIR=self.tmp, BHK_TEST_TARBALL=os.path.join(self.s, "work", "update.tar.gz"), PYTHONPATH=os.path.join(self.s, "guard"),
                   PYTHONDONTWRITEBYTECODE="1", BHK_TEST_SCRATCH=self.s, GIT_CONFIG_NOSYSTEM="1",
                   PATH=os.path.join(self.home, ".local", "bin") + os.pathsep + "/usr/local/bin:/usr/bin:/bin")
        env.update(extra)
        return env

    def git(self, cwd, *args):
        return subprocess.run(["git", "-c", "user.name=Sandbox", "-c", "user.email=sandbox@invalid",
                               "-c", "commit.gpgsign=false", *args], cwd=cwd, env=self.env(), check=True,
                              capture_output=True, text=True)

    def bhk(self, *args, cwd=None, launcher=False, timeout=180, **env):
        """`python3 -m bunnyhotkey ARGS` from the clone, or the installed launcher (launcher=True) from HOME."""
        cmd = ["sh", self.launcher, *args] if launcher else [sys.executable, "-m", "bunnyhotkey", *args]
        r = subprocess.run(cmd, cwd=cwd or (self.home if launcher else self.clone), env=self.env(**env),
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        return r

    def write(self, rel, text):
        path = os.path.join(self.home, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def violations(self):
        try:
            with open(os.path.join(self.s, "violations.jsonl")) as fh:
                return [json.loads(line) for line in fh if line.strip()]
        except OSError:
            return []

    def snapshot(self, skip=("home/clone",)):
        """relpath -> 'd' / 'l:target' / sha256 for home, run and tmp."""
        out = {}
        for top in ("home", "run", "tmp"):
            for dirpath, dirs, files in os.walk(os.path.join(self.s, top)):
                rel_dir = os.path.relpath(dirpath, self.s)
                if any(rel_dir == p or rel_dir.startswith(p + os.sep) for p in skip):
                    dirs[:] = []
                    continue
                for d in list(dirs):
                    full = os.path.join(dirpath, d)
                    if os.path.islink(full):
                        out[os.path.join(rel_dir, d)] = "l:" + os.readlink(full)
                        dirs.remove(d)
                    elif not any(os.path.join(rel_dir, d) == p for p in skip):
                        out[os.path.join(rel_dir, d)] = "d"
                for f in files:
                    full = os.path.join(dirpath, f)
                    if os.path.islink(full):
                        out[os.path.join(rel_dir, f)] = "l:" + os.readlink(full)
                    else:
                        with open(full, "rb") as fh:
                            out[os.path.join(rel_dir, f)] = hashlib.sha256(fh.read()).hexdigest()
        return out


def diff(before, after):
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    return added, removed, changed


def read(path):
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return None


class Result:
    def __init__(self):
        self.fails = []

    def check(self, ok, what, detail=""):
        if not ok:
            self.fails.append(what + (f"\n      {detail}" if detail else ""))
        return ok

    def proc(self, r, what):
        return self.check(r.returncode == 0, f"{what} exited {r.returncode}",
                          (r.stdout + r.stderr).strip().replace("\n", "\n      ")[-1500:])

    def clean(self, sb):
        v = sb.violations()
        self.check(not v, f"guard blocked {len(v)} operation(s) outside the sandbox",
                   "\n      ".join(f"{x['op']} {x['arg']}  (argv {x['argv']})" for x in v[:15]))


def make_runtime_files(sb, r):
    """What using BHK leaves around: a prefix with versions/registry, runtime locks and sockets, temp files.
    A real script run creates the prefix and the #SingleInstance lock; the rest is written by name."""
    script = sb.write("work-scripts/hello.ahk", '#SingleInstance Force\nFileAppend "ok", "*"\nExitApp\n')
    run = subprocess.run(["sh", sb.launcher, "--console", "--backend=null", "--no-tray", script], cwd=sb.home,
                         env=sb.env(), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    os.remove(script)
    os.rmdir(os.path.dirname(script))
    prefix = os.path.join(sb.data, "BunnyHotKey", "prefix")
    os.makedirs(os.path.join(prefix, "drive_c", "Program Files", "AutoHotkey", "2.0.19"), exist_ok=True)
    for name, text in (("versions.json", '{"2.0.19": {"path": "%s"}}' % os.path.join(
            prefix, "drive_c", "Program Files", "AutoHotkey", "2.0.19")), ("registry.json", "{}"), ("registry.json.lock", "")):
        with open(os.path.join(prefix, name), "w") as fh:
            fh.write(text)
    for rel in ("run/bunnyhotkey/0123456789abcdef.pid", "run/bunnyhotkey/rot/{CLSID}", f"run/bhk-sync-{os.getuid()}/mutex.x",
                "tmp/bhk-hbitmap-abc123.png", "tmp/bhk-beep-523-150.wav"):
        path = os.path.join(sb.s, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
    return run


# ---------------------------------------------------------------- scenarios
def s1_setup_from_clone(base):
    r, sb = Result(), Sandbox(base, "s1")
    p = sb.bhk("setup-desktop")
    r.proc(p, "setup-desktop")
    r.check(not os.path.exists(sb.clone), "clone folder still exists after setup-desktop", sb.clone)
    r.check(os.path.isfile(os.path.join(sb.app, "bunnyhotkey", "__main__.py")), "program not installed at app/", sb.app)
    text = read(sb.launcher) or ""
    r.check(sb.app in text and sb.clone not in text, "launcher does not point at app/", text.strip())
    r.check("text/x-autohotkey=bunnyhotkey.desktop" in (read(sb.mimeapps) or ""),
            "mimeapps.list has no text/x-autohotkey=bunnyhotkey.desktop", read(sb.mimeapps) or "(missing)")
    if os.path.exists(sb.launcher):
        r.proc(sb.bhk("versions", launcher=True), "installed launcher (bhk versions)")
    r.clean(sb)
    return r


def s1b_dirty_clone_kept(base):
    r, sb = Result(), Sandbox(base, "s1b")
    sb.write("clone/my-notes.txt", "untracked work\n")
    before = {k: v for k, v in sb.snapshot(skip=()).items() if k.startswith("home/clone")}
    r.proc(sb.bhk("setup-desktop"), "setup-desktop (clone with untracked file)")
    after = {k: v for k, v in sb.snapshot(skip=()).items() if k.startswith("home/clone")}
    added, removed, changed = diff(before, after)
    r.check(not (added or removed or changed), "the dirty clone was modified",
            f"added {added[:10]} removed {removed[:10]} changed {changed[:10]}")
    r.check(os.path.isfile(os.path.join(sb.app, "bunnyhotkey", "__main__.py")), "program not installed at app/")
    text = read(sb.launcher) or ""
    r.check(sb.app in text and sb.clone not in text, "launcher does not point at app/", text.strip())
    r.check(not any(os.path.exists(os.path.join(sb.app, d)) for d in (".git", "tests", "__pycache__")),
            "app/ contains .git, tests or __pycache__")
    r.clean(sb)
    return r


def s2_update_old_install(base):
    r, sb = Result(), Sandbox(base, "s2")
    work = os.path.join(sb.s, "work", "upstream")
    sb.git(sb.s, "clone", "-q", sb.bare, work)
    with open(os.path.join(work, "UPDATE_MARKER"), "w") as fh:
        fh.write("new upstream commit\n")
    sb.git(work, "add", "UPDATE_MARKER")
    sb.git(work, "commit", "-qm", "upstream change")
    sb.git(work, "archive", "--format=tar.gz", "--prefix=BunnyHotKey-main/", "-o",
           os.path.join(sb.s, "work", "update.tar.gz"), "HEAD")
    # what setup-desktop wrote before the app/ move: a launcher running the clone in place, no setup.json
    sb.write(".local/bin/bhk", f'#!/bin/sh\nexport PYTHONPATH="{sb.clone}${{PYTHONPATH:+:$PYTHONPATH}}"\n'
                               f'exec {sys.executable} -m bunnyhotkey "$@"\n')
    os.chmod(sb.launcher, 0o755)
    sb.write(".local/share/applications/bunnyhotkey.desktop",
             f"[Desktop Entry]\nType=Application\nName=Bunny Hot Key\nComment=Run AutoHotkey v2 scripts on Linux\n"
             f"Exec={sb.launcher} %f\nIcon=bunnyhotkey\nMimeType=text/x-autohotkey;\nTerminal=false\nCategories=Utility;\n")
    sb.write(".config/mimeapps.list", "[Default Applications]\ntext/x-autohotkey=bunnyhotkey.desktop\n")
    p = sb.bhk("update", launcher=True)
    r.proc(p, "bhk update (old-style install)")
    r.check(os.path.isfile(os.path.join(sb.app, "UPDATE_MARKER")), "update did not land in app/ (UPDATE_MARKER missing)")
    r.check(not os.path.exists(sb.clone), "old (clean) clone folder still exists after update", sb.clone)
    text = read(sb.launcher) or ""
    r.check(sb.app in text and sb.clone not in text, "launcher does not point at app/ after update", text.strip())
    r.check("text/x-autohotkey=bunnyhotkey.desktop" in (read(sb.mimeapps) or ""), "update dropped the .ahk association")
    r.clean(sb)
    return r


def s3_uninstall_leaves_nothing(base):
    r, sb = Result(), Sandbox(base, "s3")
    # the user's own files, which must come through setup + use + uninstall byte for byte
    sb.write(".config/mimeapps.list", "[Default Applications]\ntext/plain=mousepad.desktop\n\n"
                                      "[Added Associations]\ntext/plain=mousepad.desktop;\n")
    sb.write(".local/share/BunnyHotKey/Lib/Mine.ahk", "MyLibFunc() => 42\n")
    sb.write(".config/autostart/my-hotkeys.desktop", "[Desktop Entry]\nType=Application\nName=My hotkeys\n"
                                                     "Exec=bhk x.ahk\n")
    sb.write("scripts/x.ahk", "#Requires AutoHotkey v2.0\n")
    before = sb.snapshot()
    r.proc(sb.bhk("setup-desktop"), "setup-desktop")
    mime = read(sb.mimeapps) or ""
    r.check("text/plain=mousepad.desktop" in mime, "setup-desktop lost the user's own mimeapps.list lines", mime)
    used = make_runtime_files(sb, r)
    p = sb.bhk("uninstall", "--yes", launcher=True)
    r.proc(p, "bhk uninstall --yes")
    added, removed, changed = diff(before, sb.snapshot())
    added = [a for a in added if a != "home/.local/bin"]
    r.check(not added, f"{len(added)} path(s) left behind", "\n      ".join(added[:40]))
    r.check(not removed, f"{len(removed)} of the user's own path(s) deleted", "\n      ".join(removed[:40]))
    r.check(not changed, f"{len(changed)} of the user's own file(s) changed", "\n      ".join(
        f"{c}\n        now: {read(os.path.join(sb.s, c))!r}" for c in changed[:10]))
    if used.returncode:
        print(f"  note: the sample script run exited {used.returncode} (runtime files were seeded by name instead)")
    r.clean(sb)
    return r


def s3b_foreign_launcher(base):
    r, sb = Result(), Sandbox(base, "s3b")
    theirs = "#!/bin/sh\necho 'some other program called bhk'\n"
    sb.write(".local/bin/bhk", theirs)
    before = sb.snapshot()
    setup = sb.bhk("setup-desktop")
    if os.path.exists(sb.app):            # setup went ahead (or refused only the launcher): uninstall from app/
        sb.bhk("uninstall", "--yes", cwd=sb.app)
    elif os.path.exists(sb.clone):
        sb.bhk("uninstall", "--yes")
    r.check(read(sb.launcher) == theirs, "a foreign ~/.local/bin/bhk was overwritten or deleted",
            f"setup-desktop exited {setup.returncode}; launcher now: {read(sb.launcher)!r}")
    added, removed, changed = diff(before, sb.snapshot())
    r.check(not added and not removed and not changed, "setup + uninstall around a foreign launcher was not a no-op",
            f"added {added[:10]} removed {removed[:10]} changed {changed[:10]}")
    r.clean(sb)
    return r


def s4_dangerous_prefix(base, which):
    r, sb = Result(), Sandbox(base, "s4-" + ("home" if which == "home" else "root"))
    r.proc(sb.bhk("setup-desktop"), "setup-desktop")
    canaries = [sb.write("canary.txt", "keep me\n"), sb.write("Documents/keep.txt", "keep me too\n")]
    prefix = sb.home if which == "home" else "/"
    for args in (("uninstall", "--yes"), ("uninstall", "--purge", "--yes")):
        if not os.path.exists(sb.launcher):
            break
        sb.bhk(*args, launcher=True, BHK_PREFIX=prefix)
    for c in canaries:
        r.check(os.path.isfile(c), f"BHK_PREFIX={prefix}: {os.path.relpath(c, sb.home)} was deleted")
    v = sb.violations()
    r.check(not v, f"BHK_PREFIX={prefix}: uninstall tried to delete outside BHK's own files (the guard stopped it)",
            "\n      ".join(f"{x['op']} {x['arg']}" for x in v[:15]))
    return r


def s5_stops_running_scripts(base):
    r, sb = Result(), Sandbox(base, "s5")
    r.proc(sb.bhk("setup-desktop"), "setup-desktop")
    script = sb.write("scripts/sleeper.ahk", "Sleep 120000\n")
    sleeper = subprocess.Popen(["sh", sb.launcher, "--console", "--backend=null", "--no-tray", script], cwd=sb.home,
                               env=sb.env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        time.sleep(3)
        if sleeper.poll() is not None:
            r.check(False, "the sleeper script did not stay running, so this case could not be tested",
                    sleeper.stdout.read()[-800:])
            return r
        p = sb.bhk("uninstall", "--yes", launcher=False, cwd=sb.app)
        r.proc(p, "bhk uninstall --yes with a script running")
        try:
            code = sleeper.wait(timeout=15)
            r.check(code in (0, -signal.SIGTERM, 128 + signal.SIGTERM), f"sleeper ended with {code}, not SIGTERM/clean")
        except subprocess.TimeoutExpired:
            r.check(False, "uninstall left the running script alive")
        r.clean(sb)
        return r
    finally:
        if sleeper.poll() is None:
            os.killpg(sleeper.pid, signal.SIGKILL)
            sleeper.wait()


# ---------------------------------------------------------------- real-home tripwire
def real_home_state():
    home = os.path.expanduser("~")
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    config = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    state = {}
    for path in (os.path.join(home, ".local", "bin", "bhk"), os.path.join(data, "applications", "bunnyhotkey.desktop"),
                 os.path.join(config, "mimeapps.list"), os.path.join(data, "mime", "packages", "bunnyhotkey.xml")):
        state[path] = read(path)
    for path in (os.path.join(data, "BunnyHotKey"),):
        state[path] = sorted(os.listdir(path)) if os.path.isdir(path) else None
    return state


def main():
    for tool in ("rsync", "git"):
        if not shutil.which(tool):
            print(f"skipped: {tool} not installed")
            return 0
    real_before = real_home_state()
    base = tempfile.mkdtemp(prefix="install-cycle-")
    scenarios = [("1 setup-desktop from a clone moves it to app/", s1_setup_from_clone),
                 ("1b a clone with local work is left untouched", s1b_dirty_clone_kept),
                 ("2 bhk update moves an old-style install to app/", s2_update_old_install),
                 ("3 bhk uninstall --yes leaves only the user's files", s3_uninstall_leaves_nothing),
                 ("3b a foreign ~/.local/bin/bhk survives", s3b_foreign_launcher),
                 ("4a BHK_PREFIX=$HOME deletes nothing", lambda b: s4_dangerous_prefix(b, "home")),
                 ("4b BHK_PREFIX=/ deletes nothing", lambda b: s4_dangerous_prefix(b, "root")),
                 ("5 uninstall stops running scripts", s5_stops_running_scripts)]
    failed = 0
    try:
        for title, fn in scenarios:
            try:
                res = fn(base)
            except Exception as e:  # a crashed scenario is a failure, the others still run
                res = Result()
                res.check(False, f"scenario crashed: {type(e).__name__}: {e}")
            print(("ok    " if not res.fails else "FAIL  ") + title)
            for f in res.fails:
                print("    - " + f)
            failed += bool(res.fails)
    finally:
        real_after = real_home_state()
        touched = [p for p in real_before if real_before[p] != real_after[p]]
        if touched:
            failed += 1
            print("FAIL  the real home/repo changed during the test: " + ", ".join(touched))
        if KEEP or failed:
            print(f"sandboxes kept in {base}")
        else:
            shutil.rmtree(base)
    print(f"{len(scenarios) - failed if failed <= len(scenarios) else 0}/{len(scenarios)} scenarios passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
