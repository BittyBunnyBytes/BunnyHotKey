;; suite: v2 display serial
; DllCall's Win32 API emulation (tools/conformance.py): expected values follow the Win32 documentation
; (struct layouts from the 64-bit SDK); the scripts are written as they would be for Windows.

;; test: CryptBinaryToString base64 with and without CRLF
b := Buffer(3), NumPut("UChar", 0x4D, "UChar", 0x61, "UChar", 0x6E, b)
DllCall("crypt32\CryptBinaryToStringW", "Ptr", b, "UInt", 3, "UInt", 0x40000001, "Ptr", 0, "UInt*", &n := 0)
s := Buffer(n * 2)
DllCall("crypt32\CryptBinaryToStringW", "Ptr", b, "UInt", 3, "UInt", 0x40000001, "Ptr", s, "UInt*", &n)
t := StrGet(s, "UTF-16")
DllCall("crypt32\CryptBinaryToStringW", "Ptr", b, "UInt", 3, "UInt", 1, "Ptr", 0, "UInt*", &n2 := 0)
out(t " " n " " n2)
;; expect: TWFu 4 7

;; test: CryptStringToBinary base64 two-call pattern
str := "SGVsbG8sIFdvcmxkIQ=="
DllCall("crypt32\CryptStringToBinaryW", "Str", str, "UInt", 0, "UInt", 1, "Ptr", 0, "UInt*", &size := 0, "Ptr", 0, "Ptr", 0)
buf := Buffer(size)
ok := DllCall("crypt32\CryptStringToBinaryW", "Str", str, "UInt", 0, "UInt", 1, "Ptr", buf, "UInt*", &size, "Ptr", 0, "Ptr", 0)
out(ok " " size " " StrGet(buf, size, "UTF-8"))
;; expect: 1 13 Hello, World!

;; test: CryptStringToBinary and CryptBinaryToString hex
DllCall("crypt32\CryptStringToBinaryW", "Str", "deadbeef", "UInt", 0, "UInt", 0xC, "Ptr", 0, "UInt*", &size := 0, "Ptr", 0, "Ptr", 0)
b := Buffer(size)
DllCall("crypt32\CryptStringToBinaryW", "Str", "deadbeef", "UInt", 0, "UInt", 0xC, "Ptr", b, "UInt*", &size, "Ptr", 0, "Ptr", 0)
DllCall("crypt32\CryptBinaryToStringW", "Ptr", b, "UInt", size, "UInt", 0x4000000C, "Ptr", 0, "UInt*", &n := 0)
s := Buffer(n * 2)
DllCall("crypt32\CryptBinaryToStringW", "Ptr", b, "UInt", size, "UInt", 0x4000000C, "Ptr", s, "UInt*", &n)
out(size " " Format("{:X}", NumGet(b, 0, "UInt")) " " StrGet(s))
;; expect: 4 EFBEADDE deadbeef

;; test: CryptoAPI MD5 and SHA-256 hashes
Hash(alg, text) {
    DllCall("advapi32\CryptAcquireContextW", "Ptr*", &prov := 0, "Ptr", 0, "Ptr", 0, "UInt", 24, "UInt", 0xF0000000)
    DllCall("advapi32\CryptCreateHash", "Ptr", prov, "UInt", alg, "Ptr", 0, "UInt", 0, "Ptr*", &h := 0)
    b := Buffer(StrPut(text, "UTF-8") - 1)
    StrPut(text, b, "UTF-8")
    DllCall("advapi32\CryptHashData", "Ptr", h, "Ptr", b, "UInt", b.Size, "UInt", 0)
    DllCall("advapi32\CryptGetHashParam", "Ptr", h, "UInt", 2, "Ptr", 0, "UInt*", &n := 0, "UInt", 0)
    d := Buffer(n)
    DllCall("advapi32\CryptGetHashParam", "Ptr", h, "UInt", 2, "Ptr", d, "UInt*", &n, "UInt", 0)
    DllCall("advapi32\CryptDestroyHash", "Ptr", h)
    DllCall("advapi32\CryptReleaseContext", "Ptr", prov, "UInt", 0)
    s := ""
    Loop n
        s .= Format("{:02x}", NumGet(d, A_Index - 1, "UChar"))
    return s
}
out(Hash(0x8003, "abc"))
out(Hash(0x800C, "abc"))
;; expect: 900150983cd24fb0d6963f7d28e17f72
;; expect: ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad

