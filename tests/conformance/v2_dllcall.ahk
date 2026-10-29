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

;; test: CreateDIBSection, memory DC, FillRect, GetPixel and the bits in BGRA order
bi := Buffer(40, 0)
NumPut("UInt", 40, "Int", 4, "Int", -3, "UShort", 1, "UShort", 32, bi)
hbm := DllCall("CreateDIBSection", "Ptr", 0, "Ptr", bi, "UInt", 0, "Ptr*", &bits := 0, "Ptr", 0, "UInt", 0, "Ptr")
hdc := DllCall("CreateCompatibleDC", "Ptr", 0, "Ptr")
old := DllCall("SelectObject", "Ptr", hdc, "Ptr", hbm, "Ptr")
br := DllCall("CreateSolidBrush", "UInt", 0x00336699, "Ptr")
rc := Buffer(16), NumPut("Int", 1, "Int", 1, "Int", 3, "Int", 2, rc)
DllCall("FillRect", "Ptr", hdc, "Ptr", rc, "Ptr", br)
c1 := DllCall("GetPixel", "Ptr", hdc, "Int", 2, "Int", 1, "UInt")
c0 := DllCall("GetPixel", "Ptr", hdc, "Int", 0, "Int", 0, "UInt")
px := NumGet(bits, (1 * 4 + 2) * 4, "UInt")
out((old != 0) " " Format("{:06X} {:06X} {:08X}", c1, c0, px & 0xFFFFFF))
;; expect: 1 336699 000000 00996633

;; test: GetObject on a DIB section and a compatible bitmap
bi := Buffer(40, 0)
NumPut("UInt", 40, "Int", 5, "Int", 7, "UShort", 1, "UShort", 24, bi)
hbm := DllCall("CreateDIBSection", "Ptr", 0, "Ptr", bi, "UInt", 0, "Ptr*", &bits := 0, "Ptr", 0, "UInt", 0, "Ptr")
bm := Buffer(32, 0)
n := DllCall("GetObject", "Ptr", hbm, "Int", 32, "Ptr", bm)
ds := Buffer(104, 0)
n2 := DllCall("GetObject", "Ptr", hbm, "Int", 104, "Ptr", ds)
w := NumGet(bm, 4, "Int"), h := NumGet(bm, 8, "Int"), stride := NumGet(bm, 12, "Int")
bpp := NumGet(bm, 18, "UShort"), same := NumGet(bm, 24, "Ptr") = bits
hdrh := NumGet(ds, 32 + 8, "Int"), img := NumGet(ds, 32 + 20, "UInt")
cb := DllCall("CreateCompatibleBitmap", "Ptr", 0, "Int", 3, "Int", 2, "Ptr")
DllCall("GetObject", "Ptr", cb, "Int", 32, "Ptr", bm)
out(n " " n2 " " w "x" h " " stride " " bpp " " same " " hdrh " " img " | " NumGet(bm, 4, "Int") "x" NumGet(bm, 8, "Int") " " NumGet(bm, 24, "Ptr"))
;; expect: 32 104 5x7 16 24 1 7 112 | 3x2 0

;; test: BitBlt SRCCOPY and SRCINVERT, StretchBlt doubling, SetStretchBltMode
MakeDC(w, h) {
    hdc := DllCall("CreateCompatibleDC", "Ptr", 0, "Ptr")
    DllCall("SelectObject", "Ptr", hdc, "Ptr", DllCall("CreateCompatibleBitmap", "Ptr", hdc, "Int", w, "Int", h, "Ptr"))
    return hdc
}
a := MakeDC(2, 2), b := MakeDC(4, 4)
DllCall("SetPixel", "Ptr", a, "Int", 0, "Int", 0, "UInt", 0x0000FF)
DllCall("SetPixel", "Ptr", a, "Int", 1, "Int", 1, "UInt", 0x00FF00)
DllCall("BitBlt", "Ptr", b, "Int", 2, "Int", 2, "Int", 2, "Int", 2, "Ptr", a, "Int", 0, "Int", 0, "UInt", 0xCC0020)
r1 := Format("{:06X} {:06X}", DllCall("GetPixel", "Ptr", b, "Int", 2, "Int", 2, "UInt"), DllCall("GetPixel", "Ptr", b, "Int", 3, "Int", 3, "UInt"))
DllCall("BitBlt", "Ptr", b, "Int", 2, "Int", 2, "Int", 2, "Int", 2, "Ptr", a, "Int", 0, "Int", 0, "UInt", 0x660046)
r2 := Format("{:06X}", DllCall("GetPixel", "Ptr", b, "Int", 2, "Int", 2, "UInt"))
m1 := DllCall("SetStretchBltMode", "Ptr", b, "Int", 4)
m2 := DllCall("SetStretchBltMode", "Ptr", b, "Int", 3)
DllCall("StretchBlt", "Ptr", b, "Int", 0, "Int", 0, "Int", 4, "Int", 4, "Ptr", a, "Int", 0, "Int", 0, "Int", 2, "Int", 2, "UInt", 0xCC0020)
s := ""
for xy in [[0, 0], [1, 1], [2, 2], [3, 3], [3, 0]]
    s .= Format("{:06X} ", DllCall("GetPixel", "Ptr", b, "Int", xy[1], "Int", xy[2], "UInt"))
