;; suite: v2 desktop
; AutoHotkey v2.0 Control*, Edit*, ListView/StatusBar functions, messages and pixel search
; (tools/conformance.py), run against BHK's own test windows titled "BHKCtl".

Win() {
    g := Gui("-DPIScale", "BHKCtl")
    g.e := g.Add("Edit", "w200 r3", "line one`nline two")
    g.b := g.Add("Button", "w80", "Go")
    g.c := g.Add("CheckBox",, "Tick")
    g.d := g.Add("DDL", "w100", ["red", "green", "blue"])
    g.l := g.Add("ListBox", "w100 r3", ["a", "b", "c"])
    g.Show("w320 h300 NoActivate")
    WinWait("BHKCtl",, 3)
    Sleep(150)
    return g
}

;; test: ControlGetText and ControlSetText
g := Win()
ControlSetText("new text", "Edit1", "BHKCtl")
out(ControlGetText("Edit1", "BHKCtl") " " ControlGetText("Button1", "BHKCtl"))
;; expect: new text Go

;; test: ControlGetHwnd, ControlGetClassNN and ahk_id
g := Win()
h := ControlGetHwnd("Button1", "BHKCtl")
out((h = g.b.Hwnd) " " ControlGetClassNN(h) " " ControlGetClassNN(g.e))
;; expect: 1 Button1 Edit1

;; test: ControlGetPos and ControlMove
g := Win()
ControlMove(20, 30, 150, 40, "Edit1", "BHKCtl")
Sleep(100)
ControlGetPos(&x, &y, &w, &h, "Edit1", "BHKCtl")
out(w " " h)
;; expect: 150 40

;; test: ControlFocus and ControlGetFocus
g := Gui("-DPIScale", "BHKCtl Focus")
g.Add("Edit")
g.Add("Edit")
g.Show("w300 h150")
WinActivate("BHKCtl Focus")
WinWaitActive("BHKCtl Focus",, 3)
ControlFocus("Edit2", "BHKCtl Focus")
Sleep(200)
out(ControlGetClassNN(ControlGetFocus("BHKCtl Focus")))
;; expect: Edit2

;; test: ControlGetChecked and ControlSetChecked
g := Win()
ControlSetChecked(1, "Button2", "BHKCtl")
a := ControlGetChecked("Button2", "BHKCtl")
ControlSetChecked(-1, "Button2", "BHKCtl")
out(a " " ControlGetChecked("Button2", "BHKCtl") " " g.c.Value)
;; expect: 1 0 0

;; test: ControlGetEnabled, ControlSetEnabled, ControlGetVisible, ControlHide, ControlShow
g := Win()
ControlSetEnabled(0, g.b)
a := ControlGetEnabled(g.b)
ControlHide(g.b)
v := ControlGetVisible(g.b)
ControlShow(g.b)
out(a " " v " " ControlGetVisible(g.b) " " g.b.Enabled)
;; expect: 0 0 1 0

;; test: ControlGetItems, ControlChooseIndex, ControlChooseString, ControlGetChoice, ControlGetIndex
g := Win()
items := ControlGetItems(g.d)
ControlChooseIndex(3, g.d)
a := ControlGetChoice(g.d)
ControlChooseString("gre", g.d)
out(items.Length " " a " " ControlGetChoice(g.d) " " ControlGetIndex(g.d))
;; expect: 3 blue green 2

;; test: ControlAddItem, ControlDeleteItem, ControlFindItem
g := Win()
n := ControlAddItem("d", g.l)
ControlDeleteItem(1, g.l)
out(n " " ControlFindItem("c", g.l) " " ControlGetItems(g.l).Length)
;; expect: 4 2 3

;; test: ControlShowDropDown and ControlHideDropDown
g := Win()
ControlShowDropDown(g.d)
Sleep(200)
ControlHideDropDown(g.d)
out("ok")
;; expect: ok

;; test: ControlClick on a button
g := Win()
g.b.OnEvent("Click", (*) => (out("go"), ExitApp()))
ControlClick("Button1", "BHKCtl")
Sleep(1000)
out("no click")
;; expect: go

;; test: ControlSend and ControlSendText to an Edit
g := Win()
ControlSetText("", g.e)
ControlSend("ab{Enter}c", g.e)
ControlSendText("{x}", g.e)
Sleep(300)
out(StrReplace(g.e.Value, "`n", "|"))
;; expect: ab|c{x}

;; test: ControlGetStyle, ControlSetStyle, ControlGetExStyle, ControlSetExStyle
g := Win()
s := ControlGetStyle(g.e)
ControlSetStyle("+0x800", g.e)
ro := (ControlGetStyle(g.e) & 0x800) != 0
ControlSetStyle("-0x800", g.e)
ControlSetExStyle("+0x200", g.e)
ex := ControlGetExStyle(g.e)
out((s & 0x50000000 = 0x50000000) " " ro " " ((ControlGetStyle(g.e) & 0x800) = 0) " " IsInteger(ex))
;; expect: 1 1 1 1

