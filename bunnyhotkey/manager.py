"""bhk install / versions / uninstall / update / dash / windowspy / launcher / new / setup-desktop / doctor.

Installs official AutoHotkey v2 releases (github.com/AutoHotkey/AutoHotkey) into the
BHK prefix, verifying each download against the SHA-256 digest GitHub publishes.
"""
from __future__ import annotations

import hashlib
import json
import os
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
    return tag.lstrip("v"), zips[0]


def install(args):
    target = args[0] if args else "latest"
    if os.path.isfile(target) and target.lower().endswith(".zip"):
        path = target
        ver = os.path.basename(target).replace("AutoHotkey_", "").replace(".zip", "")
        digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
        source = os.path.abspath(target)
    elif os.path.isfile(target):
        raise SystemExit("bhk: pass the release .zip (or a version number); setup .exe files are not unpacked")
    else:
        ver, asset = _release(target)
        print(f"Downloading AutoHotkey {ver} ({asset['name']})...")
        tmpdir = tempfile.mkdtemp(prefix="bhk-")
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


def _desktop_files():
    """Everything setup-desktop writes outside the BHK folder."""
    home = os.path.expanduser("~")
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    files = [os.path.join(home, ".local", "bin", "bhk"),
             os.path.join(data, "applications", "bunnyhotkey.desktop"),
             os.path.join(data, "mime", "packages", "bunnyhotkey.xml"),
             os.path.join(data, "icons", "hicolor", "scalable", "apps", "bunnyhotkey.svg")]
    files += [os.path.join(data, "icons", "hicolor", f"{s}x{s}", "apps", "bunnyhotkey.png")
              for s in (16, 32, 48, 64, 128, 256)]
    return data, files


def _refresh_desktop_db(data):
    for cmd in (["update-mime-database", os.path.join(data, "mime")],
                ["update-desktop-database", os.path.join(data, "applications")],
                ["gtk-update-icon-cache", "-f", "-t", os.path.join(data, "icons", "hicolor")]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, capture_output=True)


def uninstall_self(args):
    """bhk uninstall [--purge] [--yes]: remove the launcher and desktop integration. --purge also deletes the
    prefix; --yes answers yes to every question (prefix and the BHK folder itself)."""
    yes = "--yes" in args or "-y" in args
    purge = "--purge" in args
    data, files = _desktop_files()
    removed = [f for f in files if os.path.exists(f)]
    for f in removed:
        os.remove(f)
    _refresh_desktop_db(data)
    print(f"Removed the bhk launcher, menu entry, icons and .ahk file type ({len(removed)} files).")
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    default_dir = os.path.join(base, "BunnyHotKey")
    root = os.environ.get("BHK_PREFIX") or os.path.join(default_dir, "prefix")
    if os.path.isdir(root) and (purge or _ask(f"Also delete the BHK prefix {root} "
                                              "(installed AutoHotkey versions, emulated registry, C: drive)?", yes)):
        shutil.rmtree(default_dir if root == os.path.join(default_dir, "prefix") else root, ignore_errors=True)
        print(f"Deleted {root}")
    dirty = os.path.isdir(os.path.join(ROOT, ".git")) and shutil.which("git") and \
        _git("status", "--porcelain", check=False).stdout.strip()
    if dirty:
        print(f"Note: {ROOT} has uncommitted changes.")
    if _ask(f"Also delete the Bunny Hot Key folder {ROOT}?", yes):
        shutil.rmtree(ROOT, ignore_errors=True)
        print(f"Deleted {ROOT}. Bunny Hot Key is uninstalled.")
    else:
        print(f"The Bunny Hot Key folder is still at {ROOT}; delete it to finish uninstalling.")
    return 0


REPO = "BittyBunnyBytes/BunnyHotKey"


def _git(*a, check=True):
    return subprocess.run(["git", "-C", ROOT, *a], capture_output=True, text=True, check=check)


