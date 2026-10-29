;; suite: v2 display
; AutoHotkey v2.0 Gui, controls, events and dialogs (tools/conformance.py). Windows open without
; activation; dialogs close by their own timeout or a timer, so nothing waits for the user.

;; test: every control type can be added
g := Gui()
types := ["Text", "Edit", "UpDown", "Picture", "Button", "CheckBox", "Radio", "DropDownList", "ComboBox", "ListBox",
          "ListView", "TreeView", "Link", "Hotkey", "DateTime", "MonthCal", "Slider", "Progress", "GroupBox", "Tab3",
          "StatusBar"]
n := 0
for t in types
    try (g.Add(t), n++)
g.Show("NoActivate")
out(n "/" types.Length " " Type(g["Edit1"]))
;; expect: 21/21 Gui.Edit

;; test: Value and Text of input controls
g := Gui()
e := g.Add("Edit", "vName", "Bunny")
c := g.Add("CheckBox", "vAgree Checked", "Agree")
d := g.Add("DropDownList", "vPick Choose2", ["red", "green", "blue"])
s := g.Add("Slider", "vLevel Range0-10", 4)
out(e.Value " " c.Value " " d.Value " " d.Text " " s.Value)
;; expect: Bunny 1 2 green 4

;; test: Submit with NoHide returns named values
g := Gui()
g.Add("Edit", "vUser", "guest")
g.Add("CheckBox", "vRem", "Remember").Value := 1
g.Add("ComboBox", "vCity", ["Oslo", "Rome"]).Text := "Rome"
g.Show("NoActivate")
o := g.Submit(false)
out(o.User " " o.Rem " " o.City)
;; expect: guest 1 Rome

;; test: Radio groups and Submit
g := Gui()
g.Add("Radio", "vChoice", "A")
g.Add("Radio", "Checked", "B")
g.Add("Radio",, "C")
o := g.Submit(false)
out(o.Choice)
;; expect: 2

;; test: ListBox Multi and AltSubmit
g := Gui()
lb := g.Add("ListBox", "Multi vL", ["a", "b", "c"])
lb.Choose(1), lb.Choose(3)
v := lb.Value
t := lb.Text
out(v.Length " " v[2] " " t[1] t[2])
;; expect: 2 3 ac

;; test: list control Add, Delete, Choose by text
g := Gui()
d := g.Add("DDL",, ["x"])
d.Add(["y", "z"])
d.Delete(1)
d.Choose("z")
out(d.Text " " d.Value " " ControlGetItems(d).Length)
;; expect: z 2 2

;; test: Edit options and multi-line value
g := Gui()
e := g.Add("Edit", "r3 Multi WantTab", "one`ntwo")
p := g.Add("Edit", "Password")
p.Value := "secret"
out(StrReplace(e.Value, "`n", "|") " " p.Value)
;; expect: one|two secret

;; test: UpDown buddy and Range
g := Gui()
e := g.Add("Edit")
u := g.Add("UpDown", "Range1-10", 7)
out(e.Value " " u.Value)
;; expect: 7 7

;; test: DateTime and MonthCal values
g := Gui()
dt := g.Add("DateTime")
dt.Value := "20240115123000"
mc := g.Add("MonthCal")
mc.Value := "20240220"
out(SubStr(dt.Value, 1, 8) " " SubStr(mc.Value, 1, 8))
;; expect: 20240115 20240220

;; test: Hotkey control value
g := Gui()
h := g.Add("Hotkey")
h.Value := "^!a"
out(h.Value)
;; expect: ^!a

;; test: Progress and Slider set values
g := Gui()
p := g.Add("Progress", "Range0-200", 50)
p.Value += 25
s := g.Add("Slider", "Range0-50 Vertical Invert", 20)
out(p.Value " " s.Value)
;; expect: 75 20

;; test: Tab UseTab places controls on pages
g := Gui()
t := g.Add("Tab3",, ["One", "Two"])
t.UseTab(2)
e := g.Add("Edit",, "on two")
t.UseTab()
t.Choose(2)
out(t.Text " " t.Value " " e.Value)
;; expect: Two 2 on two

;; test: ListView Add, Modify, GetText, GetCount, GetNext
g := Gui()
lv := g.Add("ListView", "Checked", ["Name", "Size"])
lv.Add(, "a", 10)
lv.Add("Check Select", "b", 2)
lv.Modify(1, "Col2", 99)
out(lv.GetCount() " " lv.GetText(1, 2) " " lv.GetNext(0, "C") " " lv.GetNext() " " lv.GetCount("Col") " " lv.GetText(0, 1))
;; expect: 2 99 2 2 2 Name

