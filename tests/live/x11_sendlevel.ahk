; Live X11 test of SendLevel / #InputLevel (AutoHotkey hotkey.cpp rules), using keys no application reacts to:
;   F23::   RegisterHotkey-style -> triggered by Send at any level
;   $F24::  hook hotkey, #InputLevel 0 -> only SendLevel 1+ triggers it
;   ~F22::  hook (pass-through) -> only SendLevel 1+
;   #InputLevel 2 / $F21:: -> SendLevel 2 does not trigger it, SendLevel 3 does
; Run: bhk --console tests/live/x11_sendlevel.ahk
#SingleInstance Force
log := ""
F23::  global log .= "F23 "
$F24:: global log .= "F24 "
~F22:: global log .= "F22 "
#InputLevel 2
$F21:: global log .= "F21 "
#InputLevel 0
Run() {
    global log
    Send "{F23}{F24}{F22}{F21}"          ; level 0: only F23
    Sleep 300
    log .= "| "
    SendLevel 1
    Send "{F24}{F22}{F21}"               ; level 1: F24 F22
    Sleep 300
    log .= "| "
    SendLevel 2
    Send "{F21}"                         ; level 2 = InputLevel 2: no
    Sleep 300
    SendLevel 3
    Send "{F21}"                         ; level 3: F21
    Sleep 300
    FileAppend Trim(log) "`n", "*"
    ExitApp
}
SetTimer Run, -300
