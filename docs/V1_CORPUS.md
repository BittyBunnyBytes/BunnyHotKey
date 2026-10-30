# AutoHotkey v1 script corpus

**319 of 327** public AutoHotkey v1 scripts load and compile in BHK's v1 frontend (`bhk --validate`: continuation sections, translation, parsing, compilation; the scripts aren't run).

The corpus holds the v1 scripts from these repositories that pass a conservative safety filter (`tools/v1_corpus_audit.py`: no process launching, file writes, registry, network, clipboard, native memory, window control, dynamic code, `#Include` or input outside hotkeys), so it is mostly libraries, functions, classes and hotkey scripts:

- https://github.com/Drugoy/Autohotkey-scripts-.ahk
- https://github.com/GorvGoyl/Autohotkey-Scripts-Windows
- https://github.com/Ixiko/AHK-libs-and-classes-collection
- https://github.com/Paris/AutoHotkey-Scripts
- https://github.com/ahkscript/ASPDM
- https://github.com/aviaryan/autohotkey-scripts
- https://github.com/camerb/AHKs
- https://github.com/denolfe/AutoHotkey
- https://github.com/jNizM/AHK_Scripts
- https://github.com/tariqporter/Gdip
- https://github.com/tdalon/ahk

Rebuild and measure with `python3 tools/v1_corpus.py fetch` and `python3 tools/v1_corpus.py measure`; the scripts aren't stored here because their licences vary (`tests/v1corpus/manifest.json` lists each source).

## Scripts that don't load

| Script | Error |
|---|---|
| AHK-libs-and-classes-collection: `libs/a-f/AhkDllFunctions.ahk` | line 19: Unexpected token |
| AHK-libs-and-classes-collection: `libs/a-f/Decimal2Fraction.ahk` | line 92: Unexpected token |
| AHK-libs-and-classes-collection: `AHK_V2/JSON_AHk_Parsing_for_ahk2.ahk` | line 115: Unexpected "}" |
| AHK-libs-and-classes-collection: `libs/g-n/Math.ahk` | line 890: Unexpected token |
| AHK-libs-and-classes-collection: `classes/class_Linear.ahk` | line 1: Unknown class. |
| AHK-libs-and-classes-collection: `classes/class_OGdip-Geometry.ahk` | line 123: Unknown class. |
| AHK-libs-and-classes-collection: `classes/class_Regex (2).ahk` | line 6: Unexpected token in class body |
| AHKs: `thirdParty/lib/Regex.ahk` | line 6: Unexpected token in class body |
