out(s) => FileAppend(s "`n", "*")
dir := A_Temp "\bhk-test-" A_TickCount
DirCreate dir
FileAppend "line1`nline2`n", dir "\a.txt"
out(FileRead(dir "\a.txt") = "line1`nline2`n")
Loop Read, dir "\a.txt"
    out(A_Index ":" A_LoopReadLine)
IniWrite "v1", dir "\c.ini", "Sec", "k1"
IniWrite "v2", dir "\c.ini", "Sec", "k2"
out(IniRead(dir "\c.ini", "Sec", "k2") " " IniRead(dir "\c.ini", "Sec", "nope", "dflt"))
FileCopy dir "\a.txt", dir "\b.txt"
n := 0
Loop Files, dir "\*.txt"
    n++
out("txt files: " n)
SplitPath dir "\a.txt", &name, , &ext, &noext
out(name " " ext " " noext)
out(FileExist(dir "\a.txt") != "" ? "exists" : "missing")
f := FileOpen(dir "\d.txt", "w")
f.WriteLine("hello")
f.Close()
f := FileOpen(dir "\d.txt", "r")
out(f.ReadLine() " " f.AtEOF)
f.Close()
DirDelete dir, true
out(DirExist(dir) = "" ? "cleaned" : "left")
