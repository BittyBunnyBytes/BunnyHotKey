;; suite: v2 display serial
; AutoHotkey v2.0 processes, registry, sound, system info, monitors, clipboard and Download.
; Not run here: Shutdown. Sound checks restore the previous volume/mute; clipboard checks restore the clipboard.

;; test: Run with an output PID, ProcessExist, ProcessWaitClose
Run("sleep 0.3",, "Hide", &pid)
e := ProcessExist(pid) = pid
r := ProcessWaitClose(pid, 3)
out(e " " (pid > 0) " " r " " ProcessExist(pid))
;; expect: 1 1 0 0

;; test: RunWait returns the exit code
out(RunWait('sh -c "exit 7"',, "Hide"))
;; expect: 7

;; test: Run with a working directory
DirCreate("wdir")
RunWait('sh -c "pwd > out.txt"', "wdir", "Hide")
SplitPath(Trim(FileRead("wdir\out.txt"), "`n"), &name)
out(name)
;; expect: wdir

;; test: Run of a missing program throws
try
    Run("bhk_no_such_program_xyz")
catch Error
    out("error")
;; expect: error

;; test: ProcessGetName, ProcessGetPath, ProcessGetParent
Run("sleep 2",, "Hide", &pid)
n := ProcessGetName(pid)
p := ProcessGetPath(pid)
par := ProcessGetParent(pid)
ProcessClose(pid)
out(n " " (InStr(p, "sleep") > 0) " " (par = DllCall("GetCurrentProcessId") || par > 0))
;; expect: sleep 1 1

;; test: ProcessWait finds a started process
Run("sleep 1",, "Hide", &pid)
out(ProcessWait(pid, 2) = pid)
ProcessClose(pid)
;; expect: 1

;; test: ProcessClose ends a process and returns its PID
Run("sleep 5",, "Hide", &pid)
c := ProcessClose(pid)
ProcessWaitClose(pid, 2)
out((c = pid) " " ProcessExist(pid))
;; expect: 1 0

;; test: ProcessSetPriority
Run("sleep 2",, "Hide", &pid)
ProcessSetPriority("Low", pid)
out("ok")
ProcessClose(pid)
;; expect: ok

;; test: RunAs without arguments is accepted
RunAs()
out("ok")
;; expect: ok

;; test: RegWrite, RegRead, RegDelete
k := "HKCU\Software\BHKConformance"
RegWrite("hello", "REG_SZ", k, "Str")
RegWrite(42, "REG_DWORD", k, "Num")
a := RegRead(k, "Str")
b := RegRead(k, "Num")
d := RegRead(k, "Missing", "dflt")
RegDelete(k, "Str")
try
    RegRead(k, "Str")
catch OSError
    gone := 1
RegDeleteKey(k)
out(a " " b " " d " " gone)
;; expect: hello 42 dflt 1

;; test: RegCreateKey and Loop Reg
k := "HKCU\Software\BHKConformance2"
RegCreateKey(k "\Sub")
RegWrite("v", "REG_SZ", k, "Val")
s := ""
Loop Reg, k, "KV"
    s .= A_LoopRegName ":" A_LoopRegType " "
RegDeleteKey(k)
out(Trim(s))
;; expect: Val:REG_SZ Sub:KEY

;; test: SetRegView
SetRegView(32)
v := A_RegView
SetRegView("Default")
out(v " " A_RegView)
;; expect: 32 Default

;; test: SysGet screen metrics
out((SysGet(0) > 0) " " (SysGet(1) > 0) " " (SysGet(80) >= 1))
;; expect: 1 1 1

;; test: SysGetIPAddresses
a := SysGetIPAddresses()
out(Type(a) " " (a.Length >= 0))
;; expect: Array 1

;; test: MonitorGet, MonitorGetWorkArea, count, primary and name
n := MonitorGetCount()
p := MonitorGetPrimary()
MonitorGet(p, &l, &t, &r, &b)
MonitorGetWorkArea(p, &wl, &wt, &wr, &wb)
out((n >= 1) " " (p >= 1) " " (r > l) " " (b > t) " " (wr - wl <= r - l) " " (MonitorGetName(p) != ""))
;; expect: 1 1 1 1 1 1

;; test: SoundGetVolume and SoundSetVolume round trip
v := SoundGetVolume()
SoundSetVolume(Max(v - 1, 0))
w := SoundGetVolume()
SoundSetVolume(v)
out((Abs(w - Max(v - 1, 0)) < 1.5) " " (Abs(SoundGetVolume() - v) < 1.5))
;; expect: 1 1

;; test: SoundGetMute and SoundSetMute round trip
m := SoundGetMute()
SoundSetMute(!m)
m2 := SoundGetMute()
SoundSetMute(m)
out((m2 = !m) " " (SoundGetMute() = m))
;; expect: 1 1

;; test: SoundGetName and SoundGetInterface
n := SoundGetName()
i := SoundGetInterface("{5CDF2C82-841E-4546-9722-0CF74078229A}")
out((n != "") " " (i != 0))
;; expect: 1 1

;; test: SoundBeep and SoundPlay of a WAV file
b := Buffer(44 + 800, 0)
StrPut("RIFF", b, 4, "CP0"), NumPut("UInt", 36 + 800, b, 4), StrPut("WAVEfmt ", b.Ptr + 8, 8, "CP0")
NumPut("UInt", 16, "UShort", 1, "UShort", 1, "UInt", 8000, "UInt", 8000, "UShort", 1, "UShort", 8, b, 16)
StrPut("data", b.Ptr + 36, 4, "CP0"), NumPut("UInt", 800, b, 40)
f := FileOpen("quiet.wav", "w")
f.RawWrite(b)
f.Close()
SoundPlay("quiet.wav", 1)
SoundBeep(2000, 20)
out("played")
;; expect: played

;; test: A_Clipboard, ClipWait and ClipboardAll (restored)
saved := ClipboardAll()
A_Clipboard := ""
A_Clipboard := "bhk clip"
ok := ClipWait(2)
got := A_Clipboard
A_Clipboard := saved
out(ok " " got)
;; expect: 1 bhk clip

;; test: OnClipboardChange fires (clipboard restored)
saved := ClipboardAll()
OnClipboardChange(Changed)
Changed(type) {
    global fired := type
}
fired := ""
A_Clipboard := "changed text"
Sleep(500)
OnClipboardChange(Changed, 0)
A_Clipboard := saved
out(fired)
;; expect: 1

;; test: Download from a file URL
FileAppend("payload", "src.txt")
Download("file://" A_WorkingDir "/src.txt", "dl.txt")
out(FileRead("dl.txt"))
;; expect: payload

;; test: Download from a local HTTP server
FileAppend("served", "page.txt")
Run('python3 -m http.server 8765 --bind 127.0.0.1', A_WorkingDir, "Hide", &pid)
Sleep(1500)
try
    Download("http://127.0.0.1:8765/page.txt", "got.txt")
ProcessClose(pid)
out(FileExist("got.txt") ? FileRead("got.txt") : "missing")
;; expect: served

;; test: A_ComputerName, A_UserName, A_OSVersion, A_Is64bitOS
out((A_ComputerName != "") " " (A_UserName != "") " " (A_OSVersion != "") " " A_Is64bitOS)
;; expect: 1 1 1 1