out(r1 " " r2 " " m1 " " m2 " | " s)
;; expect: 0000FF 00FF00 000000 1 4 | 0000FF 0000FF 00FF00 00FF00 000000 

;; test: GetDIBits fills the header, then copies bottom-up rows
hdc := DllCall("CreateCompatibleDC", "Ptr", 0, "Ptr")
hbm := DllCall("CreateCompatibleBitmap", "Ptr", hdc, "Int", 2, "Int", 3, "Ptr")
DllCall("SelectObject", "Ptr", hdc, "Ptr", hbm)
DllCall("SetPixel", "Ptr", hdc, "Int", 0, "Int", 0, "UInt", 0x0000FF)
DllCall("SetPixel", "Ptr", hdc, "Int", 1, "Int", 2, "UInt", 0xFF0000)
bi := Buffer(40, 0), NumPut("UInt", 40, bi)
lines0 := DllCall("GetDIBits", "Ptr", hdc, "Ptr", hbm, "UInt", 0, "UInt", 0, "Ptr", 0, "Ptr", bi, "UInt", 0)
hdr := NumGet(bi, 4, "Int") "x" NumGet(bi, 8, "Int") " " NumGet(bi, 14, "UShort")
NumPut("Int", 3, bi, 8), NumPut("UShort", 32, bi, 14), NumPut("UInt", 0, bi, 16)
px := Buffer(2 * 3 * 4, 0)
lines := DllCall("GetDIBits", "Ptr", hdc, "Ptr", hbm, "UInt", 0, "UInt", 3, "Ptr", px, "Ptr", bi, "UInt", 0)
first := NumGet(px, 4, "UInt") & 0xFFFFFF, last := NumGet(px, 2 * 2 * 4, "UInt") & 0xFFFFFF
NumPut("Int", -3, bi, 8)
DllCall("GetDIBits", "Ptr", hdc, "Ptr", hbm, "UInt", 0, "UInt", 3, "Ptr", px, "Ptr", bi, "UInt", 0)
td := NumGet(px, 0, "UInt") & 0xFFFFFF
out(lines0 " " hdr " " lines " " Format("{:06X} {:06X} {:06X}", first, last, td))
;; expect: 3 2x3 32 3 0000FF FF0000 FF0000

;; test: SelectObject returns the previous bitmap; DeleteObject refuses a selected bitmap
hdc := DllCall("CreateCompatibleDC", "Ptr", 0, "Ptr")
b1 := DllCall("CreateCompatibleBitmap", "Ptr", hdc, "Int", 2, "Int", 2, "Ptr")
b2 := DllCall("CreateCompatibleBitmap", "Ptr", hdc, "Int", 2, "Int", 2, "Ptr")
stock := DllCall("SelectObject", "Ptr", hdc, "Ptr", b1, "Ptr")
p1 := DllCall("SelectObject", "Ptr", hdc, "Ptr", b2, "Ptr")
d2 := DllCall("DeleteObject", "Ptr", b2)
DllCall("SelectObject", "Ptr", hdc, "Ptr", stock, "Ptr")
d2b := DllCall("DeleteObject", "Ptr", b2)
t := DllCall("GetObjectType", "Ptr", hdc), t2 := DllCall("GetObjectType", "Ptr", b1)
out((p1 = b1) " " d2 " " d2b " " DllCall("DeleteDC", "Ptr", hdc) " " t " " t2)
;; expect: 1 0 1 1 10 7

