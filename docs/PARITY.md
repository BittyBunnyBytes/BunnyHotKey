# Parity with AutoHotkey v2

![Parity chart](../assets/parity.svg)

## How it's measured
- **Built-in functions:** every name in AutoHotkey v2.0.31's own function table
  (`script.cpp` BIF table, `lib/functions.h`, `g_act`; listed in `tools/ahk_builtins.txt`).
  - *Full* means BHK implements the documented behaviour.
  - *Partial* means it exists but returns a fixed or approximate result, usually because the Windows concept has no Linux equivalent.
  - *Missing* means it raises a clear "Windows-only" error.
  - <!-- parity:counts:start -->
Result: **332 full, 3 partial, 9 missing (97%)** of 344 built-ins.
<!-- parity:counts:end -->
- **Language:** the regression suite (`tests/run.py`), with expected outputs
  checked line by line against the C++ source, plus 337 real-world scripts
  (`docs/COMPATIBILITY.md`): **327 of 337 load**; the rest are v1 files or templates.
- **Other areas:** feature lists from AutoHotkey's documentation, with each
  feature counted as full, partial or missing.
- **Updating the chart:** edit `docs/parity.json` (areas, notes, hand-scored
  percentages, the "missing" list), then run `python3 tools/parity_chart.py`.
  - Built-in scores are measured automatically against `tools/ahk_builtins.txt`.
  - That list can be regenerated from an AutoHotkey source checkout with `tools/extract_ahk_builtins.sh`.
  - The script redraws `assets/parity.svg` and rewrites the marked summary blocks in `README.md` and this file.

## What's missing or left to do
| Area | Status | What's left |
|---|---|---|
| COM / ActiveX | ❌ missing | `ComObject`, `ComObjActive`, `ComObjGet`, `ComCall`, `ComObj*` (9 functions), the Gui ActiveX control and `SoundGetInterface`. COM is Windows-only; a D-Bus bridge could cover some uses. |
| Wayland input | ❌ dropped for now | Hotkeys and Send need X11. A portal-based backend (GlobalShortcuts / RemoteDesktop) is the path forward. |
| Gui | 🟢 92% | 21 of 23 control types. ActiveX and Custom host Win32 components. Smaller differences: an UpDown's buddy doesn't show thousands separators, MonthCal `Multi` returns a one-day range, StatusBar parts share one label, and widgets use the GTK theme's metrics, so default control sizes differ slightly from Windows. |
| Win32 controls | 🟡 60% | `Control*`, `Edit*`, `ListViewGetContent`, `StatusBar*`, `WinGetText`, `WinGetControls` and `MenuSelect` are complete for the script's own Gui windows. X11 doesn't expose other programs' widgets, so for those they act on the whole window; AT-SPI accessibility could fill this in. |
| DllCall | 🟡 partial | About 45 common Win32 APIs are emulated (including `EnumWindows`, `SendMessage`, `IsWindow`). Calls into any Linux `.so`, calls by address, `CallbackCreate` trampolines and native pointers work. Arbitrary Windows DLLs don't. |
| Window messages | 🟡 partial | `OnMessage`, `SendMessage` and `PostMessage` work for the script's own windows and controls, and the common Win32 messages (`WM_CLOSE`, `WM_SYSCOMMAND`, `BM_CLICK`, `CB_SETCURSEL`, `WM_SETTEXT`...) are translated. Messages to other processes aren't delivered. |
| Hotkeys (X11) | 🟢 90% | A hotkey on a bare modifier (`LWin::`) and hotstring end characters can't be suppressed under X11's grab model. `#InputLevel` and `SendLevel` are simplified. |
| Window functions | 🟢 97% | `WinSetRegion` and `WinSetTransColor` use the X Shape extension. A colour key is a snapshot of the window's current pixels, so content drawn later isn't keyed. `WinSetStyle`/`ExStyle` only map always-on-top. |
| Files / Drives | 🟢 99% | `DriveGetLabel`, `DriveGetSerial`, `DriveGetType` and `DriveGetFileSystem` read the real mounts. `DriveSetLabel` runs the filesystem's label tool, which usually needs root. |
| Tray | 🟢 95% | Per-item tray menu icons and menu colours aren't drawn (Gui and popup menus do draw them). Verified live on XFCE; on Cinnamon through XApp's StatusIconMonitor, the mechanism Cinnamon's tray applet uses. |
| Diagnostics | 🟢 | `ListVars`, `ListHotkeys` and `KeyHistory` open AutoHotkey-style windows. `ListLines` toggles logging, but BHK doesn't record executed lines. |
| AutoHotkey v2.1-alpha | ⚪ not targeted | Typed properties, structs and `#Module` are v2.1-alpha features. BHK targets v2.0. |
| AutoHotkey v1 | ⚪ out of scope | v1 scripts get a clear message. |
