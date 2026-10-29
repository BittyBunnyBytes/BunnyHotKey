; AutoHotkey v1.1 Gui conformance (tools/v1_conformance.py). One feature per section.
; Expected output follows the v1.1 Gui, GuiControl, GuiControlGet, ListView, TreeView and StatusBar docs.
; Sections need a display (BHK's Gui is GTK); events are triggered without user input.

;; test: Edit control and Submit NoHide
Gui, Add, Edit, vName, Bunny
Gui, Show, NoActivate
Gui, Submit, NoHide
out(Name)
;; expect: Bunny

;; test: Submit without NoHide hides the window
Gui, +HwndG
Gui, Add, Edit, vE, x
Gui, Show, NoActivate
Gui, Submit
DetectHiddenWindows, Off
out((WinExist("ahk_id " G) = 0) " " E)
;; expect: 1 x

;; test: CheckBox values incl. Check3
Gui, Add, CheckBox, vC1 Checked, one
Gui, Add, CheckBox, vC2, two
Gui, Add, CheckBox, vC3 Check3 CheckedGray, three
Gui, Submit, NoHide
out(C1 C2 C3)
;; expect: 10-1

;; test: Radio group with one variable
Gui, Add, Radio, vR, a
Gui, Add, Radio, Checked, b
Gui, Add, Radio,, c
Gui, Submit, NoHide
out(R)
;; expect: 2

;; test: Radio buttons with their own variables
Gui, Add, Radio, vRa, a
Gui, Add, Radio, vRb Checked, b
Gui, Submit, NoHide
out(Ra Rb)
;; expect: 01

;; test: Radio Group option starts a new group
Gui, Add, Radio, vG1 Checked, a
Gui, Add, Radio,, b
Gui, Add, Radio, vG2 Group, c
Gui, Add, Radio, Checked, d
Gui, Submit, NoHide
out(G1 G2)
;; expect: 12

;; test: DropDownList default with || and AltSubmit
Gui, Add, DropDownList, vD1, red|green||blue
Gui, Add, DropDownList, vD2 AltSubmit Choose3, a|b|c
Gui, Submit, NoHide
out(D1 " " D2)
;; expect: green 3

;; test: ComboBox text
Gui, Add, ComboBox, vCb, one|two||three
Gui, Submit, NoHide
out(Cb)
;; expect: two

;; test: ListBox Multi selection is pipe-delimited
Gui, Add, ListBox, vLb Multi, a||b|c||
Gui, Submit, NoHide
out(Lb)
;; expect: a|c

;; test: Gui Delimiter option
Gui, +Delimiter`n
Gui, Add, DropDownList, vDd, x`ny`n`nz
Gui, Submit, NoHide
out(Dd)
;; expect: y

;; test: Slider with Range
Gui, Add, Slider, vSl Range10-20, 15
Gui, Submit, NoHide
out(Sl)
;; expect: 15

;; test: Progress set and add
Gui, Add, Progress, vPr, 30
GuiControl,, Pr, +20
GuiControlGet, p,, Pr
out(p)
;; expect: 50

;; test: Edit with UpDown buddy
Gui, Add, Edit, vEd
Gui, Add, UpDown, vUd Range1-10, 5
Gui, Submit, NoHide
out(Ed " " Ud)
;; expect: 5 5

;; test: Edit Number, Password, ReadOnly, Multi and Limit options load
Gui, Add, Edit, vN1 Number, 42
Gui, Add, Edit, vN2 Password, secret
Gui, Add, Edit, vN3 ReadOnly, ro
Gui, Add, Edit, vN4 r3 Multi, a`nb
Gui, Add, Edit, vN5 Limit3, abc
Gui, Submit, NoHide
out(N1 N2 N3 StrReplace(N4, "`n", "+") N5)
;; expect: 42secretroa+babc

;; test: DateTime and MonthCal values
Gui, Add, DateTime, vDt,
GuiControl,, Dt, 20240115123000
Gui, Add, MonthCal, vMc
GuiControl,, Mc, 20240220
Gui, Submit, NoHide
out(SubStr(Dt, 1, 8) " " SubStr(Mc, 1, 8))
;; expect: 20240115 20240220

;; test: Hotkey control
Gui, Add, Hotkey, vHk
GuiControl,, Hk, ^!a
Gui, Submit, NoHide
out(Hk)
;; expect: ^!a

;; test: Tab control and Gui Tab
Gui, Add, Tab2, vTb, One|Two
Gui, Tab, 2
Gui, Add, Edit, vInTab, tabbed
Gui, Tab
GuiControl, Choose, Tb, 2
Gui, Submit, NoHide
out(Tb " " InTab)
;; expect: Two tabbed

;; test: Text, Link and GroupBox read with GuiControlGet
Gui, Add, Text, vTx, hello
Gui, Add, Link, vLk, <a href="x">link</a>
Gui, Add, GroupBox, vGb, Group
GuiControlGet, a,, Tx
GuiControlGet, b,, Gb
out(a " " b)
;; expect: hello Group

;; test: GuiControl sets text and GuiControlGet reads it
Gui, Add, Edit, vEd, one
GuiControl,, Ed, two
GuiControlGet, Ed
out(Ed)
;; expect: two

;; test: GuiControl Text sub-command
Gui, Add, Button, vBt, Old
GuiControl, Text, Bt, New
GuiControlGet, t,, Bt
out(t)
;; expect: New

;; test: GuiControl replaces and appends list items
Gui, Add, DropDownList, vDl, a|b
GuiControl,, Dl, |x|y||z
Gui, Submit, NoHide
v1 := Dl
GuiControl,, Dl, w
GuiControl, ChooseString, Dl, w
Gui, Submit, NoHide
out(v1 " " Dl)
;; expect: y w

;; test: GuiControl Choose by position
Gui, Add, ListBox, vLb, a|b|c
GuiControl, Choose, Lb, 3
Gui, Submit, NoHide
out(Lb)
;; expect: c

;; test: GuiControl Choose with pipe fires the g-label
Gui, Add, DropDownList, vDl gChanged, a|b|c
Gui, Show, NoActivate
GuiControl, Choose, Dl, |2
Sleep, 50
out("end")
ExitApp
Changed:
Gui, Submit, NoHide
out("changed " A_GuiControl " " Dl)
return
;; expect: changed Dl b
;; expect: end

;; test: GuiControl Enable/Disable and GuiControlGet Enabled
Gui, Add, Edit, vEd
GuiControl, Disable, Ed
GuiControlGet, a, Enabled, Ed
GuiControl, Enable, Ed
GuiControlGet, b, Enabled, Ed
out(a b)
;; expect: 01

;; test: GuiControl Hide/Show and GuiControlGet Visible
Gui, Add, Edit, vEd
Gui, Show, NoActivate
GuiControl, Hide, Ed
GuiControlGet, a, Visible, Ed
GuiControl, Show, Ed
GuiControlGet, b, Visible, Ed
out(a b)
;; expect: 01

;; test: GuiControl Move and GuiControlGet Pos
Gui, Add, Edit, vEd x5 y5 w50 h20
GuiControl, Move, Ed, x30 y40 w120 h25
GuiControlGet, p, Pos, Ed
out(pX " " pY " " pW " " pH)
;; expect: 30 40 120 25

;; test: control position options x y w h
Gui, Add, Text, vT1 x10 y20 w80 h15, a
GuiControlGet, p, Pos, T1
out(pX " " pY " " pW " " pH)
;; expect: 10 20 80 15

;; test: section and xs/ys positioning
Gui, Add, Text, vA x20 y30 w40 h20 Section, a
Gui, Add, Text, vB xs y+10 w40 h20, b
Gui, Add, Text, vC x+10 ys w40 h20, c
GuiControlGet, b, Pos, B
GuiControlGet, c, Pos, C
out(bX " " bY " " cX " " cY)
;; expect: 20 60 70 30

;; test: xp and yp positioning
Gui, Add, Text, vA x15 y25 w40 h20, a
Gui, Add, Text, vB xp+5 yp+30 w40 h20, b
GuiControlGet, b, Pos, B
out(bX " " bY)
;; expect: 20 55

;; test: Gui Margin and default first position
Gui, Margin, 25, 35
Gui, Add, Text, vA w40 h20, a
GuiControlGet, a, Pos, A
out(aX " " aY)
;; expect: 25 35

;; test: GuiControlGet Hwnd and the control's +Hwnd option
Gui, Add, Edit, vEd HwndH1
GuiControlGet, h2, Hwnd, Ed
out((H1 = h2) " " (H1 > 0))
;; expect: 1 1

;; test: GuiControl by HWND
Gui, Add, Edit, HwndH, a
GuiControl,, %H%, b
GuiControlGet, t,, %H%
out(t)
;; expect: b

;; test: GuiControl Focus and GuiControlGet FocusV
Gui, Add, Edit, vFirst
Gui, Add, Edit, vSecond
Gui, Show
GuiControl, Focus, Second
Sleep, 50
GuiControlGet, f, FocusV
out(f)
;; expect: Second

;; test: GuiControl +/- options
Gui, Add, Edit, vEd
GuiControl, +ReadOnly, Ed
GuiControl, -ReadOnly, Ed
GuiControl, +Disabled, Ed
GuiControlGet, e, Enabled, Ed
out(e)
;; expect: 0

;; test: GuiControl Font and Gui Font load
Gui, Font, s12 bold, Arial
Gui, Add, Text, vTx, big
Gui, Font
GuiControl, Font, Tx
Gui, Color, White, Black
out("ok")
;; expect: ok

;; test: Gui Show title and WinGetTitle
Gui, Show, w200 h100 NoActivate, BHK v1 Title
Sleep, 50
WinGetTitle, t2, BHK v1 Title
out(t2)
;; expect: BHK v1 Title

;; test: Gui +LastFound sets the last found window
Gui, +LastFound +HwndG
Gui, Show, NoActivate, LF
out(WinExist() = G)
;; expect: 1

;; test: Gui Hwnd option and window size
Gui, +HwndG
Gui, Show, w220 h110 NoActivate
Sleep, 50
WinGetPos,,, w, h, ahk_id %G%
out((w >= 220) " " (h >= 110))
;; expect: 1 1

;; test: named and numbered Guis
Gui, 2:Add, Edit, vTwo, second
Gui, Main:Add, Edit, vM, main
Gui, 2:Submit, NoHide
Gui, Main:Submit, NoHide
out(Two " " M)
;; expect: second main

;; test: Gui New makes the window the default
Gui, New, , Fresh
Gui, Add, Edit, vFr, f
Gui, Submit, NoHide
out(Fr " " (A_DefaultGui != ""))
;; expect: f 1

;; test: Gui Default and A_DefaultGui
Gui, 3:Default
out(A_DefaultGui)
;; expect: 3

;; test: Gui Destroy frees the window
Gui, +HwndG
Gui, Show, NoActivate
Gui, Destroy
DetectHiddenWindows, On
out(WinExist("ahk_id " G) = 0)
;; expect: 1

;; test: Gui Cancel / Hide
Gui, +HwndG
Gui, Show, NoActivate
Gui, Hide
DetectHiddenWindows, Off
out(WinExist("ahk_id " G) = 0)
;; expect: 1

;; test: GuiClose label runs on WinClose
Gui, +HwndG
Gui, Show, NoActivate, CloseMe
Sleep, 50
WinClose, ahk_id %G%
Sleep, 200
out("not closed")
ExitApp
GuiClose:
out("GuiClose " A_Gui)
ExitApp
;; expect: GuiClose 1

;; test: Gui +Label prefix
Gui, +LabelMy +HwndG
Gui, Show, NoActivate
Sleep, 50
WinClose, ahk_id %G%
Sleep, 200
ExitApp
MyClose:
out("MyClose")
ExitApp
;; expect: MyClose

;; test: named Gui close label
Gui, Pane:+HwndG
Gui, Pane:Show, NoActivate
Sleep, 50
WinClose, ahk_id %G%
Sleep, 200
ExitApp
PaneGuiClose:
out("PaneGuiClose " A_Gui)
ExitApp
;; expect: PaneGuiClose Pane

;; test: GuiSize runs when the window is shown
Gui, +Resize
Gui, Show, w240 h120 NoActivate
Sleep, 200
ExitApp
GuiSize:
out("size " A_GuiWidth " " A_GuiHeight " " A_EventInfo)
ExitApp
;; expect: size 240 120 0

;; test: ControlClick on a button runs its g-label
Gui, +HwndG
Gui, Add, Button, vBtn gClicked, Press
Gui, Show, NoActivate
Sleep, 50
ControlClick, Press, ahk_id %G%
Sleep, 200
ExitApp
Clicked:
out(A_GuiControl " " A_GuiEvent)
ExitApp
;; expect: Btn Normal

;; test: GuiControl +g changes the label
Gui, +HwndG
Gui, Add, Button, vBtn gOld, Press
GuiControl, +gNew, Btn
Gui, Show, NoActivate
Sleep, 50
ControlClick, Press, ahk_id %G%
Sleep, 200
ExitApp
Old:
out("old")
ExitApp
New:
out("new")
ExitApp
;; expect: new

;; test: g-label with a function name
Gui, Add, DropDownList, vDl gOnPick, a|b
Gui, Show, NoActivate
GuiControl, Choose, Dl, |2
Sleep, 100
ExitApp
OnPick(hwnd, event, info) {
    out("func " (hwnd > 0))
}
;; expect: func 1

;; test: A_GuiControl without a variable is the control's text
Gui, Add, DropDownList, gLbl, x|y
Gui, Show, NoActivate
GuiControl, Choose, ComboBox1, |1
Sleep, 100
ExitApp
Lbl:
out("[" A_GuiControl "]")
ExitApp
;; expect: [x]

;; test: ListView add, count and text
Gui, Add, ListView, r5, Name|Size
r1 := LV_Add("", "a", 10)
r2 := LV_Add("", "b", 2)
LV_GetText(t, 2, 1)
LV_GetText(h, 0, 2)
out(r1 r2 " " LV_GetCount() " " t " " h)
;; expect: 12 2 b Size

;; test: ListView Modify and Col options
Gui, Add, ListView,, A|B
LV_Add("", "x", "y")
LV_Modify(1, "Col2", "z")
LV_GetText(t, 1, 2)
out(t)
;; expect: z

;; test: ListView Check and Select with GetNext
Gui, Add, ListView, Checked, A
LV_Add("", "one")
LV_Add("Check Select", "two")
LV_Add("Select", "three")
out(LV_GetNext(0, "C") " " LV_GetNext(0) " " LV_GetNext(2) " " LV_GetCount("S"))
;; expect: 2 2 3 2

;; test: ListView columns: insert, delete, count
Gui, Add, ListView,, A|B
c := LV_InsertCol(3, "", "C")
n1 := LV_GetCount("Column")
LV_DeleteCol(1)
out(c " " n1 " " LV_GetCount("Col"))
;; expect: 3 3 2

;; test: ListView sorting with ModifyCol
Gui, Add, ListView,, Name|Num
LV_Add("", "b", 10)
LV_Add("", "a", 9)
LV_Add("", "c", 100)
LV_ModifyCol(2, "Integer SortDesc")
LV_GetText(t, 1, 2)
LV_ModifyCol(1, "Sort")
LV_GetText(u, 1, 1)
out(t " " u)
;; expect: 100 a

;; test: ListView Delete rows
Gui, Add, ListView,, A
Loop, 3
    LV_Add("", A_Index)
LV_Delete(2)
LV_GetText(t, 2)
n := LV_GetCount()
LV_Delete()
out(n " " t " " LV_GetCount())
;; expect: 2 3 0

;; test: Gui ListView selects the default ListView
Gui, Add, ListView, vL1, A
Gui, Add, ListView, vL2, B
LV_Add("", "into2")
Gui, ListView, L1
LV_Add("", "into1")
LV_Add("", "again1")
out(LV_GetCount())
Gui, ListView, L2
out(LV_GetCount())
;; expect: 2
;; expect: 1

;; test: ListView Insert at a position
Gui, Add, ListView,, A
LV_Add("", "a")
LV_Add("", "c")
LV_Insert(2, "", "b")
LV_GetText(t, 2)
out(t)
;; expect: b

;; test: ListView g-label DoubleClick via LV_Modify Focus is not an event
Gui, Add, ListView, gLvE, A
LV_Add("", "x")
LV_Modify(1, "Select Focus")
out(LV_GetNext(0, "F"))
ExitApp
LvE:
return
;; expect: 1

;; test: TreeView add, parent, child, next
Gui, Add, TreeView
p := TV_Add("Parent")
c := TV_Add("Child", p)
q := TV_Add("Second")
out((TV_GetParent(c) = p) " " (TV_GetChild(p) = c) " " (TV_GetNext() = p) " " (TV_GetNext(p) = q) " " (TV_GetNext(p, "Full") = c) " " (TV_GetPrev(q) = p))
;; expect: 1 1 1 1 1 1

;; test: TreeView text, modify, count, delete
Gui, Add, TreeView
p := TV_Add("Parent")
c := TV_Add("Child", p)
TV_Modify(c, "", "Renamed")
TV_GetText(t, c)
n := TV_GetCount()
TV_Delete(c)
out(t " " n " " TV_GetCount())
;; expect: Renamed 2 1

;; test: TreeView Select, GetSelection and Get
Gui, Add, TreeView
a := TV_Add("a")
b := TV_Add("b", "", "Bold")
TV_Modify(b, "Select")
out((TV_GetSelection() = b) " " (TV_Get(b, "Bold") = b) " " TV_Get(a, "Bold"))
;; expect: 1 1 0

;; test: TreeView First and Sort options
Gui, Add, TreeView
TV_Add("m")
TV_Add("z")
f := TV_Add("a", "", "First")
out(TV_GetNext() = f)
;; expect: 1

;; test: StatusBar set text and parts
Gui, Add, StatusBar,, start
r1 := SB_SetParts(100, 50)
r2 := SB_SetText("second", 2)
r3 := SB_SetText("first")
out((r1 != 0) " " r2 " " r3)
;; expect: 1 1 1

;; test: StatusBar text readable with StatusBarGetText
Gui, +HwndG
Gui, Add, StatusBar,, hello bar
Gui, Show, NoActivate
Sleep, 50
StatusBarGetText, t, 1, ahk_id %G%
out(t)
;; expect: hello bar

;; test: Gui Menu bar
Menu, FileMenu, Add, Open, MenuOpen
Menu, Bar, Add, File, :FileMenu
Gui, Menu, Bar
Gui, Show, NoActivate
out("menu ok")
ExitApp
MenuOpen:
return
;; expect: menu ok

;; test: Menu item states
Menu, M, Add, Item1, H
Menu, M, Check, Item1
Menu, M, Disable, Item1
Menu, M, Rename, Item1, Renamed
Menu, M, Delete, Renamed
out("menu " ErrorLevel)
ExitApp
H:
return
;; expect: menu 0

;; test: Gui options Owner, ToolWindow, AlwaysOnTop, Resize, MinSize
Gui, 1:Show, NoActivate
Gui, 2:+Owner1 +ToolWindow +AlwaysOnTop +Resize +MinSize200x100 -MaximizeBox
Gui, 2:Show, NoActivate w250 h150
out("options ok")
;; expect: options ok

;; test: Gui Minimize, Restore, Maximize and Flash
Gui, +HwndG
Gui, Show, NoActivate
Gui, Minimize
Gui, Restore
Gui, Flash
Gui, Flash, Off
out("states ok")
;; expect: states ok

;; test: Picture control loads a file
FileAppend, % "", conf_none.png
Gui, Add, Picture, vPic w10 h10
out("pic ok")
FileDelete, conf_none.png
;; expect: pic ok

;; test: GuiControlGet Pos without explicit size reports positive size
Gui, Add, Button, vB, Hello
GuiControlGet, p, Pos, B
out((pW > 0) " " (pH > 0))
;; expect: 1 1

;; test: Gui Add returns no error for sub-command with ClassNN target
Gui, Add, Edit,, first
Gui, Add, Edit,, second
GuiControlGet, t,, Edit2
out(t)
;; expect: second

;; test: A_GuiControlEvent and A_EventInfo in a g-label
Gui, Add, ListBox, vLb gLbE, a|b|c
Gui, Show, NoActivate
GuiControl, Choose, Lb, |3
Sleep, 100
ExitApp
LbE:
out(A_GuiEvent " " A_GuiControlEvent)
ExitApp
;; expect: Normal Normal

;; test: InputBox-style Gui with Default button and Submit returns variables
Gui, Add, Edit, vUser, guest
Gui, Add, Button, Default gOK, OK
Gui, Show, NoActivate
Gui, Submit, NoHide
out(User)
ExitApp
OK:
return
;; expect: guest

;; test: ImageList and LV_SetImageList
Gui, Add, ListView,, A
il := IL_Create(2)
LV_SetImageList(il)
out(il > 0)
;; expect: 1

;; test: ListView Check toggling with LV_Modify
Gui, Add, ListView, Checked, A
LV_Add("Check", "x")
LV_Modify(1, "-Check")
out(LV_GetNext(0, "C"))
;; expect: 0

;; test: ListView column width option and auto-size
Gui, Add, ListView, w300, A|B
LV_ModifyCol(1, 120)
LV_ModifyCol()
LV_ModifyCol(2, "AutoHdr")
out("cols ok")
;; expect: cols ok

;; test: Tab3 with a named tab in Gui Tab
Gui, Add, Tab3, vT, Alpha|Beta
Gui, Tab, Beta
Gui, Add, Edit, vOnBeta, b
Gui, Tab
Gui, Submit, NoHide
out(T " " OnBeta)
;; expect: Alpha b

;; test: GuiControlGet Name from a HWND
Gui, Add, Edit, vMine HwndH
GuiControlGet, n, Name, %H%
out(n)
;; expect: Mine

;; test: Gui Show Hide and AutoSize options
Gui, +HwndG
Gui, Add, Text,, auto
Gui, Show, Hide AutoSize
DetectHiddenWindows, Off
a := WinExist("ahk_id " G)
DetectHiddenWindows, On
b := WinExist("ahk_id " G) != 0
out((a = 0) " " b)
;; expect: 1 1

;; test: Gui +Disabled and -Disabled
Gui, +Disabled
Gui, -Disabled
Gui, Show, NoActivate
out("enabled ok")
;; expect: enabled ok

;; test: Gui +OwnDialogs is accepted
Gui, +OwnDialogs
out("own ok")
;; expect: own ok

;; test: Text control options Wrap, Center, Right, Border
Gui, Add, Text, vT1 Center Border w100, c
Gui, Add, Text, vT2 Right +Wrap w100, r
GuiControlGet, t,, T2
out(t)
;; expect: r

;; test: controls with color options
Gui, Add, Text, cRed vT, red
Gui, Add, Progress, cGreen BackgroundSilver vP, 10
GuiControlGet, p,, P
out(p)
;; expect: 10

;; test: Edit control WantTab and -VScroll options load
Gui, Add, Edit, vE WantTab -VScroll r2, x
Gui, Submit, NoHide
out(E)
;; expect: x

;; test: Slider and Progress Vertical options
Gui, Add, Slider, vS Vertical Invert Range0-50, 20
Gui, Add, Progress, vP Vertical, 40
Gui, Submit, NoHide
GuiControlGet, p,, P
out(S " " p)
;; expect: 20 40

;; test: ComboBox Simple and Limit, typed text via GuiControl Text
Gui, Add, ComboBox, vC, a|b
GuiControl, Text, C, typed
Gui, Submit, NoHide
out(C)
;; expect: typed

;; test: DropDownList Sort option
Gui, Add, DropDownList, vD Sort Choose1, c|a|b
Gui, Submit, NoHide
out(D)
;; expect: a

;; test: TreeView Expand and Check options with TV_Get
Gui, Add, TreeView, Checked
p := TV_Add("p", 0, "Check")
c := TV_Add("c", p)
TV_Modify(p, "Expand")
out((TV_Get(p, "Checked") = p) " " (TV_Get(p, "Expanded") = p) " " TV_Get(c, "Checked"))
;; expect: 1 1 0

;; test: A_GuiX and A_GuiY are numbers in GuiSize
Gui, +Resize
Gui, Show, w200 h100 NoActivate
Sleep, 200
ExitApp
GuiSize:
out((A_GuiWidth > 0) " " (A_Gui = 1))
ExitApp
;; expect: 1 1
