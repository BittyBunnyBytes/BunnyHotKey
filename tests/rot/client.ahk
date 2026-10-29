o := ComObjActive("{6B39CAA1-A320-4CB0-8DB4-352AA81E460E}")
FileAppend(o.Hello("bunny") "`n", "*")
o.Add(5), o.Add(7)
FileAppend("total " o.total "`n", "*")
o.total := 100
FileAppend("total " o.total "`n", "*")
FileAppend("cb " o.CallBack((x) => x * 2) "`n", "*")
try o.Nope()
catch Error as e
    FileAppend("err " Type(e) ": " e.Message "`n", "*")
try ComObjActive("{00000000-1111-2222-3333-444444444444}")
catch OSError as e
    FileAppend("missing " e.Message "`n", "*")
