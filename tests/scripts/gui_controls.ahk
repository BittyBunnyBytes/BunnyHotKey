out(s) => FileAppend(s "`n", "*")
DetectHiddenWindows true
g := Gui("+Resize +AlwaysOnTop", "BHK Gui controls")
g.SetFont("s10 bold", "Sans")
g.BackColor := "Teal"
out("back " g.BackColor)

; ---- Tab, controls on pages, UseTab
tab := g.AddTab3("vPage", ["General", "Advanced"])
e1 := g.AddEdit("vNick w120", "bunny")
ud := g.AddUpDown("vCount Range1-20", 5)
tab.UseTab(2)
cb := g.AddCheckBox("vAdv", "Expert mode")
tab.UseTab()
out("tab " tab.Value " " tab.Text " " e1.Visible " " cb.Visible " " (e1.Gui = g))
out("updown " ud.Value " buddy " e1.Value)
ud.Value := 7
out("updown " ud.Value " buddy " e1.Value)

; ---- Hotkey, DateTime, MonthCal
hk := g.AddHotkey("vHK", "^!c")
out("hotkey " hk.Value)
hk.Value := "+F5"
out("hotkey " hk.Value)
dt := g.AddDateTime("vWhen Choose20240229", "yyyy-MM-dd")
out("datetime " dt.Value " " dt.Text)
dt.Value := "20251231"
dt.SetFormat("LongDate")
out("datetime " dt.Value " " dt.Text)
mc := g.AddMonthCal("vDay Choose20240115")
out("monthcal " mc.Value)

; ---- TreeView
tv := g.AddTreeView("vTree r6 Checked")
root := tv.Add("Animals")
bun := tv.Add("Bunny", root, "Check")
cat := tv.Add("Cat", root)
tv.Add("Plants")
out("tv " tv.GetCount() " " tv.GetText(bun) " parent=" (tv.GetParent(bun) = root) " child=" (tv.GetChild(root) = bun)
    " next=" (tv.GetNext(bun) = cat) " checked=" (tv.GetNext(0, "Checked") = bun) " get=" (tv.Get(bun, "Check") = bun))
full := "", id := 0
while id := tv.GetNext(id, "Full")
    full .= tv.GetText(id) " "
out("tv full " full)
tv.Modify(cat, "Select")
out("tv sel " tv.GetText(tv.GetSelection()) " " (tv.Value = cat))
tv.Modify(cat, , "Kitty")
tv.Delete(bun)
out("tv after " tv.GetCount() " " tv.GetText(tv.GetChild(root)))

; ---- ListView columns, sorting, selection, checkboxes
lv := g.AddListView("r5 w300 Checked", ["Name", "Size"])
lv.Add(, "b.txt", "20"), lv.Add("Check", "a.txt", "3"), lv.Add(, "c.txt", "100")
lv.ModifyCol(2, "Integer")
lv.ModifyCol(2, "Sort")
out("lv sorted " lv.GetText(1) " " lv.GetText(2) " " lv.GetText(3))
lv.ModifyCol(1, "SortDesc")
out("lv desc " lv.GetText(1) " " lv.GetText(3))
lv.Modify(2, "Select"), lv.Modify(3, "Select")
out("lv sel " lv.GetCount("S") " " lv.GetNext() " " lv.GetNext(2) " checked=" lv.GetNext(0, "C"))
lv.InsertCol(2, , "Kind")
lv.Modify(1, "Col2", "text")
out("lv cols " lv.GetCount("Col") " " lv.GetText(0, 2) " " lv.GetText(1, 2) " " lv.GetText(1, 3))
lv.DeleteCol(2)
lv.Insert(1, , "z.txt", "1")
out("lv " lv.GetCount() " " lv.GetText(1) " " lv.GetText(1, 2))

