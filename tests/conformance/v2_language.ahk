;; suite: v2
; AutoHotkey v2.0 language semantics and object/flow built-ins (tools/conformance.py).
; Expected values from the v2 docs and the v2.0.31 source.

;; test: variables, concatenation and auto-concat
a := "x", b := 5
out(a b "y" . "z")
;; expect: x5yz

;; test: integer and float arithmetic
out(7 / 2 " " 7 // 2 " " (-7 // 2) " " 2 ** 10 " " 2 ** -1 " " 0.1 + 0.2)
;; expect: 3.5 3 -3 1024 0.5 0.30000000000000004

;; test: integer overflow wraps
out(0x7FFFFFFFFFFFFFFF + 1)
;; expect: -9223372036854775808

;; test: bitwise operators and >>>
out((6 & 3) " " (6 | 3) " " (6 ^ 3) " " (~0) " " (1 << 4) " " (-16 >> 2) " " (-1 >>> 60))
;; expect: 2 7 5 -1 16 -4 15

;; test: comparison and logical operators
out((1 = 1.0) " " ("a" = "A") " " ("a" == "A") " " ("a" != "b") " " (!0) " " (1 && 0) " " (0 || "z"))
;; expect: 1 1 0 1 1 0 z

;; test: ternary, ?? and ??=
x := unset
y := x ?? "default"
z := ""
z ??= "notset"
out(y " [" z "]")
;; expect: default []

;; test: unset variables throw on read
try
    v := neverAssigned
catch UnsetError
    out("UnsetError")
;; expect: UnsetError

;; test: IsSet and maybe operator
f(a?) => IsSet(a) ? "set" : "unset"
out(f() " " f(1))
;; expect: unset set

;; test: string escapes and quotes
out("a`tb`"c'd" 'e"f`'g')
;; expect: a	b"c'de"f'g

;; test: continuation section with Join
s := "
(Join,
one
two
)"
out(s)
;; expect: one,two

;; test: multi-line expression continuation
x := 1
    + 2
    * 3
out(x)
;; expect: 7

;; test: functions: defaults, ByRef, variadic, variadic call
Def(a, b := 2) => a + b
Inc(&n) {
    n++
}
Sum(nums*) {
    t := 0
    for n in nums
        t += n
    return t
}
v := 1
Inc(&v)
arr := [1, 2, 3]
out(Def(1) " " v " " Sum(arr*) " " Sum(4, 5))
;; expect: 3 2 6 9

;; test: closures capture variables
Make() {
    n := 0
    return () => ++n
}
c := Make()
c(), c()
out(c())
;; expect: 3

;; test: nested functions and static
Outer() {
    static count := 0
    Inner() => ++count
    Inner(), Inner()
    return count
}
Outer()
out(Outer())
;; expect: 4

;; test: global and local scope
g := "glob"
ReadG() => g
SetG() {
    global g
    g := "changed"
}
NoG() {
    g := "local"
    return g
}
out(ReadG() " " NoG() " " g)
SetG()
out(g)
;; expect: glob local glob
;; expect: changed

;; test: Func objects, Bind and method references
Add(a, b) => a + b
f := Add
b := Add.Bind(10)
out(f(1, 2) " " b(5) " " f.Name " " f.MinParams " " f.MaxParams " " f.IsVariadic)
;; expect: 3 15 Add 2 2 0

;; test: dynamic variable and function calls
name := "target"
target := "hit"
fn := "StrUpper"
out(%name% " " %fn%("ab"))
;; expect: hit AB

;; test: classes, properties, static members, super
class Animal {
    static Count := 0
    __New(name) {
        this.name := name
        Animal.Count++
    }
    Speak() => this.name " makes a sound"
    Name2 => StrUpper(this.name)
}
class Dog extends Animal {
    Speak() => super.Speak() " (woof)"
}
d := Dog("Rex")
out(d.Speak() " " d.Name2 " " Animal.Count " " Type(d) " " (d is Animal))
;; expect: Rex makes a sound (woof) REX 1 Dog 1

;; test: property get/set and __Item
class Box {
    _v := 0
    V {
        get => this._v
        set => this._v := value * 2
    }
    __Item[k] {
        get => "item " k
    }
}
b := Box()
b.V := 5
out(b.V " " b["x"])
;; expect: 10 item x

;; test: meta-functions __Get, __Set, __Call
class Meta {
    __Get(name, params) => "get " name
    __Call(name, params) => "call " name " " params.Length
}
m := Meta()
out(m.foo " " m.bar(1, 2))
;; expect: get foo call bar 2

;; test: __Enum and for-loops
class Range {
    __New(n) => this.n := n
    __Enum(k) {
        i := 0
        return (&v) => (++i <= this.n) && (v := i, true)
    }
}
s := ""
for v in Range(3)
    s .= v
out(s)
;; expect: 123

;; test: __Delete on release
class D {
    __Delete() => out("deleted")
}
x := D()
x := ""
out("after")
;; expect: deleted
;; expect: after

;; test: DefineProp and GetOwnPropDesc
o := {}
o.DefineProp("p", {get: (*) => "computed"})
o.DefineProp("m", {call: (this, a) => a * 2})
out(o.p " " o.m(4) " " o.HasOwnProp("p") " " o.GetOwnPropDesc("p").HasOwnProp("get"))
;; expect: computed 8 1 1

;; test: object built-ins: ObjOwnPropCount, ObjOwnProps, ObjHasOwnProp
o := {a: 1, b: 2}
s := ""
for k, v in ObjOwnProps(o)
    s .= k v
out(ObjOwnPropCount(o) " " s " " ObjHasOwnProp(o, "a") ObjHasOwnProp(o, "z"))
;; expect: 2 a1b2 10

;; test: ObjGetBase, ObjSetBase, HasBase, IsObject
p := {greet: (this) => "hi"}
o := {}
ObjSetBase(o, p)
out((ObjGetBase(o) = p) " " HasBase(o, p) " " o.greet() " " IsObject(o) IsObject(1))
;; expect: 1 1 hi 10

;; test: HasMethod, GetMethod, HasProp
class K {
    M() => "m"
}
obj := K()
out(HasMethod(obj, "M") " " HasMethod(obj, "Nope") " " GetMethod(obj, "M")(obj) " " HasProp(obj, "base"))
;; expect: 1 0 m 1

;; test: ObjBindMethod
class C {
    Join(a, b) => a "-" b
}
f := ObjBindMethod(C(), "Join", "x")
out(f("y"))
;; expect: x-y

;; test: ObjGetCapacity and ObjSetCapacity
o := {a: 1}
ObjSetCapacity(o, 10)
out(ObjGetCapacity(o) >= 10)
;; expect: 1

;; test: IsSetRef
F(&r) => IsSetRef(&r)
a := 1
out(F(&a) " " F(&b))
;; expect: 1 0

;; test: IsLabel and Goto
Goto Skip
out("not skipped")
Skip:
out(IsLabel("Skip") " " IsLabel("Nope"))
;; expect: 1 0

;; test: Array methods
a := [3, 1, 2]
a.Push(4)
a.InsertAt(1, 0)
r := a.RemoveAt(2)
out(a.Length " " r " " a.Pop() " " a[-1] " " a.Has(1))
;; expect: 4 3 4 2 1

;; test: Array Clone, Delete, Capacity, Default
a := [1, 2]
c := a.Clone()
c[1] := 9
a.Default := "none"
a.Length := 3
out(a[1] " " c[1] " " a[3])
;; expect: 1 9 none

;; test: Map methods, case sensitivity and enumeration
m := Map("b", 2, "a", 1)
m.Set("c", 3)
m.Delete("b")
s := ""
for k, v in m
    s .= k v
out(m.Count " " m.Has("a") " " m.Get("zz", "dflt") " " s " " m.Has("A"))
m2 := Map()
m2.CaseSense := false
m2["X"] := 1
out(m2["x"])
;; expect: 2 1 dflt a1c3 0
;; expect: 1

;; test: Buffer and NumGet
b := Buffer(8, 0xFF)
NumPut("Int", 5, b)
out(b.Size " " NumGet(b, "Int") " " NumGet(b, 4, "UChar"))
;; expect: 8 5 255

;; test: try / catch class / else / finally
try {
    throw ValueError("bad", -1, "extra")
} catch TypeError {
    out("wrong")
} catch ValueError as e {
    out(e.Message " " e.Extra " " Type(e))
} else {
    out("else")
} finally {
    out("finally")
}
try
    x := 1
catch
    out("no")
else
    out("else ran")
;; expect: bad extra ValueError
;; expect: finally
;; expect: else ran

;; test: Error properties and Stack
try
    throw Error("msg")
catch as e
    out(e.Message " " (e.Line > 0) " " (e.Stack != "") " " (e.File != ""))
;; expect: msg 1 1 1

;; test: switch with and without case sensitivity
x := "B"
switch x, false {
    case "a": out("a")
    case "b", "c": out("bc")
    default: out("d")
}
switch {
    case 1 > 2: out("no")
    case 2 > 1: out("yes")
}
;; expect: bc
;; expect: yes

;; test: Loop, While, Until, Break/Continue with labels
s1 := s2 := ""
Loop 3
    s1 .= A_Index
i := 0
while i < 3
    i++
Loop {
    j := A_Index
} until j >= 2
outer:
Loop 3 {
    k := A_Index
    Loop 3 {
        if A_Index = 2
            continue outer
        if k = 3
            break outer
        s2 .= k A_Index " "
    }
}
out(s1 " " i " " j " " Trim(s2))
;; expect: 123 3 2 11 21

;; test: Loop Parse with CSV and delimiters
s := ""
Loop Parse, 'a,"b,c",d', "CSV"
    s .= "[" A_LoopField "]"
Loop Parse, "x y", " "
    s .= A_Index
out(s)
;; expect: [a][b,c][d]12

;; test: Loop Read and Loop Files
s := ""
FileAppend("l1`nl2`n", "conf_r.txt")
Loop Read, "conf_r.txt"
    s .= A_LoopReadLine
DirCreate("conf_d")
FileAppend("", "conf_d\a.txt")
Loop Files, "conf_d\*.txt"
    s .= " " A_LoopFileName " " A_LoopFileExt
FileDelete("conf_r.txt")
DirDelete("conf_d", true)
out(s)
;; expect: l1l2 a.txt txt

;; test: for over Array with index and value
s := ""
for i, v in ["a", "b"]
    s .= i v
out(s)
;; expect: 1a2b

;; test: SetTimer with a function, period and delete
n := 0
Tick() {
    global n
    n++
}
SetTimer(Tick, 10)
Sleep(80)
SetTimer(Tick, 0)
c := n
Sleep(40)
out((c >= 3) " " (c = n))
;; expect: 1 1

;; test: SetTimer one-shot with priority
SetTimer(() => out("once"), -10, 5)
Sleep(60)
;; expect: once

;; test: Critical delays timers
Critical
SetTimer(() => out("timer"), -1)
Sleep(30)
out("first")
Critical("Off")
Sleep(30)
;; expect: first
;; expect: timer

;; test: Thread NoTimers and Interrupt
Thread("NoTimers")
SetTimer(() => out("late"), -1)
Sleep(30)
out("before")
Thread("NoTimers", false)
Sleep(30)
Thread("Interrupt", 0)
;; expect: before
;; expect: late

;; test: OnError handler can suppress an error
OnError(Handler)
Handler(e, mode) {
    out("handled " e.Message)
    return 1
}
x := [].Foo()
out("not reached: return 1 exits the thread")
;; expect: handled This value of type "Array" has no method named "Foo".

;; test: OnExit callback with reason and code
OnExit((reason, code) => out("exit " reason " " code))
ExitApp(3)
;; expect: exit Exit 3

;; test: Persistent keeps the script running until ExitApp
Persistent
SetTimer(() => (out("alive"), ExitApp()), -50)
return
;; expect: alive

;; test: Pause and Suspend toggle state
Suspend(true)
s := A_IsSuspended
Suspend(false)
out(s A_IsSuspended A_IsPaused)
;; expect: 100

;; test: Reload restarts the script
if !FileExist("conf_reload.txt") {
    FileAppend("x", "conf_reload.txt")
    Reload
    Sleep(2000)
}
FileDelete("conf_reload.txt")
out("reloaded")
;; expect: reloaded

;; test: OutputDebug writes to the debugger stream
OutputDebug("dbg")
out("ok")
;; expect: ok

;; test: built-in variables
out(A_PtrSize " " A_IsUnicode " " SubStr(A_AhkVersion, 1, 2) " " (A_TickCount > 0) " " (StrLen(A_Now) = 14) " " A_Space "|" A_Tab "|")
;; expect: 8 1 2. 1 1  |	|

;; test: A_ThisFunc, A_LineNumber, A_ScriptName
F() => A_ThisFunc
SplitPath(A_ScriptFullPath, &nm)
out(F() " " (A_LineNumber > 0) " " (nm = A_ScriptName))
;; expect: F 1 1

;; test: A_Args from the command line is an Array
out(Type(A_Args) " " A_Args.Length)
;; expect: Array 0

;; test: Type of values
out(Type(1) Type(1.0) Type("") Type([]) Type(Map()) Type({}) Type(Buffer(1)) Type(Type))
;; expect: IntegerFloatStringArrayMapObjectBufferFunc

;; test: string comparison of numbers and objects
o := {}
out((o = o) " " ({} = {}) " " ("10" = 10) " " ("abc" = "ABC"))
;; expect: 1 0 1 1

;; test: VarSetStrCapacity and StrPtr
VarSetStrCapacity(&s, 100)
out(VarSetStrCapacity(&s) >= 100)
;; expect: 1

;; test: Hotkey and hotstring definitions load without running
out("loaded")
ExitApp
F12::out("x")
::btw::by the way
;; expect: loaded
