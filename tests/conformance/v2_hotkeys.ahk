;; suite: v2 desktop
; AutoHotkey v2.0 hotkeys and hotstrings on the real X11 desktop (tools/conformance.py).
; Hotkeys are triggered by the script's own input at SendLevel 1 (a hook hotkey fires on sent input
; whose send level is above its #InputLevel). Keys are F13-F20 and text typed into BHK's own test window.

Target(title := "BHKHot") {
    g := Gui("-DPIScale", title)
    g.edit := g.Add("Edit", "w300 r3")
    g.Show("w400 h200")
    WinActivate("ahk_id " g.Hwnd)
    if !WinWaitActive("ahk_id " g.Hwnd,, 3) {
        out("not active")
        ExitApp
    }
    g.edit.Focus()
    Sleep(250)
    return g
}
Fire(keys) {
    SendLevel(1)
    Send(keys)
    SendLevel(0)
    Sleep(400)
}

;; test: a hotkey fires and sets A_ThisHotkey
g := Target()
Fire("{F13}")
out("end")
ExitApp
F13::out("F13 " A_ThisHotkey)
;; expect: F13 F13
;; expect: end

;; test: modifier hotkeys
g := Target()
Fire("^{F14}")
Fire("+!{F14}")
out("end")
ExitApp
^F14::out("ctrl")
+!F14::out("shift alt")
;; expect: ctrl
;; expect: shift alt
;; expect: end

;; test: wildcard hotkey fires with extra modifiers
g := Target()
Fire("^+{F15}")
ExitApp
*F15::out("wild")
;; expect: wild

;; test: key-up hotkey
g := Target()
Fire("{F16}")
ExitApp
F16 up::out("released")
;; expect: released

;; test: custom combination
g := Target()
Fire("{F17 down}{F18}{F17 up}")
ExitApp
F17 & F18::out("combo")
;; expect: combo

;; test: ~ lets the key through to the window
g := Target()
Fire("{F19}")
ExitApp
~F19::out("passthrough")
;; expect: passthrough

;; test: remapping a key
g := Target()
Fire("{F20}")
Sleep(200)
out(g.edit.Value)
ExitApp
F20::z
;; expect: z

;; test: Hotkey() creates, disables and re-enables
g := Target()
Hotkey("F13", (k) => out("dynamic " k))
Fire("{F13}")
Hotkey("F13", "Off")
Fire("{F13}")
Hotkey("F13", "On")
Fire("{F13}")
out("end")
;; expect: dynamic F13
;; expect: dynamic F13
;; expect: end

;; test: Hotkey() with a Toggle
g := Target()
Hotkey("F14", (k) => out("t"))
Hotkey("F14", "Toggle")
Fire("{F14}")
Hotkey("F14", "Toggle")
Fire("{F14}")
out("end")
;; expect: t
;; expect: end

;; test: HotIfWinActive scopes a hotkey to a window
g := Target("BHKHot Scope")
HotIfWinActive("BHKHot Scope")
Hotkey("F15", (*) => out("in scope"))
HotIfWinActive("BHKHot NotThere")
Hotkey("F16", (*) => out("wrong"))
HotIf()
Fire("{F15}")
Fire("{F16}")
out("end")
;; expect: in scope
;; expect: end

;; test: HotIfWinNotActive, HotIfWinExist, HotIfWinNotExist
g := Target("BHKHot Cond")
HotIfWinNotActive("BHKHot Nope")
Hotkey("F17", (*) => out("not active ok"))
HotIfWinExist("BHKHot Cond")
Hotkey("F18", (*) => out("exist ok"))
HotIfWinNotExist("BHKHot Nope")
Hotkey("F19", (*) => out("not exist ok"))
HotIf()
Fire("{F17}")
Fire("{F18}")
Fire("{F19}")
;; expect: not active ok
;; expect: exist ok
;; expect: not exist ok

;; test: HotIf with a callback
g := Target()
allow := true
HotIf((*) => allow)
Hotkey("F20", (*) => out("allowed"))
HotIf()
Fire("{F20}")
allow := false
Fire("{F20}")
out("end")
;; expect: allowed
;; expect: end

;; test: #HotIf directive with an expression
g := Target()
flag := 1
Fire("{F13}")
flag := 0
Fire("{F13}")
out("end")
ExitApp
#HotIf flag
F13::out("hotif")
#HotIf
;; expect: hotif
;; expect: end

;; test: Suspend disables hotkeys
g := Target()
Suspend(true)
Fire("{F14}")
Suspend(false)
Fire("{F14}")
ExitApp
F14::out("active")
;; expect: active

;; test: A_PriorHotkey and A_TimeSinceThisHotkey
g := Target()
Fire("{F15}")
Fire("{F16}")
ExitApp
F15::return
F16::out(A_PriorHotkey " " (A_TimeSinceThisHotkey >= 0) " " (A_TimeSincePriorHotkey >= 0))
;; expect: F15 1 1

;; test: hotstring replaces typed text
g := Target()
Fire("btw ")
Sleep(300)
out("[" g.edit.Value "]")
ExitApp
::btw::by the way
;; expect: [by the way ]

;; test: hotstring options * and ?
g := Target()
Fire("xa1q")
Sleep(300)
out(g.edit.Value)
ExitApp
:*?:a1q::A-ONE
;; expect: xA-ONE

;; test: case-sensitive hotstring C
g := Target()
Fire("CS ")
Fire("cs ")
Sleep(300)
out("[" g.edit.Value "]")
ExitApp
:C:CS::caps
;; expect: [caps cs ]

;; test: hotstring B0 keeps the abbreviation and O omits the end char
; B0: the end char isn't suppressed (hook.cpp), so it reaches the window before the replacement
g := Target()
Fire("kp ")
Sleep(300)
Fire("om ")
Sleep(300)
out(g.edit.Value)
ExitApp
:B0:kp::!
:O:om::omit
;; expect: kp !omit

;; test: execute hotstring X and A_ThisHotkey
g := Target()
Fire("run1 ")
ExitApp
:X:run1::out("ran " A_ThisHotkey)
;; expect: ran :X:run1

;; test: Hotstring() function and A_EndChar
g := Target()
Hotstring("::zz1", (hs) => out("fn " A_EndChar "."))
Fire("zz1 ")
out("end")
;; expect: fn  .
;; expect: end

;; test: Hotstring reset and EndChars
Hotstring("EndChars", "-")
out(Hotstring("EndChars"))
;; expect: -

;; test: ListHotkeys opens the main window
Hotkey("F13", (*) => 0)
ListHotkeys()
r := WinWait("ahk_class AutoHotkey",, 3)
out(r != 0)
;; expect: 1

;; test: KeyHistory opens the main window
InstallKeybdHook()
KeyHistory()
r := WinWait("ahk_class AutoHotkey",, 3)
out(r != 0)
;; expect: 1

;; test: ListVars and ListLines open the main window
x := 1
ListVars()
r := WinWait("ahk_class AutoHotkey",, 3)
ListLines()
out(r != 0)
;; expect: 1
