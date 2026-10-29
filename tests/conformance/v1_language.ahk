;; suite: v1
; AutoHotkey v1.1 language conformance (tools/v1_conformance.py). One feature per section.
; Expected output follows the v1.1 documentation (Language, Variables, Functions, Objects, Commands).

;; test: literal assignment with %var% deref
name = Bunny
s = Hi %name%, bye
out(s)
;; expect: Hi Bunny, bye

;; test: literal assignment trims (AutoTrim)
s =    padded
out("[" s "]")
;; expect: [padded]

;; test: AutoTrim Off keeps spaces from %A_Space%
AutoTrim, Off
s = %A_Space%x%A_Space%
out("[" s "]")
;; expect: [ x ]

;; test: escape sequences in commands
s = a`tb`,c`;d`%e
out(s)
;; expect: a	b,c;d%e

;; test: continuation section with Join
s =
(Join|
one
two
)
out(s)
;; expect: one|two

;; test: continuation section LTrim and percent sign
x = X
s =
(LTrim
    line %x%
    100`%
)
out(s)
;; expect: line X
;; expect: 100%

;; test: continuation by leading operator
x := 1
    + 2
    . "z"
out(x)
;; expect: 3z

;; test: continuation by leading comma
a := 1
, b := 2
out(a b)
;; expect: 12

;; test: auto-concatenation and .=
a := "x", b := 5
s := a b "y"
s .= "!"
out(s)
;; expect: x5y!

;; test: true division and floor division
out(10 / 4)
out(7 // 2)
out(-7 // 2)
;; expect: 2.500000
;; expect: 3
;; expect: -3

;; test: power operator
out(2 ** 10)
out(2 ** -1)
;; expect: 1024
;; expect: 0.500000

;; test: bitwise operators
out((6 & 3) " " (6 | 3) " " (6 ^ 3) " " (1 << 4) " " (256 >> 2))
;; expect: 2 7 5 16 64

;; test: bitwise-not is 32-bit unsigned for small values
out(~0)
out(~0xF0)
;; expect: 4294967295
;; expect: 4294967055

;; test: numeric literal formatting is kept on direct assignment
x := 1.50
y := 0x1F
out(x " " y " " (x + 0) " " (y + 0))
;; expect: 1.50 0x1F 1.500000 31

;; test: float result uses default format
out(1.5 + 1)
out(3 * 1.0)
;; expect: 2.500000
;; expect: 3.000000

;; test: math on non-numbers yields blank
x := "abc" + 1
out("[" x "]")
;; expect: []

;; test: division by zero yields blank
x := 5 / 0
out("[" x "]")
;; expect: []

;; test: numeric strings with whitespace are numbers
x := " 12 " + 1
out(x)
;; expect: 13

;; test: = compares case-insensitively, == case-sensitively
out(("abc" = "ABC") " " ("abc" == "ABC"))
;; expect: 1 0

;; test: <> and != operators
out((1 <> 2) " " (1 != 1))
;; expect: 1 0

;; test: numeric strings compare as numbers
a = 10
b = 9
out(a > b)
;; expect: 1

;; test: non-numeric strings compare alphabetically
out(("abc" < "abd") " " ("b" > "a"))
;; expect: 1 1

;; test: ternary and short-circuit
x := 0
r := (x && Noisy()) ? "t" : "f"
out(r)
Noisy() {
    out("called")
}
;; expect: f

;; test: legacy If var = value (case-insensitive)
x = abc
if x = ABC
    out("eq")
;; expect: eq

;; test: legacy If compares numerically
x = 05
if x = 5
    out("num")
;; expect: num

;; test: legacy If with %var% on the right
x = a
y = a
if x = %y%
    out("deref")
;; expect: deref

;; test: legacy If blank
x =
if x =
    out("blank")
;; expect: blank

;; test: legacy If <, >, >=, <=
x = 5
if x > 3
    out("gt")
if x <= 5
    out("le")
if x < 2
    out("bad")
;; expect: gt
;; expect: le

;; test: if var between / not between
x = 7
if x between 1 and 10
    out("in")
if x not between 1 and 5
    out("out")
;; expect: in
;; expect: out

;; test: if var between strings
x = cat
if x between blue and red
    out("alpha")
;; expect: alpha

;; test: if var in / not in / contains
x = exe
if x in bat,exe,com
    out("in")
if x not in txt,doc
    out("notin")
if x contains xe,zz
    out("contains")
;; expect: in
;; expect: notin
;; expect: contains

;; test: if var is type
a = 12
b = 1.5
c = abc
d = 0x1F
e := " "
if a is integer
    out("int")
if b is float
    out("float")
if c is alpha
    out("alpha")
if d is xdigit
    out("xdigit")
if d is number
    out("hexnum")
if e is space
    out("space")
if c is not number
    out("notnum")
;; expect: int
;; expect: float
;; expect: alpha
;; expect: xdigit
;; expect: hexnum
;; expect: space
;; expect: notnum

;; test: if var is upper/lower/alnum/digit/time
u = ABC
l = abc
n = a1
g = 123
t = 20240115
if u is upper
    out("upper")
if l is lower
    out("lower")
if n is alnum
    out("alnum")
if g is digit
    out("digit")
if t is time
    out("time")
;; expect: upper
;; expect: lower
;; expect: alnum
;; expect: digit
;; expect: time

;; test: IfEqual family
x = 5
IfEqual, x, 5
    out("eq")
IfNotEqual, x, 6
    out("ne")
IfLess, x, 6
    out("lt")
IfGreaterOrEqual, x, 5
    out("ge")
;; expect: eq
;; expect: ne
;; expect: lt
;; expect: ge

;; test: IfInString / IfNotInString
s = hello world
IfInString, s, wor
    out("has")
IfNotInString, s, xyz
    out("hasnt")
;; expect: has
;; expect: hasnt

;; test: IfExist / IfNotExist / FileExist
FileAppend, x, conf_exist.txt
IfExist, conf_exist.txt
    out("exists")
IfNotExist, nope_nothing.txt
    out("missing")
out(FileExist("conf_exist.txt") != "")
FileDelete, conf_exist.txt
;; expect: exists
;; expect: missing
;; expect: 1

;; test: else with braces on one line
x := 2
if (x = 1) {
    out("one")
} else if (x = 2) {
    out("two")
} else {
    out("other")
}
;; expect: two

;; test: else on the same line as a command
x := 0
if x
    out("yes")
else out("no")
;; expect: no

;; test: Loop count with nested A_Index
Loop, 2
{
    o := A_Index
    Loop, 2
        out(o "." A_Index)
}
;; expect: 1.1
;; expect: 1.2
;; expect: 2.1
;; expect: 2.2

;; test: Loop with variable count and A_Index after loop
n := 3
Loop, %n%
    last := A_Index
out(last " " A_Index)
;; expect: 3 0

;; test: Loop Parse with delimiters and omit chars
Loop, Parse, % " a , b ,c", `,, %A_Space%
    out("[" A_LoopField "]")
;; expect: [a]
;; expect: [b]
;; expect: [c]

;; test: Loop Parse CSV
Loop, Parse, % "x,""y,z"",w", CSV
    out(A_LoopField)
;; expect: x
;; expect: y,z
;; expect: w

;; test: Loop Parse characters
Loop, Parse, % "abc"
    s .= A_LoopField "-"
out(s)
;; expect: a-b-c-

;; test: Loop Read with output file
FileAppend, line1`nline2`n, conf_in.txt
Loop, Read, conf_in.txt, conf_out.txt
    FileAppend, %A_LoopReadLine%!`n
FileRead, s, conf_out.txt
out(StrReplace(s, "`n", "|"))
FileDelete, conf_in.txt
FileDelete, conf_out.txt
;; expect: line1!|line2!|

;; test: Loop Files (legacy and new syntax)
FileCreateDir, conf_dir
FileAppend, a, conf_dir\a.txt
FileAppend, b, conf_dir\b.txt
Loop, conf_dir\*.txt
    n1++
Loop, Files, conf_dir\*.txt, F
    names .= A_LoopFileName " "
Sort, names, D%A_Space%
out(n1 " " Trim(names))
FileRemoveDir, conf_dir, 1
;; expect: 2 a.txt b.txt

;; test: A_LoopFileExt / A_LoopFileSize
FileCreateDir, conf_d2
FileAppend, hello, conf_d2\x.dat
Loop, Files, conf_d2\*
    out(A_LoopFileExt " " A_LoopFileSize)
FileRemoveDir, conf_d2, 1
;; expect: dat 5

;; test: While and Until
i := 0
while (i < 3)
    i++
Loop {
    j++
} Until j >= 4
out(i " " j)
;; expect: 3 4

;; test: For loop over object (sorted keys)
o := {b: 2, a: 1, 10: "ten", 2: "two"}
for k, v in o
    s .= k "=" v " "
out(Trim(s))
;; expect: 2=two 10=ten a=1 b=2

;; test: Break and Continue
Loop, 5 {
    if (A_Index = 2)
        continue
    if (A_Index = 4)
        break
    s .= A_Index
}
out(s)
;; expect: 13

;; test: Break out of a labelled outer loop
outer:
Loop, 3 {
    i := A_Index
    Loop, 3 {
        if (A_Index = 2)
            continue outer
        if (i = 3)
            break outer
        s .= i A_Index " "
    }
}
out(Trim(s))
;; expect: 11 21

;; test: Gosub and Return
Gosub, Sub1
out("back " v)
return
Sub1:
v := "set"
return
;; expect: back set

;; test: Goto
Goto, There
out("skipped")
There:
out("there")
;; expect: there

;; test: label fall-through
Gosub, First
return
First:
out("first")
Second:
out("second")
return
;; expect: first
;; expect: second

;; test: Gosub to a label inside a function
F()
F() {
    Gosub, Inner
    out("after")
    return
    Inner:
    out("inner")
    return
}
;; expect: inner
;; expect: after

;; test: A_ThisLabel and A_ThisFunc
Gosub, MyLabel
G()
return
MyLabel:
out(A_ThisLabel)
return
G() {
    out(A_ThisFunc)
}
;; expect: MyLabel
;; expect: G

;; test: function ByRef and default values
Swap(ByRef a, ByRef b) {
    t := a, a := b, b := t
}
Def(a, b = 2, c := "c") {
    return a b c
}
x := 1, y := 2
Swap(x, y)
out(x y " " Def(1) " " Def(1, 5, 6))
;; expect: 21 12c 156

;; test: variadic function and variadic call
Sum(nums*) {
    for i, n in nums
        t += n
    return t
}
arr := [1, 2, 3]
out(Sum(4, 5) " " Sum(arr*) " [" Sum() "]")
;; expect: 9 6 []

;; test: static variables initialize once
Counter() {
    static n := 10
    n++
    return n
}
Counter()
out(Counter())
;; expect: 12

;; test: functions are local by default
g := "global"
F() {
    return "[" g "]"
}
out(F())
;; expect: []

;; test: global declaration inside function
g := "global"
F() {
    global g
    g .= "!"
    return g
}
out(F() " " g)
;; expect: global! global!

;; test: assume-global function
g := 1
F() {
    global
    g := 2
    h := 3
}
F()
out(g h)
;; expect: 23

;; test: super-global declaration
global SG := "super"
F() {
    return SG
}
out(F())
;; expect: super

;; test: local declaration in assume-global function
x := "outer"
F() {
    global
    local x := "inner"
    return x
}
out(F() " " x)
;; expect: inner outer

;; test: return without a value is blank
F() {
    return
}
out("[" F() "]")
;; expect: []

;; test: recursion
Fact(n) {
    return n <= 1 ? 1 : n * Fact(n - 1)
}
out(Fact(10))
;; expect: 3628800

;; test: dynamic function call and Func object
Add(a, b) {
    return a + b
}
fn := "Add"
f := Func("Add")
out(%fn%(1, 2) " " f.Call(3, 4) " " f.(5, 6) " " f.Name " " f.MaxParams)
;; expect: 3 7 11 Add 2

;; test: Func Bind
Add(a, b) {
    return a + b
}
b := Func("Add").Bind(10)
out(b.Call(5))
;; expect: 15

;; test: function names don't clash with variables
Add(a, b) {
    return a + b
}
Add := 5
out(Add(1, 1) Add)
;; expect: 25

;; test: double deref in expressions
name := "target"
target := "hit"
out(%name%)
;; expect: hit

;; test: pseudo-array via dynamic names
Loop, 3
    Arr%A_Index% := A_Index * 10
out(Arr1 Arr2 Arr3)
i := 2
out(Arr%i%)
;; expect: 102030
;; expect: 20

;; test: StringSplit pseudo-array
StringSplit, p, % "a-b-c", -
out(p0 p1 p3)
;; expect: 3ac

;; test: RegExMatch pseudo-array and named groups
RegExMatch("John 42", "(?P<Name>\w+) (?P<Age>\d+)", m)
out(m " " mName " " mAge " " m1)
;; expect: John 42 John 42 John

;; test: RegExMatch match object mode
RegExMatch("abc123", "O)(?<n>\d+)", mo)
out(mo.Value() " " mo.Pos(1) " " mo.Len() " " mo.n " " mo.Count())
;; expect: 123 4 3 123 1

;; test: RegExReplace count and backreference
s := RegExReplace("a1b2", "(\d)", "<$1>", cnt)
out(s " " cnt)
;; expect: a<1>b<2> 2

;; test: block comments and inline comments
/*
out("hidden")
*/
x := 1 ; comment
out(x)
;; expect: 1

;; test: variable names with special characters
#var := 1, @v := 2, $w := 3, a_b := 4
out(#var @v $w a_b)
;; expect: 1234

;; test: empty and undefined variables are blank
out("[" nothingHere "]")
;; expect: []

;; test: increment of a blank variable
x++
out(x)
;; expect: 1

;; test: compound assignments
x := 10
x += 5
x -= 3
x *= 2
x /= 4
out(x)
x := 7
x //= 2
x |= 8
out(x)
;; expect: 6.000000
;; expect: 11

;; test: EnvAdd, EnvSub, EnvMult, EnvDiv
x = 10
EnvAdd, x, 5
EnvSub, x, 3
EnvMult, x, 2
out(x)
;; expect: 24

;; test: date math with EnvAdd and EnvSub
t = 20240131
t += 1, days
out(t)
d = 20240301
d -= 20240201, days
out(d)
;; expect: 20240201000000
;; expect: 29

;; test: SetFormat Float and Integer Hex
SetFormat, Float, 0.2
x := 1/3
out(x)
SetFormat, IntegerFast, h
y := 255 + 0
out(y)
SetFormat, Integer, H
out(255 + 0)
;; expect: 0.33
;; expect: 0xff
;; expect: 0xFF

;; test: objects: literal, dot and bracket access, case-insensitive keys
o := {Key: 1, "two words": 2}
o.Third := 3
out(o.key o["TWO WORDS"] o.third)
;; expect: 123

;; test: missing keys are blank
o := {}
out("[" o.nope "]")
;; expect: []

;; test: arrays: Push, Pop, Length, MaxIndex, MinIndex
a := [10, 20]
a.Push(30)
p := a.Pop()
out(a.Length() " " a.MaxIndex() " " a.MinIndex() " " p)
;; expect: 2 2 1 30

;; test: Insert, InsertAt, RemoveAt
a := ["a", "c"]
a.InsertAt(2, "b")
a.Insert("d")
r := a.RemoveAt(1)
out(r " " a[1] a[2] a[3] " " a.Length())
;; expect: a bcd 3

;; test: Remove and Delete
o := {a: 1, b: 2, c: 3}
v := o.Delete("b")
o.Remove("c")
out(v " " o.HasKey("a") o.HasKey("b") o.HasKey("c"))
;; expect: 2 100

;; test: Count and Clone
o := {a: 1, b: 2}
c := o.Clone()
c.c := 3
out(o.Count() " " c.Count())
;; expect: 2 3

;; test: multi-dimensional assignment creates objects
x := {}
x[1, 2] := "deep"
out(x[1][2] " " x[1, 2])
;; expect: deep deep

;; test: Object() and Array() functions
o := Object("k", "v")
a := Array(1, 2)
out(o.k a[2] IsObject(o) IsObject("x"))
;; expect: v210

;; test: _NewEnum and Next
o := {x: 1}
e := o._NewEnum()
while e.Next(k, v)
    out(k v)
;; expect: x1

;; test: ObjRawSet and ObjHasKey functions
o := {}
ObjRawSet(o, "k", 5)
out(ObjHasKey(o, "k") o.k)
;; expect: 15

;; test: string methods are not on strings
s := "abc"
out("[" s.Length() "]")
;; expect: []

;; test: class with __New, methods, instance and static vars
class Pt {
    static count := 0
    z := 9
    __New(x, y) {
        this.x := x, this.y := y
        Pt.count++
    }
    Sum() {
        return this.x + this.y + this.z
    }
}
p := new Pt(1, 2)
q := new Pt(3, 4)
out(p.Sum() " " Pt.count " " p.__Class)
;; expect: 12 2 Pt

;; test: inheritance and base.Method()
class A {
    Hi() {
        return "A"
    }
}
class B extends A {
    Hi() {
        return base.Hi() "B"
    }
}
obj := new B
out(obj.Hi() " " (obj.base = B) " " (B.base = A))
;; expect: AB 1 1

;; test: properties with get and set
class Temp {
    _c := 0
    F {
        get {
            return this._c * 9 / 5 + 32
        }
        set {
            this._c := (value - 32) * 5 / 9
            return value
        }
    }
}
t := new Temp
t.F := 212
out(Round(t._c) " " Round(t.F))
;; expect: 100 212

;; test: meta-functions __Get, __Set, __Call
class Meta {
    __Get(k) {
        return "get:" k
    }
    __Call(name, args*) {
        if (name = "Shout")
            return "call:" args[1]
    }
}
m := new Meta
out(m.foo " " m.Shout("hi"))
;; expect: get:foo call:hi

;; test: __Delete runs when the last reference goes
class D {
    __Delete() {
        out("deleted")
    }
}
d := new D
d := ""
out("after")
;; expect: deleted
;; expect: after

;; test: nested classes
class Outer {
    class Inner {
        Name() {
            return "inner"
        }
    }
}
i := new Outer.Inner
out(i.Name())
;; expect: inner

;; test: prototype objects via base
proto := {Greet: Func("Greet")}
Greet(this) {
    return "hi " this.n
}
o := {n: "bob", base: proto}
out(o.Greet())
;; expect: hi bob

;; test: throw Exception and its properties
try
    throw Exception("boom", "What", "Extra")
catch e
    out(e.Message " " e.What " " e.Extra " " (e.Line > 0))
;; expect: boom What Extra 1

;; test: throw any value and finally
try {
    throw 42
} catch v {
    out("caught " v)
} finally {
    out("finally")
}
;; expect: caught 42
;; expect: finally

;; test: ErrorLevel from commands
StringReplace, s, % "aaa", a, b, UseErrorLevel
out(s " " ErrorLevel)
StringGetPos, p, % "abc", z
out(ErrorLevel " " p)
;; expect: bbb 3
;; expect: 1 -1

;; test: built-in variables
out(A_Space "|" A_Tab "|" (StrLen(A_Now) = 14) " " (A_YYYY > 2000) " " A_PtrSize " " A_IsUnicode)
out(SubStr(A_AhkVersion, 1, 3) " " (A_LineNumber > 0) " " (A_TickCount > 0))
;; expect:  |	|1 1 8 1
;; expect: 1.1 1 1

;; test: A_ScriptName and A_ScriptDir
SplitPath, A_ScriptFullPath, n, d
out((n = A_ScriptName) " " (d = A_ScriptDir))
;; expect: 1 1

;; test: EnvSet and EnvGet
EnvSet, CONF_X, fromenv
EnvGet, v, CONF_X
out(v)
;; expect: fromenv

;; test: SubStr and InStr with v1 positions
out(SubStr("abcdef", 0) " " SubStr("abcdef", -1) " " SubStr("abcdef", 2, 3))
out(InStr("abcabc", "b") " " InStr("abcabc", "b", false, 0) " " InStr("ABC", "b", true))
;; expect: f ef bcd
;; expect: 2 5 0

;; test: StrSplit with omit characters
a := StrSplit(" a , b ", ",", " ")
out(a.Length() a[1] a[2])
;; expect: 2ab

;; test: Format
out(Format("{1:05.1f}|{2:-4}|{2:x}|{3:U}", 3.14159, 26, "ab"))
;; expect: 003.1|26  |1a|AB

;; test: Trim family
out("[" Trim("  x  ") "][" LTrim("..x", ".") "][" RTrim("x  ") "]")
;; expect: [x][x][x]

;; test: string commands
s = Hello World
StringLen, n, s
StringLeft, l, s, 3
StringRight, r, s, 3
StringMid, m, s, 7, 3
StringTrimLeft, tl, s, 6
StringUpper, u, s
StringLower, lo, s, T
out(n " " l " " r " " m " " tl " " u " " lo)
;; expect: 11 Hel rld Wor World HELLO WORLD Hello World

;; test: StringGetPos with occurrence options
s = abcabcabc
StringGetPos, p1, s, b, L2
StringGetPos, p2, s, b, R
out(p1 " " p2)
;; expect: 4 7

;; test: StringMid with L direction
s = abcdef
StringMid, m, s, 4, 2, L
out(m)
;; expect: cd

;; test: Transform commands
Transform, a, Mod, 7, 3
Transform, b, Pow, 2, 8
Transform, c, Abs, -5
Transform, d, Chr, 65
Transform, e, HTML, <b>
out(a " " b " " c " " d " " e)
;; expect: 1 256 5 A &lt;b&gt;

;; test: Sort options
s = 3,1,20
Sort, s, N D,
out(s)
t = b`na`nb
Sort, t, U
out(StrReplace(t, "`n", " "))
;; expect: 1,3,20
;; expect: a b

;; test: FormatTime formats
FormatTime, a, 20240115143005, yyyy-MM-dd HH:mm:ss
FormatTime, b, 20240115143005, dddd MMMM d
FormatTime, c, 20240115143005, h:mm tt
out(a " | " b " | " c)
;; expect: 2024-01-15 14:30:05 | Monday January 15 | 2:30 PM

;; test: SplitPath outputs
SplitPath, % "/tmp/dir/file.tar.gz", name, dir, ext, noext
out(name " " dir " " ext " " noext)
;; expect: file.tar.gz /tmp/dir gz file.tar

;; test: IniWrite / IniRead / IniDelete
IniWrite, val, conf.ini, Sec, Key
IniRead, v, conf.ini, Sec, Key
IniRead, d, conf.ini, Sec, Nope, def
IniDelete, conf.ini, Sec, Key
IniRead, g, conf.ini, Sec, Key
out(v " " d " " g)
FileDelete, conf.ini
;; expect: val def ERROR

;; test: FileRead and FileReadLine
FileAppend, one`ntwo`n, conf_r.txt
FileReadLine, l2, conf_r.txt, 2
FileRead, all, conf_r.txt
out(l2 " " StrLen(all))
FileDelete, conf_r.txt
;; expect: two 8

;; test: FileGetSize and FileGetTime
FileAppend, 12345, conf_s.txt
FileGetSize, sz, conf_s.txt
FileGetTime, t, conf_s.txt
out(sz " " StrLen(t))
FileDelete, conf_s.txt
;; expect: 5 14

;; test: Random with range
Random, r, 5, 5
Random, f, 0.0, 1.0
out(r " " (f >= 0 && f <= 1))
;; expect: 5 1

;; test: Chr, Asc, Ord, StrLen, Abs, Round, Mod, Floor, Ceil
out(Chr(66) Asc("A") " " StrLen("abc") Abs(-2) " " Round(2.567, 1) " " Round(1234, -2) " " Mod(-7, 3) " " Floor(-1.5) Ceil(1.2))
;; expect: B65 32 2.6 1200 -1 -22

;; test: math functions return blank for invalid input
out("[" Sqrt(-1) "][" Ln(-1) "][" Log(-1) "]")
;; expect: [][][]

;; test: Max and Min
out(Max(1, 7, 3) Min(4, 2, 9))
;; expect: 72

;; test: SetTimer with a label and negative period
SetTimer, Tick, -10
Sleep, 100
out("done")
return
Tick:
out("tick")
return
;; expect: tick
;; expect: done

;; test: SetTimer Off and Delete
SetTimer, Rep, 10
Sleep, 60
SetTimer, Rep, Off
c := n
Sleep, 50
out(c = n)
return
Rep:
n++
return
;; expect: 1

;; test: OnExit label
OnExit, Bye
out("start")
ExitApp
Bye:
out("bye " A_ExitReason)
ExitApp
;; expect: start
;; expect: bye Exit

;; test: OnExit function
OnExit("Leave")
out("start")
ExitApp
Leave(reason, code) {
    out("leave " reason " " code)
}
;; expect: start
;; expect: leave Exit 0

;; test: #EscapeChar and #CommentFlag
#EscapeChar \
#CommentFlag //
s = a\tb // note
out(s)
;; expect: a	b

;; test: Critical and Thread commands are accepted
Critical
Thread, NoTimers
Critical, Off
out("ok")
;; expect: ok

;; test: Process Exist sets ErrorLevel to a PID
Process, Exist
out(ErrorLevel = DllCall("GetCurrentProcessId"))
;; expect: 1

;; test: VarSetCapacity, NumPut, NumGet, StrPut, StrGet
VarSetCapacity(buf, 16, 0)
NumPut(0x11223344, buf, 0, "UInt")
StrPut("hi", &buf + 4, "UTF-16")
out(NumGet(buf, 0, "UShort") " " StrGet(&buf + 4, "UTF-16"))
;; expect: 13124 hi

;; test: address-of and IsByRef
F(ByRef x) {
    return IsByRef(x)
}
v := 1
out(F(v) F(5) (&v > 0))
;; expect: 101

;; test: IsFunc and IsLabel
Lbl:
F(a, b = 1) {
}
out(IsFunc("F") " " IsFunc("Nope") " " IsLabel("Lbl"))
;; expect: 2 0 1

;; test: Hotkey and hotstring definitions load
out("loaded")
ExitApp
#IfWinActive, ahk_class Nothing
^!F12::out("x")
#IfWinActive
::btw::by the way
F11::
    out("y")
return
;; expect: loaded

;; test: GetKeyState on the null backend
GetKeyState, s, Shift
out(s " " GetKeyState("Shift"))
;; expect: U 0

;; test: Input command times out
Input, k, T0.1 L1
out(ErrorLevel)
;; expect: Timeout

;; test: switch/case (v1.1.31+)
x := "b"
switch x
{
case "a", "b":
    out("ab")
case "c":
    out("c")
default:
    out("other")
}
;; expect: ab

;; test: Loop with an expression count
Loop % 1 + 1
    n := A_Index
out(n)
;; expect: 2

;; test: OTB if with a command on the next line
x := 1
if (x = 1) {
    StringUpper, u, % "ok"
    out(u)
}
;; expect: OK

;; test: multiple statements with commas
a := 1, b := a + 1, c := b * 2
out(a b c)
;; expect: 124

;; test: = stays case-insensitive under StringCaseSense On
StringCaseSense, On
out(("a" = "A") " " ("a" == "A"))
;; expect: 1 0

;; test: StringCaseSense affects legacy If and InStr
StringCaseSense, On
x = abc
if x = ABC
    out("bad")
else
    out("sensitive")
;; expect: sensitive

;; test: ObjBindMethod
class C {
    M(a, b) {
        return a "-" b
    }
}
c := new C
f := ObjBindMethod(c, "M", "x")
out(f.Call("y"))
;; expect: x-y

;; test: class static object and __Init
class K {
    static list := []
    v := 5
}
K.list.Push(1)
k := new K
out(K.list.Length() " " k.v)
;; expect: 1 5

;; test: __New can replace the new object
class R {
    __New() {
        return {replaced: 1}
    }
}
r := new R
out(r.replaced)
;; expect: 1

;; test: base.base chain and IsObject on a class
class P1 {
}
class P2 extends P1 {
}
o := new P2
out((o.base.base = P1) " " IsObject(P2))
;; expect: 1 1

;; test: object keys can be objects
k := {}
o := {}
o[k] := "objkey"
out(o[k])
;; expect: objkey

;; test: integer and string keys
o := {}
o[1] := "int"
o["x"] := "str"
out(o[1] o.x o.HasKey(1))
;; expect: intstr1

;; test: Length and MaxIndex with sparse arrays
a := []
a[3] := "c"
out(a.Length() " " a.MaxIndex() " [" a.MinIndex() "]")
;; expect: 3 3 [3]

;; test: string + string arithmetic
x := "5" + "5"
out(x)
;; expect: 10

;; test: Round without places returns an integer
out(Round(2.5) " " Round(-2.5) " " Round(3.14159, 3))
;; expect: 3 -3 3.142

;; test: SubStr with negative length
out(SubStr("abcdef", 2, -2))
;; expect: bcd

;; test: StrReplace with OutputVarCount and Limit
s := StrReplace("aaaa", "a", "b", n, 2)
out(s " " n)
;; expect: bbaa 2

;; test: RegExMatch with a starting position
p := RegExMatch("a1b2c3", "\d", m, 3)
out(p " " m)
;; expect: 4 2

;; test: RegExMatch options i) and m)
out(RegExMatch("ABC", "i)b") " " RegExMatch("x`nyz", "m)^y"))
;; expect: 2 3

