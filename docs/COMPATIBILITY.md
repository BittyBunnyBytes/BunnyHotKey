# Compatibility with real-world AutoHotkey v2 code

Tested 2026-10-28 (re-run after the Gui and built-in work) by loading and compiling (`bhk --validate`) every `.ahk` file in
seven widely used AutoHotkey v2 repositories. Validation runs BHK's full
loader: continuation sections, `#Include` resolution, parsing, scope analysis
and compilation. It doesn't execute the scripts.

| Repository | Files | Load OK |
|---|---:|---:|
| [thqby/ahk2_lib](https://github.com/thqby/ahk2_lib) (with submodules) | 120 | 119 |
| [Descolada/AHK-v2-libraries](https://github.com/Descolada/AHK-v2-libraries) (with Acc-v2, OCR, UIA-v2 submodules) | 87 | 85 |
| [jNizM/ahk-scripts-v2](https://github.com/jNizM/ahk-scripts-v2) | 51 | 51 |
| [Descolada/UIA-v2](https://github.com/Descolada/UIA-v2) | 32 | 32 |
| [Descolada/OCR](https://github.com/Descolada/OCR) | 13 | 13 |
| [G33kDude/cJson.ahk](https://github.com/G33kDude/cJson.ahk) (with submodules) | 33 | 26 |
| [TheArkive/JXON_ahk2](https://github.com/TheArkive/JXON_ahk2) | 1 | 1 |
| **Total** | **337** | **327** |

None of the 10 that don't load are valid standalone AutoHotkey v2 scripts. Real AutoHotkey v2 rejects them too:
- 6 are AutoHotkey **v1** files in cJson's MCL/Yunit submodule (`Gui, Yunit:Font, …`).
- 1 is a code-generation template full of `$Placeholders` (MCL's `StandaloneTemplate.ahk`).
- 2 `#Include` files that aren't in the repository (`ImagePut.ahk`, `Acc.ahk`).
- 1 extends a class defined in another file (`winrt/struct.ahk`) and only loads as part of its library.

Language fixes found by this corpus (covered by `tests/scripts/parser.ahk` and `builtins_native.ahk`):
- `} else {`, `} catch … {` and `} finally {` lines were joined with the next line.
- Assigning to `this`, as in `this := other`.
- Variadic index arguments: `obj[args*]`.
- Compound assignment in declarations: `global x += 1`.
- Directives inside class bodies, such as `#DllLoad`.
- `#Include %A_LineFile%\..\file` and single-quoted include paths.
- A by-reference argument with the maybe operator, `&var?` (UIA.ahk; 32 scripts include it). The reference
  overrides the maybe-read, as in `script.cpp`'s `SYM_REF` handling.

Loading isn't the same as running. Scripts built on COM (UIA, WebView2,
`ComObject`) or on Win32 calls outside the DllCall table load fine but raise a
clear error when they reach those calls.

Reproduce with `tests/validate_corpus.sh`.
