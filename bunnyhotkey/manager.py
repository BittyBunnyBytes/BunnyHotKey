"""bhk install / versions / uninstall / update / dash / windowspy / launcher / new / setup-desktop / doctor.

Installs official AutoHotkey v2 releases (github.com/AutoHotkey/AutoHotkey) into the
BHK prefix, verifying each download against the SHA-256 digest GitHub publishes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from .prefix import ahk_dir, installed_versions, prefix_root, save_versions

API = "https://api.github.com/repos/AutoHotkey/AutoHotkey/releases"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _get_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "BunnyHotKey"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _release(version):
    if version in (None, "", "latest"):
        rel = _get_json(API + "/latest")
    else:
        v = version if version.startswith("v") else "v" + version
        rel = _get_json(f"{API}/tags/{v}")
    tag = rel["tag_name"]
    if not tag.lstrip("v").startswith("2"):
        raise SystemExit(f"bhk: {tag} is not an AutoHotkey v2 release")
    zips = [a for a in rel["assets"] if a["name"].endswith(".zip")]
    if not zips:
        raise SystemExit(f"bhk: release {tag} has no zip asset")
    ver = tag.lstrip("v")
    if not re.fullmatch(r"[\w.+-]+", ver):
        raise SystemExit(f"bhk: unexpected release tag {tag}")
    return ver, zips[0]


def install(args):
    target = args[0] if args else "latest"
    if os.path.isfile(target) and target.lower().endswith(".zip"):
        path = target
        ver = os.path.basename(target).replace("AutoHotkey_", "").replace(".zip", "")
        if not re.fullmatch(r"[\w.+-]+", ver) or ver in (".", "..", "UX", "Lib"):
            raise SystemExit(f"bhk: can't tell the AutoHotkey version from the file name {os.path.basename(target)}")
        digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
        source = os.path.abspath(target)
    elif os.path.isfile(target):
        raise SystemExit("bhk: pass the release .zip (or a version number); setup .exe files are not unpacked")
    else:
        ver, asset = _release(target)
        print(f"Downloading AutoHotkey {ver} ({asset['name']})...")
        tmpdir = tempfile.mkdtemp(prefix="bhk-")
        import atexit
        atexit.register(shutil.rmtree, tmpdir, True)
        path = os.path.join(tmpdir, asset["name"])
        urllib.request.urlretrieve(asset["browser_download_url"], path)
        digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
        want = (asset.get("digest") or "").removeprefix("sha256:")
        if want and want != digest:
            raise SystemExit(f"bhk: checksum mismatch for {asset['name']} (expected {want}, got {digest})")
        print("SHA-256 verified." if want else "warning: GitHub published no digest for this asset.")
        source = asset["browser_download_url"]
    dest = os.path.join(ahk_dir(), ver)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    with zipfile.ZipFile(path) as z:
        for member in z.namelist():
            out = os.path.realpath(os.path.join(dest, member))
            if not out.startswith(os.path.realpath(dest) + os.sep):
                raise SystemExit(f"bhk: unsafe path in archive: {member}")
        z.extractall(dest)
    # newest install provides the shared UX folder, like AutoHotkey's own installer
    ux_src = os.path.join(dest, "UX")
    if os.path.isdir(ux_src):
        ux = os.path.join(ahk_dir(), "UX")
        if os.path.exists(ux):
            shutil.rmtree(ux)
        shutil.copytree(ux_src, ux)
    vers = installed_versions()
    vers[ver] = {"path": dest, "source": source, "sha256": digest}
    save_versions(vers)
    from .prefix import write_hashes
    write_hashes()
    from .lib import registry
    print(f"Installed AutoHotkey {ver} into {dest}")
    return 0


def versions(args):
    vers = installed_versions()
    if not vers:
        print("No AutoHotkey versions installed. Run: bhk install")
        return 0
    for v, info in sorted(vers.items()):
        print(f"{v}\t{info['path']}")
    return 0


def _ask(question, yes):
    if yes:
        return True
    if not sys.stdin.isatty():
        return False
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


# ---------------------------------------------------------------- where Bunny Hot Key lives
# The program is installed into its own folder, ~/.local/share/BunnyHotKey/app (next to the prefix), and always runs
# from there.  setup-desktop / update copy the app files into it from wherever Bunny Hot Key was cloned or unpacked
# (or from an older install); that source folder is then deleted when it's a plain clone or ZIP, or left untouched -
# and unused - when it holds work that isn't on GitHub (a development checkout).

APP_SKIP = (".git", ".github", ".gitignore", "__pycache__", "tests")     # not part of the installed app


def _data_home():
    return os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")


def _bhk_home():
    return os.path.join(_data_home(), "BunnyHotKey")


def app_dir():
    return os.path.join(_bhk_home(), "app")


def _setup_file():
    return os.path.join(_bhk_home(), "setup.json")


def _load_setup():
    try:
        with open(_setup_file()) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_setup(info):
    os.makedirs(_bhk_home(), exist_ok=True)
    with open(_setup_file(), "w") as fh:
        json.dump(info, fh, indent=1)


def _same(a, b):
    return os.path.realpath(a) == os.path.realpath(b)


def _is_bhk_tree(path):
    """A Bunny Hot Key folder (git clone, ZIP or the installed app) - never site-packages or anything else."""
    return (os.path.isdir(path) and not os.path.islink(path)
            and os.path.isfile(os.path.join(path, "bunnyhotkey", "__main__.py"))
            and os.path.isfile(os.path.join(path, "assets", "bunnyhotkey.svg"))
            and os.path.basename(os.path.realpath(path)) not in ("site-packages", "dist-packages"))


def _protected(path):
    """Folders BHK must never delete, whatever a setting or environment variable says."""
    home = os.path.realpath(os.path.expanduser("~"))
    rp = os.path.realpath(path)
    keep = {home, os.path.realpath(_data_home()), os.path.join(home, ".local"), os.path.join(home, ".config"),
            os.path.join(home, ".cache"), os.path.realpath(os.environ.get("XDG_CONFIG_HOME") or home),
            os.path.realpath(os.environ.get("XDG_RUNTIME_DIR") or "/"), "/tmp", "/var/tmp"}
    keep |= {os.path.join(home, d) for d in ("Desktop", "Documents", "Downloads", "Programs", "Music", "Pictures",
                                             "Videos", "Public", "Templates", "bin", "src")}
    if rp == "/" or rp in keep:
        return True
    if (home + os.sep).startswith(rp + os.sep):          # home itself or one of its parents
        return True
    return rp.count(os.sep) < 2                          # /usr, /opt, /etc ...


def _rmtree(path, looks_right, what):
    """Delete a folder BHK made, after checking it really is that folder.  Returns True when it's gone."""
    if not os.path.lexists(path):
        return True
    if os.path.islink(path):
        print(f"Not deleting {path}: it is a symbolic link (remove it yourself if it is BHK's).")
        return False
    if _protected(path) or not looks_right(path):
        print(f"Not deleting {path}: it doesn't look like {what}.")
        return False
    shutil.rmtree(path, ignore_errors=True)
    return not os.path.exists(path)