;; test: GlobalAlloc, GlobalLock, GlobalSize, GlobalFree
h := DllCall("GlobalAlloc", "UInt", 0x42, "UPtr", 64, "Ptr")
p := DllCall("GlobalLock", "Ptr", h, "Ptr")
z := NumGet(p, 60, "UInt")
NumPut("UInt", 1234, p)
v := NumGet(p, "UInt")
sz := DllCall("GlobalSize", "Ptr", h, "UPtr")
DllCall("GlobalUnlock", "Ptr", h)
r := DllCall("GlobalFree", "Ptr", h, "Ptr")
out((h != 0) " " z " " v " " sz " " r)
;; expect: 1 0 1234 64 0

;; test: HeapAlloc with HEAP_ZERO_MEMORY and HeapFree
heap := DllCall("GetProcessHeap", "Ptr")
p := DllCall("HeapAlloc", "Ptr", heap, "UInt", 8, "UPtr", 16, "Ptr")
z := NumGet(p, 8, "Int64")
out((heap != 0) " " z " " DllCall("HeapFree", "Ptr", heap, "UInt", 0, "Ptr", p))
;; expect: 1 0 1

;; test: VirtualProtect makes memory executable
b := Buffer(4096)
r := DllCall("VirtualProtect", "Ptr", b, "UPtr", b.Size, "UInt", 0x40, "UInt*", &old := 0)
out(r " " old)
;; expect: 1 4

;; test: rectangle helpers
a := Buffer(16), b := Buffer(16), r := Buffer(16)
DllCall("SetRect", "Ptr", a, "Int", 0, "Int", 0, "Int", 10, "Int", 10)
DllCall("SetRect", "Ptr", b, "Int", 5, "Int", 5, "Int", 20, "Int", 20)
i := DllCall("IntersectRect", "Ptr", r, "Ptr", a, "Ptr", b)
ri := NumGet(r, 0, "Int") "," NumGet(r, 12, "Int")
DllCall("UnionRect", "Ptr", r, "Ptr", a, "Ptr", b)
ru := NumGet(r, 8, "Int")
pt := DllCall("PtInRect", "Ptr", a, "Int64", 3 | (4 << 32))
DllCall("OffsetRect", "Ptr", a, "Int", 2, "Int", 3)
out(i " " ri " " ru " " pt " " NumGet(a, 0, "Int") NumGet(a, 4, "Int") " " DllCall("IsRectEmpty", "Ptr", r))
;; expect: 1 5,10 20 1 23 0

;; test: ScreenToClient and ClientToScreen round trip
g := Gui("-DPIScale", "BHKDll Coords")
g.Show("x200 y150 w300 h200 NoActivate")
WinWait("BHKDll Coords",, 3)
Sleep(200)
WinGetClientPos(&cx, &cy,,, "BHKDll Coords")
pt := Buffer(8), NumPut("Int", cx + 10, "Int", cy + 20, pt)
DllCall("ScreenToClient", "Ptr", g.Hwnd, "Ptr", pt)
a := NumGet(pt, 0, "Int") "," NumGet(pt, 4, "Int")
DllCall("ClientToScreen", "Ptr", g.Hwnd, "Ptr", pt)
out(a " " (NumGet(pt, 0, "Int") = cx + 10) (NumGet(pt, 4, "Int") = cy + 20))
;; expect: 10,20 11

;; test: WindowFromPoint finds a window under the point
g := Gui("-DPIScale +AlwaysOnTop", "BHKDll Point")
g.Show("x300 y300 w200 h120 NoActivate")
WinWait("BHKDll Point",, 3)
Sleep(300)
WinGetClientPos(&cx, &cy,,, "BHKDll Point")
h := DllCall("WindowFromPoint", "Int64", (cx + 50) | ((cy + 50) << 32), "Ptr")
out(h = g.Hwnd)
;; expect: 1

