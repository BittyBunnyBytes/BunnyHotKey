;; suite: v2 desktop
; AutoHotkey v2.0 window functions on the real X11 desktop (tools/conformance.py). Every check uses
; BHK's own test windows (titles start with "BHKWin"); none touches other windows.
; Not run here: WinMinimizeAll / WinMinimizeAllUndo (they minimize every window on the desktop).

;; test: WinExist, WinGetTitle, WinGetClass, WinGetID
g := Gui(, "BHKWin Exist")
g.Show("w300 h150 NoActivate")
WinWait("BHKWin Exist",, 3)
id := WinExist("BHKWin Exist")
out((id = g.Hwnd) " " WinGetTitle("ahk_id " id) " " (WinGetClass("ahk_id " id) != "") " " (WinGetID("BHKWin Exist") = id))
;; expect: 1 BHKWin Exist 1 1

;; test: WinActivate and WinActive
g := Gui(, "BHKWin Activate")
g.Show("w300 h150")
WinActivate("ahk_id " g.Hwnd)
r := WinWaitActive("ahk_id " g.Hwnd,, 3)
out((r = g.Hwnd) " " (WinActive("A") = g.Hwnd))
;; expect: 1 1

;; test: WinMove and WinGetPos
g := Gui("-DPIScale", "BHKWin Move")
g.Show("w300 h150 x50 y60 NoActivate")
WinWait("BHKWin Move",, 3)
WinMove(120, 130, 400, 250, "BHKWin Move")
Sleep(300)
WinGetPos(&x, &y, &w, &h, "BHKWin Move")
out((Abs(x - 120) <= 2) " " (Abs(y - 130) <= 2) " " (w = 400) " " (h = 250))
;; expect: 1 1 1 1

;; test: WinGetClientPos is inside the window
g := Gui("-DPIScale", "BHKWin Client")
g.Show("w320 h180 NoActivate")
WinWait("BHKWin Client",, 3)
Sleep(200)
WinGetClientPos(&cx, &cy, &cw, &ch, "BHKWin Client")
WinGetPos(&x, &y, &w, &h, "BHKWin Client")
out((cw = 320) " " (ch = 180) " " (cx >= x) " " (cy >= y))
;; expect: 1 1 1 1

;; test: WinMinimize, WinRestore, WinMaximize, WinGetMinMax
g := Gui("+Resize", "BHKWin State")
g.Show("w300 h150 NoActivate")
WinWait("BHKWin State",, 3)
WinMinimize("BHKWin State")
Sleep(500)
a := WinGetMinMax("BHKWin State")
WinRestore("BHKWin State")
Sleep(500)
b := WinGetMinMax("BHKWin State")
WinMaximize("BHKWin State")
Sleep(500)
c := WinGetMinMax("BHKWin State")
WinRestore("BHKWin State")
out(a " " b " " c)
;; expect: -1 0 1

;; test: WinHide, WinShow and DetectHiddenWindows
g := Gui(, "BHKWin Hide")
g.Show("w300 h150 NoActivate")
WinWait("BHKWin Hide",, 3)
WinHide("BHKWin Hide")
Sleep(200)
DetectHiddenWindows(false)
a := WinExist("BHKWin Hide")
DetectHiddenWindows(true)
b := WinExist("BHKWin Hide") != 0
WinShow("BHKWin Hide")
DetectHiddenWindows(false)
Sleep(200)
out((a = 0) " " b " " (WinExist("BHKWin Hide") != 0))
;; expect: 1 1 1

;; test: WinClose and WinWaitClose
g := Gui(, "BHKWin Close")
g.OnEvent("Close", (*) => 0)
g.Show("w300 h150 NoActivate")
WinWait("BHKWin Close",, 3)
WinClose("BHKWin Close")
r := WinWaitClose("BHKWin Close",, 3)
out(r " " WinExist("BHKWin Close"))
;; expect: 1 0

;; test: WinKill on another script's window
; another script's window: WinKill of the script's own window would end the script itself, as in AutoHotkey
FileAppend('g := Gui(, "BHKWin Kill")`ng.Show("w300 h150 NoActivate")`nPersistent`n', "victim.ahk")
Run('"' A_AhkPath '" --no-tray victim.ahk',, "Hide", &pid)
WinWait("BHKWin Kill",, 10)
WinKill("BHKWin Kill")
out(WinWaitClose("BHKWin Kill",, 3) " " (ProcessWaitClose(pid, 3) = 0))
;; expect: 1 1