;; test: ListView columns and sorting
g := Gui()
lv := g.Add("ListView",, ["N", "V"])
lv.Add(, "b", 10), lv.Add(, "a", 9), lv.Add(, "c", 100)
lv.ModifyCol(2, "Integer SortDesc")
t := lv.GetText(1, 2)
lv.ModifyCol(1, "Sort")
u := lv.GetText(1, 1)
lv.InsertCol(3, , "X")
lv.DeleteCol(1)
out(t " " u " " lv.GetCount("Column"))
;; expect: 100 a 2

;; test: ListView Insert and Delete
g := Gui()
lv := g.Add("ListView",, ["A"])
lv.Add(, "a"), lv.Add(, "c")
lv.Insert(2, , "b")
t := lv.GetText(2)
lv.Delete(1)
n := lv.GetCount()
lv.Delete()
out(t " " n " " lv.GetCount())
;; expect: b 2 0

;; test: TreeView Add, GetParent, GetChild, GetNext, GetText, Modify, Delete
g := Gui()
tv := g.Add("TreeView")
p := tv.Add("Parent")
c := tv.Add("Child", p)
q := tv.Add("Second")
tv.Modify(c, , "Renamed")
r := (tv.GetParent(c) = p) " " (tv.GetChild(p) = c) " " (tv.GetNext() = p) " " (tv.GetNext(p, "Full") = c) " " tv.GetText(c) " " tv.GetCount()
tv.Delete(c)
out(r " " tv.GetCount())
;; expect: 1 1 1 1 Renamed 3 2

;; test: TreeView Select, Get and GetSelection
g := Gui()
tv := g.Add("TreeView")
a := tv.Add("a")
b := tv.Add("b",, "Bold")
tv.Modify(b, "Select")
out((tv.GetSelection() = b) " " (tv.Get(b, "Bold") = b) " " tv.Get(a, "Bold"))
;; expect: 1 1 0

;; test: StatusBar SetText, SetParts and text readback
g := Gui()
sb := g.Add("StatusBar",, "start")
sb.SetParts(100, 60)
sb.SetText("second", 2)
sb.SetText("first")
g.Show("NoActivate")
Sleep(100)
out(StatusBarGetText(1, "ahk_id " g.Hwnd) " " StatusBarGetText(2, "ahk_id " g.Hwnd))
;; expect: first second

;; test: control Move, GetPos, Focus, Enabled, Visible
g := Gui("-DPIScale")
e := g.Add("Edit", "x10 y10 w50 h20")
e.Move(30, 40, 120, 25)
e.GetPos(&x, &y, &w, &h)
e.Enabled := false
en := e.Enabled
e.Visible := false
out(x " " y " " w " " h " " en " " e.Visible)
;; expect: 30 40 120 25 0 0

;; test: Gui margins and positioning options
g := Gui("-DPIScale")
g.MarginX := 20, g.MarginY := 30
a := g.Add("Text", "w40 h20 Section", "a")
b := g.Add("Text", "xs y+10 w40 h20", "b")
c := g.Add("Text", "x+10 ys w40 h20", "c")
a.GetPos(&ax, &ay), b.GetPos(&bx, &by), c.GetPos(&cx, &cy)
out(ax " " ay " " bx " " by " " cx " " cy)
;; expect: 20 30 20 60 70 30

;; test: Gui Show size and GetClientPos
g := Gui("-DPIScale", "BHKGui Size")
g.Show("w250 h120 NoActivate")
Sleep(150)
g.GetClientPos(,, &w, &h)
out(w " " h)
;; expect: 250 120

;; test: Gui Opt, Title, BackColor and SetFont
g := Gui("+Resize +AlwaysOnTop", "BHKGui Opt")
g.Opt("-AlwaysOnTop +MinSize200x100")
g.Title := "BHKGui Renamed"
g.BackColor := "Silver"
g.SetFont("s12 Bold", "Arial")
t := g.Add("Text",, "styled")
t.SetFont("cRed")
out(g.Title " " g.BackColor)
;; expect: BHKGui Renamed C0C0C0

