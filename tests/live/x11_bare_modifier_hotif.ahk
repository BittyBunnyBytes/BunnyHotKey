; Live X11 test: a #HotIf-conditional bare-modifier hotkey swallows the modifier only where it applies.
; In window A, RCtrl:: is active, so RCtrl+F24 arrives as plain F24; in window B, RCtrl is a normal Ctrl.
; Run: bhk --console tests/live/x11_bare_modifier_hotif.ahk
#SingleInstance Force
log := ""
#HotIf WinActive("BHK cond A")
$RCtrl:: global log .= "RCtrl "
#HotIf
$F24::  global log .= "F24 "
$^F24:: global log .= "^F24 "
a := Gui(, "BHK cond A"), a.AddText(, "A"), a.Show("x100 y100 w200 h60")
b := Gui(, "BHK cond B"), b.AddText(, "B"), b.Show("x400 y100 w200 h60")
Run() {
    global log
    SendLevel 1
    WinActivate "BHK cond A"
    WinWaitActive "BHK cond A", , 2
    Sleep 400
    Send "{RCtrl down}{F24}{RCtrl up}"
    Sleep 400
    log .= "| "
    WinActivate "BHK cond B"
    WinWaitActive "BHK cond B", , 2
    Sleep 400
    Send "{RCtrl down}{F24}{RCtrl up}"
    Sleep 400
    FileAppend Trim(log) "`n", "*"
    ExitApp
}
SetTimer Run, -500
