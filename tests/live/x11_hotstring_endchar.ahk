; Live X11 test: a hotstring swallows its end key and re-sends it after the replacement (hook.cpp
; suppress_hotstring_final_char).  Enter in the Edit presses the Default button, which records the Edit's text:
; "by the way" means Enter arrived after the replacement, "btw" would mean it leaked through first.
; Uses SendLevel 1 so the script's own Send reaches the hotstring.  Run: bhk --console tests/live/x11_hotstring_endchar.ahk
#SingleInstance Force
::btw::by the way
g := Gui(, "BHK hotstring test")
ed := g.AddEdit("w200")
g.AddButton("Default", "OK").OnEvent("Click", (*) => (FileAppend("button saw: " ed.Value "`n", "*"), ExitApp()))
g.Show()
WinActivate "BHK hotstring test"
ed.Focus()
Run() {
    SendLevel 1
    Send "btw{Enter}"
}
SetTimer Run, -800
SetTimer () => (FileAppend("timeout: " ed.Value "`n", "*"), ExitApp(1)), -4000