;; test: Screen capture with GetDC, BitBlt and PrintWindow from a Gui window
g := Gui("-Caption +AlwaysOnTop +ToolWindow")
g.BackColor := "FF0000"
g.Show("x40 y40 w60 h40 NA")
Sleep 400
WinGetClientPos(&cx, &cy, , , g)
hdc := DllCall("CreateCompatibleDC", "Ptr", 0, "Ptr")
DllCall("SelectObject", "Ptr", hdc, "Ptr", DllCall("CreateCompatibleBitmap", "Ptr", hdc, "Int", 10, "Int", 10, "Ptr"))
sdc := DllCall("GetDC", "Ptr", 0, "Ptr")
DllCall("BitBlt", "Ptr", hdc, "Int", 0, "Int", 0, "Int", 10, "Int", 10, "Ptr", sdc, "Int", cx + 20, "Int", cy + 10, "UInt", 0x40CC0020)
a := DllCall("GetPixel", "Ptr", hdc, "Int", 5, "Int", 5, "UInt")
DllCall("ReleaseDC", "Ptr", 0, "Ptr", sdc)
wdc := DllCall("GetDC", "Ptr", g.Hwnd, "Ptr")
b := DllCall("GetPixel", "Ptr", wdc, "Int", 30, "Int", 20, "UInt")
DllCall("ReleaseDC", "Ptr", g.Hwnd, "Ptr", wdc)
pdc := DllCall("CreateCompatibleDC", "Ptr", 0, "Ptr")
DllCall("SelectObject", "Ptr", pdc, "Ptr", DllCall("CreateCompatibleBitmap", "Ptr", pdc, "Int", 60, "Int", 40, "Ptr"))
ok := DllCall("PrintWindow", "Ptr", g.Hwnd, "Ptr", pdc, "UInt", 1)
c := DllCall("GetPixel", "Ptr", pdc, "Int", 30, "Int", 20, "UInt")
g.Destroy()
out(Format("{:06X} {:06X} {} {:06X}", a, b, ok, c))
;; expect: 0000FF 0000FF 1 0000FF

;; test: A GDI bitmap shown by a Picture control (HBITMAP:)
hdc := DllCall("CreateCompatibleDC", "Ptr", 0, "Ptr")
hbm := DllCall("CreateCompatibleBitmap", "Ptr", hdc, "Int", 20, "Int", 10, "Ptr")
g := Gui()
pic := g.Add("Picture", "x0 y0", "HBITMAP:*" hbm)
pic.GetPos(, , &w, &h)
g.Destroy()
out(w "x" h)
;; expect: 20x10

;; test: Events: manual and auto-reset, and a timer signalling a waiting thread
man := DllCall("CreateEvent", "Ptr", 0, "Int", 1, "Int", 0, "Ptr", 0, "Ptr")
auto := DllCall("CreateEvent", "Ptr", 0, "Int", 0, "Int", 1, "Ptr", 0, "Ptr")
w0 := DllCall("WaitForSingleObject", "Ptr", man, "UInt", 0)
a1 := DllCall("WaitForSingleObject", "Ptr", auto, "UInt", 0)
a2 := DllCall("WaitForSingleObject", "Ptr", auto, "UInt", 0)
DllCall("SetEvent", "Ptr", man)
m1 := DllCall("WaitForSingleObject", "Ptr", man, "UInt", 0)
m2 := DllCall("WaitForSingleObject", "Ptr", man, "UInt", 0)
DllCall("ResetEvent", "Ptr", man)
SetTimer(() => DllCall("SetEvent", "Ptr", man), -100)
t := A_TickCount
r := DllCall("WaitForSingleObject", "Ptr", man, "UInt", 3000)
out(w0 " " a1 " " a2 " " m1 " " m2 " " r " " (A_TickCount - t < 2000) " " DllCall("CloseHandle", "Ptr", man))
;; expect: 258 0 258 0 0 0 1 1