def _unsaved_work(root):
    """Why moving/deleting `root` could lose something: uncommitted changes or commits that aren't on GitHub.
    '' for ZIP installs and git checkouts that match their upstream."""
    if not os.path.isdir(os.path.join(root, ".git")):
        return ""
    if not shutil.which("git"):
        return "it is a git checkout (git isn't installed to check it for local changes)"
    if _git("status", "--porcelain", root=root, check=False).stdout.strip():
        return "it has uncommitted changes"
    r = _git("rev-list", "--count", "@{upstream}..HEAD", root=root, check=False)
    if r.returncode:
        return "its branch doesn't track a GitHub branch"
    if r.stdout.strip() not in ("", "0"):
        return f"it has {r.stdout.strip()} commit(s) that aren't pushed"
    return ""


BUILD_FILE = ".bhk-build"            # in the installed app: which commit it is and when that was made


def _build_stamp(root):
    """{"commit", "time"} of a Bunny Hot Key folder: from git for a checkout, else from the installed app's stamp."""
    if os.path.isdir(os.path.join(root, ".git")) and shutil.which("git"):
        r = _git("log", "-1", "--format=%H %ct", root=root, check=False).stdout.split()
        if len(r) == 2:
            return {"commit": r[0], "time": int(r[1])}
    try:
        with open(os.path.join(root, BUILD_FILE)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _write_stamp(root, stamp):
    if stamp:
        with open(os.path.join(root, BUILD_FILE), "w") as fh:
            json.dump(stamp, fh)


def _install_app(root):
    """Put the app files of the Bunny Hot Key folder `root` into ~/.local/share/BunnyHotKey/app and return that path.
    An existing install is updated (never downgraded to an older commit).  Never falls back to running from `root`:
    if the install can't be put in place, nothing changes and bhk stops."""
    dest = app_dir()
    if _same(root, dest):
        return dest
    if not _is_bhk_tree(root):
        raise SystemExit(f"bhk: {root} doesn't look like a Bunny Hot Key folder")
    if (os.path.realpath(dest) + os.sep).startswith(os.path.realpath(root) + os.sep):
        raise SystemExit(f"bhk: {root} contains {dest}; clone or unpack Bunny Hot Key somewhere else")
    if os.path.lexists(dest) and not _is_bhk_tree(dest):
        raise SystemExit(f"bhk: {dest} exists and isn't a Bunny Hot Key install; move it away first")
    why = _unsaved_work(dest) if os.path.lexists(dest) else ""
    if why:
        raise SystemExit(f"bhk: {dest} is a git checkout and {why}; move it away first")
    stamp = _build_stamp(root)
    if os.path.lexists(dest):
        have = _build_stamp(dest)
        name = lambda st: st.get("commit", "")[:7] or "unknown version"
        if have.get("time") and stamp.get("time") and stamp["time"] < have["time"] and \
                stamp.get("commit") != have.get("commit"):
            print(f"Bunny Hot Key is already installed in {dest} with a newer version ({name(have)}); keeping it.")
            _remove_source(root)
            return dest
        print(f"Bunny Hot Key is already installed in {dest}; updating it ({name(have)} -> {name(stamp)}).")
    new, old = dest + ".new", dest + ".old"
    for d in (new, old):
        if os.path.lexists(d):
            _rmtree(d, lambda p: True, "a leftover Bunny Hot Key install folder")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        shutil.copytree(root, new, symlinks=True, ignore=shutil.ignore_patterns(*APP_SKIP))
        _write_stamp(new, stamp)
    except OSError as e:
        shutil.rmtree(new, ignore_errors=True)
        raise SystemExit(f"bhk: couldn't copy Bunny Hot Key into {dest} ({e}); nothing was changed")
    if os.path.lexists(dest):
        os.rename(dest, old)
    os.rename(new, dest)
    if os.path.lexists(old):
        shutil.rmtree(old, ignore_errors=True)
    print(f"Installed Bunny Hot Key into {dest}.")
    _remove_source(root)
    return dest


def _parent_running_from(root):
    """PID of the bhk process that started this one when it runs from `root` (an older `bhk update` calls the new
    setup-desktop and still needs its folder afterwards), else 0."""
    pid = os.getppid()
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            argv = fh.read().split(b"\0")
        with open(f"/proc/{pid}/environ", "rb") as fh:
            env = dict(e.split(b"=", 1) for e in fh.read().split(b"\0") if b"=" in e)
    except OSError:
        return 0
    if b"bunnyhotkey" not in argv:
        return 0
    paths = env.get(b"PYTHONPATH", b"").decode(errors="replace").split(":")
    return pid if any(p and _same(p, root) for p in paths) else 0


def _remove_source(root):
    """Delete the folder Bunny Hot Key was installed from, unless it holds work that isn't on GitHub."""
    why = _unsaved_work(root)
    if why:
        print(f"Left {root} untouched because {why}; bhk doesn't use it.")
        return
    if _protected(root) or not _is_bhk_tree(root):
        return
    parent = _parent_running_from(root)
    if parent:
        code = ("import os, shutil, sys, time\npid, root = int(sys.argv[1]), sys.argv[2]\n"
                "for _ in range(3000):\n"
                "    try:\n        st = open(f'/proc/{pid}/stat').read().rpartition(')')[2].split()[0]\n"
                "    except OSError:\n        break\n"
                "    if st == 'Z':\n        break\n    time.sleep(0.2)\n"
                "if os.path.isfile(os.path.join(root, 'bunnyhotkey', '__main__.py')):\n"
                "    shutil.rmtree(root, ignore_errors=True)\n")
        subprocess.Popen([sys.executable, "-I", "-c", code, str(parent), root], cwd="/", start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"Removing {root} (the old install) as soon as the running bhk update finishes.")
    elif _rmtree(root, _is_bhk_tree, "a Bunny Hot Key clone"):
        print(f"Removed {root} (the copy you cloned or unpacked); it is no longer needed.")


def _launcher_root():
    """The folder the current ~/.local/bin/bhk runs Bunny Hot Key from (an older install may be anywhere)."""
    try:
        with open(_launcher_path(), errors="replace") as fh:
            m = re.search(r'PYTHONPATH="([^"$]+)', fh.read(4096))
    except OSError:
        return ""
    return m.group(1) if m else ""


def _launcher_path():
    return os.path.join(os.path.expanduser("~"), ".local", "bin", "bhk")


def _is_our_launcher(path):
    try:
        with open(path, errors="replace") as fh:
            return "-m bunnyhotkey" in fh.read(4096)
    except OSError:
        return False


def _is_our_desktop_file(path):
    try:
        with open(path, errors="replace") as fh:
            return "Name=Bunny Hot Key" in fh.read(4096)
    except OSError:
        return False


def _write_launcher(root):
    launcher = _launcher_path()
    os.makedirs(os.path.dirname(launcher), exist_ok=True)
    tmp = launcher + ".bhk-new"
    with open(tmp, "w") as fh:
        fh.write(f'#!/bin/sh\nexport PYTHONPATH="{root}${{PYTHONPATH:+:$PYTHONPATH}}"\n'
                 f'exec {sys.executable} -m bunnyhotkey "$@"\n')
    os.chmod(tmp, 0o755)
    os.replace(tmp, launcher)          # never a half-written launcher
    return launcher


def _desktop_files():
    """Everything setup-desktop writes outside the BHK folder (the launcher is listed first)."""
    data = _data_home()
    files = [_launcher_path(),
             os.path.join(data, "applications", "bunnyhotkey.desktop"),
             os.path.join(data, "mime", "packages", "bunnyhotkey.xml"),
             os.path.join(data, "icons", "hicolor", "scalable", "apps", "bunnyhotkey.svg")]
    files += [os.path.join(data, "icons", "hicolor", f"{s}x{s}", "apps", "bunnyhotkey.png")
              for s in (16, 32, 48, 64, 128, 256)]
    return data, files


def _refresh_desktop_db(data):
    cmds = [["update-mime-database", os.path.join(data, "mime")],
            ["update-desktop-database", os.path.join(data, "applications")]]
    # only refresh an icon cache that already exists: a new one in ~/.local/share/icons would go stale and hide
    # icons other programs install there later
    if os.path.exists(os.path.join(data, "icons", "hicolor", "icon-theme.cache")):
        cmds.append(["gtk-update-icon-cache", "-f", "-t", os.path.join(data, "icons", "hicolor")])
    for cmd in cmds:
        if shutil.which(cmd[0]):
            subprocess.run(cmd, capture_output=True)


def _prune_desktop_dirs(data, files):
    """After uninstall: folders setup-desktop's files lived in, when nothing else is in them any more."""
    mime = os.path.join(data, "mime")
    packages = os.path.join(mime, "packages")
    if os.path.isdir(packages) and not os.listdir(packages) and not os.path.islink(mime):
        shutil.rmtree(mime, ignore_errors=True)        # with no packages left it only holds the generated database
    apps = os.path.join(data, "applications")
    if os.path.isdir(apps) and set(os.listdir(apps)) <= {"mimeinfo.cache"}:
        shutil.rmtree(apps, ignore_errors=True)
    stops = {os.path.realpath(data), os.path.realpath(os.path.expanduser("~"))}
    for f in files[1:]:                # not ~/.local/bin: login shells only add it to PATH when it exists
        d = os.path.dirname(f)
        while os.path.realpath(d) not in stops and d != os.path.dirname(d):
            try:
                os.rmdir(d)                            # fails (and stops) at the first folder that isn't empty
            except OSError:
                break
            d = os.path.dirname(d)


MIME = "text/x-autohotkey"


def _mimeapps_files():
    cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return [os.path.join(cfg, "mimeapps.list"), os.path.join(_data_home(), "applications", "mimeapps.list")]


def _forget_association(remove_if_empty=False):
    """Take bunnyhotkey.desktop out of mimeapps.list (xdg-mime default put it there) without touching anything
    else in the file."""
    for path in _mimeapps_files():
        try:
            with open(path) as fh:
                lines = fh.read().splitlines(keepends=True)
        except OSError:
            continue
        out, changed = [], False
        for line in lines:
            key, sep, val = line.partition("=")
            if sep and not line.lstrip().startswith(("#", "[")) and "bunnyhotkey.desktop" in val:
                apps = [a for a in val.strip().split(";") if a and a != "bunnyhotkey.desktop"]
                changed = True
                if not apps:
                    continue
                line = f"{key}={';'.join(apps)};\n"
            out.append(line)
        if changed and remove_if_empty and path == _mimeapps_files()[0] and \
                all(not ln.strip() or ln.lstrip().startswith(("[", "#")) for ln in out):
            os.remove(path)            # xdg-mime created it for BHK and nothing else is in it
        elif changed:
            tmp = path + ".bhk-new"
            with open(tmp, "w") as fh:
                fh.writelines(out)
            os.replace(tmp, path)


def _bhk_processes():
    """Other running Bunny Hot Key processes of this user (scripts, Dash, Window Spy): (pid, command line)."""
    me = {os.getpid(), os.getppid()}
    home = os.path.expanduser("~").encode()
    out = []
    for name in os.listdir("/proc"):
        if not name.isdigit() or int(name) in me:
            continue
        try:
            if os.stat(f"/proc/{name}").st_uid != os.getuid():
                continue
            with open(f"/proc/{name}/cmdline", "rb") as fh:
                argv = fh.read().decode(errors="replace").split("\0")
        except OSError:
            continue
        if not any(a == "-m" and b == "bunnyhotkey" for a, b in zip(argv, argv[1:])):
            continue
        try:                           # only this home's BHK (a test install under another HOME is left alone)
            with open(f"/proc/{name}/environ", "rb") as fh:
                env = dict(e.split(b"=", 1) for e in fh.read().split(b"\0") if b"=" in e)
            if env.get(b"HOME", home).decode(errors="replace") != home.decode():
                continue
        except OSError:
            pass
        out.append((int(name), " ".join(a for a in argv if a)))
    return out


def _running(pid):
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().rpartition(")")[2].split()[0] != "Z"     # a zombie has exited, it's just not reaped
    except (OSError, IndexError):
        return False


def _stop_scripts():
    """Ask every running BHK script to exit (SIGTERM runs its OnExit and lets go of keys, grabs and the modifier
    map).  Returns the ones still running after a few seconds."""
    import signal
    import time
    procs = _bhk_processes()
    if not procs:
        return []
    print(f"Stopping {len(procs)} running Bunny Hot Key script(s)...")
    for pid, _ in procs:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        alive = [p for p in procs if _running(p[0])]
        if not alive:
            return []
        time.sleep(0.2)
    return alive


def _autostart_entries():
    """Login items scripts created with FileCreateShortcut into A_Startup that run BHK or an .ahk file."""
    cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(cfg, "autostart")
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        p = os.path.join(d, n)
        if not n.endswith(".desktop") or not os.path.isfile(p):
            continue
        try:
            with open(p, errors="replace") as fh:
                exec_ = next((ln[5:] for ln in fh.read().splitlines() if ln.startswith("Exec=")), "")
        except OSError:
            continue
        if "bunnyhotkey" in exec_ or _launcher_path() in exec_ or ".ahk" in exec_.lower():
            out.append(p)
    return out


def uninstall_self(args):
    """bhk uninstall [--purge] [--yes] [--force]: stop running scripts, then remove the launcher, menu entry, icons, .ahk file
    type and its association, the program and BHK's runtime files.  --purge also deletes the prefix (installed
    AutoHotkey versions, emulated registry, C: drive); --yes answers yes to every question."""
    yes = "--yes" in args or "-y" in args
    force = "--force" in args
    purge = "--purge" in args or yes
    left = _stop_scripts()
    if left:
        print("These Bunny Hot Key processes didn't exit; close them (or reboot) and run bhk uninstall again:")
        for pid, cmd in left:
            print(f"  {pid}  {cmd}")
        print("Nothing was removed.")
        return 1
    data, files = _desktop_files()
    removed = 0
    for f in files:
        if not os.path.lexists(f):
            continue
        if f == files[0] and not _is_our_launcher(f) or f == files[1] and not _is_our_desktop_file(f):
            print(f"Leaving {f}: it isn't Bunny Hot Key's.")
            continue
        os.remove(f)
        removed += 1
    setup = _load_setup()
    _forget_association(remove_if_empty=setup.get("mimeapps_existed") is False)
    prev = setup.get("previous_default")
    if prev and prev != "bunnyhotkey.desktop" and shutil.which("xdg-mime"):
        subprocess.run(["xdg-mime", "default", prev, MIME], capture_output=True)
    _refresh_desktop_db(data)
    _prune_desktop_dirs(data, files)
    print(f"Removed the bhk launcher, menu entry, icons and .ahk file type ({removed} files).")

    auto = _autostart_entries()
    if auto:
        print("These login items start AutoHotkey scripts with Bunny Hot Key:\n" + "".join(f"  {a}\n" for a in auto))
        if _ask("Remove them too (they can't run without Bunny Hot Key)?", False):     # yours: never by --yes
            for a in auto:
                os.remove(a)
            print(f"Removed {len(auto)} login item(s).")
        else:
            print("Kept them.")

    # runtime files (single-instance locks, IPC sockets, named mutexes, the running-object table)
    uid = os.getuid()
    run = os.environ.get("XDG_RUNTIME_DIR")
    for d in ([os.path.join(run, "bunnyhotkey"), os.path.join(run, f"bhk-sync-{uid}")] if run else
              [f"/tmp/bunnyhotkey-{uid}", f"/tmp/bhk-sync-{uid}"]):
        if os.path.isdir(d) and not os.path.islink(d) and os.stat(d).st_uid == uid:
            shutil.rmtree(d, ignore_errors=True)
    import glob
    import tempfile as _tf
    for f in glob.glob(os.path.join(_tf.gettempdir(), "bhk-*")):
        try:                           # temp files scripts left (captured bitmaps, beeps, downloads)
            if not os.path.islink(f) and os.stat(f).st_uid == uid:
                shutil.rmtree(f, ignore_errors=True) if os.path.isdir(f) else os.remove(f)
        except OSError:
            pass

    home = _bhk_home()
    root = os.environ.get("BHK_PREFIX") or os.path.join(home, "prefix")
    if os.path.isdir(root) and (purge or _ask(f"Also delete the BHK prefix {root} "
                                              "(installed AutoHotkey versions, emulated registry, C: drive)?", yes)):
        # the prefix only ever holds drive_c, the registry and versions.json; anything else in it is not ours
        if _rmtree(root, lambda p: os.path.isdir(os.path.join(p, "drive_c")), "a Bunny Hot Key prefix"):
            print(f"Deleted {root}")
    lib = os.path.join(home, "Lib")          # your own #Include library: only deleted when you answer yes yourself
    if os.path.isdir(lib) and os.listdir(lib) and _ask(f"Also delete your script library {lib}?", False):
        _rmtree(lib, lambda p: True, "the BHK script library")
    elif os.path.isdir(lib) and not os.listdir(lib):
        os.rmdir(lib)

    # the installed program; a Bunny Hot Key folder this command was started from somewhere else (a development
    # checkout) only when you say so - and work that isn't on GitHub never goes with --yes alone, only with --force
    gone = _rmtree(app_dir(), _is_bhk_tree, "a Bunny Hot Key install")
    if not _same(ROOT, app_dir()) and _is_bhk_tree(ROOT):
        why = _unsaved_work(ROOT)
        if why:
            if force or _ask(f"Also delete {ROOT}? It is a git checkout and {why}.", False):
                _rmtree(ROOT, _is_bhk_tree, "Bunny Hot Key")
            else:
                print(f"Kept {ROOT} because {why}.")
        elif _ask(f"Also delete the Bunny Hot Key folder {ROOT}?", yes):
            _rmtree(ROOT, _is_bhk_tree, "Bunny Hot Key")
    for leftover in (app_dir() + ".old", app_dir() + ".new", _setup_file()):
        if os.path.isdir(leftover):
            _rmtree(leftover, _is_bhk_tree, "an old Bunny Hot Key install")
        elif os.path.isfile(leftover):
            os.remove(leftover)
    try:
        os.rmdir(home)                 # only when nothing of the user's is left in it
    except OSError:
        pass
    print("Bunny Hot Key is uninstalled." if gone else f"Couldn't delete {app_dir()}; delete it to finish uninstalling.")
    if os.path.isdir(home):
        print(f"Kept {home}: {', '.join(sorted(os.listdir(home)))}")
    return 0


REPO = "BittyBunnyBytes/BunnyHotKey"


def _git(*a, check=True, root=None):
    return subprocess.run(["git", "-C", root or ROOT, *a], capture_output=True, text=True, check=check)


def update(args):
    """bhk update: move an older install to ~/.local/share/BunnyHotKey/app, then pull the latest Bunny Hot Key from
    GitHub (git checkouts) or download and unpack it (ZIP installs), and refresh the desktop integration."""
    from . import __version__ as old
    integrated = _is_our_launcher(_launcher_path())
    before_commit = _build_stamp(ROOT).get("commit", "")[:7]
    root = _install_app(ROOT)          # an older install outside ~/.local moves into BHK's own folder first
    if integrated:
        _write_launcher(root)
    if os.path.isdir(os.path.join(root, ".git")) and shutil.which("git"):
        if _git("status", "--porcelain", "--untracked-files=no", root=root).stdout.strip() and "--force" not in args:
            raise SystemExit(f"bhk: {root} has local changes; commit or stash them first (or: bhk update --force)")
        before = _git("rev-parse", "HEAD", root=root).stdout.strip()
        r = _git("pull", "--ff-only", root=root, check=False)
        if r.returncode:
            raise SystemExit(f"bhk: git pull failed:\n{r.stderr.strip()}")
        after = _git("rev-parse", "HEAD", root=root).stdout.strip()
        if before == after:
            print(f"Bunny Hot Key is up to date ({old}, {after[:7]}).")
        else:
            log = _git("log", "--oneline", f"{before}..{after}", root=root).stdout.strip()
            print(f"Updated {before[:7]} -> {after[:7]}:\n{log}")
    else:
        branch = next((a for a in args if not a.startswith("-")), "main")
        if not re.fullmatch(r"[\w.-]+(/[\w.-]+)*", branch) or ".." in branch:
            raise SystemExit(f"bhk: not a branch name: {branch}")
        try:
            latest = _get_json(f"https://api.github.com/repos/{REPO}/commits/{branch}")["sha"]
        except Exception:
            latest = ""
        if latest and latest == _build_stamp(root).get("commit") and "--force" not in args:
            print(f"Bunny Hot Key is up to date ({old}, {latest[:7]}).")
        else:
            _update_from_tarball(root, branch)
    sys.stdout.flush()
    if integrated:
        subprocess.run([sys.executable, "-m", "bunnyhotkey", "setup-desktop"], cwd=root,
                       env={**os.environ, "PYTHONPATH": root})
    after = _build_stamp(root).get("commit", "")[:7]
    if after and after != before_commit:
        print(f"Bunny Hot Key is now at {after}" + (f" (was {before_commit})." if before_commit else "."))
    return 0


def _update_from_tarball(root, branch):
    """Unpack the branch next to `root`, check it, then swap the folders, so a failed download or a full disk never
    leaves a half-updated install.  Files you added inside the folder are kept."""
    import tarfile
    url = f"https://codeload.github.com/{REPO}/tar.gz/refs/heads/{branch}"
    print(f"Downloading {url}")
    parent = os.path.dirname(os.path.realpath(root))
    new, old = root + ".new", root + ".old"
    for d in (new, old):
        if os.path.lexists(d):
            _rmtree(d, lambda p: True, "a leftover Bunny Hot Key update folder")
    with tempfile.TemporaryDirectory(dir=parent, prefix=".bhk-update-") as tmp:
        arc = os.path.join(tmp, "bhk.tar.gz")
        with urllib.request.urlopen(url, timeout=60) as resp, open(arc, "wb") as fh:
            shutil.copyfileobj(resp, fh)
        with tarfile.open(arc) as tf:
            tf.extractall(tmp, filter="data")
            commit = tf.pax_headers.get("comment", "")        # GitHub names the commit in the archive header
        src = next((os.path.join(tmp, d) for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))), "")
        if not _is_bhk_tree(src):
            raise SystemExit("bhk: the download doesn't look like Bunny Hot Key; nothing was changed")
        shutil.copytree(root, new, symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
        for name in os.listdir(src):           # the release replaces its own files; anything else you added stays
            if name in APP_SKIP:
                continue
            dst = os.path.join(new, name)
            if os.path.isdir(dst) and not os.path.islink(dst):
                shutil.rmtree(dst)
            elif os.path.lexists(dst):
                os.remove(dst)
            shutil.move(os.path.join(src, name), dst)
        _write_stamp(new, {"commit": commit, "time": int(__import__("time").time())})
    if not _is_bhk_tree(new):
        _rmtree(new, lambda p: True, "a Bunny Hot Key update folder")
        raise SystemExit("bhk: the update didn't unpack completely; nothing was changed")
    os.rename(root, old)
    os.rename(new, root)
    shutil.rmtree(old, ignore_errors=True)
    print(f"Installed the latest {branch} into {root}.")


def uninstall(args):
    if not args or args[0].startswith("-") or args[0].lower() in ("bhk", "self", "bunnyhotkey"):
        return uninstall_self([a for a in args if a.startswith("-")])
    vers = installed_versions()
    info = vers.pop(args[0], None)
    if info is None:
        raise SystemExit(f"bhk: {args[0]} is not installed")
    base = os.path.realpath(ahk_dir())
    path = os.path.realpath(info.get("path") or "")
    if path.startswith(base + os.sep) and os.path.basename(path) not in ("UX", "Lib"):
        shutil.rmtree(path, ignore_errors=True)
    else:
        print(f"Not deleting {info.get('path')}: it isn't inside {ahk_dir()}.")
    save_versions(vers)
    print(f"Removed AutoHotkey {args[0]}")
    return 0


def _run_ux(script, args):
    path = os.path.join(ahk_dir(), "UX", script)
    if not os.path.exists(path):
        alt = [os.path.join(i["path"], script) for i in installed_versions().values()]
        path = next((p for p in alt if os.path.exists(p)), path)
    if not os.path.exists(path):
        raise SystemExit(f"bhk: {script} not found - run 'bhk install' first")
    return subprocess.call([sys.executable, "-m", "bunnyhotkey", path, *args], cwd=ROOT)


def _ux_path(script):
    path = os.path.join(ahk_dir(), "UX", script)
    if not os.path.exists(path):
        alt = [os.path.join(i["path"], script) for i in installed_versions().values()]
        path = next((p for p in alt if os.path.exists(p)), path)
    return path if os.path.exists(path) else None


def launch_dash():
    """BHK started without a script (from its icon): open AutoHotkey's Dash, as AutoHotkey64.exe does.
    The Dash is part of the official AutoHotkey release; offer to install it if it isn't there yet."""
    if _ux_path("ui-dash.ahk") is None:
        import tempfile
        ask = ('r := MsgBox("AutoHotkey\'s Dash (new scripts, help, Window Spy, editor and launch settings) comes '
               'with the official AutoHotkey release.`n`nDownload and install it now?", "Bunny Hot Key", '
               '"YesNo Iconi")\nExitApp(r = "Yes" ? 0 : 1)\n')
        with tempfile.NamedTemporaryFile("w", suffix=".ahk", delete=False) as fh:
            fh.write(ask)
        try:
            if subprocess.call([sys.executable, "-m", "bunnyhotkey", "--no-tray", fh.name], cwd=ROOT) != 0:
                return 0
        finally:
            os.unlink(fh.name)
        if install([]) != 0 or _ux_path("ui-dash.ahk") is None:
            return 1
    return _run_ux("ui-dash.ahk", [])


def new_script(args):
    name = args[0] if args else "New Script"
    if not name.lower().endswith(".ahk"):
        name += ".ahk"
    if os.path.exists(name):
        raise SystemExit(f"bhk: {name} already exists")
    with open(name, "w") as fh:
        fh.write("#Requires AutoHotkey v2.0\n#SingleInstance Force\n\n")
    print(f"Created {name}")
    return 0


def setup_desktop(args):
    """bhk setup-desktop: install Bunny Hot Key into ~/.local/share/BunnyHotKey/app (see _install_app), then add the
    bhk launcher, icons, the .ahk file type and the menu entry.  Everything it writes outside BHK's folder is listed
    in _desktop_files() for bhk uninstall."""
    data, files = _desktop_files()
    launcher = files[0]
    # every refusal comes before anything is copied or deleted
    if os.path.lexists(launcher) and not _is_our_launcher(launcher) and "--force" not in args:
        raise SystemExit(f"bhk: {launcher} already exists and isn't Bunny Hot Key's; move it away or pass --force")
    previous = _launcher_root() if _is_our_launcher(launcher) else ""
    root = _install_app(ROOT)
    if previous and not _same(previous, root) and not _same(previous, ROOT) and _is_bhk_tree(previous):
        print(f"Found an older Bunny Hot Key install in {previous}.")
        _remove_source(previous)       # an older install elsewhere: replaced by this one
    setup = _load_setup()
    if "previous_default" not in setup and shutil.which("xdg-mime"):
        prev = subprocess.run(["xdg-mime", "query", "default", MIME], capture_output=True, text=True).stdout.strip()
        setup["previous_default"] = prev if prev != "bunnyhotkey.desktop" else ""
    if "mimeapps_existed" not in setup:
        setup["mimeapps_existed"] = os.path.exists(_mimeapps_files()[0])
    setup["root"] = root
    _save_setup(setup)
    _write_launcher(root)
    for size in (16, 32, 48, 64, 128, 256):
        d = os.path.join(data, "icons", "hicolor", f"{size}x{size}", "apps")
        os.makedirs(d, exist_ok=True)
        shutil.copy(os.path.join(root, "assets", f"bunnyhotkey-{size}.png"), os.path.join(d, "bunnyhotkey.png"))
    sd = os.path.join(data, "icons", "hicolor", "scalable", "apps")
    os.makedirs(sd, exist_ok=True)
    shutil.copy(os.path.join(root, "assets", "bunnyhotkey.svg"), os.path.join(sd, "bunnyhotkey.svg"))
    mime = os.path.join(data, "mime", "packages")
    os.makedirs(mime, exist_ok=True)
    # sub-class-of text/plain: text editors keep offering to open .ahk files
    with open(os.path.join(mime, "bunnyhotkey.xml"), "w") as fh:
        fh.write('<?xml version="1.0"?>\n<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">\n'
                 f'  <mime-type type="{MIME}">\n    <comment>AutoHotkey script</comment>\n'
                 '    <sub-class-of type="text/plain"/>\n'
                 '    <icon name="bunnyhotkey"/>\n    <glob pattern="*.ahk"/>\n  </mime-type>\n</mime-info>\n')
    apps = os.path.join(data, "applications")
    os.makedirs(apps, exist_ok=True)
    with open(os.path.join(apps, "bunnyhotkey.desktop"), "w") as fh:
        fh.write(f"[Desktop Entry]\nType=Application\nName=Bunny Hot Key\nComment=Run AutoHotkey v2 scripts on Linux\n"
                 f"Exec={launcher} %f\nIcon=bunnyhotkey\nMimeType={MIME};\nTerminal=false\n"
                 f"Categories=Utility;\n")
    _refresh_desktop_db(data)
    if shutil.which("xdg-mime"):
        os.makedirs(os.path.dirname(_mimeapps_files()[0]), exist_ok=True)   # xdg-mime silently fails without it
        subprocess.run(["xdg-mime", "default", "bunnyhotkey.desktop", MIME], capture_output=True)
    print(f"Installed launcher {launcher}, icon, .ahk file type and menu entry (Bunny Hot Key is in {root}).")
    return 0


def doctor(args):
    from .backends import detect

    class _R:
        options = {}
    print(f"Prefix:        {prefix_root()}")
    print(f"AHK installs:  {', '.join(sorted(installed_versions())) or 'none (bhk install)'}")
    print(f"Session:       {os.environ.get('XDG_SESSION_TYPE', '?')}  DISPLAY={os.environ.get('DISPLAY', '')}  "
          f"WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY', '')}")
    print(f"Input backend: {detect(_R())}")
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa: F401
        gtk = "yes"
    except (ImportError, ValueError):
        gtk = "no  (install PyGObject + GTK 3 -> Gui, MsgBox, InputBox, ToolTip, tray)"
    print(f"GTK 3:         {gtk}")
    for tool in ("wine", "zenity", "kdialog", "notify-send", "wpctl", "xclip", "wl-copy"):
        print(f"{tool + ':':15}{'yes' if shutil.which(tool) else 'no'}")
    return 0


def command(cmd, args, options):
    if cmd == "install":
        return install(args)
    if cmd in ("versions", "list"):
        return versions(args)
    if cmd == "uninstall":
        return uninstall(args)
    if cmd == "update":
        return update(args)
    if cmd == "dash":
        return _run_ux("ui-dash.ahk", args)
    if cmd == "windowspy":
        return _run_ux("WindowSpy.ahk", args)
    if cmd == "launcher":
        return _run_ux("launcher.ahk", args)
    if cmd == "new":
        return new_script(args)
    if cmd == "setup-desktop":
        return setup_desktop(args)
    if cmd == "doctor":
        return doctor(args)
    raise SystemExit(f"bhk: unknown command {cmd}")
