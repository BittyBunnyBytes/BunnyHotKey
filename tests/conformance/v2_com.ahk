;; suite: v2 serial
; AutoHotkey v2.0 COM (tools/conformance.py): the COM built-ins, BHK's emulated servers, and COM
; servers that ship with every Windows install. Servers BHK lacks fail here and count against the row.

;; test: Scripting.Dictionary
d := ComObject("Scripting.Dictionary")
d.Add("k", "v")
d["n"] := 5
out(d.Item("k") " " d.Count " " d.Exists("n") " " d.Exists("zz"))
;; expect: v 2 -1 0

;; test: Dictionary keys enumeration
d := ComObject("Scripting.Dictionary")
d.Add("a", 1), d.Add("b", 2)
s := ""
for k in d
    s .= k
out(s)
;; expect: ab

;; test: WScript.Shell Exec and environment
sh := ComObject("WScript.Shell")
ex := sh.Exec("echo hi")
out(Trim(ex.StdOut.ReadAll(), "`r`n") " " (sh.ExpandEnvironmentStrings("%HOME%") != "%HOME%"))
;; expect: hi 1

;; test: WScript.Shell Run waits for exit code
sh := ComObject("WScript.Shell")
out(sh.Run('sh -c "exit 4"', 0, true))
;; expect: 4

;; test: Scripting.FileSystemObject
fso := ComObject("Scripting.FileSystemObject")
f := fso.CreateTextFile(A_WorkingDir "\fso.txt", true)
f.WriteLine("fso line")
f.Close()
t := fso.OpenTextFile(A_WorkingDir "\fso.txt").ReadLine()
out(t " " fso.FileExists(A_WorkingDir "\fso.txt") " " fso.GetFileName("a\b\c.txt"))
;; expect: fso line -1 c.txt

;; test: ADODB.Stream reads text with a charset
FileAppend("äb", "s.txt", "UTF-8-RAW")
st := ComObject("ADODB.Stream")
st.Type := 2, st.Charset := "utf-8"
st.Open()
st.LoadFromFile(A_WorkingDir "\s.txt")
out(st.ReadText())
st.Close()
;; expect: äb

;; test: WinHttp.WinHttpRequest to a local server
FileAppend("winhttp ok", "w.txt")
Run('python3 -m http.server 8766 --bind 127.0.0.1', A_WorkingDir, "Hide", &pid)
Sleep(1500)
r := ComObject("WinHttp.WinHttpRequest.5.1")
r.Open("GET", "http://127.0.0.1:8766/w.txt", false)
r.Send()
ProcessClose(pid)
out(r.Status " " r.ResponseText)
;; expect: 200 winhttp ok

;; test: MSXML2.XMLHTTP to a local server
FileAppend("xmlhttp ok", "x.txt")
Run('python3 -m http.server 8767 --bind 127.0.0.1', A_WorkingDir, "Hide", &pid)
Sleep(1500)
r := ComObject("MSXML2.XMLHTTP")
r.open("GET", "http://127.0.0.1:8767/x.txt", false)
r.send()
ProcessClose(pid)
out(r.status " " r.responseText)
;; expect: 200 xmlhttp ok

;; test: Shell.Application NameSpace
sa := ComObject("Shell.Application")
FileAppend("", "item.txt")
ns := sa.NameSpace(A_WorkingDir)
out(ns.Items().Count >= 1)
;; expect: 1

;; test: WMI query through ComObjGet
wmi := ComObjGet("winmgmts:")
n := 0
for p in wmi.ExecQuery("SELECT * FROM Win32_Process WHERE ProcessId = " ProcessExist())
    n++
out(n)
;; expect: 1

;; test: ComObjActive and the running object table
d := ComObject("Scripting.Dictionary")
try
    o := ComObjActive("BHK.NotRegistered.Object")
catch Error
    o := "none"
out(o)
;; expect: none

;; test: ComObjType, ComObjValue, ComObjFlags
d := ComObject("Scripting.Dictionary")
out(ComObjType(d) " " (ComObjValue(d) != 0) " " IsInteger(ComObjFlags(d)) " " ComObjType(d, "Class"))
;; expect: 9 1 1 Dictionary

;; test: ComObjQuery for IDispatch
d := ComObject("Scripting.Dictionary")
q := ComObjQuery(d, "{00020400-0000-0000-C000-000000000046}")
out(q.Ptr != 0)
;; expect: 1

;; test: ComValue and ComObjArray
a := ComObjArray(0xC, 3)
a[0] := "x", a[2] := 5
v := ComValue(0xB, -1)
out(a.MaxIndex() " " a[0] a[2] " " ComObjType(v))
;; expect: 2 x5 11

;; test: ComValueRef to a VARIANT
b := Buffer(24, 0)
r := ComValue(0x400C, b.Ptr)
r[] := 42
out(r[])
;; expect: 42

;; test: ComObjConnect attaches and detaches a sink
d := ComObject("Scripting.Dictionary")
ComObjConnect(d, {})
ComObjConnect(d)
out("ok")
;; expect: ok

;; test: ComCall on IUnknown AddRef/Release
d := ComObject("Scripting.Dictionary")
p := ComObjValue(d)
n := ComCall(1, p, "UInt")
ComCall(2, p, "UInt")
out(n >= 2)
;; expect: 1

;; test: SAPI.SpVoice exists
v := ComObject("SAPI.SpVoice")
out(IsObject(v))
;; expect: 1

;; test: VBScript.RegExp (ships with Windows)
re := ComObject("VBScript.RegExp")
re.Pattern := "\d+"
re.Global := true
m := re.Execute("a1b22")
out(m.Count " " m.Item(1).Value)
;; expect: 2 22

;; test: MSXML2.DOMDocument (ships with Windows)
x := ComObject("MSXML2.DOMDocument.6.0")
x.loadXML("<r><i>v</i></r>")
out(x.selectSingleNode("//i").text)
;; expect: v

;; test: htmlfile document (ships with Windows)
h := ComObject("htmlfile")
h.write("<p id='p'>para</p>")
out(h.getElementById("p").innerText)
;; expect: para

;; test: UIAutomation CUIAutomation (ships with Windows)
u := ComObject("{ff48dba4-60ef-4201-aa87-54103eef594e}", "{30cbe57d-d9d0-452a-ab13-7ac5ac4825ee}")
out(u.Ptr != 0)
;; expect: 1

;; test: WScript.Network (ships with Windows)
n := ComObject("WScript.Network")
out(n.ComputerName != "")
;; expect: 1

;; test: Schedule.Service (ships with Windows)
s := ComObject("Schedule.Service")
s.Connect()
out(s.Connected)
;; expect: -1

;; test: ADODB.Connection (ships with Windows)
c := ComObject("ADODB.Connection")
out(c.State)
;; expect: 0
