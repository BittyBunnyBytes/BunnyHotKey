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
