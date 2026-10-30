;; suite: v2
; AutoHotkey v2.0 strings, RegEx, math and dates (tools/conformance.py). Expected values from the v2 docs.

;; test: InStr forward, backward, case and occurrence
out(InStr("abcabc", "b") " " InStr("abcabc", "b",, -1) " " InStr("ABC", "b", true) " " InStr("abcabc", "c",, 1, 2))
;; expect: 2 5 0 6

;; test: SubStr with negative start and length
out(SubStr("abcdef", 2, 3) " " SubStr("abcdef", -2) " " SubStr("abcdef", 2, -1))
;; expect: bcd ef bcde

;; test: StrLen, StrLower, StrUpper, StrTitle
out(StrLen("héllo") " " StrLower("AbC") " " StrUpper("abc") " " StrTitle("hello world"))
;; expect: 5 abc ABC Hello World

;; test: StrReplace with count and limit
s := StrReplace("aaaa", "a", "b",, &n, 3)
out(s " " n " " StrReplace("AbA", "a", "x", true))
;; expect: bbba 3 AbA

;; test: StrSplit with omit chars and max parts
a := StrSplit(" a , b , c ", ",", " ", 2)
out(a.Length "|" a[1] "|" a[2])
;; expect: 2|a|b , c

;; test: Trim, LTrim, RTrim
out("[" Trim("  x ") "][" LTrim("..x..", ".") "][" RTrim("..x..", ".") "]")
;; expect: [x][x..][..x]

;; test: StrCompare modes
out((StrCompare("a", "B") < 0) " " (StrCompare("a", "A", true) > 0) " " StrCompare("abc", "abc"))
;; expect: 1 1 0

;; test: Chr and Ord
out(Chr(65) Chr(0x1F600) " " Ord("A") " " Ord("😀"))
;; expect: A😀 65 128512

;; test: Format specifiers
out(Format("{1:05.2f}|{2:-5}|{3:x}|{3:X}|{1:.2e}|{2}{4}", 3.14159, "ab", 255, 2.5))
;; expect: 03.14|ab   |ff|FF|3.14e+00|ab2.5

;; test: Format with case and width
out(Format("{:U}|{:L}|{:T}|{:6}|{:06d}", "ab", "CD", "ef gh", "r", 42))
;; expect: AB|cd|Ef Gh|     r|000042

;; test: FormatTime tokens
out(FormatTime("20240315143005", "yyyy-MM-dd HH:mm:ss dddd MMM h tt"))
;; expect: 2024-03-15 14:30:05 Friday Mar 2 PM

;; test: FormatTime YDay and WDay
out(FormatTime("20240315", "YDay") " " FormatTime("20240315", "WDay") " " FormatTime("20240315", "YWeek"))
;; expect: 75 6 202411

;; test: RegExMatch match object
RegExMatch("key=val", "(?<k>\w+)=(\w+)", &m)
out(m[0] " " m.k " " m[2] " " m.Pos[2] " " m.Len[1] " " m.Count " " m.Name[1])
;; expect: key=val key val 5 3 2 k

;; test: RegExMatch options and start position
out(RegExMatch("ABC", "i)b") " " RegExMatch("a1b2", "\d",, 3) " " RegExMatch("x`nyz", "m)^y"))
;; expect: 2 4 3

;; test: RegExReplace with backreferences, count and limit
out(RegExReplace("a1b22", "(\d+)", "<$1>", &c) " " c " " RegExReplace("aaa", "a", "b",, 2))
;; expect: a<1>b<22> 2 bba

;; test: RegExReplace case conversion
out(RegExReplace("hello", "(\w+)", "$U1") " " RegExReplace("WORLD", "(\w)(\w+)", "$1$L2"))
;; expect: HELLO World

;; test: RegEx callouts
Counter(m, n, *) {
    global hits
    hits++
    return 0
}
hits := 0
RegExMatch("abc", "a(?CCounter)b")
out(hits)
;; expect: 1

;; test: RegEx callouts: numbered, named with a number, pcre_callout, FoundPos and the partial match
Trace(m, n, pos, hay, needle) {
    global calls
    calls .= n ":" pos ":" m[0] " "
    return 0
}
calls := ""
pcre_callout := Trace
r1 := RegExMatch("aab", "a(?C7)b")
r2 := RegExMatch("xabc", "a(?C3:Trace)b(?CTrace)c", &m)
out(r1 " " r2 " " m[0] " | " Trim(calls))
;; expect: 2 2 abc | 7:1:a 7:2:a 3:2:a 0:2:ab

;; test: RegEx callouts: a positive return backtracks, a negative one aborts with an error
Short(m, *) => StrLen(m[0]) > 2
Abort(m, *) => -5
p := RegExMatch("abcd", "\w+(?CShort)", &m)
try
    RegExMatch("abc", "b(?CAbort)")