;; test: Named mutex: ERROR_ALREADY_EXISTS, ownership and ReleaseMutex errors
name := "BHK-conformance-" A_TickCount
m := DllCall("CreateMutex", "Ptr", 0, "Int", 1, "Str", name, "Ptr")
e1 := A_LastError
m2 := DllCall("CreateMutex", "Ptr", 0, "Int", 0, "Str", name, "Ptr")
e2 := A_LastError
w := DllCall("WaitForSingleObject", "Ptr", m2, "UInt", 0)
r1 := DllCall("ReleaseMutex", "Ptr", m)
r2 := DllCall("ReleaseMutex", "Ptr", m)
r3 := DllCall("ReleaseMutex", "Ptr", m)
e3 := A_LastError
o := DllCall("OpenMutex", "UInt", 0x1F0001, "Int", 0, "Str", name, "Ptr")
DllCall("CloseHandle", "Ptr", m), DllCall("CloseHandle", "Ptr", m2), DllCall("CloseHandle", "Ptr", o)
o2 := DllCall("OpenMutex", "UInt", 0x1F0001, "Int", 0, "Str", name, "Ptr")
e4 := A_LastError
out(e1 " " e2 " " (m != m2) " " w " " r1 " " r2 " " r3 " " e3 " " (o != 0) " " o2 " " e4)
;; expect: 0 183 1 0 1 1 0 288 1 0 2

;; test: Semaphores and WaitForMultipleObjects
s := DllCall("CreateSemaphore", "Ptr", 0, "Int", 2, "Int", 3, "Ptr", 0, "Ptr")
w1 := DllCall("WaitForSingleObject", "Ptr", s, "UInt", 0)
w2 := DllCall("WaitForSingleObject", "Ptr", s, "UInt", 0)
w3 := DllCall("WaitForSingleObject", "Ptr", s, "UInt", 0)
r1 := DllCall("ReleaseSemaphore", "Ptr", s, "Int", 1, "Int*", &prev := -1)
r2 := DllCall("ReleaseSemaphore", "Ptr", s, "Int", 5, "Ptr", 0)
e := A_LastError
e1 := DllCall("CreateEvent", "Ptr", 0, "Int", 1, "Int", 0, "Ptr", 0, "Ptr")
e2 := DllCall("CreateEvent", "Ptr", 0, "Int", 1, "Int", 1, "Ptr", 0, "Ptr")
hs := Buffer(16), NumPut("Ptr", e1, "Ptr", e2, hs)
anyw := DllCall("WaitForMultipleObjects", "UInt", 2, "Ptr", hs, "Int", 0, "UInt", 0)
all := DllCall("WaitForMultipleObjects", "UInt", 2, "Ptr", hs, "Int", 1, "UInt", 0)
DllCall("SetEvent", "Ptr", e1)
all2 := DllCall("WaitForMultipleObjects", "UInt", 2, "Ptr", hs, "Int", 1, "UInt", 0)
t := A_TickCount
idle := DllCall("MsgWaitForMultipleObjects", "UInt", 0, "Ptr", 0, "Int", 0, "UInt", 50, "UInt", 0x4FF)
out(w1 " " w2 " " w3 " " r1 " " prev " " r2 " " e " | " anyw " " all " " all2 " " idle " " (A_TickCount - t >= 40))
;; expect: 0 0 258 1 0 0 298 | 1 258 0 258 1

;; test: MultiByteToWideChar and WideCharToMultiByte
src := Buffer(11), StrPut("héllo €", src, "UTF-8")
n := DllCall("MultiByteToWideChar", "UInt", 65001, "UInt", 0, "Ptr", src, "Int", -1, "Ptr", 0, "Int", 0)
w := Buffer(n * 2)
n2 := DllCall("MultiByteToWideChar", "UInt", 65001, "UInt", 0, "Ptr", src, "Int", -1, "Ptr", w, "Int", n)
m := DllCall("WideCharToMultiByte", "UInt", 65001, "UInt", 0, "Str", "héllo €", "Int", -1, "Ptr", 0, "Int", 0, "Ptr", 0, "Ptr", 0)
k := DllCall("WideCharToMultiByte", "UInt", 1252, "UInt", 0, "Str", "aΩ€", "Int", 3, "Ptr", 0, "Int", 0, "Ptr", 0, "Ptr", 0)
b := Buffer(3, 0)
DllCall("WideCharToMultiByte", "UInt", 1252, "UInt", 0, "Str", "aΩ€", "Int", 3, "Ptr", b, "Int", 3, "Ptr", 0, "Int*", &used := 0)
small := DllCall("MultiByteToWideChar", "UInt", 65001, "UInt", 0, "Ptr", src, "Int", -1, "Ptr", w, "Int", 2)
e := A_LastError
out(n " " n2 " " StrGet(w, "UTF-16") " " m " " k " " Format("{:02X}{:02X}{:02X}", NumGet(b, 0, "UChar"), NumGet(b, 1, "UChar"), NumGet(b, 2, "UChar")) " " used " " small " " e)
;; expect: 8 8 héllo € 11 3 613F80 1 0 122

