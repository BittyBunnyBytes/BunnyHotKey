; Win32 control messages sent to this script's own Gui controls (needs a display, like gui_controls.ahk)
out(s) => FileAppend(s "`n", "*")
DetectHiddenWindows true
g := Gui(, "BHK ctlmsg")

; ---- Edit
ed := g.AddEdit("w200 r3 Multi", "alpha`nbravo charlie`ndelta")
SendMessage(0xB1, 6, 11, ed)                                    ; EM_SETSEL "bravo"
s := Buffer(4), e := Buffer(4)
r := SendMessage(0xB0, s.Ptr, e.Ptr, ed)                        ; EM_GETSEL
out("getsel " NumGet(s, "UInt") " " NumGet(e, "UInt") " " (r = (6 | 11 << 16)) " " EditGetSelectedText(ed))
SendMessage(0xC2, 0, StrPtr("BRAVO"), ed)                       ; EM_REPLACESEL
out("replacesel " StrReplace(ed.Value, "`n", "|"))
out("lineindex " SendMessage(0xBB, 0, 0, ed) " " SendMessage(0xBB, 1, 0, ed) " " SendMessage(0xBB, 2, 0, ed) " " SendMessage(0xBB, 9, 0, ed))
out("linelength " SendMessage(0xC1, 0, 0, ed) " " SendMessage(0xC1, 8, 0, ed) " " SendMessage(0xC1, 99, 0, ed))
out("linefromchar " SendMessage(0xC9, 0, 0, ed) " " SendMessage(0xC9, 7, 0, ed) " " SendMessage(0xC9, 21, 0, ed))
lb := Buffer(64)
NumPut("UShort", 30, lb)
n := SendMessage(0xC4, 1, lb.Ptr, ed)                           ; EM_GETLINE
out("getline " n " " StrGet(lb, n))
SendMessage(0xB1, 0, -1, ed)                                    ; select all
out("selectall " StrLen(EditGetSelectedText(ed)))
SendMessage(0xB1, -1, 0, ed)                                    ; deselect
out("deselect [" EditGetSelectedText(ed) "]")
out("readonly " SendMessage(0xCF, 1, 0, ed) " " ((ControlGetStyle(ed) & 0x800) != 0))
SendMessage(0xCF, 0, 0, ed)
SendMessage(0xC5, 10, 0, ed)
out("limit " SendMessage(0xD5, 0, 0, ed) " canundo " SendMessage(0xC6, 0, 0, ed) " scroll " SendMessage(0xB7, 0, 0, ed) " first " SendMessage(0xCE, 0, 0, ed))
cue := Buffer(64)
out("cue " SendMessage(0x1501, 0, StrPtr("type here"), ed) " " SendMessage(0x1502, cue.Ptr, 32, ed) " " StrGet(cue))
tb := Buffer(64)
n := SendMessage(0x0D, 6, tb.Ptr, ed)                           ; WM_GETTEXT with room for 5 chars
out("gettext " n " " StrGet(tb))
out("redraw " SendMessage(0x0B, 0, 0, ed))

