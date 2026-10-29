<p align="center"><img src="assets/bunnyhotkey-128.png" width="96" alt="Bunny Hot Key icon"></p>

# Bunny Hot Key (BHK)

<p align="center">
  <a href="https://ko-fi.com/bittybunnybytes"><img src="https://img.shields.io/badge/Ko--fi-Support%20Bunny%20Hot%20Key-FF5E5B?logo=ko-fi&logoColor=white&style=for-the-badge" alt="Support Bunny Hot Key on Ko-fi"></a>
</p>

> **If Bunny Hot Key saves your AutoHotkey scripts on Linux, please [buy me a coffee on Ko-fi](https://ko-fi.com/bittybunnybytes).**
> Every tip goes into closing the gaps below: more Gui controls, Wayland and COM bridges.

## How close is it to AutoHotkey?

<p align="center"><img src="assets/parity.svg" alt="Parity with AutoHotkey v2 by area: language 99%, built-in functions 88%, Gui 65%, COM and Wayland 0%" width="860"></p>

<!-- parity:summary:start -->
**In short:** the AutoHotkey v2 *language* is essentially complete (99%), and
**88% of its built-in function API** is reproduced (270 full, 63 partial, 11 missing).

**Missing or left to do:**
- **COM/ActiveX:** Windows-only.
- **Wayland input:** dropped for now.
- **Gui:** 8 control types to go (TreeView, Tab, UpDown, Hotkey, DateTime, MonthCal, ActiveX, Custom).
- **Reading other apps' Win32 controls** (`ControlGetText` and similar).
- **Some DllCalls.**

The full breakdown is in [docs/PARITY.md](docs/PARITY.md).
<!-- parity:summary:end -->


Run **AutoHotkey v2** scripts natively on **Linux (X11)**.

BHK is a compatibility layer in the spirit of Wine/Proton, but it doesn't
emulate Windows. It reimplements the AutoHotkey v2 language and runtime in
Python, working directly from the official AutoHotkey v2.0.31 C++ source:
same operator precedence, value rules, error messages, object model, threading
model and Send/hotkey semantics. `docs/ANALYSIS.md` explains how AutoHotkey
works internally and which BHK module mirrors each part.

## Install
```sh
git clone https://github.com/BittyBunnyBytes/BunnyHotKey.git
cd BunnyHotKey
python3 -m bunnyhotkey setup-desktop   # puts `bhk` in ~/.local/bin, icon, .ahk file association
bhk install                            # optional: official AutoHotkey v2 files (Window Spy, Dash, templates)
```
Requirements: Python 3.11+, an X11 session (libX11/libXtst/libXi, standard on
every desktop) and PyGObject with GTK 3 for MsgBox/InputBox/Gui (preinstalled
on most desktops). No pip packages are needed.

## Use
```sh
bhk script.ahk [args...]   # run a script (also: double-click .ahk files after setup-desktop)
bhk --console script.ahk   # errors to the terminal instead of a dialog (like /ErrorStdOut)
bhk --validate script.ahk  # load-time check only
bhk windowspy              # AutoHotkey's own Window Spy (after `bhk install`)
bhk install [VERSION]      # install an official AutoHotkey v2 release into the BHK prefix
bhk versions               # installed versions; #Requires AutoHotkey v2.x picks among them
bhk new NAME               # new script
bhk doctor                 # what BHK can use on this machine
```

## What works
- **Language:** all of AutoHotkey v2.0. Expressions, objects, classes
  (`extends`, `super`, properties, `__Item`, meta-functions), closures,
  fat-arrow functions, ByRef `&`, variadic calls, `try/catch/else/finally`,
  every loop type including `Loop … else`, `switch`, `goto`, continuation
  sections, `#Include <Lib>`, `#HotIf` and the other directives.
- **Library:** all 362 entries in AutoHotkey's built-in function table exist.
  COM functions raise a clear error, since COM is Windows-only.
- **Input (X11):**
  - Hotkeys (modifiers, `~ * $ up`, `a & b`, remaps `a::b`, `#HotIf`) and hotstrings (all options).
  - Send/SendInput/SendText with full syntax, Click, MouseMove and friends.
  - GetKeyState, KeyWait, InputHook.
  - Hotkeys grab only the keys a script defines.
- **Windows:** WinTitle matching (title, `ahk_class`, `ahk_exe`, `ahk_pid`,
  `ahk_id`, `ahk_group`, all match modes), WinActivate, WinMove and the other
  Win* functions, PixelGetColor, PixelSearch and ImageSearch (PNG/BMP).
- **GUI:**
  - MsgBox, InputBox, ToolTip, FileSelect and DirSelect.
  - `Gui()` with Text, Edit, Button, CheckBox, Radio, DropDownList, ComboBox, ListBox, ListView, Slider, Progress, GroupBox, Picture, Link and StatusBar.
  - AHK layout options and events, plus `Menu`.
- **Tray icon, like AutoHotkey on Windows:**
  - Every persistent script gets the pink tray icon, with the script name as its tooltip.
  - The standard menu: **Open** (bold default, double-click), Help, Window Spy, Reload Script, Edit Script, Suspend Hotkeys and Pause Script (both with check marks), Exit.
  - The icon changes while Suspended or Paused.
  - `A_TrayMenu` is fully scriptable (Add, Insert, Delete, Rename, Check, Enable, Default, ClickCount, AddStandard).
  - `A_IconTip`, `A_IconHidden`, `TraySetIcon` and `#NoTrayIcon` work.
  - It uses XApp's StatusIcon, Cinnamon's tray library, on **Cinnamon, XFCE and MATE**. Other X11 trays get a plain XEmbed icon, and AppIndicator covers StatusNotifier-only panels (KDE, GNOME with the AppIndicator extension).
- **Windows compatibility:**
  - `C:\Users\<you>\Desktop` and the other shell folders map to your real folders, `Z:\` is `/`, and other drives live in the prefix.
  - The registry is emulated.
  - Common Win32 `DllCall`s are emulated, and DllCall can call Linux `.so` libraries.
  - Run translates `notepad`, `explorer`, URLs and so on to Linux equivalents.
- **Proof:**
  - `python3 tests/run.py` runs the regression suite. Its expected outputs were checked against the AutoHotkey source.
  - AutoHotkey's own UX scripts load, and Window Spy runs with live data.
  - 243 of 246 scripts from seven popular v2 repositories load (thqby/ahk2_lib, Descolada's libraries, UIA-v2 and OCR, jNizM's scripts, cJson, JXON). The other 3 include files that aren't in their repos. See `docs/COMPATIBILITY.md`, and reproduce with `tests/validate_corpus.sh`.

## Not supported
- **Wayland:** dropped for now. Hotkeys and Send need X11, although XWayland apps still work from an X11 session.
- **AutoHotkey v1 scripts:** BHK targets v2. A v1 `#Requires` gets a clear message.
- **COM/ActiveX, and Windows-only APIs that aren't in the DllCall table.**

## Note for agents
If you are an AI agent trying to use this project, these are the facts you need:
- **Command:** `bhk <script.ahk> [args]`, or `python3 -m bunnyhotkey <script.ahk>` from the repo root with no install. Exit code = the script's `ExitApp` code; 2 = load error.
- **Scripts must be AutoHotkey v2 syntax** (`MsgBox "hi"`, `x := 1`, functions with `()`). v1 syntax (`MsgBox, hi`, `%var%` everywhere) will not load.
- **Headless / CI use:** pass `--console --backend=null`.
  - Errors go to stderr in AutoHotkey's `/ErrorStdOut` format: `file (line) : ==> message` / `     Specifically: extra`.
  - `FileAppend text, "*"` writes to stdout. Use it to get results out of a script.
  - With `--backend=null`, nothing is typed or clicked. Send/Click calls are recorded but not delivered.
- **Real input needs an X11 session** (`DISPLAY` set). Hotkeys and Send then act on the user's live desktop, so don't run input-producing scripts without the user's consent.
- **Validate without running:** `bhk --validate script.ahk` exits 0 if the script loads.
- **Paths:**
  - Windows-style paths in scripts are translated.
  - `A_ScriptDir` and other path variables are Linux paths.
  - The prefix is `~/.local/share/BunnyHotKey/prefix` (override with `BHK_PREFIX`).
- **Where to look in the code:**
  - Parsing: `bunnyhotkey/lexer.py`, `parser.py`.
  - Semantics: `compiler.py`, `runtime.py`, `objects.py`.
  - Built-ins: `bunnyhotkey/lib/*.py`, one `@export`ed Python function per AHK function.
  - Input: `hotkeys.py`, `hotmgr.py`, `backends/x11.py`.
- **Adding a missing Win32 DllCall:** add a handler to the `EMU` table in `bunnyhotkey/lib/dllcall.py`.
- **Tests:** `python3 tests/run.py`. To add one, add `tests/scripts/name.ahk` plus a `name.expected` file holding its exact stdout. `tests/validate_corpus.sh` checks that real-world scripts load.
- **Tray:** shown automatically for persistent scripts. Pass `--no-tray` (or use `#NoTrayIcon`) for background or headless runs. The menu logic is in `bunnyhotkey/lib/tray.py`.

## License
GPL-2.0, the same as AutoHotkey, whose source BHK was derived from. The icon
is AutoHotkey's "H" mark (`resources/icons.svg`) recoloured with a pink gradient.
