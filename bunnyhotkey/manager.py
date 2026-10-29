"""bhk install / versions / uninstall / dash / windowspy / launcher / new / setup-desktop / doctor.

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


def uninstall(args):
    if not args:
        raise SystemExit("usage: bhk uninstall VERSION")
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
        import tkinter  # noqa: F401
        tk = "yes"
    except ImportError:
        tk = "no  (sudo pacman -S tk  -> Gui, MsgBox, InputBox, ToolTip)"
    print(f"tkinter:       {tk}")
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