catch Error as e
    err := e.Message " " e.Extra
out(p " " m[0] " | " err)
;; expect: 1 ab | PCRE execution error. -5

;; test: RegEx callouts in RegExReplace and the newline options `n and `a
Mark(m, n, pos, *) {
    global seen
    seen .= pos
}
seen := ""
r := RegExReplace("a1b2", "\d(?CMark)", "#")
out(r " " seen " " RegExMatch("a`r`nb", "m`n)^b$") " " RegExMatch("xa`nb", "m`a)a$") " " RegExMatch("xa`r`nb", "m)a$"))
;; expect: a#b# 24 4 2 2

;; test: Sort options
out(Sort("c,a,b", "D,") " " Sort("10`n9`n100", "N") " " Sort("b,a,b", "D, U") " " Sort("a,b,c", "D, R"))
;; expect: a,b,c 9
;; expect: 10
;; expect: 100 a,b c,b,a

;; test: Sort with a callback
Rev(a, b, *) => a > b ? -1 : a < b ? 1 : 0
out(Sort("1,3,2", "D,", Rev))
;; expect: 3,2,1

;; test: Abs, Ceil, Floor, Round, Mod, Max, Min
out(Abs(-3) " " Ceil(1.2) " " Floor(-1.2) " " Round(2.5) " " Round(3.14159, 2) " " Mod(-7, 3) " " Max(1, 9, 3) " " Min(4, 2))
;; expect: 3 2 -2 3 3.14 -1 9 2

;; test: Sqrt, Exp, Log, Ln
out(Sqrt(16) " " Round(Exp(1), 4) " " Log(1000) " " Round(Ln(10), 4))
;; expect: 4.0 2.7183 3.0 2.3026

;; test: trigonometry
out(Round(Sin(0), 3) " " Round(Cos(0), 3) " " Round(Tan(0.5), 4) " " Round(ASin(1), 4) " " Round(ACos(0), 4) " " Round(ATan(1), 4))
;; expect: 0.000 1.000 0.5463 1.5708 1.5708 0.7854

;; test: math errors throw
try
    Sqrt(-1)
catch ValueError
    out("ValueError")
try
    x := 1 // 0
catch ZeroDivisionError
    out("ZeroDivisionError")
;; expect: ValueError
;; expect: ZeroDivisionError

;; test: Random range and type
r := Random(5, 5)
f := Random(0.0, 1.0)
i := Random(1, 10)
out(r " " (Type(f) = "Float") " " (i >= 1 && i <= 10 && IsInteger(i)))
;; expect: 5 1 1

;; test: DateAdd and DateDiff
out(DateAdd("20240131", 1, "Days") " " DateDiff("20240301", "20240201", "Days") " " DateDiff("20240101120000", "20240101100000", "Minutes"))
;; expect: 20240201000000 29 120

;; test: VerCompare
out(VerCompare("1.2.10", "1.2.9") " " VerCompare("2.0-a", "2.0") " " VerCompare("1.0", ">=1.0") " " VerCompare("1.0", "<1.0"))
;; expect: 1 -1 1 0

;; test: StrPtr, StrPut and StrGet
buf := Buffer(20, 0)
n := StrPut("héllo", buf, "UTF-8")
out(n " " StrGet(buf, "UTF-8") " " StrGet(StrPtr("abc"), 2))
;; expect: 7 héllo ab

;; test: NumPut and NumGet
b := Buffer(16)
NumPut("UInt", 0xDEADBEEF, "Short", -2, b)
out(Format("{:X}", NumGet(b, 0, "UInt")) " " NumGet(b, 4, "Short") " " NumGet(b, 4, "UShort"))
;; expect: DEADBEEF -2 65534

;; test: type check functions
out(IsInteger("12") IsFloat("1.5") IsNumber("0x1F") IsDigit("123") IsXDigit("1F") IsAlpha("abc") IsUpper("AB") IsLower("ab") IsAlnum("a1") IsSpace(" `t") IsTime("20240101"))
;; expect: 11111111111

;; test: type check failures
out(IsInteger("1.5") IsDigit("1.5") IsAlpha("a1") IsUpper("aB") IsTime("20241399") IsSpace("x"))
;; expect: 000000

;; test: Number, Integer, Float and String conversions
out(Number("0x10") " " Integer(3.9) " " Float(2) " " String(1.5) " " Type(Number("1.0")))
;; expect: 16 3 2.0 1.5 Float

;; test: relational operators need numbers in v2.0
try
    x := 5 < "abc"
catch TypeError
    out("TypeError")
out(("10" < "9") " " ("b" = "B") " " ("b" == "B"))
;; expect: TypeError
;; expect: 0 1 0