; ---- ListBox
lst := g.AddListBox("r5 Multi", ["Red", "Green", "Blue"])
out("lb add " SendMessage(0x180, 0, StrPtr("Cyan"), lst) " insert " SendMessage(0x181, 1, StrPtr("Lime"), lst) " count " SendMessage(0x18B, 0, 0, lst))
out("lb items " ControlGetItems(lst)[2] " " ControlGetItems(lst)[5])
out("lb text " SendMessage(0x18A, 3, 0, lst) " " SendMessage(0x189, 3, tb.Ptr, lst) " " StrGet(tb) " " SendMessage(0x18A, 9, 0, lst))
out("lb find " SendMessage(0x18F, -1, StrPtr("gr"), lst) " " SendMessage(0x18F, 2, StrPtr("r"), lst) " " SendMessage(0x1A2, -1, StrPtr("blue"), lst) " " SendMessage(0x1A2, -1, StrPtr("blu"), lst))
SendMessage(0x185, 1, 0, lst)                                   ; LB_SETSEL item 0
SendMessage(0x185, 1, 3, lst)
out("lb sel " SendMessage(0x187, 0, 0, lst) " " SendMessage(0x187, 1, 0, lst) " " SendMessage(0x187, 3, 0, lst) " count " SendMessage(0x190, 0, 0, lst))
arr := Buffer(16, 0xFF)
n := SendMessage(0x191, 4, arr.Ptr, lst)
out("lb selitems " n " " NumGet(arr, 0, "Int") " " NumGet(arr, 4, "Int"))
SendMessage(0x185, 0, -1, lst)
out("lb unselall " SendMessage(0x190, 0, 0, lst) " selstring-multi " SendMessage(0x18C, -1, StrPtr("Blue"), lst))
out("lb delete " SendMessage(0x182, 0, 0, lst) " " SendMessage(0x182, 99, 0, lst) " top " SendMessage(0x18E, 0, 0, lst) " " SendMessage(0x197, 0, 0, lst))
SendMessage(0x184, 0, 0, lst)
out("lb reset " SendMessage(0x18B, 0, 0, lst) " " SendMessage(0x18F, -1, StrPtr("x"), lst))
single := g.AddListBox("r3", ["one", "two", "three"])
out("lb single " SendMessage(0x18C, -1, StrPtr("tw"), single) " " single.Value " getselcount " SendMessage(0x190, 0, 0, single))

; ---- ComboBox / DDL
dd := g.AddDropDownList(, ["Apple", "Banana"])
out("cb add " SendMessage(0x143, 0, StrPtr("Cherry"), dd) " insert " SendMessage(0x14A, 0, StrPtr("Avocado"), dd) " count " SendMessage(0x146, 0, 0, dd))
out("cb text " SendMessage(0x149, 2, 0, dd) " " SendMessage(0x148, 2, tb.Ptr, dd) " " StrGet(tb) " " SendMessage(0x149, 7, 0, dd))
out("cb find " SendMessage(0x14C, -1, StrPtr("a"), dd) " " SendMessage(0x14C, 0, StrPtr("a"), dd) " " SendMessage(0x158, -1, StrPtr("CHERRY"), dd))
out("cb select " SendMessage(0x14D, -1, StrPtr("ban"), dd) " " dd.Text " " SendMessage(0x147, 0, 0, dd))
out("cb delete " SendMessage(0x144, 0, 0, dd) " dropped " SendMessage(0x157, 0, 0, dd))
cbx := g.AddComboBox(, ["x1", "x2"])
SendMessage(0x14B, 0, 0, cbx)
out("cb reset " SendMessage(0x146, 0, 0, cbx))

; ---- Progress / Slider / UpDown
pr := g.AddProgress("w100 h10", 20)
out("pbm " SendMessage(0x408, 0, 0, pr) " setpos " SendMessage(0x402, 50, 0, pr) " " pr.Value " delta " SendMessage(0x403, 5, 0, pr) " " pr.Value)
out("pbm range " SendMessage(0x401, 0, 0 | 200 << 16, pr) " " SendMessage(0x407, 0, 0, pr) " " SendMessage(0x407, 1, 0, pr) " " SendMessage(0x406, 10, 50, pr) " " pr.Value)
SendMessage(0x404, 30, 0, pr)                                   ; PBM_SETSTEP
out("pbm step " SendMessage(0x405, 0, 0, pr) " " pr.Value " " SendMessage(0x405, 0, 0, pr) " " pr.Value)
sl := g.AddSlider("Range0-10", 3)
out("tbm " SendMessage(0x400, 0, 0, sl) " " SendMessage(0x401, 0, 0, sl) " " SendMessage(0x402, 0, 0, sl))
SendMessage(0x406, 1, 5 | 50 << 16, sl)
SendMessage(0x405, 1, 40, sl)
out("tbm " SendMessage(0x400, 0, 0, sl) " " SendMessage(0x401, 0, 0, sl) " " SendMessage(0x402, 0, 0, sl) " " sl.Value)
SendMessage(0x405, 1, 99, sl)
out("tbm clamp " sl.Value)
ue := g.AddEdit("w50", "4")
ud := g.AddUpDown("Range1-9", 4)
out("udm " SendMessage(0x472, 0, 0, ud) " setpos " SendMessage(0x471, 0, 7, ud) " " ud.Value)
SendMessage(0x46F, -5, 5, ud)
lo := Buffer(4), hi := Buffer(4)
SendMessage(0x470, lo.Ptr, hi.Ptr, ud)
out("udm range " NumGet(lo, "Int") " " NumGet(hi, "Int") " " ud.Value)

