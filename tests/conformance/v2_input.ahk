;; suite: v2 desktop
; AutoHotkey v2.0 keyboard and mouse functions with real X11 input (tools/conformance.py).
; Input only goes to BHK's own test window: Target() activates it and every section stops with
; "not active" unless that window is the active one. Lock-key checks restore the previous state.
; Not run here: BlockInput (it would block the user's keyboard and mouse).

Target(title := "BHKInput", opts := "w400 h220") {
    g := Gui("-DPIScale", title)
    g.edit := g.Add("Edit", "w300 r3 vE")
    g.Show(opts)
    WinActivate("ahk_id " g.Hwnd)
    if !WinWaitActive("ahk_id " g.Hwnd,, 3) {
        out("not active")
        ExitApp
    }
    g.edit.Focus()
    Sleep(200)
    return g
}
Guard(g) {
    if !WinActive("ahk_id " g.Hwnd) {
        out("not active")
        ExitApp
    }
}

;; test: Send types text into the focused control
g := Target()
Guard(g)
Send("hello{Space}World{!}")
Sleep(300)
out(g.edit.Value)
;; expect: hello World!

;; test: SendInput, SendEvent and SendPlay
g := Target()
Guard(g)
SendInput("a")
SendEvent("b")
SendPlay("c")
Sleep(300)
out(g.edit.Value)
;; expect: abc

;; test: SendText sends literal braces and modifiers
g := Target()
Guard(g)
SendText("{Enter}^a+b")
Sleep(300)
out(g.edit.Value)
;; expect: {Enter}^a+b

;; test: Send modifiers, key names and repeat counts
g := Target()
Guard(g)
Send("abc{Left 2}X{End}+{Home}")
Sleep(300)
Send("{Del}")
Send("q{BS}z")
Sleep(300)
out(g.edit.Value)
;; expect: z

;; test: Send {Raw} and {Text} modes
g := Target()
Guard(g)
Send("{Raw}#!^")
Send("{Text}+x")
Sleep(300)
out(g.edit.Value)
;; expect: #!^+x

;; test: Send Unicode characters
g := Target()
Guard(g)
Send("é€{U+263A}")
Sleep(400)
out(g.edit.Value)
;; expect: é€☺

;; test: SendMode and A_SendMode
SendMode("Event")
a := A_SendMode
SendMode("Input")
out(a " " A_SendMode)
;; expect: Event Input

;; test: SetKeyDelay and SetMouseDelay
SetKeyDelay(10, 5)
SetMouseDelay(15)
out(A_KeyDelay " " A_KeyDuration " " A_MouseDelay)
;; expect: 10 5 15

;; test: SendLevel and A_SendLevel
SendLevel(3)
out(A_SendLevel)
;; expect: 3

;; test: GetKeyState after a held key, and KeyWait
g := Target()
Guard(g)
Send("{Shift down}")
Sleep(100)
held := GetKeyState("Shift")
t := KeyWait("Shift", "L T0.2")
Send("{Shift up}")
Sleep(100)
out(held " " t " " GetKeyState("Shift") " " KeyWait("Shift", "L T1"))
;; expect: 1 0 0 1

;; test: GetKeyName, GetKeyVK, GetKeySC
out(GetKeyName("vk41") " " Format("{:X}", GetKeyVK("Enter")) " " Format("{:X}", GetKeySC("Esc")) " " GetKeyName("sc1C"))
;; expect: a D 1 Enter

;; test: SetCapsLockState and toggle state (restored)
was := GetKeyState("CapsLock", "T")
SetCapsLockState("On")
Sleep(200)
on := GetKeyState("CapsLock", "T")
SetCapsLockState("Off")
Sleep(200)
off := GetKeyState("CapsLock", "T")
SetCapsLockState(was ? "On" : "Off")
out(on " " off)
;; expect: 1 0

;; test: SetNumLockState and SetScrollLockState (restored)
n := GetKeyState("NumLock", "T")
SetNumLockState(!n)
Sleep(200)
n2 := GetKeyState("NumLock", "T")
SetNumLockState(n)
s := GetKeyState("ScrollLock", "T")
SetScrollLockState(s)
out((n2 = !n) " " (GetKeyState("NumLock", "T") = n))
;; expect: 1 1

;; test: SetStoreCapsLockMode
SetStoreCapsLockMode(false)
a := A_StoreCapsLockMode
SetStoreCapsLockMode(true)
out(a " " A_StoreCapsLockMode)
;; expect: 0 1

;; test: CoordMode, MouseMove and MouseGetPos over the window
g := Target()
CoordMode("Mouse", "Client")
MouseMove(50, 60, 0)
Sleep(200)
MouseGetPos(&x, &y, &win, &ctl)
out(x " " y " " (win = g.Hwnd) " " A_CoordModeMouse)
;; expect: 50 60 1 Client

;; test: MouseGetPos reports the control under the mouse
g := Target()
CoordMode("Mouse", "Client")
g.edit.GetPos(&ex, &ey)
MouseMove(ex + 5, ey + 5, 0)
Sleep(200)
MouseGetPos(,,, &ctl)
MouseGetPos(,,, &hw, 2)
out(ctl " " (hw = g.edit.Hwnd))
;; expect: Edit1 1

;; test: Click on a button fires its Click event
g := Gui("-DPIScale", "BHKInput Click")
b := g.Add("Button", "w120 h40", "Press")
b.OnEvent("Click", (*) => (out("clicked"), ExitApp()))
g.Show("w300 h150")
WinActivate("ahk_id " g.Hwnd)
WinWaitActive("ahk_id " g.Hwnd,, 3)
Guard(g)
CoordMode("Mouse", "Client")
b.GetPos(&bx, &by, &bw, &bh)
Click(bx + bw // 2, by + bh // 2)
Sleep(1500)
out("no click")
;; expect: clicked

;; test: MouseClick with button and count
g := Gui("-DPIScale", "BHKInput MouseClick")
b := g.Add("Button", "w120 h40", "Press")
c := {n: 0}
b.OnEvent("Click", (*) => c.n++)
g.Show("w300 h150")
WinActivate("ahk_id " g.Hwnd)
WinWaitActive("ahk_id " g.Hwnd,, 3)
Guard(g)
CoordMode("Mouse", "Client")
b.GetPos(&bx, &by, &bw, &bh)
MouseClick("Left", bx + 10, by + 10, 1, 0)
Sleep(300)
MouseClick("Left", bx + 10, by + 10, 1, 0)
Sleep(500)
out(c.n)
;; expect: 2

;; test: MouseClickDrag moves a slider
g := Gui("-DPIScale", "BHKInput Drag")
s := g.Add("Slider", "w300 h40 Range0-100", 0)
g.Show("w400 h150")
WinActivate("ahk_id " g.Hwnd)
WinWaitActive("ahk_id " g.Hwnd,, 3)
Guard(g)
CoordMode("Mouse", "Client")
s.GetPos(&sx, &sy, &sw, &sh)
MouseClickDrag("Left", sx + 8, sy + sh // 2, sx + sw - 5, sy + sh // 2, 5)
Sleep(500)
out(s.Value > 50)
;; expect: 1

;; test: SetDefaultMouseSpeed and A_DefaultMouseSpeed
SetDefaultMouseSpeed(7)
out(A_DefaultMouseSpeed)
;; expect: 7

;; test: CaretGetPos in a focused Edit
g := Target()
Guard(g)
Send("abc")
Sleep(300)
r := CaretGetPos(&cx, &cy)
out(r " " IsInteger(cx) " " IsInteger(cy))
;; expect: 1 1 1

;; test: InstallKeybdHook and InstallMouseHook
InstallKeybdHook()
InstallMouseHook()
out("hooks")
;; expect: hooks

;; test: InputHook collects typed keys
g := Target()
Guard(g)
ih := InputHook("L3 T3")
ih.Start()
Send("xyz")
ih.Wait(3)
out(ih.Input " " ih.EndReason)
;; expect: xyz Max

;; test: InputHook end keys and match list
g := Target()
Guard(g)
ih := InputHook("T3 *", "{Enter}", "stop")   ; * = match anywhere in the input
ih.Start()
Send("go stop")
ih.Wait(3)
r := ih.EndReason " [" ih.Input "] " ih.Match
out(r)
;; expect: Match [go stop] stop

;; test: A_PriorKey skips the script's own Send, A_TimeIdle
; key history marks sent keys as ignored ('i'), so A_PriorKey doesn't report them (BIV_PriorKey)
InstallKeybdHook()
g := Target()
Guard(g)
before := A_PriorKey
Send("k")
Sleep(200)
out((A_PriorKey = before) " " (A_TimeIdlePhysical >= 0) " " (A_TimeIdle >= 0))
;; expect: 1 1 1
