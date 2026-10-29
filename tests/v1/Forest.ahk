#NoEnv  ; Recommended for performance and compatibility with future AutoHotkey releases.
; #Warn  ; Enable warnings to assist with detecting common errors.
SendMode Input  ; Recommended for new scripts due to its superior speed and reliability.
SetWorkingDir %A_ScriptDir%  ; Ensures a consistent starting directory.
#MaxThreadsPerHotkey 2

XButton1::Shift

P::
Toggle := !Toggle
loop
{
    If not Toggle
        break
    send c
    sleep 50
    send e
    sleep 50
    send e
    sleep 50
}
return