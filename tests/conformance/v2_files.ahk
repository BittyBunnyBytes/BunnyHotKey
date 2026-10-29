;; suite: v2
; AutoHotkey v2.0 files, directories, INI and drives (tools/conformance.py). Runs in a temporary directory.
; Not run here: FileRecycleEmpty (empties the user's Trash), DriveEject/Retract/Lock/Unlock/SetLabel
; (act on hardware), Edit (opens an editor).

;; test: FileAppend, FileRead, FileExist, FileDelete
FileAppend("one`ntwo", "a.txt")
s := FileRead("a.txt")
e := FileExist("a.txt") != ""
FileDelete("a.txt")
out(StrReplace(s, "`n", "|") " " e " [" FileExist("a.txt") "]")
;; expect: one|two 1 []

;; test: FileRead options and RAW buffer
FileAppend("abcdef", "r.txt")
b := FileRead("r.txt", "RAW")
out(FileRead("r.txt", "m3") " " Type(b) " " b.Size)
;; expect: abc Buffer 6

;; test: FileEncoding and FileAppend encodings
FileAppend("é", "u8.txt", "UTF-8-RAW")
FileAppend("é", "u16.txt", "UTF-16-RAW")
FileEncoding("UTF-8")
out(FileGetSize("u8.txt") " " FileGetSize("u16.txt") " " FileRead("u8.txt") " " A_FileEncoding)
;; expect: 2 2 é UTF-8

;; test: FileAppend with a BOM
FileAppend("x", "bom.txt", "UTF-8")
out(FileGetSize("bom.txt"))
;; expect: 4

;; test: FileGetSize units
FileAppend(Format("{:2048}", ""), "big.txt")
out(FileGetSize("big.txt") " " FileGetSize("big.txt", "K"))
;; expect: 2048 2

;; test: FileCopy, overwrite and wildcards
FileAppend("1", "c1.txt")
FileAppend("2", "c2.txt")
FileCopy("c1.txt", "copy.txt")
try
    FileCopy("c2.txt", "copy.txt")
catch Error
    out("exists")
FileCopy("c2.txt", "copy.txt", 1)
DirCreate("sub")
FileCopy("c*.txt", "sub")
n := 0
Loop Files, "sub\*"
    n++
out(FileRead("copy.txt") " " n)
;; expect: exists
;; expect: 2 3

;; test: FileMove and rename
FileAppend("m", "m1.txt")
FileMove("m1.txt", "m2.txt")
out((FileExist("m1.txt") = "") " " FileRead("m2.txt"))
;; expect: 1 m

;; test: DirCreate, DirCopy, DirMove, DirDelete, DirExist
DirCreate("d1\deep")
FileAppend("x", "d1\deep\f.txt")
DirCopy("d1", "d2")
DirMove("d2", "d3")
a := FileRead("d3\deep\f.txt")
try
    DirDelete("d1")
catch Error
    out("not empty")
DirDelete("d1", true)
out(a " " (DirExist("d1") = "") " " InStr(DirExist("d3"), "D") " " (DirExist("d2") = ""))
;; expect: not empty
;; expect: x 1 1 1

;; test: FileGetAttrib and FileSetAttrib
FileAppend("x", "at.txt")
DirCreate("adir")
FileSetAttrib("+R", "at.txt")
r := InStr(FileGetAttrib("at.txt"), "R") > 0
FileSetAttrib("-R", "at.txt")
r2 := InStr(FileGetAttrib("at.txt"), "R") = 0
out(r " " r2 " " InStr(FileGetAttrib("adir"), "D") " " InStr(FileExist("at.txt"), "D"))
;; expect: 1 1 1 0

;; test: FileSetTime and FileGetTime
FileAppend("x", "t.txt")
FileSetTime("20200102030405", "t.txt", "M")
out(FileGetTime("t.txt", "M") " " StrLen(FileGetTime("t.txt", "C")))
;; expect: 20200102030405 14

;; test: FileOpen read/write methods
f := FileOpen("fo.txt", "w", "UTF-8-RAW")
f.WriteLine("line1")
f.Write("rest")
f.WriteUInt(0x41424344)
f.Close()
f := FileOpen("fo.txt", "r", "UTF-8-RAW")
l := f.ReadLine()
r := f.Read(4)
u := f.ReadUInt()
eof := f.AtEOF
len := f.Length
f.Pos := 0
first := f.Read(1)
f.Close()
out(l " " r " " Format("{:X}", u) " " eof " " len " " first)
;; expect: line1 rest 41424344 1 14 l

;; test: FileOpen RawRead and RawWrite
f := FileOpen("raw.bin", "w")
b := Buffer(3)
NumPut("UChar", 1, "UChar", 2, "UChar", 3, b)
f.RawWrite(b)
f.Close()
f := FileOpen("raw.bin", "r")
c := Buffer(3, 0)
n := f.RawRead(c)
f.Close()
out(n " " NumGet(c, 2, "UChar"))
;; expect: 3 3

;; test: FileOpen append and Seek
FileAppend("abc", "ap.txt")
f := FileOpen("ap.txt", "a")
f.Write("d")
f.Close()
f := FileOpen("ap.txt", "r")
f.Seek(-2, 2)
out(f.Read() " " FileRead("ap.txt"))
f.Close()
;; expect: cd abcd

;; test: FileInstall copies in an uncompiled script
FileAppend("src", "inst_src.txt")
FileInstall("inst_src.txt", "inst_dst.txt")
out(FileRead("inst_dst.txt"))
;; expect: src

;; test: FileCreateShortcut and FileGetShortcut
FileAppend("t", "target.txt")
FileCreateShortcut(A_WorkingDir "\target.txt", "link.lnk", A_WorkingDir, "args", "desc")
FileGetShortcut("link.lnk", &tgt, &dir, &args, &desc)
SplitPath(tgt, &name)
out(name " " args " " desc " " (dir = A_WorkingDir))
;; expect: target.txt args desc 1

;; test: FileRecycle moves a file out of place
FileAppend("bin", "conf_recycle_me.txt")
FileRecycle("conf_recycle_me.txt")
out(FileExist("conf_recycle_me.txt") = "")
;; expect: 1

;; test: IniWrite, IniRead and IniDelete
IniWrite("v1", "c.ini", "S", "k1")
IniWrite("v2", "c.ini", "S", "k2")
IniWrite("other", "c.ini", "T", "x")
a := IniRead("c.ini", "S", "k1")
d := IniRead("c.ini", "S", "nope", "dflt")
sec := IniRead("c.ini", "S")
names := IniRead("c.ini")
IniDelete("c.ini", "S", "k1")
try
    IniRead("c.ini", "S", "k1")
catch OSError
    gone := "gone"
IniDelete("c.ini", "T")
out(a " " d " " StrReplace(sec, "`n", ",") " " StrReplace(names, "`n", ",") " " gone " " StrReplace(IniRead("c.ini"), "`n", ","))
;; expect: v1 dflt k1=v1,k2=v2 S,T gone S

;; test: IniWrite a whole section
IniWrite("a=1`nb=2", "s.ini", "Sec")
out(IniRead("s.ini", "Sec", "b"))
;; expect: 2

;; test: SplitPath parts
SplitPath("/tmp/dir/file.tar.gz", &name, &dir, &ext, &noext)
out(name " " dir " " ext " " noext)
;; expect: file.tar.gz /tmp/dir gz file.tar

;; test: SetWorkingDir and A_WorkingDir
old := A_WorkingDir
DirCreate("wd")
SetWorkingDir("wd")
SplitPath(A_WorkingDir, &n)
SetWorkingDir(old)
out(n " " (A_WorkingDir = old))
;; expect: wd 1

;; test: Loop Files with recursion and directory mode
DirCreate("tree\a\b")
FileAppend("", "tree\a\x.txt")
FileAppend("", "tree\a\b\y.txt")
f := 0, d := 0
Loop Files, "tree\*", "R"
    f++
Loop Files, "tree\*", "D R"
    d++
out(f " " d)
;; expect: 2 2

;; test: A_LoopFile variables
DirCreate("lf")
FileAppend("12345", "lf\data.bin")
Loop Files, "lf\*.bin"
    out(A_LoopFileName " " A_LoopFileExt " " A_LoopFileSize " " (A_LoopFileDir = "lf") " " StrLen(A_LoopFileTimeModified))
;; expect: data.bin bin 5 1 14

;; test: DriveGetCapacity, DriveGetSpaceFree, DriveGetType, DriveGetStatus
out((DriveGetCapacity("/") > 0) " " (DriveGetSpaceFree("/") > 0) " " DriveGetType("/") " " DriveGetStatus("/"))
;; expect: 1 1 Fixed Ready

;; test: DriveGetFileSystem, DriveGetSerial, DriveGetLabel, DriveGetList
fs := DriveGetFileSystem("/")
out((fs != "") " " IsInteger(DriveGetSerial("/")) " " (Type(DriveGetLabel("/")) = "String") " " (DriveGetList() != ""))
;; expect: 1 1 1 1

;; test: DriveGetStatusCD without a disc drive
try
    s := DriveGetStatusCD()
catch Error
    s := "error"
out(s != "")
;; expect: 1

;; test: EnvSet, EnvGet and child processes
EnvSet("BHK_CONF_VAR", "fromscript")
RunWait('sh -c "echo $BHK_CONF_VAR > env_out.txt"',, "Hide")
out(EnvGet("BHK_CONF_VAR") " " Trim(FileRead("env_out.txt"), " `r`n"))
;; expect: fromscript fromscript
