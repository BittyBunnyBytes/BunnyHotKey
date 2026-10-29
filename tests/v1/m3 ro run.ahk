XButton1::  ; Back mouse button as Shift
SetMouseDelay, -1
CoordMode, Mouse, Screen
MouseGetPos, mx, my
Send {Blind}{LShift Down}
KeyWait, XButton1
Send {Blind}{LShift Up}
MouseMove, %mx%, %my%, 0, R  ; Snap cursor back
return   