;; test: SetControlDelay
SetControlDelay(-1)
out(A_ControlDelay)
;; expect: -1

;; test: EditGetLineCount, EditGetLine, EditGetCurrentLine, EditGetCurrentCol
g := Win()
ControlSetText("first`nsecond`nthird", g.e)
SendMessage(0xB1, 7, 7, g.e)                 ; EM_SETSEL to "s|econd"
out(EditGetLineCount(g.e) " " EditGetLine(2, g.e) " " EditGetCurrentLine(g.e) " " EditGetCurrentCol(g.e))
;; expect: 3 second 2 2

;; test: EditGetSelectedText and EditPaste
g := Win()
ControlSetText("hello world", g.e)
SendMessage(0xB1, 0, 5, g.e)                 ; select "hello"
sel := EditGetSelectedText(g.e)
EditPaste("bye", g.e)
out(sel " " g.e.Value)
;; expect: hello bye world

;; test: ListViewGetContent
g := Gui(, "BHKCtl LV")
lv := g.Add("ListView",, ["Name", "Size"])
lv.Add(, "a", 1), lv.Add("Select", "b", 2)
g.Show("NoActivate")
WinWait("BHKCtl LV",, 3)
out(StrReplace(ListViewGetContent("", lv), "`n", "|") " / " ListViewGetContent("Selected Col2", lv) " / " ListViewGetContent("Count", lv))
;; expect: a	1|b	2 / 2 / 2

;; test: StatusBarGetText and StatusBarWait
g := Gui(, "BHKCtl SB")
sb := g.Add("StatusBar",, "Ready")
g.Show("NoActivate")
WinWait("BHKCtl SB",, 3)
SetTimer(() => sb.SetText("Done"), -300)
r := StatusBarWait("Done", 3, 1, "BHKCtl SB")
out(StatusBarGetText(1, "BHKCtl SB") " " r)
;; expect: Done 1

;; test: SendMessage and PostMessage with WM_SETTEXT / WM_GETTEXTLENGTH
g := Win()
SendMessage(0x0C, 0, StrPtr("via message"), g.e)
n := SendMessage(0x0E, 0, 0, g.e)
PostMessage(0x0C, 0, StrPtr("posted"), g.e)
Sleep(200)
out(n " " g.e.Value)
;; expect: 11 posted

;; test: MenuSelect on the Gui's menu bar
g := Gui(, "BHKCtl Menu")
m := Menu()
m.Add("Pick", (name, *) => (out("picked " name), ExitApp()))
mb := MenuBar()
mb.Add("&File", m)
g.MenuBar := mb
g.Show("w200 h100 NoActivate")
WinWait("BHKCtl Menu",, 3)
MenuSelect("BHKCtl Menu", , "File", "Pick")
Sleep(1000)
out("no menu")
;; expect: picked Pick

;; test: PixelGetColor reads a Gui's background
g := Gui("-DPIScale -Caption +AlwaysOnTop", "BHKCtl Pixel")
g.BackColor := "FF0080"
g.Show("x40 y40 w60 h60 NoActivate")
Sleep(400)
CoordMode("Pixel", "Screen")
out(PixelGetColor(70, 70))
;; expect: 0xFF0080

;; test: PixelSearch finds a colour
g := Gui("-DPIScale -Caption +AlwaysOnTop", "BHKCtl PixelSearch")
g.BackColor := "00FF7F"
g.Show("x200 y200 w40 h40 NoActivate")
Sleep(400)
CoordMode("Pixel", "Screen")
found := PixelSearch(&px, &py, 150, 150, 300, 300, 0x00FF7F, 0)
out(found " " (px >= 200 && px < 240) " " (py >= 200 && py < 240))
;; expect: 1 1 1

;; test: ImageSearch finds a saved image
g := Gui("-DPIScale -Caption +AlwaysOnTop", "BHKCtl Image")
g.BackColor := "1E90FF"
g.Show("x300 y300 w50 h50 NoActivate")
Sleep(400)
; a 4x4 BMP of the same colour
b := Buffer(54 + 64, 0)
StrPut("BM", b, 2, "CP0"), NumPut("UInt", 54 + 64, b, 2), NumPut("UInt", 54, b, 10)
NumPut("UInt", 40, "Int", 4, "Int", 4, "UShort", 1, "UShort", 32, b, 14)
Loop 16
    NumPut("UInt", 0xFF1E90FF, b, 54 + (A_Index - 1) * 4)
f := FileOpen("blue.bmp", "w"), f.RawWrite(b), f.Close()
CoordMode("Pixel", "Screen")
found := ImageSearch(&ix, &iy, 250, 250, 400, 400, "blue.bmp")
out(found " " (ix >= 300 && ix < 350))
;; expect: 1 1
