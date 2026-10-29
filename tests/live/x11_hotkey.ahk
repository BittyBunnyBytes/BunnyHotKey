; Live X11 test (needs a display): registers F24, sends F24 to itself, expects the hotkey to fire.
; F24 is used because no application reacts to it.  Run: bhk --console tests/live/x11_hotkey.ahk
#SingleInstance Force
F24:: {
    FileAppend "hotkey fired: " ThisHotkey "`n", "*"
    ExitApp
}
SetTimer () => (FileAppend("timeout`n", "*"), ExitApp(1)), -3000
SetTimer () => Send("{F24}"), -500
