#Include %A_LineFile%\..\inc\helper.ahk
out(s) => FileAppend(s "`n", "*")
; } else { must not merge with the following lines
f(x) {
    if x {
        r := "yes"
    } else {
        r := "no"
    }
    return r
}
out(f(1) f(0))
; assigning to `this`
class Box {
    v := 1
    Swap() {
        other := Box(), other.v := 2
        this := other
        return this.v
    }
    #DllLoad nothing_to_load
}
out(Box().Swap())
; obj[args*] passes an array as index arguments
class Grid {
    __Item[r, c] => r "x" c
}
args := [3, 4]
out(Grid()[args*])
; compound assignment in a declaration
total := 10
bump() {
    global total += 5
}
bump()
out(total)
; try { } catch Error as e { } finally { } on joined lines
try {
    throw ValueError("bad")
} catch ValueError as e {
    out("caught " e.Message)
} finally {
    out("finally")
}
out(IncludedFunc())