;; test: GetCPInfo for UTF-8, Windows-1252 and Shift-JIS
info := Buffer(20, 0)
r := ""
for cp in [65001, 1252, 932] {
    DllCall("GetCPInfo", "UInt", cp, "Ptr", info)
    r .= NumGet(info, 0, "UInt") " "
}
out(r Format("{:02X}-{:02X}", NumGet(info, 6, "UChar"), NumGet(info, 7, "UChar")))
;; expect: 4 1 2 81-9F

;; test: FormatMessage from the system table, with ALLOCATE_BUFFER, and from a string with inserts
n := DllCall("FormatMessage", "UInt", 0x1200, "Ptr", 0, "UInt", 2, "UInt", 0, "Ptr", buf := Buffer(512), "UInt", 256, "Ptr", 0)
s := StrGet(buf)
n2 := DllCall("FormatMessage", "UInt", 0x1300, "Ptr", 0, "UInt", 5, "UInt", 0, "Ptr*", &p := 0, "UInt", 0, "Ptr", 0)
s2 := StrGet(p)
DllCall("LocalFree", "Ptr", p)
args := Buffer(16), NumPut("Ptr", StrPtr("disk"), "Ptr", 42, args)
n3 := DllCall("FormatMessage", "UInt", 0x2400, "Str", "%1 has %2!d! files%%%0 ignored", "UInt", 0, "UInt", 0, "Ptr", buf, "UInt", 256, "Ptr", args)
s3 := StrGet(buf)
n4 := DllCall("FormatMessage", "UInt", 0x1200, "Ptr", 0, "UInt", 0x7FFF0, "UInt", 0, "Ptr", buf, "UInt", 256, "Ptr", 0)
out(n " " (s = "The system cannot find the file specified.`r`n") " " n2 " " s2 n3 " " s3 " " n4 " " A_LastError)
;; expect: 44 1 19 Access is denied.
;; expect: 18 disk has 42 files% 0 317

;; test: DwmGetWindowAttribute frame bounds, DwmIsCompositionEnabled, EnumDisplayMonitors
g := Gui()
g.Show("x50 y60 w120 h80 NA")
Sleep 300
WinGetPos(&x, &y, &w, &h, g)
rc := Buffer(16, 0)
hr := DllCall("dwmapi\DwmGetWindowAttribute", "Ptr", g.Hwnd, "UInt", 9, "Ptr", rc, "UInt", 16)
same := NumGet(rc, 0, "Int") = x && NumGet(rc, 4, "Int") = y && NumGet(rc, 8, "Int") = x + w && NumGet(rc, 12, "Int") = y + h
DllCall("dwmapi\DwmIsCompositionEnabled", "Int*", &on := 0)
g.Destroy()
mons := []
cb := CallbackCreate((hMon, hdc, prc, lp) => (mons.Push(NumGet(prc, 0, "Int") "," NumGet(prc, 4, "Int") "," NumGet(prc, 8, "Int") "," NumGet(prc, 12, "Int")), 1), , 4)
DllCall("EnumDisplayMonitors", "Ptr", 0, "Ptr", 0, "Ptr", cb, "Ptr", 0)
CallbackFree(cb)
MonitorGet(1, &l, &t, &r, &b)
out(hr " " same " " on " " (mons.Length = MonitorGetCount()) " " (mons[1] = l "," t "," r "," b))
;; expect: 0 1 1 1 1

