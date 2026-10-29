; Live test: Control* on another program's window through AT-SPI (tests/live/foreign_app.py, a plain GTK app).
; Run: python3 tests/live/foreign_app.py &  then  bhk --console tests/live/x11_foreign_controls.ahk
out(s) => FileAppend(s "`n", "*")
w := "BHK Foreign App"
if !WinWait(w, , 5) {
    out("foreign app not running")
    ExitApp 1
}
out("controls " StrReplace(Type(WinGetControls(w)) " " WinGetControls(w).Length, "Array ", ""))
out("classnn " ControlGetClassNN("Go", w) " " ControlGetClassNN("Enable feature", w))
out("text " ControlGetText("Edit1", w) " | " ControlGetText("Static1", w))
ControlSetText("bunny", "Edit1", w)
out("settext " ControlGetText("Edit1", w))
out("checked " ControlGetChecked("Enable feature", w))
ControlSetChecked(1, "Enable feature", w)
Sleep 100
out("checked " ControlGetChecked("Button1", w))
out("combo " ControlGetChoice("ComboBox1", w) " index " ControlGetIndex("ComboBox1", w) " items " ControlGetItems("ComboBox1", w).Length)
out("edit lines " EditGetLineCount("Edit2", w) " [" EditGetLine(2, "Edit2", w) "]")
out("listview " StrReplace(ListViewGetContent("", "SysListView321", w), "`t", ","))
out("lvcount " ListViewGetContent("Count", "SysListView321", w) " col2 " StrReplace(ListViewGetContent("Col2", "SysListView321", w), "`n", "|"))
out("statusbar " StatusBarGetText(1, w))
ControlChooseIndex(3, "ComboBox1", w)
Sleep 200
out("chose " ControlGetChoice("ComboBox1", w) " " ControlChooseString("re", "ComboBox1", w))
Sleep 200
ControlClick("Go", w)
Sleep 200
out("after click " ControlGetText("Static2", w))
MenuSelect(w, , "File", "Reset")
Sleep 200
out("menu " ControlGetText("Static2", w))
out("wintext " (InStr(WinGetText(w), "Enable feature") > 0) " wintext-match " (WinExist(w, "Enable feature") != 0))
ControlGetPos(&x, &y, &cw, &ch, "Edit1", w)
out("pos " (cw > 0 && ch > 0) " enabled " ControlGetEnabled("Edit1", w) " visible " ControlGetVisible("Edit1", w))
h := ControlGetHwnd("Edit1", w)
out("byhwnd " ControlGetText(h))
try ControlGetText("NoSuchThing", w)
catch TargetError
    out("missing -> TargetError")