;; test: MonitorFromWindow, GetMonitorInfo and GetDpiForMonitor
g := Gui(, "BHKDll Monitor")
g.Show("NoActivate")
WinWait("BHKDll Monitor",, 3)
hm := DllCall("MonitorFromWindow", "Ptr", g.Hwnd, "UInt", 2, "Ptr")
mi := Buffer(40, 0), NumPut("UInt", 40, mi)
r := DllCall("GetMonitorInfoW", "Ptr", hm, "Ptr", mi)
MonitorGet(MonitorGetPrimary(), &l, &t, &rr, &bb)
DllCall("Shcore\GetDpiForMonitor", "Ptr", hm, "Int", 0, "UInt*", &dx := 0, "UInt*", &dy := 0)
primary := NumGet(mi, 36, "UInt") & 1                ; MONITORINFOF_PRIMARY
out((hm != 0) " " r " " (NumGet(mi, 12, "Int") > NumGet(mi, 4, "Int")) " " (primary || MonitorGetCount() > 1) " " (dx = A_ScreenDPI))
;; expect: 1 1 1 1 1

;; test: RegisterWindowMessage is stable and in range
a := DllCall("RegisterWindowMessage", "Str", "BHK_TEST_MSG")
b := DllCall("RegisterWindowMessage", "Str", "bhk_test_msg")
out((a = b) " " (a >= 0xC000 && a <= 0xFFFF))
;; expect: 1 1

;; test: GetACP
out(DllCall("GetACP"))
;; expect: 1252

;; test: OpenProcess, GetExitCodeProcess, WaitForSingleObject
Run("sleep 0.5",, "Hide", &pid)
h := DllCall("OpenProcess", "UInt", 0x101000, "Int", 0, "UInt", pid, "Ptr")
DllCall("GetExitCodeProcess", "Ptr", h, "UInt*", &c1 := 0)
w1 := DllCall("WaitForSingleObject", "Ptr", h, "UInt", 50)
w2 := DllCall("WaitForSingleObject", "Ptr", h, "UInt", 3000)
DllCall("GetExitCodeProcess", "Ptr", h, "UInt*", &c2 := 0)
DllCall("CloseHandle", "Ptr", h)
out((h != 0) " " c1 " " w1 " " w2 " " c2)
;; expect: 1 259 258 0 0

;; test: CreateToolhelp32Snapshot lists this script's process
snap := DllCall("CreateToolhelp32Snapshot", "UInt", 2, "UInt", 0, "Ptr")
pe := Buffer(568, 0), NumPut("UInt", 568, pe)
found := 0, n := 0
if DllCall("Process32FirstW", "Ptr", snap, "Ptr", pe)
    loop {
        n++
        if NumGet(pe, 8, "UInt") = ProcessExist()
            found := 1, parent := NumGet(pe, 32, "UInt"), exe := StrGet(pe.Ptr + 44, "UTF-16")
    } until !DllCall("Process32NextW", "Ptr", snap, "Ptr", pe)
DllCall("CloseHandle", "Ptr", snap)
out(found " " (n > 10) " " (parent > 0) " " (InStr(exe, "python") > 0))
;; expect: 1 1 1 1

;; test: QueryFullProcessImageName and GetModuleFileName
h := DllCall("OpenProcess", "UInt", 0x1000, "Int", 0, "UInt", ProcessExist(), "Ptr")
buf := Buffer(1024), size := 512
DllCall("QueryFullProcessImageNameW", "Ptr", h, "UInt", 0, "Ptr", buf, "UInt*", &size)
DllCall("CloseHandle", "Ptr", h)
mod := Buffer(1024)
n := DllCall("GetModuleFileNameW", "Ptr", 0, "Ptr", mod, "UInt", 512)
out((StrGet(buf) = A_AhkPath) " " (StrGet(mod) = A_AhkPath) " " (n = StrLen(A_AhkPath)))
;; expect: 1 1 1