;; test: SetWinEventHook reports a title change of a window
got := []
cb := CallbackCreate((hook, ev, hwnd, idObj, idChild, thread, time) => got.Push(Format("{:X}", ev) " " (hwnd = g.Hwnd)), , 7)
g := Gui(, "before")
g.Show("w100 h50 NA")
Sleep 300
hook := DllCall("SetWinEventHook", "UInt", 0x800C, "UInt", 0x800C, "Ptr", 0, "Ptr", cb, "UInt", 0, "UInt", 0, "UInt", 0, "Ptr")
WinSetTitle("after", g)
Sleep 500
u := DllCall("UnhookWinEvent", "Ptr", hook)
g.Destroy()
out((hook != 0) " " (got.Length ? got[1] : "none") " " u)
;; expect: 1 800C 1 1

;; test: HSTRINGs, RtlComputeCrc32, GetKeyboardLayout
DllCall("combase\WindowsCreateString", "Str", "hello", "UInt", 5, "Ptr*", &hs := 0)
p := DllCall("combase\WindowsGetStringRawBuffer", "Ptr", hs, "UInt*", &len := 0, "Ptr")
s := StrGet(p, len, "UTF-16")
DllCall("combase\WindowsDeleteString", "Ptr", hs)
b := Buffer(3), StrPut("abc", b, 3, "UTF-8")
crc := DllCall("ntdll\RtlComputeCrc32", "UInt", 0, "Ptr", b, "UInt", 3, "UInt")
hkl := DllCall("GetKeyboardLayout", "UInt", 0, "Ptr")
out(s " " len " " Format("{:08X}", crc) " " ((hkl & 0xFFFF) = Integer("0x" A_Language)))
;; expect: hello 5 352441C2 1

;; test: GUIDs: CLSIDFromString, StringFromGUID2, IIDFromString, CoCreateGuid, CoTaskMem, SysAllocString
g := Buffer(16)
hr := DllCall("ole32\CLSIDFromString", "Str", "{00020400-0000-0000-C000-000000000046}", "Ptr", g)
d1 := Format("{:08X}", NumGet(g, 0, "UInt"))
s := Buffer(78)
n := DllCall("ole32\StringFromGUID2", "Ptr", g, "Ptr", s, "Int", 39)
iid := Buffer(16)
hr2 := DllCall("ole32\IIDFromString", "Str", "{00000000-0000-0000-C000-000000000046}", "Ptr", iid)
DllCall("ole32\CoCreateGuid", "Ptr", ng := Buffer(16, 0))
ver := (NumGet(ng, 7, "UChar") >> 4)
p := DllCall("ole32\CoTaskMemAlloc", "UPtr", 32, "Ptr")
NumPut("Int64", 77, p), v := NumGet(p, "Int64")
DllCall("ole32\CoTaskMemFree", "Ptr", p)
bs := DllCall("oleaut32\SysAllocString", "Str", "bstr", "Ptr")
blen := NumGet(bs, -4, "UInt")
DllCall("oleaut32\SysFreeString", "Ptr", bs)
out(hr " " d1 " " n " " StrGet(s) " " hr2 " " NumGet(iid, 8, "UChar") " " ver " " v " " blen)
;; expect: 0 00020400 39 {00020400-0000-0000-C000-000000000046} 0 192 4 77 8

;; test: GetCursorPos, QueryPerformanceCounter/Frequency, SetLastError
CoordMode("Mouse", "Screen")
MouseGetPos(&mx, &my)
pt := Buffer(8)
DllCall("GetCursorPos", "Ptr", pt)
DllCall("QueryPerformanceFrequency", "Int64*", &f := 0)
DllCall("QueryPerformanceCounter", "Int64*", &c1 := 0)
Sleep 50
DllCall("QueryPerformanceCounter", "Int64*", &c2 := 0)
ms := (c2 - c1) * 1000 // f
DllCall("SetLastError", "UInt", 1234)
e := A_LastError
out((NumGet(pt, 0, "Int") = mx) " " (NumGet(pt, 4, "Int") = my) " " (f > 0) " " (ms >= 45 && ms < 1000) " " e)
;; expect: 1 1 1 1 1234

