out(s) => FileAppend(s "`n", "*")

; object pointers
o := {a: 1}
p := ObjPtrAddRef(o)
out("ptr " (ObjFromPtrAddRef(p) == o) " " ObjAddRef(p) " " ObjRelease(p) " " (ObjFromPtr(p) == o) " " (ObjPtr(o) = p))
try ObjFromPtr(12345)
catch ValueError as e
    out("badptr " e.Message)

; strings and capacity
out("strptr " StrGet(StrPtr("hello")) " " NumGet(StrPtr("A"), "UShort"))
v := "abc"
out("cap " VarSetStrCapacity(&v) " " VarSetStrCapacity(&v, 100) " " VarSetStrCapacity(&v, 0) " [" v "]")

; callbacks: libc's qsort calls back into the script
cmp(a, b) => NumGet(a, "Int") - NumGet(b, "Int")
arr := Buffer(20)
for i, n in [42, 7, 19, 3, 25]
    NumPut("Int", n, arr, (i - 1) * 4)
cb := CallbackCreate(cmp, "CDecl", 2)
DllCall("libc.so.6\qsort", "Ptr", arr, "UPtr", 5, "UPtr", 4, "Ptr", cb, "CDecl")
s := ""
loop 5
    s .= NumGet(arr, (A_Index - 1) * 4, "Int") " "
out("qsort " s)
out("bycb " DllCall(cb, "Ptr", arr.Ptr + 4, "Ptr", arr.Ptr))
CallbackFree(cb)
try CallbackFree(cb)
catch ValueError
    out("freed")

; FileGetVersion on a minimal PE with a VS_FIXEDFILEINFO block
f := A_Temp "\bhk_version_test.exe"
b := Buffer(64, 0)
NumPut("UChar", 0x4D, "UChar", 0x5A, b)              ; "MZ"
NumPut("UInt", 0xFEEF04BD, b, 16)                    ; VS_FIXEDFILEINFO.dwSignature
NumPut("UInt", 0x00010000, b, 20)
NumPut("UInt", (2 << 16) | 0, b, 24)                 ; dwFileVersionMS: 2.0
NumPut("UInt", (31 << 16) | 7, b, 28)                ; dwFileVersionLS: 31.7
FileOpen(f, "w").RawWrite(b)
out("version " FileGetVersion(f))
FileDelete(f)

; ListLines toggles, KeyHistory(N) resizes silently
out("listlines " ListLines(0) " " A_ListLines " " ListLines(1) " " A_ListLines)
KeyHistory(5)

; image lists, picture handles, menus by handle
il := IL_Create(3)
out("il " IL_Add(il, A_ScriptDir "\..\..\assets\bunnyhotkey-16.png") " " IL_Add(il, "nonexistent.png") " "
    IL_Add(il, "shell32.dll", 4) " " IL_Destroy(il) " " IL_Destroy(il))
h := LoadPicture(A_ScriptDir "\..\..\assets\bunnyhotkey-32.png", , &kind)
out("picture " (h > 0) " " kind " " LoadPicture("nonexistent.png"))
m := Menu()
out("menu " (MenuFromHandle(m.Handle) == m))

; monitors and drives
out("monitors " (MonitorGetCount() >= 1) " " (MonitorGetPrimary() >= 1) " " (InStr(MonitorGetName(), "DISPLAY") > 0))
out("drive " DriveGetType("Z:\") " " (StrLen(DriveGetFileSystem("Z:\")) > 0) " " InStr(DriveGetList(), "Z"))

; by-reference with the maybe operator
bump(&r?) => r := IsSet(r) ? r + 1 : 1
bump(&cnt?), bump(&cnt?)
out("maybe-ref " cnt)
out("done")
