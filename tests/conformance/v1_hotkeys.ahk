;; suite: v1 desktop
; AutoHotkey v1.1 hotkey and hotstring syntax on the real X11 desktop (tools/conformance.py).
; Triggered by the script's own input at SendLevel 1; keys are F13-F20 and text typed into BHK's own window.

Target(title = "BHKv1Hot") {
    global Ed
    Gui, New, -DPIScale +HwndH, %title%
    Gui, Add, Edit, w300 r3 vEd hwndEdH
    Gui, Show, w400 h200
    WinActivate, ahk_id %H%
    WinWaitActive, ahk_id %H%,, 3
    if ErrorLevel {
        out("not active")
        ExitApp
    }
    GuiControl, Focus, Ed
    Sleep, 250
    return H
}
Fire(keys) {
    SendLevel, 1
    Send, %keys%
    SendLevel, 0
    Sleep, 400
}
EdText() {
    GuiControlGet, t,, Ed
    return t
}

;; test: unbraced hotkey body ending in return
Target()
Fire("{F13}")
ExitApp
F13::
out("body " A_ThisHotkey)
return
;; expect: body F13

;; test: stacked hotkeys share one body
Target()
Fire("{F14}")
Fire("{F15}")
ExitApp
F14::
F15::
out("stacked " A_ThisHotkey)
return
;; expect: stacked F14
;; expect: stacked F15

;; test: single-line hotkey with a command
Target()
Fire("{F16}")
ExitApp
F16::FileAppend, single`n, *
;; expect: single

;; test: modifier and wildcard hotkeys
Target()
Fire("^{F17}")
Fire("+!{F18}")
ExitApp
^F17::out("ctrl")
*F18::out("wild")
;; expect: ctrl
;; expect: wild

;; test: key remap
Target()
Fire("{F19}")
Sleep, 200
out(EdText())
ExitApp
F19::q
;; expect: q

;; test: #IfWinActive scopes hotkeys
Target("BHKv1Hot Scoped")
Fire("{F20}")
Fire("{F13}")
out("end")
ExitApp
#IfWinActive, BHKv1Hot Scoped
F20::out("in scope")
#IfWinActive, BHKv1Hot Elsewhere
F13::out("wrong")
#IfWinActive
;; expect: in scope
;; expect: end

;; test: #If with an expression
flag := 1
Target()
Fire("{F14}")
flag := 0
Fire("{F14}")
out("end")
ExitApp
#If flag
F14::out("if on")
#If
;; expect: if on
;; expect: end

;; test: Hotkey command with a label, Off and On
Target()
Hotkey, F15, Lbl
Fire("{F15}")
Hotkey, F15, Off
Fire("{F15}")
Hotkey, F15, On
Fire("{F15}")
out("end")
ExitApp
Lbl:
out("label " A_ThisHotkey)
return
;; expect: label F15
;; expect: label F15
;; expect: end

;; test: Hotkey, IfWinActive in the command
Target("BHKv1Hot Cmd")
Hotkey, IfWinActive, BHKv1Hot Cmd
Hotkey, F16, Scoped
Hotkey, IfWinActive
Fire("{F16}")
ExitApp
Scoped:
out("scoped cmd")
return
;; expect: scoped cmd

;; test: Gosub to a hotkey label
Gosub, F17
ExitApp
F17::
out("gosub " A_ThisLabel)
return
;; expect: gosub F17

;; test: key-up hotkey
Target()
Fire("{F18}")
ExitApp
F18 up::out("up")
;; expect: up

;; test: v1 hotstring with replacement
Target()
Fire("btw ")
Sleep, 300
out("[" EdText() "]")
ExitApp
::btw::by the way
;; expect: [by the way ]

;; test: v1 hotstring with a body and return
Target()
Fire("hs1 ")
ExitApp
::hs1::
out("hotstring body")
return
;; expect: hotstring body

;; test: v1 hotstring options * and C
Target()
Fire("Zq")
Sleep, 300
out(EdText())
ExitApp
:*C:Zq::ZED
;; expect: ZED

;; test: Suspend toggles hotkeys
Target()
Suspend, On
Fire("{F19}")
Suspend, Off
Fire("{F19}")
ExitApp
F19::out("active")
;; expect: active

;; test: A_PriorHotkey and A_TimeSinceThisHotkey
Target()
Fire("{F13}")
Fire("{F14}")
ExitApp
F13::return
F14::out(A_PriorHotkey " " (A_TimeSinceThisHotkey >= 0))
;; expect: F13 1
