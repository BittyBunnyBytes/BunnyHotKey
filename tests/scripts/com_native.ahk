; Native COM: real vtables behind ComObjValue/ObjPtr, ComCall by vtable index, ComObjQuery, ComObjFromPtr, and raw
; IDispatch::GetIDsOfNames/Invoke on a script object.
out(s) => FileAppend(s "`n", "*")
d := ComObject("Scripting.Dictionary")
d.Add("a", 1)
p := ComObjValue(d)
out(p > 65536)
ComCall(3, d, "UInt*", &n := 5)                                 ; IDispatch::GetTypeInfoCount
out("tic " n)
q := ComObjQuery(d, "{00020400-0000-0000-C000-000000000046}")   ; IDispatch
out("type " ComObjType(q))
out("addref " ObjAddRef(p))
out("release " ObjRelease(p))
ObjAddRef(p)
d2 := ComObjFromPtr(p)                                          ; our own pointer -> the same object
out("same " (d2 == d) " " d2.Item("a"))

; script objects
o := {x: 42, f: (this, a) => a * 2}
op := ObjPtr(o)
out("objfromptr " (ObjFromPtrAddRef(op) == o))
ObjAddRef(op)
fw := ComObjFromPtr(op)
out("fw " (fw == o))
u := ComObjQuery(op, "{00000000-0000-0000-C000-000000000046}")  ; IUnknown
out("unk " ComObjType(u) " " (ComObjValue(u) == op))
try ComObjQuery(d, "{11111111-0000-0000-C000-000000000046}")
catch OSError as e
    out("err " e.Message)
x := ComObjFromPtr(ComObjValue(ComObjQuery(op, "{00020400-0000-0000-C000-000000000046}")))
out("x " x.x)

; IDispatch by hand: GetIDsOfNames (5) then Invoke (6) with DISPATCH_PROPERTYGET
names := Buffer(8), nm := Buffer(8)
NumPut("Ptr", StrPtr("x"), names)
iid := Buffer(16, 0)
ComCall(5, op, "Ptr", iid, "Ptr", names, "UInt", 1, "UInt", 0, "Ptr", nm)
out("dispid " NumGet(nm, "Int"))
dp := Buffer(24, 0), res := Buffer(24, 0)
ComCall(6, op, "Int", NumGet(nm, "Int"), "Ptr", iid, "UInt", 0, "UShort", 2, "Ptr", dp, "Ptr", res, "Ptr", 0, "Ptr", 0)
out("vt " NumGet(res, "UShort") " val " NumGet(res, 8, "Int"))
