out(s) => FileAppend(s "`n", "*")
; Scripting.Dictionary
d := ComObject("Scripting.Dictionary")
d.Add("apple", 1), d.Add("Banana", 2)
d["cherry"] := 3
d.Item["apple"] := 10
out("dict " d.Count " " d.Item["apple"] " " d("Banana") " " d.Exists("cherry") " " d.Exists("nope") " " Type(d))
keys := ""
for k in d
    keys .= k ","
out("keys " keys " " d.Keys().MaxIndex())
try d.Add("apple", 5)
catch OSError as e
    out("dup " (InStr(e.Message, "800A01C9") > 0))
d.Remove("Banana"), d.CompareMode
d2 := ComObject("Scripting.Dictionary")
d2.CompareMode := 1
d2.Add("Key", 1)
out("textmode " d2.Exists("KEY"))
; WScript.Shell
sh := ComObject("WScript.Shell")
ex := sh.Exec("echo hello from exec")
out("exec [" Trim(ex.StdOut.ReadAll(), "`n") "] status " (ex.Status = 0 || ex.Status = 1))
out("run " sh.Run("true", 0, true) " " sh.Run("false", 0, true))
out("env " (sh.ExpandEnvironmentStrings("%USERNAME%") = EnvGet("USER")) " " sh.ExpandEnvironmentStrings("%NOPE_X%"))
; FileSystemObject + TextStream
fso := ComObject("Scripting.FileSystemObject")
p := A_Temp "\bhk_com_test.txt"
ts := fso.CreateTextFile(p, true)
ts.WriteLine("line one"), ts.Write("line two"), ts.Close()
out("fso " fso.FileExists(p) " " fso.GetFileName(p) " " fso.GetExtensionName(p) " " fso.GetBaseName(p) " " fso.GetFile(p).Size)
ts := fso.OpenTextFile(p)
out("read [" ts.ReadLine() "] [" ts.ReadLine() "] eof " ts.AtEndOfStream)
ts.Close()
; ADODB.Stream (UTF-8 with BOM, as ADODB writes it)
st := ComObject("ADODB.Stream")
st.Type := 2, st.Charset := "utf-8", st.Open()
st.WriteText("héllo")
st.SaveToFile(p, 2), st.Close()
out("adodb " FileGetSize(p) " [" FileRead(p, "UTF-8") "]")
fso.DeleteFile(p)
out("deleted " fso.FileExists(p))
; ComObjArray / ComValue / ComObjType
arr := ComObjArray(0xC, 3)
arr[0] := "a", arr[2] := "c"
s := ""
for v in arr
    s .= "[" v "]"
out("safearray " arr.MaxIndex() " " s " vt=" Format("0x{:X}", ComObjType(arr)))
cv := ComValue(0xB, -1)
out("comvalue " ComObjType(cv) " " ComObjValue(cv) " dispatch " ComObjType(d) " " ComObjType(d, "name"))
; WMI
wmi := ComObjGet("winmgmts:")
n := 0
for proc in wmi.ExecQuery("Select * from Win32_Process where ProcessId = " ProcessExist())
    n++, me := proc.Name
out("wmi " n " " (me != "") " os " (wmi.ExecQuery("Select Caption from Win32_OperatingSystem").Count = 1))
; errors as in AutoHotkey
try ComObject("No.Such.Class")
catch OSError as e
    out("badclass " (InStr(e.Message, "800401F3") > 0))
try ComCall(1, 0)
catch Error
    out("comcall windows-only")