;; test: RegExReplace with a limit and start position
out(RegExReplace("aaaa", "a", "b", c, 2, 2) " " c)
;; expect: abba 2

;; test: Loop Read A_Index
FileAppend, x`ny`n, conf_li.txt
Loop, Read, conf_li.txt
    out(A_Index ":" A_LoopReadLine)
FileDelete, conf_li.txt
;; expect: 1:x
;; expect: 2:y

;; test: FileCopy, FileMove and ErrorLevel
FileAppend, data, conf_c1.txt
FileCopy, conf_c1.txt, conf_c2.txt
e1 := ErrorLevel
FileCopy, conf_c1.txt, conf_c2.txt
e2 := ErrorLevel
FileMove, conf_c2.txt, conf_c3.txt
out(e1 " " e2 " " (FileExist("conf_c3.txt") != "") " " (FileExist("conf_c2.txt") = ""))
FileDelete, conf_c*.txt
;; expect: 0 1 1 1

;; test: FileCreateDir, FileRemoveDir and ErrorLevel
FileCreateDir, conf_x\y
e1 := ErrorLevel
FileRemoveDir, conf_x
e2 := ErrorLevel
FileRemoveDir, conf_x, 1
out(e1 " " e2 " " ErrorLevel " " (FileExist("conf_x") = ""))
;; expect: 0 1 0 1

