#NoEnv
#SingleInstance Force
SetBatchLines -1
SendMode Input
out(s) {
    FileAppend, %s%`n, *
}
name = Bunny
greeting = Hello, %name%!
out(greeting)
x := 5
y = 10
z := x + y
out("z=" z)
if x = 5
    out("legacy if equal")
if x <> 6
    out("legacy if not equal")
if (x > 3 and y < 20)
    out("expr if")
if y between 5 and 15
    out("between")
if name in Bunny,Cat
    out("in list")
if name contains unn
    out("contains")
if x is integer
    out("is integer")
if name is not number
    out("not number")
IfEqual, x, 5
    out("IfEqual")
IfInString, greeting, Bunny
    out("IfInString")
StringReplace, r, greeting, Hello, Bye
out(r)
StringReplace, r2, greeting, l, L, All
out(r2 " " ErrorLevel)
StringLen, n, greeting
out("len " n)
StringLeft, l3, greeting, 3
StringRight, r3, greeting, 3
StringMid, m3, greeting, 2, 4
out(l3 "|" r3 "|" m3)
StringUpper, up, name
StringLower, lo, name
out(up lo)
StringSplit, part, greeting, `,
out(part0 ":" part1 ":" part2)
StringGetPos, pos, greeting, o
out("pos " pos)
StringTrimLeft, tl, name, 2
StringTrimRight, tr, name, 2
out(tl tr)
Loop, 3
    out("loop " A_Index)
Loop, Parse, greeting, %A_Space%`,
    out("field " A_Index "=" A_LoopField)
list := "a|b|c"
Loop, Parse, list, |
{
    if A_LoopField = b
        continue
    out("p " A_LoopField)
}
count := 0
Loop
{
    count++
    if count >= 4
        break
}
out("count " count)
Gosub, MySub
out("after gosub " subvar)
obj := {a: 1, "b c": 2}
obj.d := 4
obj["E"] := 5
out(obj.a obj["b c"] obj.D obj.e)
arr := [10, 20, 30]
arr.Insert(40)
out(arr.MaxIndex() " " arr[4] " " arr.Length())
arr.Remove(1)
out(arr[1] " " arr.MaxIndex())
for k, v in obj
    out("k " k "=" v)
o2 := Object()
o2.list := []
o2.list.Push("x")
out(o2.list[1] o2.HasKey("list") o2.HasKey("zz"))
nested := {}
nested.a := {}
nested.a.b := "deep"
out(nested.a.b)
Swap(a1 := 1, b1 := 2)
p := 1, q := 2
Swap(p, q)
out(p q)
out(Add(2, 3) " " Add(2))
out(SubStr("abcdef", 0) SubStr("abcdef", 2, 3) InStr("abcabc", "c", false, 0))
s := "He said ""hi"""
out(s)
f := 3.14159
out(f " " f * 2 " " Round(f, 2))
out(10 / 4 " " 7 // 2 " " Mod(7, 3))
c := new Counter(5)
c.Inc()
c.Inc()
out("counter " c.n " " c.Get())
out(Counter.Desc)
d := new Dog("Rex")
out(d.Speak())
FormatTime, t, 20240115123045, yyyy-MM-dd HH:mm
out(t)
t2 := 20240115
t2 += 1, days
FormatTime, t3, %t2%, yyyyMMdd
out(t3)
v := "abc"
v .= "def"
out(v)
StringSplit, w, v
out(w0)
global G := "glob"
out(ReadG())
RegExMatch("key=value", "(\w+)=(\w+)", m)
out(m " " m1 " " m2)
RegExMatch("abc123", "O)\d+", mo)
out(mo.Value(0) " " mo.Pos(0))
out(RegExReplace("aaa", "a", "b"))
s2 := StrSplit("1,2,3", ",")
out(s2.MaxIndex() s2[2])
Sort, list, D| R
out(list)
Transform, sq, Pow, 2, 10
out(sq)
SetFormat, Float, 0.2
fl := 1.0 * 3
out(fl)
SetFormat, Float, 0.6
EnvAdd, x, 10
out(x)
x -= 3
out(x)
dyn1 := "one"
idx := 1
out(dyn%idx%)
dyn%idx% := "uno"
out(dyn1)
try
    throw Exception("boom", -1)
catch e
    out("caught " e.Message)
try {
    throw "str"
} catch err {
    out("caught2 " err)
}
switch x
{
case 12: out("switch 12")
default: out("switch default")
}
emptyvar =
out("[" emptyvar "]")
out("[" undefinedvar "]")
out(Chr(65) Asc("B"))
out(StrLen("hello") Abs(-3))
VarSetCapacity(buf, 8, 0)
NumPut(1234, buf, 0, "UInt")
out(NumGet(buf, 0, "UInt"))
Goto, Skip
out("not skipped")
Skip:
out("skipped ok")
out(IsFunc("Add") IsLabel("MySub") IsFunc("Nope"))
fn := Func("Add")
out(fn.Call(1, 1) %fn%(2, 2))
out(A_IsUnicode)
MsgText := "ok"
ExitApp

MySub:
subvar := "set in sub"
return

Swap(ByRef a, ByRef b) {
    t := a
    a := b
    b := t
}

Add(a, b = 10) {
    return a + b
}

ReadG() {
    return G
}

class Counter {
    static Desc := "counter class"
    __New(start) {
        this.n := start
    }
    Inc() {
        this.n++
    }
    Get() {
        return this.n
    }
}

class Animal {
    __New(name) {
        this.name := name
    }
    Speak() {
        return this.name " makes a sound"
    }
}

class Dog extends Animal {
    Speak() {
        return base.Speak() " (woof)"
    }
}
