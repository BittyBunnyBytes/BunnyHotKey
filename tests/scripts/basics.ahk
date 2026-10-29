#Requires AutoHotkey v2.0
out(s) => FileAppend(s "`n", "*")
x := 1 + 2 * 3
out(x)
out(0.1 + 0.2)
out(1.0)
out(10 / 4)
out(7 // 2)
out(-7 // 2)
out(2 ** 10)
out(-2 ** 2)
out("abc" . 5)
out("A" = "a")
out("A" == "a")
out(1 = "1.0")
out("1" = "1.0")
s := "Hello"
s .= " World"
out(s)
out(StrLen(s) " " SubStr(s, 7) " " InStr(s, "o",, -1))
arr := [1, 2, 3]
arr.Push(4)
out(arr.Length " " arr[-1])
m := Map("b", 2, "a", 1)
for k, v in m
    out(k "=" v)
o := {z: 1, a: 2}
for k, v in o.OwnProps()
    out(k ":" v)
f(a, b := 10) => a + b
out(f(1) " " f(1, 2))
counter() {
    static n := 0
    return ++n
}
counter(), counter()
out(counter())
mk(n) {
    return () => n * 2
}
g := mk(21)
out(g())
class Animal {
    name := "?"
    __New(n) => this.name := n
    Speak() => this.name " makes a sound"
}
class Dog extends Animal {
    Speak() => super.Speak() " (woof)"
}
d := Dog("Rex")
out(d.Speak())
out(Type(d) " " (d is Animal) " " Type(Dog))
try
    y := 1 / 0
catch ZeroDivisionError as e
    out("caught " e.Message)
try {
    zz := undefinedvar + 1
} catch Error as e {
    out(Type(e) ": " e.Message)
}
Loop 3
    out("i" A_Index)
Loop Parse "a,b,c", ","
    out(A_LoopField)
switch x {
    case 1, 2: out("low")
    case 7: out("seven")
    default: out("other")
}
out(Format("{:05.2f}|{:-5}|{:x}", 3.14159, "ab", 255))
out(RegExReplace("hello world", "o(\w)", "[$1]"))
if RegExMatch("abc123def", "(\d+)", &m)
    out(m[1] " at " m.Pos[1])
out(StrSplit("a|b|c", "|").Length)
out(Round(3.14159, 2) " " Round(2.5) " " Round(-2.5))
out(IsNumber("12") " " IsInteger("1.5") " " IsFloat(1.5))
out(Integer("0x10") " " Float(3))
out(Sort("c`nb`na"))
z := x > 5 ? "big" : "small"
out(z)
out(1 || 0 "|" "" || "def" "|" 5 && 0)
out(StrUpper("abc") StrLower("DEF") StrTitle("hello there"))
