#NoEnv  ; Recommended for performance and compatibility with future AutoHotkey releases.
; #Warn  ; Enable warnings to assist with detecting common errors.
SendMode Input  ; Recommended for new scripts due to its superior speed and reliability.
SetWorkingDir %A_ScriptDir%  ; Ensures a consistent starting directory.
#MaxThreadsPerHotkey 3

~c::
MouseTrigger := !MouseTrigger
return

~x::
Toggle := !Toggle
Loop
{
	If(MouseTrigger)
	{
	If (!Toggle)
		Break
	MouseClick, left
		Sleep 31
			MouseClick, left
		Sleep 29
			MouseClick, left
		Sleep 28
			MouseClick, left
		Sleep 32
}
}