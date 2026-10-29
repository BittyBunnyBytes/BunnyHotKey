#NoEnv
#Persistent
out(s) {
    FileAppend, %s%`n, *
}
Gui, Add, Text, Section, Name:
Gui, Add, Edit, vName w150, Bunny
Gui, Add, CheckBox, vAgree Checked, Agree
Gui, Add, DropDownList, vPick, red|green||blue
Gui, Add, ListBox, vList r3 AltSubmit, one|two|three
Gui, Add, Slider, vLevel Range0-10, 4
Gui, Add, Radio, vChoice Checked, A
Gui, Add, Radio,, B
Gui, Add, Button, gPressed vBtn Default, OK
Gui, Add, ListView, r4 w200 vLV, Col A|Col B
Gui, Show, w300, BHK v1 Gui
Gui, Submit, NoHide
out(Name " " Agree " " Pick " " List " " Level " " Choice)
GuiControl,, Name, Hot Key
GuiControl,, Agree, 0
GuiControl, ChooseString, Pick, blue
GuiControl,, Level, +3
GuiControl,, Pick, |x|y||z
GuiControlGet, Name
GuiControlGet, lvl,, Level
GuiControlGet, pk,, Pick
out(Name " " lvl " " pk)
LV_Add("", "a1", "b1")
LV_Add("", "a2", "b2")
LV_Modify(2, "", "A2")
LV_GetText(t, 2, 1)
out(LV_GetCount() " " t)
GuiControlGet, en, Enabled, Name
GuiControl, Disable, Name
GuiControlGet, en2, Enabled, Name
out(en en2)
Menu, MyMenu, Add, First Item, MenuHandler
Menu, MyMenu, Add
Menu, MyMenu, Add, Second, MenuHandler
Menu, Tray, Tip, BHK tip
Gui, Destroy
Gui, 2:New, +HwndH2, Second Window
Gui, 2:Add, Edit, vE2, two
Gui, 2:Submit, NoHide
out(E2 " " (H2 > 0))
Gui, MyGui:Add, Text,, hello
Gui, MyGui:Default
out(A_DefaultGui)
Hotkey, F9, HotLabel
Hotkey, ^F9, HotFunc
SetTimer, Tick, -10
Sleep, 100
out("done")
ExitApp

Pressed:
out("pressed " A_GuiControl)
return

MenuHandler:
out("menu " A_ThisMenuItem)
return

HotLabel:
out("hot")
return

HotFunc() {
}

Tick:
out("tick " A_ThisLabel)
return

GuiClose:
ExitApp
