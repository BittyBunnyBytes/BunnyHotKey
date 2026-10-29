# How AutoHotkey v2 works (from the v2.0.31 source)

Source: the official release tag `v2.0.31` (signed by Lexikos), read from
`~/Programs/AutoHotkey/source-v2.0.31/source`. Every BHK module names the C++
function it mirrors.

## 1. Loading a script (`script.cpp`)
- `Script::LoadIncludedFile` reads the file line by line. `GetLine` trims each
  line, removes `;` comments (they must be at line start or after whitespace;
  `` `; `` escapes them), and handles `/* */` (`*/` may end a line in v2).
- `GetLineContinuation` folds **continuation sections**: a line starting with `(`
  whose options are `Join…`, `LTrim[0]`, `RTrim0`, `Comments`, or `` ` ``. Inside
  a quoted string the section's quote marks become literal. Default join is
  `` `n ``, and default indentation is "smart" (it strips the first line's indent).
- **Continuation by expression**: a line is merged with the next when
  `BalanceExpr` finds unclosed `( [ {`, when it ends with an operator
  (`EndsWithOperator`), or when the next line starts with one (`IsSOLContExpr`,
  except `++`, `--` and `::`). A trailing `{` after `)`, `]`, a control word or a
  property name is OTB, not an object literal.
- `ParseAndAddLine` classifies directives, hotstrings (`:opts:trigger::`), hotkeys
  (valid `Hotkey::TextInterpret` syntax before `::`), labels and statements. A
  command-style call is a name, then whitespace, then something that isn't a
  binary operator (`MsgBox "x"` vs `x - 1`).

## 2. Expressions (`ExpressionToPostfix`, `ExpandExpression`)
- Infix is converted to postfix with the `sPrecedence[]` table (odd values are
  right-associative): `,`6 `:=`7 `?:`11 `??`15 `||`17 `&&`21 `not`25 `is`28
  `= == != !==`30 `< > <= >=`34 `~=`36 concat 38, `|`42 `^`46 `&`50
  `<< >> >>>`54 `+ -`58 `* / //`62 `**`73(right) unary 67, `++/--` 77/82, `.`/call 86.
- Auto-concatenation happens between operands separated by whitespace. `.` is
  concatenation only with whitespace on both sides.
- An assignment binds to the nearest operand on its left (`!x := 1`, `a || b := c`).
- Values are `SYM_STRING`, `SYM_INTEGER` (__int64, wraps) or `SYM_FLOAT`. A
  "numeric string" is a string that `IsNumeric` accepts (whitespace, sign, `0x`
  hex, decimal and exponent).
- Arithmetic on a non-numeric string throws TypeError
  "Expected a Number but got a String.". `/` always yields a float; `//` truncates
  and accepts integers only.
- Equality compares numerically if **at least one side is a pure number** and both
  are numeric; two strings compare as strings (`"1" = "1.0"` is false). `<`/`>` on
  non-numbers throws.
- Float to string is `FTOA`: `%.17g`, with `.0` appended when there is no `.`/`e`.

## 3. Objects (`script_object.cpp`)
- Everything has a base chain: `Any` → `Object` → `Array`/`Map`/`Error`/`Func`…;
  primitives use `String`, `Integer` or `Float.Prototype`.
- Own properties are kept **sorted case-insensitively** (binary search), which is
  why `OwnProps()` enumerates alphabetically.
- A property is a value or a {get, set, call} descriptor. A method call on a
  value property calls the value with `this` as its first parameter.
- `obj.prop[args]` passes args to the property's getter/setter.
- Classes: `Class.Prototype.Call` creates the instance with the nearest native
  constructor, runs `__Init` (instance variable initializers, which first call
  `super.__Init`), then `__New`. Static initializers run on first use.
- Map keys are sorted (integers, then strings, then objects). Float keys become
  strings, and CaseSense defaults to On.

## 4. Execution (`ExecUntil`, `PerformLoop*`)
- One OS thread runs pseudo-threads. Hotkeys, timers and GUI events are messages,
  and a new thread interrupts the current one at a line boundary or during
  Sleep/waits, unless the thread is Critical.
- Each thread starts with the settings the auto-execute section left behind
  (SendMode, TitleMatchMode, …).
- Functions are assume-local. A name that is only read resolves to a global;
  nested functions become closures over outer locals.
- `For` backs up its loop variables and restores them afterwards.
  `Loop`/`For`/`While` may have an `else` that runs on zero iterations.
- Bare `catch` (and a lone `try`) catches only Error objects. `switch` compares
  like `==` unless CaseSense is given.

## 5. Input (`hook.cpp`, `hotkey.cpp`, `keyboard_mouse.cpp`)
- Hotkeys use RegisterHotkey or the low-level keyboard/mouse hook. The hook
  decides per event whether to suppress it, evaluates `#HotIf` (with
  `#HotIfTimeout`), and handles prefix keys (`a & b`), `~`, `*`, `$`, `up`
  and side-specific modifiers.
- Hotstrings are recognized by the hook from typed characters and end
  characters, then erased with backspaces and replaced via Send.
- `SendKeys` parses `^+!#`, `{Key N}`, `{Key down/up}`, `{Blind}`, `{Raw}`,
  `{Text}` and `{U+XXXX}`. It temporarily releases modifiers the user is holding.

## Bunny Hot Key mapping
| AutoHotkey | Bunny Hot Key |
|---|---|
| script.cpp loader | `lexer.py`, `parser.py` |
| ExpressionToPostfix / ExpandExpression | `parser.py` (Pratt, same precedences) + `compiler.py` closures |
| script_object.cpp | `objects.py`, `classes.py`, `lib/core.py` |
| ExecUntil / pseudo-threads | `runtime.py` (`check_interrupts`, `run_thread`, `sleep`) |
| hook.cpp / hotkey.cpp | `hotkeys.py` (HookEngine), `hotmgr.py` (hotstrings, #HotIf) |
| RegisterHotkey / SendInput | `backends/x11.py` (XGrabKey of each defined hotkey, XTest) |
| Gui / MsgBox (script_gui.cpp) | `lib/guiobj.py` + GTK3 helper processes (`gtkgui_helper.py`, `gtkdlg_helper.py`) |
| lib/*.cpp | `lib/*.py` |
| Windows paths/registry | `prefix.py`, `lib/files.py` (drive_c, Z:), `lib/registry.py` |