; ---- lists
lb := g.AddListBox("vMany Multi r3", ["one", "two", "three"])
lb.Choose(1), lb.Choose(3)
v := lb.Value, t := lb.Text
out("multi " v.Length " " v[1] "," v[2] " " t[2])
dd := g.AddDDL("vDD", ["red", "green", "blue"])
dd.Choose("gr")
out("ddl " dd.Text)
dd.Delete(1)
out("ddl " dd.Value " " dd.Text)
sb := g.AddStatusBar(, "Ready")
sb.SetParts(100)
sb.SetText("Part two", 2)

g.Show()
hwnd := g.Hwnd
title := "ahk_id " hwnd

; ---- Control* on our own window
out("ctrls " WinGetControls(title).Length " first " WinGetControls(title)[1])
out("classnn " ControlGetClassNN(e1) " " ControlGetClassNN(cb) " " ControlGetClassNN(lv))
out("gettext " ControlGetText("Edit1", title))
ControlSetText("carrot", "Edit1", title)
out("settext " e1.Value)
out("checked " ControlGetChecked(cb))
ControlSetChecked(1, cb)
out("checked " ControlGetChecked(cb) " " cb.Value)
out("items " ControlGetItems(dd).Length " index " ControlGetIndex(dd))
out("choose " ControlChooseString("bl", dd) " " dd.Text)
ControlChooseIndex(1, dd)
out("choice " ControlGetChoice(dd) " find " ControlFindItem("blue", dd))
ControlAddItem("cyan", dd)
out("added " ControlGetItems(dd).Length)
ControlDeleteItem(3, dd)
out("deleted " ControlGetItems(dd).Length)
ControlHide(cb)
out("visible " ControlGetVisible(cb) " " cb.Visible)
ControlSetEnabled(0, e1)
out("enabled " ControlGetEnabled(e1) " " e1.Enabled " style " Format("0x{:X}", ControlGetStyle(e1) & 0x08000000))
ControlSetEnabled(-1, e1)
out("enabled " e1.Enabled)
ml := g.AddEdit("r3 w200", "line one`nline two`nline three")
out("edit " EditGetLineCount(ml) " [" EditGetLine(2, ml) "]")
out("lvcontent " StrReplace(ListViewGetContent("Col1", lv), "`n", "|"))
out("lvcount " ListViewGetContent("Count", lv) " sel " ListViewGetContent("Count Selected", lv))
out("statusbar " StatusBarGetText(1, title) " / " StatusBarGetText(2, title))
out("wintext " (InStr(WinGetText(title), "Expert mode") > 0) " exist " (WinExist("BHK Gui controls", "Expert") = hwnd))
try ControlGetText("NoSuchControl", title)
catch TargetError as e
    out("target " e.Message)

; ---- messages
OnMessage(0x5555, (wp, lp, msg, h) => (out("msg " Format("0x{:X}", msg) " " wp " " lp " " (h = hwnd)), 42))
out("send " SendMessage(0x5555, 7, 9, , title))
out("strptr " StrGet(StrPtr("hello")))
SendMessage(0x14E, 1, 0, dd)        ; CB_SETCURSEL
out("cursel " SendMessage(0x147, 0, 0, dd) " " dd.Text)

; ---- MenuBar + MenuSelect
fileMenu := Menu()
fileMenu.Add("&Open", (name, pos, m) => out("menu " name " " pos))
sub := Menu()
sub.Add("Deep", (name, *) => out("menu " name))
fileMenu.Add("More", sub)
bar := MenuBar()
bar.Add("&File", fileMenu)
g.MenuBar := bar
MenuSelect(title, , "File", "Open")
MenuSelect(title, , "File", "More", "Deep")
Sleep 100

; ---- Submit
s := g.Submit(false)
out("submit " s.Page " " s.Nick " " s.Count " " s.HK " " s.When " " s.Day " " s.DD " " s.HasProp("Tree") " " s.Many.Length)
g.Opt("-AlwaysOnTop +ToolWindow")
try g.AddActiveX("w100 h100", "Shell.Explorer")
catch Error as e
    out("activex " (InStr(e.Message, "WebKitGTK") > 0 || InStr(e.Message, "not supported") > 0))
g.Destroy()
out("done")
