# Parity with AutoHotkey v2

![Parity chart](../assets/parity.svg)

## How it's measured
- **Built-in functions:** every name in AutoHotkey v2.0.31's own function table
  (`script.cpp` BIF table, `lib/functions.h`, `g_act`), 345 entries.
  - *Full* means BHK implements the documented behaviour.
  - *Partial* means it exists but returns a fixed or approximate result, usually because the Windows concept has no Linux equivalent.
  - *Missing* means it raises a clear "Windows-only" error.
  - Result: **271 full, 63 partial, 11 missing (88%)**.
- **Language:** the regression suite (`tests/run.py`), with expected outputs
  checked line by line against the C++ source, plus 246 real-world scripts
  (`docs/COMPATIBILITY.md`): **243 load (99%)**.
- **Other areas:** feature lists from AutoHotkey's documentation, with each
  feature counted as full, partial or missing.
- Regenerate the chart with `python3 tools/parity_chart.py`.

## What's missing or left to do
| Area | Status | What's left |
|---|---|---|
| COM / ActiveX | ❌ missing | `ComObject`, `ComObjActive`, `ComObjGet`, `ComCall`, `ComObj*` (11 functions). COM is Windows-only; a D-Bus bridge could cover some uses. |
| Wayland input | ❌ dropped for now | Hotkeys and Send need X11. A portal-based backend (GlobalShortcuts / RemoteDesktop) is the path forward. |
| Gui | 🟡 65% | Missing control types: TreeView, Tab/Tab2/Tab3, UpDown, Hotkey, DateTime, MonthCal, ActiveX, Custom. `SetFont`, `BackColor`, `Opt` styles and control colours are accepted but ignored. |
| Win32 controls | 🟡 61% | `ControlGetText/SetText/GetItems/Choose*`, `Edit*`, `ListViewGetContent`, `StatusBarGetText` and similar. Linux toolkits don't expose other apps' controls like Win32 does; AT-SPI accessibility could fill this in. |
| DllCall | 🟡 partial | About 40 common Win32 APIs are emulated, and calls into Linux `.so` libraries work. Arbitrary Windows DLLs and calls by address don't. |
| Hotkeys (X11) | 🟢 90% | A hotkey on a bare modifier (`LWin::`) and hotstring end characters can't be suppressed under X11's grab model. `#InputLevel` and `SendLevel` are simplified. |
| Window functions | 🟢 95% | `WinGetText`, `WinSetRegion`, `WinSetStyle`/`ExStyle` (except always-on-top) and transparent colours are partial. |
| Files / Drives | 🟢 95% | Drive serial, label, file system and CD status are fixed values. |
| Tray | 🟢 95% | Per-item menu icons (`Menu.SetIcon`) and menu colours aren't drawn. Verified live on XFCE; on Cinnamon through XApp's StatusIconMonitor, the mechanism Cinnamon's tray applet uses. |
| AutoHotkey v2.1-alpha | ⚪ not targeted | Typed properties, structs and `#Module` are v2.1-alpha features. BHK targets v2.0. |
| AutoHotkey v1 | ⚪ out of scope | v1 scripts get a clear message. |
