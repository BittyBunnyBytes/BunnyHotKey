; Live X11 test: a bare-modifier hotkey suppresses the modifier itself, like AutoHotkey's hook on Windows.
; While RCtrl:: is active, RCtrl is out of the modifier map, so RCtrl+F24 arrives as plain F24 (F24:: fires,
; ^F24:: doesn't).  The map is restored on exit.  Run: bhk --console tests/live/x11_bare_modifier.ahk
#SingleInstance Force
log := ""
$RCtrl:: global log .= "RCtrl "
$F24::   global log .= "F24 "
$^F24::  global log .= "^F24 "
Run() {
    global log
    SendLevel 1
    Send "{RCtrl down}{F24}{RCtrl up}"
    Sleep 400
    FileAppend Trim(log) "`n", "*"
    ExitApp
}
SetTimer Run, -500