; ---- Hotkey
hk := g.AddHotkey(, "^!c")
out("hkm " Format("0x{:X}", SendMessage(0x402, 0, 0, hk)))
SendMessage(0x401, 0x74 | (1 << 8), 0, hk)                      ; Shift+F5
out("hkm " hk.Value " " Format("0x{:X}", SendMessage(0x402, 0, 0, hk)))

; ---- ListView
lv := g.AddListView("r4 w200", ["Name", "Size"])
for v in ["one", "two", "three", "four"]
    lv.Add(, v, A_Index)
lv.Modify(2, "Select")
lv.Modify(4, "Select")
out("lvm count " SendMessage(0x1004, 0, 0, lv) " sel " SendMessage(0x1032, 0, 0, lv))
out("lvm next " SendMessage(0x100C, -1, 2, lv) " " SendMessage(0x100C, 1, 2, lv) " " SendMessage(0x100C, 3, 2, lv) " all " SendMessage(0x100C, 1, 0, lv) " " SendMessage(0x100C, 3, 0, lv))
SendMessage(0x101E, 0, 120, lv)
out("lvm colwidth " SendMessage(0x101D, 0, 0, lv) " bad " SendMessage(0x101D, 7, 0, lv) " visible " SendMessage(0x1013, 3, 0, lv))
out("lvm delete " SendMessage(0x1008, 0, 0, lv) " " lv.GetText(1) " " SendMessage(0x1008, 9, 0, lv) " all " SendMessage(0x1009, 0, 0, lv) " " lv.GetCount())

; ---- TreeView
tv := g.AddTreeView("r5")
a := tv.Add("Animals"), b := tv.Add("Bunny", a), c := tv.Add("Cat", a), p := tv.Add("Plants")
out("tvm count " SendMessage(0x1105, 0, 0, tv) " root " (SendMessage(0x110A, 0, 0, tv) = a) " child " (SendMessage(0x110A, 4, a, tv) = b) " next " (SendMessage(0x110A, 1, b, tv) = c) " parent " (SendMessage(0x110A, 3, c, tv) = a) " prev " (SendMessage(0x110A, 2, c, tv) = b))
out("tvm select " SendMessage(0x110B, 9, c, tv) " " (tv.GetSelection() = c) " caret " (SendMessage(0x110A, 9, 0, tv) = c))
out("tvm expand " SendMessage(0x1102, 2, a, tv) " " (tv.Get(a, "Expand") = a) " collapse " SendMessage(0x1102, 1, a, tv) " " tv.Get(a, "Expand"))
out("tvm delete " SendMessage(0x1101, 0, a, tv) " " SendMessage(0x1105, 0, 0, tv) " all " SendMessage(0x1101, 0, -0x10000, tv) " " SendMessage(0x1105, 0, 0, tv))

; ---- StatusBar
sb := g.AddStatusBar(, "Ready")
edges := Buffer(12)
NumPut("Int", 100, "Int", 200, "Int", -1, edges)
out("sb parts " SendMessage(0x404, 3, edges.Ptr, sb))
out("sb settext " SendMessage(0x40B, 1, StrPtr("middle"), sb) " " SendMessage(0x40B, 9, StrPtr("x"), sb))
r := SendMessage(0x40D, 1, tb.Ptr, sb)
out("sb gettext " (r & 0xFFFF) " " StrGet(tb) " " StatusBarGetText(2, g))
got := Buffer(12, 0)
out("sb getparts " SendMessage(0x406, 3, got.Ptr, sb) " " NumGet(got, 0, "Int") " " NumGet(got, 4, "Int") " " NumGet(got, 8, "Int"))

g.Destroy()
out("done")
