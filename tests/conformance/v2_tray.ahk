;; suite: v2 desktop tray
; AutoHotkey v2.0 tray icon and tray menu on the real desktop (tools/conformance.py).
; tools/x11_tray_probe.py finds this script's icon in the panel's tray by process ID.

Probe() {
    tmp := A_Temp "/bhk_probe_" ProcessExist() ".txt"     ; passed to sh, so a / path
    code := RunWait('sh -c "python3 \"' EnvGet("BHK_ROOT") '/tools/x11_tray_probe.py\" ' ProcessExist() ' > \"' tmp '\""',, "Hide")
    pos := FileExist(tmp) ? Trim(FileRead(tmp), " `r`n") : ""
    try FileDelete(tmp)
    return code = 0 ? pos : ""
}

;; test: the tray icon is embedded in the desktop's tray
Persistent
SetTimer(Check, -1500)
Check() {
    out(Probe() != "")
    ExitApp
}
return
;; expect: 1

;; test: A_IconHidden removes the icon
Persistent
SetTimer(Check, -1500)
Check() {
    a := Probe() != ""
    A_IconHidden := true
    Sleep(800)
    b := Probe() = ""
    out(a " " b " " A_IconHidden)
    ExitApp
}
return
;; expect: 1 1 1

;; test: TraySetIcon sets A_IconFile and A_IconNumber
FileAppend("", "dummy.ico")
TraySetIcon(A_WorkingDir "\dummy.ico", 3)
SplitPath(A_IconFile, &n)
out(n " " A_IconNumber)
;; expect: dummy.ico 3

;; test: A_IconTip
A_IconTip := "BHK tip"
out(A_IconTip)
;; expect: BHK tip

;; test: A_TrayMenu standard items and editing
m := A_TrayMenu
n0 := DllCall("GetMenuItemCount", "Ptr", m.Handle)
m.Add()
m.Add("Custom", (*) => 0)
m.Insert("1&", "First", (*) => 0)
m.Rename("Custom", "Renamed")
m.Check("Renamed")
m.Delete("First")
n1 := DllCall("GetMenuItemCount", "Ptr", m.Handle)
m.Delete()
n2 := DllCall("GetMenuItemCount", "Ptr", m.Handle)
m.AddStandard()
out(n0 " " (n1 = n0 + 2) " " n2 " " (DllCall("GetMenuItemCount", "Ptr", m.Handle) = n0))
;; expect: 10 1 0 1

;; test: clicking the tray icon runs the default menu item
A_TrayMenu.Add("Clicked", (*) => (out("tray item ran"), ExitApp()))
A_TrayMenu.Default := "Clicked"
A_TrayMenu.ClickCount := 1
Persistent
SetTimer(ClickIt, -1500)
ClickIt() {
    pos := StrSplit(Probe(), " ")
    if pos.Length < 2 {
        out("no icon")
        ExitApp
    }
    CoordMode("Mouse", "Screen")
    MouseGetPos(&ox, &oy)
    Click(pos[1], pos[2])
    MouseMove(ox, oy, 0)
    Sleep(1500)
    out("no menu item")
    ExitApp
}
return
;; expect: tray item ran

;; test: OnMessage receives tray mouse messages (AHK_NOTIFYICON)
OnMessage(0x404, Notify)
Notify(wParam, lParam, *) {
    if (lParam = 0x202) {          ; WM_LBUTTONUP
        out("notify " Format("{:#x}", lParam))
        ExitApp
    }
}
A_TrayMenu.ClickCount := 2
Persistent
SetTimer(ClickIt, -1500)
ClickIt() {
    pos := StrSplit(Probe(), " ")
    if pos.Length < 2 {
        out("no icon")
        ExitApp
    }
    CoordMode("Mouse", "Screen")
    MouseGetPos(&ox, &oy)
    Click(pos[1], pos[2])
    MouseMove(ox, oy, 0)
    Sleep(1500)
    out("no message")
    ExitApp
}
return
;; expect: notify 0x202

;; test: TrayTip with title and options
TrayTip("BHK", "tray balloon", "Iconi Mute")
Sleep(300)
TrayTip()
out("ok")
;; expect: ok