;; test: GetTokenInformation TokenElevation
DllCall("OpenProcessToken", "Ptr", DllCall("GetCurrentProcess", "Ptr"), "UInt", 8, "Ptr*", &tok := 0)
DllCall("advapi32\GetTokenInformation", "Ptr", tok, "Int", 20, "UInt*", &elev := 0, "UInt", 4, "UInt*", &ret := 0)
out(elev " " ret " " A_IsAdmin)
;; expect: 0 4 0

;; test: clipboard through OpenClipboard / SetClipboardData / GetClipboardData (restored)
saved := ClipboardAll()
text := "via win32"
h := DllCall("GlobalAlloc", "UInt", 2, "UPtr", (StrLen(text) + 1) * 2, "Ptr")
StrPut(text, DllCall("GlobalLock", "Ptr", h, "Ptr"), "UTF-16")
DllCall("GlobalUnlock", "Ptr", h)
DllCall("OpenClipboard", "Ptr", 0)
DllCall("EmptyClipboard")
DllCall("SetClipboardData", "UInt", 13, "Ptr", h)
DllCall("CloseClipboard")
Sleep(300)
a := A_Clipboard
DllCall("OpenClipboard", "Ptr", 0)
avail := DllCall("IsClipboardFormatAvailable", "UInt", 13)
p := DllCall("GetClipboardData", "UInt", 13, "Ptr")
b := StrGet(p, "UTF-16")
DllCall("CloseClipboard")
A_Clipboard := saved
out(a " | " avail " | " b)
;; expect: via win32 | 1 | via win32

;; test: CreateFile, WriteFile, ReadFile, GetFileSizeEx, SetFilePointer
h := DllCall("CreateFileW", "Str", A_WorkingDir "\cf.bin", "UInt", 0xC0000000, "UInt", 0, "Ptr", 0, "UInt", 2, "UInt", 0x80, "Ptr", 0, "Ptr")
data := Buffer(5), StrPut("hello", data, 5, "CP0")
DllCall("WriteFile", "Ptr", h, "Ptr", data, "UInt", 5, "UInt*", &wrote := 0, "Ptr", 0)
DllCall("GetFileSizeEx", "Ptr", h, "Int64*", &size := 0)
DllCall("SetFilePointer", "Ptr", h, "Int", 1, "Ptr", 0, "UInt", 0)
r := Buffer(4, 0)
DllCall("ReadFile", "Ptr", h, "Ptr", r, "UInt", 3, "UInt*", &got := 0, "Ptr", 0)
DllCall("CloseHandle", "Ptr", h)
miss := DllCall("CreateFileW", "Str", A_WorkingDir "\nope.bin", "UInt", 0x80000000, "UInt", 1, "Ptr", 0, "UInt", 3, "UInt", 0, "Ptr", 0, "Ptr")
err := A_LastError
out(wrote " " size " " got " " StrGet(r, 3, "CP0") " " miss " " err " " FileRead("cf.bin"))
;; expect: 5 5 3 ell -1 2 hello

;; test: GetFileAttributes and GetFullPathName
DirCreate("gfa")
a := DllCall("GetFileAttributesW", "Str", A_WorkingDir "\gfa", "UInt")
m := DllCall("GetFileAttributesW", "Str", A_WorkingDir "\missing", "UInt")
need := DllCall("GetFullPathNameW", "Str", "gfa", "UInt", 0, "Ptr", 0, "Ptr", 0)
buf := Buffer(need * 2)
n := DllCall("GetFullPathNameW", "Str", "gfa", "UInt", need, "Ptr", buf, "Ptr", 0)
out((a & 0x10 = 0x10) " " Format("{:X}", m) " " (n = need - 1) " " (InStr(StrGet(buf), "gfa") > 0))
;; expect: 1 FFFFFFFF 1 1

;; test: GetStdHandle and WriteFile to stdout
h := DllCall("GetStdHandle", "Int", -11, "Ptr")
msg := Buffer(6), StrPut("stdout", msg, 6, "CP0")
DllCall("WriteFile", "Ptr", h, "Ptr", msg, "UInt", 6, "UInt*", &n := 0, "Ptr", 0)
FileAppend("`n", "*")
;; expect: stdout