;; test: Window handles: GetForegroundWindow, GetDesktopWindow, GetWindow, IsWindowVisible, GetWindowText, SetWindowPos
g := Gui(, "dllcall-window-test")
g.Show("x100 y100 w150 h90")
WinWaitActive(g, , 3)
fg := DllCall("GetForegroundWindow", "Ptr")
desk := DllCall("GetDesktopWindow", "Ptr")
nxt := DllCall("GetWindow", "Ptr", g.Hwnd, "UInt", 2, "Ptr")
back := nxt ? DllCall("GetWindow", "Ptr", nxt, "UInt", 3, "Ptr") : g.Hwnd
vis := DllCall("IsWindowVisible", "Ptr", g.Hwnd)
buf := Buffer(200)
n := DllCall("GetWindowText", "Ptr", g.Hwnd, "Ptr", buf, "Int", 100)
DllCall("SetWindowPos", "Ptr", g.Hwnd, "Ptr", 0, "Int", 140, "Int", 130, "Int", 0, "Int", 0, "UInt", 0x15)
Sleep 300
WinGetPos(&x, &y, &w, &h, g)
g.Hide()
Sleep 200
vis2 := DllCall("IsWindowVisible", "Ptr", g.Hwnd)
g.Destroy()
out((fg = g.Hwnd) " " (desk != 0 && desk != g.Hwnd) " " (back = g.Hwnd) " " vis " " n " " StrGet(buf) " " x "," y " " vis2)
;; expect: 1 1 1 1 19 dllcall-window-test 140,130 0

;; test: SendMessage WM_SETTEXT / WM_GETTEXTLENGTH to a Gui control
g := Gui()
e := g.Add("Edit", "w100")
r := DllCall("SendMessage", "Ptr", e.Hwnd, "UInt", 0x0C, "Ptr", 0, "Str", "via sendmessage")
n := DllCall("SendMessage", "Ptr", e.Hwnd, "UInt", 0x0E, "Ptr", 0, "Ptr", 0)
t := e.Value
g.Destroy()
out(r " " n " " t)
;; expect: 1 15 via sendmessage

;; test: More DCs and bitmaps: GetWindowDC, GetDCEx, CreateDC, CreateBitmap, SetBitmapBits, CopyImage
g := Gui("-Caption")
g.BackColor := "00FF00"
g.Show("x60 y60 w40 h30 NA")
Sleep 400
w1 := DllCall("GetWindowDC", "Ptr", g.Hwnd, "Ptr")
w2 := DllCall("GetDCEx", "Ptr", g.Hwnd, "Ptr", 0, "UInt", 0x2, "Ptr")
c1 := DllCall("GetPixel", "Ptr", w1, "Int", 20, "Int", 15, "UInt")
c2 := DllCall("GetPixel", "Ptr", w2, "Int", 20, "Int", 15, "UInt")
sd := DllCall("CreateDC", "Str", "DISPLAY", "Ptr", 0, "Ptr", 0, "Ptr", 0, "Ptr")
WinGetClientPos(&cx, &cy, , , g)
c3 := DllCall("GetPixel", "Ptr", sd, "Int", cx + 5, "Int", cy + 5, "UInt")
DllCall("ReleaseDC", "Ptr", g.Hwnd, "Ptr", w1), DllCall("ReleaseDC", "Ptr", g.Hwnd, "Ptr", w2), DllCall("DeleteDC", "Ptr", sd)
g.Destroy()
px := Buffer(8), NumPut("UInt", 0x00FF0000, "UInt", 0x000000FF, px)
hb := DllCall("CreateBitmap", "Int", 2, "Int", 1, "UInt", 1, "UInt", 32, "Ptr", px, "Ptr")
hdc := DllCall("CreateCompatibleDC", "Ptr", 0, "Ptr")
big := DllCall("CopyImage", "Ptr", hb, "UInt", 0, "Int", 4, "Int", 2, "UInt", 0, "Ptr")
DllCall("SelectObject", "Ptr", hdc, "Ptr", big)
a := DllCall("GetPixel", "Ptr", hdc, "Int", 1, "Int", 1, "UInt"), b := DllCall("GetPixel", "Ptr", hdc, "Int", 3, "Int", 0, "UInt")
NumPut("UInt", 0x00123456, px, 0)
DllCall("SelectObject", "Ptr", hdc, "Ptr", hb)
n := DllCall("SetBitmapBits", "Ptr", hb, "UInt", 8, "Ptr", px)
c := DllCall("GetPixel", "Ptr", hdc, "Int", 0, "Int", 0, "UInt")
out(Format("{:06X} {:06X} {:06X} | {:06X} {:06X} {} {:06X}", c1, c2, c3, a, b, n, c))
;; expect: 00FF00 00FF00 00FF00 | 0000FF FF0000 8 563412

