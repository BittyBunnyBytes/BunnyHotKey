# Compatibility with real-world AutoHotkey v2 code

Tested 2026-10-29 (re-run after the full v1 frontend) by loading and compiling (`bhk --validate`) every `.ahk` file in
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
| [G33kDude/cJson.ahk](https://github.com/G33kDude/cJson.ahk) (with submodules) | 33 | 31 |
| [TheArkive/JXON_ahk2](https://github.com/TheArkive/JXON_ahk2) | 1 | 1 |
| **Total** | **337** | **332** |

None of the 5 that don't load are valid standalone AutoHotkey scripts. Real AutoHotkey rejects them too:
- 1 is a code-generation template full of `$Placeholders` (MCL's `StandaloneTemplate.ahk`).
- 1 is MCL's `RunTests.ahk`, which includes v1 Yunit files and v2 MCL files in one script.
- 2 `#Include` files that aren't in the repository (`ImagePut.ahk`, `Acc.ahk`).
- 1 extends a class defined in another file (`winrt/struct.ahk`) and only loads as part of its library.

5 of cJson's MCL/Yunit files are AutoHotkey **v1** (`Gui, Yunit:Font, …`). They load through the v1 frontend
(`docs/V1.md`): auto-detection guesses the version from the main file and, if that version doesn't load, tries the other.

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
