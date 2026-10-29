out(s) => FileAppend(s "`n", "*")
; numbers & formatting
out(1/3)
out(2**63)
out(9223372036854775807 + 1)
out(0x10 + 1)
out(1e3)
out(3.0 * 2)
; string/number comparisons
out(("10" < "9") " " (10 < 9))
out("abc" = "ABC")
out("abc" == "ABC")
out(1 == "1")
out("" = 0)
; truthiness
out(!"" " " !"0" " " !"0.0" " " !" " " " !"a")
; concat & auto-concat
x := 5
out("x=" x "!")
out("a" . "b")
; ternary/short-circuit values
out((0 || "") = "")
out("" ?? "dflt")
out(unsetVar ?? "dflt")
; objects
a := [10, 20, 30]
out(a.Length " " a.Has(2) " " a.Has(5))
a.RemoveAt(1)
out(a[1] "," a[2])
a.InsertAt(1, 5)
out(a[1])
m := Map()
m["X"] := 1, m["x"] := 2
out(m.Count " " m["X"] " " m["x"])
m2 := Map(), m2.CaseSense := "Off", m2["A"] := 1, m2["a"] := 2
out(m2.Count)
o := {}
o.DefineProp("Twice", {get: (this) => 42})
out(o.Twice)
out(o.HasOwnProp("Twice") " " HasProp(o, "nope"))
; errors
try
    [1,2][5]
catch IndexError as e
    out("IndexError " e.Message)
try
    Map()["k"]
catch UnsetItemError as e
    out("UnsetItemError " e.Message)
try
    "a" + 1
catch TypeError as e
    out(e.Message)
try
    ({}).nope
catch PropertyError as e
    out(e.Message)
try
    ({}).nope()
catch MethodError as e
    out(e.Message)
try
    throw "plain string"
catch Any as e
    out("caught " e)
; byref
inc(&v) => v += 1
n := 1
inc(&n), inc(&n)
out(n)
; variadic
sum(nums*) {
    t := 0
    for v in nums
        t += v
    return t
}
out(sum(1, 2, 3) " " sum([4, 5]*))
; closures capture variables
fns := []
Loop 3
    fns.Push(((i) => () => i)(A_Index))
out(fns[1]() fns[2]() fns[3]())
; class features
class Counter {
    static instances := 0
    count := 0
    __New() => Counter.instances++
    Inc() => ++this.count
    Value {
        get => this.count
        set => this.count := value * 10
    }
    __Item[k] => "item:" k
}
c := Counter(), c.Inc(), c.Inc()
out(c.Value " " Counter.instances)
c.Value := 3
out(c.count " " c["z"])
; for over own props is sorted
for k in {b: 1, A: 2, c: 3}.OwnProps()
    out(k)
; loop variants
Loop 0
    out("never")
else
    out("loop-else")
str := ""
for i, v in ["a", "b"]
    str .= i v
out(str)
i := "keep"
for i in [1, 2]
    x := i
out(i)
; switch is case-sensitive by default
switch "A" {
    case "a": out("lower")
    case "A": out("upper")
}
; goto / labels
k := 0
again:
k++
if k < 3
    goto again
out(k)
; string functions
out(SubStr("abcdef", -3) " " SubStr("abcdef", 2, -2))
out(InStr("abcabc", "c",, -1, 2))
out(StrReplace("aAa", "a", "x") " " StrReplace("aAa", "a", "x", true))
out(Trim("  pad  ") "|")
out(Format("{1}-{1}-{2:U}", "x", "y"))
out(Format("{:+d} {:.3e} {:08.3f}", 5, 12345.678, -3.5))
out(Chr(65) Ord("a"))
; __Delete runs when the last reference goes away
class DelTest {
    __New(n) => this.n := n
    __Delete() => FileAppend("delete " this.n "`n", "*")
}
dt := DelTest(1)
dt := ""
FileAppend("after 1`n", "*")
dt2 := DelTest(2), keep := dt2
dt2 := ""
FileAppend("still kept`n", "*")
keep := ""
dt3 := DelTest(3).Clone()
dt3 := ""
