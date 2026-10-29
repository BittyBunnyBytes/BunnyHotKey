Persistent
OnMessage(0x4A, Receive)
Receive(wParam, lParam, msg, hwnd) {
    size := NumGet(lParam, A_PtrSize, "UInt")
    text := StrGet(NumGet(lParam, 2 * A_PtrSize, "Ptr"), size // 2)
    FileAppend("receiver got: " text " (dwData=" NumGet(lParam, 0, "UPtr") ")`n", "*")
    return 1234
}
g := Gui(, "Receiver Gui")
g.Show("Hide")
DetectHiddenWindows true
FileAppend("gui pid matches: " (WinGetPID("ahk_id " g.Hwnd) = ProcessExist()) "`n", "*")