;; test: FileSetAttrib and FileGetAttrib
FileAppend, x, conf_a.txt
FileSetAttrib, +R, conf_a.txt
FileGetAttrib, a, conf_a.txt
out(InStr(a, "R") > 0)
FileSetAttrib, -R, conf_a.txt
FileDelete, conf_a.txt
;; expect: 1

;; test: SetWorkingDir and A_WorkingDir
d := A_WorkingDir
FileCreateDir, conf_wd
SetWorkingDir, conf_wd
SplitPath, A_WorkingDir, name
out(name)
SetWorkingDir, %d%
FileRemoveDir, conf_wd
;; expect: conf_wd

;; test: FileAppend with encoding and FileEncoding
FileAppend, é, conf_e.txt, UTF-8
FileGetSize, s, conf_e.txt
FileEncoding, UTF-8
FileRead, t, conf_e.txt
out(s " " t)
FileDelete, conf_e.txt
;; expect: 5 é

;; test: FileOpen object
f := FileOpen("conf_fo.txt", "w")
f.WriteLine("one")
f.Write("two")
f.Close()
f := FileOpen("conf_fo.txt", "r")
l1 := f.ReadLine()
rest := f.Read()
f.Close()
out(RTrim(l1, "`n") " " rest)
FileDelete, conf_fo.txt
;; expect: one two