;; test: WinSetTitle
g := Gui(, "BHKWin Old")
g.Show("w300 h150 NoActivate")
WinWait("BHKWin Old",, 3)
WinSetTitle("BHKWin New", "BHKWin Old")
Sleep(200)
out(WinGetTitle("ahk_id " g.Hwnd) " " g.Title)
;; expect: BHKWin New BHKWin New

;; test: SetTitleMatchMode 1, 2, 3 and RegEx
g := Gui(, "BHKWin Match Title")
g.Show("w300 h150 NoActivate")
WinWait("BHKWin Match Title",, 3)
SetTitleMatchMode(1)
a := WinExist("BHKWin Match") != 0
b := WinExist("Match Title") != 0
SetTitleMatchMode(2)
c := WinExist("Match Title") != 0
SetTitleMatchMode(3)
d := WinExist("BHKWin Match") != 0
SetTitleMatchMode("RegEx")
e := WinExist("^BHKWin M.tch") != 0
out(a b c d e)
;; expect: 10101

;; test: ahk_pid, ahk_exe and WinGetPID / WinGetProcessName / WinGetProcessPath
g := Gui(, "BHKWin Proc")
g.Show("w300 h150 NoActivate")
WinWait("BHKWin Proc",, 3)
pid := WinGetPID("BHKWin Proc")
name := WinGetProcessName("BHKWin Proc")
path := WinGetProcessPath("BHKWin Proc")
out((pid > 0) " " (name != "") " " (path != "") " " (WinExist("BHKWin Proc ahk_pid " pid) = g.Hwnd) " " (WinExist("BHKWin Proc ahk_exe " name) = g.Hwnd))
;; expect: 1 1 1 1 1

;; test: WinGetCount, WinGetList, WinGetIDLast
g1 := Gui(, "BHKWin List")
g2 := Gui(, "BHKWin List")
g1.Show("w200 h100 NoActivate")
g2.Show("w200 h100 NoActivate")
WinWait("BHKWin List",, 3)
Sleep(200)
l := WinGetList("BHKWin List")
last := WinGetIDLast("BHKWin List")
out(WinGetCount("BHKWin List") " " l.Length " " ((last = g1.Hwnd) || (last = g2.Hwnd)))
;; expect: 2 2 1

;; test: WinWait times out and WinWaitNotActive
r := WinWait("BHKWin Never",, 0.3)
g := Gui(, "BHKWin NotActive")
g.Show("w300 h150")
WinActivate("ahk_id " g.Hwnd)
WinWaitActive("ahk_id " g.Hwnd,, 3)
g2 := Gui(, "BHKWin Other")
g2.Show("w300 h150")
WinActivate("ahk_id " g2.Hwnd)
out(r " " (WinWaitNotActive("ahk_id " g.Hwnd,, 3) = 1))
;; expect: 0 1

;; test: WinSetAlwaysOnTop and WinGetExStyle
g := Gui(, "BHKWin Top")
g.Show("w300 h150 NoActivate")
WinWait("BHKWin Top",, 3)
WinSetAlwaysOnTop(1, "BHKWin Top")
Sleep(200)
a := (WinGetExStyle("BHKWin Top") & 0x8) != 0
WinSetAlwaysOnTop(0, "BHKWin Top")
Sleep(200)
b := (WinGetExStyle("BHKWin Top") & 0x8) = 0
out(a " " b)
;; expect: 1 1

;; test: WinSetTransparent and WinGetTransparent
g := Gui(, "BHKWin Trans")
g.Show("w300 h150 NoActivate")
WinWait("BHKWin Trans",, 3)
WinSetTransparent(128, "BHKWin Trans")
a := WinGetTransparent("BHKWin Trans")
WinSetTransparent("Off", "BHKWin Trans")
out(a " [" WinGetTransparent("BHKWin Trans") "]")
;; expect: 128 []

;; test: WinSetTransColor and WinGetTransColor
g := Gui(, "BHKWin TC")
g.BackColor := "FF00FF"
g.Show("w300 h150 NoActivate")
WinWait("BHKWin TC",, 3)
WinSetTransColor("FF00FF", "BHKWin TC")
out(WinGetTransColor("BHKWin TC"))
;; expect: 0xFF00FF

