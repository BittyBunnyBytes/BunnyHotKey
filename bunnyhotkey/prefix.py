"""The BHK prefix: a Wine-like home for installed AutoHotkey versions, drive_c and the registry.

Layout (default ~/.local/share/BunnyHotKey/prefix, override with BHK_PREFIX):
  drive_c/Program Files/AutoHotkey/<version>/   official AHK release files (bhk install)
  drive_c/Program Files/AutoHotkey/UX/          the AHK launcher/dash scripts (from the newest install)
  drive_c/users/<user>/                          -> mapped to the real home folders by files.host_path
  registry.json                                  emulated registry (HKCU/HKLM)
  versions.json                                  installed versions and their source/sha256
"""
from __future__ import annotations

import json
import os


def prefix_root() -> str:
    p = os.environ.get("BHK_PREFIX")
    if not p:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
        p = os.path.join(base, "BunnyHotKey", "prefix")
    os.makedirs(os.path.join(p, "drive_c"), exist_ok=True)
    return p


def ahk_dir() -> str:
    return os.path.join(prefix_root(), "drive_c", "Program Files", "AutoHotkey")


def versions_file() -> str:
    return os.path.join(prefix_root(), "versions.json")


def installed_versions() -> dict:
    try:
        with open(versions_file()) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_versions(v: dict):
    with open(versions_file(), "w") as fh:
        json.dump(v, fh, indent=1)


def lib_dirs(script_dir: str) -> list[str]:
    """#Include <Lib> search order: script Lib, user Lib, standard Lib (like AHK)."""
    docs = os.path.join(os.path.expanduser("~"), "Documents", "AutoHotkey", "Lib")
    out = [os.path.join(script_dir, "Lib"), docs,
           os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "BunnyHotKey", "Lib"),
           os.path.join(ahk_dir(), "Lib")]
    return out


def write_hashes():
    """UX/installed-files.csv as AutoHotkey's installer writes it (Hash,Version,Path,Description; MD5, paths
    relative to the install dir): the UX scripts find installed versions, their help files and updates by it."""
    import hashlib
    from .lib.win32shell import pe_string
    root = ahk_dir()
    if not os.path.isdir(os.path.join(root, "UX")):
        return
    rows = ["Hash,Version,Path,Description"]
    for ver, info in sorted(installed_versions().items()):
        d = info.get("path", "")
        for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            low = name.lower()
            if not (low.startswith("autohotkey") and low.endswith((".exe", ".chm"))):
                continue
            f = os.path.join(d, name)
            with open(f, "rb") as fh:
                md5 = hashlib.md5(fh.read()).hexdigest().upper()
            desc = pe_string(f, "FileDescription") if low.endswith(".exe") else ""
            rel = os.path.relpath(f, root).replace("/", "\\")
            rows.append(f'{md5},{ver},"{rel}","{desc}"')
    with open(os.path.join(root, "UX", "installed-files.csv"), "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write("\n".join(rows) + "\n")