;; test: RunWait exit code in ErrorLevel
RunWait, sh -c "exit 3",, Hide
out(ErrorLevel)
;; expect: 3

;; test: Run with an output PID
Run, sleep 0.2,, Hide, pid
out(pid > 0)
Process, WaitClose, %pid%, 3
;; expect: 1

;; test: DllCall with types
r := DllCall("libc.so.6\abs", "Int", -5, "Int")
out(r)
;; expect: 5

;; test: Exception with a negative What
F() {
    throw Exception("inner", -1)
}
try
    F()
catch e
    out(e.Message " " (e.What != ""))
;; expect: inner 1

;; test: try without catch and catch without a variable
try
    throw 1
out("continued")
try {
    throw 2
} catch {
    out("caught")
}
;; expect: continued
;; expect: caught

;; test: unhandled runtime error in a function call is ignorable
x := {}.Method()
out("[" x "]")
;; expect: []

;; test: ByRef with an object element is passed by value
Inc(ByRef v) {
    v++
}
o := {n: 1}
Inc(o.n)
x := 1
Inc(x)
out(o.n " " x)
;; expect: 1 2

;; test: A_Args and %0% command-line parameters
out(A_Args.Length() " " (0 = 0))
;; expect: 0 1

;; test: ExitApp with an exit code runs OnExit
OnExit("Bye")
ExitApp, 7
Bye(r, c) {
    out(r " " c)
}
;; expect: Exit 7