;; test: WinSetRegion
g := Gui(, "BHKWin Region")
g.Show("w300 h150 NoActivate")
WinWait("BHKWin Region",, 3)
WinSetRegion("0-0 W200 H100 E", "BHKWin Region")
WinSetRegion(, "BHKWin Region")
out("ok")
;; expect: ok

;; test: WinSetStyle, WinGetStyle, WinSetExStyle
g := Gui("+Resize", "BHKWin Style")
g.Show("w300 h150 NoActivate")
WinWait("BHKWin Style",, 3)
WinSetStyle("-0x40000", "BHKWin Style")
a := (WinGetStyle("BHKWin Style") & 0x40000) = 0
WinSetStyle("+0x40000", "BHKWin Style")
b := (WinGetStyle("BHKWin Style") & 0x40000) != 0
WinSetExStyle("+0x80", "BHKWin Style")
c := (WinGetExStyle("BHKWin Style") & 0x80) != 0
out(a " " b " " c)
;; expect: 1 1 1

;; test: WinSetEnabled
g := Gui(, "BHKWin Enabled")
g.Show("w300 h150 NoActivate")
WinWait("BHKWin Enabled",, 3)
WinSetEnabled(0, "BHKWin Enabled")
a := (WinGetStyle("BHKWin Enabled") & 0x8000000) != 0
WinSetEnabled(1, "BHKWin Enabled")
out(a " " ((WinGetStyle("BHKWin Enabled") & 0x8000000) = 0))
;; expect: 1 1

;; test: WinMoveTop, WinMoveBottom and WinRedraw
g := Gui(, "BHKWin Z")
g.Show("w300 h150 NoActivate")
WinWait("BHKWin Z",, 3)
WinMoveBottom("BHKWin Z")
WinMoveTop("BHKWin Z")
WinRedraw("BHKWin Z")
out("ok")
;; expect: ok

;; test: WinActivateBottom picks the bottom-most match
g1 := Gui(, "BHKWin Bottom")
g1.Show("w200 h100")
Sleep(200)
g2 := Gui(, "BHKWin Bottom")
g2.Show("w200 h100")
WinActivate("ahk_id " g2.Hwnd)
WinWaitActive("ahk_id " g2.Hwnd,, 3)
WinActivateBottom("BHKWin Bottom")
Sleep(400)
out(WinActive("A") = g1.Hwnd)
;; expect: 1

;; test: WinGetText and DetectHiddenText
g := Gui(, "BHKWin Text")
g.Add("Text",, "visible words")
h := g.Add("Text", "Hidden", "hidden words")
g.Show("w300 h150 NoActivate")
WinWait("BHKWin Text",, 3)
DetectHiddenText(false)
a := WinGetText("BHKWin Text")
DetectHiddenText(true)
b := WinGetText("BHKWin Text")
out((InStr(a, "visible") > 0) " " (InStr(a, "hidden") = 0) " " (InStr(b, "hidden") > 0))
;; expect: 1 1 1

;; test: WinGetControls and WinGetControlsHwnd
g := Gui(, "BHKWin Ctls")
e := g.Add("Edit")
b := g.Add("Button",, "OK")
g.Show("w300 h150 NoActivate")
WinWait("BHKWin Ctls",, 3)
c := WinGetControls("BHKWin Ctls")
h := WinGetControlsHwnd("BHKWin Ctls")
out(c.Length " " c[1] " " c[2] " " (h[1] = e.Hwnd))
;; expect: 2 Edit1 Button1 1

;; test: SetWinDelay
SetWinDelay(-1)
a := A_WinDelay
SetWinDelay(100)
out(a " " A_WinDelay)
;; expect: -1 100

;; test: GroupAdd, GroupActivate, GroupDeactivate, GroupClose
g1 := Gui(, "BHKWin GroupA")
g2 := Gui(, "BHKWin GroupB")
g1.Show("w200 h100")
g2.Show("w200 h100")
WinWait("BHKWin GroupB",, 3)
GroupAdd("bhkgrp", "BHKWin GroupA")
GroupAdd("bhkgrp", "BHKWin GroupB")
GroupActivate("bhkgrp")
Sleep(400)
a := WinActive("A")
inGroup := (a = g1.Hwnd || a = g2.Hwnd)
GroupClose("bhkgrp", "A")
Sleep(400)
out(inGroup " " (WinExist("BHKWin GroupA") = 0 || WinExist("BHKWin GroupB") = 0))
GroupDeactivate("bhkgrp")
;; expect: 1 1
