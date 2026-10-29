; Live test: SendMessage to another program's controls through AT-SPI (tests/live/foreign_app.py with
; BHK_FOREIGN_EXTRA=1).  No Send or keyboard input; the app is mapped without taking focus.
; Run: python3 tests/live/run_foreign_messages.py
out(s) => FileAppend(s "`n", "*")
w := "BHK Foreign App"
if !WinWait(w, , 5) {
    out("foreign app not running")
    ExitApp 1
}
buf := Buffer(256)

; ---- WM_ text messages
n := SendMessage(0x0D, 128, buf.Ptr, "Edit1", w)                ; WM_GETTEXT
out("gettext " n " " StrGet(buf) " len " SendMessage(0x0E, 0, 0, "Edit1", w))
n := SendMessage(0x0D, 3, buf.Ptr, "Edit1", w)
out("gettext short " n " " StrGet(buf))
out("settext " SendMessage(0x0C, 0, StrPtr("carrot"), "Edit1", w) " " ControlGetText("Edit1", w))
h := ControlGetHwnd("Edit1", w)
out("by hwnd " SendMessage(0x0E, 0, 0, h) " " DllCall("SendMessage", "Ptr", h, "UInt", 0x0E, "Ptr", 0, "Ptr", 0))

; ---- Edit (EM_)
SendMessage(0xB1, 1, 4, "Edit1", w)                             ; EM_SETSEL "arr"
s := Buffer(4), e := Buffer(4)
SendMessage(0xB0, s.Ptr, e.Ptr, "Edit1", w)
out("getsel " NumGet(s, "UInt") " " NumGet(e, "UInt") " " EditGetSelectedText("Edit1", w))
SendMessage(0xC2, 0, StrPtr("ARR"), "Edit1", w)                 ; EM_REPLACESEL
out("replacesel " ControlGetText("Edit1", w))
out("lines " SendMessage(0xBA, 0, 0, "Edit2", w) " index " SendMessage(0xBB, 1, 0, "Edit2", w) " " SendMessage(0xBB, 2, 0, "Edit2", w) " " SendMessage(0xBB, 5, 0, "Edit2", w))
out("linelength " SendMessage(0xC1, 0, 0, "Edit2", w) " " SendMessage(0xC1, 18, 0, "Edit2", w))
NumPut("UShort", 40, buf)
n := SendMessage(0xC4, 2, buf.Ptr, "Edit2", w)                  ; EM_GETLINE
out("getline " n " " StrGet(buf, n))

; ---- Button (BM_)
out("getcheck " SendMessage(0xF0, 0, 0, "Button1", w))
SendMessage(0xF1, 1, 0, "Button1", w)                           ; BM_SETCHECK
Sleep 100
out("setcheck " SendMessage(0xF0, 0, 0, "Button1", w) " " ControlGetChecked("Button1", w))
SendMessage(0xF5, 0, 0, "Button2", w)                           ; BM_CLICK "Go"
Sleep 200
out("click " ControlGetText("Static2", w))

; ---- ComboBox (CB_)
out("cb count " SendMessage(0x146, 0, 0, "ComboBox1", w) " cur " SendMessage(0x147, 0, 0, "ComboBox1", w))
out("cb text " SendMessage(0x149, 2, 0, "ComboBox1", w) " " SendMessage(0x148, 2, buf.Ptr, "ComboBox1", w) " " StrGet(buf) " " SendMessage(0x149, 9, 0, "ComboBox1", w))
out("cb find " SendMessage(0x14C, -1, StrPtr("gr"), "ComboBox1", w) " " SendMessage(0x158, -1, StrPtr("RED"), "ComboBox1", w) " " SendMessage(0x158, -1, StrPtr("re"), "ComboBox1", w))
out("cb setcursel " SendMessage(0x14E, 2, 0, "ComboBox1", w))
Sleep 200
out("cb now " ControlGetChoice("ComboBox1", w) " " SendMessage(0x147, 0, 0, "ComboBox1", w))
out("cb selectstring " SendMessage(0x14D, -1, StrPtr("r"), "ComboBox1", w))
Sleep 200
out("cb now " ControlGetChoice("ComboBox1", w))

; ---- ListBox (LB_)
out("lb count " SendMessage(0x18B, 0, 0, "ListBox1", w) " text " SendMessage(0x189, 1, buf.Ptr, "ListBox1", w) " " StrGet(buf) " len " SendMessage(0x18A, 2, 0, "ListBox1", w))
out("lb find " SendMessage(0x18F, -1, StrPtr("ch"), "ListBox1", w) " " SendMessage(0x1A2, -1, StrPtr("x"), "ListBox1", w))
out("lb setcursel " SendMessage(0x186, 1, 0, "ListBox1", w))
Sleep 100
out("lb cur " SendMessage(0x188, 0, 0, "ListBox1", w))
out("lb selectstring " SendMessage(0x18C, -1, StrPtr("che"), "ListBox1", w))
Sleep 100
out("lb cur " SendMessage(0x188, 0, 0, "ListBox1", w))

; ---- Slider, Progress, spin button (Value)
out("tbm " SendMessage(0x400, 0, 0, "msctls_trackbar321", w) " " SendMessage(0x401, 0, 0, "msctls_trackbar321", w) " " SendMessage(0x402, 0, 0, "msctls_trackbar321", w))
SendMessage(0x405, 1, 65, "msctls_trackbar321", w)
out("tbm setpos " SendMessage(0x400, 0, 0, "msctls_trackbar321", w))
out("pbm " SendMessage(0x408, 0, 0, "msctls_progress321", w))
out("udm " SendMessage(0x472, 0, 0, "Edit3", w) " setpos " SendMessage(0x471, 0, 12, "Edit3", w) " " SendMessage(0x472, 0, 0, "Edit3", w) " clamp " SendMessage(0x471, 0, 99, "Edit3", w) " " SendMessage(0x472, 0, 0, "Edit3", w))

; ---- Tab (TCM_)
out("tcm " SendMessage(0x1304, 0, 0, "SysTabControl321", w) " cur " SendMessage(0x130B, 0, 0, "SysTabControl321", w) " set " SendMessage(0x130C, 2, 0, "SysTabControl321", w))
Sleep 100
out("tcm cur " SendMessage(0x130B, 0, 0, "SysTabControl321", w) " bad " SendMessage(0x130C, 7, 0, "SysTabControl321", w))

; ---- ListView (LVM_, through Table)
out("lvm " SendMessage(0x1004, 0, 0, "SysListView321", w) " sel " SendMessage(0x1032, 0, 0, "SysListView321", w) " next " SendMessage(0x100C, -1, 2, "SysListView321", w) " " SendMessage(0x100C, 1, 2, "SysListView321", w) " all " SendMessage(0x100C, 0, 0, "SysListView321", w) " " SendMessage(0x100C, 1, 0, "SysListView321", w))

; ---- unsupported messages return 0
out("unknown " SendMessage(0x1234, 1, 2, "Edit1", w) " " SendMessage(0xCF, 1, 0, "Edit1", w) " " SendMessage(0x0D, 128, buf.Ptr, "Menu1", w))
out("done")