;; test: Hotkey command with a label
Hotkey, F10, Lbl
Hotkey, F10, Off
out("ok " ErrorLevel)
ExitApp
Lbl:
return
;; expect: ok 0

;; test: A_ThisHotkey in a hotkey label run by Gosub
Gosub, ^F9
ExitApp
^F9::
out("[" A_ThisLabel "]")
return
;; expect: [^F9]

;; test: SetTimer with a function object
SetTimer, % Func("Fn"), -10
Sleep, 80
ExitApp
Fn() {
    out("fn timer")
}
;; expect: fn timer

;; test: SetTimer priority and a label period change
SetTimer, T1, 20, 5
Sleep, 70
SetTimer, T1, Delete
out(n >= 2)
ExitApp
T1:
n++
return
;; expect: 1

;; test: OnMessage registers a function
OnMessage(0x5555, "Handler")
out(IsFunc("Handler") > 0)
Handler(w, l) {
}
;; expect: 1

;; test: RegisterCallback returns an address
cb := RegisterCallback("CB")
out(cb > 0)
CB(a) {
    return a
}
;; expect: 1

;; test: ComObjCreate Scripting.Dictionary
d := ComObjCreate("Scripting.Dictionary")
d.Add("k", "v")
out(d.Item("k") " " d.Count " " d.Exists("k"))
;; expect: v 1 -1

