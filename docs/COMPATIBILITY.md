# Compatibility with real-world AutoHotkey v2 code

Tested 2026-10-28 by loading and compiling (`bhk --validate`) every `.ahk` file in
seven widely used AutoHotkey v2 repositories. Validation runs BHK's full
loader: continuation sections, `#Include` resolution, parsing, scope analysis
and compilation. It doesn't execute the scripts.

| Repository | Files | Load OK |
|---|---:|---:|
| [thqby/ahk2_lib](https://github.com/thqby/ahk2_lib) | 105 | 105 |
| [jNizM/ahk-scripts-v2](https://github.com/jNizM/ahk-scripts-v2) | 51 | 51 |
| [Descolada/AHK-v2-libraries](https://github.com/Descolada/AHK-v2-libraries) | 36 | 33 |
| [Descolada/UIA-v2](https://github.com/Descolada/UIA-v2) | 32 | 32 |
| [Descolada/OCR](https://github.com/Descolada/OCR) | 13 | 13 |
| [G33kDude/cJson.ahk](https://github.com/G33kDude/cJson.ahk) (with submodules) | 8 | 8 |
| [TheArkive/JXON_ahk2](https://github.com/TheArkive/JXON_ahk2) | 1 | 1 |
| **Total** | **246** | **243** |

The 3 that fail `#Include` files that aren't in the repository (`ImagePut.ahk`,
`Acc.ahk`, and `..\UIA-v2\Lib\UIA.ahk` from a sibling checkout). Real AutoHotkey
reports the same load error for them.

Language fixes found by this corpus (all covered by `tests/scripts/parser.ahk`):
- `} else {`, `} catch … {` and `} finally {` lines were joined with the next line.
- Assigning to `this`, as in `this := other`.
- Variadic index arguments: `obj[args*]`.
- Compound assignment in declarations: `global x += 1`.
- Directives inside class bodies, such as `#DllLoad`.
- `#Include %A_LineFile%\..\file` and single-quoted include paths.

Loading isn't the same as running. Scripts built on COM (UIA, WebView2,
`ComObject`) or on Win32 calls outside the DllCall table load fine but raise a
clear error when they reach those calls.

Reproduce with `tests/validate_corpus.sh`.