;; test: MonitorFromPoint, Toolhelp module and thread lists, GetPriorityClass, GetOEMCP
MonitorGet(1, &l, &t)
hm := DllCall("MonitorFromPoint", "Int64", (t + 1) << 32 | (l + 1), "UInt", 0, "Ptr")
mi := Buffer(40, 0), NumPut("UInt", 40, mi)
DllCall("GetMonitorInfo", "Ptr", hm, "Ptr", mi)
off := DllCall("MonitorFromPoint", "Int64", -100000, "UInt", 0, "Ptr")
pid := ProcessExist()
snap := DllCall("CreateToolhelp32Snapshot", "UInt", 0x8, "UInt", pid, "Ptr")
me := Buffer(1080, 0), NumPut("UInt", 1080, me)
mods := 0, ok := DllCall("Module32FirstW", "Ptr", snap, "Ptr", me)
while ok
    mods++, ok := DllCall("Module32NextW", "Ptr", snap, "Ptr", me)
DllCall("CloseHandle", "Ptr", snap)
snap := DllCall("CreateToolhelp32Snapshot", "UInt", 0x4, "UInt", 0, "Ptr")
te := Buffer(28, 0), NumPut("UInt", 28, te)
mine := 0, ok := DllCall("Thread32First", "Ptr", snap, "Ptr", te)
while ok
    mine += NumGet(te, 12, "UInt") = pid, ok := DllCall("Thread32Next", "Ptr", snap, "Ptr", te)
DllCall("CloseHandle", "Ptr", snap)
pc := DllCall("GetPriorityClass", "Ptr", -1, "UInt")
out((NumGet(mi, 4, "Int") = l) " " off " " (mods >= 1) " " (mine >= 1) " " Format("{:X}", pc) " " DllCall("GetOEMCP"))
;; expect: 1 0 1 1 20 437

;; test: OpenProcess and TerminateProcess on a child, OpenSemaphore by name, SearchPath
Run("sleep 30", , , &child)
h := DllCall("OpenProcess", "UInt", 0x1F0FFF, "Int", 0, "UInt", child, "Ptr")
t := DllCall("TerminateProcess", "Ptr", h, "UInt", 1)
w := DllCall("WaitForSingleObject", "Ptr", h, "UInt", 3000)
DllCall("CloseHandle", "Ptr", h)
name := "BHK-sem-" A_TickCount
s := DllCall("CreateSemaphore", "Ptr", 0, "Int", 1, "Int", 1, "Str", name, "Ptr")
o := DllCall("OpenSemaphore", "UInt", 0x1F0003, "Int", 0, "Str", name, "Ptr")
w1 := DllCall("WaitForSingleObject", "Ptr", o, "UInt", 0)
w2 := DllCall("WaitForSingleObject", "Ptr", s, "UInt", 0)
miss := DllCall("OpenSemaphore", "UInt", 0x1F0003, "Int", 0, "Str", name "-missing", "Ptr")
e := A_LastError
FileAppend("x", A_WorkingDir "\sp.txt")
need := DllCall("SearchPath", "Str", A_WorkingDir, "Str", "sp", "Str", ".txt", "UInt", 0, "Ptr", 0, "Ptr", 0)
buf := Buffer(need * 2)
n := DllCall("SearchPath", "Str", A_WorkingDir, "Str", "sp", "Str", ".txt", "UInt", need, "Ptr", buf, "Ptr", 0)
out(t " " w " " (o != 0) " " w1 " " w2 " " miss " " e " " (n = need - 1) " " (FileExist(StrGet(buf)) != "" && InStr(StrGet(buf), "sp.txt") > 0))
;; expect: 1 0 1 0 258 0 2 1 1
