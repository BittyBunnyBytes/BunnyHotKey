DetectHiddenWindows true
target := WinWait("receiver.ahk ahk_class AutoHotkey", , 5)
FileAppend("found: " (target != 0) " class=" WinGetClass(target) "`n", "*")
msg := "hello from sender"
cds := Buffer(3 * A_PtrSize)
NumPut("Ptr", 42, "Ptr", (StrLen(msg) + 1) * 2, "Ptr", StrPtr(msg), cds)
reply := SendMessage(0x4A, 0, cds, , target)
FileAppend("reply: " reply "`n", "*")
PostMessage(0x111, 65307, , , target)       ; ID_TRAY_EXIT, like AutoHotkey's tray Exit