def update(args):
    """bhk update: pull the latest Bunny Hot Key from GitHub (git checkouts) or download and unpack it (zip
    installs), then refresh the desktop integration if it was set up."""
    from . import __version__ as old
    if os.path.isdir(os.path.join(ROOT, ".git")) and shutil.which("git"):
        if _git("status", "--porcelain", "--untracked-files=no").stdout.strip() and "--force" not in args:
            raise SystemExit(f"bhk: {ROOT} has local changes; commit or stash them first (or: bhk update --force)")
        before = _git("rev-parse", "HEAD").stdout.strip()
        r = _git("pull", "--ff-only", check=False)
        if r.returncode:
            raise SystemExit(f"bhk: git pull failed:\n{r.stderr.strip()}")
        after = _git("rev-parse", "HEAD").stdout.strip()
        if before == after:
            print(f"Bunny Hot Key is up to date ({old}, {after[:7]}).")
            return 0
        log = _git("log", "--oneline", f"{before}..{after}").stdout.strip()
        print(f"Updated {before[:7]} -> {after[:7]}:\n{log}")
    else:
        branch = args[0] if args and not args[0].startswith("-") else "main"
        url = f"https://codeload.github.com/{REPO}/tar.gz/refs/heads/{branch}"
        print(f"Downloading {url}")
        import tarfile
        with tempfile.TemporaryDirectory() as tmp:
            arc = os.path.join(tmp, "bhk.tar.gz")
            with urllib.request.urlopen(url, timeout=60) as resp, open(arc, "wb") as fh:
                shutil.copyfileobj(resp, fh)
            with tarfile.open(arc) as tf:
                tf.extractall(tmp, filter="data")
            src = next(os.path.join(tmp, d) for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d)))
            if not os.path.isfile(os.path.join(src, "bunnyhotkey", "__main__.py")):
                raise SystemExit("bhk: the download doesn't look like Bunny Hot Key; nothing was changed")
            for name in os.listdir(src):
                dst = os.path.join(ROOT, name)
                if os.path.isdir(dst) and not os.path.islink(dst):
                    shutil.rmtree(dst)
                if os.path.isdir(os.path.join(src, name)):
                    shutil.copytree(os.path.join(src, name), dst)
                else:
                    shutil.copy2(os.path.join(src, name), dst)
        print(f"Installed the latest {branch} into {ROOT}.")
    sys.stdout.flush()
    if os.path.exists(_desktop_files()[1][0]):
        subprocess.run([sys.executable, "-m", "bunnyhotkey", "setup-desktop"], cwd=ROOT)
    new = subprocess.run([sys.executable, "-c", "import bunnyhotkey; print(bunnyhotkey.__version__)"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    print(f"Bunny Hot Key {old} -> {new or '?'}")
    return 0


def uninstall(args):
    if not args or args[0].startswith("-") or args[0].lower() in ("bhk", "self", "bunnyhotkey"):
        return uninstall_self([a for a in args if a.startswith("-")])
    vers = installed_versions()
    info = vers.pop(args[0], None)
    if info is None:
        raise SystemExit(f"bhk: {args[0]} is not installed")
    shutil.rmtree(info["path"], ignore_errors=True)
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
    home = os.path.expanduser("~")
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    bindir = os.path.join(home, ".local", "bin")
    os.makedirs(bindir, exist_ok=True)
    launcher = os.path.join(bindir, "bhk")
    with open(launcher, "w") as fh:
        fh.write(f'#!/bin/sh\nexport PYTHONPATH="{ROOT}${{PYTHONPATH:+:$PYTHONPATH}}"\nexec {sys.executable} -m bunnyhotkey "$@"\n')
    os.chmod(launcher, 0o755)
    for size in (16, 32, 48, 64, 128, 256):
        d = os.path.join(data, "icons", "hicolor", f"{size}x{size}", "apps")
        os.makedirs(d, exist_ok=True)
        shutil.copy(os.path.join(ROOT, "assets", f"bunnyhotkey-{size}.png"), os.path.join(d, "bunnyhotkey.png"))
    sd = os.path.join(data, "icons", "hicolor", "scalable", "apps")
    os.makedirs(sd, exist_ok=True)
    shutil.copy(os.path.join(ROOT, "assets", "bunnyhotkey.svg"), os.path.join(sd, "bunnyhotkey.svg"))
    mime = os.path.join(data, "mime", "packages")
    os.makedirs(mime, exist_ok=True)
    with open(os.path.join(mime, "bunnyhotkey.xml"), "w") as fh:
        fh.write('<?xml version="1.0"?>\n<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">\n'
                 '  <mime-type type="text/x-autohotkey">\n    <comment>AutoHotkey script</comment>\n'
                 '    <icon name="bunnyhotkey"/>\n    <glob pattern="*.ahk"/>\n  </mime-type>\n</mime-info>\n')
    apps = os.path.join(data, "applications")
    os.makedirs(apps, exist_ok=True)
    with open(os.path.join(apps, "bunnyhotkey.desktop"), "w") as fh:
        fh.write(f"[Desktop Entry]\nType=Application\nName=Bunny Hot Key\nComment=Run AutoHotkey v2 scripts on Linux\n"
                 f"Exec={launcher} %f\nIcon=bunnyhotkey\nMimeType=text/x-autohotkey;\nTerminal=false\n"
                 f"Categories=Utility;\n")
    for cmd in (["update-mime-database", os.path.join(data, "mime")], ["update-desktop-database", apps],
                ["xdg-mime", "default", "bunnyhotkey.desktop", "text/x-autohotkey"],
                ["gtk-update-icon-cache", "-f", "-t", os.path.join(data, "icons", "hicolor")]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, capture_output=True)
    print(f"Installed launcher {launcher}, icon, .ahk file type and menu entry.")
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
