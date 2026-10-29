; Live X11 test: a "*" hotstring swallows its final character (hook.cpp suppress_hotstring_final_char), so the
; full abbreviation never appears in the target app.  tests/live/foreign_app.py logs every change of its entry.
; Run by tests/run_live.py.
#SingleInstance Force
:*:zqx::bunny
w := "BHK Foreign App"
WinWait w, , 5
WinActivate w
WinWaitActive w, , 3
ControlSetText "", "Edit1", w
ControlFocus "Edit1", w
Sleep 300
SendLevel 1
Send "zqx"
Sleep 800
FileAppend ControlGetText("Edit1", w) "`n", "*"
ExitApp