;; test: Format with a v1 float default
SetFormat, Float, 0.3
x := 1.0 + 1
out(x " " A_FormatFloat)
;; expect: 2.000 0.3

;; test: Integer overflow wraps at 64 bits
out(0x7FFFFFFFFFFFFFFF + 1)
;; expect: -9223372036854775808

;; test: Asc and Chr with Unicode
out(Asc("é") " " Chr(0x263A))
;; expect: 233 ☺

;; test: Sort with a callback function
s := "b,a,c"
Sort, s, D, F Rev
out(s)
Rev(a, b) {
    return a < b ? 1 : a > b ? -1 : 0
}
;; expect: c,b,a

;; test: Gosub from a timer keeps A_ThisLabel
SetTimer, TL, -10
Sleep, 60
ExitApp
TL:
out(A_ThisLabel)
return
;; expect: TL

;; test: global code after functions still runs
F() {
}
out("after functions")
;; expect: after functions

;; test: Critical with a timer delays it
Critical
SetTimer, CT, -1
Sleep, 30
out("first")
Critical, Off
Sleep, 30
ExitApp
CT:
out("timer")
return
;; expect: first
;; expect: timer

;; test: instances see class static members
class Cfg {
    static Name := "cfg"
    Show() {
        return this.Name
    }
}
c := new Cfg
out(c.Name " " c.Show() " " c["Name"])
;; expect: cfg cfg cfg