;; test: GuiFromHwnd and GuiCtrlFromHwnd
g := Gui()
e := g.Add("Edit")
g.Show("NoActivate")
out((GuiFromHwnd(g.Hwnd) = g) " " (GuiCtrlFromHwnd(e.Hwnd) = e) " " (GuiFromHwnd(e.Hwnd, true) = g))
;; expect: 1 1 1

;; test: Gui enumeration and control lookup by name
g := Gui()
g.Add("Edit", "vFirst")
g.Add("Button", "vSecond", "B")
s := ""
for hwnd, ctl in g
    s .= ctl.Name " "
out(Trim(s) " " g["Second"].Text)
;; expect: First Second B

;; test: Change event fires on programmatic choose
g := Gui()
d := g.Add("DDL",, ["a", "b"])
d.OnEvent("Change", (ctl, *) => (out("change " ctl.Text), ExitApp()))
g.Show("NoActivate")
ControlChooseIndex(2, d)
Sleep(1000)
out("no event")
;; expect: change b

;; test: Click event via ControlClick
g := Gui(, "BHKGui Click")
b := g.Add("Button",, "Press")
b.OnEvent("Click", (*) => (out("clicked"), ExitApp()))
g.Show("NoActivate")
Sleep(100)
ControlClick(b)
Sleep(1000)
out("no click")
;; expect: clicked

;; test: Close event and Hide/Destroy
g := Gui(, "BHKGui Close")
g.OnEvent("Close", (*) => (out("close event"), ExitApp()))
g.Show("NoActivate")
Sleep(200)
WinClose("BHKGui Close")
Sleep(1000)
out("no close")
;; expect: close event

;; test: Size event on Show
g := Gui("+Resize", "BHKGui Sized")
g.OnEvent("Size", (gui, minmax, w, h) => (out("size " w " " h " " minmax), ExitApp()))
g.Show("w220 h110 NoActivate")
Sleep(1000)
;; expect: size 220 110 0

;; test: Gui Destroy and Hide
g := Gui(, "BHKGui Gone")
g.Show("NoActivate")
Sleep(100)
g.Hide()
h := WinExist("BHKGui Gone")
g.Destroy()
DetectHiddenWindows(true)
out((h = 0) " " (WinExist("BHKGui Gone") = 0))
;; expect: 1 1

;; test: MenuBar and Menu methods
mb := MenuBar()
m := Menu()
m.Add("Open", (*) => 0)
m.Add()
m.Add("Check me", (*) => 0)
m.Check("Check me")
m.Disable("Open")
m.Rename("Open", "Opened")
mb.Add("File", m)
g := Gui()
g.MenuBar := mb
g.Show("NoActivate")
out(DllCall("GetMenuItemCount", "Ptr", m.Handle) " " (m.Handle != 0))
;; expect: 3 1

;; test: MsgBox times out
r := MsgBox("auto closes", "BHKMsg", "T0.5")
out(r)
;; expect: Timeout

;; test: MsgBox button choice by closing
SetTimer(() => ControlClick("Button2", "BHKMsg2"), -600)
r := MsgBox("pick", "BHKMsg2", "YesNo")
out(r)
;; expect: No

;; test: InputBox times out and returns an object
r := InputBox("prompt", "BHKInput", "T0.5", "dflt")
out(r.Result " " r.Value)
;; expect: Timeout dflt

;; test: ToolTip shows and hides
hw := ToolTip("tip text", 100, 100, 2)
Sleep(200)
id := WinExist("ahk_id " hw)
ToolTip(, , , 2)
Sleep(200)
out((id != 0) " " (WinExist("ahk_id " hw) = 0))
;; expect: 1 1

;; test: TrayTip shows a notification
TrayTip("BHK conformance", "notification", "Mute")
Sleep(200)
TrayTip()
out("shown")
;; expect: shown

;; test: FileSelect returns empty when cancelled
SetTimer(() => WinClose("BHKSelectFile"), -800)
r := FileSelect(, , "BHKSelectFile")
out("[" r "]")
;; expect: []

;; test: DirSelect returns empty when cancelled
SetTimer(() => WinClose("BHKSelectDir"), -800)
r := DirSelect(, , "BHKSelectDir")
out("[" r "]")
;; expect: []

;; test: IL_Create, IL_Add and SetImageList
g := Gui()
lv := g.Add("ListView",, ["A"])
il := IL_Create(2)
lv.SetImageList(il)
out((il != 0) " " IL_Destroy(il))
;; expect: 1 1

;; test: LoadPicture of a missing file returns 0
out(LoadPicture("bhk_missing_picture.png"))
;; expect: 0
